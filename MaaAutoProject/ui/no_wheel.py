from PySide6.QtWidgets import QComboBox, QTimeEdit, QLineEdit
from PySide6.QtGui import QIntValidator
from PySide6.QtCore import Signal


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


class NoWheelTimeEdit(QTimeEdit):
    def wheelEvent(self, e):
        e.ignore()


class IntLineEdit(QLineEdit):
    """替代 QSpinBox：QLineEdit + 整数校验，避开 QSS 按钮错位问题。"""
    valueChanged = Signal(int)

    def __init__(self, minimum=0, maximum=999999, value=0, parent=None):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = int(maximum)
        self.setValidator(QIntValidator(self._min, self._max, self))
        self.setText(str(int(value)))
        self.setMinimumWidth(80)
        self.setAlignment(self.alignment())
        self.editingFinished.connect(self._on_edited)

    def _on_edited(self):
        try:
            v = int(self.text())
        except (ValueError, TypeError):
            v = self._min
        v = max(self._min, min(self._max, v))
        self.setText(str(v))
        self.valueChanged.emit(v)

    def value(self) -> int:
        try:
            return int(self.text())
        except (ValueError, TypeError):
            return self._min

    def setValue(self, v: int):
        self.setText(str(int(v)))