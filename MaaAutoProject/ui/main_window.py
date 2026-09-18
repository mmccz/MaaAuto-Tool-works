import os
import sys
import logging
import datetime
import winreg
import atexit
import base64

from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QSystemTrayIcon, QMenu, QApplication
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QTime, QDate
from PySide6.QtGui import QIcon, QAction

from config_manager import load_config, save_config, LOG_DIR
from automation import execute_workflow
from utils import resource_path, kill_all_related_processes
from ui.background import BackgroundWidget
from ui.sidebar import Sidebar
from ui.sliding_stack import SlidingStack
from ui.pages.home_page import HomePage
from ui.pages.settings_page import SettingsPage
from ui.pages.about_page import AboutPage
from ui.animations import theme_transition


class Worker(QThread):
    log_signal = Signal(str)
    task_finished = Signal(str)          # ← 新增

    def __init__(self, config, run_log_dir):
        super().__init__()
        self.config = config
        self.run_log_dir = run_log_dir

    def run(self):
        logger = logging.getLogger("MaaAuto")
        for h in logger.handlers[:]:
            logger.removeHandler(h)

        file_handler = logging.FileHandler(
            os.path.join(self.run_log_dir, "task.log"), encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        logger.addHandler(file_handler)

        class SignalHandler(logging.Handler):
            def __init__(self, signal):
                super().__init__()
                self.signal = signal

            def emit(self, record):
                self.signal.emit(self.format(record))

        sh = SignalHandler(self.log_signal)
        sh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(sh)

        try:
            status = execute_workflow(self.config, logger) or "成功"
            self.task_finished.emit(status)
        except Exception as e:
            logger.error(f"执行错误: {e}")
            self.task_finished.emit("报错")
        finally:
            logger.removeHandler(sh)
            logger.removeHandler(file_handler)
            file_handler.close()

            from config_manager import LogHandler
            base = LogHandler()
            base.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            logger.addHandler(base)


class MainWindow(QMainWindow):
    def __init__(self, i18n, theme_manager):
        super().__init__()
        self.i18n = i18n
        self.theme_manager = theme_manager
        self.config = load_config()
        self.worker = None
        self.is_quitting = False

        self.logger = logging.getLogger("MaaAuto")
        self.logger.setLevel(logging.INFO)

        self.setWindowTitle(self.i18n.t("app.title"))
        self.resize(1080, 720)
        # ---- 恢复窗口几何 ----
        self._restore_geometry()
        self.setWindowIcon(QIcon(resource_path("resources/icon.ico")))

        # 中央容器
        self.bg_root = BackgroundWidget()
        self.setCentralWidget(self.bg_root)

        root_layout = QHBoxLayout(self.bg_root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar(self.i18n)
        self.sidebar.page_changed.connect(self._on_page_changed)
        root_layout.addWidget(self.sidebar)

        # ---- 用 SlidingStack 替代 QStackedWidget ----
        self.stack = SlidingStack()
        self.stack.set_animation_enabled(self.config.get("show_animation", True))
        root_layout.addWidget(self.stack, 1)

        # 页面
        self.home_page = HomePage(self.i18n)
        self.settings_page = SettingsPage(self.config, self.i18n, self.theme_manager)
        self.about_page = AboutPage(self.i18n)
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.about_page)
        self.stack.setCurrentIndex(0)

        # 信号
        self.home_page.run_clicked.connect(self.manual_run)
        self.home_page.stop_clicked.connect(self.stop_task)
        self.home_page.clear_log_clicked.connect(self.home_page.clear_log)
        self.settings_page.config_changed.connect(self._on_config_changed)
        self.settings_page.theme_changed.connect(self._on_theme_changed)
        self.settings_page.language_changed.connect(self._on_language_changed)
        self.i18n.language_changed.connect(self._retranslate_all)

        self._apply_background()
        self._setup_tray()

        # 定时器
        self.schedule_timer = QTimer(self)
        self.schedule_timer.timeout.connect(self._check_schedule)
        self.schedule_timer.start(10_000)

        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_next_run)
        self.countdown_timer.start(30_000)

        self._refresh_home_stats()
        self._update_next_run()

        atexit.register(self.cleanup_on_exit)

    # ==================================================================
    # 背景
    # ==================================================================
    def _apply_background(self):
        self.bg_root.set_background(
            self.config.get("background_image", ""),
            self.config.get("background_opacity", 0.3),
            self.config.get("background_blur", 0),
            self.config.get("background_mode", "cover"),
        )

    # ==================================================================
    # 托盘
    # ==================================================================
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(resource_path("resources/icon.ico")))
        self.tray.setToolTip("MaaAuto")

        menu = QMenu()
        self.act_show = QAction(self.i18n.t("tray.show"), self, triggered=self._tray_show)
        self.act_settings = QAction(self.i18n.t("tray.settings"), self, triggered=self._tray_show_settings)
        self.act_stop = QAction(self.i18n.t("tray.stop"), self, triggered=self._tray_stop)
        self.act_quit = QAction(self.i18n.t("tray.quit"), self, triggered=self.quit_app)

        menu.addAction(self.act_show)
        menu.addAction(self.act_settings)
        menu.addSeparator()
        menu.addAction(self.act_stop)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_normal() if r == QSystemTrayIcon.DoubleClick else None
        )
        self.tray.show()

    def _tray_show(self):
        self.show_normal()
        self._on_page_changed(0)

    def _tray_show_settings(self):
        self.show_normal()
        self._on_page_changed(1)

    def _tray_stop(self):
        if self._is_running():
            self.stop_task()
            self.tray.showMessage("MaaAuto", self.i18n.t("tray.stopped"),
                                  QSystemTrayIcon.Information, 2000)
        else:
            self.tray.showMessage("MaaAuto", self.i18n.t("tray.no_task"),
                                  QSystemTrayIcon.Information, 2000)

    # ==================================================================
    # 页面切换
    # ==================================================================
    def _on_page_changed(self, index):
        if index == self.stack.currentIndex():
            return
        self.sidebar.set_current(index)
        self.stack.setCurrentIndex(index)

    # ==================================================================
    # 配置 / 主题 / 语言
    # ==================================================================
    def _on_config_changed(self, cfg):
        self.config.update(cfg)
        save_config(self.config)
        self._apply_background()
        self._refresh_home_stats()
        self._update_next_run()
        # 应用动画开关
        self.stack.set_animation_enabled(self.config.get("show_animation", True))

    def _on_theme_changed(self, theme):
        self.config["theme"] = theme
        save_config(self.config)

        def do_switch():
            self.theme_manager.apply_theme(theme, QApplication.instance())

        theme_transition(self, do_switch, duration=260)

    def _on_language_changed(self, code):
        self.config["language"] = code
        save_config(self.config)
        self.i18n.load_language(code)

    def _retranslate_all(self, *_):
        self.setWindowTitle(self.i18n.t("app.title"))
        self.sidebar.retranslate()
        self.home_page.retranslate()
        self.settings_page.retranslate()
        self.about_page.retranslate()

        self.act_show.setText(self.i18n.t("tray.show"))
        self.act_settings.setText(self.i18n.t("tray.settings"))
        self.act_stop.setText(self.i18n.t("tray.stop"))
        self.act_quit.setText(self.i18n.t("tray.quit"))

        self._update_next_run()
        self.home_page.set_running(self._is_running())

    # ==================================================================
    # 首页状态
    # ==================================================================
    def _is_running(self):
        return bool(self.worker and self.worker.isRunning())

    def _refresh_home_stats(self):
        self.home_page.set_run_count(self.config.get("run_count", 0))
        last = self.config.get("last_run_time", "")
        self.home_page.set_last_run(last)

    def _update_next_run(self):
        if not self.config.get("enable_schedule", False):
            self.home_page.set_next_run("")
            return

        time_str = self.config.get("execute_time", "08:00")
        target = QTime.fromString(time_str, "HH:mm")
        if not target.isValid():
            self.home_page.set_next_run("")
            return

        now = QTime.currentTime()
        now_sec = now.hour() * 3600 + now.minute() * 60 + now.second()
        tgt_sec = target.hour() * 3600 + target.minute() * 60

        if tgt_sec <= now_sec:
            diff = 24 * 3600 - now_sec + tgt_sec
            is_tomorrow = True
        else:
            diff = tgt_sec - now_sec
            is_tomorrow = False

        hours = diff // 3600
        minutes = (diff % 3600) // 60

        if hours == 0 and minutes == 0:
            text = self.i18n.t("home.next_run.now")
        else:
            text = self.i18n.t("home.next_run.in",
                               hours=hours, minutes=minutes, time=time_str)

        if is_tomorrow and hours >= 12:
            text = self.i18n.t("home.next_run.tomorrow", time=time_str)

        self.home_page.set_next_run(text)

    # ==================================================================
    # 定时
    # ==================================================================
    def _check_schedule(self):
        if not self.config.get("enable_schedule", False):
            return
        now = QTime.currentTime()
        target = QTime.fromString(self.config.get("execute_time", "08:00"), "HH:mm")
        today = QDate.currentDate().toString("yyyy-MM-dd")
        if now >= target and self.config.get("last_trigger_date") != today:
            self.logger.info(
                f"定时触发：当前 {now.toString('HH:mm')} >= 设定 {target.toString('HH:mm')}"
            )
            self.config["last_trigger_date"] = today
            save_config(self.config)
            self._update_next_run()
            self.manual_run()

    # ==================================================================
    # 执行
    # ==================================================================
    def manual_run(self):
        if self._is_running():
            self.logger.info("任务正在执行中，请勿重复启动。")
            return

        self.config["run_count"] = self.config.get("run_count", 0) + 1
        self.config["last_run_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_config(self.config)
        self._refresh_home_stats()

        run_id = self.config["run_count"]
        now = datetime.datetime.now()
        run_dir = os.path.join(
            LOG_DIR,
            now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"),
            f"run_{run_id}_{now.strftime('%H%M%S')}",
        )
        os.makedirs(run_dir, exist_ok=True)

        self.logger.info(f"========== 开始第 {run_id} 次执行 ==========")
        self.logger.info(f"本次任务日志: {run_dir}")

        self.home_page.set_running(True)

        self.worker = Worker(self.config, run_dir)
        self.worker.log_signal.connect(self.home_page.append_log)
        self.worker.task_finished.connect(self._on_task_finished)   # ← 新增
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def stop_task(self):
        if not self._is_running():
            self.logger.info("当前没有正在执行的任务。")
            return
        self.logger.info("用户请求终止任务，正在等待当前阶段退出...")
        self.worker.requestInterruption()

    def _on_task_finished(self, status):
        """任务结束时按状态弹出系统托盘通知。"""
        if not self.config.get("enable_system_notify", True):
            return
        if status == "成功":
            msg = self.i18n.t("notify.task_success")
            icon = QSystemTrayIcon.Information
        elif status == "中止":
            msg = self.i18n.t("notify.task_stopped")
            icon = QSystemTrayIcon.Warning
        else:
            msg = self.i18n.t("notify.task_failed")
            icon = QSystemTrayIcon.Critical
        self.tray.showMessage("MaaAuto", msg, icon, 5000)

    def _on_worker_finished(self):
        self.home_page.set_running(False)
        self.logger.info("任务执行结束。\n")
        self._refresh_home_stats()
        self._update_next_run()

    # ==================================================================
    # 自启 / 退出
    # ==================================================================
    def set_auto_start(self):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "MaaAuto"
        exe_path = os.path.abspath(sys.argv[0])
        if exe_path.endswith(".py"):
            exe_path = f'python "{exe_path}"'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                 winreg.KEY_SET_VALUE)
            if self.config.get("auto_start"):
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ,
                                  f'"{exe_path}" --autostart')
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            self.logger.error(f"设置开机自启失败: {e}")

    def show_normal(self):
        self.showNormal()
        self.activateWindow()

    def cleanup_on_exit(self):
        if self.config.get("kill_on_exit", True):
            kill_all_related_processes()
        if self.worker and self.worker.isRunning():
            self.worker.terminate()

    def quit_app(self):
        self.is_quitting = True
        self._save_geometry()
        self.set_auto_start()
        self.cleanup_on_exit()
        QApplication.quit()

    def closeEvent(self, event):
        if self.is_quitting:
            event.accept()
            return
        if self.config.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
            self.tray.showMessage("MaaAuto", self.i18n.t("tray.minimized"),
                                  QSystemTrayIcon.Information, 2000)
        else:
            self.is_quitting = True
            self._save_geometry()
            self.cleanup_on_exit()
            event.accept()
            QApplication.quit()

    def _restore_geometry(self):
        data = self.config.get("window_geometry", "")
        if not data:
            return
        try:
            self.restoreGeometry(base64.b64decode(data.encode("ascii")))
        except Exception:
            pass

    def _save_geometry(self):
        try:
            data = bytes(self.saveGeometry())
            self.config["window_geometry"] = base64.b64encode(data).decode("ascii")
            save_config(self.config)
        except Exception:
            pass