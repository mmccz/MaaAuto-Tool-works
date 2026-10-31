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
    """The user aborted the task."""
    pass


def check_interrupt():
    """Call periodically in long loops; raises TaskInterrupted once an abort is requested."""
    t = QThread.currentThread()
    if t is not None and t.isInterruptionRequested():
        raise TaskInterrupted("用户中止")


def interruptible_sleep(seconds, chunk=0.5):
    """Sleep in slices, checking for an interrupt every chunk seconds.
    Replaces a bare time.sleep() so a user abort is noticed promptly.
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
    "maaend.exe",          # process matching is a substring test, so "maaend" also covers versioned names
    "python.exe", "pythonw.exe", "maa_auto.exe",
    # ---- upgrade / uninstall (aligned with MaaAutoInstaller, frozen 2026-09) ----
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
    """Whether any of the processes is running.
    Fuzzy matching: with ["maaend"], any process name containing "maaend" counts.
    """
    process_names = [p.lower() for p in process_names]
    for proc in psutil.process_iter(['name']):
        try:
            proc_name = proc.info['name'].lower()
            for target_name in process_names:
                if target_name in proc_name:  # substring match
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def wait_for_process_start(process_names, timeout=120, check_interval=3):
    """Wait for the process to start; raises TimeoutError on timeout."""
    start_time = time.time()
    process_names = [p.lower() for p in process_names]
    logger.info(f"等待进程启动: {process_names} (超时 {timeout} 秒)")

    while time.time() - start_time < timeout:
        check_interrupt()

        if is_process_running(process_names):
            logger.info(f"检测到目标进程已成功启动: {process_names}")
            return True

        # sleep in slices so an abort is noticed within a second
        for _ in range(check_interval):
            check_interrupt()
            time.sleep(1)

    raise TimeoutError(f"等待进程启动超时 ({timeout}秒): {process_names}")


def wait_for_process_exit(process_names, timeout=7200, check_interval=15):
    """Wait for the process to exit; raises TimeoutError. Logs a heartbeat on long waits."""
    start_time = time.time()
    last_log_time = time.time()
    process_names = [p.lower() for p in process_names]
    logger.info(f"等待进程关闭: {process_names} (超时 {timeout} 秒)")

    while time.time() - start_time < timeout:
        check_interrupt()

        if not is_process_running(process_names):
            logger.info(f"目标进程已退出: {process_names}")
            return True

        # a heartbeat every 60 s proves the app is still alive
        elapsed = int(time.time() - start_time)
        if elapsed > 60 and time.time() - last_log_time > 60:
            logger.info(f"持续等待进程关闭中... 已等待 {elapsed // 60} 分钟")
            last_log_time = time.time()

        # sleep in slices so an abort is noticed within a second
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
    """Cleanup when the app exits."""
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
    """Minimise the windows of the given processes (fuzzy matching)."""
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
                    if target_name in proc_name:  # fuzzy match
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
    """Restore and raise the windows of the given processes (fuzzy matching)."""
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
                    if target_name in proc_name:  # fuzzy match
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
    return brought_count > 0


def kill_blacklist_apps(blacklist_names):
    """Kill foreground apps on the user's blacklist (fuzzy, so "chrome" matches "chrome.exe").
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
# Window geometry (limits the search area and locates clicks)
#
# Coordinates are always **screen physical pixels**: main.py declares per-monitor-v2
# DPI awareness, so win32gui.GetWindowRect / ClientToScreen return the same units as
# ImageGrab pixels and SetCursorPos input - no conversion anywhere.
# --------------------------------------------------------------------------- #
MIN_WINDOW_AREA = 200 * 100     # windows smaller than this area are trays / tooltips and get ignored


def find_process_window(process_names, min_area=MIN_WINDOW_AREA):
    """Return the largest visible top-level window of a matching process, or 0.

    Largest rather than first: MAA-style programs have a main window, log popups and
    hidden helper windows at once; the main window is usually the largest, which makes
    it the steadiest search area.
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
    """Screen rect of the window frame (left, top, right, bottom); None on failure."""
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
    """Screen rect of the client area (no title bar or border); falls back to the frame.

    Finding should use the client area: icons and text in the title bar disturb matching,
    and the client area is steadier across themes (dark / light title bars).
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


# GetSystemMetrics virtual-desktop indices (l/t can be negative with several monitors)
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


def virtual_screen_rect():
    """Screen rect of the whole virtual desktop, all monitors included; None on failure."""
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
    """Area of the intersection of two (l, t, r, b) rects; 0 when they do not overlap."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0
    return w * h


def visible_ratio(rect, screen=None):
    """Fraction of ``rect`` (0..1) that lies inside the virtual desktop.

    A window dragged off every monitor only yields black screenshots and unreachable
    clicks, so finding would wait out the full timeout. This ratio lets the caller give
    a clear reason up front.

    :return: 0..1; 1.0 when the screen size is unknown (no check, previous behaviour)
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