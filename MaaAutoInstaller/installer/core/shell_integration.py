"""Backup / restore / repair for the installer "shell integration".

Why this exists (the 1.4.2 lesson)
---------------------------------
Three things an Inno installer writes are **shared globally by AppId**,
regardless of the install directory:

* ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{AppId}_is1``
  (the row in "Settings -> Apps"; Windows uses it to find the uninstaller)
* the Start Menu group ``%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\MaaAuto``
* the desktop link ``MaaAuto.lnk``

The local release-verification scripts (``tools/verify_release.py``,
``tools/smoke_install.py``) do "install a copy -> run tests -> uninstall". They
install to ``%LOCALAPPDATA%\\Programs\\MaaAuto`` while the user may have the real
thing in a custom directory such as ``D:\\MaaAuto`` -- **same AppId** -- so the
verification uninstall deletes the user's registry entry and Start Menu group
along with its own:

* MaaAuto in "Settings -> Apps" turns into "app not found" (UninstallString
  points at a deleted exe)
* the Start Menu / desktop shortcuts disappear

The program files themselves are untouched (the auto-updater only replaces
files); only this **bookkeeping** breaks.

So the verification scripts must now:

1. install to a **separate directory** (``MaaAuto_verify``) and never touch the
   user's install;
2. call ``snapshot()`` before and ``restore()`` after to back up and restore the
   registry entry and shortcuts.

``repair_integration()`` rebuilds this bookkeeping on machines where it was
already deleted by mistake.
"""

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Keep in sync with the AppId in packaging/installer.iss (changing this requires the same .iss change)
APP_ID = "{6F3A2C1E-8B4D-4E7A-9C15-3D02A7B9E4C1}"
APP_NAME = "MaaAuto"
UNINSTALL_KEY = f"{APP_ID}_is1"
UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
ICON_GROUP = "MaaAuto"
MAIN_EXE = "MaaAuto.exe"
UNINSTALLER_EXE = "unins000.exe"


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def uninstall_key_path() -> str:
    return f"{UNINSTALL_ROOT}\\{UNINSTALL_KEY}"


def start_menu_group() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / ICON_GROUP)


def desktop_lnk() -> Path:
    # For per-user installs the Inno {autodesktop} constant is the current user desktop
    desktop = Path(os.environ.get("USERPROFILE") or str(Path.home())) / "Desktop"
    return desktop / f"{APP_NAME}.lnk"


# --------------------------------------------------------------------------- #
# MSIX directory redirection for Microsoft Store Python
# --------------------------------------------------------------------------- #
def packaged_python() -> bool:
    """Whether the interpreter comes from the Microsoft Store (an MSIX-packaged app).

    MSIX app writes to ``%APPDATA%`` are silently redirected to
    ``%LOCALAPPDATA%\\Packages\\<package>\\LocalCache\\Roaming``, which neither
    Explorer nor Inno can see. So "repair Start Menu" reports OK while creating
    nothing at all (hit while retesting the 1.4.2 fix).

    Child processes (powershell.exe) do not inherit the package identity and
    write to the real path, so reads and writes of such paths are delegated to
    PowerShell.
    """
    prefix = str(getattr(sys, "prefix", "")).replace("/", "\\").lower()
    return "\\windowsapps\\" in prefix


def _ps_literal(text: object) -> str:
    """Wrap as a PowerShell single-quoted string (single quotes doubled)."""
    return "'" + str(text).replace("'", "''") + "'"


def _ps(script: str) -> Optional[str]:
    """Run a PowerShell snippet; return stdout on success, None on failure/unavailable."""
    if os.name != "nt":
        return None
    exe = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell"
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
            capture_output=True, timeout=60)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8-sig", "replace")


