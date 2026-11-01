"""Backup/restore tests for shell integration (uninstall registry key / Start menu / desktop shortcut).

Background (the 1.4.1 incident): the local check script installed to
``%LOCALAPPDATA%\\Programs\\MaaAuto`` with the same Inno AppId and then uninstalled,
while Inno's uninstall registry key, Start menu group and desktop shortcut are
**shared globally by AppId** -- so the user's registration for ``D:\\MaaAuto`` was
deleted with it, Windows showed "the system cannot find the app", and the icons were gone.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT if (ROOT / "installer").is_dir() else ROOT / "MaaAutoInstaller"
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

from installer.core import shell_integration as shell  # noqa: E402


# --------------------------------------------------------------------------- #
# constants must match the Inno script
# --------------------------------------------------------------------------- #
def test_app_id_matches_installer_iss():
    iss = (PKG / "packaging" / "installer.iss").read_text(encoding="utf-8")
    app_id_line = [l for l in iss.splitlines() if l.strip().startswith("AppId=")][0]
    # in Inno, {{ means a literal {, so the real AppId is {6F3A...}
    literal = app_id_line.split("=", 1)[1].strip().replace("{{", "{", 1)
    assert literal == shell.APP_ID
    assert shell.UNINSTALL_KEY == shell.APP_ID + "_is1"
    # the icon group name must match {group} in [Icons]
    assert "DefaultGroupName=" + shell.ICON_GROUP in iss


# --------------------------------------------------------------------------- #
# snapshot / restore (never touches the real registry or real shortcuts)
# --------------------------------------------------------------------------- #
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point all three global paths at tmp and swap registry I/O for an in-memory dict."""
    group = tmp_path / "StartMenu" / "MaaAuto"
    desktop = tmp_path / "Desktop" / "MaaAuto.lnk"
    state = {"key": None}

    monkeypatch.setattr(shell, "start_menu_group", lambda: group)
    monkeypatch.setattr(shell, "desktop_lnk", lambda: desktop)
    monkeypatch.setattr(shell, "read_uninstall_key", lambda: state["key"])
    monkeypatch.setattr(shell, "write_uninstall_key",
                        lambda items: state.__setitem__("key", list(items)))
    monkeypatch.setattr(shell, "delete_uninstall_key",
                        lambda: state.__setitem__("key", None))
    return {"group": group, "desktop": desktop, "state": state}


def test_snapshot_captures_everything(sandbox):
    group, desktop, state = sandbox["group"], sandbox["desktop"], sandbox["state"]
    group.mkdir(parents=True)
    (group / "MaaAuto.lnk").write_bytes(b"LNK-APP")
    (group / "卸载 MaaAuto.lnk").write_bytes(b"LNK-UNINST")
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(b"LNK-DESKTOP")
    state["key"] = [("DisplayName", "MaaAuto", 1),
                    ("InstallLocation", r"D:\MaaAuto\\", 1)]

    snap = shell.snapshot()
    assert snap.key_items is not None and len(snap.key_items) == 2
    assert snap.group_files == {"MaaAuto.lnk": b"LNK-APP",
                                "卸载 MaaAuto.lnk": b"LNK-UNINST"}
    assert snap.desktop_link == b"LNK-DESKTOP"
    assert "注册表项" in snap.summary() and "开始菜单" in snap.summary()


def test_restore_puts_user_state_back(sandbox):
    """Simulate the check script: registry rewritten, shortcuts deleted/replaced by the verify copy -> restore."""
    group, desktop, state = sandbox["group"], sandbox["desktop"], sandbox["state"]
    group.mkdir(parents=True)
    (group / "MaaAuto.lnk").write_bytes(b"LNK-APP")
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(b"LNK-DESKTOP")
    state["key"] = [("InstallLocation", r"D:\MaaAuto\\", 1)]
    snap = shell.snapshot()

    # what the check script does: registry points at the verify dir, shortcuts cleared
    state["key"] = [("InstallLocation", r"C:\verify\\", 1)]
    if group.exists():
        import shutil
        shutil.rmtree(group)
    desktop.unlink()

    msg = shell.restore(snap)
    assert "还原注册表项" in msg and "还原开始菜单" in msg and "还原桌面" in msg
    assert state["key"][0][1] == r"D:\MaaAuto\\"
    assert (group / "MaaAuto.lnk").read_bytes() == b"LNK-APP"
    assert desktop.read_bytes() == b"LNK-DESKTOP"


