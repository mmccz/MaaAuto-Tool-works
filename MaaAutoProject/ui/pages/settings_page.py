import logging
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QPushButton,
    QLineEdit, QSlider,
    QFileDialog, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, Signal, QTime, QTimer

from ui.components import (SettingItem, SettingGroup, Switch, SegmentedControl,
                           AccentColorPicker)
from ui.pages.process_picker import ProcessPickerDialog
from ui.no_wheel import NoWheelComboBox, IntLineEdit
from ui.flow_layout import FlowLayout
from ui.schedule_editor import ScheduleEditor
from ui.wheel_time_picker import WheelTimePicker
from notifier import send_webhook, HAS_SERVERCHAN
from utils import AsyncWorker

if HAS_SERVERCHAN:
    from serverchan_sdk import sc_send
else:
    sc_send = None

logger = logging.getLogger("MaaAuto")


def _match_test_worker(cfg):
    """后台线程：按当前配置截屏匹配一次（只找不点）。

    返回 ``[{"name":…, "match":Match|None, "source":…, "size":…, "error":…}]``。
    放模块级、不碰 Qt 控件，是因为跨线程访问界面对象正是「升级器 0xC0000005
    崩溃」的成因。
    """
    import vision
    import automation

    results = []
    threshold = float(cfg.get("match_threshold", 0.80))
    scale_min = float(cfg.get("match_scale_min", 0.60))
    scale_max = float(cfg.get("match_scale_max", 2.00))
    user_dir = automation._user_template_dir(cfg)

    for name in ("maa_start.png", "maaend_start.png"):
        paths = automation.template_paths(name, cfg)
        if not paths:
            results.append({"name": name, "match": None, "source": "缺失",
                            "size": "", "error": "缺少模板文件"})
            continue
        path = paths[0]
        source = "用户模板" if os.path.dirname(path) == os.path.normpath(user_dir) \
            else "内置模板"
        size = ""
        try:
            from PIL import Image
            with Image.open(path) as im:
                size = f"{im.width}×{im.height}"
        except Exception:
            pass
        # 1.4.5：先把 MAA / MaaEnd 窗口弄到最前面再截屏。
        # 旧实现直接抓全屏 —— 用户点「测试找图」时 MaaAuto 的窗口正压在目标
        # 上面，截到的全是自己的界面，于是永远「未命中」。
        proc = automation.template_process(name, cfg)
        if proc:
            try:
                from process_utils import bring_process_to_front, interruptible_sleep
                if bring_process_to_front([proc]):
                    interruptible_sleep(0.8)
            except Exception as e:
                logger.warning(f"把 {proc} 窗口前置失败: {e}")
        try:
            match = vision.find_any(paths, region=None, threshold=threshold,
                                    scale_min=scale_min, scale_max=scale_max)
            results.append({"name": name, "match": match, "source": source,
                            "size": size, "error": None, "process": proc})
        except Exception as e:
            results.append({"name": name, "match": None, "source": source,
                            "size": size, "error": f"异常: {e}", "process": proc})
    return results


