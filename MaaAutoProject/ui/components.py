from PySide6.QtWidgets import (QFrame, QWidget, QLabel, QHBoxLayout, QVBoxLayout,
                               QSizePolicy, QPushButton, QAbstractButton,
                               QButtonGroup, QColorDialog)
from PySide6.QtCore import (Qt, Property, QPropertyAnimation, QEasingCurve,
                            QAbstractAnimation, QRectF, Signal)
from PySide6.QtGui import QColor, QPainter


# =============================================================================
# Card / StatCard / SettingItem / SettingGroup（保持原样）
# =============================================================================
class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.NoFrame)


class StatCard(Card):
    def __init__(self, title="", value="", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("StatTitle")
        layout.addWidget(self.title_label)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setWordWrap(True)
        layout.addWidget(self.value_label)
        layout.addStretch()

    def set_title(self, text):
        self.title_label.setText(text)

    def set_value(self, text):
        self.value_label.setText(text)


class SettingItem(QWidget):
    def __init__(self, title="", description="", widget=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(16)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SettingTitle")
        text_layout.addWidget(self.title_label)

        if description:
            self.desc_label = QLabel(description)
            self.desc_label.setObjectName("SettingDesc")
            self.desc_label.setWordWrap(True)
            text_layout.addWidget(self.desc_label)
        else:
            self.desc_label = None

        layout.addLayout(text_layout, 1)
        self.widget = widget
        if widget is not None:
            layout.addWidget(widget, 0, Qt.AlignRight | Qt.AlignVCenter)

    def set_title(self, text):
        self.title_label.setText(text)

    def set_description(self, text):
        if self.desc_label:
            self.desc_label.setText(text)


class SettingGroup(QFrame):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("SettingGroup")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 16, 20, 16)
        self._layout.setSpacing(0)

        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("GroupTitle")
            self._layout.addWidget(self.title_label)
            self._layout.addSpacing(8)
        else:
            self.title_label = None

        self._separator_count = 0

    def add_item(self, item):
        if self._separator_count > 0:
            sep = QFrame()
            sep.setObjectName("Separator")
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            self._layout.addWidget(sep)
        self._layout.addWidget(item)
        self._separator_count += 1

    def set_title(self, text):
        if self.title_label:
            self.title_label.setText(text)


# =============================================================================
# Switch：iOS 风格开关
# =============================================================================
class Switch(QAbstractButton):
    """
    自适应主题色的 iOS 风格开关。
    通过 QSS 的 qproperty-* 注入颜色：
        Switch { qproperty-accent: #3b82f6; qproperty-trackOff: #e5e7eb;
                 qproperty-knobColor: #ffffff; }
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Switch")
        self.setCheckable(True)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)

        self._progress = 0.0
        self._accent = QColor("#3b82f6")
        self._track_off = QColor("#e5e7eb")
        self._knob_color = QColor("#ffffff")

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._on_toggled)

    # -------- progress --------
    def _get_progress(self):
        return self._progress

    def _set_progress(self, v):
        self._progress = float(v)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    # -------- accent --------
    def _get_accent(self):
        return self._accent

    def _set_accent(self, c):
        self._accent = c if isinstance(c, QColor) else QColor(c)
        self.update()

    accent = Property(QColor, _get_accent, _set_accent)

    # -------- trackOff --------
    def _get_track_off(self):
        return self._track_off

    def _set_track_off(self, c):
        self._track_off = c if isinstance(c, QColor) else QColor(c)
        self.update()

    trackOff = Property(QColor, _get_track_off, _set_track_off)

    # -------- knobColor --------
    def _get_knob_color(self):
        return self._knob_color

    def _set_knob_color(self, c):
        self._knob_color = c if isinstance(c, QColor) else QColor(c)
        self.update()

    knobColor = Property(QColor, _get_knob_color, _set_knob_color)

    # -------- API --------
    def _on_toggled(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setCheckedSilently(self, checked):
        """初始化时使用，跳过动画、不触发信号。"""
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._anim.stop()
        self._progress = 1.0 if checked else 0.0
        self.update()

    # -------- 绘制 --------
    def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)

            w, h = self.width(), self.height()
            radius = h / 2.0
            t = self._progress

            if not self.isEnabled():
                # 禁用态：灰色不透明
                track = QColor("#d1d5db" if self._knob_color.lightness() > 128 else "#4b5563")
                knob = QColor("#f3f4f6" if self._knob_color.lightness() > 128 else "#9ca3af")
                p.setPen(Qt.NoPen)
                p.setBrush(track)
                p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
                knob_d = h - 6
                knob_x = 3.0 + (w - knob_d - 6.0) * t
                p.setBrush(knob)
                p.drawEllipse(QRectF(knob_x, 3, knob_d, knob_d))
                return

            # 悬停：稍微提亮
            hover = self.underMouse()
            mix = 0.08 if hover else 0.0

            r = int(self._track_off.red() * (1 - t) + self._accent.red() * t)
            g = int(self._track_off.green() * (1 - t) + self._accent.green() * t)
            b = int(self._track_off.blue() * (1 - t) + self._accent.blue() * t)
            if mix:
                r = min(255, int(r + (255 - r) * mix))
                g = min(255, int(g + (255 - g) * mix))
                b = min(255, int(b + (255 - b) * mix))

            p.setPen(Qt.NoPen)
            p.setBrush(QColor(r, g, b))
            p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

            knob_d = h - 6
            min_x = 3.0
            max_x = w - knob_d - 3.0
            knob_x = min_x + (max_x - min_x) * t

            p.setBrush(self._knob_color)
            p.drawEllipse(QRectF(knob_x, 3, knob_d, knob_d))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


# =============================================================================
# SegmentedControl：分段选择器（用于前台处理三选一）
# =============================================================================
class SegmentedControl(QWidget):
    """
    类似 iOS 的分段控件。
    items: [(i18n_key_or_text, value), ...]
    用法：
        seg = SegmentedControl([("settings.foreground_action.none", "none"),
                                ("settings.foreground_action.kill_all", "kill_all"),
                                ("settings.foreground_action.blacklist", "blacklist")],
                               i18n=self.i18n)
        seg.selection_changed.connect(...)
    """
    selection_changed = Signal(object)

    def __init__(self, items=None, i18n=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentedControl")
        self._i18n = i18n
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = []
        self._values = []
        self._keys = []
        self._group.idClicked.connect(self._on_clicked)

        if items:
            self.set_items(items)

    def set_items(self, items):
        for btn in self._buttons:
            self._group.removeButton(btn)
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()
        self._values.clear()
        self._keys.clear()

        for i, (key_or_text, value) in enumerate(items):
            text = self._i18n.t(key_or_text) if self._i18n else key_or_text
            btn = QPushButton(text)
            btn.setObjectName("SegmentItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._group.addButton(btn, i)
            self._layout.addWidget(btn)
            self._buttons.append(btn)
            self._values.append(value)
            self._keys.append(key_or_text)

        if self._buttons:
            self._buttons[0].setChecked(True)

    def _on_clicked(self, idx):
        self.selection_changed.emit(self._values[idx])

    def current_value(self):
        for i, b in enumerate(self._buttons):
            if b.isChecked():
                return self._values[i]
        return None

    def set_current_value(self, value, emit=False):
        for i, v in enumerate(self._values):
            if v == value:
                if not emit:
                    self._group.blockSignals(True)
                self._buttons[i].setChecked(True)
                if not emit:
                    self._group.blockSignals(False)
                return

    def retranslate(self):
        if not self._i18n:
            return
        for btn, key in zip(self._buttons, self._keys):
            btn.setText(self._i18n.t(key))


# =============================================================================
# AccentColorPicker：强调色选择器（预设色块 + 自定义）
# =============================================================================
class AccentColorPicker(QWidget):
    """
    强调色选择器：
      - 一排预设色块（互斥），点击后立即发出 colorChanged(str)
      - 右侧一个「自定义」按钮，打开 QColorDialog
    用法：
        picker = AccentColorPicker(i18n=self.i18n)
        picker.set_color(config.get("accent_color", "#3b82f6"))
        picker.colorChanged.connect(...)
    """
    colorChanged = Signal(str)

    PRESETS = [
        "#3b82f6",  # 蓝（默认）
        "#10b981",  # 绿
        "#14b8a6",  # 青
        "#f59e0b",  # 琥珀
        "#f97316",  # 橙
        "#ef4444",  # 红
        "#ec4899",  # 粉
        "#8b5cf6",  # 紫
    ]

    def __init__(self, i18n=None, parent=None):
        super().__init__(parent)
        self._i18n = i18n
        self._color = self.PRESETS[0]
        self._swatches = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        for i, hexv in enumerate(self.PRESETS):
            btn = QPushButton()
            btn.setObjectName("AccentSwatch")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(24, 24)
            btn.setToolTip(hexv)
            # 色块自身颜色是动态的，无法走全局 QSS，这里直接内联样式
            btn.setStyleSheet(f"""
                QPushButton#AccentSwatch {{
                    background-color: {hexv};
                    border: 2px solid transparent;
                    border-radius: 12px;
                }}
                QPushButton#AccentSwatch:hover {{
                    border: 2px solid rgba(148, 163, 184, 0.65);
                }}
                QPushButton#AccentSwatch:checked {{
                    border: 2px solid #94a3b8;
                }}
            """)
            self._group.addButton(btn, i)
            self._swatches[hexv] = btn
            lay.addWidget(btn)

        self._group.idClicked.connect(self._on_swatch_clicked)

        self.custom_btn = QPushButton(
            self._i18n.t("settings.accent_color.custom") if self._i18n else "Custom"
        )
        self.custom_btn.setObjectName("GhostButton")
        self.custom_btn.setCursor(Qt.PointingHandCursor)
        self.custom_btn.clicked.connect(self._open_color_dialog)
        lay.addWidget(self.custom_btn)

        self.set_color(self._color, emit=False)

    # ------------------------------------------------------------------
    def _on_swatch_clicked(self, idx):
        hexv = self.PRESETS[idx]
        self._color = hexv
        self.colorChanged.emit(hexv)

    def _open_color_dialog(self):
        initial = QColor(self._color)
        title = self._i18n.t("settings.accent_color") if self._i18n else "Accent Color"
        c = QColorDialog.getColor(initial, self, title)
        if c.isValid():
            self.set_color(c.name().lower(), emit=True)

    # ------------------------------------------------------------------
    def color(self) -> str:
        return self._color

    def set_color(self, hexv, emit=False):
        hexv = str(hexv).strip().lower()
        if not hexv.startswith("#"):
            hexv = "#" + hexv
        self._color = hexv

        # 更新预设色块选中态（不触发 idClicked，因为那是用户点击专属信号）
        for preset, btn in self._swatches.items():
            btn.setChecked(preset == hexv)

        if emit:
            self.colorChanged.emit(hexv)

    def retranslate(self):
        if self._i18n:
            self.custom_btn.setText(self._i18n.t("settings.accent_color.custom"))