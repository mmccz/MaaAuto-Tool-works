import time
import subprocess
import os
import datetime
import logging
import vision
import input_driver
from utils import resource_path
from config_manager import CONFIG_DIR, LOG_DIR
from process_utils import (kill_foreground_apps, kill_blacklist_apps,
                           is_process_running,
                           wait_for_process_exit, wait_for_process_start,
                           minimize_process_windows, bring_process_to_front,
                           find_process_window, get_client_rect_screen,
                           visible_ratio,
                           TaskInterrupted, check_interrupt,
                           interruptible_sleep)
from notifier import send_task_report  # <--- import the standalone notification module

logger = logging.getLogger("MaaAuto")


# --------------------------------------------------------------------------- #
# Template-matching settings (all defaulted, so old config files still work)
#
# Background: 1.0.x matched exact sizes full-screen via pyautogui.locateCenterOnScreen,
# so at 125% / 150% scaling the templates were a size small and never found. Now
# vision.find does multi-scale matching in the target client area; tuning lives here.
# --------------------------------------------------------------------------- #
DEFAULT_MATCH_THRESHOLD = 0.80      # correlation-coefficient threshold
DEFAULT_SCALE_MIN = 0.60            # lowest template scale searched (60%)
DEFAULT_SCALE_MAX = 2.00            # highest (200%)
DEFAULT_SCALE_STEP = 0.05
DEFAULT_MATCH_INTERVAL = 1.5        # interval between attempts (seconds)
DEFAULT_VERIFY_DELAY_MS = 900       # wait after clicking before checking whether it took effect
DEFAULT_VERIFY_RETRIES = 1          # extra clicks when the first did nothing (0 = none)

# Below this visible-area ratio the window counts as off-screen: raise at once instead of waiting for the timeout.
MIN_VISIBLE_RATIO = 0.35


class EmulatorStartupFailed(RuntimeError):
    """Emulator failed to start or connect (an environment issue; retrying will not help)."""


class TemplateNotFound(TimeoutError):
    """Template matching timed out: the button may well be on screen, yet no template matches.

    Typically caused by restyling after a MAA / MaaEnd update (new buttons, themes,
    custom backgrounds), or by bundled templates differing too much from the user's
    window size / scaling. Subclasses ``TimeoutError`` so older code that catches
    timeouts keeps working.
    """


class TemplateMissing(FileNotFoundError):
    """The template file itself is missing (user template deleted, bundled resource absent)."""


class TargetWindowNotVisible(RuntimeError):
    """The target window is almost entirely off-screen, so finding and clicking cannot work."""


# Actionable advice after a template-match timeout; it goes into the log and the UI reminder.
TEMPLATE_HINT = (
    "如果按钮明明在屏幕上却一直找不到，通常是 MAA / MaaEnd 更新后界面样式变了"
    "（按钮改版、换主题、自定义背景），或内置模板与当前窗口尺寸 / 缩放比相差太大。\n"
    "处理：打开「设置 → 模板」重新截取对应按钮（用户模板会优先于内置模板）；"
    "也可以先调整窗口大小 / 换回默认主题再试。"
)
OFFSCREEN_HINT = (
    "目标窗口大部分在屏幕外，截图里只有黑边，找图不可能成功。\n"
    "处理：先把 MAA / MaaEnd 窗口移回屏幕内（或恢复 / 最大化）再执行任务。"
)

def _try_restore_window(hwnd):
    """Restore a minimized window once; return True if it really was restored.

    Windows parks minimized windows at -32000, so without restoring first a minimized
    window is misread as "off-screen" and the hint points the user the wrong way.
    """
    try:
        import win32con
        import win32gui
        if hwnd and win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.5)
            return True
    except Exception:
        pass
    return False


# Failure kind of the last task; the UI uses it to pick which hint to show.
# Kept as module state rather than an extra execute_workflow return value, to avoid breaking callers / tests.
_LAST_FAILURE = {"kind": "", "message": ""}

FAILURE_TEMPLATE = "template"
FAILURE_OFFSCREEN = "window_offscreen"


def last_failure():
    """Failure info of the last task, as a copy: ``{"kind": ..., "message": ...}``."""
    return dict(_LAST_FAILURE)


