"""Schedule editor: multiple time slots + weekdays (1.3.0).

Lives in the settings page "Schedule & push" group, replacing the single ``WheelTimePicker``:

* Weekdays: 7 toggleable buttons (1=Mon ... 7=Sun); **none selected = every day**;
* Slots: a list of times with "Add time..." / "Remove selected", picking times via ``WheelTimePicker``;
* Every change emits ``changed()``; the settings page still auto-saves.

The widget never touches config directly, only get/set, which keeps it unit-testable.
"""

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from ui.wheel_time_picker import WheelTimePicker

WEEKDAY_KEYS = ("weekday.1", "weekday.2", "weekday.3", "weekday.4",
                "weekday.5", "weekday.6", "weekday.7")


class TimePickDialog(QDialog):
    """Small dialog to pick one time (reuses the wheel)."""

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
    """Weekday buttons + time slot list."""

    changed = Signal()

    def __init__(self, i18n, times=None, weekdays=None, parent=None):
        super().__init__(parent)
        self.i18n = i18n

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ---- Weekdays ----
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

        # ---- Time slots ----
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
        if self.list.count() == 0:          # keep at least one, avoid a "no time" config
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
        """Follow UI scale (self-painted / fixed-size widgets ignore QSS)."""
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
