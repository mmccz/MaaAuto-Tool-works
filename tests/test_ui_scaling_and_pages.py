"""Regression tests for UI scaling (QSS font-size) and sliding page transitions.

Both were reported as "looks like it was never implemented" in the 1.0.2 field report:
* UI scale: the QSS ``* { font-size: 13px }`` overrides QApplication.setFont(), so
  changing only the app font does nothing — font-size inside the QSS must be rewritten;
* fast page switching: switching while an animation is running lets the old animation's
  done() hide the current page, leaving the UI blank.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MaaAutoProject")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from themes import ThemeManager  # noqa: E402
import themes as themes_mod  # noqa: E402


# --------------------------------------------------------------------------- #
# QSS scaling
# --------------------------------------------------------------------------- #
def test_scale_font_sizes_scales_px_values():
    qss = ("* { font-size: 13px; }\n"
           "QLabel#PageTitle { font-size: 22px; font-weight: 700; }\n"
           "QPushButton#JumpChip { padding: 5px 14px; font-size: 12px; }")
    out = ThemeManager._scale_font_sizes(qss, 1.5)

    assert "font-size: 20px" in out        # 13 * 1.5 = 19.5 → 20
    assert "font-size: 33px" in out        # 22 * 1.5 = 33
    assert "font-size: 18px" in out        # 12 * 1.5 = 18
    # px values outside font-size are untouched (padding etc. is handled by Qt layout)
    assert "padding: 5px 14px" in out


def test_scale_one_is_noop():
    qss = "QLabel { font-size: 13px; }"
    assert ThemeManager._scale_font_sizes(qss, 1.0) == qss


def test_scale_qss_scales_lengths_too():
    """Scaling font size alone is not enough: without a larger min-width "whole screen" wraps."""
    qss = ("* { font-size: 13px; }\n"
           "QPushButton#SegmentItem { padding: 6px 16px; min-width: 90px; }\n"
           "QFrame#Card { border: 1px solid rgba(0, 0, 0, 0.06);"
           " border-radius: 12px; }\n"
           "QSlider::handle { margin: -5px 0; }")
    out = ThemeManager._scale_qss(qss, 1.5)

    assert "font-size: 20px" in out
    assert "min-width: 135px" in out
    assert "padding: 9px 24px" in out
    assert "border-radius: 18px" in out
    assert "margin: -8px 0" in out
    # Hairline borders stay 1px, otherwise the UI "bloats"
    assert "border: 1px solid" in out


def test_scale_qss_one_is_noop():
    qss = "QLabel { font-size: 13px; padding: 4px 8px; }"
    assert ThemeManager._scale_qss(qss, 1.0) == qss


def test_scale_has_floor():
    qss = "QLabel { font-size: 9px; }"
    assert "font-size: 8px" in ThemeManager._scale_font_sizes(qss, 0.5)


def test_theme_manager_remembers_ui_scale(tmp_path, monkeypatch):
    """apply_accent / theme switching must not drop the UI scale."""
    (tmp_path / "light.qss").write_text("QLabel { font-size: 10px; }",
                                        encoding="utf-8")
    tm = ThemeManager(str(tmp_path))

    class FakeApp:
        def __init__(self):
            self.sheets = []

        def setStyleSheet(self, s):
            self.sheets.append(s)

        def topLevelWidgets(self):
            return []

        def processEvents(self):
            pass

    app = FakeApp()
    tm.apply_theme("light", app, ui_scale=1.5)
    assert "font-size: 15px" in app.sheets[-1]

    # Accent color only, ui_scale not passed explicitly → still 1.5
    tm.apply_accent("#ff0000", app)
    assert "font-size: 15px" in app.sheets[-1]


# --------------------------------------------------------------------------- #
# Sliding page transitions
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_rapid_switch_keeps_current_page_visible(qapp):
    from PySide6.QtWidgets import QWidget, QLabel
    from ui.sliding_stack import SlidingStack
    import time

    stack = SlidingStack()
    stack.resize(400, 300)
    pages = []
    for i in range(3):
        w = QWidget()
        QLabel(f"page{i}", w)
        pages.append(w)
        stack.addWidget(w)
    stack.show()

    stack.setCurrentIndex(0)
    assert stack.currentIndex() == 0
    assert pages[0].isVisible()

    # Simulate rapid clicking: 1 → 2 → 1 → 2
    stack.setCurrentIndex(1)
    stack.setCurrentIndex(2)
    stack.setCurrentIndex(0)
    stack.setCurrentIndex(1)

    current = stack.currentIndex()
    assert current == 1
    # Key regression: the current page must not be hidden by the previous animation's
    # done() (the 1.0.2 "UI disappears" bug)
    assert pages[current].isVisible(), "当前页被误隐藏了"

    # Once the animation finishes only the current page should be visible (otherwise pages stack)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        qapp.processEvents()
        if not stack._busy:
            break
        time.sleep(0.02)
    qapp.processEvents()

    assert [p for p in pages if p.isVisible()] == [pages[current]]


def test_switching_back_and_forth_no_animation(qapp):
    from PySide6.QtWidgets import QWidget
    from ui.sliding_stack import SlidingStack

    stack = SlidingStack()
    stack.resize(400, 300)
    stack.set_animation_enabled(False)
    pages = [QWidget(), QWidget()]
    for w in pages:
        stack.addWidget(w)
    stack.show()

    stack.setCurrentIndex(0)
    stack.setCurrentIndex(1)
    stack.setCurrentIndex(0)
    assert stack.currentIndex() == 0
    assert pages[0].isVisible() and not pages[1].isVisible()


# --------------------------------------------------------------------------- #
# UI scale takes effect live + restart entry point
#
# The 1.0.4 problem: changing the scale only wrote the config, the UI changed on the
# next start, and there was no restart prompt/button — users reported "changed it and
# nothing happened, and there's no restart option either".
# --------------------------------------------------------------------------- #
def test_build_restart_command_frozen():
    from ui.main_window import build_restart_command

    program, args = build_restart_command(
        ["MaaAuto.exe", "--minimized", "--upgrading", "--autostart"],
        frozen=True, executable=r"C:\Apps\MaaAuto\MaaAuto.exe")

    assert program == r"C:\Apps\MaaAuto\MaaAuto.exe"
    # --upgrading / --autostart must be stripped: a restart should show the window, not go silently to tray
    assert args == ["--minimized"]


def test_build_restart_command_dev_mode():
    from ui.main_window import build_restart_command

    program, args = build_restart_command(
        ["main.py", "--debug"], frozen=False,
        executable=r"C:\Python311\python.exe")

    assert program == r"C:\Python311\python.exe"
    # In dev mode the script path must be put back, otherwise the new process just starts an interpreter
    assert args[0].endswith("main.py")
    assert args[1:] == ["--debug"]


def test_apply_ui_scale_live_repaints_and_widens_sidebar(qapp, tmp_path):
    """After a scale switch: QSS font-size is rewritten proportionally right away and the sidebar widens."""
    from ui.main_window import apply_ui_scale_live

    (tmp_path / "light.qss").write_text(
        "* { font-size: 10px; }\nQLabel#PageTitle { font-size: 20px; }",
        encoding="utf-8")
    tm = ThemeManager(str(tmp_path))

    class FakeSidebar:
        def __init__(self):
            self.scale = None

        def set_scale(self, value):
            self.scale = value

    sidebar = FakeSidebar()
    previous = qapp.styleSheet()
    try:
        scale = apply_ui_scale_live(tm, qapp, 1.5, theme="light",
                                    sidebar=sidebar)
        assert scale == 1.5
        sheet = qapp.styleSheet()
        assert "font-size: 15px" in sheet      # 10 * 1.5
        assert "font-size: 30px" in sheet      # 20 * 1.5
        assert sidebar.scale == 1.5
    finally:
        qapp.setStyleSheet(previous or "")


def test_apply_ui_scale_live_clamps_scale(qapp, tmp_path):
    from ui.main_window import apply_ui_scale_live

    (tmp_path / "light.qss").write_text("QLabel { font-size: 10px; }",
                                        encoding="utf-8")
    tm = ThemeManager(str(tmp_path))
    previous = qapp.styleSheet()
    try:
        assert apply_ui_scale_live(tm, qapp, 5.0, theme="light") == 2.0
        assert apply_ui_scale_live(tm, qapp, "bad", theme="light") == 1.0
    finally:
        qapp.setStyleSheet(previous or "")


def test_sidebar_set_scale_changes_width(qapp):
    from ui.sidebar import Sidebar

    class FakeI18n:
        def t(self, key, **kwargs):
            return key

    bar = Sidebar(FakeI18n(), compact=False, scale=1.0)
    assert bar.minimumWidth() == Sidebar.BASE_WIDTH
    bar.set_scale(1.5)
    assert bar.minimumWidth() == int(round(Sidebar.BASE_WIDTH * 1.5))
    assert bar.maximumWidth() == bar.minimumWidth()      # setFixedWidth
    bar.set_scale(0.5)                                   # floor is 1.0, never narrower than default
    assert bar.minimumWidth() == Sidebar.BASE_WIDTH


def test_time_picker_keeps_value_after_first_tick(qapp):
    """The wheel time picker must not reset "08:00" to 00:00 in the first event loop after startup.

    1.0.4 side effect observed in the field: on every start the scheduled run time was
    changed to 00:00 and persisted, which also clobbered other settings written at the
    same moment (UI scale / theme) with the stale config snapshot.
    """
    from PySide6.QtCore import QTime
    from ui.wheel_time_picker import WheelTimePicker

    picker = WheelTimePicker()
    picker.setTime(QTime.fromString("08:00", "HH:mm"))
    emits = []
    picker.timeChanged.connect(lambda t: emits.append(t.toString("HH:mm")))

    qapp.processEvents()          # let the singleShot(0) queued at construction run

    assert picker.time().toString("HH:mm") == "08:00"
    assert emits == [], "初始化对齐滚动条时不应 emit timeChanged"


def test_switch_and_swatch_scale_with_ui(qapp):
    """Custom-painted / fixed-size controls must scale too, otherwise the switch is still 44×24 at 150%."""
    from ui.components import Switch, AccentColorPicker

    sw = Switch()
    assert (sw.minimumWidth(), sw.minimumHeight()) == (Switch.BASE_WIDTH,
                                                      Switch.BASE_HEIGHT)
    sw.set_ui_scale(1.5)
    assert (sw.minimumWidth(), sw.minimumHeight()) == (66, 36)

    picker = AccentColorPicker()
    picker.set_ui_scale(1.5)
    swatch = next(iter(picker._swatches.values()))
    assert (swatch.minimumWidth(), swatch.minimumHeight()) == (36, 36)


def test_wheel_column_scales_and_keeps_value(qapp):
    from PySide6.QtCore import QTime
    from ui.wheel_time_picker import WheelTimePicker, WheelColumn

    column = WheelColumn([f"{h:02d}" for h in range(24)])
    column.set_value("08")
    assert column.value() == "08"

    column.set_ui_scale(1.5)
    assert column.ITEM_HEIGHT == int(round(WheelColumn.BASE_ITEM_HEIGHT * 1.5))
    assert column.minimumHeight() == column.ITEM_HEIGHT
    # After recomputing the item height the scrollbar must realign without losing the value
    assert column.value() == "08"

    picker = WheelTimePicker()
    picker.setTime(QTime.fromString("08:30", "HH:mm"))
    picker.set_ui_scale(1.25)
    assert picker.time().toString("HH:mm") == "08:30"


def test_settings_page_scales_painted_widgets(qapp):
    from config_manager import DEFAULT_CONFIG
    from ui.pages.settings_page import SettingsPage

    class FakeI18n:
        current_lang = "zh_CN"

        def t(self, key, **kwargs):
            return key

        def available_languages(self):
            return [("zh_CN", "简体中文")]

    cfg = dict(DEFAULT_CONFIG)
    cfg["ui_scale"] = 1.5
    page = SettingsPage(cfg, FakeI18n(), None)
    try:
        for sw, _key in page._switches:
            assert sw.minimumWidth() == 66 and sw.minimumHeight() == 36
        # Schedule editor (weekday buttons + slot list) scales proportionally
        assert page.schedule_editor._day_buttons[0][1].width() == 51
        assert page.schedule_editor.list.height() == 132
        assert page.accent_picker._swatches
    finally:
        page.deleteLater()


def test_sidebar_live_scale_updates_logo_and_padding(qapp):
    from ui.sidebar import Sidebar

    class FakeI18n:
        def t(self, key, **kwargs):
            return key

    bar = Sidebar(FakeI18n(), compact=False, scale=1.0)
    assert bar._logo.width() == 28
    bar.set_scale(1.5)
    assert bar._logo.width() == 42
    assert bar._layout.contentsMargins().left() == 18
    assert bar.minimumWidth() == int(round(Sidebar.BASE_WIDTH * 1.5))


def test_spawn_new_instance_normalizes_tuple(qapp, monkeypatch):
    """PySide6's static startDetached returns (ok, pid); a tuple must not be used as a truthy value."""
    import ui.main_window as mw

    class FakeQProcess:
        result = (False, 0)

        @staticmethod
        def startDetached(program, args, cwd=""):
            return FakeQProcess.result

    monkeypatch.setattr(mw, "QProcess", FakeQProcess)

    FakeQProcess.result = (False, 0)
    assert mw.spawn_new_instance("x", []) is False
    FakeQProcess.result = (True, 4242)
    assert mw.spawn_new_instance("x", []) is True
    FakeQProcess.result = True           # older API: plain bool
    assert mw.spawn_new_instance("x", []) is True


