"""Unit tests for the "Settings → Apps" version self-heal (D-2).

Auto-updates do not run Inno, so the uninstall entry's DisplayVersion stays at the
version installed; on startup the app calls ``apps_registry.sync_display_version`` to
correct it. Only the pure helpers and matching rules are covered here; the real
registry is never touched.
"""

import os

from apps_registry import updates_for, _version_parts, sync_display_version


INSTALL = r"D:\MaaAuto"


def _entry(**extra):
    values = {
        "DisplayName": "MaaAuto",
        "DisplayVersion": "1.4.2",
        "InstallLocation": INSTALL + "\\",
        "Inno Setup: App Path": INSTALL,
        "DisplayIcon": os.path.join(INSTALL, "MaaAuto.exe"),
        "VersionMajor": 1,
        "VersionMinor": 4,
    }
    values.update(extra)
    return values


def test_version_parts():
    assert _version_parts("1.4.3") == [1, 4, 3]
    assert _version_parts("1.5.0b2") == [1, 5, 0]
    assert _version_parts("") == [0]


def test_no_change_when_already_current():
    assert updates_for(_entry(), "1.4.2", INSTALL) == {}


def test_updates_version_after_delta_upgrade():
    out = updates_for(_entry(), "1.4.3", INSTALL)
    assert out["DisplayVersion"] == "1.4.3"
    # 1.4.x internal upgrade: major/minor unchanged, so no need to write them
    assert "VersionMajor" not in out
    assert "VersionMinor" not in out


def test_bumps_major_minor_when_xy_changes():
    out = updates_for(_entry(), "1.5.0", INSTALL)
    assert out["DisplayVersion"] == "1.5.0"
    assert out["VersionMinor"] == 5
    assert "VersionMajor" not in out


def test_updates_icon_when_path_moved():
    out = updates_for(_entry(DisplayIcon=r"C:\old\MaaAuto.exe"), "1.4.2", INSTALL)
    assert out["DisplayIcon"] == os.path.join(os.path.abspath(INSTALL), "MaaAuto.exe")


def test_ignores_other_install_dir():
    assert updates_for(_entry(), "1.4.3", r"D:\Other") == {}


def test_ignores_other_app():
    assert updates_for(_entry(DisplayName="OtherApp"), "1.4.3", INSTALL) == {}


def test_ignores_entry_without_location():
    assert updates_for({"DisplayName": "MaaAuto"}, "1.4.3", INSTALL) == {}


def test_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert sync_display_version("1.4.3", INSTALL) is False