def _set_failure(kind, message=""):
    _LAST_FAILURE["kind"] = kind or ""
    _LAST_FAILURE["message"] = message or ""


def _clear_failure():
    _set_failure("", "")


# --------------------------------------------------------------------------- #
# Click verification
#
# Why: "the click was sent" does not mean "the click landed". If the target is covered
# or never reached the foreground, the click lands on the window above it: the log looks
# fine, the UI does nothing. So compare a small pixel patch around the click before/after.
# --------------------------------------------------------------------------- #
def _patch_region(x, y, half_w=40, half_h=28):
    return (int(x) - half_w, int(y) - half_h, int(x) + half_w, int(y) + half_h)


def _patch_diff(before, after):
    """Mean pixel difference between two patch captures.

    :return: the mean difference, or ``None`` when a capture is missing or the shapes
             differ (lock screen, RDP disconnect, minimized window): undecidable.

    Up to 1.1.0 this returned ``999.0`` (large enough to always exceed the threshold),
    so a failed capture read as "the screen changed" and the log falsely claimed the
    click had taken effect. A missing frame must be able to say so.
    """
    if before is None or after is None or before.shape != after.shape:
        return None
    try:
        import numpy as np
        return float(np.abs(after.astype(np.int16) - before.astype(np.int16)).mean())
    except Exception:
        return None


def _wait_patch_change(region, before, delay_ms, threshold=1.5):
    """Sleep delay_ms, then capture the same patch again.

    :return: ``(changed, diff)`` where changed is True/False, or ``None`` when it cannot
             be decided (diff is None then too).
    """
    time.sleep(max(0, delay_ms) / 1000.0)
    after = vision.grab(region)
    diff = _patch_diff(before, after)
    if diff is None:
        return None, None
    return diff >= threshold, diff


def _resolve_target_window(hwnd, procs, x, y):
    """Resolve the top-level window handle to activate or post to."""
    target = int(hwnd or 0)
    if not target:
        target = int(input_driver.window_at_point(x, y) or 0)
    if not target and procs:
        target = int(find_process_window(procs) or 0)
    return input_driver.root_window(target) if target else 0


