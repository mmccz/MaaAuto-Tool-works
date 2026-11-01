"""Tests for reading and writing the manifest (.maaauto.json).

This is the contract file between installer and updater: a wrong field name, a
dropped unknown field, or a stale timestamp makes the upgrade logic read the
wrong version.
"""

import json

from installer.core import manifest as m


def test_write_read_roundtrip(tmp_path):
    man = m.Manifest(version="1.0.1", installer_version="1.0.1",
                     install_dir=str(tmp_path), app_exe="MaaAuto.exe")
    path = m.write_manifest(tmp_path, man)

    assert path.exists()
    again = m.read_manifest(tmp_path)
    assert again.version == "1.0.1"
    assert again.app_exe == "MaaAuto.exe"
    assert again.manifest_version == m.MANIFEST_VERSION


def test_timestamps_set_on_write(tmp_path):
    man = m.Manifest(version="1.0.0")
    m.write_manifest(tmp_path, man)
    again = m.read_manifest(tmp_path)
    assert again.installed_at
    assert again.updated_at


def test_installed_at_is_not_overwritten(tmp_path):
    man = m.Manifest(version="1.0.0", installed_at="2020-01-01T00:00:00")
    m.write_manifest(tmp_path, man)
    assert m.read_manifest(tmp_path).installed_at == "2020-01-01T00:00:00"


def test_unknown_fields_are_filtered(tmp_path):
    (tmp_path / m.MANIFEST_NAME).write_text(json.dumps({
        "version": "2.0.0",
        "brand_new_field": {"x": 1},
    }), encoding="utf-8")

    man = m.read_manifest(tmp_path)
    assert man.version == "2.0.0"
    assert not hasattr(man, "brand_new_field")


def test_missing_file_returns_none(tmp_path):
    assert m.read_manifest(tmp_path) is None


def test_corrupt_file_returns_none(tmp_path):
    (tmp_path / m.MANIFEST_NAME).write_text("{oops", encoding="utf-8")
    assert m.read_manifest(tmp_path) is None


def test_extra_roundtrip(tmp_path):
    man = m.Manifest(version="1.0.0", extra={
        "update_api": "https://api/x", "payload_asset_prefix": "MaaAuto_payload_v"})
    m.write_manifest(tmp_path, man)
    again = m.read_manifest(tmp_path)
    assert again.extra["update_api"] == "https://api/x"
