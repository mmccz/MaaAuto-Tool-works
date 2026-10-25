"""定时编辑器：多时段 + 工作日（1.3.0）。

放在设置页「定时与推送」分组里，替代原来的单个 ``WheelTimePicker``：

* 星期：7 个可切换按钮（1=周一 … 7=周日），**一个都不选 = 每天**；
* 时段：一列时间，支持「添加时间…」「删除选中」，内部用 ``WheelTimePicker`` 选时间；
* 任何改动都发 ``changed()``，设置页照旧自动保存。

控件不直接读写配置，只负责「取值 / 设值」，方便单测。
"""

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from ui.wheel_time_picker import WheelTimePicker

WEEKDAY_KEYS = ("weekday.1", "weekday.2", "weekday.3", "weekday.4",
                "weekday.5", "weekday.6", "weekday.7")


class TimePickDialog(QDialog):
    """选一个时间的小弹窗（复用滚轮）。"""

    def __init__(self, i18n, initial="08:00", parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(i18n.t("settings.schedule.add"))
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        self.picker = WheelTimePicker()
        self.picker.setTime(QTime.fromString(initial, "HH:mm"))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.picker)
        row.addStretch()
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.resize(260, 150)

    def value(self) -> str:
        return self.picker.time().toString("HH:mm")


class ScheduleEditor(QWidget):
    """星期按钮 + 时段列表。"""

    changed = Signal()

    def __init__(self, i18n, times=None, weekdays=None, parent=None):
        super().__init__(parent)
        self.i18n = i18n

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ---- 星期 ----
        week_row = QHBoxLayout()
        week_row.setSpacing(4)
        self._day_buttons = []
        for idx, key in enumerate(WEEKDAY_KEYS, 1):
            btn = QToolButton()
            btn.setText(i18n.t(key))
            btn.setCheckable(True)
            btn.setObjectName("WeekdayButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedWidth(34)
            btn.toggled.connect(lambda _=False: self.changed.emit())
            self._day_buttons.append((idx, btn))
            week_row.addWidget(btn)
        self.day_hint = QLabel(i18n.t("settings.schedule.every_day"))
        self.day_hint.setObjectName("DialogSubtitle")
        week_row.addSpacing(6)
        week_row.addWidget(self.day_hint)
        week_row.addStretch()
        root.addLayout(week_row)

        # ---- 时段 ----
        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        self.list = QListWidget()
        self.list.setObjectName("ScheduleTimeList")
        self.list.setFixedHeight(88)
        self.list.setMinimumWidth(120)
        self.list.setMaximumWidth(200)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        time_row.addWidget(self.list)

        btns = QVBoxLayout()
        btns.setSpacing(4)
        self.btn_add = QPushButton(i18n.t("settings.schedule.add"))
        self.btn_add.setObjectName("GhostButton")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self._add_time)
        self.btn_remove = QPushButton(i18n.t("settings.schedule.remove"))
        self.btn_remove.setObjectName("GhostButton")
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.clicked.connect(self._remove_time)
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_remove)
        btns.addStretch()
        time_row.addLayout(btns)
        time_row.addStretch()
        root.addLayout(time_row)

        self.set_values(times or ["08:00"], weekdays or [])

    # ------------------------------------------------------------------ #
    def _add_time(self):
        dlg = TimePickDialog(self.i18n, "08:00", self)
        if dlg.exec() != QDialog.Accepted:
            return
        value = dlg.value()
        if self.list.findItems(value, Qt.MatchExactly):
            return
        self._insert_sorted(value)
        self.changed.emit()

    def _insert_sorted(self, value):
        existing = [self.list.item(i).text() for i in range(self.list.count())]
        existing.append(value)
        existing.sort()
        self.list.clear()
        self.list.addItems(existing)

    def _remove_time(self):
        row = self.list.currentRow()
        if row < 0:
            return
        self.list.takeItem(row)
        if self.list.count() == 0:          # 至少留一个，避免「没有时间」的配置
            self.list.addItem("08:00")
        self.changed.emit()

    # ------------------------------------------------------------------ #
    def times(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def weekdays(self):
        return [idx for idx, btn in self._day_buttons if btn.isChecked()]

    def values(self):
        return self.times(), self.weekdays()

    def set_values(self, times, weekdays):
        times = [t for t in (times or []) if t] or ["08:00"]
        self.list.clear()
        for value in sorted(set(times)):
            self.list.addItem(value)
        selected = set(weekdays or [])
        for idx, btn in self._day_buttons:
            btn.blockSignals(True)
            btn.setChecked(idx in selected)
            btn.blockSignals(False)
        self._refresh_hint()

    def _refresh_hint(self):
        text = (self.i18n.t("settings.schedule.every_day") if not self.weekdays()
                else "")
        self.day_hint.setText(text)

    def set_ui_scale(self, scale):
        """跟随界面缩放（自绘/固定尺寸控件不吃 QSS）。"""
        try:
            scale = max(0.75, min(2.0, float(scale)))
        except (TypeError, ValueError):
            scale = 1.0
        btn_w = int(34 * scale)
        for _idx, btn in self._day_buttons:
            btn.setFixedWidth(btn_w)
        self.list.setFixedHeight(int(88 * scale))
        self._scale = scale

    def retranslate(self):
        for idx, btn in self._day_buttons:
            btn.setText(self.i18n.t(WEEKDAY_KEYS[idx - 1]))
        self.btn_add.setText(self.i18n.t("settings.schedule.add"))
        self.btn_remove.setText(self.i18n.t("settings.schedule.remove"))
        self._refresh_hint()
