#!/usr/bin/env python
"""
把 MaaAutoProject/dist/MaaAuto/ 部署到目标安装目录。

保留用户数据：
  - config/
  - logs/
  - .maaauto.json
  - upgrade.exe
  - uninstall.exe

会先删除这些（再拷新的）：
  - _internal/
  - resources/  themes/  i18n/
  - MaaAuto.exe

用法：
    cd MaaAuto-Tool-works\\MaaAutoProject
    python deploy_dev.py                    # 默认目标 D:\\MaaAuto
    python deploy_dev.py E:\\MaaAuto-Test    # 指定目录
"""

import os
import sys
import shutil
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST_APP = ROOT / "dist" / "MaaAuto"

# 安装目录里要保留的（不覆盖、不删除）
KEEP_IN_INSTALL = {
    "config",
    "logs",
    ".maaauto.json",
    "upgrade.exe",
    "uninstall.exe",
    "deploy_dev.py",       # 本脚本自己
}

# 安装目录里要删掉再拷新的（顶层）
REPLACE_TOP = [
    "MaaAuto.exe",
    "_internal",
    "resources",
    "themes",
    "i18n",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "_version_info.txt",
]


def human(n):
    if n >= 1024 * 1024:
        return f"{n / (1024*1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?",
                        default=r"D:\MaaAuto",
                        help="目标安装目录（默认 D:\\MaaAuto）")
    args = parser.parse_args()

    target = Path(args.target).resolve()

    print("=" * 60)
    print("MaaAuto 开发部署")
    print("=" * 60)
    print(f"源目录 : {DIST_APP}")
    print(f"目标目录: {target}")
    print("=" * 60)

    if not DIST_APP.exists():
        print(f"[ERROR] 打包产物不存在：{DIST_APP}")
        print(f"        请先运行：python build.py")
        sys.exit(1)

    if not target.exists():
        print(f"[ERROR] 目标目录不存在：{target}")
        sys.exit(1)

    # ---- 检查是否有主程序在跑 ----
    try:
        import psutil
        running = False
        for p in psutil.process_iter(['name', 'exe']):
            try:
                exe = (p.info.get('exe') or "")
                if exe.lower().endswith("maaauto.exe") and \
                   str(target).lower() in exe.lower():
                    print(f"[WARN] 检测到主程序正在运行：PID {p.info['pid']} {exe}")
                    running = True
            except Exception:
                pass
        if running:
            print("[ERROR] 请先关闭主程序再部署")
            sys.exit(1)
    except ImportError:
        pass

    # ---- 1. 删除旧内容（保留白名单）----
    print()
    print("[1] 清理旧内容（保留 config/logs/.maaauto.json/upgrade.exe/uninstall.exe）")
    for name in REPLACE_TOP:
        p = target / name
        if not p.exists():
            continue
        if name in KEEP_IN_INSTALL:
            print(f"  跳过（白名单）: {name}")
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            print(f"  删除: {name}")
        except Exception as e:
            print(f"  [WARN] 删除 {name} 失败: {e}")

    # ---- 2. 拷贝新内容 ----
    print()
    print("[2] 拷贝新内容")
    copied = 0
    for item in DIST_APP.iterdir():
        if item.name in KEEP_IN_INSTALL:
            print(f"  跳过（白名单）: {item.name}")
            continue
        dst = target / item.name
        try:
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)
                n = sum(1 for _ in dst.rglob("*") if _.is_file())
                print(f"  + {item.name}/  ({n} 个文件)")
            else:
                if dst.exists():
                    dst.unlink()
                shutil.copy2(item, dst)
                print(f"  + {item.name}  ({human(item.stat().st_size)})")
            copied += 1
        except Exception as e:
            print(f"  [ERROR] 拷贝 {item.name} 失败: {e}")

    # ---- 3. 报告 ----
    print()
    print("=" * 60)
    print(f"[OK] 部署完成：{copied} 项")
    print("=" * 60)
    print()
    print(f"  启动：{target / 'MaaAuto.exe'}")
    print(f"  配置：{target / 'config' / 'config.json'}")
    print(f"  日志：{target / 'logs'}")
    print()
    print("  保留项（未动）：")
    for name in sorted(KEEP_IN_INSTALL):
        p = target / name
        mark = "✓" if p.exists() else "✗"
        print(f"    {mark} {name}")
    print()


if __name__ == "__main__":
    main()