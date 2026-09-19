"""
MaaAuto 发布脚本 —— 生成 GitHub Release 所需的源码包。

产出：
    release/MaaAuto_Source.zip    源码包（顶层是源码根）

用法：
    python publish.py                 # 完整：build.py + Source.zip
    python publish.py --skip-build    # 跳过 build.py
    python publish.py --keep          # 不清理 release/ 旧文件
    python publish.py --debug         # build.py 保留控制台窗口

前置：
    pip install pyinstaller
    已在 app_info.py 更新 APP_VERSION

与安装器侧的约定（2026-09 冻结）：
  - MaaAuto_Source.zip 顶层直接是源码根（main.py / app_info.py / requirements.txt / ui/ / ...）
    不含 MaaAutoProject/ 这一层
  - 本脚本只生成 Source.zip
  - Online 包（MaaAuto_Online_vX.X.X-Windows-x64.exe）由安装器侧
    MaaAutoInstaller/build_installer.py 生成
  - 两个 asset 由用户手动上传到同一个 GitHub Release
  - Release tag 必须是 PEP 440 格式（v2.1.0 / v2.1.0b1），不能是 v2.1.0-beta
"""

import os
import re
import sys
import hashlib
import zipfile
import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
RELEASE_DIR = ROOT / "release"
APP_NAME = "MaaAuto"

# 打 Source.zip 时排除的顶层目录（不递归；子目录由 dirs[:] 过滤统一处理）
EXCLUDE_TOP = {
    ".git", ".hg", ".svn",
    ".idea", ".vscode",
    "venv", ".venv", "env", ".env",
    "node_modules",
    "__pycache__",
    "dist", "build", "release",
    "config", "logs",          # 运行后生成，不属于源码
}

# 打 Source.zip 时排除的顶层文件
EXCLUDE_FILES = {
    "MaaAuto.spec",
    "_version_info.txt",       # build.py 生成的，会重新生成
    ".DS_Store",
    "Thumbs.db",
    # ---- 开发/发布脚本（用户不需要）----
    "publish.py",              # 发布脚本
    "deploy_dev.py",           # 本地部署到 D:\MaaAuto 的辅助脚本
    "diagnose.py",             # 环境诊断脚本
    "selftest.py",             # 自测脚本（如果存在）
}

# 任意层级都排除的后缀
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log")


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def read_app_info():
    info = {"APP_NAME": APP_NAME, "APP_VERSION": "0.0.0"}
    path = ROOT / "app_info.py"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        for key in ("APP_NAME", "APP_VERSION"):
            m = re.search(rf'^{key}\s*=\s*["\']([^"\']*)["\']', text, re.M)
            if m:
                info[key] = m.group(1)
    return info


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


# --------------------------------------------------------------------------- #
# build.py
# --------------------------------------------------------------------------- #
def run_build(debug=False):
    build_script = ROOT / "build.py"
    if not build_script.exists():
        print(f"[error] 找不到 build.py: {build_script}")
        sys.exit(1)

    cmd = [sys.executable, str(build_script)]
    if debug:
        cmd.append("--debug")

    print(f"[publish] 调用 build.py：{' '.join(cmd)}")
    ret = subprocess.call(cmd, cwd=str(ROOT))
    if ret != 0:
        print(f"[error] build.py 失败，退出码 {ret}")
        sys.exit(ret)


# --------------------------------------------------------------------------- #
# Source.zip
# --------------------------------------------------------------------------- #
def make_source_zip(version: str) -> Path:
    """
    打包源码 → release/MaaAuto_Source.zip
    顶层直接是源码根。
    """
    out = RELEASE_DIR / "MaaAuto_Source.zip"
    if out.exists():
        out.unlink()

    print(f"[publish] 生成 Source.zip: {out.name}")

    count = 0
    skipped = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(ROOT):
            root_path = Path(root)

            dirs[:] = [
                d for d in dirs
                if d not in EXCLUDE_TOP and not d.startswith(".")
            ]

            rel_root = root_path.relative_to(ROOT)

            for fname in files:
                if not rel_root.parts and fname in EXCLUDE_FILES:
                    skipped.append(fname)
                    continue
                if fname.endswith(EXCLUDE_SUFFIXES):
                    continue
                if fname.startswith(".") and fname != ".gitignore":
                    continue

                fpath = root_path / fname
                arcname = fpath.relative_to(ROOT).as_posix()
                try:
                    zf.write(fpath, arcname)
                    count += 1
                except Exception as e:
                    print(f"[warn] 跳过 {arcname}: {e}")

    size = out.stat().st_size
    print(f"[publish] Source.zip 完成：{count} 个文件，{human_size(size)}")
    if skipped:
        print(f"[publish] 已排除开发脚本: {', '.join(sorted(set(skipped)))}")
    return out


