"""Tests for the "did the click take effect" verification in click_match.

This targets the core problem in the 1.0.2 field report: the click was sent and the
log looked fine, yet the UI did not react. The verdict is "did the pixels near the
click point change", so vision.grab is swapped for controlled fake frames to drive
the "changed / unchanged" branches precisely.
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
    """Return preset frames in order; keep returning the last one once exhausted."""

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
    """One click takes effect → click only once."""
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
    """First click does nothing (typical: window not active, click swallowed) → retry once and succeed."""
    monkeypatch.setattr(vision, "grab",
                        FakeScreen([blank(100), blank(100), blank(230)]).grab)
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    ok = automation.click_match(make_match(),
                                {"click_verify": True, "click_retries": 1},
                                procs=["maa.exe"])
    assert ok is True
    assert len(click_counter) == 2


def test_click_gives_up_after_retries(monkeypatch, no_sleep, fg_ok, click_counter):
    """When retries run out, stop pushing and return True (the flow continues), but log a warning."""
    monkeypatch.setattr(vision, "grab", lambda region=None: blank(100))
    monkeypatch.setattr(automation, "_resolve_target_window", lambda *a: 42)

    warnings = []
    monkeypatch.setattr(automation.logger, "warning",
                        lambda msg, *a, **k: warnings.append(str(msg)))

    ok = automation.click_match(make_match(),
                                {"click_verify": True, "click_retries": 2},
                                procs=["maa.exe"])
    assert ok is True
    assert len(click_counter) == 3        # 1 initial attempt + 2 retries
    assert any("画面无变化" in w for w in warnings)


def test_foreground_failure_uses_background_click(monkeypatch, no_sleep,
                                                  click_counter):
    """When the foreground cannot be grabbed, do not click blindly: post a background click first, and if it works, leave the mouse alone."""
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
    """The background click had no effect either → still try a real click."""
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
    # 1.1.1: a missing capture no longer returns 999.0 (that read as "frame changed"); None = cannot tell
    assert automation._patch_diff(a, None) is None
    assert automation._patch_diff(a, b[0:5]) is None

    region = automation._patch_region(100, 200)
    assert region == (60, 172, 140, 228)


# --------------------------------------------------------------------------- #
# 1.1.1 regression: click_activate (background clicks only when activation is off)
# --------------------------------------------------------------------------- #
def test_click_activate_off_uses_background_click_only(monkeypatch, no_sleep):
    """click_activate=False → do not activate the window, post background clicks only, never a real click."""
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
    assert activated == []                       # never tried to go foreground
    assert len(clicks) == 1
    assert clicks[0][2]["mode"] == input_driver.CLICK_POSTMESSAGE


def test_click_activate_off_gives_up_when_background_fails(monkeypatch, no_sleep):
    """Activation off and the background click also fails → give up (must never degrade to a real click)."""
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
    assert len(clicks) == 1                      # only the background post was attempted
    assert clicks[0][2]["mode"] == input_driver.CLICK_POSTMESSAGE


# --------------------------------------------------------------------------- #
# 1.1.1 regression: a failed capture must not count as "click took effect"
# --------------------------------------------------------------------------- #
def test_grab_failure_is_unknown_not_success(monkeypatch, no_sleep, fg_ok,
                                             click_counter):
    """Capture failed (locked screen / remote session gone) → only warn that verification is impossible; do not claim success and do not retry."""
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
    assert len(click_counter) == 1               # no pointless retries when the outcome cannot be judged
    assert not any("点击生效" in m for m in infos)
    assert any("无法校验" in w for w in warnings)


def test_before_frame_is_grabbed_after_activation(monkeypatch, no_sleep):
    """The "before" frame must be grabbed after activation, otherwise activation itself looks like the click took effect."""
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

