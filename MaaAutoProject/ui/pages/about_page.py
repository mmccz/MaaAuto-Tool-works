import os
import sys
import zipfile
import datetime
import platform
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtCore import qVersion
from ui.components import Card
from utils import resource_path, AsyncWorker
from config_manager import LOG_DIR, CONFIG_DIR, load_config
import app_info


class AboutPage(QWidget):
    announcements_clicked = Signal()

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
        self.ver_tag = QLabel(app_info.APP_VERSION)
        self.ver_tag.setObjectName("VersionTag")
        ver_row.addWidget(self.ver_tag)
        self.license_tag = QLabel(app_info.APP_LICENSE)
        self.license_tag.setObjectName("LicenseTag")
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
        self.gh_val = QLabel()
        self.gh_val.setOpenExternalLinks(True)
        gh_row.addWidget(self.gh_key)
        gh_row.addWidget(self.gh_val, 1)
        link_layout.addLayout(gh_row)
        em_row = QHBoxLayout()
        self.em_key = QLabel(self.i18n.t("about.email"))
        self.em_key.setObjectName("SettingDesc")
        self.em_key.setFixedWidth(120)
        self.em_val = QLabel()
        self.em_val.setOpenExternalLinks(True)
        em_row.addWidget(self.em_key)
        em_row.addWidget(self.em_val, 1)
        link_layout.addLayout(em_row)
        self._refresh_link_labels()
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

        self.btn_announcements = QPushButton(self.i18n.t("announce.title"))
        self.btn_announcements.setObjectName("GhostButton")
        self.btn_announcements.setCursor(Qt.PointingHandCursor)
        self.btn_announcements.clicked.connect(self.announcements_clicked)

        self.btn_export = QPushButton(self.i18n.t("about.export_logs"))
        self.btn_export.setObjectName("PrimaryButton")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self.export_logs)

        action_layout.addWidget(self.btn_open_config)
        action_layout.addWidget(self.btn_open_logs)
        action_layout.addWidget(self.btn_check_update)
        action_layout.addWidget(self.btn_announcements)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_export)
        root.addWidget(self.action_group)

        root.addStretch()
        self.copyright_label = QLabel(self.i18n.t("about.copyright"))
        self.copyright_label.setObjectName("SettingDesc")
        self.copyright_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.copyright_label)

        self._refresh_env_info()

    def _refresh_link_labels(self):
        """富文本链接颜色跟着主题走。

        QLabel 里的 ``<a>`` 用的是 Qt 默认纯蓝 #0000ff，深色主题下贴在
        #0f1115 背景上几乎看不见（1.0.5 实测反馈）。QSS 管不到标签内部的
        锚点，只能把颜色写进 span。
        """
        from themes import link_color
        color = link_color()
        self.gh_val.setText(
            f'<a href="{app_info.APP_GITHUB}">'
            f'<span style="color:{color}; text-decoration:none;">'
            f'{app_info.APP_GITHUB}</span></a>')
        self.em_val.setText(
            f'<a href="mailto:{app_info.APP_EMAIL}">'
            f'<span style="color:{color}; text-decoration:none;">'
            f'{app_info.APP_EMAIL}</span></a>')

    def refresh_theme_colors(self):
        """主题切换后调用（链接颜色不会自己跟着 QSS 变）。"""
        self._refresh_link_labels()

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
    def _channel(self):
        """当前更新频道（stable / beta），读配置；失败按 stable。"""
        try:
            return load_config().get("update_channel", "stable")
        except Exception:
            return "stable"

    def check_for_update(self):
        from update_checker import check_update

        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText(self.i18n.t("about.check_update.checking"))

        self._update_check_worker = AsyncWorker(check_update, self._channel())
        self._update_check_worker.finished.connect(self._on_check_done)
        self._update_check_worker.error.connect(self._on_check_error)
        self._update_check_worker.start()

    def _on_check_done(self, info):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(self.i18n.t("about.check_update"))

        from ui.update_dialog import MessageDialog, ask_update

        if info is None:
            MessageDialog(self.i18n, self.i18n.t("update.failed.title"),
                          self.i18n.t("about.check_update.failed"),
                          self, icon="warning").exec()
            return

        if not info.get("has_update"):
            MessageDialog(
                self.i18n, self.i18n.t("update.latest.title"),
                self.i18n.t("update.latest.text", current=info["current"]),
                self).exec()
            return

        if not ask_update(self.i18n, info, self):
            return

        from update_checker import apply_update
        if not apply_update(self, silent=False, channel=self._channel()):
            MessageDialog(self.i18n, self.i18n.t("update.failed.title"),
                          self.i18n.t("update.apply_failed"),
                          self, icon="warning").exec()
            return

        from PySide6.QtWidgets import QApplication
        win = self.window()
        if hasattr(win, "is_quitting"):
            win.is_quitting = True
        # 升级后会自动重启，别把 MAA / 模拟器一起关掉
        if hasattr(win, "_relaunching"):
            win._relaunching = True
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
        from ui.update_dialog import MessageDialog
        MessageDialog(
            self.i18n, self.i18n.t("update.failed.title"),
            self.i18n.t("about.check_update.failed") + f"\n\n{err_msg}",
            self, icon="warning").exec()

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
        self.btn_announcements.setText(self.i18n.t("announce.title"))
        self.btn_export.setText(self.i18n.t("about.export_logs"))
        self.copyright_label.setText(self.i18n.t("about.copyright"))