def click_match(match, config, procs=None, hwnd=0):
    """Click a match once according to config, and try to confirm the click landed.

    Flow:
      1. position = match center + click offset;
      2. ``click_activate=False`` -> **background post only** (PostMessage): never
         activate and never send a real click, which would hit whatever window is in
         the foreground at that moment (possibly another program);
      3. ``click_mode=postmessage`` -> post to the background directly;
      4. when a real click is needed: bring the window to the foreground first (three-
         level fallback, verified), and only **after** that capture the "before"
         frame - activation itself changes those pixels, so an early capture would
         make the verification meaningless;
      5. foreground failed -> try a background click first (PostMessage ignores window
         stacking and works for Qt apps);
      6. capture failed -> only warn "cannot verify"; no extra click, no claim of success.
    """
    config = config or {}
    offset_x = int(config.get("click_offset_x", 0) or 0)
    offset_y = int(config.get("click_offset_y", 0) or 0)
    cx, cy = match.center
    x, y = cx + offset_x, cy + offset_y

    mode = str(config.get("click_mode", input_driver.CLICK_SENDINPUT)).lower()
    activate = bool(config.get("click_activate", True))
    verify = bool(config.get("click_verify", True))
    delay_ms = int(config.get("click_verify_delay_ms", DEFAULT_VERIFY_DELAY_MS))
    retries = max(0, int(config.get("click_retries", DEFAULT_VERIFY_RETRIES)))

    target = _resolve_target_window(hwnd, procs, x, y)
    patch = _patch_region(x, y)

    def _before_frame():
        """Pixels of this patch; nothing is captured when verification is off."""
        return vision.grab(patch) if verify else None

    # ---- Background click only: foreground activation is off, or postmessage is already the mode ----
    if not activate or mode == input_driver.CLICK_POSTMESSAGE:
        if not activate and mode != input_driver.CLICK_POSTMESSAGE:
            logger.info("已关闭「点击前激活窗口」：本次改用后台点击，"
                        "不移动鼠标、不抢占焦点")
        before = _before_frame()
        if input_driver.click(x, y, mode=input_driver.CLICK_POSTMESSAGE, hwnd=target):
            if not verify:
                logger.info(f"后台点击已投递: ({x}, {y})")
                return True
            changed, diff = _wait_patch_change(patch, before, delay_ms)
            if changed:
                logger.info(f"后台点击生效: ({x}, {y}) 像素差 {diff:.1f}")
                return True
            if changed is None:
                logger.warning(f"后台点击已投递，但截图失败无法校验: ({x}, {y})")
                return True
            logger.warning(f"后台点击未生效（像素差 {diff:.1f}）")
        else:
            logger.warning("后台点击投递失败")

        if not activate:
            logger.error(
                "已关闭「点击前激活窗口」，而后台点击也没投递成功，放弃本次点击；"
                "继续发真实点击会落到当前前台窗口上。可在设置里重新打开该开关。")
            return False

    # ---- Real-click path: activate first, then capture the "before" frame ----
    fg_ok = input_driver.ensure_foreground(target) if target else False
    if target and not fg_ok:
        logger.info("目标窗口未能切到前台，先尝试后台点击（不占用鼠标）")
        before = _before_frame()
        if input_driver.post_click(target, x, y):
            if not verify:
                return True
            changed, diff = _wait_patch_change(patch, before, delay_ms)
            if changed:
                logger.info(f"后台点击生效: ({x}, {y}) 像素差 {diff:.1f}")
                return True
            if changed is None:
                logger.warning(f"后台点击已投递，但截图失败无法校验: ({x}, {y})")
                return True
            logger.warning(f"后台点击未生效（像素差 {diff:.1f}），继续尝试真实点击")

    # Important: `before` must be captured after the activation above (activation changes pixels)
    before = _before_frame()

    attempt = 0
    while True:
        attempt += 1
        ok = input_driver.click(
            x, y,
            mode=input_driver.CLICK_SENDINPUT,
            restore_cursor=bool(config.get("click_restore_cursor", True)),
            move_delay_ms=int(config.get("click_move_delay_ms", 80)),
            hwnd=target)
        if not ok:
            logger.error(f"鼠标点击失败: ({x}, {y})")
            return False

        if not verify:
            logger.info(f"已点击: ({x}, {y})")
            return True

        changed, diff = _wait_patch_change(patch, before, delay_ms)
        if changed:
            logger.info(f"点击生效: ({x}, {y}) 第 {attempt} 次，像素差 {diff:.1f}")
            return True

        if changed is None:
            logger.warning(
                f"点击已发送，但截图失败无法校验: ({x}, {y})"
                "（锁屏、远程桌面断开或目标窗口最小化时会出现）")
            return True

        if attempt > retries:
            logger.warning(
                f"点击已发送但画面无变化（({x}, {y}) 像素差 {diff:.1f}）。"
                f"可能是按钮状态本身不变、目标被遮挡或窗口未激活；继续后续流程。")
            return True

        logger.info(f"点击后画面无变化（像素差 {diff:.1f}），补点第 {attempt + 1} 次")
        input_driver.ensure_foreground(target)



def _launch_program(exe_path, logger):
    """Start an external program (MAA / MaaEnd).

    The config value is usually the absolute path of an .exe and may contain spaces
    (e.g. Program Files). The old `Popen(path, shell=True)` cut the path at the first
    space and failed; here the single-element list (no shell) comes first, and only
    when the path does not exist - meaning the user typed "exe + arguments" as one
    command line - do we fall back to the shell for compatibility.
    """
    if os.path.exists(exe_path):
        return subprocess.Popen([exe_path])
    logger.warning(
        "启动路径不是已存在的文件，按整串命令行交给 shell 处理: %s", exe_path)
    return subprocess.Popen(exe_path, shell=True)


def _user_template_dir(config):
    """User template directory: the configured one, else ``config/templates``."""
    path = (config or {}).get("template_dir", "").strip()
    if path:
        return path
    return os.path.join(CONFIG_DIR, "templates")


def template_paths(image_name, config=None):
    """Candidate template paths: the user directory first, then bundled resources."""
    return vision.template_candidates(
        image_name,
        user_dir=_user_template_dir(config),
        bundled_dir=resource_path("resources"),
    )


