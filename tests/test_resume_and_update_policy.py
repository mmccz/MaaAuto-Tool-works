"""Upgrade hand-off: --resume-run parsing and the "don't retry a failed upgrade" rule."""

import os
import time

import pytest

import update_checker


# --------------------------------------------------------------------------- #
# --resume-run
# --------------------------------------------------------------------------- #
def test_resume_flag_is_absent_by_default():
    import main

    assert main._parse_resume_run([]) is None
    assert main._parse_resume_run(["--autostart"]) is None


def test_resume_flag_with_an_id():
    import main

    assert main._parse_resume_run(["--resume-run=abc123"]) == "abc123"
    assert main._parse_resume_run(["--autostart", "--resume-run=abc123"]) == "abc123"


def test_resume_flag_with_a_separate_argument():
    import main

    assert main._parse_resume_run(["--resume-run", "abc123"]) == "abc123"
    assert main._parse_resume_run(["--resume-run", "--autostart"]) == ""


def test_bare_resume_flag_means_use_the_journal():
    import main

    assert main._parse_resume_run(["--resume-run"]) == ""


# --------------------------------------------------------------------------- #
# Update policy / cooldown
# --------------------------------------------------------------------------- #
def test_no_flag_means_no_recent_failure(tmp_path):
    assert update_checker.failed_upgrade_age_hours(tmp_path) is None
    assert update_checker.recent_upgrade_failure(tmp_path) is False


def test_a_fresh_failure_flag_blocks_auto_update(tmp_path):
    flag = tmp_path / update_checker.UPGRADE_FAILED_FLAG
    flag.write_text("failed", encoding="utf-8")
    assert update_checker.recent_upgrade_failure(tmp_path) is True
    assert update_checker.auto_update_allowed({"update_policy": "between-rounds"}, tmp_path) is False


def test_an_old_failure_flag_no_longer_blocks(tmp_path):
    flag = tmp_path / update_checker.UPGRADE_FAILED_FLAG
    flag.write_text("failed", encoding="utf-8")
    old = time.time() - 25 * 3600
    os.utime(flag, (old, old))

    assert update_checker.failed_upgrade_age_hours(tmp_path) > 24
    assert update_checker.recent_upgrade_failure(tmp_path) is False


def test_manual_policy_never_auto_updates(tmp_path):
    assert update_checker.auto_update_allowed({"update_policy": "manual"}, tmp_path) is False
    assert update_checker.auto_update_allowed({}, tmp_path) is True


@pytest.mark.parametrize("hours", [1, 12, 23])
def test_cooldown_window_is_configurable(tmp_path, hours):
    flag = tmp_path / update_checker.UPGRADE_FAILED_FLAG
    flag.write_text("failed", encoding="utf-8")
    old = time.time() - (hours + 2) * 3600
    os.utime(flag, (old, old))

    assert update_checker.recent_upgrade_failure(tmp_path, hours=hours) is False
    assert update_checker.recent_upgrade_failure(tmp_path, hours=hours + 4) is True

# --------------------------------------------------------------------------- #
# one-shot cleanup of the recorded launch arguments
# --------------------------------------------------------------------------- #
def test_strip_resume_args_removes_only_the_resume_flag(tmp_path):
    import json

    from ui.main_window import strip_resume_args

    path = tmp_path / "last_launch_args.json"
    path.write_text(
        json.dumps({"args": ["--autostart", "--resume-run=abc123"], "written_at": "x"}),
        encoding="utf-8",
    )

    assert strip_resume_args(path) is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["args"] == ["--autostart"]
    assert saved["written_at"] == "x"
    # Second call: nothing left to strip.
    assert strip_resume_args(path) is False


def test_strip_resume_args_tolerates_a_missing_file(tmp_path):
    from ui.main_window import strip_resume_args

    assert strip_resume_args(tmp_path / "nope.json") is False
