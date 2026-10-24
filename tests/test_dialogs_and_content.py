"""1.0.6 新增内容的回归测试：升级弹窗、公告、新手教程、重启不杀进程、重影。

这里刻意覆盖「用户实测反馈过」的点：
  * 点「重启程序」把已开的 MAA / MuMu 一起关掉（atexit 又调了一次 cleanup）；
  * 切换界面缩放偶发重影（旧画面遮罩没在改布局前清掉）；
  * 深色主题下版本号标签/链接看不清；
  * 升级弹窗把 GitHub Markdown 原样塞进 QMessageBox，很难看；
  * 新手教程必须包含 MAA「完成后退出模拟器」与 MaaEnd「最后一条关闭程序」两条。
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
# 公告
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

    # 有新公告：数字 = 新公告条数
    st = unread_state(items, "2026-10-24", ["a"], "2026-10-24")
    assert st["count"] == 2 and st["new_ids"] == ["b", "c"]

    # 全部看过、updated 没变 → 0
    st = unread_state(items, "2026-10-24", ["a", "b", "c"], "2026-10-24")
    assert st["count"] == 0

    # 全部看过但公告内容更新（updated 变化）→ 至少 1 条提示
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
    # 缓存比内置新 → initial 用缓存
    u2, items2 = initial_announcements(str(tmp_path))
    assert u2 == "2999-01-01" and items2 == items


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
        dlg.list.setCurrentRow(1)
        qapp.processEvents()
        assert dlg.item_title.text() == items[1]["title"]["zh_CN"]
        assert dlg.browser.toPlainText().strip()
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# 升级弹窗
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
        # 不能把 Markdown 标记原样显示出来（旧版 QMessageBox 的问题）
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
        assert not hasattr(dlg.notes, "toPlainText")   # 落到了 QLabel 兜底
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
# 新手教程
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
# 版本标签 / 公告红点
# --------------------------------------------------------------------------- #
def test_about_version_tag_uses_qss(qapp, i18n):
    from ui.pages.about_page import AboutPage

    page = AboutPage(i18n)
    try:
        assert page.ver_tag.objectName() == "VersionTag"
        assert page.license_tag.objectName() == "LicenseTag"
        # 颜色交给 QSS（深浅主题各一套），不能再写内联样式
        assert page.ver_tag.styleSheet() == ""
        assert page.license_tag.styleSheet() == ""
        assert page.ver_tag.text()
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
# 重启不杀 MAA / 模拟器 + 重影遮罩
# --------------------------------------------------------------------------- #
def _make_window(qapp, tmp_path, monkeypatch):
    import config_manager
    from i18n import init_i18n
    from themes import ThemeManager
    from ui.main_window import MainWindow
    from utils import resource_path

    # 屏蔽启动引导定时器（教程/公告自动弹 + 在线公告拉取），否则它们会在
    # 后续测试的事件循环里触发、后台线程被析构时报 QThread 警告。
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
        # 正常退出：应该清理
        win._relaunching = False
        win.cleanup_on_exit()
        assert calls == [True]

        # 重启/升级：不能动 MAA / 模拟器
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
        # 模拟「上一次换主题留下的旧截图遮罩」
        overlay = QWidget(win)
        overlay.show()
        win._theme_overlay = overlay
        win._on_ui_scale_changed(1.25, ask_restart=False)
        qapp.processEvents()
        assert getattr(win, "_theme_overlay", None) is None, "遮罩没清掉，会留重影"
        # 缩放确实生效了
        assert win.sidebar.minimumWidth() > 0
        assert "font-size: 16px" in qapp.styleSheet()   # 13 * 1.25 ≈ 16
        clear_transition_overlay(win)                   # 幂等
    finally:
        _close_window(win, qapp)


def test_announcement_badge_marks_seen(qapp, tmp_path, monkeypatch):
    win = _make_window(qapp, tmp_path, monkeypatch)
    try:
        state = win._refresh_announcement_badge()
        assert state["count"] > 0
        assert "⦁" in win.home_page.btn_announcements.text()
        # 直接标记已读并刷新红点（不弹模态窗）
        updated, items = win._announcements_data()
        win.config["announcements_seen"] = [it.get("id") for it in items]
        win.config["announcements_seen_updated"] = updated
        state = win._refresh_announcement_badge()
        assert state["count"] == 0
        assert "⦁" not in win.home_page.btn_announcements.text()

        # 公告内容更新（updated 变了、id 没变）→ 红点重新出现
        win.config["announcements_seen_updated"] = "2000-01-01"
        state = win._refresh_announcement_badge()
        assert state["count"] == 1 and state["updated_changed"]
        assert "⦁" in win.home_page.btn_announcements.text()
    finally:
        _close_window(win, qapp)


def test_settings_snapshot_keeps_runtime_keys(qapp, tmp_path, monkeypatch):
    """设置页的旧快照不能把 tutorial_seen / 公告已读冲回 False。

    实测 bug：看过教程后随便改一个设置，下次启动教程又弹了 —— 因为设置页
    保存时把启动时复制的整份配置（tutorial_seen=False）发了回来。
    """
    win = _make_window(qapp, tmp_path, monkeypatch)
    try:
        win.config["tutorial_seen"] = True
        win.config["announcements_seen"] = ["v1.0.6"]
        win.config["announcements_seen_updated"] = "2026-10-24"
        win.config["run_count"] = 7

        stale = dict(win.settings_page.config)     # 设置页启动时的旧快照
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
        # 普通设置项仍然正常更新
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
