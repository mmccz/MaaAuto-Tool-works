"""Install/uninstall smoke: silent install -> verify artifacts and manifest
-> silent uninstall -> confirm nothing is left.

Difference from ``verify_release.py``: that one is the **full** verification
(upgrade path, fake Release, Start menu tasks, data retention...), run manually
on a dev machine; this one keeps only the core assertions that must pass before
release, finishes in a few minutes, and is called by ``release.yml`` between
"build finished" and "publish the Release":

* installer will not install, manifest written wrong, artifact missing, uninstall
  leftovers -> red before publishing, so a broken version never ships;
* no network, no main app launch (the app requires admin, and a UAC prompt hangs
  CI), so it is safe to run on a runner.

Usage (from the installer repo root) ::

    python MaaAutoInstaller/tools/smoke_install.py 1.1.1
    python MaaAutoInstaller/tools/smoke_install.py v1.1.1 --keep
    python MaaAutoInstaller/tools/smoke_install.py --setup dist/MaaAuto_Setup_v1.1.1-Windows-x64.exe

Exit code: 0 = everything passed; 1 = an assertion failed or an exception occurred.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Printing non-ASCII text crashes CI's cp1252 console; force UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent          # MaaAutoInstaller/tools/
INSTALLER_ROOT = HERE.parent.parent             # MaaAuto-Installer/
INSTALLER_PKG = HERE.parent                     # MaaAutoInstaller/
DIST = INSTALLER_ROOT / "dist"
sys.path.insert(0, str(INSTALLER_PKG))   # MaaAutoInstaller/, package name is installer
from installer.core import shell_integration as shell  # noqa: E402

# Must install into a **separate directory**: Inno's uninstall registry key, Start
# menu group and desktop shortcut are shared globally by AppId, so installing over
# the user's real install dir (even a custom D:\MaaAuto) and then uninstalling
# deletes the user's registration too (hit in 1.4.1: "Settings > Apps" turned into
# "the system cannot find the app").
DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) \
    / "Programs" / "MaaAuto_verify"
START_MENU = shell.start_menu_group()
DESKTOP_LNK = shell.desktop_lnk()

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (f"  [{detail}]" if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)
    return cond


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, timeout=600):
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    try:
        return subprocess.run([str(c) for c in cmd], timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"  ! 超时（{timeout}s）", flush=True)
        return None


def uninstaller_alive():
    """Inno's uninstaller copies itself to a temp dir and exits its original
    process immediately.

    So wait for those copies (unins* / _iu*) to exit, otherwise "uninstall done"
    is reported too early.
    """
    try:
        import psutil
    except ImportError:
        return False
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name.startswith("unins") or name.startswith("_iu"):
            return True
    return False


def wait_gone(path, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not path.exists() and not uninstaller_alive():
            return True
        time.sleep(0.5)
    return not path.exists()


def contract_extra():
    """Installer-side contract defaults; {} if the import fails (the assertion then fails)."""
    sys.path.insert(0, str(INSTALLER_PKG))
    try:
        from installer.contract import default_manifest_extra
        return default_manifest_extra()
    except Exception as e:                       # should not happen: same repo, same dir
        print(f"  ! 读取 contract.py 失败: {e}", flush=True)
        return {}


def find_setup(version_arg):
    version = (version_arg or "").strip().lstrip("vV")
    if version:
        path = DIST / f"MaaAuto_Setup_v{version}-Windows-x64.exe"
        if path.exists():
            return version, path
        print(f"  ! 指定版本找不到安装包: {path}", flush=True)
        return version, None
    candidates = sorted(DIST.glob("MaaAuto_Setup_v*-Windows-x64.exe"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return "", None
    path = candidates[0]
    version = path.name.split("MaaAuto_Setup_v")[1].split("-Windows-x64")[0]
    return version, path


def main():
    ap = argparse.ArgumentParser(description="安装/卸载 smoke（发布前必过）")
    ap.add_argument("version", nargs="?", default="",
                    help="版本号（可带 v 前缀）；缺省取 dist 里最新的 Setup")
    ap.add_argument("--setup", default="", help="直接指定 Setup 路径")
    ap.add_argument("--dir", default="",
                    help="安装目录（默认 %%LOCALAPPDATA%%\Programs\MaaAuto_verify；别指向正式安装目录）")
    ap.add_argument("--keep", action="store_true", help="不卸载（排查用）")
    args = ap.parse_args()

    print("=" * 72, flush=True)

    if args.setup:
        setup = Path(args.setup)
        version = (args.version or "").strip().lstrip("vV")
        if not version:
            version = setup.name.split("MaaAuto_Setup_v")[-1].split("-Windows-x64")[0]
    else:
        version, setup = find_setup(args.version)

    app_dir = Path(args.dir) if args.dir else DEFAULT_DIR
    default_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MaaAuto"
    if app_dir.resolve() == default_app.resolve():
        print("  ! 拒绝在默认正式安装目录上跑 smoke（会删掉用户的安装与登记）",
              flush=True)
        return 1
    foreign = shell.foreign_install(app_dir)
    snapshot = shell.snapshot()
    print(f"  已备份外壳集成：{snapshot.summary()}", flush=True)
    if foreign is not None:
        print(f"  ! 本机另有一份安装：{foreign}（跑完会还原它的登记）", flush=True)

    print(f"[1] 安装包检查（版本 {version or '?'}）", flush=True)
    if not check("安装包存在", bool(setup) and setup.exists(), str(setup)):
        print("  找不到安装包，先跑 build_release.py。", flush=True)
        return 1
    check("版本号非空", bool(version))
    print(f"  大小 {setup.stat().st_size / 1024 / 1024:.1f} MB", flush=True)

    sums = setup.parent / "SHA256SUMS.txt"
    if sums.exists():
        listed = {}
        for line in sums.read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, name = line.split()
                listed[name] = digest
        check("SHA256SUMS 与安装包一致",
              listed.get(setup.name) == sha256_of(setup),
              f"sums={listed.get(setup.name)} actual={sha256_of(setup)}")

    # Inno cannot create its temp dir under Low IL / sandbox (error 5); copy to TEMP and run
    tmp_root = Path(tempfile.mkdtemp(prefix="maa_smoke_"))
    local_setup = tmp_root / setup.name
    shutil.copy2(setup, local_setup)

    print(f"[2] 静默安装 → {app_dir}", flush=True)
    # Clear leftovers; otherwise "install succeeded" may be inspecting the old dir
    if app_dir.exists():
        shutil.rmtree(app_dir, ignore_errors=True)
        time.sleep(0.5)
    shell.clear_start_menu_group()

    proc = run([local_setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                f"/DIR={app_dir}", "/MERGETASKS=!startmenuicon"], timeout=900)
    check("安装退出码 0", proc is not None and proc.returncode == 0,
          "" if proc is None else str(proc.returncode))

    print("[3] 安装结果校验", flush=True)
    check("安装目录存在", app_dir.exists(), str(app_dir))
    check("主程序在", (app_dir / "MaaAuto.exe").exists())
    check("升级器在（自动升级依赖）", (app_dir / "upgrade.exe").exists())
    check("卸载器在", (app_dir / "unins000.exe").exists())
    check("_internal 已解包", (app_dir / "_internal").is_dir())
    # /MERGETASKS=!startmenuicon must take effect, otherwise the user's Start menu gets shortcuts
    check("未创建开始菜单（任务参数生效）", not shell.start_menu_files(), str(START_MENU))

    manifest_path = app_dir / ".maaauto.json"
    manifest = {}
    if check("manifest 存在", manifest_path.exists(), str(manifest_path)):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            check("manifest 是合法 JSON", False, str(e))
    if manifest:
        check(f"manifest.version = {version}", manifest.get("version") == version,
              str(manifest.get("version")))
        check(f"manifest.installer_version = {version}",
              manifest.get("installer_version") == version,
              str(manifest.get("installer_version")))
        check("manifest_version = 3", manifest.get("manifest_version") == 3,
              str(manifest.get("manifest_version")))

        extra = manifest.get("extra") or {}
        expected = contract_extra()
        for key in ("update_api", "payload_asset_prefix", "min_installer_version"):
            if key in expected:
                check(f"extra.{key} 与 contract.py 一致",
                      extra.get(key) == expected[key],
                      f"{extra.get(key)!r} != {expected[key]!r}")

    if args.keep:
        print(f"[4] --keep：跳过卸载，安装目录保留在 {app_dir}", flush=True)
    else:
        print("[4] 静默卸载（/PURGEDATA）", flush=True)
        unins = app_dir / "unins000.exe"
        if unins.exists():
            proc = run([unins, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                        "/NORESTART", "/PURGEDATA"], timeout=600)
            check("卸载退出码 0", proc is not None and proc.returncode == 0,
                  "" if proc is None else str(proc.returncode))
        check("安装目录已清空（无残留）", wait_gone(app_dir), str(app_dir))
        check("没有残留卸载器进程", not uninstaller_alive())

    if not args.keep:
        try:
            print(f"[5] 还原外壳集成：{shell.restore(snapshot)}", flush=True)
        except Exception as e:
            print(f"  ! 还原外壳集成失败({e})，可跑 tools/repair_integration.py",
                  flush=True)
            fails.append("还原外壳集成")
    shutil.rmtree(tmp_root, ignore_errors=True)

    print("=" * 72, flush=True)
    if fails:
        print(f"FAILED {len(fails)} 项：", flush=True)
        for name in fails:
            print(f"  - {name}", flush=True)
        return 1
    print("SMOKE OK：安装 → 校验 → 卸载 全部通过", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"异常: {e}", flush=True)
        raise SystemExit(1)
