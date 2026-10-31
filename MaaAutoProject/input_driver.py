"""Mouse clicking: a real click (SendInput) and a background click (PostMessage).

Each mode has its own use case:

``sendinput`` (default)
    Move the cursor, then inject real mouse down/up events. **Most reliable**: games
    and Qt apps accept them as a genuine mouse action. Cost: it occupies the cursor,
    and the target must be in the foreground, so ``activate_window`` runs first.

``postmessage`` (experimental)
    Post ``WM_LBUTTONDOWN`` / ``WM_LBUTTONUP`` straight to the target client area:
    **no cursor movement, no foreground needed**, so it clicks in the background.
    It bypasses the system input queue though, so games (DirectInput / exclusive
    fullscreen) usually miss it while most Qt apps take it. Hence an option, not the default.

Coordinates: always screen physical pixels (the process declares per-monitor-v2 DPI
awareness), identical to what ``vision`` returns, so pass them straight through.
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

# ---- mouse event constants ----
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
# SendInput structures
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


# On 64-bit the argument types must be declared, or handles / pointers are truncated to 32 bits
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
# Cursor
# --------------------------------------------------------------------------- #
def cursor_pos():
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return (0, 0)
    return (int(pt.x), int(pt.y))


def move_cursor(x, y):
    user32.SetCursorPos(int(x), int(y))


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #
def activate_window(hwnd):
    """Bring a window to the foreground as far as possible.

    ``SetForegroundWindow`` has an old rule: the system may ignore it when called by a
    non-foreground process. The workaround is to attach temporarily to the input queue
    of the current foreground window.
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
    """Wait until the target window really is foreground (at most timeout seconds)."""
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return user32.GetForegroundWindow() == hwnd


def root_window(hwnd):
    """Top-level window (used for activation / posting when the hit is on a child control)."""
    if not hwnd:
        return 0
    try:
        root = user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT)
        return int(root or hwnd)
    except Exception:
        return int(hwnd)


def ensure_foreground(hwnd, timeout=2.0):
    """Force a window to the foreground and **verify** it; returns whether that worked.

    Why one SetForegroundWindow call is not enough
    ----------------------------------------------
    Windows keeps an old rule: only the current foreground process, or one that just
    received user input, may steal the foreground - otherwise ``SetForegroundWindow`` is
    silently ignored. Called from a background thread in this project it often fails,
    and once it fails the injected click lands on **another window** (our own main
    window, say), which looks like "the click did nothing".

    So the attempts run from cheapest to most expensive, each verified with
    GetForegroundWindow:
      1. the usual SetForegroundWindow (plus AttachThreadInput);
      2. flash TOPMOST and drop it again (process_utils.bring_process_to_front's trick);
      3. minimise, then restore (the system brings it forward).
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
# Clicking
# --------------------------------------------------------------------------- #
def click(x, y, mode=CLICK_SENDINPUT, restore_cursor=True, move_delay_ms=80,
          hwnd=None):
    """Click once at screen coordinates (x, y).

    :param mode: ``sendinput`` / ``postmessage``
    :param restore_cursor: in sendinput mode, put the cursor back afterwards
    :param move_delay_ms: pause after moving and before pressing, so the target reacts to hover
    :param hwnd: target window for postmessage; defaults to the window under the point
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
    """Pack client coordinates into a mouse-message lParam (16 bits each, negatives truncated)."""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def post_click(hwnd, screen_x, screen_y, message_only=False):
    """Post one left click to hwnd's client area (no cursor movement, no foreground needed).

    False means the window ignores posted messages (common for games); the caller should
    fall back to sendinput.
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
