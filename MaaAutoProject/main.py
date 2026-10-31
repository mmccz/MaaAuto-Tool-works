import os
import sys
import json
import ctypes
import logging
import datetime
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer

from utils import resource_path
from config_manager import (load_config, save_config, setup_logger,
                            cleanup_old_logs, CONFIG_DIR, LOG_DIR)
from upgrade_guard import resolve_upgrade_flag
from apps_registry import sync_display_version
from i18n import init_i18n
from themes import ThemeManager
from ui.main_window import MainWindow


# --------------------------------------------------------------------------- #
# --upgrading: quiet, graceful exit
# --------------------------------------------------------------------------- #
def _handle_upgrading_mode():
    logger = logging.getLogger("MaaAuto")
    logger.setLevel(logging.INFO)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(LOG_DIR, "upgrading.log"), encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
    except Exception:
        pass

    logger.info("收到 --upgrading，开始优雅退出")
    logger.info(f"CONFIG_DIR: {CONFIG_DIR}")
    logger.info(f"LOG_DIR: {LOG_DIR}")

    try:
        cfg = load_config()
        save_config(cfg)
        logger.info("配置已落盘")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

    try:
        from process_utils import kill_all_related_processes
        kill_all_related_processes()
        logger.info("子进程清理完成")
    except Exception as e:
        logger.error(f"清理子进程失败: {e}")

    logger.info("--upgrading 处理完成，退出")
    sys.exit(0)


# --------------------------------------------------------------------------- #
# check for a failed previous auto-upgrade
# --------------------------------------------------------------------------- #
def _check_upgrade_failure():
    flag = os.path.join(CONFIG_DIR, "upgrade_failed.flag")
    logger = logging.getLogger("MaaAuto")

    # silent check, nothing shown on the main window
    logger.debug(f"检查升级失败标志: {flag}")

    if not os.path.exists(flag):
        logger.debug("未发现升级失败标志，跳过")
        return

    try:
        with open(flag, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"读取升级失败标志失败: {e}")
        try:
            os.remove(flag)
        except Exception:
            pass
        return

    # INFO only once the flag exists, since a dialog follows
    logger.info(f"发现升级失败标志: {data}")

    msg = (
        f"上次升级未能完成\n\n"
        f"从 {data.get('from_version', '?')} → {data.get('to_version', '?')}\n"
        f"原因：{data.get('reason', '未知')}\n"
        f"日志：{data.get('log_path', '未知')}\n\n"
        f"请到 GitHub Releases 手动下载完整安装包。"
    )
    try:
        QMessageBox.warning(None, "MaaAuto 升级失败", msg)
    except Exception as e:
        logger.error(f"弹窗失败: {e}")
    try:
        os.remove(flag)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# write this run's launch arguments
