"""Setup wizard (2.0.1): four steps, and the last one is read-only.

Nothing here may start MAA/MaaEnd - the wizard only writes config when the user
presses 完成, and the final page is the same selfcheck.py the tray entry runs.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MaaAutoProject")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def i18n():
    from i18n import init_i18n
    from utils import resource_path

    inst = init_i18n(resource_path("i18n"))
    inst.load_language("zh_CN")
    yield inst
    inst.load_language("zh_CN")


class FakeEnv:
    def __init__(self, files=(), processes=(), admin=True):
        self.files = {str(f) for f in files}
        self.processes = set(processes)
        self.admin = admin

    def exe_exists(self, path):
        return bool(path) and str(path) in self.files

    def process_running(self, name):
        return name in self.processes

    def is_admin(self):
        return self.admin

    def detect_exe(self, process_name, candidates):
        return None


def make_wizard(i18n, monkeypatch, config=None):
    import selfcheck
    from ui.setup_wizard import SetupWizardDialog

    monkeypatch.setattr(selfcheck, "Environment", lambda: FakeEnv())
    return SetupWizardDialog(i18n, dict(config or {"control": "inject"}))


def test_has_four_steps_and_starts_on_the_first(qapp, i18n, monkeypatch):
    dlg = make_wizard(i18n, monkeypatch)
    try:
        assert dlg.stack.count() == 4
        assert dlg._index == 0
        assert dlg.back_button.isEnabled() is False
        assert dlg.next_button.text() == dlg._t("setup.next", "下一步")
    finally:
        dlg.deleteLater()


def test_navigation_walks_all_pages_and_finishes(qapp, i18n, monkeypatch):
    dlg = make_wizard(i18n, monkeypatch)
    try:
        for expected in (1, 2, 3):
            dlg._go_next()
            assert dlg._index == expected
        assert dlg.next_button.text() == dlg._t("setup.finish", "完成")
        dlg._go_back()
        assert dlg._index == 2
    finally:
        dlg.deleteLater()


def test_last_page_runs_the_read_only_selfcheck(qapp, i18n, monkeypatch):
    dlg = make_wizard(i18n, monkeypatch)
    try:
        dlg._index = 3
        dlg.stack.setCurrentIndex(3)
        checks = dlg.refresh_check_page()
        assert checks, "自检至少要产出一条结果"
        assert dlg.summary.text()
        assert dlg.check_rows.count() > 0
    finally:
        dlg.deleteLater()


def test_finish_writes_the_expected_keys(qapp, i18n, monkeypatch):
    saved = {}
    monkeypatch.setattr("config_manager.save_config", lambda cfg: saved.update(cfg), raising=False)
    dlg = make_wizard(i18n, monkeypatch)
    try:
        dlg.maa_path_edit.setText(r"E:\MAA\MAA.exe")
        dlg.maaend_path_edit.setText(r"E:\MaaEnd\MaaEnd.exe")
        dlg.schedule_enable.setChecked(True)
        dlg.push_edit.setText("SCT123")
        dlg._finish()
        assert saved["maa_path"] == r"E:\MAA\MAA.exe"
        assert saved["maaend_path"] == r"E:\MaaEnd\MaaEnd.exe"
        assert saved["enable_schedule"] is True
        assert saved["schedule_times"]
        assert saved["serverchan_key"] == "SCT123"
        assert saved["setup_wizard_seen"] is True
    finally:
        dlg.deleteLater()


def test_paths_page_fills_from_detection(qapp, i18n, monkeypatch):
    import upstream

    monkeypatch.setattr(
        upstream, "detect_exe", lambda name, candidates: r"E:\MAA\MAA.exe" if name == "maa.exe" else None
    )
    dlg = make_wizard(i18n, monkeypatch, {"control": "inject", "maa_path": "", "maaend_path": ""})
    try:
        assert dlg.maa_path_edit.text() == r"E:\MAA\MAA.exe"
    finally:
        dlg.deleteLater()


def test_config_preview_uses_the_typed_paths(qapp, i18n, monkeypatch):
    dlg = make_wizard(i18n, monkeypatch)
    try:
        dlg.maa_path_edit.setText(r"E:\MAA\MAA.exe")
        dlg.maaend_path_edit.setText(r"E:\MaaEnd\MaaEnd.exe")
        preview = dlg._config_preview()
        assert preview["maa_path"] == r"E:\MAA\MAA.exe"
        assert preview["maaend_path"] == r"E:\MaaEnd\MaaEnd.exe"
    finally:
        dlg.deleteLater()


def test_step_rail_tracks_the_current_page(qapp, i18n, monkeypatch):
    dlg = make_wizard(i18n, monkeypatch)
    try:
        assert len(dlg.rail_rows) == 4
        dot, label = dlg.rail_rows[0]
        assert dot.text() == "1"
        assert dot.objectName() == "SetupStepDotActive"
        dlg._go_next()
        assert dlg.rail_rows[0][0].objectName() == "SetupStepDot"
        assert dlg.rail_rows[1][0].objectName() == "SetupStepDotActive"
        assert dlg.rail_rows[1][1].objectName() == "SetupStepActive"
    finally:
        dlg.deleteLater()
