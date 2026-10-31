import os
import sys
import logging
import datetime
import atexit
import base64

from PySide6.QtWidgets import (QMainWindow, QHBoxLayout, QMessageBox,
                               QSystemTrayIcon, QMenu, QApplication)
from PySide6.QtCore import QTimer, QThread, Signal, QTime, QDate, QProcess
from PySide6.QtGui import QIcon, QAction

from config_manager import (load_config, save_config, LOG_DIR, CONFIG_DIR,
                            RUNTIME_CONFIG_KEYS)
from automation import (execute_workflow, last_failure,
                        FAILURE_TEMPLATE, FAILURE_OFFSCREEN)
from utils import resource_path, AsyncWorker
import autostart
from process_utils import kill_all_related_processes
from ui.background import BackgroundWidget
from ui.sidebar import Sidebar
from ui.sliding_stack import SlidingStack
from ui.pages.home_page import HomePage
from ui.pages.settings_page import SettingsPage
from ui.pages.about_page import AboutPage
from ui.animations import theme_transition, clear_transition_overlay


# =========================================================================== #
# 界面缩放 / 重启（模块级，便于单测，不依赖 MainWindow 实例）
# =========================================================================== #
def build_restart_command(argv=None, frozen=None, executable=None):
    """构造「重启自己」的 (program, args)。

    * 打包态：``sys.executable`` 就是 MaaAuto.exe，其余参数原样透传；
    * 开发态：``sys.executable`` 是 python.exe，必须把脚本路径补回第一个参数，
      否则新进程会变成「启动解释器」然后立刻退出。

    ``--upgrading`` / ``--autostart`` 一律剥掉：重启是用户主动点出来的，
    期望看到主窗口，而不是静默进托盘。
    """
    argv = list(sys.argv if argv is None else argv)
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    executable = sys.executable if executable is None else executable

    args = [a for a in argv[1:] if a not in ("--upgrading", "--autostart")]
    if frozen:
        return executable, args
    script = os.path.abspath(argv[0]) if argv else ""
    return executable, ([script] if script else []) + args


def apply_ui_scale_live(theme_manager, app, scale, theme=None,
                        accent_color=None, sidebar=None):
    """即时应用界面缩放，不必重启。

    1.0.4 只把 ``ui_scale`` 存进配置，界面毫无反应——用户以为功能没做。
    这里做三件真正看得见的事：

    * 重写 QSS 里的 px 长度（字号 + ``min-width`` / ``min-height`` / padding；
      QSS 的 ``* { font-size: 13px }`` 会覆盖 ``QApplication.setFont()``，
      只改 app 字体等于没改）；
    * 侧栏宽度/边距/图标按比例重排（它是构造时 ``setFixedWidth`` 定死的）；
    * 自绘控件（开关、色块、滚轮时间）由调用方 ``SettingsPage.apply_ui_scale``
      同步。

    返回实际使用的缩放倍数（已夹到 0.75~2.0）。
    """
    try:
        scale = max(0.75, min(2.0, float(scale)))
    except (TypeError, ValueError):
        scale = 1.0

    if theme is None:
        theme = getattr(theme_manager, "_requested_theme", "system")
    theme_manager.apply_theme(theme, app, accent_color=accent_color,
                              ui_scale=scale)
    if sidebar is not None:
        sidebar.set_scale(scale)
    return scale


def spawn_new_instance(program, args, workdir=""):
    """拉起一个新进程，返回是否成功。

    ★ PySide6 的静态 ``QProcess.startDetached(program, args, cwd)`` 返回的是
    ``(ok, pid)`` 元组，而实例方法 ``startDetached()`` 返回 bool。直接
    ``if not QProcess.startDetached(...)`` 会把 ``(False, 0)`` 判成成功——
    非空元组永远为真——重启失败也就不会提示用户。这里统一归一成 bool。
    """
    try:
        result = QProcess.startDetached(program, args, workdir)
    except Exception:
        return False
    if isinstance(result, tuple):
        return bool(result[0]) if result else False
    return bool(result)


