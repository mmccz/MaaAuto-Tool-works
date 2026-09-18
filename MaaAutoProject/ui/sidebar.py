from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QSpacerItem, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from utils import resource_path


class Sidebar(QWidget):
    page_changed = Signal(int)

    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(200)
        self.i18n = i18n
        self._buttons = []
        self._nav_keys = ["nav.home", "nav.settings", "nav.about"]
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 20)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(28, 28)
        logo.setPixmap(QIcon(resource_path("resources/icon.ico")).pixmap(28, 28))
        header.addWidget(logo)
        self.title_label = QLabel(self.i18n.t("app.title"))
        self.title_label.setObjectName("AppTitle")
        header.addWidget(self.title_label)
        header.addStretch()
        layout.addLayout(header)
        layout.addSpacing(22)

        self._nav_layout = QVBoxLayout()
        self._nav_layout.setSpacing(4)
        layout.addLayout(self._nav_layout)

        for key in self._nav_keys:
            btn = QPushButton(self.i18n.t(key))
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            idx = len(self._buttons)
            btn.clicked.connect(lambda _, i=idx: self._on_click(i))
            self._buttons.append(btn)
            self._nav_layout.addWidget(btn)

        layout.addStretch()
        self._buttons[0].setChecked(True)

    def _on_click(self, index):
        for i, b in enumerate(self._buttons):
            b.setChecked(i == index)
        self.page_changed.emit(index)

    def set_current(self, index):
        for i, b in enumerate(self._buttons):
            b.setChecked(i == index)

    def retranslate(self):
        self.title_label.setText(self.i18n.t("app.title"))
        for btn, key in zip(self._buttons, self._nav_keys):
            btn.setText(self.i18n.t(key))