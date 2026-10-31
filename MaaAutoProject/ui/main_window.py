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
# UI scale / restart (module-level so it is unit-testable without a MainWindow instance)
# =========================================================================== #
def build_restart_command(argv=None, frozen=None, executable=None):
    """Build the (program, args) pair for restarting ourselves.

    * Frozen: ``sys.executable`` is MaaAuto.exe; pass the remaining args through as-is.
    * Dev: ``sys.executable`` is python.exe, so the script path must go back as the first
      argument, or the new process just starts an interpreter and exits at once.

    ``--upgrading`` / ``--autostart`` are always stripped: a restart is user-initiated,
    so they expect the main window, not a silent tray start.
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
    """Apply the UI scale immediately, without a restart.

    1.0.4 only stored ``ui_scale`` in the config; nothing on screen changed, so users
    assumed the feature was not implemented. Three visible things happen here:

    * px lengths in the QSS are rewritten (font size + ``min-width`` / ``min-height`` /
      padding; QSS ``* { font-size: 13px }`` overrides ``QApplication.setFont()``, so
      changing only the app font is a no-op);
    * sidebar width/margins/icons are re-laid out proportionally (pinned by
      ``setFixedWidth`` at construction);
    * custom-painted widgets (switch, swatches, time wheel) are synced by the caller
      through ``SettingsPage.apply_ui_scale``.

    Returns the scale actually used (clamped to 0.75~2.0).
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
    """Start a new process; return whether it succeeded.

    ★ PySide6's static ``QProcess.startDetached(program, args, cwd)`` returns an
    ``(ok, pid)`` tuple, while the instance method returns bool. Testing
    ``if not QProcess.startDetached(...)`` treats ``(False, 0)`` as success — a
    non-empty tuple is always truthy — so a failed restart goes unreported. Normalized
    to a bool here.
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

        # Attach/detach only our own file handler; never removeHandler the global one.
        #
        # The old code removed every handler at the start (including the one main.py's
        # setup_logger() created and connected to the home-page log), then added back a
        # LogHandler **with no signal connected** at the end. Consequences:
        #   - from the 2nd run on, main-thread logs stopped showing on the home page;
        #   - each run leaked one extra empty handler.
        #
        # UI logging now goes through main.py's LogHandler: it is a QObject, so emits from
        # the worker thread are queued to the main thread — safe and never duplicated.
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
        # A restart / upgrade launches a new instance, so quitting must **not** kill
        # MAA / the emulator as a side effect. The old code relied on kill_on_exit, and
        # atexit called cleanup_on_exit again, so "Restart app" also closed a running
        # MAA / MuMu (measured).
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

        # When a scheduled run hits a running task, remember the "already deferred" date to avoid logging every 10s
        self._schedule_deferred_key = ""

        # update check thread handle
        self._update_check_worker = None
        # Prompt "new version found" only once per run so tray retries do not nag repeatedly
        self._update_prompt_shown = False

        self.home_page.tutorial_clicked.connect(self.show_tutorial)
        self.home_page.announcements_clicked.connect(self.show_announcements)
        self.about_page.announcements_clicked.connect(self.show_announcements)
        # Announcements: in-memory cache + background fetch of the online version + at most one auto-show per run
        self._ann_cache = None
        self._announcements_worker = None
        self._announcements_shown_this_run = False
        self._announcements_dialog = None
        self._tutorial_open = False
        self._refresh_announcement_badge()

        if self.config.get("auto_check_update", True):
            QTimer.singleShot(5000, self._auto_check_update)

        # Startup prompts: tutorial first (first launch), then announcements (auto-shown once when unread/updated)
        QTimer.singleShot(1200, self._startup_prompts)
        # Fetch online announcements in the background (content updates need no release)
        QTimer.singleShot(2500, self._fetch_announcements_async)
        # Re-validate autostart on every launch: old versions wrote a Run key (a no-op for
        # elevated programs), so upgraded users are migrated to a logon scheduled task here.
        QTimer.singleShot(900, self.set_auto_start)

    # ==================================================================
    # Background
    # ==================================================================
    def _apply_background(self):
        self.bg_root.set_background(
            self.config.get("background_image", ""),
            self.config.get("background_opacity", 0.3),
            self.config.get("background_blur", 0),
            self.config.get("background_mode", "cover"),
        )

    # ==================================================================
    # Tray
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
    # Page switching
    # ==================================================================
    def _on_page_changed(self, index):
        if index == self.stack.currentIndex():
            return
        self.sidebar.set_current(index)
        self.stack.setCurrentIndex(index)

    # ==================================================================
    # Config / theme / language / accent color
    # ==================================================================
    def _on_config_changed(self, cfg):
        auto_start_before = self.config.get("auto_start", False)
        # The settings page snapshot carries runtime keys from startup (tutorial_seen etc.);
        # a plain update would push them back to stale values — measured: tutorial on every
        # start, run count reset.
        runtime = {k: self.config[k] for k in RUNTIME_CONFIG_KEYS
                   if k in self.config}
        self.config.update(cfg)
        self.config.update(runtime)
        save_config(self.config)
        self._apply_background()
        self._refresh_home_stats()
        self._update_next_run()
        self.stack.set_animation_enabled(self.config.get("show_animation", True))

        # Autostart is registry state and cannot wait for exit: toggling the switch should apply at once
        if bool(self.config.get("auto_start", False)) != bool(auto_start_before):
            self.set_auto_start()

    def _on_theme_changed(self, theme):
        self.config["theme"] = theme
        save_config(self.config)
        accent = self.config.get("accent_color", "#3b82f6")

        def do_switch():
            self.theme_manager.apply_theme(
                theme, QApplication.instance(), accent_color=accent)
            # Rich-text link colors do not follow QSS; refresh them once after a theme switch
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
    # Home page state
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
    # Schedule
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

        # Task still running: do **not** write last_trigger_key; the next check after it ends catches up
        if self._is_running():
            if self._schedule_deferred_key != key:
                self._schedule_deferred_key = key
                self.logger.info("定时时间已到，但任务仍在执行；结束后会自动补跑一次。")
            return

        self.logger.info(f"定时触发：{key}")
        self.config["last_trigger_key"] = key
        self.config["last_trigger_date"] = now.date().isoformat()   # legacy field
        save_config(self.config)
        self._update_next_run()
        self.manual_run()

    # ==================================================================
    # Execution
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
            # On failure say what to do next: a search timeout usually means stale templates,
            # while an off-screen window is an environment problem — the fixes differ completely.
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
    # Hide the main window while a task runs
    #
    # Our window is a plain 1080x720 always-on-top frame and easily covers MAA / MaaEnd
    # buttons. When covered, image search grabs our own UI (no match or wrong match), or
    # clicks land on our own window — both look like "clicked, nothing happened". So hide
    # to the tray when a task starts and restore afterwards.
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
    # UI scale (applied live) and restart
    # ==================================================================
    def _current_scale(self):
        try:
            return max(0.75, min(2.0,
                                  float(self.config.get("ui_scale", 1.0) or 1.0)))
        except (TypeError, ValueError):
            return 1.0

    def _on_ui_scale_changed(self, scale, ask_restart=True):
        """Settings page changed the scale: repaint live first, then offer a restart.

        1.0.4 only wrote ui_scale to the config, so the UI changed only after the next
        start and nothing said so — measured: "changed nothing, no restart option". Both
        steps are restored here.
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

        # ★ No more "fade out the old frame overlay": scaling changes window and widget
        #   sizes, the overlay keeps the old size, and fading shows ghosts of the old layout
        #   (measured, occasional double image at 150%). Repaint directly.
        clear_transition_overlay(self)
        do_apply()

        if ask_restart:
            QTimer.singleShot(260, lambda: self._ask_restart(scale))

    def _apply_scale_limits(self):
        """Recompute the minimum window size for the current scale so large text is not clipped on small screens."""
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
        """Ask whether to restart now (split out so tests need no real modal dialog)."""
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
        # Switching scale twice queues two 260ms timers; the dialog runs a nested modal event
        # loop, so the second callback fires while it is open — latch it, no stacked dialogs.
        if self._restart_ask_open:
            return
        self._restart_ask_open = True
        try:
            if self._confirm_restart(scale):
                self.restart_app()
        finally:
            self._restart_ask_open = False

    def restart_app(self):
        """Restart: spawn the new process first, quit this one only once it is up.

        Only the UI is rebuilt; the "quit" cleanup path is skipped — a restart must not
        kill MAA / the emulator as a side effect (that is ``kill_on_exit`` semantics). The
        task thread is still stopped first.
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
    # Announcements / first-run tutorial
    #
    # Announcements are bundled + online: startup opens from cache/bundled data at once, a
    # background thread fetches announcements.json from GitHub (content changes need no
    # release), then writes the cache and refreshes the badge. "Unread" = unseen id, or a
    # seen id whose updated changed (content edited).
    def _announcements_data(self):
        """Currently effective (updated, items); prefer the newest version fetched into memory."""
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
        """Fetch online announcements in the background; stay silent on failure (keep cache/bundled)."""
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
        # Merge instead of overwrite: jsDelivr caches, so it may return older JSON
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
        # Do not stack a second window if one is open: raise the existing one instead
        existing = getattr(self, "_announcements_dialog", None)
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                self._announcements_dialog = None

        self._announcements_shown_this_run = True
        # Persist "seen" first: while the window is open the user may quit the app or be
        # ended by the updater; the old code wrote after exec(), so the next start prompted again.
        self._mark_announcements_seen(updated, items)

        dlg = AnnouncementDialog(self.i18n, items, self.i18n.current_lang,
                                 self, updated=updated)
        self._announcements_dialog = dlg
        try:
            dlg.exec()
        finally:
            self._announcements_dialog = None
            # New announcements may have arrived meanwhile; record again on close
            latest_updated, latest_items = self._announcements_data()
            self._mark_announcements_seen(latest_updated, latest_items)

    def _mark_announcements_seen(self, updated, items):
        self.config["announcements_seen"] = [it.get("id") for it in items
                                            if it.get("id")]
        self.config["announcements_seen_updated"] = updated or ""
        save_config(self.config)
        self._refresh_announcement_badge()

    def _maybe_show_announcements(self):
        """Auto-show announcements once when unread/updated (once per run; tray stays quiet).

        Fresh installs never auto-open (the tutorial comes first) — only the badge shows;
        users who have seen announcements before get an auto-show on new ids or updated changes.
        """
        if getattr(self, "_announcements_shown_this_run", False):
            return
        if self._tutorial_open:
            return
        if not self.isVisible() or self.isMinimized():
            return
        if not (self.config.get("announcements_seen_updated")
                or self.config.get("announcements_seen")):
            return                      # never opened announcements: let the user click
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
        """Show the tutorial automatically on first launch; afterwards only via the home button."""
        if self.config.get("tutorial_seen"):
            return False
        if not self.isVisible() or self.isMinimized():
            return False
        self.logger.info("首次启动，展示新手教程。")
        self.show_tutorial()
        return True

    def _startup_prompts(self):
        """On first launch show the tutorial, then consider announcements after it closes (no stacked modals)."""
        shown = self._maybe_show_tutorial()
        delay = 400 if shown else 200
        QTimer.singleShot(delay, self._maybe_show_announcements)

    # ==================================================================
    # Upgrading
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
        Check for updates 5 seconds after launch — on a background thread, never blocking the UI.
        Success / failure / no update all come back to the main thread through signals.
        """
        try:
            from update_checker import check_update
        except Exception as e:
            self.logger.warning(f"无法导入 update_checker: {e}")
            return

        # run the network request on a background thread
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
            # Manual update: no longer just a tray balloon — show the new version-comparison +
            # release-notes dialog instead. While a task runs or the window sits in the tray, do
            # not interrupt; still a balloon only.
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
            # Upgrading restarts afterwards: do not kill MAA / the emulator on the way out
            self._relaunching = True
            try:
                self._save_geometry()
            except Exception:
                pass
            self.cleanup_on_exit()
            QApplication.quit()

    # ==================================================================
    # Autostart / quit
    # ==================================================================
    def set_auto_start(self):
        """Toggle autostart (1.4.5+: logon scheduled task when frozen, Run key in dev).

        MaaAuto.exe requires admin rights, and Windows will not launch an elevated program
        from ``HKCU\\...\\Run`` — the switch looks on in Task Manager yet nothing happens at
        logon. The scheduled task uses ``/RL HIGHEST`` to get an admin token at logon without
        a UAC prompt. See :mod:`autostart`.
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
        """Wait for background threads (update check / online announcements) before exit, so no QThread is destroyed while running."""
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
            # A restart / auto-upgrade launches a new instance right away; MAA, the emulator and
            # the game are unrelated to this exit. The old code still killed by kill_on_exit — measured:
            # "clicked restart, MAA was gone too".
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
    # Size adaptation (small screens / high DPI)
    # ==================================================================
    def _available_rect(self):
        """Available area of the current screen (taskbar excluded), in logical pixels."""
        from PySide6.QtGui import QGuiApplication
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()

    def _preferred_size(self):
        """Shrink the default 1080x720 to the screen's available area.

        On a 1366x768 laptop at 125% scaling the taskbar eats into 1080x720 and the bottom
        buttons become unreachable, so leave an 80px margin inside the available area.
        A larger UI scale makes content bigger; the default size grows with it, still capped.
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
        # The window may have been closed on a larger display or at a different scale: keep it on-screen after restore
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