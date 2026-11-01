"""Log judgement: the 2.0 replacement for "the emulator exited, must be fine".

The synthetic lines below are copied from a real MAA 6.21 `debug/gui.log`
(2026-11-01), including the continuation lines that carry the failed task names.
"""

import json

import log_monitor
import run_state


def rules():
    return log_monitor.LogRules.load()


def maa_line(stamp, level, module, message, extra=()):
    return log_monitor.LogLine(
        timestamp=log_monitor.LogTail._parse_time(stamp),
        level=level,
        module=module,
        message=message,
        extra=list(extra),
    )


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def test_builtin_rules_load():
    loaded = rules()
    assert loaded.source == "builtin"
    assert "任务已全部完成！" in loaded.maa_success
    assert loaded.maa_task_done == "完成任务: "
    assert loaded.maaend_task_done == "任务完成: "


def test_rules_reject_an_unknown_schema_and_fall_back():
    broken = '{"schema_version": 99, "maa": {"success": ["NOPE"]}}'
    loaded = log_monitor.LogRules.load(remote_text=broken)
    assert loaded.source == "builtin"
    assert "任务已全部完成！" in loaded.maa_success


def test_rules_accept_a_compatible_remote_copy():
    remote = (
        '{"schema_version": 1, "updated": "2026-11-02",'
        ' "maa": {"success": ["任务全部完成啦"], "failure": [], "issues": []},'
        ' "maaend": {"task_done": "完成: "}}'
    )
    loaded = log_monitor.LogRules.load(remote_text=remote)
    assert loaded.source == "remote"
    assert loaded.maa_success == ["任务全部完成啦"]


def test_missing_rules_file_falls_back_to_an_empty_table(tmp_path):
    loaded = log_monitor.LogRules.load(path=tmp_path / "nope.json")
    assert loaded.maa_success == []


# --------------------------------------------------------------------------- #
# MAA judge
# --------------------------------------------------------------------------- #
def test_success_line_finishes_the_round():
    judge = log_monitor.MaaLogJudge(rules())
    outcome = judge.feed(
        maa_line("2026-11-01 15:08:02", "INF", "TaskQueueViewModel", "任务已全部完成！")
    )
    assert outcome is not None
    assert outcome.state == run_state.STATE_SUCCESS
    assert judge.finish().state == run_state.STATE_SUCCESS


def test_failure_terminator_collects_continuation_names():
    judge = log_monitor.MaaLogJudge(rules())
    judge.feed(
        maa_line(
            "2026-10-18 00:20:28",
            "ERR",
            "TaskQueueViewModel",
            "任务已结束，以下任务出现错误:",
            ["自动肉鸽", "理智作战"],
        )
    )
    outcome = judge.finish()
    assert outcome.state == run_state.STATE_FAILED
    assert outcome.code == "PARTIAL"
    names = {t["name"] for t in outcome.tasks}
    assert names == {"自动肉鸽", "理智作战"}


def test_older_failure_wording_is_still_recognised():
    judge = log_monitor.MaaLogJudge(rules())
    judge.feed(
        maa_line("2026-11-01 10:00:00", "INF", "TaskQueueViewModel", "任务已完成，但出现错误！")
    )
    assert judge.finish().state == run_state.STATE_FAILED


def test_adb_failure_in_a_continuation_line_is_retryable():
    judge = log_monitor.MaaLogJudge(rules())
    judge.feed(maa_line("2026-10-17 10:52:29", "ERR", "TaskQueueViewModel", "连接失败", ["请 ｢检查连接设置｣ → ｢尝试重启模拟器与 ADB｣"]))
    assert judge.feed(maa_line("2026-10-17 10:52:29", "INF", "TaskQueueViewModel", "已停止")) is None
    outcome = judge.finish()
    assert outcome.code == "ADB_FAIL"
    assert outcome.retryable is True


def test_task_lines_are_collected_even_while_running():
    judge = log_monitor.MaaLogJudge(rules())
    judge.feed(maa_line("2026-11-01 12:00:01", "INF", "TaskQueueViewModel", "完成任务: 开始唤醒"))
    judge.feed(maa_line("2026-11-01 12:00:02", "ERR", "TaskQueueViewModel", "任务出错: 信用收支"))
    assert judge.task_list() == [
        {"name": "开始唤醒", "state": "done"},
        {"name": "信用收支", "state": "failed"},
    ]


def test_unrecognised_log_is_unknown_not_success():
    judge = log_monitor.MaaLogJudge(rules())
    judge.feed(maa_line("2026-11-01 12:00:00", "INF", "Bootstrapper", "something we do not know"))
    outcome = judge.finish(exited=True)
    assert outcome.state == run_state.STATE_FAILED
    assert outcome.code == "LOG_UNKNOWN"


def test_timestamp_gate_skips_lines_from_before_the_round():
    import datetime

    since = datetime.datetime(2026, 11, 1, 12, 0, 0)
    judge = log_monitor.MaaLogJudge(rules(), since=since)
    old = maa_line("2026-10-31 15:00:00", "INF", "TaskQueueViewModel", "任务已全部完成！")
    assert judge.feed(old) is None
    assert judge.finish(exited=True).code == "LOG_UNKNOWN"


# --------------------------------------------------------------------------- #
# MaaEnd stdout judge
# --------------------------------------------------------------------------- #
def test_maaend_all_tasks_done_is_success():
    judge = log_monitor.MaaEndStdoutJudge(rules())
    judge.feed("[2026-11-01 15:44:12] 任务开始: 基建换班")
    judge.feed("[2026-11-01 15:50:00] 任务完成: 基建换班")
    judge.feed("[2026-11-01 15:50:01] 任务开始: CloseGamePC")
    judge.feed("[2026-11-01 15:50:30] 任务完成: CloseGamePC")
    outcome = judge.finish(exit_code=0)
    assert outcome.state == run_state.STATE_SUCCESS
    assert {t["name"] for t in outcome.tasks} == {"基建换班", "CloseGamePC"}


