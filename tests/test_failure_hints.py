"""Next-step hints when template matching fails, and fast-fail for off-screen windows (1.4.4).

Two real incidents (2026-10-31 simulation test):

* BUG-01: MAA 6.21 changed how the Link Start button renders; the old bundled template
  peaked at 0.74, so all three 60-second attempts timed out. The log only said
  "template search timed out: maa_start.png", so the tester had no idea that a button
  plainly visible on screen still needed its template re-captured.
* RUN-08: the window was dragged off every monitor, captures were all black borders,
  and matching waited out the full timeout for nothing.

No real screen capture or real clicks here: regions, match results and screen rects
are all replaced.
"""

import json
import os
import sys

import pytest

import automation
import process_utils
import vision

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MaaAutoProject")
RES = os.path.join(APP_DIR, "resources")


# --------------------------------------------------------------------------- #
# visible_ratio: off-screen detection
# --------------------------------------------------------------------------- #
def test_visible_ratio_fully_inside():
    assert process_utils.visible_ratio((100, 100, 500, 400), (0, 0, 1920, 1080)) == 1.0


def test_visible_ratio_half_out():
    # Width 400, only 200 inside the screen
    assert process_utils.visible_ratio((-200, 0, 200, 100), (0, 0, 1920, 1080)) == 0.5


def test_visible_ratio_completely_outside():
    assert process_utils.visible_ratio((3000, 3000, 3300, 3400), (0, 0, 1920, 1080)) == 0.0


def test_visible_ratio_negative_secondary_monitor_is_inside():
    # A secondary monitor on the left (negative coords) must not be misjudged as off-screen
    screen = (-1920, 0, 2560, 1440)
    assert process_utils.visible_ratio((-1800, 100, -1000, 900), screen) == 1.0


def test_visible_ratio_unknown_screen_does_not_block(monkeypatch):
    # With no screen size available, keep the old behavior (1.0); an API failure must not block the task
    monkeypatch.setattr(process_utils, "virtual_screen_rect", lambda: None)
    assert process_utils.visible_ratio((3000, 3000, 3300, 3400)) == 1.0


# --------------------------------------------------------------------------- #
# find_and_click: three failure kinds, each with a clear reason
# --------------------------------------------------------------------------- #
def _no_click(monkeypatch):
    import input_driver
    monkeypatch.setattr(input_driver, "click", lambda *a, **k: True)
    monkeypatch.setattr(automation, "_save_failure_screenshot", lambda *a, **k: None)
    monkeypatch.setattr(automation, "check_interrupt", lambda: None)
    monkeypatch.setattr(automation, "interruptible_sleep", lambda s: None)


def test_missing_template_raises_file_error(monkeypatch):
    monkeypatch.setattr(automation, "template_paths", lambda name, cfg: [])
    with pytest.raises(automation.TemplateMissing) as ei:
        automation.find_and_click("maa_start.png", {}, timeout=0.05)
    msg = str(ei.value)
    assert "设置 → 模板" in msg
    assert "maa_start.png" in msg


def test_offscreen_window_fails_fast(monkeypatch):
    _no_click(monkeypatch)
    monkeypatch.setattr(automation, "template_paths",
                        lambda name, cfg: [(os.path.join(RES, name), "builtin")])
    monkeypatch.setattr(automation, "_search_region",
                        lambda cfg, procs: ((3000, 3000, 3300, 3400), 123))
    monkeypatch.setattr(process_utils, "virtual_screen_rect", lambda: (0, 0, 1920, 1080))
    searched = []
    monkeypatch.setattr(vision, "find_any",
                        lambda *a, **k: searched.append(1) or None)

    with pytest.raises(automation.TargetWindowNotVisible) as ei:
        automation.find_and_click("maa_start.png", {}, timeout=5)
    assert searched == []                    # no pointless waiting: the search never ran
    assert "屏幕外" in str(ei.value)


def test_timeout_message_tells_user_to_recapture(monkeypatch):
    _no_click(monkeypatch)
    monkeypatch.setattr(automation, "template_paths",
                        lambda name, cfg: [(os.path.join(RES, name), "builtin")])
    monkeypatch.setattr(automation, "_search_region", lambda cfg, procs: (None, 0))
    monkeypatch.setattr(vision, "find_any", lambda *a, **k: None)

    with pytest.raises(automation.TemplateNotFound) as ei:
        automation.find_and_click("maa_start.png", {"wait_timeout": 0.05})
    msg = str(ei.value)
    assert "设置 → 模板" in msg
    assert "界面样式变了" in msg
    # The new exception is still a TimeoutError, so existing callers are unaffected
    assert isinstance(ei.value, TimeoutError)


