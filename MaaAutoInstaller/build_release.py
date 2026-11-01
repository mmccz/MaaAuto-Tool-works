"""One-shot build for MaaAuto 3.0.0 (shared by CI and local runs).

Outputs (in ``dist/`` by default)::

    MaaAuto_payload_v{ver}.zip          <- downloaded by the updater
    MaaAuto_Setup_v{ver}-Windows-x64.exe <- full installer for new users (payload embedded)
    MaaAuto_Online_v{ver}-Windows-x64.exe<- online bootstrap stub (about 2 MB)

Pipeline: contract check -> main app build.py -> trim payload -> pack upgrade.exe
-> zip payload -> compile the full installer with Inno -> compute sha256 ->
compile the online stub with Inno.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path

# The CI runner default stdout encoding is cp1252, so printing non-ASCII log
# text raises UnicodeEncodeError outright. Switch to UTF-8 right after import
# so local and CI runs behave the same.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent          # MaaAutoInstaller/
REPO = HERE.parent                              # MaaAuto-Installer/
BUILD = HERE / "_build"
DIST = REPO / "dist"
TOOLS = HERE / "tools"
PACKAGING = HERE / "packaging"
RESOURCES = HERE / "resources"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?$")

ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def err(msg: str) -> None:
    print(f"[build][ERROR] {msg}", file=sys.stderr, flush=True)


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_iscc(explicit: str = "") -> Path:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        raise FileNotFoundError(f"ISCC 不存在: {p}")

    # Candidate locations (choco / winget / manual installs differ)
    candidates = list(ISCC_CANDIDATES)
    for env_name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Inno Setup 6" / "ISCC.exe")
            candidates.append(Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    which = shutil.which("ISCC") or shutil.which("iscc")
    if which:
        candidates.insert(0, Path(which))

    for p in candidates:
        if p.exists():
            log(f"使用 ISCC: {p}")
            return p

    listed = "\n  ".join(str(p) for p in candidates)
    raise FileNotFoundError(
        "找不到 ISCC.exe（Inno Setup）。已尝试：\n  "
        f"{listed}\n请安装 Inno Setup 6（choco install innosetup）或传 --iscc。")


# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #
def read_app_info(source_dir: Path) -> dict:
    text = (source_dir / "app_info.py").read_text(encoding="utf-8")
    keys = ["APP_VERSION", "APP_UPDATE_API", "APP_MIN_INSTALLER_VERSION",
            "APP_PAYLOAD_ASSET_PREFIX", "APP_DELTA_ASSET_PREFIX"]
    out = {}
    for key in keys:
        m = re.search(rf'^{key}\s*=\s*["\']([^"\']*)["\']', text, re.M)
        out[key] = m.group(1) if m else ""
    return out


def check_contract(source_dir: Path) -> dict:
    info = read_app_info(source_dir)
    version = info["APP_VERSION"]
    problems = []

    if not version:
        problems.append("APP_VERSION 缺失，或不是行首字符串常量")
    elif not VERSION_RE.match(version):
        problems.append(f"APP_VERSION={version!r} 不符合 X.Y.Z[(a|b|rc)N][.postN]")
    for key in ("APP_UPDATE_API", "APP_MIN_INSTALLER_VERSION",
                "APP_PAYLOAD_ASSET_PREFIX", "APP_DELTA_ASSET_PREFIX"):
        if not info[key]:
            problems.append(f"{key} 缺失")

    sys.path.insert(0, str(HERE))
    from installer.contract import default_manifest_extra, APP_INFO_CONSTANTS
    extra = default_manifest_extra()
    for extra_key, const_name in APP_INFO_CONSTANTS.items():
        if info.get(const_name) and info[const_name] != str(extra[extra_key]):
            problems.append(
                f"{const_name} 与 installer/contract.py 不一致："
                f"源码={info[const_name]!r}，安装器={extra[extra_key]!r}")

    if problems:
        raise RuntimeError("契约校验失败：\n  - " + "\n  - ".join(problems))
    log(f"契约校验通过: {version} / payload 前缀 {info['APP_PAYLOAD_ASSET_PREFIX']}")
    return info


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
def run(cmd, cwd: Path, timeout: int = 3600, tag: str = "") -> None:
    log(f"执行{(' ' + tag) if tag else ''}: {' '.join(str(c) for c in cmd)}")
    # The child process needs UTF-8 too: the CI runner default stdout is
    # cp1252, so Chinese output from build.py / PyInstaller raises
    # UnicodeEncodeError.
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [str(c) for c in cmd], cwd=str(cwd), env=child_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        if line:
            print(f"  | {line}", flush=True)
    proc.wait(timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"命令失败（exit {proc.returncode}）: {cmd[0]}")


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def build_main(source_dir: Path) -> Path:
    log("打包主程序（build.py）...")
    run([sys.executable, "build.py"], cwd=source_dir, tag="主程序")
    out = source_dir / "dist" / "MaaAuto"
    if not (out / "MaaAuto.exe").exists():
        raise RuntimeError(f"主程序产物缺失: {out / 'MaaAuto.exe'}")
    log(f"主程序产物: {out}")
    return out


def make_payload(main_dist: Path, trim: bool) -> Path:
    payload = BUILD / "payload"
    shutil.rmtree(payload, ignore_errors=True)
    log("复制产物为 payload...")
    shutil.copytree(main_dist, payload)

    if trim:
        log("裁剪 payload...")
        run([sys.executable, str(PACKAGING / "trim_payload.py"), str(payload), "--apply"],
            cwd=HERE, tag="裁剪")

    # payload must not carry user data
    for name in ("config", "logs", ".maaauto.json"):
        p = payload / name
        if p.exists():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
    return payload


def build_upgrade_exe(debug: bool) -> Path:
    out_dir = BUILD / "stub"
    shutil.rmtree(out_dir, ignore_errors=True)
    work = BUILD / "pyi_work"
    shutil.rmtree(work, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--console" if debug else "--windowed",
        "--name", "upgrade",
        "--noupx",
        "--icon", str(RESOURCES / "icon_upgrade.ico"),
        "--distpath", str(out_dir),
        "--workpath", str(work),
        "--specpath", str(BUILD),
        "--paths", str(HERE),
        "--hidden-import", "psutil",
        "--hidden-import", "installer.core.payload",
        # bsdiff4 is only used on the build machine to generate patches; the
        # apply side is stdlib-only bspatch. Without this exclusion PyInstaller
        # follows the lazy import in delta.py and bundles it.
        "--exclude-module", "bsdiff4",
        str(TOOLS / "upgrade_stub.py"),
    ]
    log("打包 upgrade.exe ...")
    run(cmd, cwd=HERE, tag="upgrade.exe")
    exe = out_dir / "upgrade.exe"
    if not exe.exists():
        raise RuntimeError(f"upgrade.exe 未生成: {exe}")
    log(f"upgrade.exe: {human(exe.stat().st_size)}")
    return exe


def make_payload_zip(payload: Path, upgrade_exe: Path, version: str,
                     prefix: str) -> Path:
    shutil.copy2(upgrade_exe, payload / "upgrade.exe")
    out = BUILD / f"{prefix}{version}.zip"
    if out.exists():
        out.unlink()
    log("压缩 payload（LZMA）...")
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_LZMA) as zf:
        for p in sorted(payload.rglob("*")):
            if not p.is_file():
                continue
            zf.write(p, p.relative_to(payload).as_posix())
            count += 1
    log(f"payload: {count} 个文件，{human(out.stat().st_size)}")
    return out


def fetch_prev_payload(info: dict, dest: Path) -> tuple:
    """Fetch the payload of the latest stable release from GitHub as the delta base.

     CI builds every release in a clean environment with no previous artifacts,
     so it queries ``APP_UPDATE_API`` for latest and downloads
     ``payload_v{tag}.zip`` (about 68 MB, fast on a runner).
    """
    import json as _json
    import urllib.request as _req

    api = info["APP_UPDATE_API"]
    log(f"查询上一版 Release: {api}")
    request = _req.Request(api, headers={"User-Agent": "MaaAutoBuild/1.0"})
    with _req.urlopen(request, timeout=30) as resp:
        release = _json.load(resp)

    tag = (release.get("tag_name") or "").lstrip("vV")
    want = f"{info['APP_PAYLOAD_ASSET_PREFIX']}{tag}.zip"
    url = ""
    for asset in release.get("assets") or []:
        if (asset.get("name") or "") == want:
            url = asset.get("browser_download_url") or ""
            break
    if not url:
        raise RuntimeError(f"最新 Release 里没有 {want}，无法生成差分包")

    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"下载差分基准: {want}")
    with _req.urlopen(_req.Request(url, headers={"User-Agent": "MaaAutoBuild/1.0"}),
                      timeout=600) as src, open(dest, "wb") as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    return tag, dest


def build_delta_zip(payload: Path, base: Path, base_version: str,
                    version: str, info: dict) -> Path:
    """Build ``{delta_prefix}{base}_to_{version}.zip``."""
    from installer.core import delta as delta_mod
    out = DIST / f"{info['APP_DELTA_ASSET_PREFIX']}{base_version}_to_{version}.zip"
    log(f"生成差分包: {base_version} -> {version}")
    delta_mod.build_delta(payload, base, out, version, base_version, log=log)
    return out


def compile_installer(version: str, info: dict, payload_dir: Path,
                      iscc: Path) -> Path:
    exe_name = f"MaaAuto_Setup_v{version}-Windows-x64.exe"
    # Inno VersionInfoVersion accepts digits only: 1.0.1b1 -> 1.0.1.0
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    quad = f"{m.group(1)}.{m.group(2)}.{m.group(3)}.0" if m else "0.0.0.0"
    log("编译完整安装包（Inno Setup）...")
    run([
        iscc,
        f"/DMyAppVersion={version}",
        f"/DMyVersionQuad={quad}",
        f"/DMyInstallerVersion={read_installer_version()}",
        f"/DMyUpdateApi={info['APP_UPDATE_API']}",
        f"/DMyPayloadPrefix={info['APP_PAYLOAD_ASSET_PREFIX']}",
        f"/DMyMinInstaller={info['APP_MIN_INSTALLER_VERSION']}",
        f"/DMyPayloadDir={payload_dir}",
        f"/DMyOutputDir={DIST}",
        f"/DMyIcon={RESOURCES / 'icon.ico'}",
        f"/DMySetupBase={exe_name[:-4]}",
        str(PACKAGING / "installer.iss"),
    ], cwd=HERE, tag="完整安装包")
    exe = DIST / exe_name
    if not exe.exists():
        raise RuntimeError(f"安装包未生成: {exe}")
    log(f"完整安装包: {human(exe.stat().st_size)}")
    return exe


def compile_online(version: str, setup_name: str, setup_sha: str,
                   iscc: Path) -> Path:
    url = (f"https://github.com/mmccz/MaaAuto-Tool-works/releases/download/"
           f"v{version}/{setup_name}")
    exe_name = f"MaaAuto_Online_v{version}-Windows-x64.exe"
    log("编译在线引导包（Inno Setup）...")
    run([
        iscc,
        f"/DMyAppVersion={version}",
        f"/DMySetupUrl={url}",
        f"/DMySetupSha256={setup_sha}",
        f"/DMyOutputDir={DIST}",
        f"/DMyIcon={RESOURCES / 'icon.ico'}",
        f"/DMyOnlineBase={exe_name[:-4]}",
        str(PACKAGING / "online.iss"),
    ], cwd=HERE, tag="在线引导包")
    exe = DIST / exe_name
    if not exe.exists():
        raise RuntimeError(f"在线引导包未生成: {exe}")
    log(f"在线引导包: {human(exe.stat().st_size)}")
    return exe


def read_installer_version() -> str:
    p = HERE / "VERSION"
    return p.read_text(encoding="utf-8").strip() if p.exists() else "0.0.0"


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="构建 MaaAuto 3.0.0 发布产物")
    ap.add_argument("--source-dir", type=Path, default=None,
                    help="主程序源码目录（默认自动探测）")
    ap.add_argument("--skip-main-build", action="store_true",
                    help="复用主程序已有 dist/MaaAuto")
    ap.add_argument("--skip-stub", action="store_true",
                    help="复用已有 _build/stub/upgrade.exe")
    ap.add_argument("--no-trim", action="store_true", help="不裁剪 payload")
    ap.add_argument("--keep-build", action="store_true", help="保留 _build/")
    ap.add_argument("--debug", action="store_true", help="upgrade.exe 保留控制台")
    ap.add_argument("--iscc", default="", help="ISCC.exe 路径")
    ap.add_argument("--delta-from", default="",
                    help="差分包基准：上一版 payload .zip 或已解压目录")
    ap.add_argument("--delta-base-version", default="",
                    help="基准版本号（--delta-from 给目录/无版本名时必填）")
    ap.add_argument("--delta-auto", action="store_true",
                    help="自动从 GitHub 最新 Release 下载 payload 作为基准（CI 用）")
    args = ap.parse_args()

    started = time.time()
    source_dir = (args.source_dir or default_source_dir()).resolve()
    if not (source_dir / "app_info.py").exists():
        err(f"源码目录无效: {source_dir}")
        return 1

    try:
        info = check_contract(source_dir)
    except Exception as e:
        err(str(e))
        traceback.print_exc()
        return 1

    version = info["APP_VERSION"]
    prefix = info["APP_PAYLOAD_ASSET_PREFIX"]
    try:
        iscc = find_iscc(args.iscc)
    except Exception as e:
        err(str(e))
        traceback.print_exc()
        return 1

    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    try:
        if args.skip_main_build:
            main_dist = source_dir / "dist" / "MaaAuto"
            if not (main_dist / "MaaAuto.exe").exists():
                raise RuntimeError(f"--skip-main-build 但产物不存在: {main_dist}")
            log(f"复用主程序产物: {main_dist}")
        else:
            main_dist = build_main(source_dir)

        payload = make_payload(main_dist, trim=not args.no_trim)

        if args.skip_stub:
            upgrade_exe = BUILD / "stub" / "upgrade.exe"
            if not upgrade_exe.exists():
                raise RuntimeError(f"--skip-stub 但不存在: {upgrade_exe}")
        else:
            upgrade_exe = build_upgrade_exe(args.debug)

        payload_zip = make_payload_zip(payload, upgrade_exe, version, prefix)
        shutil.copy2(payload_zip, DIST / payload_zip.name)

        setup = compile_installer(version, info, payload, iscc)
        setup_sha = sha256_of(setup)
        online = compile_online(version, setup.name, setup_sha, iscc)

        # Delta package (optional): changed files only, measured 61 MB -> 0.6 MB
        delta_zip = None
        base_path = args.delta_from
        base_version = args.delta_base_version
        if not base_path and args.delta_auto:
            base_version, base_path = fetch_prev_payload(info, BUILD / "prev_payload.zip")
        if base_path:
            if not base_version:
                m = re.search(r"(\d+\.\d+\.\d+(?:[ab]|rc)?\d*)", Path(base_path).name)
                if not m:
                    raise RuntimeError("--delta-from 无法推断版本号，请加 --delta-base-version")
                base_version = m.group(1)
            delta_zip = build_delta_zip(payload, Path(base_path), base_version,
                                        version, info)
        elif args.delta_auto or args.delta_from:
            raise RuntimeError("未能确定差分基准")

        lines = []
        for p in (payload_zip, setup, online):
            lines.append(f"{sha256_of(p)}  {p.name}")
        if delta_zip is not None:
            lines.append(f"{sha256_of(delta_zip)}  {delta_zip.name}")
        (DIST / "SHA256SUMS.txt").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")

        if not args.keep_build:
            shutil.rmtree(BUILD / "pyi_work", ignore_errors=True)
            shutil.rmtree(BUILD / "payload", ignore_errors=True)
            spec = BUILD / "upgrade.spec"
            if spec.exists():
                spec.unlink()

        print()
        print("=" * 64)
        print(f"构建完成（{time.time() - started:.0f}s）→ {DIST}")
        print("=" * 64)
        for p in [setup, online, payload_zip] + ([delta_zip] if delta_zip else []):
            print(f"  {p.name:<52} {human(p.stat().st_size):>10}")
        print()
        print("README / Release 正文可直接引用 SHA256SUMS.txt")
        print()
        print("提示：如果本仓库目录被安全软件/沙箱标记为低完整性（Low IL），")
        print("      从 dist/ 直接双击安装包会报「无法创建目录 is-*.tmp，错误 5」。")
        print("      把 exe 复制到桌面或下载目录再运行即可。")
        return 0

    except Exception as e:
        err(str(e))
        traceback.print_exc()
        return 1


def default_source_dir() -> Path:
    candidates = [
        REPO.parent / "MaaAuto-Tool-works" / "MaaAutoProject",
        REPO / "MaaAuto-Tool-works" / "MaaAutoProject",
        REPO / "MaaAutoProject",
    ]
    for c in candidates:
        if (c / "app_info.py").exists():
            return c
    return candidates[0]


if __name__ == "__main__":
    raise SystemExit(main())
