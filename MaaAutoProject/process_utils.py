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
    "maaend.exe", "maaend v2.29.0-beta.1",  # 保留旧版，兼容新版
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