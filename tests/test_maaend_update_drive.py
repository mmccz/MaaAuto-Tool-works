"""MaaEnd update takeover: drive MXU's own installer between rounds.

MXU cannot be told "don't update" from config, and its pending state lives in the
WebView localStorage; the only observable is its log. So a downloaded, pending update
is installed in a dedicated session (MaaEnd started WITHOUT --autostart), and a merely
available version is reported, never clicked.
"""

import time

import maaend_update
import run_state
import upstream


def make_root(tmp_path, log_text=""):
    root = tmp_path / "MaaEnd"
    (root / "debug").mkdir(parents=True)
    (root / "MaaEnd.exe").write_text("x", encoding="utf-8")
    if log_text:
        (root / "debug" / "2026-11-01-4.log").write_text(log_text, encoding="utf-8")
    return root


class DummyProc:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def run_session(root, monkeypatch, *, proc=None, timeout=2, poll=0.01):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append(args)
        return proc or DummyProc(exit_code=0)

    monkeypatch.setattr(maaend_update.subprocess, "Popen", fake_popen)
    result = maaend_update.run_update_session(
        root, root / "MaaEnd.exe", None, timeout=timeout, poll=poll
    )
    return result, calls


def test_update_session_launches_without_autostart(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    result, calls = run_session(root, monkeypatch)

    assert calls, "必须真的拉起 MaaEnd"
    assert "--autostart" not in calls[0]
    assert "--quit-after-run" not in calls[0]
    assert result.state in ("applied", "failed", "timeout")


def test_applied_marker_is_detected(tmp_path, monkeypatch):
    root = make_root(tmp_path, log_text="")
    log = root / "debug" / "2026-11-01-5.log"

    class Proc:
        def poll(self):
            log.write_text("已读取更新完成信息: 2.15.0\n", encoding="utf-8")
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(maaend_update.subprocess, "Popen", lambda *a, **k: Proc())
    result = maaend_update.run_update_session(
        root, root / "MaaEnd.exe", None, timeout=1, poll=0.01
    )

    assert result.state == "applied"
    assert result.version == "2.15.0"


def test_timeout_is_reported_without_raising(tmp_path, monkeypatch):
    root = make_root(tmp_path)

    class Alive:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(maaend_update.subprocess, "Popen", lambda *a, **k: Alive())
    result = maaend_update.run_update_session(
        root, root / "MaaEnd.exe", None, timeout=0.05, poll=0.01
    )
    assert result.state == "timeout"


def test_launch_failure_is_reported(tmp_path, monkeypatch):
    root = make_root(tmp_path)

    def boom(*args, **kwargs):
        raise OSError("740 请求的操作需要提升")

    monkeypatch.setattr(maaend_update.subprocess, "Popen", boom)
    result = maaend_update.run_update_session(root, root / "MaaEnd.exe", None, timeout=1)
    assert result.state == "failed"
    assert "MaaEnd" in result.message


# --------------------------------------------------------------------------- #
# Orchestrator hook
# --------------------------------------------------------------------------- #
class FakeEnd:
    name = "MaaEnd"

    def __init__(self, state="pending", applied="applied"):
        self.calls = []
        self._state = state
        self._applied = applied

    def preflight(self):
        return []

    def prepare(self):
        self.calls.append("prepare")

    def launch(self):
        self.calls.append("launch")

    def wait_ready(self, timeout=None):
        self.calls.append("wait_ready")

    def wait_signal(self, deadline, on_progress=None):
        return upstream.Outcome(state=run_state.STATE_SUCCESS)

    def stop(self, graceful=True):
        pass

    def cleanup(self):
        pass

    def update_state(self):
        return self._state, "2.15.0", "log"

    def apply_pending_update(self):
        self.calls.append("update")
        return maaend_update.UpdateResult(self._applied, "2.15.0", "done")


def build_runner(tmp_path, adapter, policy=None):
    import orchestrator
    import run_state as rs

    cfg = {"control": "inject", "retry": 0, "game_exit_timeout": 60,
           "maa_path": "", "maaend_path": "MaaEnd.exe"}
    if policy:
        cfg["update_policy"] = policy
    return orchestrator.Orchestrator(
        cfg,
        type("L", (), {m: staticmethod(lambda *a, **k: None) for m in ("info", "warning", "error", "success")})(),
        store=rs.RunStateStore(tmp_path),
        upstreams={rs.PHASE_MAAEND: adapter},
        sleep=lambda s: None,
    )


def test_pending_update_is_applied_before_the_phase(tmp_path):
    adapter = FakeEnd(state="pending")
    result = build_runner(tmp_path, adapter).run()

    assert result.status == "成功"
    assert "update" in adapter.calls
    assert adapter.calls.index("update") < adapter.calls.index("launch")


def test_manual_policy_skips_the_update_session(tmp_path):
    adapter = FakeEnd(state="pending")
    build_runner(tmp_path, adapter, policy="manual").run()
    assert "update" not in adapter.calls


def test_available_update_is_not_driven(tmp_path):
    adapter = FakeEnd(state="available")
    build_runner(tmp_path, adapter).run()
    assert "update" not in adapter.calls
