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
                           TaskInterrupted, check_interrupt,
                           interruptible_sleep)
from notifier import send_task_report  # <--- 引入独立的推送模块

logger = logging.getLogger("MaaAuto")


# --------------------------------------------------------------------------- #
# 找图相关配置（全部有默认值，老配置文件不改也能跑）
#
# 背景：1.0.x 用 pyautogui.locateCenterOnScreen 全屏精确尺寸匹配，模板在
# 125% / 150% 缩放下比屏幕上的按钮小一圈，于是一直「找不到按钮」。现在改为
# vision.find 多尺度匹配 + 限定目标窗口客户区，参数集中在这里。
# --------------------------------------------------------------------------- #
DEFAULT_MATCH_THRESHOLD = 0.80      # 相关系数阈值
DEFAULT_SCALE_MIN = 0.60            # 模板缩放搜索下限（60%）
DEFAULT_SCALE_MAX = 2.00            # 上限（200%）
DEFAULT_SCALE_STEP = 0.05
DEFAULT_MATCH_INTERVAL = 1.5        # 两次尝试之间的间隔（秒）
DEFAULT_VERIFY_DELAY_MS = 900       # 点击后等多久再判断「有没有生效」
DEFAULT_VERIFY_RETRIES = 1          # 点击无效时再补几次（0=不补）


class EmulatorStartupFailed(RuntimeError):
    """模拟器启动/连接失败（环境问题，重试也不会好）。"""


# --------------------------------------------------------------------------- #
# 点击生效判定
#
# 为什么需要它：「点击发出去了」不等于「点到了」。目标窗口若被别的窗口挡住、
# 或者没抢到前台，注入的点击会落到上层窗口上——日志一切正常，界面毫无反应。
# 这里在点击点周围取一小块像素，比较点击前后的变化，变化明显才认为生效。
# --------------------------------------------------------------------------- #
def _patch_region(x, y, half_w=40, half_h=28):
    return (int(x) - half_w, int(y) - half_h, int(x) + half_w, int(y) + half_h)


def _patch_diff(before, after):
    """两块截图的平均像素差。

    :return: 平均差值；截图缺失或尺寸不一致（锁屏、RDP 断开、窗口最小化）时
             返回 ``None`` 表示「无法判定」。

    1.1.0 及以前这里返回 ``999.0``（一个大到必然超过阈值的数），于是「截图失败」
    会被当成「画面变了」，日志谎报「点击生效」。缺图就是缺图，必须能表达出来。
    """
    if before is None or after is None or before.shape != after.shape:
        return None
    try:
        import numpy as np
        return float(np.abs(after.astype(np.int16) - before.astype(np.int16)).mean())
    except Exception:
        return None


def _wait_patch_change(region, before, delay_ms, threshold=1.5):
    """等 delay_ms 后重新截同一块。

    :return: ``(changed, diff)``；changed 为 True/False，
             无法判定时为 ``None``（此时 diff 也是 None）。
    """
    time.sleep(max(0, delay_ms) / 1000.0)
    after = vision.grab(region)
    diff = _patch_diff(before, after)
    if diff is None:
        return None, None
    return diff >= threshold, diff


def _resolve_target_window(hwnd, procs, x, y):
    """确定要激活/投递的顶层窗口句柄。"""
    target = int(hwnd or 0)
    if not target:
        target = int(input_driver.window_at_point(x, y) or 0)
    if not target and procs:
        target = int(find_process_window(procs) or 0)
    return input_driver.root_window(target) if target else 0


