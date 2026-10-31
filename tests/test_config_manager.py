"""Unit tests for config_manager: atomic writes, fallback on bad files, defaults for new keys."""

import json
import os

import pytest

import config_manager as cm


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point CONFIG_FILE at a temp dir so the real config/ is never polluted."""
    cfg_file = tmp_path / "config" / "config.json"
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cm, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(cm, "CONFIG_DIR", str(cfg_file.parent))
    return cfg_file


def test_defaults_when_missing(isolated):
    cfg = cm.load_config()
    assert cfg["click_mode"] == "sendinput"
    assert cfg["search_scope"] == "window"
    assert cfg["match_threshold"] == pytest.approx(0.8)
    assert cfg["ui_scale"] == pytest.approx(1.0)


def test_save_and_load_roundtrip(isolated):
    cfg = cm.load_config()
    cfg["maa_path"] = r"C:\Program Files\带空格 中文\MAA.exe"
    cfg["match_scale_min"] = 0.7
    cfg["click_mode"] = "postmessage"
    cm.save_config(cfg)

    again = cm.load_config()
    assert again["maa_path"] == cfg["maa_path"]
    assert again["match_scale_min"] == pytest.approx(0.7)
    assert again["click_mode"] == "postmessage"


def test_save_is_atomic_leftover_tmp_removed(isolated):
    cm.save_config(cm.load_config())
    assert not os.path.exists(str(isolated) + ".tmp")
    # What lands on disk is complete JSON, never a truncated half
    with open(isolated, "r", encoding="utf-8") as f:
        json.load(f)


def test_broken_json_falls_back_to_defaults(isolated):
    isolated.write_text("{ this is not json", encoding="utf-8")
    cfg = cm.load_config()
    assert cfg["retry_times"] == cm.DEFAULT_CONFIG["retry_times"]


def test_utf8_bom_is_accepted(isolated):
    data = dict(cm.DEFAULT_CONFIG)
    data["maa_path"] = r"D:\中文\MAA.exe"
    isolated.write_bytes(b"\xef\xbb\xbf" + json.dumps(
        data, ensure_ascii=False).encode("utf-8"))

    assert cm.load_config()["maa_path"] == data["maa_path"]


def test_unknown_keys_are_kept(isolated):
    """When old and new versions are mixed, unknown keys must not be dropped (otherwise an upgrade silently eats the config)."""
    isolated.write_text(json.dumps({"future_key": 42}, ensure_ascii=False),
                        encoding="utf-8")
    cfg = cm.load_config()
    assert cfg["future_key"] == 42
    cm.save_config(cfg)
    assert json.loads(isolated.read_text(encoding="utf-8"))["future_key"] == 42