# --------------------------------------------------------------------------- #
def _write_launch_args(logger):
    try:
        launch_args = [a for a in sys.argv[1:] if a != "--upgrading"]
        args_file = os.path.join(CONFIG_DIR, "last_launch_args.json")
        with open(args_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "args": launch_args,
                    "written_at": datetime.datetime.now().isoformat(timespec="seconds"),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        # normal runs stay off the main window; visible in DEBUG only
        logger.debug(f"已写入启动参数: {launch_args} -> {args_file}")
    except Exception as e:
        logger.error(f"写入 last_launch_args.json 失败: {e}")


# --------------------------------------------------------------------------- #
# Privileges
#
# Since v2.1.0 the installer writes a RUNASADMIN compatibility flag for MaaAuto.exe:
#     HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers
# so the app raises UAC on every start and is_admin() is always True.
#
# The app **no longer elevates itself** (elevate_if_needed() was removed 2026-09-20):
#   - RUNASADMIN plus ShellExecuteW("runas") would mean a second UAC prompt
#   - letting the installer own elevation is the cleaner design
#   - --no-admin / --elevated are obsolete and no longer do anything
#
# is_admin() stays for internal diagnostics and future use.
# --------------------------------------------------------------------------- #
def is_admin() -> bool:
    """Whether this process runs as administrator.

    Note: once the installer sets the RUNASADMIN compatibility flag on MaaAuto.exe,
    this **always returns True** in a normal installed setup.
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# DPI
# --------------------------------------------------------------------------- #
def set_dpi_awareness() -> bool:
    """Declare per-monitor-v2 DPI awareness; True on success.

    * These three APIs return 0 / an error code on failure, **they never raise**. The old
      implementation only checked for exceptions, so a failed call looked like success and
      the app kept running DPI-unaware: ImageGrab captures physical pixels while
      GetWindowRect reports virtual ones, shifting every coordinate (20% at 125%).
    """
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        # 0 = S_OK
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except Exception:
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return True
    except Exception:
        pass
    return False


# --------------------------------------------------------------------------- #
# UI scaling
#
# Qt scales layouts by system DPI, but a 1080x720 window with the default font size
# suits neither 4K / high scaling nor a 1366x768 screen. Only the base font grows
# (the QSS has no px font sizes, so everything scales), while MainWindow shrinks to fit.
# --------------------------------------------------------------------------- #
def apply_ui_scale(app, config):
    """Apply ui_scale to the app font; returns the factor actually used.

    What really makes the UI look bigger is the QSS ``font-size`` rewrite inside
    ``ThemeManager.apply_theme`` (QSS overrides the app font). Scaling the app font here
    still covers widgets added later that the QSS does not reach; the settings page takes
    the live path in ``ui.main_window.apply_ui_scale_live`` and needs no restart.
    """
    try:
        scale = float(config.get("ui_scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    scale = max(0.75, min(2.0, scale))
    if abs(scale - 1.0) < 1e-3:
        return scale
    try:
        font = app.font()
        base = font.pointSizeF()
        if base <= 0:
            base = 9.0
        font.setPointSizeF(base * scale)
        app.setFont(font)
    except Exception as e:
        logging.getLogger("MaaAuto").warning(f"应用界面缩放失败: {e}")
    return scale


# --------------------------------------------------------------------------- #
# Global exception fallback
# --------------------------------------------------------------------------- #
def install_excepthook():
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            logging.getLogger("MaaAuto").error("未捕获异常:\n" + msg)
        except Exception:
            pass
        try:
            QMessageBox.critical(None, "MaaAuto 出错", msg[-1500:])
        except Exception:
            pass
    sys.excepthook = _hook


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    # 0) --upgrading has top priority
    if "--upgrading" in sys.argv:
        _handle_upgrading_mode()

    # 1) config/.upgrading fallback
    #
    #    Normal: the upgrader writes the flag, then the app exits.
    #    Abnormal: the upgrader crashes / is killed in Task Manager / returns without
    #    stopping the app; the flag stays behind and every double-click "does nothing".
    #    upgrade_guard clears it once it has timed out with no upgrader; rules there.
    upgrading_flag = os.path.join(CONFIG_DIR, ".upgrading")
    if not resolve_upgrade_flag(
            upgrading_flag,
            log_path=os.path.join(LOG_DIR, "upgrading.log")):
        sys.exit(0)

    # 2) DPI
    if not set_dpi_awareness():
        logging.getLogger("MaaAuto").warning(
            "未能声明 DPI 感知，找图坐标可能偏移；如遇到点偏请反馈")

    # 3) QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("MaaAuto")
    app.setOrganizationName("MaaAuto")
    app.setQuitOnLastWindowClosed(False)

    icon_path = resource_path("resources/icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 4) Logging
    logger, ui_handler = setup_logger()
    install_excepthook()

    # Startup summary: one INFO line only; paths go to DEBUG (keeps the main window clean)
    logger.info("MaaAuto 启动")
    logger.debug(f"BASE_DIR: {os.path.dirname(CONFIG_DIR)}")
    logger.debug(f"CONFIG_DIR: {CONFIG_DIR}")
    logger.debug(f"LOG_DIR: {LOG_DIR}")
    logger.debug(f"argv: {sys.argv}")

    # 5) i18n + config
    i18n = init_i18n(resource_path("i18n"))
    config = load_config()

    # 5.1) Self-heal the Settings > Apps version: auto-upgrade skips Inno, so the uninstall
    #      entry keeps the install-time version (D-2); only touched if it points at us.
    try:
        from app_info import APP_VERSION
        if sync_display_version(APP_VERSION, os.path.dirname(CONFIG_DIR)):
            logger.info("已把「设置→应用」里的版本号更新到当前版本")
    except Exception as e:
        logger.debug(f"同步应用列表版本号失败: {e}")

    # Prune expired task logs (dates from directory names; keep 90 days by default, 0 = off)
    try:
        removed = cleanup_old_logs(config.get("log_retention_days"),
                                   logger=logger)
        if removed:
            logger.info(f"已清理 {removed} 个超过保留期的日志目录")
    except Exception as e:                       # a cleanup failure must never block startup
        logger.debug(f"清理旧日志失败: {e}")

    ui_scale = apply_ui_scale(app, config)
    logger.info(f"界面缩放: {int(round(ui_scale * 100))}%"
                f"（设置页可即时调整，无需重启）")

    lang = config.get("language", "zh_CN")
    if not i18n.load_language(lang):
        i18n.load_language("zh_CN")

    # 6) Theme (UI scale is passed too: QSS font-size overrides the app font)
    theme_manager = ThemeManager(resource_path("themes"))
    theme_manager.apply_theme(config.get("theme", "system"), app,
                              ui_scale=config.get("ui_scale", 1.0))

    # 7) Main window
    window = MainWindow(i18n, theme_manager)

    # 8) Log signal -> home page
    #
    # * This is the **only** path for UI logs: a worker attaches its own file handler
    #   and leaves the global one alone. Drop this line and task logs leave the UI.
    ui_handler.log_signal.connect(window.home_page.append_log)

    # 9) Write launch arguments (debug level inside, keeps the main window clean)
    _write_launch_args(logger)

    # 10) Show the window
    if "--autostart" in sys.argv:
        window.hide()
    else:
        window.show()

    # 11) Delayed check of the upgrade-failure flag (debug inside; INFO only on a problem)
    QTimer.singleShot(300, _check_upgrade_failure)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()