def test_minimized_window_is_restored_before_judging(monkeypatch):
    """On Windows a minimized window sits at -32000, so it must not be reported as off-screen right away."""
    _no_click(monkeypatch)
    regions = [((3000, 3000, 3300, 3400), 77), ((10, 10, 500, 400), 77)]
    monkeypatch.setattr(automation, "_search_region",
                        lambda cfg, procs: regions.pop(0) if len(regions) > 1 else regions[0])
    monkeypatch.setattr(automation, "_try_restore_window", lambda hwnd: True)
    monkeypatch.setattr(process_utils, "virtual_screen_rect", lambda: (0, 0, 1920, 1080))
    monkeypatch.setattr(automation, "template_paths",
                        lambda name, cfg: [(os.path.join(RES, name), "builtin")])
    seen = []

    def fake_find(paths, region=None, **kw):
        seen.append(region)
        return vision.Match(left=100, top=100, width=132, height=66,
                            score=0.97, scale=1.0, template="maa_start.png")

    monkeypatch.setattr(vision, "find_any", fake_find)
    assert automation.find_and_click("maa_start.png", {}, timeout=5) is not False
    assert seen and seen[0] == (10, 10, 500, 400)


# --------------------------------------------------------------------------- #
# execute_workflow: the failure kind lands in last_failure, the UI shows a hint from it
# --------------------------------------------------------------------------- #
@pytest.fixture
def quiet_workflow(monkeypatch):
    monkeypatch.setattr(automation, "_handle_foreground_action", lambda c, l: None)
    monkeypatch.setattr(automation, "send_task_report", lambda *a, **k: None)
    monkeypatch.setattr(automation, "interruptible_sleep", lambda s: None)


def test_workflow_records_template_failure(monkeypatch, quiet_workflow):
    attempts = []

    def fake_phase(config, logger):
        attempts.append(1)
        raise automation.TemplateNotFound("找图超时，未能找到: maa_start.png")

    monkeypatch.setattr(automation, "run_maa_phase", fake_phase)
    status = automation.execute_workflow(
        {"maa_path": "MAA.exe", "retry_times": 2, "retry_interval": 0},
        automation.logger)
    assert status == "报错"
    assert len(attempts) == 2
    assert automation.last_failure()["kind"] == automation.FAILURE_TEMPLATE
    assert "maa_start.png" in automation.last_failure()["message"]


def test_workflow_records_offscreen_without_retry(monkeypatch, quiet_workflow):
    attempts = []

    def fake_phase(config, logger):
        attempts.append(1)
        raise automation.TargetWindowNotVisible("目标窗口几乎在屏幕外")

    monkeypatch.setattr(automation, "run_maa_phase", fake_phase)
    status = automation.execute_workflow(
        {"maa_path": "MAA.exe", "retry_times": 3, "retry_interval": 0},
        automation.logger)
    assert status == "报错"
    assert len(attempts) == 1                 # environment problems are not retried
    assert automation.last_failure()["kind"] == automation.FAILURE_OFFSCREEN


def test_workflow_success_clears_previous_failure(monkeypatch, quiet_workflow):
    automation._set_failure(automation.FAILURE_TEMPLATE, "上一轮的旧失败")
    monkeypatch.setattr(automation, "run_maa_phase", lambda c, l: True)
    monkeypatch.setattr(automation, "run_maaend_phase", lambda c, l: True)
    status = automation.execute_workflow(
        {"maa_path": "MAA.exe", "maaend_path": "MaaEnd.exe", "retry_times": 1},
        automation.logger)
    assert status == "成功"
    assert automation.last_failure()["kind"] == ""


# --------------------------------------------------------------------------- #
# Bundled template: MAA 6.21 button size (the old 144×68 template no longer matches)
# --------------------------------------------------------------------------- #
def test_builtin_maa_template_matches_new_ui():
    import cv2
    path = os.path.join(RES, "maa_start.png")
    img = cv2.imdecode(__import__("numpy").fromfile(path, dtype="uint8"),
                       cv2.IMREAD_COLOR)
    assert img is not None, "内置模板缺失"
    h, w = img.shape[:2]
    assert (w, h) == (132, 66)
    assert os.path.getsize(path) > 3000      # not an LFS pointer / empty stub
    assert os.path.getsize(os.path.join(RES, "maaend_start.png")) > 3000


# --------------------------------------------------------------------------- #
# Tray hint strings: both failure kinds must exist in Chinese and English
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", ["notify.task_failed_template",
                                 "notify.task_failed_offscreen"])
def test_notify_hint_keys_exist_in_both_languages(key):
    texts = {}
    for lang in ("zh_CN", "en_US"):
        with open(os.path.join(APP_DIR, "i18n", f"{lang}.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        assert data.get(key), f"{lang} 缺少 {key}"
        texts[lang] = data[key]
    assert texts["zh_CN"] != texts["en_US"]
