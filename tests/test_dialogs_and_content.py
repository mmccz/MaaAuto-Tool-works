"""Regression tests for content added in 1.0.6: update dialog, announcements,
tutorial, restart not killing processes, and ghosting.

Deliberately covers the points users reported after testing:
  * clicking "restart app" shut down a running MAA / MuMu too (atexit ran cleanup again);
  * switching UI scale occasionally left a ghost image (the old frame mask was not
    cleared before the layout change);
  * the version tag/link was unreadable in the dark theme;
  * the update dialog dumped raw GitHub Markdown into a QMessageBox, which looked awful;
  * the tutorial must include both MAA "exit emulator when done" and MaaEnd
    "close program as the last step".
"""

import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MaaAutoProject")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

RES = os.path.join(APP_DIR, "resources")


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


# --------------------------------------------------------------------------- #
# Announcements
# --------------------------------------------------------------------------- #
def test_bundled_announcements_are_complete():
    from ui.announcements import load_bundled_announcements, localize

    updated, items = load_bundled_announcements()
    assert updated, "announcements.json 缺少 updated"
    assert len(items) >= 3, "公告太少，至少覆盖版本更新 + 使用提醒"
    ids = [it.get("id") for it in items]
    assert len(ids) == len(set(ids)), f"公告 id 重复: {ids}"
    for item in items:
        assert item.get("id") and item.get("date") and item.get("tag")
        for lang in ("zh_CN", "en_US"):
            loc = localize(item, lang)
            assert loc["title"].strip(), f"{item['id']} 缺 {lang} 标题"
            assert loc["body"].strip(), f"{item['id']} 缺 {lang} 正文"


def test_unseen_ids_and_unread_state():
    from ui.announcements import unseen_ids, unread_state

    items = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"no_id": True}]
    assert unseen_ids(items, []) == ["a", "b", "c"]
    assert unseen_ids(items, ["a"]) == ["b", "c"]
    assert unseen_ids(items, ["a", "b", "c"]) == []

    # New announcements: the number equals how many are new
    st = unread_state(items, "2026-10-24", ["a"], "2026-10-24")
    assert st["count"] == 2 and st["new_ids"] == ["b", "c"]

    # All seen and updated is unchanged → 0
    st = unread_state(items, "2026-10-24", ["a", "b", "c"], "2026-10-24")
    assert st["count"] == 0

    # All seen but the content changed (updated moved) → at least one prompt
    st = unread_state(items, "2026-10-25", ["a", "b", "c"], "2026-10-24")
    assert st["count"] == 1 and st["updated_changed"] and st["new_ids"] == []


def test_parse_announcements_handles_bad_payload():
    from ui.announcements import parse_announcements

    assert parse_announcements("not json") == ("", [])
    assert parse_announcements(b'{"items": "nope"}') == ("", [])
    assert parse_announcements({"items": [{"id": "x"}, {"no": 1}]}) == (
        "", [{"id": "x"}])
    updated, items = parse_announcements(
        '{"updated": "2026-10-24", "items": [{"id": "x"}]}')
    assert updated == "2026-10-24" and items == [{"id": "x"}]


def test_cache_roundtrip_and_newer_wins(tmp_path):
    from ui.announcements import (save_cache, load_cached_announcements,
                                  initial_announcements)

    items = [{"id": "remote-1", "date": "2026-10-24", "tag": "t",
              "title": {"zh_CN": "标题", "en_US": "title"},
              "body": {"zh_CN": "正文", "en_US": "body"}}]
    assert save_cache("2999-01-01", items, config_dir=str(tmp_path))
    updated, got = load_cached_announcements(str(tmp_path))
    assert updated == "2999-01-01" and got == items
    # Cache newer than bundled → updated comes from the cache; items are the union
    # of bundled + cache (since 1.3.0 it no longer replaces everything, otherwise a
    # stale mirror would bump out newer announcements)
    u2, items2 = initial_announcements(str(tmp_path))
    assert u2 == "2999-01-01"
    ids2 = {it["id"] for it in items2}
    assert {"remote-1"} <= ids2 and len(items2) >= len(items)


