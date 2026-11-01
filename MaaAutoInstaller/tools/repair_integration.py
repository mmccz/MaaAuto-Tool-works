"""Repair a desktop icon / Start menu / "Settings > Apps" entry lost after an upgrade.

Symptoms
--------
* "Settings > Apps" shows "the system cannot find the app" for MaaAuto (or the entry is gone);
* no MaaAuto folder in the Start menu;
* the desktop shortcut is missing.

But ``MaaAuto.exe`` is still in the install directory (e.g. ``D:\\MaaAuto``) and runs fine.

Cause: Inno's uninstall registry key, Start menu group and desktop shortcut are
**shared globally by AppId**. The local release check script installs to
``%LOCALAPPDATA%\\Programs\\MaaAuto`` with the same AppId and then uninstalls,
which deletes the user's registration as well (even if installed elsewhere).
Program files are unaffected.

This tool only rebuilds the registration; it never touches program files or user config:

    python MaaAutoInstaller/tools/repair_integration.py
    python MaaAutoInstaller/tools/repair_integration.py --dir D:\\MaaAuto
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # MaaAutoInstaller/tools
INSTALLER_ROOT = HERE.parent.parent             # MaaAuto-Installer/
sys.path.insert(0, str(HERE.parent))   # MaaAutoInstaller/, package name is installer

from installer.core import shell_integration as shell  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def guess_candidates() -> list:
    """Directories registered in the registry plus a few common install locations."""
    out = []
    loc = shell.installed_location()
    if loc:
        out.append(loc)
    out.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MaaAuto")
    out.append(Path(r"D:\MaaAuto"))
    out.append(Path(r"C:\Program Files\MaaAuto"))
    seen, uniq = set(), []
    for p in out:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def version_of(install_dir: Path) -> str:
    mf = install_dir / ".maaauto.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8")).get("version", "")
        except Exception:
            return ""
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="重建 MaaAuto 的图标与「设置→应用」登记")
    ap.add_argument("--dir", default="", help="安装目录；缺省自动探测")
    ap.add_argument("--version", default="", help="写进『应用』列表的版本号；缺省读 manifest")
    args = ap.parse_args()

    target = Path(args.dir) if args.dir else None
    if target is None:
        for cand in guess_candidates():
            if (cand / shell.MAIN_EXE).exists():
                target = cand
                break
    if target is None:
        print("找不到带 MaaAuto.exe 的安装目录，请用 --dir 指定。")
        return 2

    if not (target / shell.MAIN_EXE).exists():
        print(f"{target} 里没有 {shell.MAIN_EXE}，请确认安装目录。")
        return 2
    if not (target / shell.UNINSTALLER_EXE).exists():
        print(f"[!] {target} 里没有 {shell.UNINSTALLER_EXE}：安装不完整，"
              f"建议重新运行完整安装包。仍会重建图标，但「设置→应用」里的卸载会不可用。")

    version = args.version or version_of(target)
    print("=" * 72)
    print(f"安装目录 : {target}")
    print(f"版本     : {version or '（未知）'}")
    print("=" * 72)

    result = shell.repair_integration(target, version)
    labels = {
        "start_menu": "开始菜单快捷方式",
        "start_menu_uninstall": "开始菜单「卸载」快捷方式",
        "desktop": "桌面快捷方式",
        "registry": "「设置 → 应用」登记",
    }
    fails = 0
    for key, label in labels.items():
        ok = bool(result.get(key))
        print(("  OK   " if ok else "  FAIL ") + label)
        fails += 0 if ok else 1

    loc = shell.installed_location()
    print(f"\n注册表 InstallLocation = {loc}")
    print("完成。" if not fails else "部分项目失败（可能缺少 pywin32）；可手动重装一次安装包。")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
