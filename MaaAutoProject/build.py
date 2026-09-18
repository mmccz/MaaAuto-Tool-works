"""
MaaAuto 一键打包脚本（PyInstaller）

用法：
    python build.py                 # 默认：onedir + 无控制台 + 写版本信息
    python build.py --debug         # 保留控制台窗口（方便看崩溃日志）
    python build.py --onefile       # 单文件模式（启动慢，不推荐，pyautogui 资源解压慢）
    python build.py --keep-build    # 不自动清理 build/ 和 dist/
    python build.py --no-version    # 不生成 version_info.txt（exe 无属性信息）
    python build.py --no-clean      # 跳过 pyinstaller --clean（增量更快）
    python build.py --no-pycache-clean  # 不清理项目里的 __pycache__ 目录
    python build.py --clean-pycache-only  # 只清理 __pycache__ 然后退出

前置：
    pip install pyinstaller

产物：
    dist/MaaAuto/MaaAuto.exe         （onedir 模式，推荐直接拷整个 dist/MaaAuto 文件夹）
    dist/MaaAuto.exe                 （onefile 模式）

注意：
    config/ 和 logs/ 不打进包里。程序首次运行时会在 exe 同级目录自动创建，
    所以要保证 exe 所在目录可写（避免装在 C:\\Program Files）。
"""

import os
import re
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_FILE = ROOT / "MaaAuto.spec"
VERSION_FILE = ROOT / "_version_info.txt"

# 需要打进包里的资源目录（源路径 → 包内相对路径）
DATA_DIRS = [
    ("resources", "resources"),
    ("themes",    "themes"),
    ("i18n",      "i18n"),
]

# pyautogui / Pillow / psutil 等常被 PyInstaller 漏掉的隐式导入
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
]

# 体积优化：明确排除这些包（如误伤请从列表移除）
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

# 清理 __pycache__ 时跳过这些目录名（不区分大小写）
PYCACHE_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    ".idea", ".vscode",
    "venv", ".venv", "env", ".env",
    "node_modules",
    "__pycache__",       # 会被专门处理，遍历时不再深入
    "dist", "build",     # 打包产物目录无需清理
}


# --------------------------------------------------------------------------- #
# 元信息读取
# --------------------------------------------------------------------------- #
def read_app_info():
    """从 app_info.py 里读取版本号 / 应用名，不 import（避免引入依赖）。"""
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
    """把 '2.0.0-Beta1' → (2, 0, 0, 0)，供 exe 属性使用。"""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", ver_str or "")
    if not m:
        return (0, 0, 0, 0)
    return tuple(int(x) for x in m.groups()) + (0,)


# --------------------------------------------------------------------------- #
# version_info.txt 生成（PyInstaller 的 exe 属性格式）
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
        u'080404B0',   # 0804 = 简体中文，04B0 = Unicode
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
    """
    递归删除项目内所有 __pycache__ 目录。
    - 跳过 PYCACHE_SKIP_DIRS 中列出的目录（.git / venv / node_modules 等）
    - 同时删除散落的 .pyc / .pyo 文件
    """
    if not root.exists():
        return 0

    removed_dirs = 0
    removed_files = 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        cur = Path(dirpath)

        # 就地过滤掉不想深入的目录
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in PYCACHE_SKIP_DIRS
        ]

        # 删除当前层的 __pycache__
        if "__pycache__" in dirnames:
            pyc_dir = cur / "__pycache__"
            try:
                shutil.rmtree(pyc_dir, ignore_errors=True)
                print(f"[pycache] 删除 {pyc_dir.relative_to(root)}")
                removed_dirs += 1
            except Exception as e:
                print(f"[pycache] 删除失败 {pyc_dir}: {e}")
            # 从遍历队列里移除，避免继续深入
            dirnames.remove("__pycache__")

        # 删除散落的 .pyc / .pyo（少数情况下会出现在非 __pycache__ 位置）
        for fn in filenames:
            if fn.endswith((".pyc", ".pyo")):
                fp = cur / fn
                try:
                    fp.unlink()
                    removed_files += 1
                except Exception:
                    pass

    if removed_dirs == 0 and removed_files == 0:
        print("[pycache] 未发现需要清理的 __pycache__ / .pyc")
    else:
        print(f"[pycache] 共删除 {removed_dirs} 个 __pycache__ 目录，"
              f"{removed_files} 个 .pyc/.pyo 文件")
    return removed_dirs + removed_files


