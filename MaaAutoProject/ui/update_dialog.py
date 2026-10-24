"""升级提示弹窗（替代「把 GitHub Release 正文塞进 QMessageBox」）。

旧实现的问题（1.0.5 实测反馈）：
  * QMessageBox 里的正文是纯文本，GitHub 的 Markdown（##、-、表格）原样显示，
    长链接不换行，窗口被撑得很丑；
  * 没有「版本 → 版本」的对比，只有一行「发现新版本 x.y.z」；
  * 「是/否」按钮语义不清。

这里的弹窗跟界面共用主题：标题区 + 发布说明富文本区（Markdown 渲染、可滚动）
+ 明确的「立即升级 / 稍后 / 查看发布页」按钮。
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTextBrowser)

from utils import resource_path

NOTES_LIMIT = 12000

LINK_COLOR_LIGHT = "#2563eb"
LINK_COLOR_DARK = "#60a5fa"


def link_color():
    try:
        from themes import link_color as _theme_link_color
        return _theme_link_color()
    except Exception:
        return LINK_COLOR_LIGHT


def colorize_links(browser, color=None):
    """把富文本里的链接改成当前主题可见的颜色。

    ``setMarkdown`` 会给每个链接写死 ``#0000ff``（实测 charFormat 前景色就是
    纯蓝），既不跟 QSS 也不跟 palette 走 —— 深色主题下几乎看不见。这里渲染完
    再遍历所有 anchor 片段，统一 merge 一个前景色。
    """
    color = color or link_color()
    doc = browser.document()
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    ranges = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isAnchor():
                ranges.append((frag.position(), frag.length()))
            it += 1
        block = block.next()
    for pos, length in ranges:
        cursor = QTextCursor(doc)
        cursor.setPosition(pos)
        cursor.setPosition(pos + length, QTextCursor.KeepAnchor)
        cursor.mergeCharFormat(fmt)
    return len(ranges)


def render_notes_browser(notes):
    """把 Release 正文渲染进 QTextBrowser（优先 Markdown）。"""
    browser = QTextBrowser()
    browser.setObjectName("ReleaseNotes")
    browser.setOpenExternalLinks(True)
    browser.setLineWrapMode(QTextBrowser.WidgetWidth)
    text = (notes or "").strip()
    if len(text) > NOTES_LIMIT:
        text = text[:NOTES_LIMIT] + "\n\n…"
    if not text:
        return browser
    try:
        browser.setMarkdown(text)
        colorize_links(browser)
    except Exception:
        browser.setPlainText(re.sub(r"[#*`>]", "", text))
    return browser


class MessageDialog(QDialog):
    """统一样式的信息弹窗（替代散落的 QMessageBox.information）。"""

    def __init__(self, i18n, title, text, parent=None, icon="info"):
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle("MaaAuto")
        self.setMinimumWidth(420)
        self.setMaximumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        icon_label = QLabel()
        icon_label.setFixedSize(36, 36)
        icon_path = resource_path("resources/icon.ico")
        if icon == "warning":
            icon_label.setText("⚠")
            icon_label.setObjectName("DialogIconWarn")
        else:
            icon_label.setPixmap(QIcon(icon_path).pixmap(36, 36))
        head.addWidget(icon_label)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("DialogTitle")
        self.title_label.setWordWrap(True)
        head.addWidget(self.title_label, 1)
        root.addLayout(head)

        self.text_label = QLabel(text)
        self.text_label.setObjectName("DialogText")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.text_label)

        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_ok = QPushButton(self.i18n.t("common.got_it"))
        self.btn_ok.setObjectName("PrimaryButton")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self.accept)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)


class UpdateDialog(QDialog):
    """发现新版本：版本对比 + 发布说明 + 升级/稍后/发布页。

    ``chosen`` 取值：``"update"`` / ``"later"`` / ``"open"``。
    """

    def __init__(self, i18n, info, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.info = info or {}
        self.chosen = "later"
        self.setWindowTitle("MaaAuto")
        self.resize(680, 520)
        self.setMinimumSize(560, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        # ---- 头部：图标 + 标题 + 版本对比 ----
        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setFixedSize(48, 48)
        logo.setPixmap(QIcon(resource_path("resources/icon.ico")).pixmap(48, 48))
        head.addWidget(logo, 0, Qt.AlignTop)

        head_text = QVBoxLayout()
        head_text.setSpacing(4)
        self.title_label = QLabel(self.i18n.t("update.title"))
        self.title_label.setObjectName("DialogTitle")
        head_text.addWidget(self.title_label)

        self.version_label = QLabel(self.i18n.t(
            "update.subtitle",
            latest=self.info.get("latest", "?"),
            current=self.info.get("current", "?")))
        self.version_label.setObjectName("DialogSubtitle")
        head_text.addWidget(self.version_label)

        channel = self.info.get("channel", "stable")
        self.channel_label = QLabel(self.i18n.t(f"update.channel.{channel}"))
        self.channel_label.setObjectName("UpdateChannelTag")
        head_text.addWidget(self.channel_label, 0, Qt.AlignLeft)
        head.addLayout(head_text, 1)
        root.addLayout(head)

        # ---- 发布说明 ----
        self.notes_title = QLabel(self.i18n.t("update.notes"))
        self.notes_title.setObjectName("SectionTitle")
        root.addWidget(self.notes_title)

        notes = self.info.get("notes") or ""
        if notes.strip():
            self.notes = render_notes_browser(notes)
        else:
            self.notes = QLabel(self.i18n.t("update.no_notes"))
            self.notes.setObjectName("DialogText")
            self.notes.setWordWrap(True)
            self.notes.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self.notes, 1)

        # ---- 按钮 ----
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_open = QPushButton(self.i18n.t("update.btn.open"))
        self.btn_open.setObjectName("GhostButton")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(self._on_open)
        if self.info.get("html_url"):
            btns.addWidget(self.btn_open)
        btns.addStretch()

        self.btn_later = QPushButton(self.i18n.t("update.btn.later"))
        self.btn_later.setObjectName("GhostButton")
        self.btn_later.setCursor(Qt.PointingHandCursor)
        self.btn_later.clicked.connect(self._on_later)
        btns.addWidget(self.btn_later)

        self.btn_update = QPushButton(self.i18n.t("update.btn.update"))
        self.btn_update.setObjectName("PrimaryButton")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.setDefault(True)
        self.btn_update.clicked.connect(self._on_update)
        btns.addWidget(self.btn_update)
        root.addLayout(btns)

    def _on_open(self):
        self.chosen = "open"
        self.accept()

    def _on_later(self):
        self.chosen = "later"
        self.reject()

    def _on_update(self):
        self.chosen = "update"
        self.accept()


def ask_update(i18n, info, parent=None):
    """弹窗询问是否升级；返回 True 表示用户选择「立即升级」。"""
    dlg = UpdateDialog(i18n, info, parent)
    dlg.exec()
    if dlg.chosen == "open":
        url = (info or {}).get("html_url") or ""
        if url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        return False
    return dlg.chosen == "update"