def _read_group_via_ps(group: Path) -> Dict[str, bytes]:
    root = _ps_literal(str(group))
    script = (
        f"$root = {root};"
        "if (-not (Test-Path -LiteralPath $root)) { exit 3 };"
        "$root = (Resolve-Path -LiteralPath $root).Path;"
        "Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {"
        "  $rel = $_.FullName.Substring($root.Length + 1).Replace('\\', '/');"
        "  $rel + [char]9 + [Convert]::ToBase64String([IO.File]::ReadAllBytes($_.FullName))"
        " }"
    )
    out = _ps(script)
    if not out:
        return {}
    files: Dict[str, bytes] = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        rel, b64 = line.split("\t", 1)
        try:
            files[rel.strip()] = base64.b64decode(b64.strip())
        except Exception:
            continue
    return files


def _write_group_via_ps(group: Path, files: Dict[str, bytes]) -> bool:
    """Rebuild the Start Menu group via PowerShell (delete it entirely first, then write the bytes back)."""
    parts = [
        f"$root = {_ps_literal(str(group))};",
        "if (Test-Path -LiteralPath $root) {"
        " Remove-Item -LiteralPath $root -Recurse -Force };",
    ]
    for rel, data in files.items():
        target = Path(str(group)) / rel
        b64 = base64.b64encode(data).decode("ascii")
        parts.append(f"$p = {_ps_literal(str(target))};")
        parts.append("New-Item -ItemType Directory -Path (Split-Path -Parent $p)"
                     " -Force | Out-Null;")
        parts.append(f"[IO.File]::WriteAllBytes($p,"
                     f" [Convert]::FromBase64String('{b64}'));")
    return _ps("".join(parts)) is not None


def start_menu_files() -> Dict[str, bytes]:
    """Files in the Start Menu group (relative path -> raw bytes); {} when empty or missing."""
    if packaged_python():
        return _read_group_via_ps(start_menu_group())
    group = start_menu_group()
    files: Dict[str, bytes] = {}
    if group.is_dir():
        for p in group.rglob("*"):
            if p.is_file():
                try:
                    files[p.relative_to(group).as_posix()] = p.read_bytes()
                except OSError:
                    pass
    return files


def clear_start_menu_group() -> None:
    """Delete the Start Menu group (real path; a plain rmtree does not work under MSIX)."""
    group = start_menu_group()
    if packaged_python():
        _ps("if (Test-Path -LiteralPath %s) { Remove-Item -LiteralPath %s"
            " -Recurse -Force }" % (_ps_literal(group), _ps_literal(group)))
    else:
        shutil.rmtree(group, ignore_errors=True)




# --------------------------------------------------------------------------- #
# Registry: read the whole key as (name, value, type) triples so it can be written back verbatim
# --------------------------------------------------------------------------- #
def read_uninstall_key() -> Optional[List[Tuple[str, object, int]]]:
    """Read the current user MaaAuto uninstall entry; None when absent."""
    try:
        import winreg
    except Exception:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key_path()) as k:
            items = []
            i = 0
            while True:
                try:
                    name, value, kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                items.append((name, value, kind))
            return items
    except OSError:
        return None


def write_uninstall_key(items: List[Tuple[str, object, int]]) -> None:
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, uninstall_key_path(), 0,
                            winreg.KEY_WRITE) as k:
        for name, value, kind in items:
            winreg.SetValueEx(k, name, 0, kind, value)


def delete_uninstall_key() -> None:
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, uninstall_key_path())
    except OSError:
        pass


def installed_location() -> Optional[Path]:
    """Install directory recorded in the registry (None when missing)."""
    items = read_uninstall_key() or []
    for name, value, _kind in items:
        if name.lower() in ("installlocation", "inno setup: app path"):
            text = str(value).strip().rstrip("\\")
            if text:
                return Path(text)
    return None


def foreign_install(target_dir: Path) -> Optional[Path]:
    """Return that directory when the registry records a "different install".

    The verification scripts use it to warn that the shared registry entry and
    shortcuts are about to be touched.
    """
    loc = installed_location()
    try:
        target = Path(target_dir).resolve()
    except OSError:
        target = Path(target_dir)
    if loc is None:
        return None
    try:
        if loc.resolve() == target:
            return None
    except OSError:
        pass
    return loc


