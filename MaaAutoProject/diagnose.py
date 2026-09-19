#!/usr/bin/env python
"""
MaaAuto 诊断脚本：打印运行时关键路径 + 状态

用法：
    cd MaaAuto-Tool-works\\MaaAutoProject
    python diagnose.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def line():
    print("-" * 64)


def read_text_safe(path):
    """用 utf-8-sig 读文件（兼容 BOM）。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except Exception as e:
        return f"[读取失败: {e}]"


def main():
    print("=" * 64)
    print("MaaAuto 诊断")
    print("=" * 64)

    print("\n[1] 环境")
    print(f"  Python         : {sys.version.split()[0]}")
    print(f"  sys.executable : {sys.executable}")
    print(f"  CWD            : {os.getcwd()}")
    print(f"  script path    : {os.path.abspath(__file__)}")
    print(f"  frozen         : {getattr(sys, 'frozen', False)}")

    print("\n[2] config_manager 路径")
    try:
        import config_manager as cm
        print(f"  BASE_DIR     : {cm.BASE_DIR}")
        print(f"  CONFIG_DIR   : {cm.CONFIG_DIR}")
        print(f"  LOG_DIR      : {cm.LOG_DIR}")
        print(f"  CONFIG_FILE  : {cm.CONFIG_FILE}")
        print(f"  config 存在  : {os.path.isdir(cm.CONFIG_DIR)}")
        print(f"  logs 存在    : {os.path.isdir(cm.LOG_DIR)}")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print("\n[3] 关键标志文件")
    try:
        from config_manager import CONFIG_DIR, LOG_DIR
        for name in (".upgrading", "upgrade_failed.flag", "last_launch_args.json"):
            p = os.path.join(CONFIG_DIR, name)
            exists = os.path.exists(p)
            status = "存在" if exists else "不存在"
            print(f"  {name:25s} : {status}")
            print(f"      路径: {p}")
            if exists and name in ("upgrade_failed.flag", "last_launch_args.json"):
                content = read_text_safe(p)
                print(f"      内容: {content[:200]}")
        line()
        for name in ("upgrading.log", "task.log"):
            p = os.path.join(LOG_DIR, name)
            print(f"  {name:25s} : {'存在' if os.path.exists(p) else '不存在'}")
            print(f"      路径: {p}")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print("\n[4] Server 酱状态（导入 notifier 时的实际值）")
    try:
        import notifier
        print(f"  HAS_SERVERCHAN : {notifier.HAS_SERVERCHAN}")
        if notifier.HAS_SERVERCHAN:
            print(f"  sc_send        : {notifier.sc_send}")
        else:
            print(f"  sc_send        : None (未加载)")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print("\n[5] serverchan_sdk 文件")
    sdk_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "serverchan_sdk.py")
    print(f"  路径: {sdk_path}")
    print(f"  存在: {os.path.exists(sdk_path)}")
    bak = sdk_path + ".bak"
    if os.path.exists(bak):
        print(f"  ⚠ 发现备份文件: {bak}")
        print(f"     （说明之前改过名，注意恢复）")

    print("\n[6] config.json 关键字段")
    try:
        from config_manager import load_config
        cfg = load_config()
        for k in ("auto_check_update", "auto_download_update",
                  "auto_start", "minimize_to_tray", "kill_on_exit"):
            v = cfg.get(k)
            print(f"  {k:25s} : {v}")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print("\n[7] 当前 Python 进程（可能有僵尸进程）")
    try:
        import psutil
        me = os.getpid()
        count = 0
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (p.info['name'] or '').lower()
                if 'python' in name:
                    cmdline = p.info['cmdline'] or []
                    cmd_short = ' '.join(cmdline)[:80] if cmdline else ''
                    mark = " ← 本进程" if p.info['pid'] == me else ""
                    print(f"  PID {p.info['pid']:6d}  {name:15s}  {cmd_short}{mark}")
                    count += 1
            except Exception:
                pass
        if count <= 1:
            print("  （无其他 Python 进程）")
        print(f"\n  提示：如果有多个 python.exe 且 cmdline 含 main.py，")
        print(f"        可能有僵尸进程，用任务管理器结束它们再测。")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print("\n" + "=" * 64)
    print("诊断完成")
    print("=" * 64)


if __name__ == "__main__":
    main()