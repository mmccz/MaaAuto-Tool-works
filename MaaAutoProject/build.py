"""
MaaAuto 一键打包脚本（PyInstaller）。

用法：
    python build.py                 # 默认：onedir + 无控制台
    python build.py --debug         # 保留控制台窗口
    python build.py --onefile       # 单文件模式（不推荐，启动慢）
    python build.py --keep-build    # 不清理 build/ 和 dist/
    python build.py --no-clean      # 跳过 pyinstaller --clean

产物：
    dist/MaaAuto/MaaAuto.exe
    dist/MaaAuto/_internal/...
    dist/MaaAuto/requirements.txt   （附带文件）
    dist/MaaAuto/README.md
    dist/MaaAuto/LICENSE
    dist/MaaAuto/CHANGELOG.md
    dist/MaaAuto/_version_info.txt

前置：
    pip install pyinstaller
"""

import os
import re
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_FILE = ROOT / "MaaAuto.spec"
VERSION_FILE = ROOT / "_version_info.txt"

# 打进包里的资源目录（源路径 → 包内相对路径）
DATA_DIRS = [
    ("resources", "resources"),
    ("themes",    "themes"),
    ("i18n",      "i18n"),
]

# ★ 额外要拷到 dist/MaaAuto/ 顶层的文件（不通过 PyInstaller add-data）
EXTRA_DIST_FILES = [
    "requirements.txt",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "_version_info.txt",   # 由本脚本生成
]

# pyautogui / Pillow / psutil / cv2 等常被 PyInstaller 漏掉的隐式导入
HIDDEN_IMPORTS = [
    "pyscreeze",
    "pygetwindow",
    "pymsgbox",
    "mouseinfo",
    "PIL",
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageQt",
    "psutil",
    "win32gui",
    "win32process",
    "win32con",
    "winreg",
    "serverchan_sdk",   # ← 本地文件 serverchan_sdk.py，确保进 exe
    "cv2",              # ← pyautogui confidence 参数依赖（opencv-python-headless）
]

# 体积优化：明确排除这些包
EXCLUDES = [
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    "IPython",
    "jupyter",
    "notebook",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "wx",
    # "tkinter",   # 若 pyautogui 弹窗报错，取消这行注释
]

PYCACHE_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    ".idea", ".vscode",
    "venv", ".venv", "env", ".env",
    "node_modules",
    "__pycache__",
    "dist", "build",
}


# --------------------------------------------------------------------------- #
# 元信息
# --------------------------------------------------------------------------- #
def read_app_info():
    info = {
        "APP_NAME": "MaaAuto",
        "APP_DISPLAY_NAME": "MaaAuto",
        "APP_VERSION": "0.0.0",
        "APP_ORG": "MaaAuto",
        "APP_GITHUB": "",
        "APP_EMAIL": "",
        "APP_LICENSE": "MIT",
    }
    path = ROOT / "app_info.py"
    if not path.exists():
        return info
    text = path.read_text(encoding="utf-8")
    for key in list(info.keys()):
        m = re.search(rf'^{key}\s*=\s*["\']([^"\']*)["\']', text, re.M)
        if m:
            info[key] = m.group(1)
    return info


def version_tuple(ver_str):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", ver_str or "")
    if not m:
        return (0, 0, 0, 0)
    return tuple(int(x) for x in m.groups()) + (0,)


