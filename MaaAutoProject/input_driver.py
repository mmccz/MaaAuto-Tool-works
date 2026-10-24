"""鼠标点击：真实点击（SendInput）与后台点击（PostMessage）。

两种方式各有适用场景：

``sendinput``（默认）
    移动光标 → 注入真实的鼠标按下/抬起事件。**最可靠**：游戏和 Qt 程序都认，
    因为对它们来说这就是一次真的鼠标操作。代价是必须占用光标，且目标窗口
    在前台才点得中（否则点到别的窗口上），所以默认先 ``activate_window``。

``postmessage``（实验性）
    直接把 ``WM_LBUTTONDOWN`` / ``WM_LBUTTONUP`` 投递到目标窗口的客户区，
    **不移动光标、不需要窗口在前台**，可以在后台点。但它绕过系统的输入队列，
    游戏（尤其是 DirectInput / 独占全屏）通常收不到；Qt 程序大多可以。
    所以这是「后台跑任务、同时还能用鼠标干别的」的选项，不是默认。

坐标约定：全部是屏幕物理像素（进程已声明 per-monitor-v2 DPI 感知），
与 ``vision`` 的返回值一致，可直接传入。
"""

import ctypes
import logging
import time
from ctypes import wintypes

logger = logging.getLogger("MaaAuto")

CLICK_SENDINPUT = "sendinput"
CLICK_POSTMESSAGE = "postmessage"
CLICK_MODES = (CLICK_SENDINPUT, CLICK_POSTMESSAGE)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---- 鼠标事件常量 ----
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
INPUT_MOUSE = 0
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
SW_RESTORE = 9
SW_MINIMIZE = 6
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
GA_ROOT = 2


# --------------------------------------------------------------------------- #
# SendInput 结构体
# --------------------------------------------------------------------------- #
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_mouse(flags):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, 0, flags, 0, None)
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        raise OSError("SendInput 注入鼠标事件失败（可能有更高权限的窗口在前台）")


# 64 位下必须显式声明参数类型，否则句柄/指针会被截断成 32 位
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.SetCursorPos.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
user32.ScreenToClient.restype = wintypes.BOOL
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT)
user32.SetWindowPos.restype = wintypes.BOOL
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)


# --------------------------------------------------------------------------- #
# 光标
# --------------------------------------------------------------------------- #
def cursor_pos():
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return (0, 0)
    return (int(pt.x), int(pt.y))


def move_cursor(x, y):
    user32.SetCursorPos(int(x), int(y))


