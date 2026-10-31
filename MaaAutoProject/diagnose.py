#!/usr/bin/env python
"""MaaAuto diagnostics: print the key runtime paths plus their state.

Usage:
    cd MaaAuto-Tool-works\\MaaAutoProject
    python diagnose.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def line():
    print("-" * 64)


def read_text_safe(path):
    """Read a file with utf-8-sig (tolerates a BOM)."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except Exception as e:
        return f"[读取失败: {e}]"


def main():
    # Declare DPI awareness first, otherwise the screen size / DIP values below come back
    # virtualised by the system (1536x864 instead of 1920x1080 at 125%), which misleads finding bugs.
    _set_dpi_awareness()
    print("=" * 64)
    print("MaaAuto 诊断")
    print("=" * 64)

    print("\n[1] 环境")
    print(f"  Python         : {sys.version.split()[0]}")
    print(f"  sys.executable : {sys.executable}")
    print(f"  CWD            : {os.getcwd()}")
    print(f"  script path    : {os.path.abspath(__file__)}")
    print(f"  frozen         : {getattr(sys, 'frozen', False)}")
    try:
        import system_info
        print(f"  OS             : {system_info.describe_system()}")
    except Exception as e:
        print(f"  OS             : [ERROR] {e}")

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

    print("\n[8] 显示 / 找图环境")
    try:
        import ctypes
        from ctypes import wintypes
        w, h = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
        print(f"  屏幕(物理像素) : {w}x{h}")
        print(f"  进程 DPI 感知  : {'是' if _is_dpi_aware() else '否（找图坐标会错位）'}")
        import vision
        print(f"  dpi_scale     : {vision.dpi_scale():.2f}")
        print(f"  opencv        : {'可用' if vision.HAS_CV2 else '缺失！找图不可用'}")
        import automation
        cfg = {}
        try:
            from config_manager import load_config
            cfg = load_config()
        except Exception:
            pass
        for name in ("maa_start.png", "maaend_start.png"):
            paths = automation.template_paths(name, cfg)
            origin = "用户模板" if paths and paths[0].endswith(
                name) and "resources" not in paths[0] else "内置模板"
            print(f"  {name:16s} : {'找到' if paths else '缺失'} ({origin}) {paths[:1]}")
        print(f"  搜索范围       : {cfg.get('search_scope', 'window')}")
        print(f"  相似度阈值     : {cfg.get('match_threshold', 0.8)}")
        print(f"  缩放搜索区间   : {cfg.get('match_scale_min', 0.6)}~{cfg.get('match_scale_max', 2.0)}")
        print(f"  点击方式       : {cfg.get('click_mode', 'sendinput')}")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print("\n" + "=" * 64)
    print("诊断完成")
    print("=" * 64)


def _set_dpi_awareness():
    """Same three-level fallback as main.py, so the diagnostics report physical pixels.

    * These three APIs **return an error code / 0 instead of raising**, so the return
      value must be checked; returning merely because nothing raised leaves the process
      DPI-unaware (screenshots in physical pixels, GetWindowRect in virtual pixels, and
      every finding coordinate shifted).
    """
    import ctypes
    user32 = ctypes.windll.user32
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except Exception:
        pass
    try:
        if user32.SetProcessDPIAware():
            return True
    except Exception:
        pass
    return False


def _is_dpi_aware():
    """Whether this process declared DPI awareness (without it find coordinates shift).

    GetAwarenessFromDpiAwarenessContext: 0 = unaware, 1 = system, 2 = per-monitor.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        ctx = user32.GetThreadDpiAwarenessContext()
        awareness = user32.GetAwarenessFromDpiAwarenessContext(ctx)
        return int(awareness) > 0
    except Exception:
        return False


if __name__ == "__main__":
    main()