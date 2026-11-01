"""Orchestration: phase order, retry policy, resume and mandatory cleanup.

No screen, no process, no network: the upstreams are fakes and the journal is a
temp file, exactly like the rest of the suite.
"""

import process_utils
import run_state
import upstream
import orchestrator
from orchestrator import Orchestrator


class FakeUpstream:
    name = "Fake"
    control_mode = "inject"

    def __init__(self, name="Fake", outcomes=None, issues=None, raises=None, events=None):
        self.name = name
        self.calls = []
        self.events = events if events is not None else []
        self.outcomes = list(outcomes or [])
        self.issues = list(issues or [])
        self.raises = raises
        self.deadline = None

    def _record(self, action):
        self.calls.append(action)
        self.events.append(f"{self.name}:{action}")

    def preflight(self):
        self._record("preflight")
        return self.issues

    def prepare(self):
        self._record("prepare")

    def launch(self):
        self._record("launch")

    def wait_ready(self, timeout=None):
        self._record("wait_ready")
        return True

    def wait_signal(self, deadline, on_progress=None):
        self._record("wait_signal")
        self.deadline = deadline
        if self.raises is not None:
            raise self.raises
        if self.outcomes:
            return self.outcomes.pop(0)
        return upstream.Outcome(state=run_state.STATE_FAILED, code="LOG_UNKNOWN")

    def stop(self, graceful=True):
        self._record("stop")

    def cleanup(self):
        self._record("cleanup")


def success(name="Fake"):
    return upstream.Outcome(state=run_state.STATE_SUCCESS, message=f"{name} ok")


def store(tmp_path):
    return run_state.RunStateStore(tmp_path)


def build(tmp_path, maa=None, maaend=None, config=None, sleeps=None):
    cfg = {"control": "inject", "game_exit_timeout": 600, "retry": 2,
           "keep_upstream": False, "maa_path": "MAA.exe", "maaend_path": "MaaEnd.exe"}
    cfg.update(config or {})
    upstreams = {}
    if maa is not None:
        upstreams[run_state.PHASE_MAA] = maa
    if maaend is not None:
        upstreams[run_state.PHASE_MAAEND] = maaend
    slept = sleeps if sleeps is not None else []

    runner = Orchestrator(
        cfg,
        FakeLogger(),
        store=store(tmp_path),
        upstreams=upstreams,
        sleep=lambda seconds: slept.append(seconds),
        # One sleep call per backoff keeps the assertions about "how long did we wait"
        # readable; the chunking itself is covered by test_sleep_is_chunked.
        sleep_chunk=3600,
    )
    return runner, slept


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

    def success(self, message):
        self._log("info", message)

    def text(self):
        return "\n".join(m for _, m in self.lines)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_both_phases_run_in_order_and_clean_up(tmp_path):
    maa = FakeUpstream("MAA", [success("MAA")])
    maaend = FakeUpstream("MaaEnd", [success("MaaEnd")])
    runner, _ = build(tmp_path, maa, maaend)

    result = runner.run()

    assert result.status == "成功"
    assert maa.calls[:4] == ["preflight", "prepare", "launch", "wait_ready"]
    assert maaend.calls[:4] == ["preflight", "prepare", "launch", "wait_ready"]
    assert "stop" in maa.calls and "cleanup" in maa.calls
    assert "stop" in maaend.calls and "cleanup" in maaend.calls
    assert result.record.completed_phases == [run_state.PHASE_MAA, run_state.PHASE_MAAEND]


def test_keep_upstream_skips_stop_but_still_cleans_up(tmp_path):
    maa = FakeUpstream("MAA", [success()])
    runner, _ = build(tmp_path, maa, None, config={"keep_upstream": True})

    runner.run()

    assert "stop" not in maa.calls
    assert "cleanup" in maa.calls