def test_remote_urls_point_at_github():
    from ui.announcements import remote_urls

    urls = remote_urls()
    assert urls, "没有配置在线公告地址"
    assert any("raw.githubusercontent.com" in u for u in urls)
    assert all(u.startswith("https://") for u in urls)


def test_announcement_dialog_shows_first_item(qapp, i18n):
    from ui.announcements import AnnouncementDialog, initial_announcements

    _, items = initial_announcements()
    dlg = AnnouncementDialog(i18n, items, "zh_CN", updated="2026-10-24")
    try:
        assert dlg.list.count() == len(items)
        assert "2026-10-24" in dlg.subtitle_label.text()
        # 1.3.0: the right side holds every announcement as one long text, the left list navigates
        text = dlg.browser.toPlainText()
        for item in items:
            assert item["title"]["zh_CN"] in text
        dlg.list.setCurrentRow(1)     # navigation must not raise
        qapp.processEvents()
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# Update dialog
# --------------------------------------------------------------------------- #
INFO = {
    "has_update": True,
    "current": "1.0.5",
    "latest": "1.0.6",
    "channel": "stable",
    "html_url": "https://example.com/releases/v1.0.6",
    "notes": "## 1.0.6\n\n### 修复\n\n- 重启不再关掉 MAA\n\n见 [发布页](https://example.com)。",
}


def test_update_dialog_renders_notes_markdown(qapp, i18n):
    from ui.update_dialog import UpdateDialog

    dlg = UpdateDialog(i18n, INFO)
    try:
        text = dlg.notes.toPlainText()
        assert "1.0.6" in text
        assert "重启不再关掉 MAA" in text
        # Markdown markers must not be shown raw (the old QMessageBox bug)
        assert "##" not in text
        assert dlg.btn_update.isDefault()
    finally:
        dlg.deleteLater()


def test_update_dialog_choices(qapp, i18n):
    from PySide6.QtWidgets import QDialog
    from ui.update_dialog import UpdateDialog

    dlg = UpdateDialog(i18n, INFO)
    dlg._on_update()
    assert dlg.chosen == "update"
    assert dlg.result() == QDialog.Accepted

    dlg2 = UpdateDialog(i18n, INFO)
    dlg2._on_later()
    assert dlg2.chosen == "later"
    assert dlg2.result() == QDialog.Rejected

    dlg3 = UpdateDialog(i18n, {**INFO, "html_url": ""})
    assert not dlg3.btn_open.isVisibleTo(dlg3), "没有发布页链接时不该显示按钮"
    dlg3.deleteLater()


def test_update_dialog_without_notes(qapp, i18n):
    from ui.update_dialog import UpdateDialog

    dlg = UpdateDialog(i18n, {**INFO, "notes": ""})
    try:
        assert not hasattr(dlg.notes, "toPlainText")   # fell back to a QLabel
    finally:
        dlg.deleteLater()


def test_colorize_links_uses_theme_color(qapp):
    from PySide6.QtWidgets import QTextBrowser
    from ui.update_dialog import colorize_links, LINK_COLOR_DARK

    browser = QTextBrowser()
    browser.setMarkdown("见 [发布页](https://example.com)。")
    n = colorize_links(browser, LINK_COLOR_DARK)
    assert n == 1
    doc = browser.document()
    block = doc.begin()
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        if frag.isValid() and frag.charFormat().isAnchor():
            assert frag.charFormat().foreground().color().name() == LINK_COLOR_DARK
            break
        it += 1
    else:
        pytest.fail("没找到链接片段")
    browser.deleteLater()


def test_message_dialog_ok(qapp, i18n):
    from PySide6.QtWidgets import QDialog
    from ui.update_dialog import MessageDialog

    dlg = MessageDialog(i18n, i18n.t("update.latest.title"),
                        i18n.t("update.latest.text", current="1.0.6"))
    try:
        assert "1.0.6" in dlg.text_label.text()
        dlg.btn_ok.click()
        assert dlg.result() == QDialog.Accepted
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# Tutorial
# --------------------------------------------------------------------------- #
MANDATORY = [
    ("tutorial.warn_maa", ["完成后退出模拟器"]),
    ("tutorial.warn_maaend", ["关闭程序", "关闭模拟器", "最后"]),
]