class SettingsPage(QWidget):
    """设置页：单页滚动式分组 + 顶部跳转 chips + 视口高亮。"""

    config_changed = Signal(dict)
    theme_changed = Signal(str)
    language_changed = Signal(str)
    accent_changed = Signal(str)
    # 界面缩放单独走一条信号：主窗口要「即时重绘」，而不是只存配置等重启
    ui_scale_changed = Signal(float)
    restart_requested = Signal()

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
        self.apply_ui_scale(self.config.get("ui_scale", 1.0))

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

        self.jump_widget = QWidget()
        self.jump_bar = FlowLayout(self.jump_widget, margin=0,
                                   h_spacing=6, v_spacing=6)
        hl.addWidget(self.jump_widget)

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
        self.min_emu_runtime_spin = self._make_spin(
            0, 600, int(self.config.get("min_emulator_runtime", 60)))
        self._add_item(g, "settings.min_emulator_runtime",
                       "settings.min_emulator_runtime.desc", self.min_emu_runtime_spin)

        g = self._new_group("vision")
        self._build_vision_group(g)

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
        self.schedule_editor = ScheduleEditor(
            self.i18n,
            times=self.config.get("schedule_times") or [self.config.get("execute_time", "08:00")],
            weekdays=self.config.get("schedule_weekdays") or [])
        self._add_item(g, "settings.schedule.times",
                       "settings.schedule.times.desc", self.schedule_editor)

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

        # 背景模糊：0~60px。和透明度一样用滑杆（数值小的控件用输入框很难拖准）
        blur_row = QWidget()
        blur_lay = QHBoxLayout(blur_row)
        blur_lay.setContentsMargins(0, 0, 0, 0)
        blur_lay.setSpacing(8)
        self.bg_blur_slider = QSlider(Qt.Horizontal)
        self.bg_blur_slider.setRange(0, 60)
        self.bg_blur_slider.setFixedWidth(220)
        self.bg_blur_slider.setValue(int(self.config.get("background_blur", 0)))
        self.bg_blur_slider.valueChanged.connect(self._on_bg_blur_changed)
        blur_lay.addWidget(self.bg_blur_slider)
        self.bg_blur_value = QLabel(str(self.bg_blur_slider.value()))
        self.bg_blur_value.setObjectName("SettingDesc")
        self.bg_blur_value.setFixedWidth(28)
        self.bg_blur_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        blur_lay.addWidget(self.bg_blur_value)
        self._add_item(g, "settings.background.blur", None, blur_row)

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

        self._ui_scale_values = (1.0, 1.25, 1.5)
        self.ui_scale_combo = NoWheelComboBox()
        for val in self._ui_scale_values:
            self.ui_scale_combo.addItem(f"{int(round(val * 100))}%", val)
        idx = self.ui_scale_combo.findData(
            float(self.config.get("ui_scale", 1.0)))
        if idx < 0:
            idx = 0
        self.ui_scale_combo.setCurrentIndex(idx)
        self.ui_scale_combo.setMinimumWidth(120)

        # 缩放旁边常驻一个「重启程序」——切换比例后即时生效，但窗口结构
        # （侧栏宽度、日志字号、滚动位置）要靠重启按新比例完整重建。
        # 1.0.4 既没有即时生效，也没有这个入口，实测就是「什么都没出现」。
        scale_row = QWidget()
        sr = QHBoxLayout(scale_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(6)
        sr.addWidget(self.ui_scale_combo)
        self.btn_restart = QPushButton(self.i18n.t("settings.ui_scale.restart"))
        self.btn_restart.setObjectName("GhostButton")
        self.btn_restart.setCursor(Qt.PointingHandCursor)
        self.btn_restart.setToolTip(self.i18n.t("settings.ui_scale.restart.tip"))
        self.btn_restart.clicked.connect(self.restart_requested)
        sr.addWidget(self.btn_restart)

        self._add_item(g, "settings.ui_scale", "settings.ui_scale.desc", scale_row)

        g = self._new_group("general")
        self.auto_start_sw = self._add_switch(g, "settings.auto_start", None,
                                             "auto_start", False)
        self.tray_sw = self._add_switch(g, "settings.minimize_to_tray", None,
                                       "minimize_to_tray", True)
        self.kill_sw = self._add_switch(g, "settings.kill_on_exit", None,
                                       "kill_on_exit", True)
        self.log_retention_spin = self._make_spin(
            0, 3650, int(self.config.get("log_retention_days", 90) or 0))
        self._add_item(g, "settings.log_retention_days",
                       "settings.log_retention_days.desc", self.log_retention_spin)
        self.auto_check_update_sw = self._add_switch(
            g, "settings.auto_check_update", None, "auto_check_update", True)
        self.auto_download_update_sw = self._add_switch(
            g, "settings.auto_download_update",
            "settings.auto_download_update.desc", "auto_download_update", False)

        self._channel_values = ("stable", "beta")
        self.channel_combo = NoWheelComboBox()
        for val in self._channel_values:
            self.channel_combo.addItem(
                self.i18n.t(f"settings.update_channel.{val}"), val)
        idx = self.channel_combo.findData(self.config.get("update_channel", "stable"))
        if idx >= 0:
            self.channel_combo.setCurrentIndex(idx)
        self.channel_combo.setMinimumWidth(160)
        self._add_item(g, "settings.update_channel",
                       "settings.update_channel.desc", self.channel_combo)

    # ------------------------------------------------------------------
    # 找图与点击
    #
    # 1.0.x 的找图是「全屏 + 固定尺寸」匹配：模板在 125% / 150% 缩放下比屏幕上的
    # 按钮小一圈，于是频繁超时。这一组参数把匹配范围、相似度、缩放搜索区间
    # 和点击方式都暴露出来，用户换机器/换缩放后不用等发版也能自己校准。
    # ------------------------------------------------------------------
    def _build_vision_group(self, g):
        self.scope_seg = SegmentedControl(
            items=[("settings.search_scope.window", "window"),
                   ("settings.search_scope.screen", "screen")],
            i18n=self.i18n,
        )
        self.scope_seg.set_current_value(self.config.get("search_scope", "window"))
        self._add_item(g, "settings.search_scope", "settings.search_scope.desc",
                       self.scope_seg)

        self.threshold_spin = self._make_spin(
            50, 99, int(round(float(self.config.get("match_threshold", 0.80)) * 100)))
        self._add_item(g, "settings.match_threshold",
                       "settings.match_threshold.desc", self.threshold_spin)

        scales = QWidget()
        sl = QHBoxLayout(scales)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        self.scale_min_spin = self._make_spin(
            30, 200, int(round(float(self.config.get("match_scale_min", 0.60)) * 100)))
        self.scale_max_spin = self._make_spin(
            30, 400, int(round(float(self.config.get("match_scale_max", 2.00)) * 100)))
        sl.addWidget(self.scale_min_spin)
        sl.addWidget(QLabel("% ~"))
        sl.addWidget(self.scale_max_spin)
        sl.addWidget(QLabel("%"))
        self._add_item(g, "settings.match_scale", "settings.match_scale.desc", scales)

        self._click_mode_values = ("sendinput", "postmessage")
        self.click_mode_combo = NoWheelComboBox()
        for val in self._click_mode_values:
            self.click_mode_combo.addItem(
                self.i18n.t(f"settings.click_mode.{val}"), val)
        idx = self.click_mode_combo.findData(
            self.config.get("click_mode", "sendinput"))
        if idx >= 0:
            self.click_mode_combo.setCurrentIndex(idx)
        self.click_mode_combo.setMinimumWidth(180)
        self._add_item(g, "settings.click_mode", "settings.click_mode.desc",
                       self.click_mode_combo)

        self.click_activate_sw = self._add_switch(
            g, "settings.click_activate", "settings.click_activate.desc",
            "click_activate", True)
        self.click_restore_sw = self._add_switch(
            g, "settings.click_restore_cursor",
            "settings.click_restore_cursor.desc", "click_restore_cursor", True)

        self.click_verify_sw = self._add_switch(
            g, "settings.click_verify", "settings.click_verify.desc",
            "click_verify", True)

        self.minimize_on_task_sw = self._add_switch(
            g, "settings.minimize_on_task", "settings.minimize_on_task.desc",
            "minimize_on_task", True)

        offsets = QWidget()
        ol = QHBoxLayout(offsets)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(6)
        self.offset_x_spin = self._make_spin(
            -200, 200, int(self.config.get("click_offset_x", 0)))
        self.offset_y_spin = self._make_spin(
            -200, 200, int(self.config.get("click_offset_y", 0)))
        ol.addWidget(QLabel("X"))
        ol.addWidget(self.offset_x_spin)
        ol.addWidget(QLabel("Y"))
        ol.addWidget(self.offset_y_spin)
        self._add_item(g, "settings.click_offset", "settings.click_offset.desc",
                       offsets)

        self.template_dir_edit = QLineEdit(self.config.get("template_dir", ""))
        self.template_dir_edit.setPlaceholderText(
            self.i18n.t("settings.template_dir.desc"))
        self.template_dir_edit.setMinimumWidth(160)
        td_wrap = QWidget()
        td_l = QHBoxLayout(td_wrap)
        td_l.setContentsMargins(0, 0, 0, 0)
        td_l.setSpacing(6)
        td_l.addWidget(self.template_dir_edit)
        self.btn_template_browse = QPushButton(self.i18n.t("settings.browse"))
        self.btn_template_browse.setObjectName("GhostButton")
        self.btn_template_browse.setCursor(Qt.PointingHandCursor)
        self.btn_template_browse.clicked.connect(self._browse_template_dir)
        td_l.addWidget(self.btn_template_browse)
        self._add_item(g, "settings.template_dir", "settings.template_dir.desc",
                       td_wrap)

        actions = QWidget()
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        self.btn_capture_template = QPushButton(
            self.i18n.t("settings.template_capture"))
        self.btn_capture_template.setObjectName("GhostButton")
        self.btn_capture_template.setCursor(Qt.PointingHandCursor)
        self.btn_capture_template.clicked.connect(self._open_template_capture)
        al.addWidget(self.btn_capture_template)
        self.btn_test_match = QPushButton(self.i18n.t("settings.match_test"))
        self.btn_test_match.setObjectName("GhostButton")
        self.btn_test_match.setCursor(Qt.PointingHandCursor)
        self.btn_test_match.clicked.connect(self._run_match_test)
        al.addWidget(self.btn_test_match)
        self._add_item(g, "settings.template_capture", "settings.template_capture.desc",
                       actions)

    # ==================================================================
    # 界面缩放（自绘控件）
    # ==================================================================
    def apply_ui_scale(self, scale):
        """把界面缩放同步给 QSS 管不到的自绘控件。

        QSS 只能重写 ``font-size``；Switch / 强调色色块 / 滚轮时间都是固定
        像素尺寸，不跟着缩放就会在 150% 下显得又小又挤（开关 44×24 配 20px 字）。
        """
        try:
            scale = max(0.75, min(2.0, float(scale)))
        except (TypeError, ValueError):
            scale = 1.0
        for sw, _key in self._switches:
            try:
                sw.set_ui_scale(scale)
            except Exception as e:
                logger.warning(f"缩放开关尺寸失败: {e}")
        for widget in (self.schedule_editor, self.accent_picker):
            try:
                widget.set_ui_scale(scale)
            except Exception as e:
                logger.warning(f"缩放控件尺寸失败: {e}")

    # ==================================================================
    # 自动保存
    # ==================================================================
    def _connect_auto_save(self):
        def emit_config(*_):
            self.config_changed.emit(self.get_config())

        for w in (self.maa_path_edit, self.maaend_path_edit, self.emulator_edit,
                  self.pc_game_edit, self.blacklist_edit, self.sc_edit,
                  self.webhook_edit, self.bg_edit, self.template_dir_edit):
            w.textChanged.connect(emit_config)
        for w in (self.wait_timeout_spin, self.game_start_spin, self.game_exit_spin,
                  self.retry_times_spin, self.retry_interval_spin,
                  self.threshold_spin, self.scale_min_spin, self.scale_max_spin,
                  self.offset_x_spin, self.offset_y_spin, self.min_emu_runtime_spin,
                  self.log_retention_spin):
            w.valueChanged.connect(emit_config)
        for sw, _key in self._switches:
            sw.toggled.connect(emit_config)
        self.schedule_editor.changed.connect(emit_config)
        self.channel_combo.currentIndexChanged.connect(emit_config)
        self.fg_seg.selection_changed.connect(emit_config)
        self.scope_seg.selection_changed.connect(emit_config)
        self.click_mode_combo.currentIndexChanged.connect(emit_config)
        self.ui_scale_combo.currentIndexChanged.connect(self._on_ui_scale_changed)
        # 滑条拖动会连续发 valueChanged；原来每一格都触发「整图高斯模糊 + 写配置」，
        # 表现为拖动很卡。这里改成：文字实时更新，重绘/落盘防抖 180ms，松手立刻生效。
        self._bg_apply_timer = QTimer(self)
        self._bg_apply_timer.setSingleShot(True)
        self._bg_apply_timer.setInterval(180)
        self._bg_apply_timer.timeout.connect(emit_config)
        self.bg_opacity_slider.valueChanged.connect(self._on_bg_slider_changed)
        self.bg_blur_slider.valueChanged.connect(self._on_bg_slider_changed)
        for slider in (self.bg_opacity_slider, self.bg_blur_slider):
            slider.sliderReleased.connect(emit_config)
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

    def _on_ui_scale_changed(self, *_):
        """先存配置（config_changed），再通知主窗口即时重绘。"""
        self.config_changed.emit(self.get_config())
        try:
            scale = float(self.ui_scale_combo.currentData() or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        self.ui_scale_changed.emit(scale)

    def _on_lang_changed(self, *_):
        code = self.lang_combo.currentData()
        if not code:
            return
        self.config["language"] = code
        self.language_changed.emit(code)

    def _on_accent_changed(self, hexv):
        self.config["accent_color"] = hexv
        self.accent_changed.emit(hexv)

    def _on_bg_blur_changed(self, value):
        self.bg_blur_value.setText(str(int(value)))

    # ==================================================================
    # 交互
    # ==================================================================

    def _on_bg_slider_changed(self, *_):
        """背景两个滑条：值变了先刷文字，再防抖更新背景与配置。"""
        self.bg_blur_value.setText(str(self.bg_blur_slider.value()))
        self._bg_apply_timer.start()
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

    # ------------------------------------------------------------------
    # 找图与点击
    # ------------------------------------------------------------------
    def _browse_template_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, self.i18n.t("settings.template_dir"))
        if path:
            self.template_dir_edit.setText(path)

    def _open_template_capture(self):
        """打开「截取模板」：框选屏幕区域，存成当前分辨率下的模板。

        保存路径与自检分数直接显示在对话框里（1.0.2 的二次弹窗一闪即逝），
        所以这里不再弹提示，只负责把模板目录回填到设置项。
        """
        try:
            from ui.template_capture import TemplateCaptureDialog
        except Exception as e:
            QMessageBox.critical(self, self.i18n.t("common.error"), str(e))
            return

        dlg = TemplateCaptureDialog(self.i18n, self.get_config(), self)
        dlg.exec()
        target_dir = dlg.saved_dir()
        if target_dir and not self.template_dir_edit.text().strip():
            # 用户模板落在默认目录时显式写出来，方便事后手动管理
            self.template_dir_edit.setText(target_dir)
        if dlg.saved_file():
            logger.info(f"模板已更新: {dlg.saved_file()}"
                        f"（自检 {dlg.saved_score():.3f}）")

    def _run_match_test(self):
        """按当前设置截屏匹配一次，只报告结果、不点击。"""
        self.btn_test_match.setEnabled(False)
        self.btn_test_match.setText(self.i18n.t("about.check_update.checking"))
        self._match_test_worker = AsyncWorker(_match_test_worker, self.get_config())
        self._match_test_worker.finished.connect(self._on_match_test_done)
        self._match_test_worker.error.connect(self._on_match_test_error)
        self._match_test_worker.start()

    def _reset_match_test_button(self):
        self.btn_test_match.setEnabled(True)
        self.btn_test_match.setText(self.i18n.t("settings.match_test"))

    def _on_match_test_done(self, results):
        self._reset_match_test_button()
        # 测试时把 MAA / MaaEnd 拉到了前面，结果弹窗不能被压在后面
        try:
            win = self.window()
            win.showNormal()
            win.raise_()
            win.activateWindow()
        except Exception:
            pass
        lines = []
        for item in results:
            name = item["name"]
            if item.get("error"):
                lines.append(f"{name}: {item['error']}")
                continue
            match = item.get("match")
            source = item.get("source", "?")
            size = item.get("size", "")
            if match is None:
                lines.append(f"{name}: 未命中（{source} {size}）")
                continue
            # 用户自截模板是「屏幕原尺寸」，所以 scale≈1.00 是正常的；
            # 内置模板则应按系统缩放比命中（125% 时约 1.25）。
            lines.append(
                f"{name}: score={match.score:.3f} scale={match.scale:.2f} "
                f"center={match.center}  [{source} {size}]")
            logger.info(f"找图测试命中: {match}（来源 {source} {size}）")
        lines.append("")
        lines.append(self.i18n.t("settings.match_test.hint"))
        QMessageBox.information(self, self.i18n.t("settings.match_test"),
                                "\n".join(lines) or "-")

    def _on_match_test_error(self, msg):
        self._reset_match_test_button()
        QMessageBox.critical(self, self.i18n.t("common.error"), msg)

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
        c["min_emulator_runtime"] = self.min_emu_runtime_spin.value()
        c["log_retention_days"] = self.log_retention_spin.value()
        sched_times, sched_days = self.schedule_editor.values()
        c["schedule_times"] = sched_times
        c["schedule_weekdays"] = sched_days
        c["execute_time"] = sched_times[0] if sched_times else "08:00"
        c["serverchan_key"] = self.sc_edit.text().strip()
        c["webhook_url"] = self.webhook_edit.text().strip()
        c["blacklist_apps"] = self.blacklist_edit.text()
        c["background_image"] = self.bg_edit.text().strip()
        c["background_opacity"] = self.bg_opacity_slider.value() / 100.0
        c["background_blur"] = int(self.bg_blur_slider.value())
        c["background_mode"] = self.bg_mode_combo.currentData() or "cover"
        c["theme"] = (self.theme_combo.currentData() or "settings.theme.system").split(".")[-1]
        c["language"] = self.lang_combo.currentData() or "zh_CN"
        c["update_channel"] = self.channel_combo.currentData() or "stable"
        c["accent_color"] = self.accent_picker.color()
        for sw, key in self._switches:
            c[key] = sw.isChecked()
        c["foreground_action"] = self.fg_seg.current_value() or "none"

        # ---- 找图与点击 ----
        c["search_scope"] = self.scope_seg.current_value() or "window"
        c["match_threshold"] = self.threshold_spin.value() / 100.0
        c["match_scale_min"] = self.scale_min_spin.value() / 100.0
        c["match_scale_max"] = self.scale_max_spin.value() / 100.0
        if c["match_scale_max"] < c["match_scale_min"]:
            c["match_scale_max"] = c["match_scale_min"]
        c["click_mode"] = self.click_mode_combo.currentData() or "sendinput"
        c["click_offset_x"] = self.offset_x_spin.value()
        c["click_offset_y"] = self.offset_y_spin.value()
        c["template_dir"] = self.template_dir_edit.text().strip()
        c["ui_scale"] = float(self.ui_scale_combo.currentData() or 1.0)
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

        self.schedule_editor.retranslate()

        self.channel_combo.blockSignals(True)
        for i, val in enumerate(self._channel_values):
            if i < self.channel_combo.count():
                self.channel_combo.setItemText(
                    i, self.i18n.t(f"settings.update_channel.{val}"))
        self.channel_combo.blockSignals(False)

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
        self.btn_template_browse.setText(self.i18n.t("settings.browse"))
        self.btn_capture_template.setText(self.i18n.t("settings.template_capture"))
        self.btn_test_match.setText(self.i18n.t("settings.match_test"))
        self.btn_restart.setText(self.i18n.t("settings.ui_scale.restart"))
        self.btn_restart.setToolTip(self.i18n.t("settings.ui_scale.restart.tip"))
        self.fg_seg.retranslate()
        self.scope_seg.retranslate()
        self.accent_picker.retranslate()

        self.click_mode_combo.blockSignals(True)
        for i, val in enumerate(self._click_mode_values):
            if i < self.click_mode_combo.count():
                self.click_mode_combo.setItemText(
                    i, self.i18n.t(f"settings.click_mode.{val}"))
        self.click_mode_combo.blockSignals(False)

        self.blacklist_edit.setPlaceholderText(self.i18n.t("settings.blacklist_apps.desc"))
        self.webhook_edit.setPlaceholderText(self.i18n.t("settings.webhook_url.desc"))
        self.template_dir_edit.setPlaceholderText(
            self.i18n.t("settings.template_dir.desc"))