import os
import sys
import ctypes
import logging
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from utils import resource_path
from config_manager import load_config, setup_logger
from i18n import init_i18n
from themes import ThemeManager
from ui.main_window import MainWindow


# --------------------------------------------------------------------------- #
# 权限
# --------------------------------------------------------------------------- #
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_if_needed() -> bool:
    """
    若非管理员，尝试以管理员身份重启自身。
    返回 True 表示已经发出提权请求（原进程应当退出）。
    """
    if is_admin():
        return False
    if "--no-admin" in sys.argv:
        return False
    if "--elevated" in sys.argv:
        # 已经提过一次仍未获得管理员权限，不再重试
        return False

    # 拼参数：保留原参数，附加 --elevated 标记
    args = [a for a in sys.argv[1:] if a != "--elevated"]
    args.append("--elevated")
    params = " ".join(f'"{a}"' if " " in a else a for a in args)

    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        # ShellExecuteW 返回值 > 32 表示成功发起请求
        if ret > 32:
            return True
    except Exception:
        pass
    # 提权失败（用户拒绝 UAC / 商店版 Python 限制等）：以普通权限继续运行
    return False


# --------------------------------------------------------------------------- #
# DPI
# --------------------------------------------------------------------------- #
def set_dpi_awareness():
    """必须在 QApplication 创建之前调用。"""
    try:
        # Windows 10 1703+ 推荐：Per-Monitor DPI Aware V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
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
    # 1) 提权（失败也不影响启动）
    #Is not use

    # 2) DPI（必须在 QApplication 之前）
    set_dpi_awareness()

    # 3) QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("MaaAuto")
    app.setOrganizationName("MaaAuto")
    app.setQuitOnLastWindowClosed(False)      # 托盘常驻

    icon_path = resource_path("resources/icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 4) 日志（尽早建立，便于后续异常落盘）
    logger, ui_handler = setup_logger()
    install_excepthook()

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

    # 8) 把日志信号接到首页日志框
    ui_handler.log_signal.connect(window.home_page.append_log)
    logger.info("程序启动成功")

    # 9) 启动显示策略
    if "--autostart" in sys.argv:
        window.hide()          # 开机自启：静默驻留托盘
    else:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()