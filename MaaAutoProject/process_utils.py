import os
import time
import psutil
import win32gui
import win32process
import logging
import win32con
from PySide6.QtCore import QThread

logger = logging.getLogger("MaaAuto")


class TaskInterrupted(Exception):
    """用户主动中止任务。"""
    pass


def check_interrupt():
    """在长循环中定期调用，被要求中断时抛出 TaskInterrupted。"""
    t = QThread.currentThread()
    if t is not None and t.isInterruptionRequested():
        raise TaskInterrupted("用户中止")


def interruptible_sleep(seconds, chunk=0.5):
    """
    分段睡眠，每 chunk 秒检查一次中断。
    用于替代裸 time.sleep()，让用户中止能得到及时响应。
    """
    remaining = float(seconds)
    while remaining > 0:
        check_interrupt()
        step = min(chunk, remaining)
        time.sleep(step)
        remaining -= step


WHITE_LIST = [
    "explorer.exe", "winlogon.exe", "csrss.exe", "smss.exe", "svchost.exe",
    "dwm.exe", "taskhostw.exe", "sihost.exe", "fontdrvhost.exe", "ctfmon.exe",
    "system", "registry", "idle", "searchindexer.exe", "securityhealthsystray.exe",
    "mumupalyer.exe", "mumuplayer.exe", "nemuplayer.exe", "dnplayer.exe",
    "maa.exe", "maacore.exe", "maa-cli.exe",
    "maaend.exe",          # 进程匹配是「包含」比较，"maaend" 已能覆盖带版本号的名字
    "python.exe", "pythonw.exe", "maa_auto.exe",
    # ---- 升级/卸载（与 MaaAutoInstaller 对齐，2026-09 冻结）----
    "upgrade.exe", "uninstall.exe",
]


def kill_foreground_apps():
    logger.info("开始执行方案A：清理前台程序...")
    pids_to_kill = set()

    def enum_windows_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            pids_to_kill.add(pid)
        return True

    win32gui.EnumWindows(enum_windows_callback, None)
    current_pid = os.getpid()
    killed_count = 0

    for pid in pids_to_kill:
        if pid == current_pid:
            continue
        try:
            proc = psutil.Process(pid)
            name = proc.name().lower()
            if name not in WHITE_LIST:
                logger.info(f"关闭程序: {proc.name()} (PID: {pid})")
                proc.kill()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    logger.info(f"前台程序清理完成，共关闭 {killed_count} 个程序。")


def is_process_running(process_names):
    """
    判断进程是否在运行。
    支持模糊匹配：传入 ["maaend"] 只要进程名包含 "maaend" 即视为运行中。
    """
    process_names = [p.lower() for p in process_names]
    for proc in psutil.process_iter(['name']):
        try:
            proc_name = proc.info['name'].lower()
            for target_name in process_names:
                if target_name in proc_name:  # 包含匹配
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def wait_for_process_start(process_names, timeout=120, check_interval=3):
    """等待进程启动。超时抛出 TimeoutError。"""
    start_time = time.time()
    process_names = [p.lower() for p in process_names]
    logger.info(f"等待进程启动: {process_names} (超时 {timeout} 秒)")

    while time.time() - start_time < timeout:
        check_interrupt()

        if is_process_running(process_names):
            logger.info(f"检测到目标进程已成功启动: {process_names}")
            return True

        # 分段 sleep，1 秒响应中断
        for _ in range(check_interval):
            check_interrupt()
            time.sleep(1)

    raise TimeoutError(f"等待进程启动超时 ({timeout}秒): {process_names}")