class Worker(QThread):
    task_finished = Signal(str)

    def __init__(self, config, run_log_dir):
        super().__init__()
        self.config = config
        self.run_log_dir = run_log_dir

    def run(self):
        logger = logging.getLogger("MaaAuto")

        # 只挂/摘自己的文件 handler，绝不 removeHandler 掉全局 handler。
        #
        # 旧的实现会在开头摘掉 logger 的所有 handler（包括 main.py 里
        # setup_logger() 创建、并已 connect 到首页日志的那个），结束时再补
        # 一个**没有接信号**的 LogHandler。后果：
        #   - 从第 2 次执行起，主线程日志不再出现在首页；
        #   - 每次运行多挂一个空 handler。
        #
        # 现在界面日志统一走 main.py 的那个 LogHandler：它是 QObject，
        # 从 worker 线程 emit 会被 Qt 排队到主线程，安全且不会重复。
        file_handler = logging.FileHandler(
            os.path.join(self.run_log_dir, "task.log"), encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)

        try:
            status = execute_workflow(self.config, logger) or "成功"
            self.task_finished.emit(status)
        except Exception as e:
            logger.error(f"执行错误: {e}")
            self.task_finished.emit("报错")
        finally:
            logger.removeHandler(file_handler)
            file_handler.close()


