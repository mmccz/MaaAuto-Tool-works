"""First-run wizard: four short steps, and the last one only reads.

Steps
  1. Programs   - auto-detect MAA / MaaEnd, or browse for them
  2. Tasks      - which MaaEnd instance to run, and what MAA will actually run
  3. Schedule   - enable the timer, one time slot, optional push key
  4. Check      - the read-only self-check (selfcheck.py); no test run, by design

Nothing is started here. The wizard writes the config only when the user presses
"完成", and every step can be revisited.
"""

import os

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

import selfcheck

STEP_TITLES = (
    "setup.paths.title",
    "setup.tasks.title",
    "setup.schedule.title",
    "setup.check.title",
)

LEVEL_MARKS = {
    selfcheck.LEVEL_OK: ("✓", "SetupOk"),
    selfcheck.LEVEL_WARN: ("!", "SetupWarn"),
    selfcheck.LEVEL_ERROR: ("✕", "SetupError"),
}


class SetupWizardDialog(QDialog):
    """Read-only setup check + the three settings a first run actually needs."""

    control_mode_changed = Signal(str)      # kept for callers that still listen

    def __init__(self, i18n, config, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.config = config
        self.setWindowTitle("MaaAuto")
        self.resize(820, 640)
        self.setMinimumSize(680, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        head = QVBoxLayout(header)
        head.setContentsMargins(26, 22, 26, 10)
        head.setSpacing(6)
        title = QLabel(self._t("setup.title", "环境自检"))
        title.setObjectName("PageTitle")
        head.addWidget(title)
        self.step_label = QLabel("")
        self.step_label.setObjectName("DialogSubtitle")
        head.addWidget(self.step_label)
        root.addWidget(header)

        self.stack = QStackedWidget()
        self.pages = [
            self._build_paths_page(),
            self._build_tasks_page(),
            self._build_schedule_page(),
            self._build_check_page(),
        ]
        for page in self.pages:
            self.stack.addWidget(page)

        # Step rail: a numbered list makes it obvious how long the wizard is and
        # where you are; the previous layout only had a "第 N / 4 步" subtitle.
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        rail_wrap = QWidget()
        rail = QVBoxLayout(rail_wrap)
        rail.setContentsMargins(26, 6, 12, 6)
        rail.setSpacing(10)
        self.rail_rows = []
        for index, title_key in enumerate(STEP_TITLES):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            dot = QLabel(str(index + 1))
            dot.setObjectName("SetupStepDot")
            dot.setAlignment(Qt.AlignCenter)
            label = QLabel(self._t(title_key))
            label.setObjectName("SetupStep")
            row_layout.addWidget(dot)
            row_layout.addWidget(label, 1)
            rail.addWidget(row)
            self.rail_rows.append((dot, label))
        rail.addStretch(1)
        rail_wrap.setFixedWidth(214)
        body.addWidget(rail_wrap)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(22, 8, 22, 18)
        footer.setSpacing(10)
        self.back_button = QPushButton(self._t("setup.back", "上一步"))
        self.back_button.setObjectName("GhostButton")
        self.back_button.clicked.connect(self._go_back)
        self.next_button = QPushButton(self._t("setup.next", "下一步"))
        self.next_button.setObjectName("PrimaryButton")
        self.next_button.clicked.connect(self._go_next)
        self.close_button = QPushButton(self._t("setup.close", "关闭"))
        self.close_button.setObjectName("GhostButton")
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.back_button)
        footer.addStretch(1)
        footer.addWidget(self.close_button)
        footer.addWidget(self.next_button)
        root.addLayout(footer)

        self._index = 0
        self._update_nav()

    # ---- helpers ------------------------------------------------------- #
    def _t(self, key, fallback=""):
        try:
            text = self.i18n.t(key)
        except Exception:
            text = key
        return fallback if not text or text == key else text

    def _page(self, title_key, body_key):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 6, 26, 6)
        layout.setSpacing(10)
        title = QLabel(self._t(title_key))
        title.setObjectName("SetupTitle")
        layout.addWidget(title)
        body = QLabel(self._t(body_key))
        body.setObjectName("SetupDetail")
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addSpacing(4)
        return page, layout

    @staticmethod
    def _row(widgets):
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for widget in widgets:
            lay.addWidget(widget, 1 if hasattr(widget, "text") else 0)
        return wrap

    def _browse_button(self, line_edit, filter_):
        button = QPushButton(self._t("settings.browse", "浏览"))
        button.setObjectName("GhostButton")

        def pick():
            from PySide6.QtWidgets import QFileDialog

            path, _ = QFileDialog.getOpenFileName(self, self._t("settings.browse"), "", filter_)
            if path:
                path = os.path.normpath(path)
                line_edit.setText(path)

        button.clicked.connect(pick)
        return button

    # ---- page 1: programs ---------------------------------------------- #
    def _build_paths_page(self):
        page, layout = self._page("setup.paths.title", "setup.paths.body")
        self.maa_path_edit = QLineEdit(str(self.config.get("maa_path") or ""))
        self.maaend_path_edit = QLineEdit(str(self.config.get("maaend_path") or ""))
        for edit, label_key, filter_ in (
            (self.maa_path_edit, "setup.paths.maa", "MAA.exe"),
            (self.maaend_path_edit, "setup.paths.maaend", "MaaEnd.exe"),
        ):
            label = QLabel(self._t(label_key))
            label.setObjectName("SetupDetail")
            layout.addWidget(label)
            layout.addWidget(self._row([edit, self._browse_button(edit, filter_)]))
        detect = QPushButton(self._t("setup.paths.detect", "自动检测"))
        detect.setObjectName("GhostButton")
        detect.clicked.connect(self._auto_detect)
        layout.addWidget(detect, 0, Qt.AlignLeft)
        layout.addStretch(1)
        self._auto_detect(silent=True)
        return page

    def _auto_detect(self, silent=False):
        """Fill empty fields from the running process / known install locations."""

        try:
            import upstream
        except Exception:
            return
        if not self.maa_path_edit.text().strip():
            found = upstream.detect_exe("maa.exe", [r"E:\MAA\MAA.exe"])
            if found:
                self.maa_path_edit.setText(str(found))
        if not self.maaend_path_edit.text().strip():
            found = upstream.detect_exe("maaend", [r"E:\MaaEnd\MaaEnd.exe"])
            if found:
                self.maaend_path_edit.setText(str(found))
        if not silent:
            self._refresh_tasks_page()

    # ---- page 2: tasks / instance -------------------------------------- #
    def _build_tasks_page(self):
        page, layout = self._page("setup.tasks.title", "setup.tasks.body")
        label = QLabel(self._t("settings.maaend_instance", "MaaEnd 实例"))
        label.setObjectName("SetupDetail")
        layout.addWidget(label)
        self.instance_combo = QComboBox()
        self.instance_combo.setMinimumWidth(240)
        layout.addWidget(self.instance_combo, 0, Qt.AlignLeft)

        self.tasks_summary = QLabel("")
        self.tasks_summary.setObjectName("SetupDetail")
        self.tasks_summary.setWordWrap(True)
        layout.addWidget(self.tasks_summary)
        layout.addStretch(1)
        self._refresh_tasks_page()
        return page

    def _config_preview(self):
        """A config dict with the paths typed so far (for detection helpers)."""

        preview = dict(self.config)
        preview["maa_path"] = self.maa_path_edit.text().strip()
        preview["maaend_path"] = self.maaend_path_edit.text().strip()
        return preview

    def _refresh_tasks_page(self):
        try:
            from ui.pages.settings_page import maaend_instance_names

            names = maaend_instance_names(self._config_preview())
        except Exception:
            names = []
        want = str(self.config.get("maaend_instance") or "")
        self.instance_combo.blockSignals(True)
        self.instance_combo.clear()
        self.instance_combo.addItem(self._t("settings.maaend_instance.auto"), "")
        for name in names:
            self.instance_combo.addItem(name, name)
        index = self.instance_combo.findData(want)
        self.instance_combo.setCurrentIndex(index if index >= 0 else 0)
        self.instance_combo.blockSignals(False)

        try:
            from injector import MaaConfig
            from pathlib import Path

            maa_path = self.maa_path_edit.text().strip()
            if maa_path:
                cfg = MaaConfig(Path(maa_path).parent)
                tasks = [t["name"] for t in cfg.enabled_tasks()]
            else:
                tasks = []
        except Exception:
            tasks = []
        if tasks:
            self.tasks_summary.setText(
                self._t("setup.tasks.queue", "MAA 当前方案会执行：") + " → ".join(tasks)
            )
        else:
            self.tasks_summary.setText(self._t("setup.tasks.empty", "还没有检测到 MAA 任务队列"))

    # ---- page 3: schedule ---------------------------------------------- #
    def _build_schedule_page(self):
        page, layout = self._page("setup.schedule.title", "setup.schedule.body")
        self.schedule_enable = QPushButton(self._t("settings.enable_schedule", "启用定时"))
        self.schedule_enable.setObjectName("GhostButton")
        self.schedule_enable.setCheckable(True)
        enabled = bool(self.config.get("enable_schedule", False))
        self.schedule_enable.setChecked(enabled)
        layout.addWidget(self.schedule_enable, 0, Qt.AlignLeft)

        self.time_edit = QTimeEdit()
        times = self.config.get("schedule_times") or [self.config.get("execute_time", "08:00")]
        self.time_edit.setTime(QTime.fromString(str(times[0]), "HH:mm"))
        layout.addWidget(self.time_edit, 0, Qt.AlignLeft)

        self.push_edit = QLineEdit(str(self.config.get("serverchan_key") or ""))
        self.push_edit.setPlaceholderText(self._t("settings.serverchan_key", "Server酱 SendKey"))
        layout.addWidget(self.push_edit)
        layout.addStretch(1)
        return page

    # ---- page 4: check -------------------------------------------------- #
    def _build_check_page(self):
        page, layout = self._page("setup.check.title", "setup.check.body")
        self.summary = QLabel("")
        self.summary.setObjectName("DialogSubtitle")
        layout.addWidget(self.summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        self.check_container = QWidget()
        self.check_container.setObjectName("SetupContainer")
        self.check_container.setAttribute(Qt.WA_StyledBackground, True)
        self.check_rows = QVBoxLayout(self.check_container)
        self.check_rows.setContentsMargins(0, 4, 0, 4)
        self.check_rows.setSpacing(8)
        scroll.setWidget(self.check_container)
        layout.addWidget(scroll, 1)
        return page

    def _check_row(self, check):
        card = QFrame()
        card.setObjectName("SetupCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        mark, style = LEVEL_MARKS.get(check.level, ("?", "SetupWarn"))
        marker = QLabel(mark)
        marker.setObjectName(style)
        marker.setFixedWidth(22)
        marker.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        lay.addWidget(marker)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(self._t(check.title_key, check.code))
        title.setObjectName("SetupTitle")
        text.addWidget(title)
        if check.detail:
            detail = QLabel(check.detail)
            detail.setObjectName("SetupDetail")
            detail.setWordWrap(True)
            text.addWidget(detail)
        if check.hint:
            hint = QLabel(check.hint)
            hint.setObjectName("SetupHint")
            hint.setWordWrap(True)
            text.addWidget(hint)
        lay.addLayout(text, 1)
        return card

    def refresh_check_page(self):
        checks = selfcheck.run_selfcheck(self._config_preview())
        level, errors, warns = selfcheck.summarize(checks)
        order = {selfcheck.LEVEL_OK: 0, selfcheck.LEVEL_WARN: 1, selfcheck.LEVEL_ERROR: 2}
        checks = sorted(checks, key=lambda c: order.get(c.level, 0))

        while self.check_rows.count():
            item = self.check_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for check in checks:
            self.check_rows.addWidget(self._check_row(check))
        self.check_rows.addStretch(1)

        if level == selfcheck.LEVEL_ERROR:
            self.summary.setText(
                self._t("setup.summary_error", "发现 {errors} 个必须修复的问题").replace(
                    "{errors}", str(errors)
                )
            )
        elif level == selfcheck.LEVEL_WARN:
            self.summary.setText(
                self._t("setup.summary_warn", "有 {warns} 条提醒，不影响运行").replace(
                    "{warns}", str(warns)
                )
            )
        else:
            self.summary.setText(self._t("setup.summary_ok", "环境检查通过，可以执行任务"))
        return checks

    # ---- navigation ----------------------------------------------------- #
    def _update_nav(self):
        last = self._index == len(self.pages) - 1
        self.back_button.setEnabled(self._index > 0)
        self.next_button.setText(
            self._t("setup.finish", "完成") if last else self._t("setup.next", "下一步")
        )
        self.step_label.setText(
            self._t("setup.step", "第 {n} / {total} 步").replace("{n}", str(self._index + 1)).replace(
                "{total}", str(len(self.pages))
            )
        )
        for index, (dot, label) in enumerate(getattr(self, "rail_rows", [])):
            active = index == self._index
            dot.setObjectName("SetupStepDotActive" if active else "SetupStepDot")
            label.setObjectName("SetupStepActive" if active else "SetupStep")
            for widget in (dot, label):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        if last:
            self.refresh_check_page()

    def _go_back(self):
        if self._index > 0:
            self._index -= 1
            self.stack.setCurrentIndex(self._index)
            self._update_nav()

    def _go_next(self):
        if self._index < len(self.pages) - 1:
            if self._index == 0:
                self._refresh_tasks_page()
            self._index += 1
            self.stack.setCurrentIndex(self._index)
            self._update_nav()
            return
        self._finish()

    # ---- finish --------------------------------------------------------- #
    def _finish(self):
        cfg = self.config
        cfg["maa_path"] = self.maa_path_edit.text().strip()
        cfg["maaend_path"] = self.maaend_path_edit.text().strip()
        cfg["maaend_instance"] = self.instance_combo.currentData() or ""
        cfg["enable_schedule"] = self.schedule_enable.isChecked()
        cfg["execute_time"] = self.time_edit.time().toString("HH:mm")
        cfg["schedule_times"] = [cfg["execute_time"]]
        cfg["serverchan_key"] = self.push_edit.text().strip()
        cfg["setup_wizard_seen"] = True
        try:
            from config_manager import save_config

            save_config(cfg)
        except Exception:
            pass
        self.accept()