def test_restore_clears_entries_created_by_verify(sandbox):
    """Nothing was registered beforehand (user never installed) -> the check run must leave no residue."""
    group, desktop, state = sandbox["group"], sandbox["desktop"], sandbox["state"]
    state["key"] = None
    snap = shell.snapshot()

    group.mkdir(parents=True)
    (group / "MaaAuto.lnk").write_bytes(b"VERIFY")
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(b"VERIFY")
    state["key"] = [("DisplayName", "MaaAuto", 1)]

    shell.restore(snap)
    assert state["key"] is None
    assert not group.exists()
    assert not desktop.exists()


# --------------------------------------------------------------------------- #
# detect a second install on this machine
# --------------------------------------------------------------------------- #
def test_foreign_install_detected(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "read_uninstall_key",
                        lambda: [("InstallLocation", r"D:\MaaAuto\\", 1)])
    assert shell.foreign_install(tmp_path / "other") == Path(r"D:\MaaAuto")


def test_foreign_install_none_when_same_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "read_uninstall_key",
                        lambda: [("InstallLocation", str(tmp_path) + "\\", 1)])
    assert shell.foreign_install(tmp_path) is None


def test_foreign_install_none_without_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "read_uninstall_key", lambda: None)
    assert shell.foreign_install(tmp_path) is None


# --------------------------------------------------------------------------- #
# repair a damaged machine
# --------------------------------------------------------------------------- #
def test_repair_requires_existing_exe(tmp_path):
    with pytest.raises(FileNotFoundError):
        shell.repair_integration(tmp_path, "1.4.2")


def test_repair_writes_registry_and_links(tmp_path, monkeypatch):
    install = tmp_path / "app"
    install.mkdir()
    (install / shell.MAIN_EXE).write_bytes(b"exe")
    (install / shell.UNINSTALLER_EXE).write_bytes(b"unins")
    written = {}
    monkeypatch.setattr(shell, "write_uninstall_key",
                        lambda items: written.setdefault("items", list(items)))
    monkeypatch.setattr(shell, "start_menu_group", lambda: tmp_path / "sm" / "MaaAuto")
    monkeypatch.setattr(shell, "desktop_lnk", lambda: tmp_path / "desk" / "MaaAuto.lnk")
    monkeypatch.setattr(shell, "_write_lnk", lambda *a, **k: True)

    result = shell.repair_integration(install, "1.4.2")
    assert result["registry"] and result["start_menu"] and result["desktop"]
    items = dict((n, v) for n, v, _k in written["items"])
    assert items["DisplayVersion"] == "1.4.2"
    assert items["InstallLocation"] == str(install) + "\\"
    assert str(install / shell.UNINSTALLER_EXE) in items["UninstallString"]
    assert items["DisplayIcon"] == str(install / shell.MAIN_EXE)


# --------------------------------------------------------------------------- #
# Microsoft Store Python: %APPDATA% is redirected to LocalCache
# --------------------------------------------------------------------------- #
def test_packaged_python_detection(monkeypatch):
    monkeypatch.setattr(shell.sys, "prefix",
                        r"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.11_x64__qbz5n2kfra8p0")
    assert shell.packaged_python() is True
    monkeypatch.setattr(shell.sys, "prefix", r"C:\Python311")
    assert shell.packaged_python() is False


