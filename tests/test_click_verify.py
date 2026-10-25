"""click_match 的「点击生效校验」逻辑测试。

对应 1.0.2 实测报告的核心问题：点击发出去了、日志正常，界面毫无反应。
判定依据是「点击点附近的像素有没有变化」，所以这里把 vision.grab 换成
可控的假画面，精确驱动「有变化 / 没变化」两种分支。
"""

import numpy as np
import pytest

import automation
import input_driver
import vision


def make_match(center=(300, 200), size=(100, 40)):
    return vision.Match(left=center[0] - size[0] // 2,
                        top=center[1] - size[1] // 2,
                        width=size[0], height=size[1],
                        score=0.9, scale=1.0, template="t.png")


class FakeScreen:
    """按顺序返回预设帧；用完后一直返回最后一帧。"""

    def __init__(self, frames):
        self._frames = list(frames)
        self.calls = 0

    def grab(self, region=None):
        idx = min(self.calls, len(self._frames) - 1)
        self.calls += 1
        return self._frames[idx]


def blank(value=100, shape=(56, 80, 3)):
    return np.full(shape, value, dtype=np.uint8)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(automation.time, "sleep", lambda s: None)


@pytest.fixture
def fg_ok(monkeypatch):
    calls = []
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: calls.append(hwnd) or True)
    return calls


@pytest.fixture
def click_counter(monkeypatch):
    calls = []

    def fake_click(x, y, **kw):
        calls.append((x, y, kw))
        return True

    monkeypatch.setattr(input_driver, "click", fake_click)
    return calls


def test_click_verified_first_try(monkeypatch, no_sleep, fg_ok, click_counter):
    """点一下就有效 → 只点一次。"""
    monkeypatch.setattr(vision, "grab",
                        FakeScreen([blank(100), blank(200)]).grab)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    ok = automation.click_match(make_match(), {"click_verify": True},
                                procs=["maa.exe"])
    assert ok is True
    assert len(click_counter) == 1
    assert click_counter[0][:2] == (300, 200)


def test_click_retries_when_nothing_changed(monkeypatch, no_sleep, fg_ok,
                                            click_counter):
    """第一下没反应（典型：窗口未激活，第一下被吃掉）→ 补点一次并成功。"""
    monkeypatch.setattr(vision, "grab",
                        FakeScreen([blank(100), blank(100), blank(230)]).grab)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    ok = automation.click_match(make_match(),
                                {"click_verify": True, "click_retries": 1},
                                procs=["maa.exe"])
    assert ok is True
    assert len(click_counter) == 2


def test_click_gives_up_after_retries(monkeypatch, no_sleep, fg_ok, click_counter):
    """补点次数用完后不再纠缠，返回 True（流程继续），但日志会警告。"""
    monkeypatch.setattr(vision, "grab", lambda region=None: blank(100))
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    warnings = []
    monkeypatch.setattr(automation.logger, "warning",
                        lambda msg, *a, **k: warnings.append(str(msg)))

    ok = automation.click_match(make_match(),
                                {"click_verify": True, "click_retries": 2},
                                procs=["maa.exe"])
    assert ok is True
    assert len(click_counter) == 3        # 1 次 + 2 次补点
    assert any("画面无变化" in w for w in warnings)


def test_foreground_failure_uses_background_click(monkeypatch, no_sleep,
                                                  click_counter):
    """抢不到前台时不盲点，先投递后台点击；成功就不再动鼠标。"""
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: False)
    posted = []
    monkeypatch.setattr(input_driver, "post_click",
                        lambda hwnd, x, y, **kw: posted.append((hwnd, x, y)) or True)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 99)
    monkeypatch.setattr(vision, "grab",
                        FakeScreen([blank(100), blank(220)]).grab)

    ok = automation.click_match(make_match(), {"click_verify": True},
                                procs=["maa.exe"])
    assert ok is True
    assert posted == [(99, 300, 200)]
    assert click_counter == []


def test_foreground_failure_falls_back_to_real_click(monkeypatch, no_sleep,
                                                     click_counter):
    """后台点击也没生效 → 仍然尝试真实点击。"""
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: False)
    monkeypatch.setattr(input_driver, "post_click",
                        lambda hwnd, x, y, **kw: True)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 99)
    monkeypatch.setattr(vision, "grab",
                        FakeScreen([blank(100), blank(100), blank(240)]).grab)

    ok = automation.click_match(make_match(),
                                {"click_verify": True, "click_retries": 0},
                                procs=["maa.exe"])
    assert ok is True
    assert len(click_counter) == 1


def test_offsets_are_applied(monkeypatch, no_sleep, fg_ok, click_counter):
    monkeypatch.setattr(vision, "grab", lambda region=None: blank(100))
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)
    automation.click_match(make_match((300, 200)),
                           {"click_verify": False, "click_offset_x": -7,
                            "click_offset_y": 9})
    assert click_counter[0][:2] == (293, 209)


