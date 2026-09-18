import html as _html

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTextEdit, QSizePolicy)
from PySide6.QtCore import Qt, Signal

from ui.components import StatCard


class HomePage(QWidget):
    """首页：状态卡片 + 立即执行/结束任务按钮 + 实时日志。"""

    run_clicked = Signal()
    stop_clicked = Signal()
    clear_log_clicked = Signal()

    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self._is_running = False
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        # 顶部标题 + 运行/结束按钮
        top = QHBoxLayout()
        self.page_title = QLabel(self.i18n.t("nav.home"))
        self.page_title.setObjectName("PageTitle")
        top.addWidget(self.page_title)
        top.addStretch()

        self.run_btn = QPushButton(self.i18n.t("home.btn.run"))
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setMinimumWidth(140)
        self.run_btn.clicked.connect(self._on_run_btn_clicked)
        top.addWidget(self.run_btn)
        layout.addLayout(top)

        # 4 张状态卡片
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.card_status = StatCard(self.i18n.t("home.status.label"),
                                    self.i18n.t("home.status.idle"))
        self.card_last_run = StatCard(self.i18n.t("home.last_run.label"),
                                      self.i18n.t("home.last_run.none"))
        self.card_next_run = StatCard(self.i18n.t("home.next_run.label"),
                                      self.i18n.t("home.next_run.none"))
        self.card_run_count = StatCard(self.i18n.t("home.run_count.label"), "0")
        for c in (self.card_status, self.card_last_run,
                  self.card_next_run, self.card_run_count):
            cards.addWidget(c)
        layout.addLayout(cards)

        # 日志标题栏
        log_header = QHBoxLayout()
        self.log_title = QLabel(self.i18n.t("home.log.title"))
        self.log_title.setObjectName("SectionTitle")
        log_header.addWidget(self.log_title)
        log_header.addStretch()

        self.clear_btn = QPushButton(self.i18n.t("home.log.clear"))
        self.clear_btn.setObjectName("GhostButton")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_log_clicked.emit)
        log_header.addWidget(self.clear_btn)
        layout.addLayout(log_header)

        # 日志视图
        self.log_text = QTextEdit()
        self.log_text.setObjectName("LogView")
        self.log_text.setReadOnly(True)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.log_text, 1)

    # ------------------------------------------------------------------
    # 按钮行为
    # ------------------------------------------------------------------
    def _on_run_btn_clicked(self):
        if self._is_running:
            # 用户请求结束任务：先把自己禁掉防止重复点，再通知外部
            self.run_btn.setEnabled(False)
            self.run_btn.setText(self.i18n.t("home.btn.stopping"))
            self.stop_clicked.emit()
        else:
            self.run_clicked.emit()

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def append_log(self, text):
        self.log_text.append(self._colorize(text))
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

        doc = self.log_text.document()
        if doc.blockCount() > 2000:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    @staticmethod
    def _colorize(line: str) -> str:
        escaped = _html.escape(line)
        if "==========" in line:
            return f'<span style="color:#60a5fa;font-weight:700;">{escaped}</span>'
        if " - ERROR - " in line or "【严重错误】" in line:
            return f'<span style="color:#f87171;">{escaped}</span>'
        if " - WARNING - " in line:
            return f'<span style="color:#fbbf24;">{escaped}</span>'
        if "中止" in line or "已终止" in line:
            return f'<span style="color:#fbbf24;font-weight:600;">{escaped}</span>'
        if "成功" in line and "失败" not in line:
            return f'<span style="color:#4ade80;">{escaped}</span>'
        return f'<span style="color:#cbd5e1;">{escaped}</span>'

    def clear_log(self):
        self.log_text.clear()

    # ------------------------------------------------------------------
    # 动态字段
    # ------------------------------------------------------------------
    def set_status(self, status_key):
        self.card_status.set_value(self.i18n.t(status_key))

    def set_last_run(self, text):
        self.card_last_run.set_value(text or self.i18n.t("home.last_run.none"))

    def set_next_run(self, text):
        self.card_next_run.set_value(text or self.i18n.t("home.next_run.none"))

    def set_run_count(self, count):
        unit = self.i18n.t("home.run_count.unit")
        self.card_run_count.set_value(f"{count} {unit}".strip())

    def set_running(self, running):
        self._is_running = running
        self.run_btn.setEnabled(True)

        if running:
            self.run_btn.setObjectName("DangerButton")
            self.run_btn.setText(self.i18n.t("home.btn.stop"))
        else:
            self.run_btn.setObjectName("PrimaryButton")
            self.run_btn.setText(self.i18n.t("home.btn.run"))

        # objectName 变了必须 unpolish/polish 才会重新匹配 QSS
        self.run_btn.style().unpolish(self.run_btn)
        self.run_btn.style().polish(self.run_btn)

        self.set_status("home.status.running" if running else "home.status.idle")

        if running:
            self.card_status.setStyleSheet(
                "QFrame#Card { border: 1px solid rgba(59,130,246,0.55); }"
            )
        else:
            self.card_status.setStyleSheet("")

    # ------------------------------------------------------------------
    # 语言切换
    # ------------------------------------------------------------------
    def retranslate(self):
        self.page_title.setText(self.i18n.t("nav.home"))
        self.run_btn.setText(self.i18n.t("home.btn.stop") if self._is_running
                             else self.i18n.t("home.btn.run"))
        self.card_status.set_title(self.i18n.t("home.status.label"))
        self.card_last_run.set_title(self.i18n.t("home.last_run.label"))
        self.card_next_run.set_title(self.i18n.t("home.next_run.label"))
        self.card_run_count.set_title(self.i18n.t("home.run_count.label"))
        self.log_title.setText(self.i18n.t("home.log.title"))
        self.clear_btn.setText(self.i18n.t("home.log.clear"))