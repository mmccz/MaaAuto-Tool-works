import os
import sys
import zipfile
import datetime
import platform
import subprocess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFileDialog, QMessageBox, QFrame)
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtCore import qVersion
from ui.components import Card
from utils import resource_path, AsyncWorker
from config_manager import LOG_DIR, CONFIG_DIR
import app_info


class AboutPage(QWidget):
    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self._update_check_worker = None
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        self.page_title = QLabel(self.i18n.t("nav.about"))
        self.page_title.setObjectName("PageTitle")
        root.addWidget(self.page_title)

        header_card = Card()
        hl = QHBoxLayout(header_card)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(20)

        logo = QLabel()
        logo.setFixedSize(72, 72)
        pix = QIcon(resource_path("resources/icon.ico")).pixmap(72, 72)
        logo.setPixmap(pix)
        hl.addWidget(logo)

        info = QVBoxLayout()
        info.setSpacing(4)
        self.name_label = QLabel(app_info.APP_DISPLAY_NAME)
        self.name_label.setObjectName("PageTitle")
        info.addWidget(self.name_label)
        self.desc_label = QLabel(self.i18n.t("app.description"))
        self.desc_label.setObjectName("SettingDesc")
        info.addWidget(self.desc_label)

        ver_row = QHBoxLayout()
        ver_row.setSpacing(8)
        ver_tag = QLabel(app_info.APP_VERSION)
        ver_tag.setObjectName("JumpChip")
        ver_tag.setStyleSheet(
            "background: rgba(59,130,246,0.15); color:#1d4ed8;"
            "border-radius:10px; padding:2px 10px; font-size:12px;")
        ver_row.addWidget(ver_tag)
        self.license_tag = QLabel(app_info.APP_LICENSE)
        self.license_tag.setObjectName("JumpChip")
        self.license_tag.setStyleSheet(
            "background: rgba(16,185,129,0.15); color:#047857;"
            "border-radius:10px; padding:2px 10px; font-size:12px;")
        ver_row.addWidget(self.license_tag)
        ver_row.addStretch()
        info.addLayout(ver_row)
        hl.addLayout(info, 1)
        root.addWidget(header_card)

        self.env_group = Card()
        env_layout = QVBoxLayout(self.env_group)
        env_layout.setContentsMargins(24, 18, 24, 18)
        env_layout.setSpacing(8)
        self.env_title = QLabel(self.i18n.t("about.title"))
        self.env_title.setObjectName("GroupTitle")
        env_layout.addWidget(self.env_title)
        self.env_labels = {}
        for key in ("about.python", "about.pyside", "about.qt", "about.system"):
            row = QHBoxLayout()
            k = QLabel(self.i18n.t(key))
            k.setObjectName("SettingDesc")
            k.setFixedWidth(120)
            v = QLabel("-")
            v.setObjectName("SettingTitle")
            row.addWidget(k)
            row.addWidget(v, 1)
            env_layout.addLayout(row)
            self.env_labels[key] = (k, v)
        root.addWidget(self.env_group)

        self.link_group = Card()
        link_layout = QVBoxLayout(self.link_group)
        link_layout.setContentsMargins(24, 18, 24, 18)
        link_layout.setSpacing(10)
        gh_row = QHBoxLayout()
        self.gh_key = QLabel(self.i18n.t("about.github"))
        self.gh_key.setObjectName("SettingDesc")
        self.gh_key.setFixedWidth(120)
        self.gh_val = QLabel(f'<a href="{app_info.APP_GITHUB}">{app_info.APP_GITHUB}</a>')
        self.gh_val.setOpenExternalLinks(True)
        gh_row.addWidget(self.gh_key)
        gh_row.addWidget(self.gh_val, 1)
        link_layout.addLayout(gh_row)
        em_row = QHBoxLayout()
        self.em_key = QLabel(self.i18n.t("about.email"))
        self.em_key.setObjectName("SettingDesc")
        self.em_key.setFixedWidth(120)
        self.em_val = QLabel(f'<a href="mailto:{app_info.APP_EMAIL}">{app_info.APP_EMAIL}</a>')
        self.em_val.setOpenExternalLinks(True)
        em_row.addWidget(self.em_key)
        em_row.addWidget(self.em_val, 1)
        link_layout.addLayout(em_row)
        root.addWidget(self.link_group)

        self.action_group = Card()
        action_layout = QHBoxLayout(self.action_group)
        action_layout.setContentsMargins(20, 14, 20, 14)
        action_layout.setSpacing(12)

        self.btn_open_config = QPushButton(self.i18n.t("about.open_config"))
        self.btn_open_config.setObjectName("GhostButton")
        self.btn_open_config.setCursor(Qt.PointingHandCursor)
        self.btn_open_config.clicked.connect(self.open_config_dir)

        self.btn_open_logs = QPushButton(self.i18n.t("about.open_logs"))
        self.btn_open_logs.setObjectName("GhostButton")
        self.btn_open_logs.setCursor(Qt.PointingHandCursor)
        self.btn_open_logs.clicked.connect(self.open_logs_dir)

        self.btn_check_update = QPushButton(self.i18n.t("about.check_update"))
        self.btn_check_update.setObjectName("GhostButton")
        self.btn_check_update.setCursor(Qt.PointingHandCursor)
        self.btn_check_update.clicked.connect(self.check_for_update)

        self.btn_export = QPushButton(self.i18n.t("about.export_logs"))
        self.btn_export.setObjectName("PrimaryButton")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self.export_logs)

        action_layout.addWidget(self.btn_open_config)
        action_layout.addWidget(self.btn_open_logs)
        action_layout.addWidget(self.btn_check_update)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_export)
        root.addWidget(self.action_group)

        root.addStretch()
        self.copyright_label = QLabel(self.i18n.t("about.copyright"))
        self.copyright_label.setObjectName("SettingDesc")
        self.copyright_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.copyright_label)

        self._refresh_env_info()

    def _refresh_env_info(self):
        try:
            import PySide6
            pyside_ver = PySide6.__version__
        except Exception:
            pyside_ver = "-"
        data = {
            "about.python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "about.pyside": pyside_ver,
            "about.qt": qVersion(),
            "about.system": f"{platform.system()} {platform.release()} ({platform.version()})",
        }
        for key, val in data.items():
            if key in self.env_labels:
                self.env_labels[key][1].setText(val)

    def open_config_dir(self):
        os.startfile(os.path.abspath(CONFIG_DIR))

    def open_logs_dir(self):
        os.startfile(os.path.abspath(LOG_DIR))

    def export_logs(self):
        default_name = f"MaaAuto_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, self.i18n.t("dialog.export.title"), default_name, "ZIP (*.zip)")
        if not path:
            return
        try:
            base = os.path.abspath(LOG_DIR)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(base):
                    for f in files:
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, base)
                        zf.write(full, rel)
            QMessageBox.information(self, self.i18n.t("common.success"),
                                    self.i18n.t("dialog.export.success", path=path))
        except Exception as e:
            QMessageBox.critical(self, self.i18n.t("common.error"),
                                 self.i18n.t("dialog.export.failed", err=str(e)))

    # ==================================================================
    # 检查更新 —— 后台线程执行，绝不阻塞 UI
    # ==================================================================
    def check_for_update(self):
        from update_checker import check_update

        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText(self.i18n.t("about.check_update.checking"))

        self._update_check_worker = AsyncWorker(check_update)
        self._update_check_worker.finished.connect(self._on_check_done)
        self._update_check_worker.error.connect(self._on_check_error)
        self._update_check_worker.start()

    def _on_check_done(self, info):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(self.i18n.t("about.check_update"))

        if info is None:
            QMessageBox.warning(self, self.i18n.t("common.warning"),
                                self.i18n.t("about.check_update.failed"))
            return

        if not info.get("has_update"):
            QMessageBox.information(
                self, self.i18n.t("common.info"),
                self.i18n.t("about.check_update.latest") + f"\n\n{info['current']}")
            return

        notes = (info.get("notes") or "").strip()
        if len(notes) > 800:
            notes = notes[:800] + "\n…"
        msg = self.i18n.t("about.check_update.available", version=info["latest"])
        if notes:
            msg += "\n\n" + notes
        msg += "\n\n" + self.i18n.t("about.check_update.confirm")

        ret = QMessageBox.question(self, "MaaAuto", msg,
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.Yes)
        if ret != QMessageBox.Yes:
            return

        from update_checker import apply_update
        if apply_update(self, silent=False):
            from PySide6.QtWidgets import QApplication
            win = self.window()
            if hasattr(win, "is_quitting"):
                win.is_quitting = True
            try:
                if hasattr(win, "_save_geometry"):
                    win._save_geometry()
                if hasattr(win, "cleanup_on_exit"):
                    win.cleanup_on_exit()
            except Exception:
                pass
            QApplication.quit()

    def _on_check_error(self, err_msg):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(self.i18n.t("about.check_update"))
        QMessageBox.warning(
            self, self.i18n.t("common.warning"),
            self.i18n.t("about.check_update.failed") + f"\n\n{err_msg}")

    def retranslate(self):
        self.page_title.setText(self.i18n.t("nav.about"))
        self.desc_label.setText(self.i18n.t("app.description"))
        self.env_title.setText(self.i18n.t("about.title"))
        for key, (k, _) in self.env_labels.items():
            k.setText(self.i18n.t(key))
        self.gh_key.setText(self.i18n.t("about.github"))
        self.em_key.setText(self.i18n.t("about.email"))
        self.btn_open_config.setText(self.i18n.t("about.open_config"))
        self.btn_open_logs.setText(self.i18n.t("about.open_logs"))
        self.btn_check_update.setText(self.i18n.t("about.check_update"))
        self.btn_export.setText(self.i18n.t("about.export_logs"))
        self.copyright_label.setText(self.i18n.t("about.copyright"))