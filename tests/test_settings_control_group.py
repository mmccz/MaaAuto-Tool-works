"""Settings > Run control group (2.0.1): the five keys the injection path needs.

Without this group the control mode / MaaEnd instance / retry policy could only be
changed by hand-editing config.json - which is not a user-facing option.
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


class FakeI18n:
    current_lang = "zh_CN"

    def t(self, key, **kwargs):
        return key

    def available_languages(self):
        return [("zh_CN", "简体中文"), ("en_US", "English")]


def make_page(config=None):
    from config_manager import DEFAULT_CONFIG
    from ui.pages.settings_page import SettingsPage

    cfg = dict(DEFAULT_CONFIG)
    cfg.update(config or {})
    return SettingsPage(cfg, FakeI18n(), None)


def test_group_exists_with_all_widgets(qapp):
    page = make_page()
    assert page.control_seg is not None
    assert page.maaend_instance_combo is not None
    assert page.retry_spin is not None
    assert page.update_policy_seg is not None
    assert page.keep_upstream_sw is not None
    assert "control" in page._groups


def test_defaults_match_the_config_defaults(qapp):
    page = make_page()
    assert page.control_seg.current_value() == "inject"
    assert page.retry_spin.value() == 2
    assert page.update_policy_seg.current_value() == "between-rounds"
    assert page.keep_upstream_sw.isChecked() is False


def test_instance_dropdown_always_offers_the_automatic_entry(qapp):
    page = make_page()
    assert page.maaend_instance_combo.count() >= 1
    assert page.maaend_instance_combo.itemData(0) == ""
    assert page.maaend_instance_combo.itemText(0) == "settings.maaend_instance.auto"


def test_values_round_trip_through_get_config(qapp):
    page = make_page(
        {"control": "click", "maaend_instance": "杂项", "retry": 4, "keep_upstream": True}
    )
    assert page.control_seg.current_value() == "click"
    assert page.retry_spin.value() == 4
    assert page.keep_upstream_sw.isChecked() is True

    page.control_seg.set_current_value("inject")
    page.update_policy_seg.set_current_value("manual")
    page.retry_spin.setValue(1)
    page.keep_upstream_sw.setChecked(True)

    cfg = page.get_config()
    assert cfg["control"] == "inject"
    assert cfg["update_policy"] == "manual"
    assert cfg["retry"] == 1
    assert cfg["keep_upstream"] is True


def test_switching_the_instance_keeps_the_name(qapp):
    page = make_page({"maaend_instance": ""})
    # Simulate the user picking an instance from the dropdown.
    page.maaend_instance_combo.addItem("测试实例", "测试实例")
    page.maaend_instance_combo.setCurrentIndex(page.maaend_instance_combo.count() - 1)
    assert page.get_config()["maaend_instance"] == "测试实例"
