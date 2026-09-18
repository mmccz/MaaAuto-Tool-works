import os
import psutil
import win32gui
import win32process

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
                               QTableWidget, QTableWidgetItem, QLabel, QPushButton,
                               QHeaderView, QAbstractItemView, QCheckBox)
from PySide6.QtCore import Qt


# 默认隐藏的系统进程（小写）
SYSTEM_PROCESSES = {
    "explorer.exe", "system", "registry", "idle",
    "svchost.exe", "csrss.exe", "winlogon.exe", "smss.exe",
    "dwm.exe", "taskhostw.exe", "sihost.exe", "fontdrvhost.exe",
    "ctfmon.exe", "searchindexer.exe", "securityhealthsystray.exe",
    "runtimebroker.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe",
    "applicationframehost.exe", "searchapp.exe",
    "widgets.exe", "widgetservice.exe", "lockapp.exe",
    "securityhealthservice.exe", "sgrmbroker.exe",
    "wmiprvse.exe", "dllhost.exe", "conhost.exe",
    "audiodg.exe", "spoolsv.exe", "lsass.exe", "services.exe",
    "wininit.exe", "taskmgr.exe",
}


def collect_window_processes():
    results = {}
    self_pid = os.getpid()

    def enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or not title.strip():
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if pid == self_pid or pid in results:
            return True
        try:
            proc = psutil.Process(pid)
            results[pid] = {"name": proc.name(), "pid": pid, "title": title}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        return True

    win32gui.EnumWindows(enum_cb, None)
    return list(results.values())


class ProcessPickerDialog(QDialog):
    def __init__(self, i18n, current_blacklist="", parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(i18n.t("process_picker.title"))
        self.resize(720, 560)

        self._current = {
            x.strip().lower()
            for x in current_blacklist.replace("，", ",").replace("；", ",")
                             .replace(";", ",").replace("\n", ",").split(",")
            if x.strip()
        }

        # 记录每个进程的原始数据（dict）
        self._rows = []

        self._setup_ui()
        self._load_processes()

    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # 搜索框 + 显示系统进程
        top = QHBoxLayout()
        top.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self.i18n.t("process_picker.search"))
        self.search_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.search_edit, 1)

        self.show_system_cb = QCheckBox(self.i18n.t("process_picker.show_system"))
        self.show_system_cb.toggled.connect(self._apply_filter)
        top.addWidget(self.show_system_cb)
        layout.addLayout(top)

        # 表格
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            self.i18n.t("process_picker.col_name"),
            self.i18n.t("process_picker.col_pid"),
            self.i18n.t("process_picker.col_title"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionsClickable(True)

        layout.addWidget(self.table, 1)

        # 底部
        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setObjectName("SettingDesc")
        bottom.addWidget(self.count_label)
        bottom.addStretch()

        self.btn_clear = QPushButton(self.i18n.t("process_picker.clear"))
        self.btn_clear.setObjectName("GhostButton")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_selection)
        bottom.addWidget(self.btn_clear)

        self.btn_cancel = QPushButton(self.i18n.t("common.cancel"))
        self.btn_cancel.setObjectName("GhostButton")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton(self.i18n.t("common.ok"))
        self.btn_ok.setObjectName("PrimaryButton")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self.accept)
        bottom.addWidget(self.btn_ok)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------
    def _load_processes(self):
        procs = collect_window_processes()
        procs.sort(key=lambda p: p["name"].lower())
        self._rows = procs

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for p in procs:
            row = self.table.rowCount()
            self.table.insertRow(row)

            item_name = QTableWidgetItem(p["name"])
            item_name.setFlags(item_name.flags() | Qt.ItemIsUserCheckable)
            item_name.setCheckState(
                Qt.Checked if p["name"].lower() in self._current else Qt.Unchecked
            )
            self.table.setItem(row, 0, item_name)

            item_pid = QTableWidgetItem(str(p["pid"]))
            item_pid.setTextAlignment(Qt.AlignCenter)
            # 让 PID 支持按数字排序
            item_pid.setData(Qt.UserRole, p["pid"])
            self.table.setItem(row, 1, item_pid)

            item_title = QTableWidgetItem(p.get("title", ""))
            self.table.setItem(row, 2, item_title)

        self.table.blockSignals(False)
        self._apply_filter()

    # ------------------------------------------------------------------
    def _is_system(self, name):
        return name.lower() in SYSTEM_PROCESSES

    def _apply_filter(self, *_):
        text = self.search_edit.text().strip().lower()
        show_system = self.show_system_cb.isChecked()

        visible = 0
        for row, p in enumerate(self._rows):
            name_lc = p["name"].lower()
            title_lc = (p.get("title", "") or "").lower()

            # 系统进程过滤
            if not show_system and self._is_system(p["name"]):
                self.table.setRowHidden(row, True)
                continue

            # 搜索
            if text and text not in name_lc and text not in title_lc:
                self.table.setRowHidden(row, True)
                continue

            self.table.setRowHidden(row, False)
            visible += 1

        self._update_count(total=len(self._rows), visible=visible)

    def _on_row_double_clicked(self, item):
        """双击切换勾选"""
        row = item.row()
        it = self.table.item(row, 0)
        if not it:
            return
        it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def _on_item_changed(self, item):
        if item.column() == 0:
            self._update_count()

    def _update_count(self, total=None, visible=None):
        if total is None:
            total = self.table.rowCount()
        if visible is None:
            visible = sum(
                1 for r in range(self.table.rowCount())
                if not self.table.isRowHidden(r)
            )
        selected = sum(
            1 for r in range(self.table.rowCount())
            if self.table.item(r, 0)
            and self.table.item(r, 0).checkState() == Qt.Checked
        )
        self.count_label.setText(
            self.i18n.t("process_picker.stats",
                        total=total, visible=visible, n=selected)
        )

    def _clear_selection(self):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 0)
            if it:
                it.setCheckState(Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_count()

    # ------------------------------------------------------------------
    def get_selection(self):
        names = []
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 0)
            if it and it.checkState() == Qt.Checked:
                names.append(it.text())
        return names

    def get_selection_str(self):
        return ",".join(self.get_selection())