def wait_for_process_exit(process_names, timeout=7200, check_interval=15):
    """等待进程退出。超时抛出 TimeoutError。长等待时输出心跳日志。"""
    start_time = time.time()
    last_log_time = time.time()
    process_names = [p.lower() for p in process_names]
    logger.info(f"等待进程关闭: {process_names} (超时 {timeout} 秒)")

    while time.time() - start_time < timeout:
        check_interrupt()

        if not is_process_running(process_names):
            logger.info(f"目标进程已退出: {process_names}")
            return True

        # 每60秒输出一次心跳日志，证明程序仍在正常运行
        elapsed = int(time.time() - start_time)
        if elapsed > 60 and time.time() - last_log_time > 60:
            logger.info(f"持续等待进程关闭中... 已等待 {elapsed // 60} 分钟")
            last_log_time = time.time()

        # 分段 sleep，1 秒响应中断
        for _ in range(check_interval):
            check_interrupt()
            time.sleep(1)

    raise TimeoutError(f"等待进程关闭超时 ({timeout}秒): {process_names}")


def kill_process_by_name(process_names):
    process_names = [p.lower() for p in process_names]
    killed = False
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() in process_names:
                logger.info(f"正在关闭进程: {proc.info['name']}")
                proc.kill()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


def kill_all_related_processes():
    """退出程序时清理"""
    targets = ["maa.exe", "maa-cli.exe", "maaend.exe", "mumuplayer.exe", "nemuplayer.exe", "dnplayer.exe"]
    logger.info("正在清理残留进程...")
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() in targets:
                logger.info(f"强制关闭残留进程: {proc.info['name']}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def minimize_process_windows(process_names):
    """将指定进程的窗口最小化（支持模糊匹配）"""
    process_names = [p.lower() for p in process_names]
    minimized_count = 0
    processed_pids = set()

    def enum_windows_callback(hwnd, _):
        nonlocal minimized_count
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in processed_pids:
                return True
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name().lower()
                for target_name in process_names:
                    if target_name in proc_name:  # 模糊匹配
                        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                        logger.info(f"已将进程 {proc.name()} 窗口最小化到后台")
                        minimized_count += 1
                        processed_pids.add(pid)
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return True

    win32gui.EnumWindows(enum_windows_callback, None)
    if minimized_count == 0:
        logger.info(f"未找到可最小化的窗口: {process_names}")


def bring_process_to_front(process_names):
    """将指定进程的窗口还原并置于最前面（支持模糊匹配）"""
    process_names = [p.lower() for p in process_names]
    brought_count = 0
    processed_pids = set()

    def enum_windows_callback(hwnd, _):
        nonlocal brought_count
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in processed_pids:
                return True
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name().lower()
                for target_name in process_names:
                    if target_name in proc_name:  # 模糊匹配
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetWindowPos(
                            hwnd,
                            win32con.HWND_TOPMOST,
                            0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                        )
                        win32gui.SetForegroundWindow(hwnd)
                        time.sleep(1)
                        win32gui.SetWindowPos(
                            hwnd,
                            win32con.HWND_NOTOPMOST,
                            0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                        )

                        logger.info(f"已将进程 {proc.name()} 拉取到前台")
                        brought_count += 1
                        processed_pids.add(pid)
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return True

    win32gui.EnumWindows(enum_windows_callback, None)
    if brought_count == 0:
        logger.info(f"未找到可置顶的窗口: {process_names}")


def kill_blacklist_apps(blacklist_names):
    """
    按用户黑名单关闭前台程序（模糊匹配，例如 "chrome" 可以匹配 "chrome.exe"）。
    """
    if not blacklist_names:
        logger.info("黑名单为空，无需处理。")
        return
    blacklist_lower = [n.strip().lower() for n in blacklist_names if n and n.strip()]
    if not blacklist_lower:
        logger.info("黑名单为空，无需处理。")
        return

    logger.info(f"开始按黑名单清理前台程序: {blacklist_lower}")
    pids_to_kill = set()

    def enum_windows_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            pids_to_kill.add(pid)
        return True

    win32gui.EnumWindows(enum_windows_callback, None)
    current_pid = os.getpid()
    killed_count = 0

    for pid in pids_to_kill:
        if pid == current_pid:
            continue
        try:
            proc = psutil.Process(pid)
            name = proc.name().lower()
            for target in blacklist_lower:
                if target in name:
                    logger.info(f"关闭黑名单程序: {proc.name()} (PID: {pid})")
                    proc.kill()
                    killed_count += 1
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    logger.info(f"黑名单程序清理完成，共关闭 {killed_count} 个程序。")


# --------------------------------------------------------------------------- #
# 窗口几何（供找图限定搜索区域、点击定位使用）
#
# 坐标一律是**屏幕物理像素**：本进程在 main.py 里声明了 per-monitor-v2 DPI 感知，
# 所以 win32gui.GetWindowRect / ClientToScreen 返回的坐标与 ImageGrab 截到的像素、
# SetCursorPos 接受的坐标是同一套，不需要任何换算。
# --------------------------------------------------------------------------- #
MIN_WINDOW_AREA = 200 * 100     # 低于这个面积的窗口当作托盘/提示窗，忽略


def find_process_window(process_names, min_area=MIN_WINDOW_AREA):
    """返回匹配进程中面积最大的可见顶层窗口句柄；找不到返回 0。

    取「面积最大」而不是「第一个」：MAA 之类程序常常同时有主窗口、日志浮窗、
    隐藏的辅助窗口，主窗口面积通常最大，用它做搜索区域最稳。
    """
    process_names = [p.lower() for p in process_names if p]
    if not process_names:
        return 0

    best = {"hwnd": 0, "area": 0}

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            name = proc.name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return True
        except Exception:
            return True
        if not any(target in name for target in process_names):
            return True
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
        area = max(0, right - left) * max(0, bottom - top)
        if area >= min_area and area > best["area"]:
            best["hwnd"] = hwnd
            best["area"] = area
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception as e:
        logger.debug(f"枚举窗口失败: {e}")
    return best["hwnd"]


def get_window_rect_screen(hwnd):
    """窗口外框的屏幕矩形 (left, top, right, bottom)；失败返回 None。"""
    if not hwnd:
        return None
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def get_client_rect_screen(hwnd):
    """窗口客户区（去掉标题栏/边框）的屏幕矩形；失败时退回外框矩形。

    找图应该用客户区：标题栏里的图标/文字会干扰匹配，而且客户区在不同
    主题（深色/浅色标题栏）下更稳定。
    """
    if not hwnd:
        return None
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        if right <= left or bottom <= top:
            return get_window_rect_screen(hwnd)
        sx, sy = win32gui.ClientToScreen(hwnd, (left, top))
        ex, ey = win32gui.ClientToScreen(hwnd, (right, bottom))
        return (sx, sy, ex, ey)
    except Exception:
        return get_window_rect_screen(hwnd)


# GetSystemMetrics 的虚拟桌面索引（多显示器时 l/t 可能是负数）
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


def virtual_screen_rect():
    """整个虚拟桌面（含所有显示器和负坐标副屏）的屏幕矩形；失败返回 None。"""
    try:
        import win32api
        left = win32api.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        width = win32api.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return (left, top, left + width, top + height)


def intersect_area(a, b):
    """两个 (l, t, r, b) 矩形的交集面积；无交集返回 0。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0
    return w * h


def visible_ratio(rect, screen=None):
    """``rect`` 落在虚拟桌面内的面积占比（0~1）。

    窗口被拖到所有显示器之外时，截图只能拿到黑边、点击也点不到，
    找图会白等满超时。用这个比例提前判断，直接给出明确原因。

    :return: 0~1；拿不到屏幕尺寸时返回 1.0（不做拦截，保持旧行为）
    """
    if not rect:
        return 1.0
    screen = screen or virtual_screen_rect()
    if not screen:
        return 1.0
    total = max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
    if total <= 0:
        return 0.0
    return intersect_area(rect, screen) / total


def is_window_valid(hwnd):
    try:
        return bool(hwnd) and bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False