def test_sidebar_scaled_at_construction(qapp):
    """If ui_scale is already 1.5 at startup, margins/icon must be proportional from the start (not only after a switch)."""
    from ui.sidebar import Sidebar

    class FakeI18n:
        def t(self, key, **kwargs):
            return key

    bar = Sidebar(FakeI18n(), compact=False, scale=1.5)
    assert bar.minimumWidth() == int(round(Sidebar.BASE_WIDTH * 1.5))
    assert bar._logo.width() == 42
    assert bar._layout.contentsMargins().left() == 18
    assert bar._header_gap.sizeHint().height() == 33


def test_settings_page_emits_ui_scale_and_restart(qapp):
    from config_manager import DEFAULT_CONFIG
    from ui.pages.settings_page import SettingsPage

    class FakeI18n:
        current_lang = "zh_CN"

        def t(self, key, **kwargs):
            return key

        def available_languages(self):
            return [("zh_CN", "简体中文")]

    page = SettingsPage(dict(DEFAULT_CONFIG), FakeI18n(), None)
    try:
        scales = []
        restarts = []
        page.ui_scale_changed.connect(scales.append)
        page.restart_requested.connect(lambda: restarts.append(True))

        page.ui_scale_combo.setCurrentIndex(
            page.ui_scale_combo.findData(1.5))
        assert scales == [1.5]

        page.btn_restart.click()
        assert restarts == [True]
    finally:
        page.deleteLater()


