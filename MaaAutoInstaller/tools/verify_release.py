"""Full installer verification: silent install -> content checks -> fake
Release upgrade -> uninstall.

Usage (from the installer repo root) ::

    python MaaAutoInstaller/tools/verify_release.py 1.2.0

Prerequisites:
  * Setup / Online / payload / SHA256SUMS already built into dist/ by build_release.py;
  * the current user can install per-user programs (no admin required).

Checks:
  1. all artifacts present + SHA256SUMS matching the files;
  2. install (``/MERGETASKS=!startmenuicon``) -> no Start menu created; manifest version correct;
  3. packaged content: i18n keys consistent, tutorial/announcements/templates included;
  4. uninstall leaves nothing behind;
  5. default install (creates the Start menu) -> both shortcuts;
  6. offline upgrade via tools/fake_release_server.py (1.0.0 -> target version),
     verifying version/manifest/user data/no leftover flags;
  7. uninstall (``/PURGEDATA``) -> install dir, Start menu and desktop shortcut all removed.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # MaaAutoInstaller/tools
INSTALLER_ROOT = HERE.parent.parent             # MaaAuto-Installer/
DIST = INSTALLER_ROOT / "dist"
sys.path.insert(0, str(HERE.parent))   # MaaAutoInstaller/, package name is installer

from installer.core import shell_integration as shell  # noqa: E402

# Verification must install into a **separate directory**: Inno's uninstall
# registry key, Start menu group and desktop shortcut are shared globally by
# AppId, so installing over the user's real install dir (default
# %LOCALAPPDATA%\Programs\MaaAuto, or a custom D:\MaaAuto) and then uninstalling
# deletes the user's registration too -- 1.4.1 was bitten by exactly this:
# "Settings > Apps" showed "the system cannot find the app", and the Start menu
# and desktop icons disappeared with it. Program files were untouched; only the
# registration was broken.
APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "MaaAuto_verify"
SM = shell.start_menu_group()
DESKTOP_LNK = shell.desktop_lnk()

# Back up the shell integration before starting; restore it verbatim at the end
_foreign = shell.foreign_install(APP_DIR)
if _foreign is not None:
    print("=" * 72)
    print(f"[!] 检测到本机另有一份 MaaAuto 安装在 {_foreign}")
    print("    本脚本会临时改写共享的卸载注册表项和快捷方式，")
    print("    跑完会自动还原；中途中断可用 tools/repair_integration.py 修复。")
    print("=" * 72)
_snapshot = shell.snapshot()
print(f"[i] 已备份外壳集成：{_snapshot.summary()}")

VERSION = sys.argv[1] if len(sys.argv) > 1 else ""
if not VERSION:
    raise SystemExit("用法: python verify_release.py <version>")

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], **kw)


def uninstaller_alive():
    try:
        import psutil
    except ImportError:
        return False
    for proc in psutil.process_iter(["name"]):
        name = (proc.info["name"] or "").lower()
        if name.startswith("unins") or name.startswith("_iu"):
            return True
    return False


def wait_gone(path: Path, timeout=120):
    for _ in range(timeout * 2):
        if not path.exists() and not uninstaller_alive():
            return True
        time.sleep(0.5)
    return not path.exists()


setup = DIST / f"MaaAuto_Setup_v{VERSION}-Windows-x64.exe"
online = DIST / f"MaaAuto_Online_v{VERSION}-Windows-x64.exe"
payload = DIST / f"MaaAuto_payload_v{VERSION}.zip"
deltas = sorted(DIST.glob(f"MaaAuto_delta_v*_to_{VERSION}.zip"))
delta = deltas[0] if deltas else None
sums = DIST / "SHA256SUMS.txt"

print("=" * 72)
print(f"[0] 产物检查（{VERSION}）")
for p in (setup, online, payload, sums):
    check(f"存在 {p.name}", p.exists(), str(p))
if delta is not None:
    check(f"存在 {delta.name}", delta.exists(), str(delta))
if sums.exists():
    listed = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split()
            listed[name] = digest
    for p in [setup, online, payload] + ([delta] if delta else []):
        if p.exists():
            check(f"SHA256 匹配 {p.name}", listed.get(p.name) == sha(p))

work = Path(tempfile.mkdtemp(prefix=f"maa_setup_{VERSION}_"))
local_setup = work / setup.name
shutil.copy2(setup, local_setup)


def install(extra=None):
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR, ignore_errors=True)
    shell.clear_start_menu_group()
    if DESKTOP_LNK.exists():
        DESKTOP_LNK.unlink()
    # /DIR is mandatory: Inno reuses the last install dir by default (this machine
    # was once installed to D:\MaaAuto by deploy_dev.py)
    args = [local_setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            f"/DIR={APP_DIR}"]
    if extra:
        args += extra
    return run(args, timeout=600).returncode


def uninstall(purge=True):
    args = [APP_DIR / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES",
            "/NORESTART"]
    if purge:
        args.append("/PURGEDATA")
    code = run(args, timeout=300).returncode
    wait_gone(APP_DIR)
    time.sleep(1)
    return code


print("=" * 72)
print("[1] 安装：不创建开始菜单（/MERGETASKS=!startmenuicon）")
code = install(["/MERGETASKS=!startmenuicon"])
check("安装退出码 0", code == 0, str(code))
check("安装目录存在", APP_DIR.exists())
check("未创建开始菜单（任务生效）", not shell.start_menu_files(), str(SM))
manifest = json.loads((APP_DIR / ".maaauto.json").read_text(encoding="utf-8"))
check(f"manifest 版本 = {VERSION}", manifest.get("version") == VERSION,
      str(manifest.get("version")))
check(f"installer_version = {VERSION}",
      manifest.get("installer_version") == VERSION,
      str(manifest.get("installer_version")))

print("=" * 72)
print("[2] 打包内容校验")
res = APP_DIR / "_internal" / "resources"
ann = res / "announcements.json"
check("announcements.json 已打包", ann.exists(), str(ann))
if ann.exists():
    items = json.loads(ann.read_text(encoding="utf-8")).get("items") or []
    check("公告条目 >= 5", len(items) >= 5, str(len(items)))
    check("公告中英双语齐全",
          all(it.get("title", {}).get("zh_CN") and it.get("title", {}).get("en_US")
              and it.get("body", {}).get("zh_CN") and it.get("body", {}).get("en_US")
              for it in items))
check("内置模板仍在", (res / "maa_start.png").exists()
      and (res / "maaend_start.png").exists())

zh = APP_DIR / "_internal" / "i18n" / "zh_CN.json"
en = APP_DIR / "_internal" / "i18n" / "en_US.json"
check("i18n 存在", zh.exists() and en.exists())
if zh.exists() and en.exists():
    d_zh = json.loads(zh.read_text(encoding="utf-8"))
    d_en = json.loads(en.read_text(encoding="utf-8"))
    check("i18n 中英键数一致", len(d_zh) == len(d_en),
          f"{len(d_zh)} vs {len(d_en)}")
    for key in ("update.title", "announce.title", "tutorial.title",
                "tutorial.warn_maa", "tutorial.warn_maaend"):
        check(f"i18n 含 {key}", key in d_zh and key in d_en)
    check("教程含「完成后退出模拟器」",
          "完成后退出模拟器" in d_zh.get("tutorial.warn_maa", ""))
    check("教程含「关闭程序/关闭模拟器」",
          "关闭程序" in d_zh.get("tutorial.warn_maaend", "")
          or "关闭模拟器" in d_zh.get("tutorial.warn_maaend", ""))
check("主题样式存在",
      (APP_DIR / "_internal" / "themes" / "light.qss").exists()
      and (APP_DIR / "_internal" / "themes" / "dark.qss").exists())

print("=" * 72)
print("[3] 卸载（未建开始菜单的安装）")
code = uninstall()
check("卸载退出码 0", code == 0, str(code))
check("安装目录已删除", not APP_DIR.exists(), str(APP_DIR))
check("没有开始菜单残留", not shell.start_menu_files(), str(SM))

print("=" * 72)
print("[4] 安装（默认任务，创建开始菜单）")
code = install()
check("安装退出码 0", code == 0, str(code))
sm_files_real = shell.start_menu_files()
check("开始菜单已创建", bool(sm_files_real), str(SM))
sm_files = sorted(Path(p).name for p in sm_files_real if p.endswith(".lnk"))
check("开始菜单含两个快捷方式", len(sm_files) == 2, str(sm_files))

print("=" * 72)
print("[5] 升级链路（本地假 Release，不联网）")
manifest_path = APP_DIR / ".maaauto.json"
m = json.loads(manifest_path.read_text(encoding="utf-8"))
m["version"] = "1.0.0"
m["last_upgrade_from"] = ""
manifest_path.write_text(json.dumps(m, ensure_ascii=False, indent=2),
                         encoding="utf-8")
(APP_DIR / "config").mkdir(exist_ok=True)
(APP_DIR / "config" / "keep.txt").write_text("user-data", encoding="utf-8")

server = subprocess.Popen(
    [sys.executable, str(HERE / "fake_release_server.py"),
     "--payload", str(payload), "--version", VERSION, "--port", "8775",
     "--patch-manifest", str(APP_DIR)]
    + (["--delta", str(delta)] if delta else []),
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    encoding="utf-8", errors="replace")
try:
    import socket
    ready = False
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", 8775), timeout=0.2):
                ready = True
                break
        except OSError:
            time.sleep(0.1)
    check("假 Release 服务就绪", ready)

    upg = APP_DIR / "upgrade.exe"
    r = run([upg, "--from-main", "--check-only", "--no-ui"], timeout=180,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace")
    check("check-only 发现新版本", r.returncode == 0,
          f"{r.returncode}: {(r.stdout or '')[-300:]}")

    if delta is not None:
        print(f"  已挂差分资产 {delta.name}（基准 1.0.0 → 无补丁，应自动回退整包）")
    r = run([upg, "--from-main", "--no-ui"], timeout=600,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace")
    check("升级退出码 0", r.returncode == 0,
          f"{r.returncode}: {(r.stdout or '')[-600:]}")
    m2 = json.loads(manifest_path.read_text(encoding="utf-8"))
    check(f"升级后版本 = {VERSION}", m2.get("version") == VERSION,
          str(m2.get("version")))
    check("last_upgrade_from = 1.0.0", m2.get("last_upgrade_from") == "1.0.0")
    check("用户数据保留",
          (APP_DIR / "config" / "keep.txt").read_text(encoding="utf-8") == "user-data")
    check("无 .upgrading 残留", not (APP_DIR / "config" / ".upgrading").exists())
    r = run([upg, "--from-main", "--check-only", "--no-ui"], timeout=180,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace")
    check("已是最新（退出码 1）", r.returncode == 1, str(r.returncode))
finally:
    server.terminate()
    try:
        server.wait(timeout=10)
    except Exception:
        server.kill()

print("=" * 72)
print("[6] 卸载（有开始菜单的安装）")
code = uninstall()
check("卸载退出码 0", code == 0, str(code))
check("安装目录已删除", not APP_DIR.exists(), str(APP_DIR))
check("开始菜单目录已删除", not shell.start_menu_files(), str(SM))
check("桌面快捷方式不存在", not DESKTOP_LNK.exists())

print()
print("=" * 72)
print("[7] 还原本机原有的外壳集成")
try:
    _restored = shell.restore(_snapshot)
    print(f"  {_restored}")
    _files_now = shell.start_menu_files()
    check("开始菜单已按快照还原", _files_now == _snapshot.group_files,
          f"now={sorted(_files_now)} snap={sorted(_snapshot.group_files)}")
    if _snapshot.desktop_link is not None:
        check("桌面快捷方式已按快照还原",
              DESKTOP_LNK.exists()
              and DESKTOP_LNK.read_bytes() == _snapshot.desktop_link,
              str(DESKTOP_LNK))
    if _foreign is not None:
        loc = shell.installed_location()
        check(f"用户那份安装的登记已恢复（{_foreign}）",
              loc is not None and loc.resolve() == _foreign.resolve(), str(loc))
        check("还原后的卸载器文件存在",
              (_foreign / "unins000.exe").exists(), str(_foreign))
finally:
    shutil.rmtree(work, ignore_errors=True)

print()
print("=" * 72)
print("RESULT:", "ALL PASSED" if not fails else f"FAILED ({len(fails)}): {fails}")
sys.exit(1 if fails else 0)