# --------------------------------------------------------------------------- #
# Retry policy
# --------------------------------------------------------------------------- #
def test_retryable_failure_is_retried_with_backoff(tmp_path):
    maa = FakeUpstream(
        "MAA",
        [
            upstream.Outcome(state=run_state.STATE_FAILED, code="ADB_FAIL", message="连不上"),
            success(),
        ],
    )
    runner, slept = build(tmp_path, maa, None)

    result = runner.run()

    assert result.status == "成功"
    assert maa.calls.count("launch") == 2
    assert slept == [30]


def test_fatal_issue_stops_the_round_without_retrying(tmp_path):
    maa = FakeUpstream(
        "MAA",
        [success()],
        issues=[upstream.Issue("NO_EXE", "未找到 MAA.exe", "请填写路径")],
    )
    maaend = FakeUpstream("MaaEnd", [success()])
    runner, slept = build(tmp_path, maa, maaend)

    result = runner.run()

    assert result.status == "报错"
    assert "未找到 MAA.exe" in result.message
    assert "launch" not in maa.calls          # never launched
    assert "preflight" not in maaend.calls            # fatal code breaks the chain
    assert slept == []


def test_exhausted_retries_report_the_last_failure(tmp_path):
    outcomes = [
        upstream.Outcome(state=run_state.STATE_FAILED, code="TASK_ERROR", message="失败")
        for _ in range(3)
    ]
    maa = FakeUpstream("MAA", outcomes)
    runner, slept = build(tmp_path, maa, None)

    result = runner.run()

    assert result.status == "报错"
    assert maa.calls.count("launch") == 3
    assert slept == [30, 60]


def test_non_fatal_failure_does_not_cancel_the_next_phase(tmp_path):
    maa = FakeUpstream(
        "MAA",
        [upstream.Outcome(state=run_state.STATE_FAILED, code="PARTIAL", message="部分失败")] * 3,
    )
    maaend = FakeUpstream("MaaEnd", [success()])
    runner, _ = build(tmp_path, maa, maaend)

    result = runner.run()

    assert result.status == "报错"
    assert "launch" in maaend.calls           # MaaEnd still got its turn


def test_repeated_failure_breaker_stops_retrying(tmp_path):
    st = store(tmp_path)
    previous = st.begin("old-run")
    previous.recent_failures = ["ADB_FAIL", "ADB_FAIL"]
    st.save(previous)

    maa = FakeUpstream(
        "MAA",
        [upstream.Outcome(state=run_state.STATE_FAILED, code="ADB_FAIL", message="连不上")] * 3,
    )
    runner, slept = build(tmp_path, maa, None)

    result = runner.run()

    assert result.status == "报错"
    assert maa.calls.count("launch") == 1
    assert "连续" in result.message
    assert slept == []


def test_upstream_error_is_reported_as_a_failure(tmp_path):
    maa = FakeUpstream("MAA", [success()], raises=upstream.UpstreamError("NEED_ADMIN", "需要管理员", "请提权"))
    runner, _ = build(tmp_path, maa, None)

    result = runner.run()

    assert result.status == "报错"
    assert "需要管理员" in result.message
    assert "cleanup" in maa.calls


# --------------------------------------------------------------------------- #
# Abort / resume
# --------------------------------------------------------------------------- #
def test_user_abort_is_not_a_failure(tmp_path):
    maa = FakeUpstream("MAA", raises=process_utils.TaskInterrupted())
    runner, _ = build(tmp_path, maa, None)

    result = runner.run()

    assert result.status == "中止"
    assert "cleanup" in maa.calls


def test_resume_skips_completed_phases(tmp_path):
    st = store(tmp_path)
    record = st.begin("run-resume")
    record.state = run_state.STATE_RUNNING
    record.completed_phases = [run_state.PHASE_MAA]
    st.save(record)

    maa = FakeUpstream("MAA", [success()])
    maaend = FakeUpstream("MaaEnd", [success()])
    runner, _ = build(tmp_path, maa, maaend)

    result = runner.run(resume=True, run_id="run-resume")

    assert result.status == "成功"
    # Skipped phases are never launched, armed or preflighted; cleanup still runs
    # (harmless, and it would undo a leftover injection from the crashed round).
    assert "launch" not in maa.calls
    assert "preflight" not in maa.calls
    assert "stop" not in maa.calls
    assert "launch" in maaend.calls


