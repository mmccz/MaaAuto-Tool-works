"""Unit tests for upgrade_guard (pytest port of the old _self_test plus edge cases).

This module decides whether the main app exits or keeps starting when it sees a
``.upgrading`` flag. Both wrong answers are bad:
* deleting the flag too eagerly -> the app starts mid-upgrade while files are being replaced;
* never clearing a stale flag -> double-clicking the app does nothing at all.
"""

import os
import time

import pytest

import upgrade_guard as guard


@pytest.fixture
def flag(tmp_path):
    return str(tmp_path / ".upgrading")


@pytest.fixture
def log(tmp_path):
    return str(tmp_path / "logs" / "upgrading.log")


def touch(path, age_seconds=0):
    with open(path, "w", encoding="utf-8") as f:
        f.write("upgrading")
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(path, (old, old))


def test_no_flag_allows_start(flag, log):
    assert guard.resolve_upgrade_flag(flag, log_path=log,
                                      helper_probe=lambda: False) is True


def test_fresh_flag_blocks_start(flag, log):
    touch(flag)
    assert guard.resolve_upgrade_flag(flag, log_path=log,
                                      helper_probe=lambda: False) is False


def test_stale_flag_with_helper_keeps_waiting(flag, log):
    touch(flag, guard.UPGRADE_FLAG_STALE_SECONDS + 10)
    assert guard.resolve_upgrade_flag(flag, log_path=log,
                                      helper_probe=lambda: True) is False
    assert os.path.exists(flag)


def test_stale_flag_without_helper_is_cleaned(flag, log):
    touch(flag, guard.UPGRADE_FLAG_STALE_SECONDS + 10)
    assert guard.resolve_upgrade_flag(flag, log_path=log,
                                      helper_probe=lambda: False) is True
    assert not os.path.exists(flag)


def test_probe_exception_is_conservative(flag, log):
    touch(flag, guard.UPGRADE_FLAG_STALE_SECONDS + 10)

    def boom():
        raise RuntimeError("probe failed")

    assert guard.resolve_upgrade_flag(flag, log_path=log, helper_probe=boom) is False
    assert os.path.exists(flag)


def test_custom_stale_threshold(flag, log):
    touch(flag, 5)
    assert guard.resolve_upgrade_flag(flag, log_path=log, helper_probe=lambda: False,
                                      stale_seconds=1) is True


def test_event_is_logged(flag, log):
    touch(flag)
    guard.resolve_upgrade_flag(flag, log_path=log, helper_probe=lambda: False)
    assert os.path.exists(log)
    assert "升级标志" in open(log, encoding="utf-8").read()


def test_log_failure_is_silent(flag, log):
    """An unwritable log directory must not affect the start decision."""
    touch(flag)
    bad_log = os.path.join(log, "nested", "..", "\x00bad")
    assert guard.resolve_upgrade_flag(flag, log_path=bad_log,
                                      helper_probe=lambda: False) is False


def test_flag_age_missing_file(tmp_path):
    assert guard.flag_age_seconds(str(tmp_path / "nope")) is None


def test_helper_names_cover_upgrade_and_uninstall():
    assert "upgrade.exe" in guard.HELPER_PROCESS_NAMES
    assert "uninstall.exe" in guard.HELPER_PROCESS_NAMES


def test_is_helper_running_returns_bool():
    assert isinstance(guard.is_helper_running(), bool)