def test_maaend_failed_task_wins():
    judge = log_monitor.MaaEndStdoutJudge(rules())
    judge.feed("[2026-11-01 15:44:12] 任务开始: 信用收支")
    judge.feed("[2026-11-01 15:45:00] 任务失败: 信用收支")
    outcome = judge.finish(exit_code=0)
    assert outcome.state == run_state.STATE_FAILED
    assert outcome.code == "TASK_ERROR"
    assert "信用收支" in outcome.message


def test_maaend_without_task_lines_is_unknown():
    judge = log_monitor.MaaEndStdoutJudge(rules())
    outcome = judge.finish(exit_code=0)
    assert outcome.code == "LOG_UNKNOWN"


def test_maaend_nonzero_exit_is_a_failure():
    judge = log_monitor.MaaEndStdoutJudge(rules())
    judge.feed("[2026-11-01 15:44:12] 任务开始: 基建换班")
    outcome = judge.finish(exit_code=3)
    assert outcome.state == run_state.STATE_FAILED
    assert outcome.code == "TASK_ERROR"


# --------------------------------------------------------------------------- #
# LogTail
# --------------------------------------------------------------------------- #
LOG_BODY = """[2026-11-01 15:44:12.100][INF][TaskQueueViewModel]     <2> 完成任务: 开始唤醒
[2026-11-01 15:45:00.000][INF][TaskQueueViewModel]     <2> 任务已全部完成！
(用时 0h 5m 58s)
"""


def test_tail_merges_continuation_lines(tmp_path):
    path = tmp_path / "gui.log"
    path.write_text(LOG_BODY, encoding="utf-8")
    tail = log_monitor.LogTail.whole(path)
    records = tail.read() + tail.flush()
    assert [r.message for r in records][-1] == "任务已全部完成！"
    assert records[-1].extra == ["(用时 0h 5m 58s)"]


def test_tail_at_end_ignores_history(tmp_path):
    path = tmp_path / "gui.log"
    path.write_text(LOG_BODY, encoding="utf-8")
    tail = log_monitor.LogTail.at_end(path)
    assert tail.read() == []
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("[2026-11-01 16:00:00.000][INF][X] <2> 新的一行\n")
    assert [r.message for r in tail.read()] == ["新的一行"]


def test_tail_detects_a_truncated_file(tmp_path):
    path = tmp_path / "gui.log"
    path.write_text(LOG_BODY, encoding="utf-8")
    tail = log_monitor.LogTail.whole(path)
    tail.read()
    path.write_text("[2026-11-01 16:00:00.000][INF][X] <2> 重启后的第一行\n", encoding="utf-8")
    assert tail.rotate_if_needed() is True
    assert [r.message for r in tail.read()] == ["重启后的第一行"]


def test_tail_survives_a_partial_line(tmp_path):
    path = tmp_path / "gui.log"
    path.write_text("[2026-11-01 15:00:00.000][INF][X] <2> 半", encoding="utf-8")
    tail = log_monitor.LogTail.whole(path)
    assert tail.read() == []
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("行\n")
    assert [r.message for r in tail.read()] == ["半行"]


# --------------------------------------------------------------------------- #
# Remote rule table (cache override)
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self, payload):
        self.payload = payload.encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def remote_payload(success="新的收尾语", schema=1):
    return json.dumps(
        {"schema_version": schema, "updated": "2026-11-02",
         "maa": {"success": [success], "failure": [], "issues": []}},
        ensure_ascii=False,
    )


def test_refresh_rules_writes_the_cache(tmp_path):
    rules = log_monitor.refresh_rules(
        ["https://example.invalid/rules.json"],
        tmp_path,
        opener=lambda url: FakeResponse(remote_payload()),
    )
    assert rules is not None and rules.source == "remote"
    assert log_monitor.default_cache_path(tmp_path).is_file()

    cached = log_monitor.load_rules(tmp_path)
    assert cached.source == "cache"
    assert cached.maa_success == ["新的收尾语"]


def test_load_rules_without_a_cache_is_the_builtin(tmp_path):
    rules = log_monitor.load_rules(tmp_path)
    assert rules.source == "builtin"
    assert "任务已全部完成！" in rules.maa_success


def test_an_incompatible_cache_is_ignored(tmp_path):
    log_monitor.default_cache_path(tmp_path).write_text(
        remote_payload(schema=99), encoding="utf-8")
    rules = log_monitor.load_rules(tmp_path)
    assert rules.source == "builtin"


def test_a_corrupt_cache_is_ignored(tmp_path):
    log_monitor.default_cache_path(tmp_path).write_text("{broken", encoding="utf-8")
    assert log_monitor.load_rules(tmp_path).source == "builtin"


def test_refresh_rules_is_silent_on_failure(tmp_path):
    def boom(url):
        raise OSError("offline")

    assert log_monitor.refresh_rules(["https://example.invalid"], tmp_path, opener=boom) is None
    assert not log_monitor.default_cache_path(tmp_path).exists()


def test_refresh_rules_stops_at_the_first_bad_schema(tmp_path):
    rules = log_monitor.refresh_rules(
        ["https://example.invalid/1", "https://example.invalid/2"],
        tmp_path,
        opener=lambda url: FakeResponse(remote_payload(schema=99)),
    )
    assert rules is None
