"""Keeps the MaaAuto entry in Settings > Apps up to date (D-2 self-healing).

**Why this exists**: the auto-updater only replaces program files and never runs
the Inno installer, so the uninstall entry's ``DisplayVersion`` stays frozen at the
version that was installed. A user who had upgraded to 1.4.2 still saw 1.4.1 in
Settings > Apps (found while re-checking on 2026-10-31).

**How it is fixed**: on every start the main program looks up the uninstall entry
once, and only when ``InstallLocation`` points at itself does it rewrite
``DisplayVersion`` / ``DisplayIcon`` / ``VersionMajor`` / ``VersionMinor`` to the
current version. A failed write is logged at DEBUG and never affects startup; on
non-Windows platforms this is skipped entirely.

Only ``HKCU`` is touched (this is a per-user install), so no admin rights needed.
"""

import os
from typing import Dict

APP_DISPLAY_NAME = "MaaAuto"
MAIN_EXE = "MaaAuto.exe"
UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def _norm(path: object) -> str:
    """Normalize a path for comparing the registered dir with the install dir."""
    try:
        text = str(path).strip().strip('"')
        if not text:
            return ""
        return os.path.normcase(os.path.abspath(text)).rstrip("\\/")
    except Exception:
        return ""


def _version_parts(text: str):
    out = []
    for piece in str(text or "").split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return out


def updates_for(values: Dict[str, object], app_version: str,
                install_dir: str) -> Dict[str, object]:
    """Compute the uninstall-entry values that need rewriting.

    Returns ``{}`` when nothing needs changing or the entry is not ours.
    Pure function: it never reads the registry, which keeps it unit-testable.
    """
    if not app_version:
        return {}
    if str(values.get("DisplayName", "")).strip() != APP_DISPLAY_NAME:
        return {}
    loc = values.get("InstallLocation") or values.get("Inno Setup: App Path") or ""
    if _norm(loc) != _norm(install_dir):
        return {}

    out: Dict[str, object] = {}
    if str(values.get("DisplayVersion", "")) != app_version:
        out["DisplayVersion"] = app_version

    icon = os.path.join(os.path.abspath(install_dir), MAIN_EXE)
    if _norm(values.get("DisplayIcon", "")) != _norm(icon):
        out["DisplayIcon"] = icon

    parts = _version_parts(app_version) + [0, 0]
    if values.get("VersionMajor") != parts[0]:
        out["VersionMajor"] = parts[0]
    if values.get("VersionMinor") != parts[1]:
        out["VersionMinor"] = parts[1]
    return out


def _enum_subkeys(root, path: str):
    import winreg
    names = []
    try:
        with winreg.OpenKey(root, path) as key:
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
    except OSError:
        pass
    return names


def _read_values(root, path: str):
    import winreg
    values = {}
    try:
        with winreg.OpenKey(root, path) as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                    index += 1
                    values[name] = value
                except OSError:
                    break
    except OSError:
        return None
    return values


def sync_display_version(app_version: str, install_dir: str) -> bool:
    """Set the uninstall-entry version to ``app_version`` for the entry pointing at
    ``install_dir``.

    Returns whether the registry was actually written. Exceptions are swallowed:
    this is display-only information and must never affect startup.
    """
    if os.name != "nt":
        return False
    try:
        import winreg
    except Exception:
        return False

    root = winreg.HKEY_CURRENT_USER
    for name in _enum_subkeys(root, UNINSTALL_ROOT):
        path = UNINSTALL_ROOT + "\\" + name
        values = _read_values(root, path)
        if not values:
            continue
        updates = updates_for(values, app_version, install_dir)
        if not updates:
            continue
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE) as key:
                for key_name, value in updates.items():
                    kind = (winreg.REG_DWORD
                            if isinstance(value, int) else winreg.REG_SZ)
                    winreg.SetValueEx(key, key_name, 0, kind, value)
            return True
        except OSError:
            return False
    return False