# Template -> config key holding the path of the process it belongs to.
# Before "test template" / "capture template" the matching window must be brought to the
# front; otherwise another window (usually MaaAuto) covers it and matching never works.
TEMPLATE_TARGETS = {
    "maa_start.png": "maa_path",
    "maaend_start.png": "maaend_path",
}


def template_process(image_name, config=None):
    """Process name a template belongs to (e.g. ``MAA.exe``); empty for custom templates."""
    key = TEMPLATE_TARGETS.get(str(image_name or "").strip().lower())
    if not key:
        return ""
    path = str((config or {}).get(key) or "").strip()
    if not path:
        return ""
    return os.path.basename(path.replace("/", "\\"))


def _search_region(config, procs):
    """Return (search rect, window handle) according to config.

    ``search_scope = window`` (default): search inside the target's client area only.
        Fast (orders of magnitude less area to scan) and no false hits from look-alikes.
    ``search_scope = screen``: search the whole screen, for when the title bar / border
        covers things or the target draws its buttons in a separate borderless window.
    """
    scope = str((config or {}).get("search_scope", "window")).lower()
    if scope == "screen" or not procs:
        return None, 0

    hwnd = find_process_window(procs)
    rect = get_client_rect_screen(hwnd)
    if not rect:
        return None, 0

    # Allow padding: tolerance for edge-hugging buttons or translucent window borders
    pad = int((config or {}).get("search_padding", 0) or 0)
    if pad:
        rect = (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)
    return rect, hwnd