def test_tutorial_warns_contain_mandatory_rules(i18n):
    for key, needles in MANDATORY:
        text = i18n.t(key)
        assert text != key, f"缺少翻译键 {key}"
        for needle in needles:
            assert needle in text, f"{key} 里没有「{needle}」：{text}"


def test_tutorial_dialog_has_warning_blocks(qapp, i18n):
    from ui.tutorial_dialog import TutorialDialog

    dlg = TutorialDialog(i18n)
    try:
        warnings = [w for _t, _tk, _b, _bk, w, _wk in dlg._sections
                    if w is not None]
        assert len(warnings) == 2
        assert all(w.objectName() == "TutorialWarning" for w in warnings)
        joined = "\n".join(w.text() for w in warnings)
        assert "完成后退出模拟器" in joined
        assert "关闭程序" in joined or "关闭模拟器" in joined
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# Version tag / announcement badge
# --------------------------------------------------------------------------- #
def test_about_version_tag_uses_qss(qapp, i18n):
    from ui.pages.about_page import AboutPage

    page = AboutPage(i18n)
    try:
        assert page.ver_tag.objectName() == "VersionTag"
        assert page.license_tag.objectName() == "LicenseTag"
        # Colors come from QSS (one set per light/dark theme); no inline style allowed
        assert page.ver_tag.styleSheet() == ""
        assert page.license_tag.styleSheet() == ""
        assert page.ver_tag.text()
    finally:
        page.deleteLater()


def test_about_system_label_uses_system_info(qapp, i18n):
    """1.4.1: the system version must come from system_info (build-number fix for Win11),
    not a hand-built ``platform.release()`` (which returns "10" on Win11)."""
    import system_info
    from ui.pages.about_page import AboutPage

    page = AboutPage(i18n)
    try:
        label = page.env_labels["about.system"][1]
        assert label.text() == system_info.describe_system()
        assert label.text()
    finally:
        page.deleteLater()


def test_home_announcement_badge(qapp, i18n):
    from ui.pages.home_page import HomePage

    page = HomePage(i18n)
    try:
        page.set_announcement_badge(0)
        assert page.btn_announcements.objectName() == "GhostButton"
        page.set_announcement_badge(3)
        assert "3" in page.btn_announcements.text()
        assert page.btn_announcements.objectName() == "GhostButtonHot"
    finally:
        page.deleteLater()


# --------------------------------------------------------------------------- #
# Restart must not kill MAA / the emulator + ghost overlay
# --------------------------------------------------------------------------- #
def _make_window(qapp, tmp_path, monkeypatch):
    import config_manager
    from i18n import init_i18n
    from themes import ThemeManager
    from ui.main_window import MainWindow
    from utils import resource_path

    # Disable the startup guide timers (auto-popped tutorial/announcements + online
    # announcement fetch); otherwise they fire inside later tests' event loops and
    # their background threads are destroyed with QThread warnings.
    import ui.main_window as mw
    real_single_shot = mw.QTimer.singleShot

    def guarded_single_shot(ms, fn, *args, **kwargs):
        if ms in (1200, 2500):
            return
        return real_single_shot(ms, fn, *args, **kwargs)

    monkeypatch.setattr(mw.QTimer, "singleShot",
                        staticmethod(guarded_single_shot))

    monkeypatch.setattr(config_manager, "CONFIG_FILE",
                        str(tmp_path / "config.json"))
    cfg = dict(config_manager.DEFAULT_CONFIG)
    cfg.update({"kill_on_exit": True, "auto_check_update": False,
                "minimize_to_tray": False, "minimize_on_task": False,
                "show_animation": False, "auto_start": False,
                "tutorial_seen": True})
    config_manager.save_config(cfg)

    i18n = init_i18n(resource_path("i18n"))
    i18n.load_language("zh_CN")
    tm = ThemeManager(resource_path("themes"))
    tm.apply_theme("light", qapp, ui_scale=1.0)
    win = MainWindow(i18n, tm)
    for timer in (win.schedule_timer, win.countdown_timer,
                  win._upgrading_check_timer):
        timer.stop()
    return win


