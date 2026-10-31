"""找图失败时给出「下一步怎么办」，以及窗口离屏时快速失败（1.4.4）。

两个真实事故（2026-10-31 仿真测试）：

* BUG-01：MAA 6.21 改了 Link Start 按钮的渲染，旧内置模板最高只有 0.74，
  三次 60 秒全部超时；日志只有一句「找图超时，未能找到: maa_start.png」，
  测试者不知道「按钮明明在屏幕上」时要重新截模板。
* RUN-08：窗口被拖到所有显示器之外，截图只有黑边，找图白等满超时。

这里不截真实屏幕、不做真实点击：区域、匹配结果、屏幕矩形全部替换。
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
# visible_ratio：屏幕外判定
# --------------------------------------------------------------------------- #
def test_visible_ratio_fully_inside():
    assert process_utils.visible_ratio((100, 100, 500, 400), (0, 0, 1920, 1080)) == 1.0


def test_visible_ratio_half_out():
    # 宽 400，只有 200 在屏幕内
    assert process_utils.visible_ratio((-200, 0, 200, 100), (0, 0, 1920, 1080)) == 0.5


def test_visible_ratio_completely_outside():
    assert process_utils.visible_ratio((3000, 3000, 3300, 3400), (0, 0, 1920, 1080)) == 0.0


def test_visible_ratio_negative_secondary_monitor_is_inside():
    # 副屏在左侧（负坐标）时不能被误判成「屏幕外」
    screen = (-1920, 0, 2560, 1440)
    assert process_utils.visible_ratio((-1800, 100, -1000, 900), screen) == 1.0


def test_visible_ratio_unknown_screen_does_not_block(monkeypatch):
    # 拿不到屏幕尺寸时保持旧行为（1.0），不能因为 API 失败就拦下任务
    monkeypatch.setattr(process_utils, "virtual_screen_rect", lambda: None)
    assert process_utils.visible_ratio((3000, 3000, 3300, 3400)) == 1.0


# --------------------------------------------------------------------------- #
# find_and_click：三种失败各自给出明确原因
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
    assert searched == []                    # 没有白等，一次都没去搜索
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
    # 新异常仍按 TimeoutError 处理，旧调用方不受影响
    assert isinstance(ei.value, TimeoutError)


def test_minimized_window_is_restored_before_judging(monkeypatch):
    """最小化窗口在 Windows 里坐标是 -32000，不能直接报「在屏幕外」。"""
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
# execute_workflow：失败类型写进 last_failure，界面据此弹提示
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
    assert len(attempts) == 1                 # 环境问题不重试
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
# 内置模板：MAA 6.21 的按钮尺寸（旧模板 144×68 已经匹配不上）
# --------------------------------------------------------------------------- #
def test_builtin_maa_template_matches_new_ui():
    import cv2
    path = os.path.join(RES, "maa_start.png")
    img = cv2.imdecode(__import__("numpy").fromfile(path, dtype="uint8"),
                       cv2.IMREAD_COLOR)
    assert img is not None, "内置模板缺失"
    h, w = img.shape[:2]
    assert (w, h) == (132, 66)
    assert os.path.getsize(path) > 3000      # 不是 LFS 指针/空壳
    assert os.path.getsize(os.path.join(RES, "maaend_start.png")) > 3000


# --------------------------------------------------------------------------- #
# 托盘提示文案：两种失败都要在中英文里存在
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