# --------------------------------------------------------------------------- #
# 依赖检查
# --------------------------------------------------------------------------- #
def check_dependencies():
    """
    检查 3 类依赖：
      1. pip 包（requirements.txt 里应声明）
      2. 本地模块（项目根目录应有对应 .py 文件）
      3. 关键资源文件（build.py add-data 的目录）
    """
    problems = []

    # ---- 1) pip 包 ----
    req = ROOT / "requirements.txt"
    if not req.exists():
        problems.append("requirements.txt 不存在")
        req_text = ""
    else:
        try:
            req_text = req.read_text(encoding="utf-8").lower()
        except Exception:
            req_text = ""

    required_pip = {
        "pyside6": "PySide6",
        "pyinstaller": "pyinstaller",
        "psutil": "psutil",
        "pyautogui": "pyautogui",
        "pillow": "Pillow",
        "packaging": "packaging",
        "pywin32": "pywin32",
    }
    for key, pkg in required_pip.items():
        if key not in req_text:
            problems.append(f"requirements.txt 缺少 pip 包: {pkg}")

    # ---- 2) 本地模块 ----
    local_modules = [
        "serverchan_sdk.py",
    ]
    for name in local_modules:
        if not (ROOT / name).exists():
            problems.append(
                f"缺少本地模块: {name}\n"
                f"          （notifier.py / settings_page.py 依赖它）\n"
                f"          （从 git 或备份恢复，或改用 PyPI 的 serverchan-sdk）"
            )

    # ---- 3) 资源目录 ----
    resource_dirs = ["resources", "themes", "i18n"]
    for name in resource_dirs:
        if not (ROOT / name).is_dir():
            problems.append(f"缺少资源目录: {name}/")

    # ---- 报告 ----
    if problems:
        print()
        print("=" * 60)
        print("[warn] 发布前检查发现问题：")
        print("=" * 60)
        for p in problems:
            print(f"  - {p}")
        print("=" * 60)
        print()
    else:
        print("[publish] 依赖检查通过")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="MaaAuto 发布脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-build", action="store_true",
                        help="跳过 build.py（复用现有 dist/）")
    parser.add_argument("--keep", action="store_true",
                        help="不清理 release/ 旧 zip")
    parser.add_argument("--debug", action="store_true",
                        help="build.py 保留控制台窗口")
    args = parser.parse_args()

    info = read_app_info()
    version = info["APP_VERSION"]

    print("=" * 60)
    print(f"MaaAuto 发布脚本 —— v{version}")
    print("=" * 60)
    print(f"项目根目录：{ROOT}")
    print(f"Python：{sys.version.split()[0]}")
    print("=" * 60)

    # 0. 依赖检查（先做，早暴露问题）
    check_dependencies()

    # 1. release/ 目录
    RELEASE_DIR.mkdir(exist_ok=True)
    if not args.keep:
        old_zips = list(RELEASE_DIR.glob("*.zip"))
        for old in old_zips:
            print(f"[clean] 删除旧文件: {old.name}")
            old.unlink()

    # 2. 打包
    if not args.skip_build:
        run_build(debug=args.debug)
    else:
        print("[publish] 跳过 build.py（--skip-build）")

    # 3. Source.zip
    source_zip = make_source_zip(version)

    # 4. sha256
    src_sha = sha256_of_file(source_zip)

    # 5. 报告
    print()
    print("=" * 60)
    print(f"[OK] 发布包已生成：{RELEASE_DIR}")
    print("=" * 60)
    print()
    print(f"  {source_zip.name}")
    print(f"    用途：升级器（upgrade.exe）源码包")
    print(f"    大小：{human_size(source_zip.stat().st_size)}")
    print(f"    sha256：{src_sha}")
    print()
    print("=" * 60)
    print("【下一步：手动上传两个 asset】")
    print("=" * 60)
    print()
    print(f"  - MaaAuto_Source.zip")
    print(f"      ← 本脚本刚生成，位于 release/ 目录")
    print()
    print(f"  - MaaAuto_Online_v{version}-Windows-x64.exe")
    print(f"      ← 由安装器侧 MaaAutoInstaller/build_installer.py 生成")
    print(f"         路径：MaaAutoInstaller/dist/")
    print()
    print("  两个 asset 一起上传到同一个 GitHub Release。")
    print()
    print("=" * 60)
    print("  注意：")
    print(f"    * tag（必须 PEP 440）：v{version}")
    print("    * tag 不能是 v2.1.0-beta，只能是 v2.1.0 / v2.1.0b1 / v2.1.0rc1")
    print("    * Source.zip 是升级器必需的，别忘了传")
    print()


if __name__ == "__main__":
    main()