def test_no_verify_skips_screen_grabs(monkeypatch, no_sleep, fg_ok,
                                      click_counter):
    monkeypatch.setattr(vision, "grab",
                        lambda region=None: pytest.fail("关闭校验时不该截图"))
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)
    assert automation.click_match(make_match(), {"click_verify": False}) is True
    assert len(click_counter) == 1


def test_postmessage_mode_uses_post_only(monkeypatch, no_sleep, click_counter):
    monkeypatch.setattr(vision, "grab", lambda region=None: blank(100))
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 7)
    automation.click_match(make_match(), {
        "click_mode": input_driver.CLICK_POSTMESSAGE,
        "click_verify": False,
    })
    assert click_counter[0][2]["mode"] == input_driver.CLICK_POSTMESSAGE
    assert click_counter[0][2]["hwnd"] == 7


def test_patch_diff_helpers():
    a = np.zeros((10, 10, 3), dtype=np.uint8)
    b = np.full((10, 10, 3), 50, dtype=np.uint8)
    assert automation._patch_diff(a, a) == 0.0
    assert automation._patch_diff(a, b) == pytest.approx(50.0)
    # 1.1.1：截图缺失不再返回 999.0（那会被当成「画面变了」），改为 None=无法判定
    assert automation._patch_diff(a, None) is None
    assert automation._patch_diff(a, b[0:5]) is None

    region = automation._patch_region(100, 200)
    assert region == (60, 172, 140, 228)


# --------------------------------------------------------------------------- #
# 1.1.1 回归：click_activate（关掉前台激活时只允许后台点击）
# --------------------------------------------------------------------------- #
def test_click_activate_off_uses_background_click_only(monkeypatch, no_sleep):
    """click_activate=False → 不激活窗口，只发后台点击，绝不发真实点击。"""
    activated = []
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: activated.append(hwnd) or True)
    clicks = []

    def fake_click(x, y, **kw):
        clicks.append((x, y, kw))
        return True

    monkeypatch.setattr(input_driver, "click", fake_click)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    ok = automation.click_match(
        make_match(), {"click_activate": False, "click_verify": False})

    assert ok is True
    assert activated == []                       # 从未尝试切前台
    assert len(clicks) == 1
    assert clicks[0][2]["mode"] == input_driver.CLICK_POSTMESSAGE


def test_click_activate_off_gives_up_when_background_fails(monkeypatch, no_sleep):
    """关了激活、后台点击也失败 → 放弃（绝不能退化成真实点击）。"""
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: pytest.fail("不该激活窗口"))
    clicks = []

    def fake_click(x, y, **kw):
        clicks.append((x, y, kw))
        return False

    monkeypatch.setattr(input_driver, "click", fake_click)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    ok = automation.click_match(
        make_match(), {"click_activate": False, "click_verify": False})

    assert ok is False
    assert len(clicks) == 1                      # 只尝试过后台投递
    assert clicks[0][2]["mode"] == input_driver.CLICK_POSTMESSAGE


# --------------------------------------------------------------------------- #
# 1.1.1 回归：截图失败不能被当成「点击生效」
# --------------------------------------------------------------------------- #
def test_grab_failure_is_unknown_not_success(monkeypatch, no_sleep, fg_ok,
                                             click_counter):
    """截图失败（锁屏/远程断开）→ 只警告无法校验，不宣称生效、不补点。"""
    monkeypatch.setattr(vision, "grab", lambda region=None: None)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    infos, warnings = [], []
    monkeypatch.setattr(automation.logger, "info",
                        lambda msg, *a, **k: infos.append(str(msg)))
    monkeypatch.setattr(automation.logger, "warning",
                        lambda msg, *a, **k: warnings.append(str(msg)))

    ok = automation.click_match(make_match(),
                                {"click_verify": True, "click_retries": 3},
                                procs=["maa.exe"])

    assert ok is True
    assert len(click_counter) == 1               # 无法判定时不做无意义补点
    assert not any("点击生效" in m for m in infos)
    assert any("无法校验" in w for w in warnings)


def test_before_frame_is_grabbed_after_activation(monkeypatch, no_sleep):
    """「点击前」画面必须在激活之后取，否则激活本身就被当成点击生效。"""
    order = []
    monkeypatch.setattr(input_driver, "ensure_foreground",
                        lambda hwnd, timeout=2.0: order.append("fg") or True)
    monkeypatch.setattr(vision, "grab",
                        lambda region=None: order.append("grab") or blank(100))

    def fake_click(x, y, **kw):
        order.append("click")
        return True

    monkeypatch.setattr(input_driver, "click", fake_click)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)
    monkeypatch.setattr(automation.logger, "warning", lambda *a, **k: None)

    automation.click_match(make_match(),
                           {"click_verify": True, "click_retries": 0})

    assert order.index("fg") < order.index("grab")
    assert order.index("grab") < order.index("click")

