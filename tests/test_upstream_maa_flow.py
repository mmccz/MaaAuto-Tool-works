"""MAA adapter lifecycle: inject BEFORE launch, judge from the pre-launch offset.

The 2.0.0 build launched MAA and *then* wrote ``RunDirectly``; MAA reads its config
once at startup, so it never started the queue. These tests pin the order down.
"""

import json
import logging
import time
from pathlib import Path

import pytest

import log_monitor
import run_state
import upstream
import upstream_maa


class FakeLogger:
    def __init__(self):
        self.lines = []

    def _log(self, level, message):
        self.lines.append((level, message))

    def info(self, message):
        self._log("info", message)

    def warning(self, message):
        self._log("warning", message)

    def error(self, message):
        self._log("error", message)

    def debug(self, message):
        self._log("debug", message)


class DummyProc:
    def poll(self):
        return None


def make_maa(tmp_path, *, log_text=""):
    root = tmp_path / "MAA"
    config = root / "config"
    (root / "debug").mkdir(parents=True)
    config.mkdir(parents=True)
    (root / "MAA.exe").write_text("x", encoding="utf-8")
    (config / "gui.json").write_text(
        json.dumps({"Current": "Default", "Global": {}, "Configurations": {"Default": {}}}),
        encoding="utf-8",
    )
    (config / "gui.new.json").write_text(
        json.dumps(
            {
                "Current": "Default",
                "Configurations": {
                    "Default": {
                        "Gui": {
                            "StartUpSettings": {"RunDirectly": False},
                            "RuntimeSettings": {"StartGame": False},
                        },
                        "TaskQueue": [{"TaskType": "StartUp", "Name": "开始唤醒", "IsEnable": True}],
                    }
                },
                "Update": {},
                "AnnouncementInfo": {},
            }
        ),
        encoding="utf-8",
    )
    log = root / "debug" / "gui.log"
    if log_text:
        log.write_text(log_text, encoding="utf-8")
    else:
        log.write_text("", encoding="utf-8")
    return root


def adapter_for(root, **kwargs):
    cfg = {"maa_path": str(root / "MAA.exe"), "control": "inject"}
    return upstream_maa.MaaUpstream(cfg, FakeLogger(), journal_path=root / "journal.json", **kwargs)


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #
def test_prepare_runs_before_launch(tmp_path, monkeypatch):
    root = make_maa(tmp_path)
    adapter = adapter_for(root)
    order = []

    monkeypatch.setattr(
        upstream_maa.MaaInjector, "apply", lambda self: order.append("inject") or []
    )
    monkeypatch.setattr(
        upstream_maa.subprocess, "Popen", lambda *a, **k: order.append("launch") or DummyProc()
    )

    adapter.prepare()
    adapter.launch()

    assert order == ["inject", "launch"], "注入必须在启动之前，否则 MAA 读不到"


def test_log_offset_is_captured_before_launch(tmp_path, monkeypatch):
    root = make_maa(tmp_path, log_text="x" * 100)
    adapter = adapter_for(root)

    def fake_popen(*args, **kwargs):
        # MAA appends its startup banner right after launch: that part must NOT
        # be treated as "already consumed".
        (root / "debug" / "gui.log").write_text("x" * 100 + "startup", encoding="utf-8")
        return DummyProc()

    monkeypatch.setattr(upstream_maa.subprocess, "Popen", fake_popen)

    adapter.launch()

    assert adapter._log_offset == 100


# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #
def test_wait_ready_returns_when_a_ready_marker_appears(tmp_path, monkeypatch):
    root = make_maa(tmp_path, log_text="")
    adapter = adapter_for(root)
    adapter._log_offset = 0
    monkeypatch.setattr(upstream_maa.process_utils, "is_process_running", lambda names: True)

    def fake_popen(*args, **kwargs):
        (root / "debug" / "gui.log").write_text(
            "[2026-11-01 21:00:00.000][INF][Bootstrapper] <2> MaaAssistantArknights GUI started\n",
            encoding="utf-8",
        )
        return DummyProc()

    monkeypatch.setattr(upstream_maa.subprocess, "Popen", fake_popen)
    adapter.launch()

    assert adapter.wait_ready(timeout=2) is True


def test_wait_ready_fails_when_the_process_dies(tmp_path, monkeypatch):
    root = make_maa(tmp_path)
    adapter = adapter_for(root)
    adapter._log_offset = 0
    monkeypatch.setattr(upstream_maa.process_utils, "is_process_running", lambda names: False)
    monkeypatch.setattr(upstream_maa.subprocess, "Popen", lambda *a, **k: DummyProc())

    adapter.launch()

    with pytest.raises(upstream.UpstreamError) as excinfo:
        adapter.wait_ready(timeout=1)
    assert excinfo.value.code == "LAUNCH_FAIL"


# --------------------------------------------------------------------------- #
# "It never started" guard
# --------------------------------------------------------------------------- #
def test_missing_start_marker_fails_fast(tmp_path, monkeypatch):
    root = make_maa(tmp_path, log_text="")
    rules = log_monitor.LogRules.load()
    rules.maa_start_grace = 0
    adapter = adapter_for(root, rules=rules)
    adapter._log_offset = 0
    adapter._started_at = None
    adapter._launched_at = time.monotonic() - 5
    adapter.exe = root / "MAA.exe"
    monkeypatch.setattr(upstream_maa.process_utils, "is_process_running", lambda names: True)

    outcome = adapter.wait_signal(time.monotonic() + 3)

    assert outcome.code == "NOT_STARTED"
    assert "没有开始任务" in outcome.message


def test_start_marker_disarms_the_guard(tmp_path, monkeypatch):
    root = make_maa(tmp_path, log_text="")
    rules = log_monitor.LogRules.load()
    rules.maa_start_grace = 0
    adapter = adapter_for(root, rules=rules)
    adapter._log_offset = 0
    adapter._started_at = None
    adapter._launched_at = time.monotonic() - 5
    adapter.exe = root / "MAA.exe"
    (root / "debug" / "gui.log").write_text(
        "[2026-11-01 21:00:01.000][INF][TaskQueueViewModel] <2> 正在连接模拟器……\n",
        encoding="utf-8",
    )
    # Pretend the process exits right after: the judge finishes instead of NOT_STARTED.
    monkeypatch.setattr(upstream_maa.process_utils, "is_process_running", lambda names: False)

    outcome = adapter.wait_signal(time.monotonic() + 2)

    assert outcome.code != "NOT_STARTED"
    assert outcome.code == "LOG_UNKNOWN"


# --------------------------------------------------------------------------- #
# Judge start tracking
# --------------------------------------------------------------------------- #
def test_judge_marks_started_on_real_log_markers():
    rules = log_monitor.LogRules.load()
    for marker in ("正在连接模拟器……", 'Index 0, Type "StartUp"', "called from LinkStartWithTasks"):
        judge = log_monitor.MaaLogJudge(rules)
        judge.feed(log_monitor.LogLine(message=marker))
        assert judge.started is True, marker


def test_judge_is_not_started_by_unrelated_lines():
    rules = log_monitor.LogRules.load()
    judge = log_monitor.MaaLogJudge(rules)
    judge.feed(log_monitor.LogLine(message="HTTP: OK GET https://example.invalid"))
    assert judge.started is False