def test_foreground_hook_runs_once_before_the_phases(tmp_path):
    seen = []
    maa = FakeUpstream("MAA", [success()])
    runner, _ = build(tmp_path, maa, None)
    runner.foreground = lambda cfg, log: seen.append("fg")

    runner.run()

    assert seen == ["fg"]
    assert maa.calls[0] == "preflight"


def test_phase_deadline_uses_the_configured_timeout(tmp_path):
    maa = FakeUpstream("MAA", [success()])
    runner, _ = build(tmp_path, maa, None, config={"game_exit_timeout": 120})
    now = runner.clock()

    runner.run()

    assert maa.deadline is not None
    assert maa.deadline - now >= 120


def test_sleep_is_chunked_so_a_stop_is_noticed(tmp_path):
    maa = FakeUpstream(
        "MAA",
        [upstream.Outcome(state=run_state.STATE_FAILED, code="ADB_FAIL", message="连不上"), success()],
    )
    slept = []
    runner = Orchestrator(
        {"control": "inject", "retry": 1, "game_exit_timeout": 600,
         "maa_path": "MAA.exe", "maaend_path": "MaaEnd.exe"},
        FakeLogger(),
        store=store(tmp_path),
        upstreams={run_state.PHASE_MAA: maa},
        sleep=lambda seconds: slept.append(seconds),
        sleep_chunk=0.5,
    )

    runner.run()

    assert len(slept) > 1
    assert sum(slept) == 30


# --------------------------------------------------------------------------- #
# Per-phase teardown and phase selection (2.0.4)
# --------------------------------------------------------------------------- #
def test_maa_is_stopped_before_maaend_starts(tmp_path):
    """The reported bug: MAA stayed open while MaaEnd was launched."""

    events = []
    maa = FakeUpstream("MAA", [success()], events=events)
    maaend = FakeUpstream("MaaEnd", [success()], events=events)
    runner, _ = build(tmp_path, maa, maaend)

    runner.run()

    assert "MAA:stop" in events
    assert events.index("MAA:stop") < events.index("MaaEnd:prepare"), (
        "MAA 必须先被关掉，再启动 MaaEnd"
    )


def test_a_phase_without_a_path_is_skipped(tmp_path):
    maa = FakeUpstream("MAA", [success()])
    maaend = FakeUpstream("MaaEnd", [success()])
    runner, _ = build(tmp_path, maa, maaend, config={"maaend_path": ""})

    result = runner.run()

    assert result.status == "成功"
    assert "prepare" not in maaend.calls          # not configured -> never touched


def test_no_configured_path_reports_a_clear_error(tmp_path):
    runner, _ = build(
        tmp_path, FakeUpstream("MAA", [success()]), None,
        config={"maa_path": "", "maaend_path": ""},
    )

    result = runner.run()

    assert result.status == "报错"
    assert "没有配置" in result.message


def test_progress_is_logged_only_when_the_count_changes(tmp_path):
    maa = FakeUpstream("MAA", [success()])
    runner, _ = build(tmp_path, maa, None)
    report = runner._progress_printer(maa)
    tasks = [
        {"name": "开始唤醒", "state": "done"},
        {"name": "基建换班", "state": "running"},
    ]

    report(tasks)
    report(tasks)                     # unchanged: must not log again
    report([{"name": "开始唤醒", "state": "done"}, {"name": "基建换班", "state": "done"}])

    progress = [m for lvl, m in runner.logger.lines if "进度" in m]
    assert len(progress) == 2
    assert "1/2" in progress[0] and "刚完成: 开始唤醒" in progress[0]
    assert "2/2" in progress[1]