def test_main_window_applies_scale_without_restart(qapp, tmp_path, monkeypatch):
    """Whole-window regression: after switching to 150% the UI repaints at once, the sidebar widens, and it asks about restarting."""
    import time

    import config_manager
    from i18n import init_i18n
    from themes import ThemeManager
    from ui.main_window import MainWindow
    from utils import resource_path

    monkeypatch.setattr(config_manager, "CONFIG_FILE",
                        str(tmp_path / "config.json"))
    cfg = dict(config_manager.DEFAULT_CONFIG)
    cfg.update({"kill_on_exit": False, "auto_check_update": False,
                "minimize_to_tray": False, "minimize_on_task": False,
                "show_animation": False, "auto_start": False})
    config_manager.save_config(cfg)

    i18n = init_i18n(resource_path("i18n"))
    assert i18n.load_language("zh_CN")
    tm = ThemeManager(resource_path("themes"))
    tm.apply_theme("light", qapp, ui_scale=1.0)

    win = MainWindow(i18n, tm)
    try:
        for timer in (win.schedule_timer, win.countdown_timer,
                      win._upgrading_check_timer):
            timer.stop()

        asked = []
        monkeypatch.setattr(win, "_ask_restart",
                            lambda scale: asked.append(scale))

        base_width = win.sidebar._base_width
        win._on_ui_scale_changed(1.5)
        qapp.processEvents()                   # let theme_transition's singleShot(0) run

        assert win.config["ui_scale"] == 1.5
        assert "font-size: 20px" in qapp.styleSheet()   # 13 * 1.5 = 19.5 → 20
        assert win.sidebar.minimumWidth() == int(round(base_width * 1.5))

        deadline = time.time() + 2.0
        while time.time() < deadline and not asked:
            qapp.processEvents()
            time.sleep(0.02)
        assert asked == [1.5], "切换缩放后没有弹出「是否立即重启」"
    finally:
        for timer in (win.schedule_timer, win.countdown_timer,
                      win._upgrading_check_timer):
            timer.stop()
        win.is_quitting = True
        win.hide()
        win.tray.hide()
        win.deleteLater()
        qapp.processEvents()