def _close_window(win, qapp):
    for timer in (win.schedule_timer, win.countdown_timer,
                  win._upgrading_check_timer):
        timer.stop()
    win.is_quitting = True
    win.hide()
    win.tray.hide()
    win.deleteLater()
    qapp.processEvents()


def test_restart_does_not_kill_related_processes(qapp, tmp_path, monkeypatch):
    import ui.main_window as mw

    calls = []
    monkeypatch.setattr(mw, "kill_all_related_processes",
                        lambda: calls.append(True))
    win = _make_window(qapp, tmp_path, monkeypatch)
    try:
        # Normal exit: should clean up
        win._relaunching = False
        win.cleanup_on_exit()
        assert calls == [True]

        # Restart/upgrade: must leave MAA / the emulator alone
        calls.clear()
        win._relaunching = True
        win.cleanup_on_exit()
        assert calls == []
    finally:
        _close_window(win, qapp)


def test_scale_switch_clears_transition_overlay(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from ui.animations import clear_transition_overlay

    win = _make_window(qapp, tmp_path, monkeypatch)
    try:
        # Simulate the old screenshot overlay left by a previous theme switch
        overlay = QWidget(win)
        overlay.show()
        win._theme_overlay = overlay
        win._on_ui_scale_changed(1.25, ask_restart=False)
        qapp.processEvents()
        assert getattr(win, "_theme_overlay", None) is None, "遮罩没清掉，会留重影"
        # The scale change really took effect
        assert win.sidebar.minimumWidth() > 0
        assert "font-size: 16px" in qapp.styleSheet()   # 13 * 1.25 ≈ 16
        clear_transition_overlay(win)                   # idempotent
    finally:
        _close_window(win, qapp)


def test_announcement_badge_marks_seen(qapp, tmp_path, monkeypatch):
    win = _make_window(qapp, tmp_path, monkeypatch)
    try:
        state = win._refresh_announcement_badge()
        assert state["count"] > 0
        assert "⦁" in win.home_page.btn_announcements.text()
        # Mark everything read and refresh the badge (no modal dialog)
        updated, items = win._announcements_data()
        win.config["announcements_seen"] = [it.get("id") for it in items]
        win.config["announcements_seen_updated"] = updated
        state = win._refresh_announcement_badge()
        assert state["count"] == 0
        assert "⦁" not in win.home_page.btn_announcements.text()

        # Announcement content updated (updated changed, ids unchanged) → badge returns
        win.config["announcements_seen_updated"] = "2000-01-01"
        state = win._refresh_announcement_badge()
        assert state["count"] == 1 and state["updated_changed"]
        assert "⦁" in win.home_page.btn_announcements.text()
    finally:
        _close_window(win, qapp)


def test_settings_snapshot_keeps_runtime_keys(qapp, tmp_path, monkeypatch):
    """A stale settings-page snapshot must not reset tutorial_seen / announcement
    read state back to False.

    Observed bug: after seeing the tutorial, changing any setting made it pop up
    again on the next start — because the settings page saved back the whole config
    it had copied at startup (with tutorial_seen=False).
    """
    win = _make_window(qapp, tmp_path, monkeypatch)
    try:
        win.config["tutorial_seen"] = True
        win.config["announcements_seen"] = ["v1.0.6"]
        win.config["announcements_seen_updated"] = "2026-10-24"
        win.config["run_count"] = 7

        stale = dict(win.settings_page.config)     # snapshot taken at settings-page startup
        stale["tutorial_seen"] = False
        stale["announcements_seen"] = []
        stale["announcements_seen_updated"] = ""
        stale["run_count"] = 0
        stale["wait_timeout"] = 99

        win._on_config_changed(stale)

        assert win.config["tutorial_seen"] is True
        assert win.config["announcements_seen"] == ["v1.0.6"]
        assert win.config["announcements_seen_updated"] == "2026-10-24"
        assert win.config["run_count"] == 7
        # Ordinary settings still update normally
        assert win.config["wait_timeout"] == 99

        import config_manager
        with open(config_manager.CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["tutorial_seen"] is True
        assert saved["run_count"] == 7
    finally:
        _close_window(win, qapp)


def test_background_blur_is_slider(qapp, i18n):
    from config_manager import DEFAULT_CONFIG
    from ui.pages.settings_page import SettingsPage

    class FakeI18n:
        current_lang = "zh_CN"

        def t(self, key, **kwargs):
            return key

        def available_languages(self):
            return [("zh_CN", "简体中文")]

    cfg = dict(DEFAULT_CONFIG)
    cfg["background_blur"] = 12
    page = SettingsPage(cfg, FakeI18n(), None)
    try:
        from PySide6.QtWidgets import QSlider
        assert isinstance(page.bg_blur_slider, QSlider)
        assert page.bg_blur_slider.value() == 12
        assert page.bg_blur_value.text() == "12"

        page.bg_blur_slider.setValue(30)
        qapp.processEvents()
        assert page.bg_blur_value.text() == "30"
        assert page.get_config()["background_blur"] == 30
    finally:
        page.deleteLater()


def test_announcements_marked_read_when_opened(qapp, i18n, tmp_path, monkeypatch):
    """1.3.0: opening the announcements persists them as read immediately, instead of
    waiting for the window to close.

    The old code wrote after exec(): if the user quit or the upgrade process killed the
    app while the window was open, the next start prompted "new announcements" again —
    exactly the "prompts again after restart" reported by users.
    """
    import config_manager
    from themes import ThemeManager
    from ui.main_window import MainWindow
    from utils import resource_path

    monkeypatch.setattr(config_manager, "CONFIG_FILE",
                        str(tmp_path / "config.json"))
    cfg = dict(config_manager.DEFAULT_CONFIG)
    cfg.update({"kill_on_exit": False, "auto_check_update": False,
                "minimize_to_tray": False, "minimize_on_task": False,
                "show_animation": False, "auto_start": False,
                "announcements_seen": [], "announcements_seen_updated": ""})
    config_manager.save_config(cfg)

    tm = ThemeManager(resource_path("themes"))
    tm.apply_theme("light", qapp, ui_scale=1.0)

    win = MainWindow(i18n, tm)
    try:
        for timer in (win.schedule_timer, win.countdown_timer,
                      win._upgrading_check_timer):
            timer.stop()

        import ui.announcements as ann_module

        class FakeDialog:
            def __init__(self, *a, **kw):
                pass

            def exec(self):
                # Simulate "the process is killed while the window is still open":
                # the read state should already be on disk by now
                saved = config_manager.load_config()
                assert saved["announcements_seen"], "打开时就该标记已读"
                assert saved["announcements_seen_updated"]
                return 0

        monkeypatch.setattr(ann_module, "AnnouncementDialog", FakeDialog)
        win.show_announcements()

        assert win._announcements_dialog is None          # reference released after close
        assert config_manager.load_config()["announcements_seen_updated"]
    finally:
        win.is_quitting = True
        win.hide()
        win.tray.hide()
        win.deleteLater()
        qapp.processEvents()


def test_announcement_search_filters_index(qapp, i18n):
    """1.4.0: all past updates live in one announcement area and are found via the search box."""
    from ui.announcements import AnnouncementDialog

    def item(ident, title):
        return {"id": ident, "date": "2026-10-25", "tag": "版本更新",
                "title": {"zh_CN": title, "en_US": title},
                "body": {"zh_CN": f"正文 {ident}", "en_US": f"body {ident}"}}

    items = [item("v1.3.0", "定时多时段"), item("v1.2.0", "差分更新")]
    dlg = AnnouncementDialog(i18n, items, "zh_CN", updated="2026-10-25")
    try:
        assert dlg.list.count() == 2
        dlg.search.setText("1.2.0")
        hidden = [i for i in range(dlg.list.count())
                  if dlg.list.item(i).isHidden()]
        assert len(hidden) == 1
        assert "1" in dlg.count_label.text()          # 1 match
        dlg.search.setText("")
        assert not any(dlg.list.item(i).isHidden()
                       for i in range(dlg.list.count()))
    finally:
        dlg.deleteLater()
