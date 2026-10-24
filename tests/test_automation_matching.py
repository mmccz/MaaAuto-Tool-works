"""automation.py 里「找图 + 点击」编排逻辑的测试。

不截真实屏幕、不注入真实鼠标：vision.find_any 与 input_driver.* 全部被替换，
只验证「用哪个区域搜、命中了往哪点、什么时候回退/超时」。
"""

import pytest

import automation
import input_driver
import vision


def make_match(left=100, top=50, width=60, height=20, score=0.9, scale=1.0):
    return vision.Match(left=left, top=top, width=width, height=height,
                        score=score, scale=scale, template="maa_start.png")


@pytest.fixture
def stub_vision(monkeypatch):
    """让 find_any 立刻返回预设结果，并记录传给它的 region。"""
    calls = {"region": "unset", "n": 0}
    queue = []

    def fake_find_any(paths, region=None, **kwargs):
        calls["region"] = region
        calls["n"] += 1
        return queue.pop(0) if queue else None

    monkeypatch.setattr(vision, "find_any", fake_find_any)
    return calls, queue


@pytest.fixture
def fake_click(monkeypatch):
    recorded = {"clicks": [], "activated": [], "posted": []}

    monkeypatch.setattr(input_driver, "click",
                        lambda x, y, **kw: recorded["clicks"].append((x, y, kw)) or True)
    monkeypatch.setattr(input_driver, "activate_window",
                        lambda hwnd: recorded["activated"].append(hwnd) or True)
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: recorded["activated"].append(hwnd) or True)
    monkeypatch.setattr(input_driver, "wait_foreground", lambda hwnd, t: True)
    monkeypatch.setattr(input_driver, "post_click",
                        lambda hwnd, x, y, **kw: recorded["posted"].append((hwnd, x, y)) or True)
    return recorded


BASE_CFG = {"click_verify": False}


def test_search_region_window_scope(monkeypatch):
    monkeypatch.setattr(automation, "find_process_window", lambda procs: 111)
    monkeypatch.setattr(automation, "get_client_rect_screen",
                        lambda hwnd: (10, 20, 300, 400))

    region, hwnd = automation._search_region(
        {"search_scope": "window"}, ["maa.exe"])
    assert region == (10, 20, 300, 400)
    assert hwnd == 111


def test_search_region_padding(monkeypatch):
    monkeypatch.setattr(automation, "find_process_window", lambda procs: 111)
    monkeypatch.setattr(automation, "get_client_rect_screen",
                        lambda hwnd: (10, 20, 300, 400))

    region, _ = automation._search_region(
        {"search_scope": "window", "search_padding": 8}, ["maa.exe"])
    assert region == (2, 12, 308, 408)


def test_search_region_screen_scope(monkeypatch):
    monkeypatch.setattr(automation, "find_process_window",
                        lambda procs: pytest.fail("全屏模式不该去找窗口"))
    region, hwnd = automation._search_region({"search_scope": "screen"}, ["maa.exe"])
    assert region is None and hwnd == 0


def test_search_region_without_window_falls_back_to_screen(monkeypatch):
    monkeypatch.setattr(automation, "find_process_window", lambda procs: 0)
    monkeypatch.setattr(automation, "get_client_rect_screen", lambda hwnd: None)
    region, hwnd = automation._search_region({"search_scope": "window"}, ["maa.exe"])
    assert region is None and hwnd == 0


def test_template_paths_user_dir_wins(tmp_path, monkeypatch):
    user = tmp_path / "templates"
    user.mkdir()
    (user / "maa_start.png").write_bytes(b"user")
    monkeypatch.setattr(automation, "resource_path",
                        lambda rel: str(tmp_path / "res"))

    paths = automation.template_paths("maa_start.png", {"template_dir": str(user)})
    assert len(paths) == 1
    assert paths[0].startswith(str(user))


def test_find_and_click_hits_and_clicks(monkeypatch, stub_vision, fake_click):
    calls, queue = stub_vision
    queue.append(make_match(left=100, top=50, width=60, height=20))

    cfg = {"search_scope": "screen", "click_offset_x": 3, "click_offset_y": -4,
           "wait_timeout": 5, "click_verify": False}
    assert automation.find_and_click("maa_start.png", cfg) is True

    # 命中点 = 中心 (130, 60) + 偏移
    x, y, kw = fake_click["clicks"][0]
    assert (x, y) == (133, 56)
    assert kw["mode"] == input_driver.CLICK_SENDINPUT


def test_find_and_click_waits_for_window_scope(monkeypatch, stub_vision, fake_click):
    calls, queue = stub_vision
    queue.extend([None, make_match()])
    monkeypatch.setattr(automation, "find_process_window", lambda procs: 7)
    monkeypatch.setattr(automation, "get_client_rect_screen",
                        lambda hwnd: (0, 0, 200, 200))
    monkeypatch.setattr(automation, "interruptible_sleep", lambda s: None)

    cfg = {"search_scope": "window", "wait_timeout": 5, "click_verify": False}
    assert automation.find_and_click("maa_start.png", cfg, procs=["maa.exe"]) is True
    assert calls["n"] == 2
    assert calls["region"] == (0, 0, 200, 200)
    assert fake_click["activated"] == [7]


def test_find_and_click_timeout(monkeypatch, stub_vision, fake_click):
    calls, queue = stub_vision
    monkeypatch.setattr(automation, "interruptible_sleep", lambda s: None)
    monkeypatch.setattr(automation, "_save_failure_screenshot",
                        lambda name, region: None)

    with pytest.raises(TimeoutError):
        automation.find_and_click("maa_start.png",
                                  {"wait_timeout": 0.05, "click_verify": False})

    assert calls["n"] >= 1
    assert fake_click["clicks"] == []


def test_find_and_click_missing_template(monkeypatch, fake_click):
    monkeypatch.setattr(automation, "template_paths", lambda name, cfg: [])
    assert automation.find_and_click("nope.png", {}) is False
    assert fake_click["clicks"] == []


def test_postmessage_mode_skips_activation(monkeypatch, stub_vision, fake_click):
    calls, queue = stub_vision
    queue.append(make_match())
    monkeypatch.setattr(automation, "find_process_window", lambda procs: 9)

    cfg = {"search_scope": "screen", "click_mode": "postmessage",
           "wait_timeout": 5, "click_verify": False}
    assert automation.find_and_click("maa_start.png", cfg, procs=["maa.exe"]) is True
    assert fake_click["activated"] == []
    assert fake_click["clicks"][0][2]["mode"] == input_driver.CLICK_POSTMESSAGE


def test_postmessage_falls_back_to_real_click(monkeypatch, stub_vision):
    calls, queue = stub_vision
    queue.append(make_match())
    monkeypatch.setattr(automation, "find_process_window", lambda procs: 9)

    modes = []

    def fake_click(x, y, **kw):
        modes.append(kw.get("mode"))
        return len(modes) > 1        # 第一次（postmessage）失败，第二次成功

    monkeypatch.setattr(input_driver, "click", fake_click)
    monkeypatch.setattr(input_driver, "activate_window", lambda hwnd: True)
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: True)
    monkeypatch.setattr(input_driver, "wait_foreground", lambda hwnd, t: True)

    cfg = {"search_scope": "screen", "click_mode": "postmessage",
           "wait_timeout": 5, "click_verify": False}
    assert automation.find_and_click("maa_start.png", cfg, procs=["maa.exe"]) is True
    assert modes == [input_driver.CLICK_POSTMESSAGE, input_driver.CLICK_SENDINPUT]