def _save_failure_screenshot(image_name, region):
    """On a template-match timeout, keep an on-site screenshot so users can report"""
    try:
        img = vision.grab(region)
        if img is None:
            return None
        path = os.path.join(
            LOG_DIR,
            f"find_fail_{os.path.splitext(image_name)[0]}_"
            f"{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
        return path if vision.save_png(img, path) else None
    except Exception as e:
        logger.debug(f"保存现场截图失败: {e}")
        return None


def find_and_click(image_name, config=None, procs=None, timeout=None):
    """Find the target image and click it.

    Compared with 1.0.x's ``pyautogui.locateCenterOnScreen``:
      * multi-scale matching -> still found at 125% / 150% scaling and other resolutions;
      * search limited to the target's client area -> fast, and never clicks elsewhere;
      * user template overrides (``config/templates/``) -> re-capture after a
        resolution change;
      * selectable click mode: real click (default) or background PostMessage click.

    :param image_name: template file name, e.g. ``maa_start.png``
    :param config:     config dict (reads the match_* / click_* settings)
    :param procs:      target process names, used to locate the window and post clicks
    :param timeout:    overrides ``wait_timeout`` from config
    """
    config = config or {}
    procs = procs or []
    if timeout is None:
        timeout = config.get("wait_timeout", 60)

    candidates = template_paths(image_name, config)
    if not candidates:
        logger.error(
            f"【严重错误】找不到图像文件: {image_name} "
            f"（已查 {_user_template_dir(config)} 与内置 resources）")
        raise TemplateMissing(
            f"找不到模板文件: {image_name}\n"
            f"已查找：用户模板目录 {_user_template_dir(config)}、内置 resources。\n"
            f"处理：到「设置 → 模板」重新截取一张，或重新安装以补回内置模板。")

    threshold = float(config.get("match_threshold", DEFAULT_MATCH_THRESHOLD))
    scale_min = float(config.get("match_scale_min", DEFAULT_SCALE_MIN))
    scale_max = float(config.get("match_scale_max", DEFAULT_SCALE_MAX))
    scale_step = float(config.get("match_scale_step", DEFAULT_SCALE_STEP))
    interval = max(0.3, float(config.get("match_interval", DEFAULT_MATCH_INTERVAL)))
    click_mode = str(config.get("click_mode", input_driver.CLICK_SENDINPUT)).lower()
    if not config.get("click_activate", True):
        click_mode += "（不激活窗口，仅后台投递）"

    logger.info(
        f"开始寻找目标按钮: {image_name} (超时 {timeout} 秒, "
        f"阈值 {threshold:.2f}, 尺度 {scale_min:.2f}~{scale_max:.2f}, "
        f"点击方式 {click_mode})")

    start_time = time.time()
    attempt = 0
    last_region = None

    while time.time() - start_time < timeout:
        check_interrupt()
        attempt += 1
        region, hwnd = _search_region(config, procs)
        last_region = region

        if region:
            ratio = visible_ratio(region)
            if ratio < MIN_VISIBLE_RATIO and _try_restore_window(hwnd):
                region, hwnd = _search_region(config, procs)
                last_region = region
                ratio = visible_ratio(region) if region else 1.0
            if region and ratio < MIN_VISIBLE_RATIO:
                logger.error(
                    f"目标窗口可见比例仅 {ratio:.0%}（区域 {region}），"
                    f"截图里会是大片黑边，不可能找到 {image_name}")
                raise TargetWindowNotVisible(
                    f"目标窗口几乎在屏幕外（可见 {ratio:.0%}，窗口区域 {region}），"
                    f"无法识别 {image_name}。\n{OFFSCREEN_HINT}")

        match = vision.find_any(
            candidates, region=region, threshold=threshold,
            scale_min=scale_min, scale_max=scale_max, scale_step=scale_step)

        if match:
            logger.info(
                f"命中目标（第 {attempt} 次尝试）: {match}；"
                f"缩放比 {match.scale:.2f}")
            return click_match(match, config, procs=procs, hwnd=hwnd)

        interruptible_sleep(interval)

    shot = _save_failure_screenshot(image_name, last_region)
    if shot:
        logger.info(f"找图失败现场截图: {shot}")
    logger.warning(TEMPLATE_HINT)
    raise TemplateNotFound(
        f"找图超时（{attempt} 次尝试，共 {timeout} 秒），未能找到: {image_name}\n"
        f"{TEMPLATE_HINT}"
        + (f"\n现场截图（用于确认按钮当时长什么样）：{shot}" if shot else ""))


def run_maa_phase(config, logger):
    maa_path = config.get("maa_path", "").strip()
    if not maa_path:
        logger.info("未配置 MAA 启动地址，跳过 MAA 阶段。")
        return False

    emulator_proc = config.get("emulator_proc", "MuMuPlayer.exe")
    maa_procs = ["maa.exe", "maa-cli.exe"]

    if is_process_running(maa_procs):
        logger.info("检测到 MAA 已在运行，正在拉取到前台...")
        bring_process_to_front(maa_procs)
        interruptible_sleep(3)
    else:
        if not os.path.exists(maa_path):
            raise FileNotFoundError(f"MAA 路径无效: {maa_path}")
        logger.info(f"MAA 未运行，正在启动新进程: {maa_path}")
        _launch_program(maa_path, logger)
        interruptible_sleep(5)

    # Check that the emulator is up before clicking. If MAA's "start emulator on launch"
    # is off (Start.OpenEmulatorAfterLaunch=False in gui.json), MAA goes straight to ADB
    # and the connection is refused while the emulator is down (10061 in MAA's log); the
    # task fails at once. That is an environment problem: say so, so the click gets no blame.
    if not is_process_running([emulator_proc]):
        logger.warning(
            f"点击前未检测到模拟器进程（{emulator_proc}）。如果 MAA 的"
            f"「启动后自动开启模拟器」没有打开，MAA 会立刻连接失败（ADB 10061）。"
            f"建议：在 MAA 里勾选该选项，或先手动启动模拟器再执行任务。")

    logger.info("正在尝试点击 MAA 的【Link Start!】按钮...")
    find_and_click("maa_start.png", config, procs=maa_procs)

    wait_for_process_start([emulator_proc], config.get("game_start_timeout", 120))
    emulator_started_at = time.time()

    logger.info("MAA 正在运行，等待模拟器关闭...")
    wait_for_process_exit([emulator_proc], config.get("game_exit_timeout", 7200), check_interval=15)

    uptime = time.time() - emulator_started_at
    _check_emulator_runtime(uptime, config.get("min_emulator_runtime", 60))

    logger.info(f"模拟器运行 {uptime / 60:.1f} 分钟后退出，判定本次任务完成。")
    logger.info("模拟器已关闭，正在将 MAA 最小化到后台备用...")
    minimize_process_windows(maa_procs)
    interruptible_sleep(3)
    return True


def _check_emulator_runtime(uptime, min_runtime):
    """An emulator that quits right after launch almost always failed to start or connect,
    so it must not count as success.

    Up to 1.0.3 a plain "emulator process exited" was treated as success: when MuMu
    died at once because ADB could not connect (10061 in MAA's log) we reported
    success and the user believed the run had finished.
    :raises RuntimeError: uptime below the threshold
    """
    try:
        min_runtime = float(min_runtime or 0)
    except (TypeError, ValueError):
        min_runtime = 0.0
    if min_runtime <= 0 or uptime >= min_runtime:
        return
    raise EmulatorStartupFailed(
        f"模拟器启动后仅 {uptime:.0f} 秒就退出（阈值 {min_runtime:.0f} 秒），"
        f"判定为启动/连接失败，而不是任务完成。常见原因：\n"
        f"  1) MAA 的模拟器连接设置不对（MuMu 12 默认应为 127.0.0.1:16384）；\n"
        f"  2) MAA 未开启「启动后自动开启模拟器」，而模拟器本来就没运行；\n"
        f"  3) 模拟器没启动完（Android 还在开机）就被要求连接；\n"
        f"  4) 虚拟机加速不可用 / 模拟器安装不完整。\n"
        f"请查看 MAA 自己的日志（其安装目录下 debug\\asst.log）确认是 "
        f"ConnectingFailed 还是模拟器崩溃。")


def run_maaend_phase(config, logger):
    maaend_path = config.get("maaend_path", "").strip()
    if not maaend_path:
        logger.info("未配置 MaaEnd 启动地址，跳过 MaaEnd 阶段。")
        return False

    pc_game_proc = config.get("pc_game_proc", "Endfield.exe")
    maaend_procs = ["maaend"]

    if is_process_running(maaend_procs):
        logger.info("检测到 MaaEnd 已在运行，正在拉取到前台...")
        bring_process_to_front(maaend_procs)
        interruptible_sleep(3)
    else:
        if not os.path.exists(maaend_path):
            raise FileNotFoundError(f"MaaEnd 路径无效: {maaend_path}")
        logger.info(f"MaaEnd 未运行，正在启动新进程: {maaend_path}")
        _launch_program(maaend_path, logger)
        interruptible_sleep(10)

    logger.info("正在尝试点击 MaaEnd 的【开始任务】按钮...")
    find_and_click("maaend_start.png", config, procs=maaend_procs)

    wait_for_process_start([pc_game_proc], config.get("game_start_timeout", 120))

    logger.info("PC端游戏已启动，等待游戏关闭...")
    wait_for_process_exit([pc_game_proc], config.get("game_exit_timeout", 7200), check_interval=15)

    logger.info("PC端游戏已关闭，正在将 MaaEnd 最小化到后台备用...")
    minimize_process_windows(maaend_procs)
    interruptible_sleep(3)
    return True


def _handle_foreground_action(config, logger):
    """Apply the configured pre-launch handling of foreground programs."""
    action = config.get("foreground_action", "none")

    if action == "kill_all":
        logger.info("前台处理策略：【关闭所有前台程序】")
        kill_foreground_apps()

    elif action == "blacklist":
        blacklist_str = config.get("blacklist_apps", "")
        # Accept Chinese commas, ASCII commas, newlines and semicolons alike
        blacklist = [n.strip() for n in
                     blacklist_str.replace("，", ",").replace("；", ",").replace(";", ",")
                     .replace("\n", ",").split(",") if n.strip()]
        if blacklist:
            logger.info(f"前台处理策略：【用户黑名单】 -> {blacklist}")
            kill_blacklist_apps(blacklist)
        else:
            logger.info("前台处理策略：【用户黑名单】，但黑名单为空，跳过清理。")

    else:
        logger.info("前台处理策略：【不做任何操作】，跳过清理前台程序。")


def execute_workflow(config, logger):
    start_time = datetime.datetime.now()

    # ================= 1. Capture this task's log records =================
    task_logs = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            task_logs.append(self.format(record))

    capture_handler = CaptureHandler()
    capture_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(capture_handler)

    overall_status = "成功"
    send_key = config.get("serverchan_key", "")
    webhook_url = config.get("webhook_url", "")
    retry_times = config.get("retry_times", 3)
    retry_interval = config.get("retry_interval", 30)
    _clear_failure()

    try:
        # ================= Pre-launch foreground handling (per config) =================
        _handle_foreground_action(config, logger)

        # ================= MAA phase =================
        maa_path = config.get("maa_path", "").strip()
        if maa_path:
            for attempt in range(1, retry_times + 1):
                try:
                    logger.info(f"========== 开始 MAA 阶段 (尝试 {attempt}/{retry_times}) ==========")
                    run_maa_phase(config, logger)
                    break
                except TaskInterrupted:
                    raise
                except TargetWindowNotVisible as e:
                    # Window is off-screen: retrying will not move it back, so say so plainly
                    logger.error(f"MAA 阶段失败（窗口在屏幕外，不再重试）: {e}")
                    _set_failure(FAILURE_OFFSCREEN, str(e))
                    overall_status = "报错"
                    break
                except EmulatorStartupFailed as e:
                    # Environment / config problem: clicking Link Start again fails the same way, so stop
                    logger.error(f"MAA 阶段失败（环境问题，不再重试）: {e}")
                    overall_status = "报错"
                    break
                except Exception as e:
                    logger.error(f"MAA 阶段发生异常: {e}")
                    if attempt < retry_times:
                        logger.info(f"将在 {retry_interval} 秒后重试 MAA 阶段...")
                        if is_process_running(["maa.exe", "maa-cli.exe"]):
                            bring_process_to_front(["maa.exe", "maa-cli.exe"])
                        interruptible_sleep(retry_interval)   # <- interruptible
                    else:
                        logger.error("MAA 阶段重试次数已达上限，跳过该阶段。")
                        if isinstance(e, (TemplateNotFound, TemplateMissing)):
                            _set_failure(FAILURE_TEMPLATE, str(e))
                        overall_status = "报错"
        else:
            logger.info("未配置 MAA 启动地址，跳过 MAA 阶段。")

        # ================= MaaEnd phase =================
        maaend_path = config.get("maaend_path", "").strip()
        if maaend_path:
            for attempt in range(1, retry_times + 1):
                try:
                    logger.info(f"========== 开始 MaaEnd 阶段 (尝试 {attempt}/{retry_times}) ==========")
                    run_maaend_phase(config, logger)
                    break
                except TaskInterrupted:
                    raise
                except TargetWindowNotVisible as e:
                    logger.error(f"MaaEnd 阶段失败（窗口在屏幕外，不再重试）: {e}")
                    _set_failure(FAILURE_OFFSCREEN, str(e))
                    overall_status = "报错"
                    break
                except Exception as e:
                    logger.error(f"MaaEnd 阶段发生异常: {e}")
                    if attempt < retry_times:
                        logger.info(f"将在 {retry_interval} 秒后重试 MaaEnd 阶段...")
                        if is_process_running(["maaend"]):
                            bring_process_to_front(["maaend"])
                        interruptible_sleep(retry_interval)   # <- interruptible
                    else:
                        logger.error("MaaEnd 阶段重试次数已达上限。")
                        if isinstance(e, (TemplateNotFound, TemplateMissing)):
                            _set_failure(FAILURE_TEMPLATE, str(e))
                        overall_status = "报错"
        else:
            logger.info("未配置 MaaEnd 启动地址，跳过 MaaEnd 阶段。")

    except TaskInterrupted:
        logger.info("=== 任务被用户中止 ===")
        overall_status = "中止"
    except Exception as global_e:
        logger.error(f"执行过程中发生未知严重错误: {global_e}")
        overall_status = "报错"
    finally:
        logger.removeHandler(capture_handler)

    # ================= 2. Hand off to the standalone notification module =================
    end_time = datetime.datetime.now()
    send_task_report(send_key, start_time, end_time, overall_status, task_logs, webhook_url)

    logger.info("整个自动化流程结束！")
    return overall_status          # <- overall status