# --------------------------------------------------------------------------- #
# version_info.txt 生成
# --------------------------------------------------------------------------- #
def write_version_file(info):
    ver = version_tuple(info["APP_VERSION"])
    vt = ", ".join(str(x) for x in ver)
    name = info.get("APP_DISPLAY_NAME") or info.get("APP_NAME", "MaaAuto")
    company = info.get("APP_ORG", name)
    copyright_text = f"Copyright (C) 2024-2026 {company}. All rights reserved."
    license_text = info.get("APP_LICENSE", "")
    github = info.get("APP_GITHUB", "")
    email = info.get("APP_EMAIL", "")

    content = f"""# UTF-8
#
# PyInstaller 生成的 Windows 版本资源文件
# 由 build.py 自动生成，请勿手动修改。
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({vt}),
    prodvers=({vt}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'080404B0',
        [StringStruct(u'CompanyName',      u'{company}'),
         StringStruct(u'FileDescription',  u'{name}'),
         StringStruct(u'FileVersion',      u'{info["APP_VERSION"]}'),
         StringStruct(u'InternalName',     u'{info["APP_NAME"]}'),
         StringStruct(u'LegalCopyright',   u'{copyright_text}'),
         StringStruct(u'LegalTrademarks',  u''),
         StringStruct(u'OriginalFilename', u'{info["APP_NAME"]}.exe'),
         StringStruct(u'ProductName',      u'{name}'),
         StringStruct(u'ProductVersion',   u'{info["APP_VERSION"]}'),
         StringStruct(u'Comments',         u'{github} {email}'.strip()),
         StringStruct(u'License',          u'{license_text}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""
    VERSION_FILE.write_text(content, encoding="utf-8")
    return VERSION_FILE


# --------------------------------------------------------------------------- #
# 清理
# --------------------------------------------------------------------------- #
def clean_artifacts():
    for p in (DIST_DIR, BUILD_DIR):
        if p.exists():
            print(f"[clean] 删除 {p}")
            shutil.rmtree(p, ignore_errors=True)
    if SPEC_FILE.exists():
        print(f"[clean] 删除 {SPEC_FILE.name}")
        try:
            SPEC_FILE.unlink()
        except Exception:
            pass


def clean_pycache(root: Path = ROOT):
    removed = 0
    for dirpath, dirnames, _files in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if d.lower() not in PYCACHE_SKIP_DIRS]
        if "__pycache__" in dirnames:
            p = Path(dirpath) / "__pycache__"
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
            dirnames.remove("__pycache__")
    if removed:
        print(f"[pycache] 清理 {removed} 个 __pycache__")


# --------------------------------------------------------------------------- #
# 环境检查
# --------------------------------------------------------------------------- #
def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        pass
    print("=" * 60)
    print("未检测到 PyInstaller。")
    print("请先安装：pip install pyinstaller")
    print("=" * 60)
    return False


# --------------------------------------------------------------------------- #
# 组装命令
# --------------------------------------------------------------------------- #
def build_command(args, info, version_file):
    cmd = [sys.executable, "-m", "PyInstaller"]
    cmd.append("--noconfirm")
    if not args.no_clean:
        cmd.append("--clean")

    cmd += ["--name", info["APP_NAME"]]

    icon = ROOT / "resources" / "icon.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]
    else:
        print(f"[warn] 找不到图标 {icon}，将使用默认图标。")

    cmd.append(str(ROOT / "main.py"))
    cmd.append("--onefile" if args.onefile else "--onedir")
    cmd.append("--console" if args.debug else "--windowed")

    # 资源目录
    sep = os.pathsep
    for src, dst in DATA_DIRS:
        src_path = ROOT / src
        if src_path.exists():
            cmd += ["--add-data", f"{src_path}{sep}{dst}"]
        else:
            print(f"[warn] 资源目录不存在，跳过: {src_path}")

    # 隐式导入
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]

    # 排除
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]

    # 版本信息
    if version_file and not args.no_version:
        cmd += ["--version-file", str(version_file)]

    return cmd


# --------------------------------------------------------------------------- #
# 拷贝额外文件到 dist 顶层
# --------------------------------------------------------------------------- #
def copy_extra_dist_files(target_dir: Path):
    """
    PyInstaller 只打 exe/_internal，我们要把 requirements.txt、README.md
    等文件放在 dist/MaaAuto/ 顶层（和 exe 同级），让用户看到跟以前一样的结构。
    """
    target_dir = Path(target_dir)
    copied = 0
    for name in EXTRA_DIST_FILES:
        src = ROOT / name
        if not src.exists():
            print(f"[warn] 附带文件不存在，跳过: {name}")
            continue
        dst = target_dir / name
        try:
            if dst.exists():
                dst.unlink()
            shutil.copy2(src, dst)
            print(f"[dist] + {name}")
            copied += 1
        except Exception as e:
            print(f"[warn] 复制 {name} 失败: {e}")
    return copied


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="MaaAuto 打包脚本（PyInstaller）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--debug", action="store_true",
                        help="保留控制台窗口")
    parser.add_argument("--onefile", action="store_true",
                        help="单文件模式（启动慢，不推荐）")
    parser.add_argument("--keep-build", action="store_true",
                        help="不自动清理 build/ 和 dist/")
    parser.add_argument("--no-clean", action="store_true",
                        help="跳过 pyinstaller --clean")
    parser.add_argument("--no-version", action="store_true",
                        help="不生成 exe 版本信息")
    args = parser.parse_args()

    print("=" * 60)
    print("MaaAuto 打包脚本")
    print("=" * 60)
    print(f"项目根目录 : {ROOT}")
    print(f"Python     : {sys.version.split()[0]} ({sys.executable})")
    print(f"模式       : {'onefile' if args.onefile else 'onedir'}"
          f" / {'console' if args.debug else 'windowed'}")
    print("=" * 60)

    if not ensure_pyinstaller():
        sys.exit(1)

    # 检查 cv2 是否可用（否则打出来的包找图会失败）
    try:
        import cv2  # noqa: F401
        print(f"[info] OpenCV 已安装（找图 confidence 参数可用）")
    except ImportError:
        print()
        print("=" * 60)
        print("[warn] 未检测到 OpenCV，打出的包将无法使用 confidence 找图。")
        print("       建议先安装：pip install opencv-python-headless")
        print("=" * 60)
        print()

    info = read_app_info()
    print(f"[info] 应用名     : {info['APP_DISPLAY_NAME']}")
    print(f"[info] 版本号     : {info['APP_VERSION']}")
    print(f"[info] 版本元组   : {version_tuple(info['APP_VERSION'])}")

    if not args.keep_build:
        clean_artifacts()
    clean_pycache(ROOT)

    # 版本文件
    version_file = None
    if not args.no_version:
        version_file = write_version_file(info)
        print(f"[info] 已生成版本信息: {version_file.name}")

    # 组装命令
    cmd = build_command(args, info, version_file)
    print("\n[cmd] 执行命令：")
    print("      " + " ".join(f'"{x}"' if " " in x else x for x in cmd))
    print()

    # 执行
    ret = subprocess.call(cmd, cwd=str(ROOT))
    if ret != 0:
        print("\n" + "=" * 60)
        print(f"打包失败，PyInstaller 退出码 {ret}")
        print("=" * 60)
        sys.exit(ret)

    # 拷贝额外文件到 dist 顶层
    if args.onefile:
        # onefile 模式没有顶层目录，跳过多文件拷贝
        print("[dist] onefile 模式跳过附带文件拷贝")
    else:
        out_dir = DIST_DIR / info["APP_NAME"]
        copy_extra_dist_files(out_dir)

    if not args.keep_build:
        clean_pycache(ROOT)

    # 收尾
    print("\n" + "=" * 60)
    print("[OK] 打包成功")
    print("=" * 60)

    if args.onefile:
        exe = DIST_DIR / f"{info['APP_NAME']}.exe"
    else:
        exe = DIST_DIR / info["APP_NAME"] / f"{info['APP_NAME']}.exe"

    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"产物：{exe}")
        print(f"主程序：{size_mb:.1f} MB")
        if not args.onefile:
            total = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
            print(f"整包：{total / (1024 * 1024):.1f} MB（含依赖）")
    else:
        print("[warn] 未找到预期的 exe，请检查 dist/ 目录。")


if __name__ == "__main__":
    main()