# --------------------------------------------------------------------------- #
# Snapshot / restore
# --------------------------------------------------------------------------- #
@dataclass
class IntegrationSnapshot:
    """Shell-integration state snapshot (registry values + raw shortcut bytes)."""
    key_items: Optional[List[Tuple[str, object, int]]] = None
    group_files: Dict[str, bytes] = field(default_factory=dict)
    desktop_link: Optional[bytes] = None
    # temp dir for the backup (used to copy shortcuts, must be cleaned up in restore)
    _tmp: Optional[Path] = None

    def summary(self) -> str:
        parts = []
        if self.key_items is not None:
            parts.append(f"注册表项 {len(self.key_items)} 个值")
        if self.group_files:
            parts.append(f"开始菜单 {len(self.group_files)} 个文件")
        if self.desktop_link:
            parts.append("桌面快捷方式")
        return "、".join(parts) if parts else "（无）"


def snapshot() -> IntegrationSnapshot:
    snap = IntegrationSnapshot(key_items=read_uninstall_key())
    # Start Menu group goes through start_menu_files(): under MSIX Python only PowerShell sees the real directory
    snap.group_files = start_menu_files()
    lnk = desktop_lnk()
    if lnk.is_file():
        try:
            snap.desktop_link = lnk.read_bytes()
        except OSError:
            pass
    return snap


def restore(snap: IntegrationSnapshot) -> str:
    """Write the snapshot back; return a human-readable restore summary."""
    actions = []

    # Registry
    if snap.key_items is None:
        # Nothing was registered at snapshot time: normally the entry written by
        # the verification run should be deleted. But if the recorded install
        # directory still exists (program files too), this is the user's real
        # install: better to leave a redundant entry than to delete it again
        # (that is exactly what went wrong in 1.4.1).
        loc = installed_location()
        if loc is not None and (loc / MAIN_EXE).exists():
            actions.append(f"保留现有登记（{loc} 仍在），未删除")
        else:
            delete_uninstall_key()
            actions.append("已清掉本次校验写入的注册表项")
    else:
        write_uninstall_key(snap.key_items)
        actions.append(f"还原注册表项（{len(snap.key_items)} 个值）")

    # Start Menu: delete what the verification run left behind, then rebuild from the snapshot
    group = start_menu_group()
    if packaged_python():
        # MSIX redirection would send write_bytes into LocalCache, so PowerShell must write the real path
        if _write_group_via_ps(group, snap.group_files):
            if snap.group_files:
                actions.append(f"还原开始菜单（{len(snap.group_files)} 个文件）")
        else:
            actions.append("开始菜单还原失败（PowerShell 不可用，请手动运行 "
                           "tools/repair_integration.py）")
    else:
        if group.exists():
            shutil.rmtree(group, ignore_errors=True)
        if snap.group_files:
            group.mkdir(parents=True, exist_ok=True)
            for rel, data in snap.group_files.items():
                target = group / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            actions.append(f"还原开始菜单（{len(snap.group_files)} 个文件）")

    # Desktop
    lnk = desktop_lnk()
    if snap.desktop_link:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        lnk.write_bytes(snap.desktop_link)
        actions.append("还原桌面快捷方式")
    elif lnk.exists():
        try:
            lnk.unlink()
            actions.append("清掉本次校验新建的桌面快捷方式")
        except OSError:
            pass

    return "；".join(actions)


# --------------------------------------------------------------------------- #
# Repair (for machines whose entries were deleted by mistake)
# --------------------------------------------------------------------------- #
def _write_lnk_via_ps(path: Path, target: Path, workdir: Path,
                      description: str = "") -> bool:
    """Create a .lnk on the **real** path (bypassing the MSIX %APPDATA% redirection)."""
    script = (
        "$sh = New-Object -ComObject WScript.Shell;"
        f"$lnk = $sh.CreateShortcut({_ps_literal(path)});"
        f"$lnk.TargetPath = {_ps_literal(target)};"
        f"$lnk.WorkingDirectory = {_ps_literal(workdir)};"
        f"$lnk.IconLocation = {_ps_literal(target)};"
        f"$lnk.Description = {_ps_literal(description)};"
        "$lnk.Save();"
        "if (-not (Test-Path -LiteralPath "
        f"{_ps_literal(path)})) {{ exit 5 }}"
    )
    dir_script = ("New-Item -ItemType Directory -Path (Split-Path -Parent "
                  f"{_ps_literal(path)}) -Force | Out-Null;")
    return _ps(dir_script + script) is not None