def test_main_window_restart_confirm_true_restarts(qapp, tmp_path, monkeypatch):
    """Confirming "restart now" goes through restart_app; choosing "later" does nothing."""
    import config_manager
    from i18n import init_i18n
    from themes import ThemeManager
    from ui.main_window import MainWindow
    from utils import resource_path

    monkeypatch.setattr(config_manager, "CONFIG_FILE",
                        str(tmp_path / "config.json"))
    cfg = dict(config_manager.DEFAULT_CONFIG)
    cfg.update({"kill_on_exit": False, "auto_check_update": False,
                "minimize_to_tray": False, "show_animation": False})
    config_manager.save_config(cfg)

    i18n = init_i18n(resource_path("i18n"))
    i18n.load_language("zh_CN")
    tm = ThemeManager(resource_path("themes"))

    win = MainWindow(i18n, tm)
    try:
        for timer in (win.schedule_timer, win.countdown_timer,
                      win._upgrading_check_timer):
            timer.stop()

        restarted = []
        monkeypatch.setattr(win, "restart_app", lambda: restarted.append(True))

        monkeypatch.setattr(win, "_confirm_restart", lambda scale: True)
        win._ask_restart(1.25)
        assert restarted == [True]

        restarted.clear()
        monkeypatch.setattr(win, "_confirm_restart", lambda scale: False)
        win._ask_restart(1.25)
        assert restarted == []
    finally:
        for timer in (win.schedule_timer, win.countdown_timer,
                      win._upgrading_check_timer):
            timer.stop()
        win.is_quitting = True
        win.hide()
        win.tray.hide()
        win.deleteLater()
        qapp.processEvents()

def test_settings_page_round_trips_log_retention(qapp):
    """Log retention days must really round-trip through the config (1.1.1).

    This guards against a past regression: 1.1.0's ``click_activate`` had a settings
    toggle and wrote the config, but the runtime never read it, so the toggle did
    nothing. Every new setting needs at least a control ↔ get_config round trip.
    """
    from config_manager import DEFAULT_CONFIG
    from ui.pages.settings_page import SettingsPage

    class FakeI18n:
        current_lang = "zh_CN"

        def t(self, key, **kwargs):
            return key

        def available_languages(self):
            return [("zh_CN", "简体中文")]

    cfg = dict(DEFAULT_CONFIG)
    cfg["log_retention_days"] = 30
    page = SettingsPage(cfg, FakeI18n(), None)
    try:
        assert page.log_retention_spin.value() == 30
        emitted = []
        page.config_changed.connect(emitted.append)
        # IntLineEdit only emits valueChanged when editing finishes (Enter / focus out)
        page.log_retention_spin.setText("7")
        page.log_retention_spin.editingFinished.emit()
        assert page.get_config()["log_retention_days"] == 7
        assert emitted, "改动日志保留天数应触发自动保存"
    finally:
        page.deleteLater()
