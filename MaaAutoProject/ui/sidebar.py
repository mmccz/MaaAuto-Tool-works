from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QSpacerItem, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from utils import resource_path


class Sidebar(QWidget):
    page_changed = Signal(int)

    BASE_WIDTH_COMPACT = 168
    BASE_WIDTH = 200

    def __init__(self, i18n, compact=False, scale=1.0, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        # 窄屏（<1000 逻辑像素）时收窄，把空间留给内容区；
        # 界面缩放放大字号时同步加宽，否则「MaaAuto 控制台」会被截断。
        self._base_width = self.BASE_WIDTH_COMPACT if compact else self.BASE_WIDTH
        self._scale = self._normalize_scale(scale)
        self.setFixedWidth(self.scaled_width())
        self.i18n = i18n
        self._compact = compact
        self._buttons = []
        self._nav_keys = ["nav.home", "nav.settings", "nav.about"]
        self._setup_ui()

    # ------------------------------------------------------------------
    # 界面缩放
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_scale(scale):
        try:
            return max(1.0, min(2.0, float(scale)))
        except (TypeError, ValueError):
            return 1.0

    def scaled_width(self):
        return int(round(self._base_width * self._scale))

    def set_scale(self, scale):
        """界面缩放变化时即时改宽度（不必重启）。

        宽度是构造时 setFixedWidth 定死的，1.0.4 改缩放后侧栏宽度要等重启
        才跟着变——也是「界面缩放改了没反应」的一部分。图标、内外边距一起
        放大，否则 150% 时只剩字变大、图标还是 28px。
        """
        self._scale = self._normalize_scale(scale)
        self.setFixedWidth(self.scaled_width())
        self._apply_metrics()
        self.updateGeometry()

    def _px(self, value):
        return max(1, int(round(value * self._scale)))

    def _apply_metrics(self):
        self._layout.setContentsMargins(self._px(12), self._px(20),
                                        self._px(12), self._px(20))
        self._layout.setSpacing(self._px(6))
        self._header.setSpacing(self._px(10))
        self._nav_layout.setSpacing(self._px(4))
        self._header_gap.changeSize(0, self._px(22), QSizePolicy.Fixed,
                                    QSizePolicy.Fixed)
        logo_px = self._px(28)
        self._logo.setFixedSize(logo_px, logo_px)
        self._logo.setPixmap(
            QIcon(resource_path("resources/icon.ico")).pixmap(logo_px, logo_px))

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 20)
        layout.setSpacing(6)
        self._layout = layout

        header = QHBoxLayout()
        header.setSpacing(10)
        self._header = header
        self._logo = QLabel()
        self._logo.setFixedSize(28, 28)
        self._logo.setPixmap(
            QIcon(resource_path("resources/icon.ico")).pixmap(28, 28))
        header.addWidget(self._logo)
        self.title_label = QLabel(self.i18n.t("app.title"))
        self.title_label.setObjectName("AppTitle")
        header.addWidget(self.title_label)
        header.addStretch()
        layout.addLayout(header)

        self._header_gap = QSpacerItem(0, 22, QSizePolicy.Fixed,
                                       QSizePolicy.Fixed)
        layout.addItem(self._header_gap)

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
        self._apply_metrics()      # 启动时可能就是 1.25 / 1.5，边距图标要一次对齐

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