# --------------------------------------------------------------------------- #
# 检查环境
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

    # 入口
    cmd.append(str(ROOT / "main.py"))

    # onedir / onefile
    cmd.append("--onefile" if args.onefile else "--onedir")

    # 控制台
    if args.debug:
        cmd.append("--console")
    else:
        cmd.append("--windowed")

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
# 主流程
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="MaaAuto 打包脚本（PyInstaller）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--debug", action="store_true",
                        help="保留控制台窗口（默认 windowed 无控制台）")
    parser.add_argument("--onefile", action="store_true",
                        help="单文件模式（启动慢，不推荐）")
    parser.add_argument("--keep-build", action="store_true",
                        help="不自动清理 build/ 和 dist/")
    parser.add_argument("--no-clean", action="store_true",
                        help="跳过 pyinstaller --clean（增量构建更快）")
    parser.add_argument("--no-version", action="store_true",
                        help="不生成 exe 版本信息")
    parser.add_argument("--no-pycache-clean", action="store_true",
                        help="不清理项目里的 __pycache__ 目录")
    parser.add_argument("--clean-pycache-only", action="store_true",
                        help="只清理 __pycache__ 后退出（不打包）")
    args = parser.parse_args()

    print("=" * 60)
    print("MaaAuto 打包脚本")
    print("=" * 60)
    print(f"项目根目录 : {ROOT}")
    print(f"Python     : {sys.version.split()[0]} ({sys.executable})")
    print(f"模式       : {'onefile' if args.onefile else 'onedir'}"
          f" / {'console' if args.debug else 'windowed'}")
    print("=" * 60)

    # -------- 只清 pycache --------
    if args.clean_pycache_only:
        print("[mode] 仅清理 __pycache__")
        clean_pycache(ROOT)
        print("完成。")
        return

    if not ensure_pyinstaller():
        sys.exit(1)

    info = read_app_info()
    print(f"[info] 应用名     : {info['APP_DISPLAY_NAME']}")
    print(f"[info] 版本号     : {info['APP_VERSION']}")
    print(f"[info] 版本元组   : {version_tuple(info['APP_VERSION'])}")

    # -------- 打包前清理 --------
    if not args.keep_build:
        clean_artifacts()
    if not args.no_pycache_clean:
        print("[stage] 打包前清理 __pycache__ ...")
        clean_pycache(ROOT)

    # 版本文件
    version_file = None
    if not args.no_version:
        version_file = write_version_file(info)
        print(f"[info] 已生成版本信息: {version_file.name}")

    # 组装命令
    cmd = build_command(args, info, version_file)
    print("\n[cmd] 执行命令：")
    print("      " + " ".join(
        f'"{x}"' if " " in x else x for x in cmd
    ))
    print()

    # 执行
    ret = subprocess.call(cmd, cwd=str(ROOT))
    if ret != 0:
        print("\n" + "=" * 60)
        print(f"打包失败，PyInstaller 退出码 {ret}")
        print("=" * 60)
        sys.exit(ret)

    # -------- 打包后清理（build 过程会在项目内散落 .pyc） --------
    if not args.no_pycache_clean:
        print("\n[stage] 打包后清理 __pycache__ ...")
        clean_pycache(ROOT)

    # 收尾
    print("\n" + "=" * 60)
    print("打包成功 ✅")
    print("=" * 60)

    if args.onefile:
        exe = DIST_DIR / f"{info['APP_NAME']}.exe"
    else:
        exe = DIST_DIR / info["APP_NAME"] / f"{info['APP_NAME']}.exe"

    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"产物：{exe}")
        print(f"大小：{size_mb:.1f} MB")
        if not args.onefile:
            total = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
            print(f"整包：{total / (1024 * 1024):.1f} MB（含依赖）")
            print()
            print("提示：分发时请拷贝整个文件夹：")
            print(f"      {exe.parent}")
    else:
        print("[warn] 未找到预期的 exe，请检查 dist/ 目录。")

    print()
    print("运行前请确认：")
    print("  1. exe 所在目录可写（config/ 和 logs/ 会在同级创建）")
    print("  2. 若程序闪退，用 `python build.py --debug` 重新打包查看报错")
    print("=" * 60)


if __name__ == "__main__":
    main()