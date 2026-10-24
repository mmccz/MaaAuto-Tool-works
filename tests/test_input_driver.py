"""input_driver 的单元测试。

只测「坐标换算 / 调用顺序 / 失败回退」这类纯逻辑；
真实鼠标注入不能也不该在 CI 上跑，所以 move_cursor 与 _send_mouse 都被替换。
"""

import input_driver


def test_make_lparam_packs_signed_coords():
    assert input_driver.make_lparam(0, 0) == 0
    assert input_driver.make_lparam(10, 20) == (20 << 16) | 10
    # 负坐标按 16 位补码截断，不能把高位带进 y
    lparam = input_driver.make_lparam(-1, -1)
    assert lparam == ((-1 & 0xFFFF) << 16) | (-1 & 0xFFFF)


def test_cursor_pos_returns_ints():
    x, y = input_driver.cursor_pos()
    assert isinstance(x, int) and isinstance(y, int)


def test_click_sendinput_moves_and_restores(monkeypatch):
    moved = []
    sent = []

    monkeypatch.setattr(input_driver, "cursor_pos", lambda: (5, 6))
    monkeypatch.setattr(input_driver, "move_cursor",
                        lambda x, y: moved.append((x, y)))
    monkeypatch.setattr(input_driver, "_send_mouse", lambda flags: sent.append(flags))
    monkeypatch.setattr(input_driver.time, "sleep", lambda s: None)

    ok = input_driver.click(100, 200, move_delay_ms=0)

    assert ok is True
    assert sent == [input_driver.MOUSEEVENTF_LEFTDOWN,
                    input_driver.MOUSEEVENTF_LEFTUP]
    assert moved[0] == (100, 200)
    assert moved[-1] == (5, 6)          # 还原到原位


def test_click_without_restore_leaves_cursor(monkeypatch):
    moved = []
    monkeypatch.setattr(input_driver, "cursor_pos", lambda: (5, 6))
    monkeypatch.setattr(input_driver, "move_cursor",
                        lambda x, y: moved.append((x, y)))
    monkeypatch.setattr(input_driver, "_send_mouse", lambda flags: None)
    monkeypatch.setattr(input_driver.time, "sleep", lambda s: None)

    assert input_driver.click(11, 22, restore_cursor=False) is True
    assert moved == [(11, 22)]


def test_click_returns_false_on_injection_error(monkeypatch):
    monkeypatch.setattr(input_driver, "cursor_pos", lambda: (0, 0))
    monkeypatch.setattr(input_driver, "move_cursor", lambda x, y: None)
    monkeypatch.setattr(input_driver.time, "sleep", lambda s: None)

    def boom(flags):
        raise OSError("inject failed")

    monkeypatch.setattr(input_driver, "_send_mouse", boom)

    assert input_driver.click(1, 2) is False


def test_post_click_uses_client_coords(monkeypatch):
    posted = []

    monkeypatch.setattr(input_driver.user32, "ScreenToClient",
                        lambda hwnd, pt: _set_pt(pt, 30, 40))
    monkeypatch.setattr(input_driver.user32, "PostMessageW",
                        lambda hwnd, msg, wparam, lparam: posted.append(
                            (msg, wparam, lparam)) or 1)
    monkeypatch.setattr(input_driver.time, "sleep", lambda s: None)

    assert input_driver.post_click(1234, 500, 600) is True
    expected = input_driver.make_lparam(30, 40)
    assert [p[0] for p in posted] == [input_driver.WM_MOUSEMOVE,
                                      input_driver.WM_LBUTTONDOWN,
                                      input_driver.WM_LBUTTONUP]
    assert all(p[2] == expected for p in posted)
    assert posted[1][1] == input_driver.MK_LBUTTON


def test_post_click_without_window_fails(monkeypatch):
    monkeypatch.setattr(input_driver.user32, "ScreenToClient",
                        lambda hwnd, pt: 0)
    assert input_driver.post_click(0, 1, 2) is False


def test_click_postmessage_falls_back_to_window_at_point(monkeypatch):
    used = []

    def fake_post_click(hwnd, x, y, message_only=False):
        used.append(hwnd)
        return True

    monkeypatch.setattr(input_driver, "post_click", fake_post_click)
    monkeypatch.setattr(input_driver, "window_at_point", lambda x, y: 4242)

    assert input_driver.click(10, 10, mode=input_driver.CLICK_POSTMESSAGE) is True
    assert used == [4242]


def test_activate_window_with_invalid_handle():
    assert input_driver.activate_window(0) is False


class _Pt:
    def __init__(self):
        self.x = 0
        self.y = 0


def _set_pt(ptref, x, y):
    """模拟 ScreenToClient 把 pt 改成客户区坐标（ptref 是 ctypes.byref 对象）。"""
    import ctypes
    from ctypes import wintypes

    p = ctypes.cast(ptref, ctypes.POINTER(wintypes.POINT)).contents
    p.x = x
    p.y = y
    return 1