def click_match(match, config, procs=None, hwnd=0):
    """按配置点击一次匹配结果，并尽量确认「真的点到了」。

    流程：
      1. 坐标 = 命中中心 + 点击偏移；
      2. ``click_activate=False`` → **只走后台点击**（PostMessage）：绝不激活窗口、
         也不发真实点击，否则点击会落到当时的前台窗口（可能是别的程序）上；
      3. ``click_mode=postmessage`` → 直接后台投递；
      4. 需要真实点击时：先切前台（三级回退 + 校验），**切完之后**才拍「点击前」
         画面——激活本身会改变那块像素，提前拍会让校验失去意义；
      5. 前台失败 → 先试后台点击（PostMessage 不受窗口层级影响，Qt 程序可用）；
      6. 截图失败 → 只警告「无法校验」，不补点、不宣称生效。
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
        """当前这块区域的像素；关闭校验时不截图。"""
        return vision.grab(patch) if verify else None

    # ---- 只走后台点击：用户关了前台激活，或本来就是后台模式 ----
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

    # ---- 真实点击路径：先激活，再拍「点击前」画面 ----
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

    # 关键：`before` 必须在上面的激活动作之后取（激活会改变画面）
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
    """启动外部程序（MAA / MaaEnd）。

    配置项通常是 .exe 的绝对路径，可能带空格（如 Program Files）。
    旧的写法 `Popen(path, shell=True)` 会在第一个空格处截断，启动失败；
    这里优先用单元素列表（不经 shell），只有在路径本身不存在、用户实际
    填的是「exe + 参数」整串命令时，才回退到 shell 保持兼容。
    """
    if os.path.exists(exe_path):
        return subprocess.Popen([exe_path])
    logger.warning(
        "启动路径不是已存在的文件，按整串命令行交给 shell 处理: %s", exe_path)
    return subprocess.Popen(exe_path, shell=True)


def _user_template_dir(config):
    """用户模板目录：配置指定，默认 ``config/templates``。"""
    path = (config or {}).get("template_dir", "").strip()
    if path:
        return path
    return os.path.join(CONFIG_DIR, "templates")


def template_paths(image_name, config=None):
    """模板候选路径：用户目录优先，其次内置 resources。"""
    return vision.template_candidates(
        image_name,
        user_dir=_user_template_dir(config),
        bundled_dir=resource_path("resources"),
    )


def _search_region(config, procs):
    """按配置返回 (搜索矩形, 窗口句柄)。

    ``search_scope = window``（默认）：限定在目标窗口客户区内找。
        好处是快（少扫几十倍面积）、不会被别处的相似图误命中。
    ``search_scope = screen``：整屏找，用于窗口标题/边框遮挡、或目标程序
        把按钮画在独立无边框窗口里的情况。
    """
    scope = str((config or {}).get("search_scope", "window")).lower()
    if scope == "screen" or not procs:
        return None, 0

    hwnd = find_process_window(procs)
    rect = get_client_rect_screen(hwnd)
    if not rect:
        return None, 0

    # 允许外扩若干像素：按钮贴边或窗口边框半透明时的容错
    pad = int((config or {}).get("search_padding", 0) or 0)
    if pad:
        rect = (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)
    return rect, hwnd


def _save_failure_screenshot(image_name, region):
    """找图超时时留一张现场截图，方便用户回报「明明在屏幕上却找不到」。"""
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
    """寻找目标图像并点击。

    相比 1.0.x 的 ``pyautogui.locateCenterOnScreen``：
      * 多尺度匹配 → 125%/150% 缩放、不同分辨率下同样能找到；
      * 限定在目标窗口客户区搜索 → 快，且不会点到别处；
      * 支持用户模板覆盖（``config/templates/``）→ 换分辨率后可自行重截；
      * 点击方式可选：真实点击（默认）或后台 PostMessage 点击。

    :param image_name: 模板文件名，如 ``maa_start.png``
    :param config:     配置字典（读 match_* / click_* 参数）
    :param procs:      目标进程名列表，用于定位窗口与后台点击
    :param timeout:    覆盖配置里的 ``wait_timeout``
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
        return False

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
    raise TimeoutError(f"找图超时，未能找到: {image_name}")


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

    # 点击前先看看模拟器在不在。MAA 的「启动后自动开启模拟器」如果没开
    # （gui.json 里 Start.OpenEmulatorAfterLaunch=False），它会直接去连 ADB，
    # 而模拟器没起来时连接会被拒绝（MAA 日志里是 10061），任务当场失败——
    # 但这属于环境问题，先把话说明白，避免用户以为是「点击没生效」。
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
    """模拟器「刚启动就退出」几乎都是启动/连接失败，不能算任务成功。

    1.0.3 及以前只看「模拟器进程退出」就判定成功：MuMu 因为 ADB 连不上
    （MAA 日志里的 10061）当场退出时，我们会误报「成功」，用户还以为真的挂完了。
    :raises RuntimeError: 运行时长低于阈值
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
    """根据配置决定启动前的前台程序处理方式"""
    action = config.get("foreground_action", "none")

    if action == "kill_all":
        logger.info("前台处理策略：【关闭所有前台程序】")
        kill_foreground_apps()

    elif action == "blacklist":
        blacklist_str = config.get("blacklist_apps", "")
        # 同时兼容中文逗号、英文逗号、换行、分号
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

    # ================= 1. 动态捕获本次任务的日志 =================
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

    try:
        # ================= 启动前的前台处理（按配置） =================
        _handle_foreground_action(config, logger)

        # ================= MAA 阶段 =================
        maa_path = config.get("maa_path", "").strip()
        if maa_path:
            for attempt in range(1, retry_times + 1):
                try:
                    logger.info(f"========== 开始 MAA 阶段 (尝试 {attempt}/{retry_times}) ==========")
                    run_maa_phase(config, logger)
                    break
                except TaskInterrupted:
                    raise
                except EmulatorStartupFailed as e:
                    # 环境/配置问题：再点几次 Link Start 也是同样的失败，直接收尾
                    logger.error(f"MAA 阶段失败（环境问题，不再重试）: {e}")
                    overall_status = "报错"
                    break
                except Exception as e:
                    logger.error(f"MAA 阶段发生异常: {e}")
                    if attempt < retry_times:
                        logger.info(f"将在 {retry_interval} 秒后重试 MAA 阶段...")
                        if is_process_running(["maa.exe", "maa-cli.exe"]):
                            bring_process_to_front(["maa.exe", "maa-cli.exe"])
                        interruptible_sleep(retry_interval)   # ← 可中断
                    else:
                        logger.error("MAA 阶段重试次数已达上限，跳过该阶段。")
                        overall_status = "报错"
        else:
            logger.info("未配置 MAA 启动地址，跳过 MAA 阶段。")

        # ================= MaaEnd 阶段 =================
        maaend_path = config.get("maaend_path", "").strip()
        if maaend_path:
            for attempt in range(1, retry_times + 1):
                try:
                    logger.info(f"========== 开始 MaaEnd 阶段 (尝试 {attempt}/{retry_times}) ==========")
                    run_maaend_phase(config, logger)
                    break
                except TaskInterrupted:
                    raise
                except Exception as e:
                    logger.error(f"MaaEnd 阶段发生异常: {e}")
                    if attempt < retry_times:
                        logger.info(f"将在 {retry_interval} 秒后重试 MaaEnd 阶段...")
                        if is_process_running(["maaend"]):
                            bring_process_to_front(["maaend"])
                        interruptible_sleep(retry_interval)   # ← 可中断
                    else:
                        logger.error("MaaEnd 阶段重试次数已达上限。")
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

    # ================= 2. 调用独立的推送模块 =================
    end_time = datetime.datetime.now()
    send_task_report(send_key, start_time, end_time, overall_status, task_logs, webhook_url)

    logger.info("整个自动化流程结束！")
    return overall_status          # ← 返回状态