class MainWindow(QMainWindow):
    def __init__(self, i18n, theme_manager):
        super().__init__()
        self.i18n = i18n
        self.theme_manager = theme_manager
        self.config = load_config()
        self.worker = None
        self.is_quitting = False
        self._hidden_for_task = False
        self._restart_ask_open = False
        # 重启 / 升级后会自动拉起新实例，这时退出**不能**顺手杀掉 MAA / 模拟器。
        # 旧实现只靠 kill_on_exit，而 atexit 里还会再调一次 cleanup_on_exit，
        # 于是「重启程序」会把用户已经开好的 MAA / MuMu 一起关掉（实测）。
        self._relaunching = False

        self.logger = logging.getLogger("MaaAuto")
        self.logger.setLevel(logging.INFO)

        self.setWindowTitle(self.i18n.t("app.title"))
        size_w, size_h = self._preferred_size()
        self.resize(size_w, size_h)
        self._restore_geometry()
        self.setWindowIcon(QIcon(resource_path("resources/icon.ico")))

        self.bg_root = BackgroundWidget()
        self.setCentralWidget(self.bg_root)

        root_layout = QHBoxLayout(self.bg_root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar(self.i18n, compact=(size_w < 1000),
                               scale=float(self.config.get("ui_scale", 1.0) or 1.0))
        self.sidebar.page_changed.connect(self._on_page_changed)
        root_layout.addWidget(self.sidebar)

        self.stack = SlidingStack()
        self.stack.set_animation_enabled(self.config.get("show_animation", True))
        root_layout.addWidget(self.stack, 1)

        self.home_page = HomePage(self.i18n)
        self.settings_page = SettingsPage(self.config, self.i18n, self.theme_manager)
        self.about_page = AboutPage(self.i18n)
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.about_page)
        self.stack.setCurrentIndex(0)

        self.home_page.run_clicked.connect(self.manual_run)
        self.home_page.stop_clicked.connect(self.stop_task)
        self.home_page.clear_log_clicked.connect(self.home_page.clear_log)
        self.settings_page.config_changed.connect(self._on_config_changed)
        self.settings_page.theme_changed.connect(self._on_theme_changed)
        self.settings_page.language_changed.connect(self._on_language_changed)
        self.settings_page.accent_changed.connect(self._on_accent_changed)
        self.settings_page.ui_scale_changed.connect(self._on_ui_scale_changed)
        self.settings_page.restart_requested.connect(self.restart_app)
        self.i18n.language_changed.connect(self._retranslate_all)

        self._apply_background()
        self._setup_tray()

        self.schedule_timer = QTimer(self)
        self.schedule_timer.timeout.connect(self._check_schedule)
        self.schedule_timer.start(10_000)

        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_next_run)
        self.countdown_timer.start(30_000)

        self._refresh_home_stats()
        self._update_next_run()

        atexit.register(self.cleanup_on_exit)

        self._upgrading_check_timer = QTimer(self)
        self._upgrading_check_timer.timeout.connect(self._check_upgrading_flag)
        self._upgrading_check_timer.start(1000)

        self._pending_upgrade_silent = False
        self._pending_upgrade_info = None

        # 定时撞上运行中任务时，记下"已提示过顺延"的日期，避免每 10s 刷日志
        self._schedule_deferred_key = ""

        # 更新检查线程句柄
        self._update_check_worker = None
        # 同一次运行里只弹一次「发现新版本」，避免托盘重试时反复骚扰
        self._update_prompt_shown = False

        self.home_page.tutorial_clicked.connect(self.show_tutorial)
        self.home_page.announcements_clicked.connect(self.show_announcements)
        self.about_page.announcements_clicked.connect(self.show_announcements)
        # 公告：内存缓存 + 后台拉在线版本 + 每轮运行最多自动弹一次
        self._ann_cache = None
        self._announcements_worker = None
        self._announcements_shown_this_run = False
        self._announcements_dialog = None
        self._tutorial_open = False
        self._refresh_announcement_badge()

        if self.config.get("auto_check_update", True):
            QTimer.singleShot(5000, self._auto_check_update)

        # 启动引导：先教程（首次），再公告（有未读/更新时自动弹一次）
        QTimer.singleShot(1200, self._startup_prompts)
        # 后台拉在线公告（不需要发版就能改公告）
        QTimer.singleShot(2500, self._fetch_announcements_async)
        # 每次启动校一遍自启：旧版本写的是 Run 键（对提权程序无效），
        # 升级上来的用户要在这里迁移成登录计划任务。
        QTimer.singleShot(900, self.set_auto_start)

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
        self.act_restart = QAction(self.i18n.t("tray.restart"), self, triggered=self.restart_app)
        self.act_quit = QAction(self.i18n.t("tray.quit"), self, triggered=self.quit_app)

        menu.addAction(self.act_show)
        menu.addAction(self.act_settings)
        menu.addSeparator()
        menu.addAction(self.act_stop)
        menu.addSeparator()
        menu.addAction(self.act_restart)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_normal() if r == QSystemTrayIcon.DoubleClick else None)
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
    # 配置 / 主题 / 语言 / 强调色
    # ==================================================================
    def _on_config_changed(self, cfg):
        auto_start_before = self.config.get("auto_start", False)
        # 设置页的快照里带着启动时的运行时键（tutorial_seen 等），直接 update
        # 会把它们冲回旧值：实测「教程每次启动都弹」「运行次数被重置」。
        runtime = {k: self.config[k] for k in RUNTIME_CONFIG_KEYS
                   if k in self.config}
        self.config.update(cfg)
        self.config.update(runtime)
        save_config(self.config)
        self._apply_background()
        self._refresh_home_stats()
        self._update_next_run()
        self.stack.set_animation_enabled(self.config.get("show_animation", True))

        # 开机自启是注册表状态，不能只等退出时才写：用户拨开关就该生效。
        if bool(self.config.get("auto_start", False)) != bool(auto_start_before):
            self.set_auto_start()

    def _on_theme_changed(self, theme):
        self.config["theme"] = theme
        save_config(self.config)
        accent = self.config.get("accent_color", "#3b82f6")

        def do_switch():
            self.theme_manager.apply_theme(
                theme, QApplication.instance(), accent_color=accent)
            # 富文本链接色不跟 QSS 走，切主题后要手动刷一次
            self.about_page.refresh_theme_colors()

        theme_transition(self, do_switch, duration=260)

    def _on_language_changed(self, code):
        self.config["language"] = code
        save_config(self.config)
        self.i18n.load_language(code)

    def _on_accent_changed(self, hexv):
        self.config["accent_color"] = hexv
        save_config(self.config)
        try:
            self.theme_manager.apply_accent(hexv, QApplication.instance())
        except Exception as e:
            self.logger.error(f"应用强调色失败: {e}")

    def _retranslate_all(self, *_):
        self.setWindowTitle(self.i18n.t("app.title"))
        self.sidebar.retranslate()
        self.home_page.retranslate()
        self.settings_page.retranslate()
        self.about_page.retranslate()
        self.act_show.setText(self.i18n.t("tray.show"))
        self.act_settings.setText(self.i18n.t("tray.settings"))
        self.act_stop.setText(self.i18n.t("tray.stop"))
        self.act_restart.setText(self.i18n.t("tray.restart"))
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
        import datetime as _dt
        import schedule_utils as su
        times = su.effective_times(self.config)
        weekdays = su.effective_weekdays(self.config)
        now = _dt.datetime.now()
        when = su.next_run(times, weekdays, now)
        if when is None:
            self.home_page.set_next_run("")
            return
        hours, minutes, not_today = su.humanize_next(when, now)
        time_text = when.strftime("%H:%M")
        if hours == 0 and minutes == 0:
            text = self.i18n.t("home.next_run.now")
        else:
            text = self.i18n.t("home.next_run.in", hours=hours,
                               minutes=minutes, time=time_text)
        if not_today and hours >= 12:
            text = self.i18n.t("home.next_run.tomorrow", time=time_text)
        self.home_page.set_next_run(text)

    # ==================================================================
    # 定时
    # ==================================================================
    def _check_schedule(self):
        if not self.config.get("enable_schedule", False):
            return
        import datetime as _dt
        import schedule_utils as su

        times = su.effective_times(self.config)
        weekdays = su.effective_weekdays(self.config)
        now = _dt.datetime.now()
        last_key = self.config.get("last_trigger_key") or ""
        key = su.due_slot(times, weekdays, now, last_key)
        if not key:
            return

        # 任务还在跑：**不要**写 last_trigger_key，等它结束后的下一次检查补跑
        if self._is_running():
            if self._schedule_deferred_key != key:
                self._schedule_deferred_key = key
                self.logger.info("定时时间已到，但任务仍在执行；结束后会自动补跑一次。")
            return

        self.logger.info(f"定时触发：{key}")
        self.config["last_trigger_key"] = key
        self.config["last_trigger_date"] = now.date().isoformat()   # 兼容旧字段
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
            f"run_{run_id}_{now.strftime('%H%M%S')}")
        os.makedirs(run_dir, exist_ok=True)
        self.logger.info(f"========== 开始第 {run_id} 次执行 ==========")
        self.logger.info(f"本次任务日志: {run_dir}")
        self.home_page.set_running(True)
        self._hide_for_task()
        self.worker = Worker(self.config, run_dir)
        self.worker.task_finished.connect(self._on_task_finished)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def stop_task(self):
        if not self._is_running():
            self.logger.info("当前没有正在执行的任务。")
            return
        self.logger.info("用户请求终止任务，正在等待当前阶段退出...")
        self.worker.requestInterruption()

    def _on_task_finished(self, status):
        if not self.config.get("enable_system_notify", True):
            return
        duration = 5000
        if status == "成功":
            msg = self.i18n.t("notify.task_success")
            icon = QSystemTrayIcon.Information
        elif status == "中止":
            msg = self.i18n.t("notify.task_stopped")
            icon = QSystemTrayIcon.Warning
        else:
            # 失败时尽量说清楚「下一步做什么」：找图超时基本等于模板过期，
            # 窗口在屏幕外则是环境问题，两者的处理方式完全不同。
            kind = last_failure().get("kind")
            if kind == FAILURE_TEMPLATE:
                msg = self.i18n.t("notify.task_failed_template")
                icon = QSystemTrayIcon.Warning
                duration = 10000
            elif kind == FAILURE_OFFSCREEN:
                msg = self.i18n.t("notify.task_failed_offscreen")
                icon = QSystemTrayIcon.Warning
                duration = 8000
            else:
                msg = self.i18n.t("notify.task_failed")
                icon = QSystemTrayIcon.Critical
        self.tray.showMessage("MaaAuto", msg, icon, duration)

    def _on_worker_finished(self):
        self.home_page.set_running(False)
        self.logger.info("任务执行结束。\n")
        self._refresh_home_stats()
        self._update_next_run()
        self._restore_after_task()
        if self._pending_upgrade_silent and self._pending_upgrade_info:
            info = self._pending_upgrade_info
            self._pending_upgrade_silent = False
            self._pending_upgrade_info = None
            self.logger.info("任务已结束，开始挂起的自动升级。")
            QTimer.singleShot(2000, lambda: self._trigger_upgrade(info, silent=True))

    # ------------------------------------------------------------------
    # 任务期间隐藏主窗口
    #
    # 我们的窗口是普通置顶的 1080×720，很容易盖住 MAA / MaaEnd 的按钮。
    # 一旦被盖住：找图截到的是我们自己的界面（匹配失败或匹配到别的东西），
    # 或者点击落到了我们自己窗口上——两种都表现为「点了没反应」。
    # 所以任务开始时自动收进托盘，结束后再还原。
    # ------------------------------------------------------------------
    def _hide_for_task(self):
        self._hidden_for_task = False
        if not self.config.get("minimize_on_task", True):
            return
        if not self.isVisible() or self.isMinimized():
            return
        self.logger.info("任务期间自动隐藏主窗口（避免遮挡目标程序），结束后自动还原。")
        self.hide()
        self._hidden_for_task = True

    def _restore_after_task(self):
        if not getattr(self, "_hidden_for_task", False):
            return
        self._hidden_for_task = False
        self.show_normal()

    # ==================================================================
    # 界面缩放（即时生效）与重启
    # ==================================================================
    def _current_scale(self):
        try:
            return max(0.75, min(2.0,
                                  float(self.config.get("ui_scale", 1.0) or 1.0)))
        except (TypeError, ValueError):
            return 1.0

    def _on_ui_scale_changed(self, scale, ask_restart=True):
        """设置页切换缩放比例：先即时重绘，再问要不要重启。

        1.0.4 的实现只把 ui_scale 写进配置，界面要等下次启动才变、也没有任何
        提示，实测就是「改了没反应，也没有重启选项」。现在两步都补上。
        """
        try:
            scale = max(0.75, min(2.0, float(scale)))
        except (TypeError, ValueError):
            scale = 1.0

        self.config["ui_scale"] = scale
        save_config(self.config)
        self.logger.info(
            f"界面缩放切换为 {int(round(scale * 100))}%，即时重绘（无需重启）")

        def do_apply():
            apply_ui_scale_live(
                self.theme_manager, QApplication.instance(), scale,
                theme=self.config.get("theme", "system"),
                accent_color=self.config.get("accent_color", "#3b82f6"),
                sidebar=self.sidebar)
            self.settings_page.apply_ui_scale(scale)
            self._apply_scale_limits()

        # ★ 不能再用「旧画面遮罩淡出」：缩放会改窗口和控件尺寸，遮罩还是旧尺寸，
        #   淡出时就会看到旧布局残影（实测 150% 下偶发「重影」）。直接重绘。
        clear_transition_overlay(self)
        do_apply()

        if ask_restart:
            QTimer.singleShot(260, lambda: self._ask_restart(scale))

    def _apply_scale_limits(self):
        """按当前缩放重算最小窗口尺寸，避免大字号在小屏上被裁掉。"""
        avail = self._available_rect()
        if avail is None:
            return
        scale = self._current_scale()
        min_w = max(640, int(min(900 * scale, avail.width() - 40)))
        min_h = max(420, int(min(560 * scale, avail.height() - 40)))
        self.setMinimumSize(min_w, min_h)
        if self.width() < min_w or self.height() < min_h:
            self.resize(max(self.width(), min_w), max(self.height(), min_h))

    def _confirm_restart(self, scale) -> bool:
        """询问是否立即重启（拆出来方便单测，不必真的弹模态框）。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(self.i18n.t("settings.ui_scale.applied.title"))
        box.setText(self.i18n.t("settings.ui_scale.applied.text",
                                scale=int(round(scale * 100))))
        btn_now = box.addButton(self.i18n.t("common.restart_now"),
                                QMessageBox.AcceptRole)
        box.addButton(self.i18n.t("common.later"), QMessageBox.RejectRole)
        box.setDefaultButton(btn_now)
        box.exec()
        return box.clickedButton() is btn_now

    def _ask_restart(self, scale):
        # 连续切两次缩放会排两个 260ms 定时器；弹窗是模态嵌套事件循环，
        # 第二个回调会在弹窗期间执行 —— 加个门闩，别叠两个对话框。
        if self._restart_ask_open:
            return
        self._restart_ask_open = True
        try:
            if self._confirm_restart(scale):
                self.restart_app()
        finally:
            self._restart_ask_open = False

    def restart_app(self):
        """重启自己：先拉起新进程，确认起来了再退出当前进程。

        只重建界面，不走「退出」的清理流程——重启不应该顺手把 MAA / 模拟器
        一起杀掉（那是 ``kill_on_exit`` 的语义）。任务线程仍会先停掉。
        """
        program, args = build_restart_command()
        ok = spawn_new_instance(program, args, os.path.dirname(program))
        self.logger.info(f"重启程序: {program} {' '.join(args)}" + ("" if ok else "（启动失败）"))

        if not ok:
            self.logger.error("重启失败：无法启动新实例")
            QMessageBox.warning(self, self.i18n.t("common.warning"),
                                self.i18n.t("settings.restart.failed"))
            return False

        self.is_quitting = True
        self._relaunching = True
        try:
            self._save_geometry()
        except Exception:
            pass
        self._shutdown_worker(1500)
        QApplication.quit()
        return True

    # ==================================================================
    # 公告 / 新手教程
    #
    # 公告走「内置 + 在线」：启动先用缓存/内置秒开，后台线程拉 GitHub 上的
    # announcements.json（不需要发版就能改公告），拉到后写缓存、刷新红点。
    # 「未读」= 没见过的 id；或 id 都见过但 updated 变了（内容有更新）。
    # ==================================================================
    def _announcements_data(self):
        """当前生效的 (updated, items)：优先用内存里拉到的最新版本。"""
        if getattr(self, "_ann_cache", None):
            updated, items = self._ann_cache
            if items:
                return updated, items
        from ui.announcements import initial_announcements
        updated, items = initial_announcements()
        self._ann_cache = (updated, items)
        return updated, items

    def _refresh_announcement_badge(self):
        from ui.announcements import unread_state
        updated, items = self._announcements_data()
        state = unread_state(
            items, updated,
            self.config.get("announcements_seen") or [],
            self.config.get("announcements_seen_updated") or "")
        self.home_page.set_announcement_badge(state["count"])
        return state

    def _fetch_announcements_async(self):
        """后台拉在线公告；失败静默（继续用缓存/内置）。"""
        from ui.announcements import fetch_remote_announcements

        self._announcements_worker = AsyncWorker(fetch_remote_announcements)
        self._announcements_worker.finished.connect(self._on_remote_announcements)
        self._announcements_worker.error.connect(
            lambda err: self.logger.debug(f"拉取在线公告失败: {err}"))
        self._announcements_worker.start()

    def _on_remote_announcements(self, result):
        if not result:
            return
        remote_updated, remote_items = result
        from ui.announcements import pick_best, save_cache
        local_updated, local_items = self._announcements_data()
        # 合并而不是覆盖：jsDelivr 有缓存，可能返回更旧的 JSON
        updated, items = pick_best(local_updated, local_items,
                                   remote_updated, remote_items)
        save_cache(updated, items)
        old_updated = (self._ann_cache or ("", []))[0]
        self._ann_cache = (updated, items)
        if len(items) != len(local_items) or updated != old_updated:
            self.logger.info(f"在线公告已同步：{updated}（{len(items)} 条）")
        self._refresh_announcement_badge()
        self._maybe_show_announcements()

    def show_announcements(self):
        from ui.announcements import AnnouncementDialog
        updated, items = self._announcements_data()
        if not items:
            return
        # 已经开着就不要叠第二个：把现有窗口提到前面
        existing = getattr(self, "_announcements_dialog", None)
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                self._announcements_dialog = None

        self._announcements_shown_this_run = True
        # 先落盘已读：窗口开着时用户可能直接关掉程序/被升级进程结束，
        # 旧实现把写入放在 exec() 之后，于是下次启动又提示"有新公告"。
        self._mark_announcements_seen(updated, items)

        dlg = AnnouncementDialog(self.i18n, items, self.i18n.current_lang,
                                 self, updated=updated)
        self._announcements_dialog = dlg
        try:
            dlg.exec()
        finally:
            self._announcements_dialog = None
            # 期间可能又拉到了新公告，关闭时再记一次
            latest_updated, latest_items = self._announcements_data()
            self._mark_announcements_seen(latest_updated, latest_items)

    def _mark_announcements_seen(self, updated, items):
        self.config["announcements_seen"] = [it.get("id") for it in items
                                            if it.get("id")]
        self.config["announcements_seen_updated"] = updated or ""
        save_config(self.config)
        self._refresh_announcement_badge()

    def _maybe_show_announcements(self):
        """有未读/更新时自动弹一次公告（每轮运行一次；窗口在托盘时不打扰）。

        首次安装不自动弹（先看新手教程），只显示红点；老用户（看过公告的）
        遇到新公告或 updated 变化才自动弹。
        """
        if getattr(self, "_announcements_shown_this_run", False):
            return
        if self._tutorial_open:
            return
        if not self.isVisible() or self.isMinimized():
            return
        if not (self.config.get("announcements_seen_updated")
                or self.config.get("announcements_seen")):
            return                      # 从没看过公告：留给用户自己点
        state = self._refresh_announcement_badge()
        if state["count"] > 0:
            self.logger.info(f"公告有更新（{state['count']}），自动展示。")
            self.show_announcements()

    def show_tutorial(self):
        from ui.tutorial_dialog import TutorialDialog
        self._tutorial_open = True
        try:
            dlg = TutorialDialog(self.i18n, self)
            dlg.exec()
        finally:
            self._tutorial_open = False
        if not self.config.get("tutorial_seen"):
            self.config["tutorial_seen"] = True
            save_config(self.config)

    def _maybe_show_tutorial(self):
        """首次启动自动展示新手教程；之后只从首页按钮进入。"""
        if self.config.get("tutorial_seen"):
            return False
        if not self.isVisible() or self.isMinimized():
            return False
        self.logger.info("首次启动，展示新手教程。")
        self.show_tutorial()
        return True

    def _startup_prompts(self):
        """首次启动先弹教程，教程关掉后再考虑公告（避免两个模态叠一起）。"""
        shown = self._maybe_show_tutorial()
        delay = 400 if shown else 200
        QTimer.singleShot(delay, self._maybe_show_announcements)

    # ==================================================================
    # 升级
    # ==================================================================
    def _check_upgrading_flag(self):
        flag = os.path.join(CONFIG_DIR, ".upgrading")
        if not os.path.exists(flag):
            return
        self.logger.info("检测到升级标志 config/.upgrading，准备退出...")
        self._upgrading_check_timer.stop()
        self.is_quitting = True
        try:
            self._save_geometry()
        except Exception:
            pass
        self.cleanup_on_exit()
        QApplication.quit()

    def _auto_check_update(self):
        """
        启动 5 秒后检查更新 —— 后台线程执行，绝不阻塞 UI。
        无论成功/失败/无更新，都通过信号回主线程处理。
        """
        try:
            from update_checker import check_update
        except Exception as e:
            self.logger.warning(f"无法导入 update_checker: {e}")
            return

        # 后台线程执行网络请求
        channel = self.config.get("update_channel", "stable")
        self._update_check_worker = AsyncWorker(check_update, channel)
        self._update_check_worker.finished.connect(self._on_update_checked)
        self._update_check_worker.error.connect(
            lambda err: self.logger.warning(f"检查更新失败: {err}"))
        self._update_check_worker.start()

    def _on_update_checked(self, info):
        if not info or not info.get("has_update"):
            return
        self.logger.info(f"检测到新版本: {info['latest']}（当前 {info['current']}）")
        if self.config.get("auto_download_update", False):
            if self._is_running():
                self._pending_upgrade_silent = True
                self._pending_upgrade_info = info
                self.tray.showMessage(
                    "MaaAuto",
                    self.i18n.t("upgrade.pending_after_task", version=info["latest"]),
                    QSystemTrayIcon.Information, 5000)
                self.logger.info("任务运行中，自动升级已挂起，任务结束后执行。")
                return
            self._trigger_upgrade(info, silent=True)
        else:
            # 手动升级：不再只弹托盘气泡，直接给「版本对比 + 发布说明」的新弹窗。
            # 任务运行中 / 窗口在托盘里时不打扰，仍然只发气泡。
            if self._update_prompt_shown:
                return
            self._update_prompt_shown = True
            if self._is_running() or not self.isVisible():
                self.tray.showMessage(
                    "MaaAuto",
                    self.i18n.t("upgrade.available", version=info["latest"]),
                    QSystemTrayIcon.Information, 5000)
                return
            from ui.update_dialog import ask_update
            if ask_update(self.i18n, info, self):
                self._trigger_upgrade(info, silent=False)

    def _trigger_upgrade(self, info, silent=False):
        from update_checker import apply_update
        channel = self.config.get("update_channel", "stable")
        self.logger.info(f"触发升级: silent={silent}, channel={channel} → {info.get('latest')}")
        if apply_update(self, silent=silent, channel=channel):
            self.is_quitting = True
            # 升级完会自动重启：退出时别把 MAA / 模拟器一起杀掉
            self._relaunching = True
            try:
                self._save_geometry()
            except Exception:
                pass
            self.cleanup_on_exit()
            QApplication.quit()

    # ==================================================================
    # 自启 / 退出
    # ==================================================================
    def set_auto_start(self):
        """开关开机自启（1.4.5 起：打包态用登录计划任务，开发态用 Run 键）。

        MaaAuto.exe 要求管理员权限，而 Windows 不会用 ``HKCU\\...\\Run`` 拉起
        需要提权的程序——任务管理器里开关亮着，登录时却什么都不发生。
        计划任务用 ``/RL HIGHEST`` 在登录时直接给管理员令牌，不弹 UAC。
        详见 :mod:`autostart`。
        """
        enabled = bool(self.config.get("auto_start", False))
        frozen = getattr(sys, "frozen", False)
        script = None if frozen else os.path.abspath(sys.argv[0])

        ok = autostart.set_enabled(enabled, executable=sys.executable,
                                   script=script)
        if enabled and not ok:
            self.logger.error(
                "开机自启没有设置成功：创建登录计划任务失败（需要管理员权限）。"
                "详见日志；可稍后重试，或用 README 里的排查步骤手动注册。")
            try:
                self.tray.showMessage("MaaAuto",
                                      self.i18n.t("notify.autostart_failed"),
                                      QSystemTrayIcon.Warning, 8000)
            except Exception:
                pass
        elif enabled:
            self.logger.info(f"开机自启已启用（{autostart.describe()}）")

    def show_normal(self):
        self.showNormal()
        self.activateWindow()

    def _shutdown_worker(self, timeout_ms=3000):
        if not (self.worker and self.worker.isRunning()):
            return
        self.logger.info("正在请求任务线程退出...")
        self.worker.requestInterruption()
        if not self.worker.wait(timeout_ms):
            self.logger.warning(f"任务线程 {timeout_ms}ms 内未退出，强制终止。")
            self.worker.terminate()
            self.worker.wait(1000)

    def _wait_async_workers(self, timeout_ms=800):
        """退出前等一下后台线程（更新检查 / 在线公告），避免 QThread 被析构时还在跑。"""
        for name in ("_update_check_worker", "_announcements_worker"):
            worker = getattr(self, name, None)
            if worker is None:
                continue
            try:
                if worker.isRunning():
                    worker.wait(timeout_ms)
            except Exception:
                pass

    def cleanup_on_exit(self):
        self._shutdown_worker()
        self._wait_async_workers()
        if self._relaunching:
            # 重启 / 自动升级会紧接着拉起新实例，MAA、模拟器与游戏跟这次退出
            # 完全无关；旧实现照 kill_on_exit 杀了一遍，实测「点重启，MAA 也没了」。
            self.logger.info("即将重启/升级，跳过结束 MAA / 模拟器等外部进程。")
            return
        if self.config.get("kill_on_exit", True):
            kill_all_related_processes()

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

    # ==================================================================
    # 尺寸适配（小屏幕 / 高 DPI）
    # ==================================================================
    def _available_rect(self):
        """当前屏幕的可用区域（已扣掉任务栏），单位是逻辑像素。"""
        from PySide6.QtGui import QGuiApplication
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()

    def _preferred_size(self):
        """按屏幕可用区域收缩默认 1080×720。

        1080×720 在 125% 缩放的 1366×768 笔记本上会被任务栏吃掉一截，
        窗口底部按钮点不到；这里直接按可用区域留 80px 边距。
        界面缩放放大字号后内容更占地方，默认尺寸同步放大，仍受可用区域限制。
        """
        avail = self._available_rect()
        scale = self._current_scale()
        if avail is None:
            return (int(1080 * scale), int(720 * scale))
        width = min(int(1080 * scale), max(720, avail.width() - 80))
        height = min(int(720 * scale), max(480, avail.height() - 80))
        self.setMinimumSize(max(640, int(min(900 * scale, avail.width() - 40))),
                            max(420, int(min(560 * scale, avail.height() - 40))))
        return (width, height)

    def _restore_geometry(self):
        data = self.config.get("window_geometry", "")
        if not data:
            return
        try:
            self.restoreGeometry(base64.b64decode(data.encode("ascii")))
        except Exception:
            return
        # 上次可能是在更大的显示器/不同缩放下关的窗口：恢复后要保证还在屏幕内
        avail = self._available_rect()
        if avail is None:
            return
        if (self.width() > avail.width() or self.height() > avail.height()
                or not avail.intersects(self.frameGeometry())):
            self.resize(min(self.width(), max(720, avail.width() - 80)),
                        min(self.height(), max(480, avail.height() - 80)))
            self.move(avail.x() + (avail.width() - self.width()) // 2,
                      avail.y() + (avail.height() - self.height()) // 2)

    def _save_geometry(self):
        try:
            data = bytes(self.saveGeometry())
            self.config["window_geometry"] = base64.b64encode(data).decode("ascii")
            save_config(self.config)
        except Exception:
            pass