# --------------------------------------------------------------------------- #
# 窗口
# --------------------------------------------------------------------------- #
def activate_window(hwnd):
    """尽量把窗口提到前台。

    ``SetForegroundWindow`` 有个老规矩：非前台进程调用时系统可能直接忽略。
    绕法是把自己临时 attach 到当前前台窗口的输入队列上。
    """
    if not hwnd:
        return False
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
    except Exception:
        pass
    try:
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_self = kernel32.GetCurrentThreadId()
        attached = False
        if tid_fg and tid_fg != tid_self:
            attached = bool(user32.AttachThreadInput(tid_self, tid_fg, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(tid_self, tid_fg, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception as e:
        logger.debug(f"activate_window 失败 hwnd={hwnd}: {e}")
        return False


def wait_foreground(hwnd, timeout=1.0):
    """等目标窗口真的变成前台（最多 timeout 秒）。"""
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return user32.GetForegroundWindow() == hwnd


def root_window(hwnd):
    """取顶层窗口（点在同级子窗口上时用来激活/投递）。"""
    if not hwnd:
        return 0
    try:
        root = user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT)
        return int(root or hwnd)
    except Exception:
        return int(hwnd)


def ensure_foreground(hwnd, timeout=2.0):
    """尽最大努力把窗口变成前台，并**确认**结果；返回是否成功。

    为什么不能只调一次 SetForegroundWindow
    --------------------------------------
    Windows 有一条老规则：只有「当前前台进程」或刚收到用户输入的进程才能
    抢前台，否则 ``SetForegroundWindow`` 被静默忽略。实测在本项目里，
    从后台线程直接调用时经常失败——而一旦失败，随后注入的点击就会落到
    **别的窗口**上（比如我们自己的主界面），表现为「点了没反应」。

    这里按「代价从低到高」依次尝试，每步都验证 GetForegroundWindow：
      1. 常规 SetForegroundWindow（附 AttachThreadInput）；
      2. TOPMOST 顶一下再取消（process_utils.bring_process_to_front 的招）；
      3. 最小化 → 还原（系统会把它提到前台）。
    """
    if not hwnd:
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True

    if activate_window(hwnd) or wait_foreground(hwnd, 0.35):
        return True

    try:
        user32.SetWindowPos(wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        activate_window(hwnd)
        time.sleep(0.12)
        user32.SetWindowPos(wintypes.HWND(hwnd), HWND_NOTOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE)
    except Exception as e:
        logger.debug(f"TOPMOST 激活失败: {e}")
    if wait_foreground(hwnd, 0.5):
        return True

    try:
        user32.ShowWindow(wintypes.HWND(hwnd), SW_MINIMIZE)
        time.sleep(0.1)
        user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
        time.sleep(0.12)
        activate_window(hwnd)
    except Exception as e:
        logger.debug(f"最小化-还原激活失败: {e}")

    return wait_foreground(hwnd, max(0.3, timeout - 0.9))


def window_at_point(x, y):
    pt = wintypes.POINT(int(x), int(y))
    return user32.WindowFromPoint(pt)


# --------------------------------------------------------------------------- #
# 点击
# --------------------------------------------------------------------------- #
def click(x, y, mode=CLICK_SENDINPUT, restore_cursor=True, move_delay_ms=80,
          hwnd=None):
    """在屏幕坐标 (x, y) 点击一次。

    :param mode: ``sendinput`` / ``postmessage``
    :param restore_cursor: sendinput 模式下点完把光标放回原处
    :param move_delay_ms: 移过去之后停一下再按下，给目标程序 hover 反应时间
    :param hwnd: postmessage 模式的目标窗口；为空则取该点所在的窗口
    """
    x, y = int(round(x)), int(round(y))

    if mode == CLICK_POSTMESSAGE:
        target = hwnd or window_at_point(x, y)
        if not target:
            logger.warning(f"后台点击失败：({x},{y}) 处没有窗口")
            return False
        return post_click(target, x, y)

    origin = cursor_pos() if restore_cursor else None
    try:
        move_cursor(x, y)
        if move_delay_ms:
            time.sleep(move_delay_ms / 1000.0)
        _send_mouse(MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.02)
        _send_mouse(MOUSEEVENTF_LEFTUP)
        return True
    except Exception as e:
        logger.error(f"鼠标点击失败 ({x},{y}) mode={mode}: {e}")
        return False
    finally:
        if restore_cursor and origin is not None:
            time.sleep(0.05)
            move_cursor(*origin)


def make_lparam(x, y):
    """把客户区坐标打包成鼠标消息的 lParam（各 16 位，负坐标按补码截断）。"""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def post_click(hwnd, screen_x, screen_y, message_only=False):
    """把一次左键点击投递到 hwnd 的客户区（不移动光标、不需要前台）。

    返回 False 说明该窗口不吃 post 消息（常见于游戏），调用方应该退回 sendinput。
    """
    pt = wintypes.POINT(int(screen_x), int(screen_y))
    if not user32.ScreenToClient(hwnd, ctypes.byref(pt)):
        return False

    lparam = make_lparam(pt.x, pt.y)
    ok_move = user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.02)
    ok_down = user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.03)
    ok_up = user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    return bool(ok_move and ok_down and ok_up)
