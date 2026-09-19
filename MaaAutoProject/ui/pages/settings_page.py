import os
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QPushButton,
    QLineEdit, QSlider,
    QFileDialog, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, Signal, QTime

from ui.components import (SettingItem, SettingGroup, Switch, SegmentedControl,
                           AccentColorPicker)
from ui.pages.process_picker import ProcessPickerDialog
from ui.no_wheel import NoWheelComboBox, IntLineEdit
from ui.wheel_time_picker import WheelTimePicker
from notifier import send_webhook, HAS_SERVERCHAN
from utils import AsyncWorker

if HAS_SERVERCHAN:
    from serverchan_sdk import sc_send
else:
    sc_send = None

logger = logging.getLogger("MaaAuto")


class SettingsPage(QWidget):
    """设置页：单页滚动式分组 + 顶部跳转 chips + 视口高亮。"""

    config_changed = Signal(dict)
    theme_changed = Signal(str)
    language_changed = Signal(str)
    accent_changed = Signal(str)

    def __init__(self, config, i18n, theme_manager, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.i18n = i18n
        self.theme_manager = theme_manager

        self._groups = {}
        self._jump_chips = []
        self._items = []
        self._switches = []
        self._seg_controls = []

        self._active_chip_key = None

        # 网络测试线程句柄（防止被 GC）
        self._sc_test_worker = None
        self._wh_test_worker = None

        self._theme_keys = [
            "settings.theme.light",
            "settings.theme.dark",
            "settings.theme.system",
        ]
        self._bg_mode_keys = [
            "settings.background.mode.cover",
            "settings.background.mode.contain",
            "settings.background.mode.stretch",
            "settings.background.mode.tile",
        ]
        self._bg_mode_values = ["cover", "contain", "stretch", "tile"]

        self._setup_ui()
        self._connect_auto_save()

        self.scroll.verticalScrollBar().valueChanged.connect(self._update_active_chip)

    # ==================================================================
    # 构建 UI
    # ==================================================================
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        hl = QVBoxLayout(header)
        hl.setContentsMargins(28, 24, 28, 8)
        hl.setSpacing(10)

        self.page_title = QLabel(self.i18n.t("settings.title"))
        self.page_title.setObjectName("PageTitle")
        hl.addWidget(self.page_title)

        self.jump_bar = QHBoxLayout()
        self.jump_bar.setSpacing(6)
        hl.addLayout(self.jump_bar)

        root.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        container.setObjectName("SettingsContainer")
        container.setAttribute(Qt.WA_StyledBackground, True)
        container.setAutoFillBackground(False)
        self.scroll.setWidget(container)

        self.vbox = QVBoxLayout(container)
        self.vbox.setContentsMargins(28, 18, 28, 28)
        self.vbox.setSpacing(18)

        root.addWidget(self.scroll, 1)

        self._build_groups()
        self.vbox.addStretch()
        self.vbox.addSpacing(40)

        self.scroll.verticalScrollBar().setValue(0)

    # ------------------------------------------------------------------
    def _new_group(self, group_key):
        title = self.i18n.t(f"settings.group.{group_key}")
        group = SettingGroup(title)
        self.vbox.addWidget(group)
        self._groups[group_key] = group

        chip = QPushButton(title)
        chip.setObjectName("JumpChip")
        chip.setCursor(Qt.PointingHandCursor)
        chip.setCheckable(True)
        chip.clicked.connect(lambda _, w=group: self._scroll_to(w))
        self.jump_bar.addWidget(chip)
        self._jump_chips.append((chip, f"settings.group.{group_key}", group))

        return group

    def _add_item(self, group, title_key, desc_key, widget):
        title = self.i18n.t(title_key)
        desc = self.i18n.t(desc_key) if desc_key else ""
        item = SettingItem(title, desc, widget)
        group.add_item(item)
        self._items.append((item, title_key, desc_key))
        return item

    def _add_switch(self, group, title_key, desc_key, config_key, default=False):
        sw = Switch()
        sw.setCheckedSilently(self.config.get(config_key, default))
        self._switches.append((sw, config_key))
        self._add_item(group, title_key, desc_key, sw)
        return sw

    @staticmethod
    def _make_spin(minimum, maximum, value):
        return IntLineEdit(minimum, maximum, value)

    def _wrap_browse(self, line_edit, btn_attr="_browse_btn"):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(line_edit)

        btn = QPushButton(self.i18n.t("settings.browse"))
        btn.setObjectName("GhostButton")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._browse_exe(line_edit))
        lay.addWidget(btn)

        setattr(line_edit, btn_attr, btn)
        return w

    def _scroll_to(self, widget):
        y = widget.mapTo(self.scroll.widget(), widget.rect().topLeft()).y()
        self.scroll.verticalScrollBar().setValue(max(0, y - 16))

    def _update_active_chip(self, *_):
        if not self._groups:
            return
        current_y = self.scroll.verticalScrollBar().value()
        best_key = None
        best_delta = None
        for key, group in self._groups.items():
            gy = group.mapTo(self.scroll.widget(), group.rect().topLeft()).y()
            delta = abs(gy - current_y - 8)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_key = key

        if self._active_chip_key == best_key:
            return
        self._active_chip_key = best_key
        for chip, _key, group in self._jump_chips:
            chip.setChecked(self._groups.get(best_key) is group)

    # ------------------------------------------------------------------
    # 分组
    # ------------------------------------------------------------------
    def _build_groups(self):
        g = self._new_group("paths")
        self.maa_path_edit = QLineEdit(self.config.get("maa_path", ""))
        self._add_item(g, "settings.maa_path", "settings.maa_path.desc",
                       self._wrap_browse(self.maa_path_edit))
        self.maaend_path_edit = QLineEdit(self.config.get("maaend_path", ""))
        self._add_item(g, "settings.maaend_path", "settings.maaend_path.desc",
                       self._wrap_browse(self.maaend_path_edit))

        g = self._new_group("process")
        self.emulator_edit = QLineEdit(self.config.get("emulator_proc", "MuMuPlayer.exe"))
        self._add_item(g, "settings.emulator_proc", "settings.emulator_proc.desc",
                       self.emulator_edit)
        self.pc_game_edit = QLineEdit(self.config.get("pc_game_proc", "Endfield.exe"))
        self._add_item(g, "settings.pc_game_proc", "settings.pc_game_proc.desc",
                       self.pc_game_edit)
        self.wait_timeout_spin = self._make_spin(10, 300, self.config.get("wait_timeout", 60))
        self._add_item(g, "settings.wait_timeout", "settings.wait_timeout.desc",
                       self.wait_timeout_spin)
        self.game_start_spin = self._make_spin(30, 600, self.config.get("game_start_timeout", 120))
        self._add_item(g, "settings.game_start_timeout", "settings.game_start_timeout.desc",
                       self.game_start_spin)
        self.game_exit_spin = self._make_spin(300, 14400, self.config.get("game_exit_timeout", 7200))
        self._add_item(g, "settings.game_exit_timeout", "settings.game_exit_timeout.desc",
                       self.game_exit_spin)
        self.retry_times_spin = self._make_spin(1, 10, self.config.get("retry_times", 3))
        self._add_item(g, "settings.retry_times", "settings.retry_times.desc",
                       self.retry_times_spin)
        self.retry_interval_spin = self._make_spin(5, 300, self.config.get("retry_interval", 30))
        self._add_item(g, "settings.retry_interval", "settings.retry_interval.desc",
                       self.retry_interval_spin)

        g = self._new_group("foreground")
        self.fg_seg = SegmentedControl(
            items=[
                ("settings.foreground_action.none", "none"),
                ("settings.foreground_action.kill_all", "kill_all"),
                ("settings.foreground_action.blacklist", "blacklist"),
            ],
            i18n=self.i18n,
        )
        current_action = self.config.get("foreground_action", "none")
        self.fg_seg.set_current_value(current_action)
        self._add_item(g, "settings.foreground_action", None, self.fg_seg)

        self.blacklist_edit = QLineEdit(self.config.get("blacklist_apps", ""))
        self.blacklist_edit.setPlaceholderText(self.i18n.t("settings.blacklist_apps.desc"))
        self.blacklist_edit.setMinimumWidth(220)
        bl_wrap = QWidget()
        bl_layout = QHBoxLayout(bl_wrap)
        bl_layout.setContentsMargins(0, 0, 0, 0)
        bl_layout.setSpacing(6)
        bl_layout.addWidget(self.blacklist_edit)
        self.btn_pick_process = QPushButton(self.i18n.t("settings.blacklist_apps.pick"))
        self.btn_pick_process.setObjectName("GhostButton")
        self.btn_pick_process.setCursor(Qt.PointingHandCursor)
        self.btn_pick_process.clicked.connect(self._open_process_picker)
        bl_layout.addWidget(self.btn_pick_process)
        self._add_item(g, "settings.blacklist_apps", "settings.blacklist_apps.desc", bl_wrap)

        g = self._new_group("schedule")
        self.enable_schedule_cb = self._add_switch(g, "settings.enable_schedule", None,
                                                  "enable_schedule", False)
        self.sys_notify_sw = self._add_switch(g, "settings.enable_system_notify",
                                             "settings.enable_system_notify.desc",
                                             "enable_system_notify", True)
        self.time_edit = WheelTimePicker()
        self.time_edit.setTime(QTime.fromString(self.config.get("execute_time", "08:00"), "HH:mm"))
        self._add_item(g, "settings.execute_time", None, self.time_edit)

        self.sc_edit = QLineEdit(self.config.get("serverchan_key", ""))
        self.sc_edit.setEchoMode(QLineEdit.Password)
        self.sc_edit.setMinimumWidth(220)
        sc_wrap = QWidget()
        sc_l = QHBoxLayout(sc_wrap)
        sc_l.setContentsMargins(0, 0, 0, 0)
        sc_l.setSpacing(6)
        sc_l.addWidget(self.sc_edit)
        self.btn_sc_test = QPushButton(self.i18n.t("settings.test"))
        self.btn_sc_test.setObjectName("GhostButton")
        self.btn_sc_test.setCursor(Qt.PointingHandCursor)
        self.btn_sc_test.clicked.connect(self.test_serverchan)
        sc_l.addWidget(self.btn_sc_test)
        self._add_item(g, "settings.serverchan_key", None, sc_wrap)

        self.webhook_edit = QLineEdit(self.config.get("webhook_url", ""))
        self.webhook_edit.setPlaceholderText(self.i18n.t("settings.webhook_url.desc"))
        self.webhook_edit.setMinimumWidth(220)
        wh_wrap = QWidget()
        wh_l = QHBoxLayout(wh_wrap)
        wh_l.setContentsMargins(0, 0, 0, 0)
        wh_l.setSpacing(6)
        wh_l.addWidget(self.webhook_edit)
        self.btn_wh_test = QPushButton(self.i18n.t("settings.test"))
        self.btn_wh_test.setObjectName("GhostButton")
        self.btn_wh_test.setCursor(Qt.PointingHandCursor)
        self.btn_wh_test.clicked.connect(self.test_webhook)
        wh_l.addWidget(self.btn_wh_test)
        self._add_item(g, "settings.webhook_url", "settings.webhook_url.desc", wh_wrap)

        g = self._new_group("appearance")
        self.theme_combo = NoWheelComboBox()
        for key in self._theme_keys:
            self.theme_combo.addItem(self.i18n.t(key), key)
        cur_theme = self.config.get("theme", "system")
        idx = self.theme_combo.findData(f"settings.theme.{cur_theme}")
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.setMinimumWidth(160)
        self._add_item(g, "settings.theme", None, self.theme_combo)

        self.accent_picker = AccentColorPicker(self.i18n)
        self.accent_picker.set_color(self.config.get("accent_color", "#3b82f6"))
        self.accent_picker.colorChanged.connect(self._on_accent_changed)
        self._add_item(g, "settings.accent_color", "settings.accent_color.desc",
                       self.accent_picker)

        self.lang_combo = NoWheelComboBox()
        for code, name in self.i18n.available_languages():
            self.lang_combo.addItem(name, code)
        idx = self.lang_combo.findData(self.i18n.current_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.setMinimumWidth(160)
        self._add_item(g, "settings.language", None, self.lang_combo)

        self.bg_edit = QLineEdit(self.config.get("background_image", ""))
        self.bg_edit.setMinimumWidth(200)
        bg_wrap = QWidget()
        bg_l = QHBoxLayout(bg_wrap)
        bg_l.setContentsMargins(0, 0, 0, 0)
        bg_l.setSpacing(6)
        bg_l.addWidget(self.bg_edit)
        self.btn_bg_pick = QPushButton(self.i18n.t("settings.browse"))
        self.btn_bg_pick.setObjectName("GhostButton")
        self.btn_bg_pick.setCursor(Qt.PointingHandCursor)
        self.btn_bg_pick.clicked.connect(self._pick_background)
        bg_l.addWidget(self.btn_bg_pick)
        self.btn_bg_clear = QPushButton(self.i18n.t("settings.background.clear"))
        self.btn_bg_clear.setObjectName("GhostButton")
        self.btn_bg_clear.setCursor(Qt.PointingHandCursor)
        self.btn_bg_clear.clicked.connect(self._clear_background)
        bg_l.addWidget(self.btn_bg_clear)
        self._add_item(g, "settings.background", "settings.background.desc", bg_wrap)

        self.bg_opacity_slider = QSlider(Qt.Horizontal)
        self.bg_opacity_slider.setRange(0, 100)
        self.bg_opacity_slider.setFixedWidth(220)
        self.bg_opacity_slider.setValue(int(self.config.get("background_opacity", 0.3) * 100))
        self._add_item(g, "settings.background.opacity", None, self.bg_opacity_slider)

        self.bg_blur_spin = self._make_spin(0, 60, int(self.config.get("background_blur", 0)))
        self._add_item(g, "settings.background.blur", None, self.bg_blur_spin)

        self.bg_mode_combo = NoWheelComboBox()
        for key, val in zip(self._bg_mode_keys, self._bg_mode_values):
            self.bg_mode_combo.addItem(self.i18n.t(key), val)
        idx = self.bg_mode_combo.findData(self.config.get("background_mode", "cover"))
        if idx >= 0:
            self.bg_mode_combo.setCurrentIndex(idx)
        self.bg_mode_combo.setMinimumWidth(160)
        self._add_item(g, "settings.background.mode", None, self.bg_mode_combo)

        self.anim_sw = self._add_switch(g, "settings.show_animation", None,
                                       "show_animation", True)

        g = self._new_group("general")
        self.auto_start_sw = self._add_switch(g, "settings.auto_start", None,
                                             "auto_start", False)
        self.tray_sw = self._add_switch(g, "settings.minimize_to_tray", None,
                                       "minimize_to_tray", True)
        self.kill_sw = self._add_switch(g, "settings.kill_on_exit", None,
                                       "kill_on_exit", True)
        self.auto_check_update_sw = self._add_switch(
            g, "settings.auto_check_update", None, "auto_check_update", True)
        self.auto_download_update_sw = self._add_switch(
            g, "settings.auto_download_update",
            "settings.auto_download_update.desc", "auto_download_update", False)

    # ==================================================================
    # 自动保存
    # ==================================================================
    def _connect_auto_save(self):
        def emit_config(*_):
            self.config_changed.emit(self.get_config())

        for w in (self.maa_path_edit, self.maaend_path_edit, self.emulator_edit,
                  self.pc_game_edit, self.blacklist_edit, self.sc_edit,
                  self.webhook_edit, self.bg_edit):
            w.textChanged.connect(emit_config)
        for w in (self.wait_timeout_spin, self.game_start_spin, self.game_exit_spin,
                  self.retry_times_spin, self.retry_interval_spin, self.bg_blur_spin):
            w.valueChanged.connect(emit_config)
        for sw, _key in self._switches:
            sw.toggled.connect(emit_config)
        self.time_edit.timeChanged.connect(emit_config)
        self.fg_seg.selection_changed.connect(emit_config)
        self.bg_opacity_slider.valueChanged.connect(emit_config)
        self.bg_mode_combo.currentIndexChanged.connect(emit_config)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)

    def _on_theme_changed(self, *_):
        key = self.theme_combo.currentData()
        if not key:
            return
        theme = key.split(".")[-1]
        self.config["theme"] = theme
        self.theme_changed.emit(theme)

    def _on_lang_changed(self, *_):
        code = self.lang_combo.currentData()
        if not code:
            return
        self.config["language"] = code
        self.language_changed.emit(code)

    def _on_accent_changed(self, hexv):
        self.config["accent_color"] = hexv
        self.accent_changed.emit(hexv)

    # ==================================================================
    # 交互
    # ==================================================================
    def _browse_exe(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(
            self, self.i18n.t("settings.browse"), "",
            "Executable (*.exe);;All Files (*)")
        if path:
            line_edit.setText(path)

    def _pick_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.i18n.t("settings.background"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.bg_edit.setText(path)

    def _clear_background(self):
        self.bg_edit.setText("")

    def _open_process_picker(self):
        dlg = ProcessPickerDialog(self.i18n, self.blacklist_edit.text(), self)
        if dlg.exec():
            names = dlg.get_selection()
            self.blacklist_edit.setText(",".join(names))

    # ==================================================================
    # 测试推送 —— 全部改为后台线程，绝不阻塞 UI
    # ==================================================================
    def test_serverchan(self):
        if not HAS_SERVERCHAN:
            QMessageBox.warning(
                self, self.i18n.t("common.warning"),
                "未加载 serverchan_sdk，无法测试 Server 酱推送。\n\n"
                "请检查安装包是否完整（重装一次），或改用通用 Webhook。")
            return

        key = self.sc_edit.text().strip()
        if not key:
            QMessageBox.warning(self, self.i18n.t("common.warning"),
                                self.i18n.t("serverchan.test.empty_key"))
            return

        # 禁用按钮 + 提示
        self.btn_sc_test.setEnabled(False)
        self.btn_sc_test.setText(self.i18n.t("about.check_update.checking"))

        # 后台线程调用 sc_send
        self._sc_test_worker = AsyncWorker(
            sc_send, key, "MaaAuto Test", "Test message", {"tags": "test"})
        self._sc_test_worker.finished.connect(self._on_sc_test_done)
        self._sc_test_worker.error.connect(self._on_sc_test_error)
        self._sc_test_worker.start()

    def _on_sc_test_done(self, res):
        self.btn_sc_test.setEnabled(True)
        self.btn_sc_test.setText(self.i18n.t("settings.test"))
        logger.info(f"Server酱测试响应: {res}")

        ok = False
        if isinstance(res, dict):
            code = res.get("code")
            msg = str(res.get("message", "")).upper()
            ok = (code == 0) or (msg == "SUCCESS")

        if ok:
            QMessageBox.information(self, self.i18n.t("common.success"),
                                    self.i18n.t("serverchan.test.success"))
        else:
            QMessageBox.warning(
                self, self.i18n.t("common.warning"),
                f"{self.i18n.t('serverchan.test.failed')}\n\n{res}")

    def _on_sc_test_error(self, err_msg):
        self.btn_sc_test.setEnabled(True)
        self.btn_sc_test.setText(self.i18n.t("settings.test"))
        QMessageBox.critical(self, self.i18n.t("common.error"), err_msg)

    def test_webhook(self):
        url = self.webhook_edit.text().strip()
        if not url:
            QMessageBox.warning(self, self.i18n.t("common.warning"),
                                self.i18n.t("settings.webhook_url"))
            return

        self.btn_wh_test.setEnabled(False)
        self.btn_wh_test.setText(self.i18n.t("about.check_update.checking"))

        self._wh_test_worker = AsyncWorker(
            send_webhook, url, "MaaAuto Test", "Test message")
        self._wh_test_worker.finished.connect(self._on_wh_test_done)
        self._wh_test_worker.error.connect(self._on_wh_test_error)
        self._wh_test_worker.start()

    def _on_wh_test_done(self, _):
        self.btn_wh_test.setEnabled(True)
        self.btn_wh_test.setText(self.i18n.t("settings.test"))
        QMessageBox.information(self, self.i18n.t("common.success"),
                                self.i18n.t("common.success"))

    def _on_wh_test_error(self, err_msg):
        self.btn_wh_test.setEnabled(True)
        self.btn_wh_test.setText(self.i18n.t("settings.test"))
        QMessageBox.critical(self, self.i18n.t("common.error"), err_msg)

    # ==================================================================
    # 读取配置
    # ==================================================================
    def get_config(self):
        c = self.config
        c["maa_path"] = self.maa_path_edit.text().strip()
        c["maaend_path"] = self.maaend_path_edit.text().strip()
        c["emulator_proc"] = self.emulator_edit.text().strip() or "MuMuPlayer.exe"
        c["pc_game_proc"] = self.pc_game_edit.text().strip() or "Endfield.exe"
        c["wait_timeout"] = self.wait_timeout_spin.value()
        c["game_start_timeout"] = self.game_start_spin.value()
        c["game_exit_timeout"] = self.game_exit_spin.value()
        c["retry_times"] = self.retry_times_spin.value()
        c["retry_interval"] = self.retry_interval_spin.value()
        c["execute_time"] = self.time_edit.time().toString("HH:mm")
        c["serverchan_key"] = self.sc_edit.text().strip()
        c["webhook_url"] = self.webhook_edit.text().strip()
        c["blacklist_apps"] = self.blacklist_edit.text()
        c["background_image"] = self.bg_edit.text().strip()
        c["background_opacity"] = self.bg_opacity_slider.value() / 100.0
        c["background_blur"] = self.bg_blur_spin.value()
        c["background_mode"] = self.bg_mode_combo.currentData() or "cover"
        c["theme"] = (self.theme_combo.currentData() or "settings.theme.system").split(".")[-1]
        c["language"] = self.lang_combo.currentData() or "zh_CN"
        c["accent_color"] = self.accent_picker.color()
        for sw, key in self._switches:
            c[key] = sw.isChecked()
        c["foreground_action"] = self.fg_seg.current_value() or "none"
        return c

    # ==================================================================
    # 语言切换
    # ==================================================================
    def retranslate(self):
        self.page_title.setText(self.i18n.t("settings.title"))
        for group_key, group in self._groups.items():
            group.set_title(self.i18n.t(f"settings.group.{group_key}"))
        for chip, key, _group in self._jump_chips:
            chip.setText(self.i18n.t(key))
        for item, title_key, desc_key in self._items:
            item.set_title(self.i18n.t(title_key))
            if desc_key:
                item.set_description(self.i18n.t(desc_key))

        self.theme_combo.blockSignals(True)
        for i, key in enumerate(self._theme_keys):
            if i < self.theme_combo.count():
                self.theme_combo.setItemText(i, self.i18n.t(key))
        self.theme_combo.blockSignals(False)

        self.bg_mode_combo.blockSignals(True)
        for i, key in enumerate(self._bg_mode_keys):
            if i < self.bg_mode_combo.count():
                self.bg_mode_combo.setItemText(i, self.i18n.t(key))
        self.bg_mode_combo.blockSignals(False)

        self.lang_combo.blockSignals(True)
        for i, (_code, name) in enumerate(self.i18n.available_languages()):
            if i < self.lang_combo.count():
                self.lang_combo.setItemText(i, name)
        self.lang_combo.blockSignals(False)

        for le in (self.maa_path_edit, self.maaend_path_edit):
            btn = getattr(le, "_browse_btn", None)
            if btn is not None:
                btn.setText(self.i18n.t("settings.browse"))
        self.btn_bg_pick.setText(self.i18n.t("settings.browse"))
        self.btn_bg_clear.setText(self.i18n.t("settings.background.clear"))
        self.btn_pick_process.setText(self.i18n.t("settings.blacklist_apps.pick"))
        self.btn_sc_test.setText(self.i18n.t("settings.test"))
        self.btn_wh_test.setText(self.i18n.t("settings.test"))
        self.fg_seg.retranslate()
        self.accent_picker.retranslate()
        self.blacklist_edit.setPlaceholderText(self.i18n.t("settings.blacklist_apps.desc"))
        self.webhook_edit.setPlaceholderText(self.i18n.t("settings.webhook_url.desc"))