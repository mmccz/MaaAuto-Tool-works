"""「测试找图」「截取模板」前必须先把 MAA / MaaEnd 窗口前置。

用户实测：点「测试找图」永远未命中——因为截屏时 MaaAuto 的窗口正压在 MAA
上面；截取模板同理，框到的其实是自己的界面。这里固定模板→进程的映射，
以及两个入口调用前置的顺序。
"""

import os
import types

import pytest

import automation


# --------------------------------------------------------------------------- #
# 模板 → 进程
# --------------------------------------------------------------------------- #
def test_template_process_uses_config_paths():
    cfg = {"maa_path": r"E:\MAA\MAA.exe",
           "maaend_path": "E:/MaaEnd/MaaEnd.exe"}
    assert automation.template_process("maa_start.png", cfg) == "MAA.exe"
    assert automation.template_process("maaend_start.png", cfg) == "MaaEnd.exe"


def test_template_process_custom_and_missing_are_empty():
    assert automation.template_process("my_button.png", {}) == ""
    assert automation.template_process("maa_start.png", {"maa_path": "  "}) == ""
    assert automation.template_process("maa_start.png", None) == ""


def test_template_process_case_insensitive():
    cfg = {"maa_path": r"E:\MAA\MAA.exe"}
    assert automation.template_process("MAA_START.PNG", cfg) == "MAA.exe"


# --------------------------------------------------------------------------- #
# 测试找图：先前置再截图
# --------------------------------------------------------------------------- #
def test_match_test_brings_each_target_to_front_first(monkeypatch):
    import vision
    import process_utils
    from ui.pages import settings_page

    events = []

    def fake_front(names):
        events.append(("front", names[0]))
        return True

    def fake_find(paths, region=None, **kwargs):
        events.append(("find", os.path.basename(paths[0])))
        return None

    monkeypatch.setattr(process_utils, "bring_process_to_front", fake_front)
    monkeypatch.setattr(process_utils, "interruptible_sleep", lambda s: None)
    monkeypatch.setattr(vision, "find_any", fake_find)

    cfg = {"maa_path": r"E:\MAA\MAA.exe",
           "maaend_path": r"E:\MaaEnd\MaaEnd.exe"}
    results = settings_page._match_test_worker(cfg)

    assert [e[0] for e in events] == ["front", "find", "front", "find"]
    assert events[0][1] == "MAA.exe"
    assert events[2][1] == "MaaEnd.exe"
    assert [r["process"] for r in results] == ["MAA.exe", "MaaEnd.exe"]


def test_match_test_skips_foreground_when_path_missing(monkeypatch):
    import vision
    import process_utils
    from ui.pages import settings_page

    events = []
    monkeypatch.setattr(process_utils, "bring_process_to_front",
                        lambda names: events.append(names) or True)
    monkeypatch.setattr(process_utils, "interruptible_sleep", lambda s: None)
    monkeypatch.setattr(vision, "find_any", lambda *a, **k: None)

    settings_page._match_test_worker({})
    assert events == []


def test_match_test_survives_foreground_error(monkeypatch):
    import vision
    import process_utils
    from ui.pages import settings_page

    def boom(names):
        raise RuntimeError("窗口没了")

    monkeypatch.setattr(process_utils, "bring_process_to_front", boom)
    monkeypatch.setattr(process_utils, "interruptible_sleep", lambda s: None)
    monkeypatch.setattr(vision, "find_any", lambda *a, **k: None)

    results = settings_page._match_test_worker(
        {"maa_path": r"E:\MAA\MAA.exe"})
    # 前置失败不能让「测试找图」整体崩掉
    assert results and results[0]["error"] is None


# --------------------------------------------------------------------------- #
# 截取模板：同样先前置
# --------------------------------------------------------------------------- #
def _fake_dialog(cfg):
    """只借 TemplateCaptureDialog 的方法，不构造 Qt 控件。"""
    from ui.template_capture import TemplateCaptureDialog

    class _FakeDialog(TemplateCaptureDialog):
        def __init__(self, config):
            self.config = config

    return _FakeDialog(cfg)


def test_capture_target_process_mapping():
    from ui.template_capture import TemplateCaptureDialog

    dlg = _fake_dialog({"maa_path": r"E:\MAA\MAA.exe"})
    assert TemplateCaptureDialog._target_process(dlg, "maa_start.png") == "MAA.exe"
    assert TemplateCaptureDialog._target_process(dlg, "custom.png") == ""


def test_capture_brings_target_to_front(monkeypatch):
    import process_utils
    from ui.template_capture import TemplateCaptureDialog

    events = []
    monkeypatch.setattr(process_utils, "bring_process_to_front",
                        lambda names: events.append(names[0]) or True)
    monkeypatch.setattr(process_utils, "interruptible_sleep", lambda s: None)

    dlg = _fake_dialog({"maaend_path": r"E:\MaaEnd\MaaEnd.exe"})
    proc = TemplateCaptureDialog._bring_target_front(dlg, "maaend_start.png")
    assert proc == "MaaEnd.exe"
    assert events == ["MaaEnd.exe"]


def test_capture_without_target_does_not_touch_windows(monkeypatch):
    import process_utils
    from ui.template_capture import TemplateCaptureDialog

    monkeypatch.setattr(process_utils, "bring_process_to_front",
                        lambda names: pytest.fail("自定义模板不该前置任何窗口"))

    dlg = _fake_dialog({})
    assert TemplateCaptureDialog._bring_target_front(dlg, "custom.png") == ""
