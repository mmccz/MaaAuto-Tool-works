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
                            CONFIG_DIR, LOG_DIR)
from i18n import init_i18n
from themes import ThemeManager
from ui.main_window import MainWindow


# --------------------------------------------------------------------------- #
# --upgrading：静默优雅退出
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
        from utils import kill_all_related_processes
        kill_all_related_processes()
        logger.info("子进程清理完成")
    except Exception as e:
        logger.error(f"清理子进程失败: {e}")

    logger.info("--upgrading 处理完成，退出")
    sys.exit(0)


# --------------------------------------------------------------------------- #
# 上次自动升级失败检查
# --------------------------------------------------------------------------- #
def _check_upgrade_failure():
    flag = os.path.join(CONFIG_DIR, "upgrade_failed.flag")
    logger = logging.getLogger("MaaAuto")

    # 静默检查，不显示在主界面
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

    # 发现标志才用 INFO，因为接下来要弹窗
    logger.info(f"发现升级失败标志: {data}")

    msg = (
        f"上次自动升级失败\n\n"
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
# 写入本次启动参数
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
        # 正常情况不刷主界面，仅 DEBUG 时可见
        logger.debug(f"已写入启动参数: {launch_args} -> {args_file}")
    except Exception as e:
        logger.error(f"写入 last_launch_args.json 失败: {e}")


# --------------------------------------------------------------------------- #
# 权限
#
# 自 v2.1.0 起，安装器在安装时会为 MaaAuto.exe 写入 RUNASADMIN 兼容标志：
#     HKCU\Software\Microsoft\Windows\CurrentVersion\AppCompatFlags\Layers
# 因此主程序每次启动都会弹 UAC，且 is_admin() 恒为 True。
#
# 主程序**不再自我提权**（原 elevate_if_needed() 已移除，2026-09-20）：
#   - 若 RUNASADMIN 标志 + ShellExecuteW("runas") 同时生效 → 二次 UAC 弹窗
#   - 由安装器统一负责提权，是更清晰的方案
#   - 原 --no-admin / --elevated 参数随之废弃，不再有实际作用
#
# 保留 is_admin() 供内部诊断 / 未来扩展使用。
# --------------------------------------------------------------------------- #
def is_admin() -> bool:
    """当前进程是否以管理员身份运行。

    注意：安装器为 MaaAuto.exe 设置了 RUNASADMIN 兼容标志后，
    本函数在正常安装环境下**恒返回 True**。
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# DPI
# --------------------------------------------------------------------------- #
def set_dpi_awareness():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 全局异常兜底
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
# 入口
# --------------------------------------------------------------------------- #
def main():
    # 0) --upgrading 优先级最高
    if "--upgrading" in sys.argv:
        _handle_upgrading_mode()

    # 1) config/.upgrading 兜底
    upgrading_flag = os.path.join(CONFIG_DIR, ".upgrading")
    if os.path.exists(upgrading_flag):
        logging.getLogger("MaaAuto").info(
            f"检测到 {upgrading_flag}，直接退出。"
        )
        sys.exit(0)

    # 2) DPI
    set_dpi_awareness()

    # 3) QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("MaaAuto")
    app.setOrganizationName("MaaAuto")
    app.setQuitOnLastWindowClosed(False)

    icon_path = resource_path("resources/icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 4) 日志
    logger, ui_handler = setup_logger()
    install_excepthook()

    # 启动摘要：只留一条 INFO，路径信息走 DEBUG（不刷主界面）
    logger.info("MaaAuto 启动")
    logger.debug(f"BASE_DIR: {os.path.dirname(CONFIG_DIR)}")
    logger.debug(f"CONFIG_DIR: {CONFIG_DIR}")
    logger.debug(f"LOG_DIR: {LOG_DIR}")
    logger.debug(f"argv: {sys.argv}")

    # 5) i18n + 配置
    i18n = init_i18n(resource_path("i18n"))
    config = load_config()

    lang = config.get("language", "zh_CN")
    if not i18n.load_language(lang):
        i18n.load_language("zh_CN")

    # 6) 主题
    theme_manager = ThemeManager(resource_path("themes"))
    theme_manager.apply_theme(config.get("theme", "system"), app)

    # 7) 主窗口
    window = MainWindow(i18n, theme_manager)

    # 8) 日志信号 → 首页
    ui_handler.log_signal.connect(window.home_page.append_log)

    # 9) 写启动参数（内部 debug 级别，不刷主界面）
    _write_launch_args(logger)

    # 10) 显示窗口
    if "--autostart" in sys.argv:
        window.hide()
    else:
        window.show()

    # 11) 延迟检查升级失败标志（内部 debug 级别，只有发现问题才 INFO）
    QTimer.singleShot(300, _check_upgrade_failure)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()