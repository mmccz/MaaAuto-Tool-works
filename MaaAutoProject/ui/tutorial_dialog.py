"""新手教程：第一次使用时把「怎么配、怎么跑」讲清楚。

重点（用户明确要求必须让使用者看到的两条）：
  1. MAA 里一定要勾选「完成后退出模拟器」；
  2. MaaEnd 任务列表**最后**一定要加「关闭程序」或「关闭模拟器」。

这两条单独用 ``TutorialWarning`` 样式块高亮（红底深红字，深色主题下自动换色），
而不是埋在正文里 —— 它们是整个自动化能不能收尾的前提。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QWidget, QFrame)

# (标题 key, 正文 key, 高亮警告 key 或 None)
SECTIONS = [
    ("tutorial.s1.title", "tutorial.s1.body", None),
    ("tutorial.s2.title", "tutorial.s2.body", "tutorial.warn_maa"),
    ("tutorial.s3.title", "tutorial.s3.body", "tutorial.warn_maaend"),
    ("tutorial.s4.title", "tutorial.s4.body", None),
    ("tutorial.s5.title", "tutorial.s5.body", None),
    ("tutorial.s6.title", "tutorial.s6.body", None),
    ("tutorial.s7.title", "tutorial.s7.body", None),
]


class TutorialDialog(QDialog):
    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle("MaaAuto")
        self.resize(820, 640)
        self.setMinimumSize(680, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        hl = QVBoxLayout(header)
        hl.setContentsMargins(26, 22, 26, 10)
        hl.setSpacing(6)
        self.title_label = QLabel(self.i18n.t("tutorial.title"))
        self.title_label.setObjectName("PageTitle")
        hl.addWidget(self.title_label)
        self.subtitle_label = QLabel(self.i18n.t("tutorial.subtitle"))
        self.subtitle_label.setObjectName("DialogSubtitle")
        hl.addWidget(self.subtitle_label)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        container = QWidget()
        # ★ 不加这两行，深色主题下滚动区会露出默认白底（QWidget 不会自己透明），
        #   于是白底 + 浅色文字 = 看不见（实测截图）。
        container.setObjectName("TutorialContainer")
        container.setAttribute(Qt.WA_StyledBackground, True)
        container.setAutoFillBackground(False)
        self.vbox = QVBoxLayout(container)
        self.vbox.setContentsMargins(26, 8, 26, 20)
        self.vbox.setSpacing(14)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)
        self.scroll = scroll

        self._sections = []
        for title_key, body_key, warn_key in SECTIONS:
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)

            title = QLabel(self.i18n.t(title_key))
            title.setObjectName("SectionTitle")
            bl.addWidget(title)

            body = QLabel(self.i18n.t(body_key))
            body.setObjectName("DialogText")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bl.addWidget(body)

            warn = None
            if warn_key:
                warn = QLabel(self.i18n.t(warn_key))
                warn.setObjectName("TutorialWarning")
                warn.setWordWrap(True)
                warn.setTextInteractionFlags(Qt.TextSelectableByMouse)
                bl.addWidget(warn)

            self.vbox.addWidget(block)
            self._sections.append((title, title_key, body, body_key,
                                   warn, warn_key))
        self.vbox.addStretch()

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(26, 12, 26, 18)
        fl.setSpacing(12)
        self.footer_label = QLabel(self.i18n.t("tutorial.footer"))
        self.footer_label.setObjectName("DialogSubtitle")
        self.footer_label.setWordWrap(True)
        fl.addWidget(self.footer_label, 1)
        self.btn_close = QPushButton(self.i18n.t("tutorial.close"))
        self.btn_close.setObjectName("PrimaryButton")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setMinimumWidth(150)
        self.btn_close.clicked.connect(self.accept)
        fl.addWidget(self.btn_close, 0, Qt.AlignVCenter)
        root.addWidget(footer)

    def retranslate(self):
        self.title_label.setText(self.i18n.t("tutorial.title"))
        self.subtitle_label.setText(self.i18n.t("tutorial.subtitle"))
        for title, title_key, body, body_key, warn, warn_key in self._sections:
            title.setText(self.i18n.t(title_key))
            body.setText(self.i18n.t(body_key))
            if warn is not None and warn_key:
                warn.setText(self.i18n.t(warn_key))
        self.footer_label.setText(self.i18n.t("tutorial.footer"))
        self.btn_close.setText(self.i18n.t("tutorial.close"))
