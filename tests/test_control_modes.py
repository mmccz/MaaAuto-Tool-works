"""execute_workflow dispatch: inject (2.0) vs click (1.x), without touching either upstream.

The legacy branch is covered by the 1.x tests; what matters here is that the
`control` switch really routes to the orchestrator and that the status mapping the
UI/report depends on ("成功" / "报错" / "中止") is preserved.
"""

import orchestrator
import run_state

import automation


def make_logger():
    """A real logger (execute_workflow attaches its own capture handler to it)."""

    import logging

    logger = logging.getLogger("MaaAuto.test.control")
    logger.setLevel(logging.INFO)
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


def patch_reporting(monkeypatch):
    """Report sending would hit the network; capture the call instead."""

    reports = []
    monkeypatch.setattr(
        automation,
        "send_task_report",
        lambda *args, **kwargs: reports.append(args),
        raising=False,
    )
    return reports


def test_inject_mode_uses_the_orchestrator(tmp_path, monkeypatch):
    reports = patch_reporting(monkeypatch)
    seen = {}

    class FakeOrchestrator:
        def __init__(self, config, logger, **kwargs):
            seen["config"] = config
            seen["kwargs"] = kwargs

        def run(self, resume=False, run_id=None):
            seen["resume"] = resume
            return orchestrator.RunResult(status="成功", message="", tasks=[])

    monkeypatch.setattr(orchestrator, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(orchestrator, "default_store", lambda: None)

    status = automation.execute_workflow({"control": "inject", "maa_path": "x"}, make_logger())

    assert status == "成功"
    assert "config" in seen
    assert seen["resume"] is False
    assert reports, "报告仍然要发出去"


def test_inject_mode_forwards_the_resume_hint(tmp_path, monkeypatch):
    patch_reporting(monkeypatch)
    seen = {}

    class FakeOrchestrator:
        def __init__(self, config, logger, **kwargs):
            pass

        def run(self, resume=False, run_id=None):
            seen["resume"] = resume
            seen["run_id"] = run_id
            return orchestrator.RunResult(status="成功")

    monkeypatch.setattr(orchestrator, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(orchestrator, "default_store", lambda: None)

    automation.execute_workflow(
        {"control": "inject", "_resume_run": True, "_run_id": "abc"}, make_logger()
    )

    assert seen == {"resume": True, "run_id": "abc"}


def test_inject_failure_sets_the_last_failure_message(tmp_path, monkeypatch):
    patch_reporting(monkeypatch)

    class FakeOrchestrator:
        def __init__(self, config, logger, **kwargs):
            pass

        def run(self, resume=False, run_id=None):
            return orchestrator.RunResult(status="报错", message="NO_EXE: 未找到 MAA.exe")

    monkeypatch.setattr(orchestrator, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(orchestrator, "default_store", lambda: None)

    status = automation.execute_workflow({"control": "inject"}, make_logger())

    assert status == "报错"
    assert "未找到 MAA.exe" in automation.last_failure().get("message", "")


def test_abort_is_reported_as_aborted(tmp_path, monkeypatch):
    patch_reporting(monkeypatch)

    class FakeOrchestrator:
        def __init__(self, config, logger, **kwargs):
            pass

        def run(self, resume=False, run_id=None):
            return orchestrator.RunResult(status="中止", message="用户中止")

    monkeypatch.setattr(orchestrator, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(orchestrator, "default_store", lambda: None)

    assert automation.execute_workflow({"control": "inject"}, make_logger()) == "中止"


def test_missing_control_key_falls_back_to_the_legacy_path(tmp_path, monkeypatch):
    """Old configs (no `control`) keep the 1.x behaviour until migration runs."""

    patch_reporting(monkeypatch)
    called = {"legacy": False}

    def fake_legacy(config, logger):
        called["legacy"] = True
        return "成功"

    monkeypatch.setattr(automation, "_execute_legacy", fake_legacy)

    status = automation.execute_workflow({}, make_logger())

    assert status == "成功"
    assert called["legacy"] is True


def test_click_mode_runs_the_legacy_path(tmp_path, monkeypatch):
    patch_reporting(monkeypatch)
    called = {"legacy": False}

    def fake_legacy(config, logger):
        called["legacy"] = True
        return "成功"

    monkeypatch.setattr(automation, "_execute_legacy", fake_legacy)

    assert automation.execute_workflow({"control": "click"}, make_logger()) == "成功"
    assert called["legacy"] is True


def test_report_is_sent_even_when_the_run_raises(tmp_path, monkeypatch):
    reports = patch_reporting(monkeypatch)

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    # A constructor failure happens inside _execute_inject; execute_workflow must
    # swallow it (status "报错") and still send the report - a crash must neither
    # lose the notification nor escape into the worker thread.
    monkeypatch.setattr(orchestrator, "Orchestrator", Boom)
    monkeypatch.setattr(orchestrator, "default_store", lambda: None)

    status = automation.execute_workflow({"control": "inject"}, make_logger())

    assert status == "报错"
    assert reports, "即使异常，报告也必须发出"
