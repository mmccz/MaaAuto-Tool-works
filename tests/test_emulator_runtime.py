"""An emulator that exits right after launch must be judged a failure, not a success.

From a real 1.0.3 log: the click had taken effect, but MAA could not reach MuMu
(ADB 10061), MuMu exited after 15 seconds, and the tool still reported "success" — the
user thought the run had completed.
"""

import pytest

import automation


# --------------------------------------------------------------------------- #
# Pure predicate helpers
# --------------------------------------------------------------------------- #
def test_short_runtime_raises():
    with pytest.raises(RuntimeError) as ei:
        automation._check_emulator_runtime(uptime=15, min_runtime=60)
    msg = str(ei.value)
    assert "15 秒" in msg
    assert "16384" in msg          # hints at MuMu's default port
    assert "asst.log" in msg       # points at MAA's own log


def test_long_runtime_ok():
    assert automation._check_emulator_runtime(1200, 60) is None


def test_threshold_disabled():
    assert automation._check_emulator_runtime(1, 0) is None
    assert automation._check_emulator_runtime(1, None) is None


def test_bad_threshold_is_ignored():
    assert automation._check_emulator_runtime(1, "abc") is None


def test_runtime_equal_to_threshold_is_ok():
    assert automation._check_emulator_runtime(60, 60) is None


# --------------------------------------------------------------------------- #
# run_maa_phase orchestration
# --------------------------------------------------------------------------- #
@pytest.fixture
def maa_env(tmp_path, monkeypatch):
    maa = tmp_path / "MAA.exe"
    maa.write_bytes(b"x")
    calls = {}

    monkeypatch.setattr(automation, "is_process_running", lambda procs: calls.get("running", False))
    monkeypatch.setattr(automation, "_launch_program", lambda path, log: calls.setdefault("launched", path))
    monkeypatch.setattr(automation, "interruptible_sleep", lambda s: None)
    monkeypatch.setattr(automation, "find_and_click", lambda *a, **k: calls.setdefault("clicked", True))
    monkeypatch.setattr(automation, "wait_for_process_start", lambda procs, timeout: True)
    monkeypatch.setattr(automation, "wait_for_process_exit", lambda procs, timeout, check_interval=15: True)
    monkeypatch.setattr(automation, "minimize_process_windows", lambda procs: None)
    monkeypatch.setattr(automation, "bring_process_to_front", lambda procs: None)

    clock = {"now": 1000.0}
    monkeypatch.setattr(automation.time, "time", lambda: clock["now"])

    def finish_after(seconds):
        """Simulate wait_for_process_exit consuming `seconds` seconds."""
        def fake_exit(procs, timeout, check_interval=15):
            clock["now"] += seconds
            return True
        monkeypatch.setattr(automation, "wait_for_process_exit", fake_exit)

    return {"maa": str(maa), "calls": calls, "finish_after": finish_after}

def test_maa_phase_fails_when_emulator_dies_immediately(maa_env):
    maa_env["finish_after"](15)
    cfg = {"maa_path": maa_env["maa"], "min_emulator_runtime": 60}

    with pytest.raises(RuntimeError) as ei:
        automation.run_maa_phase(cfg, automation.logger)
    assert "15 秒" in str(ei.value)
    assert maa_env["calls"]["clicked"] is True     # the click itself succeeded


def test_maa_phase_ok_when_emulator_runs_long(maa_env):
    maa_env["finish_after"](1200)
    cfg = {"maa_path": maa_env["maa"], "min_emulator_runtime": 60}
    assert automation.run_maa_phase(cfg, automation.logger) is True


def test_workflow_does_not_retry_environment_failure(monkeypatch, maa_env):
    """An unreachable emulator is an environment problem; retrying 3 times only wastes 6 minutes — it should fail right away."""
    attempts = []

    def fake_phase(config, logger):
        attempts.append(1)
        raise automation.EmulatorStartupFailed("ADB 10061")

    monkeypatch.setattr(automation, "run_maa_phase", fake_phase)
    monkeypatch.setattr(automation, "_handle_foreground_action", lambda c, l: None)
    monkeypatch.setattr(automation, "send_task_report", lambda *a, **k: None)

    status = automation.execute_workflow(
        {"maa_path": maa_env["maa"], "retry_times": 3}, automation.logger)
    assert status == "报错"
    assert len(attempts) == 1          # no retries


def test_workflow_retries_other_failures(monkeypatch, maa_env):
    attempts = []

    def fake_phase(config, logger):
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError("模拟器启动超时")
        return True

    monkeypatch.setattr(automation, "run_maa_phase", fake_phase)
    monkeypatch.setattr(automation, "_handle_foreground_action", lambda c, l: None)
    monkeypatch.setattr(automation, "interruptible_sleep", lambda s: None)
    monkeypatch.setattr(automation, "send_task_report", lambda *a, **k: None)

    status = automation.execute_workflow(
        {"maa_path": maa_env["maa"], "retry_times": 3, "retry_interval": 0},
        automation.logger)
    assert status == "成功"
    assert len(attempts) == 3
