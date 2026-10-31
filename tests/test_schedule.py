"""Regression tests for schedule rules (multiple slots + weekdays) and announcement merging (1.3.0)."""

import datetime as dt

import pytest

import schedule_utils as su
from config_manager import DEFAULT_CONFIG
from ui.announcements import merge_announcements, pick_best


# --------------------------------------------------------------------------- #
# Config migration and normalization
# --------------------------------------------------------------------------- #
def test_defaults_exist():
    assert DEFAULT_CONFIG["schedule_times"] == []
    assert DEFAULT_CONFIG["schedule_weekdays"] == []
    assert DEFAULT_CONFIG["last_trigger_key"] == ""


def test_effective_times_migrates_legacy_execute_time():
    """A legacy config with only execute_time becomes a single slot (the user setting must not be lost)."""
    assert su.effective_times({"execute_time": "09:30"}) == ["09:30"]
    assert su.effective_times({"execute_time": "09:30",
                               "schedule_times": ["20:00"]}) == ["20:00"]
    assert su.effective_times({}) == ["08:00"]


def test_normalize_times():
    # 8:00 normalizes to 08:00; 20:5 is accepted too (=20:05); invalid and out-of-range values drop
    assert su.normalize_times(["8:00", "08:00", "20:5", "bad", "24:00", ""]) == \
        ["08:00", "20:05"]
    assert su.normalize_times(["20:30", "08:00"]) == ["08:00", "20:30"]


def test_normalize_weekdays_drops_invalid():
    assert su.normalize_weekdays([7, 1, 9, 0, "3", "x"]) == [1, 3, 7]


# --------------------------------------------------------------------------- #
# Trigger decision
# --------------------------------------------------------------------------- #
def _at(hour, minute=0, day=dt.date(2026, 10, 26)):      # 2026-10-26 is a Monday
    return dt.datetime.combine(day, dt.time(hour, minute))


def test_due_slot_basic():
    times = ["08:00", "20:00"]
    now = _at(8, 0)
    assert su.due_slot(times, [], now, "") == "2026-10-26 08:00"
    # The same slot does not fire twice
    assert su.due_slot(times, [], now, "2026-10-26 08:00") is None
    # The second slot fires only once 20:00 arrives
    assert su.due_slot(times, [], _at(20, 0), "2026-10-26 08:00") == \
        "2026-10-26 20:00"


def test_due_slot_catch_up_runs_only_latest():
    """When several slots were missed, catch up on only the latest one, so the task does not run twice back to back."""
    assert su.due_slot(["08:00", "09:00"], [], _at(10, 0), "") == \
        "2026-10-26 09:00"


def test_due_slot_respects_weekdays():
    # Monday is checked, Tuesday is not
    assert su.due_slot(["08:00"], [1], _at(9, 1), "") is not None
    tuesday = dt.date(2026, 10, 27)
    now = dt.datetime.combine(tuesday, dt.time(9, 1))
    assert su.due_slot(["08:00"], [1], now, "") is None


def test_due_slot_before_first_slot():
    assert su.due_slot(["20:00"], [], _at(8, 0), "") is None


# --------------------------------------------------------------------------- #
# Next run
# --------------------------------------------------------------------------- #
def test_next_run_same_day():
    when = su.next_run(["08:00", "20:00"], [], _at(9, 0))
    assert when == _at(20, 0)


def test_next_run_skips_to_active_weekday():
    """After Friday night with only Monday active → next_run should be Monday morning."""
    friday = dt.date(2026, 10, 30)
    now = dt.datetime.combine(friday, dt.time(21, 0))
    when = su.next_run(["08:00"], [1], now)          # Monday only
    assert when.date() == dt.date(2026, 11, 2)
    assert when.hour == 8


def test_next_run_every_day():
    when = su.next_run(["08:00"], [], _at(9, 0))
    assert when.date() == dt.date(2026, 10, 27)


# --------------------------------------------------------------------------- #
# Announcement merging (a stale mirror must not override newer announcements)
# --------------------------------------------------------------------------- #
def _item(ident, date, title=None):
    return {"id": ident, "date": date, "tag": "版本更新",
            "title": {"zh_CN": title or ident, "en_US": ident},
            "body": {"zh_CN": "b", "en_US": "b"}}


def test_merge_keeps_items_only_present_locally():
    """When the online source is older (fewer items), local newer items must not be deleted."""
    local = [_item("v1.3.0", "2026-10-25"), _item("v1.2.0", "2026-10-24")]
    stale_remote = [_item("v1.2.0", "2026-10-24")]
    merged = merge_announcements(local, stale_remote)
    assert [i["id"] for i in merged] == ["v1.3.0", "v1.2.0"]


def test_merge_remote_wins_for_same_id():
    local = [_item("v1.3.0", "2026-10-25", "旧标题")]
    remote = [_item("v1.3.0", "2026-10-26", "新标题")]
    merged = merge_announcements(local, remote)
    assert merged[0]["title"]["zh_CN"] == "新标题"


def test_pick_best_uses_max_updated_and_union():
    updated, items = pick_best("2026-10-24", [_item("v1.2.0", "2026-10-24")],
                               "2026-10-25", [_item("v1.3.0", "2026-10-25")])
    assert updated == "2026-10-25"
    assert {i["id"] for i in items} == {"v1.2.0", "v1.3.0"}


def test_pick_best_never_downgrades_updated():
    updated, _ = pick_best("2026-10-25", [_item("a", "2026-10-25")],
                           "2026-10-20", [_item("b", "2026-10-20")])
    assert updated == "2026-10-25"


# --------------------------------------------------------------------------- #
# UI: schedule editor
# --------------------------------------------------------------------------- #
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class FakeI18n:
    current_lang = "zh_CN"

    def t(self, key, **kwargs):
        return key


def test_schedule_editor_roundtrip(qapp):
    from ui.schedule_editor import ScheduleEditor

    editor = ScheduleEditor(FakeI18n(), times=["08:00", "20:30"],
                            weekdays=[1, 3, 5])
    try:
        times, days = editor.values()
        assert times == ["08:00", "20:30"]
        assert days == [1, 3, 5]
        # Keep at least one slot: emptying the list auto-adds 08:00 back
        editor.list.setCurrentRow(0)
        editor._remove_time()
        assert editor.times() == ["20:30"]
        editor.list.setCurrentRow(0)
        editor._remove_time()          # delete the last one → 08:00 is added back
        assert editor.times() == ["08:00"]
    finally:
        editor.deleteLater()


def test_schedule_editor_emits_changed(qapp):
    from ui.schedule_editor import ScheduleEditor

    editor = ScheduleEditor(FakeI18n(), times=["08:00"], weekdays=[])
    try:
        seen = []
        editor.changed.connect(lambda: seen.append(1))
        editor._day_buttons[0][1].setChecked(True)
        assert seen          # checking a weekday must notify the settings page to save
    finally:
        editor.deleteLater()
