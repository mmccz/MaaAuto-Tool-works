"""Round journal: state transitions, resume and the repeated-failure breaker."""

import json

import run_state


def test_begin_writes_a_journal(tmp_path):
    store = run_state.RunStateStore(tmp_path)
    record = store.begin("run-1")
    assert record.run_id == "run-1"
    assert run_state.STATE_IDLE == record.state
    saved = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
    assert saved["run_id"] == "run-1"


def test_save_and_load_round_trip(tmp_path):
    store = run_state.RunStateStore(tmp_path)
    record = store.begin("run-2")
    record.state = run_state.STATE_RUNNING
    record.phase = run_state.PHASE_MAA
    record.completed_phases = [run_state.PHASE_MAA]
    store.save(record)

    loaded = store.load()
    assert loaded.run_id == "run-2"
    assert loaded.state == run_state.STATE_RUNNING
    assert loaded.completed_phases == [run_state.PHASE_MAA]


def test_corrupt_journal_is_ignored(tmp_path):
    (tmp_path / "run_state.json").write_text("{not json", encoding="utf-8")
    store = run_state.RunStateStore(tmp_path)
    assert store.load() is None
    fresh = store.resume()
    assert fresh.state == run_state.STATE_IDLE


def test_resume_keeps_an_unfinished_round_and_restarts_a_finished_one(tmp_path):
    store = run_state.RunStateStore(tmp_path)
    record = store.begin("run-3")
    record.state = run_state.STATE_RUNNING
    record.completed_phases = [run_state.PHASE_MAA]
    store.save(record)

    resumed = store.resume("run-3")
    assert resumed.run_id == "run-3"
    assert resumed.completed_phases == [run_state.PHASE_MAA]

    record.state = run_state.STATE_SUCCESS
    store.save(record)
    restarted = store.resume("run-3")
    assert restarted.completed_phases == []


def test_resume_with_a_different_run_id_starts_over(tmp_path):
    store = run_state.RunStateStore(tmp_path)
    record = store.begin("run-4")
    record.state = run_state.STATE_RUNNING
    store.save(record)
    assert store.resume("other").run_id == "other"


def test_repeated_failure_breaker_counts_a_streak(tmp_path):
    store = run_state.RunStateStore(tmp_path)
    record = store.begin("run-5")
    for index in range(3):
        store.record_failure(record, "ADB_FAIL")
        assert store.repeated_failure(record, "ADB_FAIL") is (index == 2)
    # A different code breaks the streak.
    store.record_failure(record, "TASK_ERROR")
    assert store.repeated_failure(record, "ADB_FAIL") is False


def test_terminal_states_are_the_four_that_end_a_round():
    assert run_state.TERMINAL_STATES == {
        run_state.STATE_SUCCESS,
        run_state.STATE_FAILED,
        run_state.STATE_TIMEOUT,
        run_state.STATE_ABORTED,
    }
    assert run_state.STATE_RUNNING not in run_state.TERMINAL_STATES


def test_clear_removes_the_journal(tmp_path):
    store = run_state.RunStateStore(tmp_path)
    store.begin("run-6")
    store.clear()
    assert store.load() is None