def _write_lnk(path: Path, target: Path, workdir: Path, description: str = "") -> bool:
    """Create a .lnk via WScript.Shell (pywin32 is not a deployment dependency, imported on demand)."""
    if packaged_python():
        return _write_lnk_via_ps(path, target, workdir, description)
    try:
        import win32com.client
    except Exception:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sh = win32com.client.Dispatch("WScript.Shell")
        lnk = sh.CreateShortCut(str(path))
        lnk.TargetPath = str(target)
        lnk.WorkingDirectory = str(workdir)
        lnk.IconLocation = str(target)
        lnk.Description = description
        lnk.Save()
        return path.exists()
    except Exception:
        return False


def _dir_size_kb(root: Path) -> int:
    total = 0
    for p in Path(root).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total // 1024


def repair_integration(install_dir: Path, version: str = "") -> Dict[str, bool]:
    """Rebuild the uninstall registry entry, Start Menu group and desktop shortcut for ``install_dir``.

    Add/overwrite only, never delete program files; used to repair "icons and the
    Apps entry vanished after an upgrade".
    """
    import time

    install_dir = Path(install_dir)
    exe = install_dir / MAIN_EXE
    uninst = install_dir / UNINSTALLER_EXE
    if not exe.exists():
        raise FileNotFoundError(f"{exe} 不存在，先确认安装目录")

    result = {}

    group = start_menu_group()
    result["start_menu"] = _write_lnk(group / f"{APP_NAME}.lnk", exe, install_dir,
                                      APP_NAME)
    result["start_menu_uninstall"] = _write_lnk(
        group / f"卸载 {APP_NAME}.lnk", uninst, install_dir, f"卸载 {APP_NAME}")
    result["desktop"] = _write_lnk(desktop_lnk(), exe, install_dir, APP_NAME)

    items: List[Tuple[str, object, int]] = [
        ("DisplayName", APP_NAME, 1),
        ("DisplayVersion", version or "", 1),
        ("DisplayIcon", str(exe), 1),
        ("UninstallString", f'"{uninst}"', 1),
        ("QuietUninstallString", f'"{uninst}" /SILENT', 1),
        ("InstallLocation", str(install_dir) + "\\", 1),
        ("Publisher", "mmccz", 1),
        ("URLInfoAbout", "https://github.com/mmccz/MaaAuto-Tool-works", 1),
        ("HelpLink", "https://github.com/mmccz/MaaAuto-Tool-works/issues", 1),
        ("URLUpdateInfo", "https://github.com/mmccz/MaaAuto-Tool-works/releases", 1),
        ("NoModify", 1, 4),
        ("NoRepair", 1, 4),
        ("InstallDate", time.strftime("%Y%m%d"), 1),
        ("EstimatedSize", _dir_size_kb(install_dir), 4),
        ("Inno Setup: App Path", str(install_dir), 1),
        ("Inno Setup: Icon Group", ICON_GROUP, 1),
        ("Inno Setup: Language", "cn", 1),
        ("Inno Setup: Selected Tasks", "startmenuicon,desktopicon", 1),
        ("Inno Setup: User", os.environ.get("USERNAME", ""), 1),
    ]
    if version:
        parts = version.split(".")
        try:
            items.append(("VersionMajor", int(parts[0]), 4))
            items.append(("VersionMinor", int(parts[1]), 4))
        except (IndexError, ValueError):
            pass
    write_uninstall_key(items)
    result["registry"] = True
    return result