def test_snapshot_reads_group_through_powershell_when_packaged(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "packaged_python", lambda: True)
    monkeypatch.setattr(shell, "start_menu_group", lambda: tmp_path / "sm" / "MaaAuto")
    monkeypatch.setattr(shell, "read_uninstall_key", lambda: None)
    monkeypatch.setattr(shell, "desktop_lnk", lambda: tmp_path / "NoDesktop.lnk")
    monkeypatch.setattr(shell, "_read_group_via_ps",
                        lambda group: {"MaaAuto.lnk": b"REAL-LNK"})
    snap = shell.snapshot()
    assert snap.group_files == {"MaaAuto.lnk": b"REAL-LNK"}


def test_restore_writes_group_through_powershell_when_packaged(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(shell, "packaged_python", lambda: True)
    monkeypatch.setattr(shell, "start_menu_group", lambda: tmp_path / "sm" / "MaaAuto")
    monkeypatch.setattr(shell, "write_uninstall_key", lambda items: None)
    monkeypatch.setattr(shell, "desktop_lnk", lambda: tmp_path / "NoDesktop.lnk")

    def fake_write(group, files):
        calls["group"] = group
        calls["files"] = files
        return True

    monkeypatch.setattr(shell, "_write_group_via_ps", fake_write)
    snap = shell.IntegrationSnapshot(key_items=[("DisplayName", "MaaAuto", 1)],
                                     group_files={"MaaAuto.lnk": b"REAL-LNK"})
    msg = shell.restore(snap)
    assert calls["files"] == {"MaaAuto.lnk": b"REAL-LNK"}
    assert "还原开始菜单" in msg


def test_restore_reports_failure_when_powershell_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "packaged_python", lambda: True)
    monkeypatch.setattr(shell, "start_menu_group", lambda: tmp_path / "sm" / "MaaAuto")
    monkeypatch.setattr(shell, "write_uninstall_key", lambda items: None)
    monkeypatch.setattr(shell, "desktop_lnk", lambda: tmp_path / "NoDesktop.lnk")
    monkeypatch.setattr(shell, "_write_group_via_ps", lambda group, files: False)

    snap = shell.IntegrationSnapshot(key_items=None,
                                     group_files={"MaaAuto.lnk": b"X"})
    msg = shell.restore(snap)
    assert "开始菜单还原失败" in msg


def test_write_lnk_uses_powershell_when_packaged(monkeypatch, tmp_path):
    used = {}
    monkeypatch.setattr(shell, "packaged_python", lambda: True)

    def fake_ps(script):
        used["script"] = script
        return ""

    monkeypatch.setattr(shell, "_ps", fake_ps)
    ok = shell._write_lnk(tmp_path / "sm" / "MaaAuto.lnk", tmp_path / "MaaAuto.exe",
                          tmp_path, "MaaAuto")
    assert ok is True
    assert "CreateShortcut" in used["script"]



def test_restore_keeps_real_install_when_snapshot_was_empty(monkeypatch, tmp_path):
    """The snapshot read no registration, but the live one points at an existing real install -> keep it."""
    install = tmp_path / "app"
    install.mkdir()
    (install / shell.MAIN_EXE).write_bytes(b"exe")
    state = {"key": [("InstallLocation", str(install) + "\\", 1)]}
    monkeypatch.setattr(shell, "read_uninstall_key", lambda: state["key"])
    monkeypatch.setattr(shell, "write_uninstall_key",
                        lambda items: state.__setitem__("key", list(items)))
    monkeypatch.setattr(shell, "delete_uninstall_key",
                        lambda: state.__setitem__("key", None))
    monkeypatch.setattr(shell, "start_menu_group", lambda: tmp_path / "sm" / "MaaAuto")
    monkeypatch.setattr(shell, "desktop_lnk", lambda: tmp_path / "NoDesktop.lnk")

    msg = shell.restore(shell.IntegrationSnapshot(key_items=None))
    assert "保留现有登记" in msg
    assert state["key"] is not None
