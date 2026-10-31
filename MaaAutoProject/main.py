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
        from process_utils import kill_all_related_processes
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
#     HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers
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
def set_dpi_awareness() -> bool:
    """声明 per-monitor-v2 DPI 感知，成功返回 True。

    ★ 这三个 API 失败时返回 0 / 错误码，**不会抛异常**。旧实现只看「有没有
      抛异常」，于是设置失败也当作成功继续跑——此时进程仍是不感知状态：
      ImageGrab 截到的是物理像素、GetWindowRect 返回虚拟像素，找图的
      点击坐标会整体偏移（125% 缩放下偏 20%）。
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
# 界面缩放
#
# Qt 会按系统 DPI 自动缩放布局，但「1080×720 的窗口 + 默认字号」在 4K/高缩放
# 或 1366×768 小屏上都显得不合适。这里只放大基础字号（QSS 里没有 px 字号，
# 所以整体会等比放大），配合 MainWindow 按可用区域收缩窗口。
# --------------------------------------------------------------------------- #
def apply_ui_scale(app, config):
    """把 ui_scale 应用到 app 字体，返回实际生效的倍数。

    注意：真正让界面「看得见变大」的是 ``ThemeManager.apply_theme`` 里对 QSS
    ``font-size`` 的重写（QSS 会覆盖 app 字体）。这里保留 app 字体缩放是为了
    覆盖将来可能新增的、未被 QSS 命中的控件；设置页切换比例时走
    ``ui.main_window.apply_ui_scale_live`` 的即时路径，不必重启。
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
    #
    #    正常情况：升级器写好标志 → 主程序退出。
    #    异常情况：升级器崩溃 / 被任务管理器结束 / 停不掉主程序就返回，
    #    标志会残留，用户此后双击主程序“毫无反应”。由 upgrade_guard 判定
    #    “超时且无升级器进程”后删除标志并继续启动；判定规则见该模块。
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

    # 5.1) 「设置→应用」版本号自愈：自动升级不跑 Inno，卸载项版本会一直停在
    #      安装时的值（D-2）。只有登记目录正好指向自己时才改，失败静默。
    try:
        from app_info import APP_VERSION
        if sync_display_version(APP_VERSION, os.path.dirname(CONFIG_DIR)):
            logger.info("已把「设置→应用」里的版本号更新到当前版本")
    except Exception as e:
        logger.debug(f"同步应用列表版本号失败: {e}")

    # 清理过期任务日志（按目录名里的日期判断，默认保留 90 天；0=不清理）
    try:
        removed = cleanup_old_logs(config.get("log_retention_days"),
                                   logger=logger)
        if removed:
            logger.info(f"已清理 {removed} 个超过保留期的日志目录")
    except Exception as e:                       # 清理失败绝不能影响启动
        logger.debug(f"清理旧日志失败: {e}")

    ui_scale = apply_ui_scale(app, config)
    logger.info(f"界面缩放: {int(round(ui_scale * 100))}%"
                f"（设置页可即时调整，无需重启）")

    lang = config.get("language", "zh_CN")
    if not i18n.load_language(lang):
        i18n.load_language("zh_CN")

    # 6) 主题（界面缩放一并传入：QSS 里的 font-size 会覆盖 app 字体）
    theme_manager = ThemeManager(resource_path("themes"))
    theme_manager.apply_theme(config.get("theme", "system"), app,
                              ui_scale=config.get("ui_scale", 1.0))

    # 7) 主窗口
    window = MainWindow(i18n, theme_manager)

    # 8) 日志信号 → 首页
    #
    # ★ 这是界面日志的**唯一**通路：Worker 只挂自己的文件 handler，
    #   不再接管全局 handler。删掉这行会让任务日志在界面上消失。
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