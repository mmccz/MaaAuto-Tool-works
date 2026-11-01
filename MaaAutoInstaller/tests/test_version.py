"""Tests for version parsing / comparison / payload asset matching / channel selection.

These are the most common causes of a broken upgrade: a version string parsed
wrong, so no new version is seen; or an asset name that does not match, so no
download URL is found.
"""

import pytest

from installer.core import manifest as manifest_mod
from installer.core import payload


# --------------------------------------------------------------------------- #
# version parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("1.0.0", (1, 0, 0, 3, 0, 0)),
    ("v1.0.1b1", (1, 0, 1, 1, 1, 0)),
    ("1.0.1rc2", (1, 0, 1, 2, 2, 0)),
    ("1.0.1a3", (1, 0, 1, 0, 3, 0)),
    ("1.0.1.post4", (1, 0, 1, 3, 0, 4)),
    ("  2.10.3  ", (2, 10, 3, 3, 0, 0)),
])
def test_parse_version_valid(text, expected):
    assert payload.parse_version(text) == expected


@pytest.mark.parametrize("text", ["", None, "1.0", "1.0.0.0", "abc", "1.0.0-beta.1"])
def test_parse_version_invalid(text):
    assert payload.parse_version(text) is None


@pytest.mark.parametrize("a,b,expected", [
    ("1.0.1", "1.0.0", 1),
    ("1.0.0", "1.0.1", -1),
    ("1.0.0", "1.0.0", 0),
    ("1.0.1b1", "1.0.0", 1),        # a prerelease is still newer than an older stable
    ("1.0.1b1", "1.0.1", -1),       # but older than the same version's stable
    ("1.0.1b2", "1.0.1b1", 1),
    ("1.0.1rc1", "1.0.1b9", 1),
])
def test_compare_versions(a, b, expected):
    assert payload.compare_versions(a, b) == expected


def test_compare_versions_invalid():
    assert payload.compare_versions("bad", "1.0.0") is None


# --------------------------------------------------------------------------- #
# payload assets
# --------------------------------------------------------------------------- #
def test_pick_payload_asset_exact_name():
    release = {"assets": [
        {"name": "MaaAuto_payload_v1.0.1b1.zip", "size": 10},
        {"name": "MaaAuto_Setup_v1.0.1b1-Windows-x64.exe", "size": 99},
    ]}
    asset = payload.pick_payload_asset(release, "1.0.1b1", "MaaAuto_payload_v")
    assert asset["size"] == 10


def test_pick_payload_asset_is_case_insensitive():
    release = {"assets": [{"name": "maaauto_PAYLOAD_v1.0.0.ZIP"}]}
    assert payload.pick_payload_asset(release, "1.0.0", "MaaAuto_payload_v")


def test_pick_payload_asset_missing_returns_none():
    release = {"assets": [{"name": "other.zip"}]}
    assert payload.pick_payload_asset(release, "1.0.0", "MaaAuto_payload_v") is None


def test_sha_from_asset_digest():
    asset = {"digest": "sha256:ABCDEF123"}
    assert payload._sha_from_asset(asset) == "abcdef123"
    assert payload._sha_from_asset({"digest": ""}) == ""
    assert payload._sha_from_asset({}) == ""


# --------------------------------------------------------------------------- #
# channel / check_update
# --------------------------------------------------------------------------- #
def _release(tag, payload_prefix="MaaAuto_payload_v", version=None):
    version = version or tag.lstrip("v")
    return {
        "tag_name": tag,
        "body": "notes",
        "html_url": "https://example.invalid/rel",
        "draft": False,
        "prerelease": tag != "v1.0.0",
        "assets": [{
            "name": f"{payload_prefix}{version}.zip",
            "browser_download_url": "https://example.invalid/p.zip",
            "size": 1234,
            "digest": "sha256:aa",
        }],
    }


def test_check_update_finds_newer(monkeypatch):
    monkeypatch.setattr(payload, "fetch_release",
                        lambda api, channel: _release("v1.0.2"))
    info = payload.check_update(manifest_mod.Manifest(version="1.0.1"),
                                "https://api/x/releases/latest",
                                "MaaAuto_payload_v")
    assert info.has_update is True
    assert info.latest == "1.0.2"
    assert info.payload_name == "MaaAuto_payload_v1.0.2.zip"
    assert info.payload_sha == "aa"


def test_check_update_up_to_date(monkeypatch):
    monkeypatch.setattr(payload, "fetch_release",
                        lambda api, channel: _release("v1.0.1"))
    info = payload.check_update(manifest_mod.Manifest(version="1.0.1"),
                                "https://api/x/releases/latest",
                                "MaaAuto_payload_v")
    assert info.has_update is False
    assert info.error == ""


def test_check_update_ignores_older_without_downgrade(monkeypatch):
    monkeypatch.setattr(payload, "fetch_release",
                        lambda api, channel: _release("v1.0.0"))
    info = payload.check_update(manifest_mod.Manifest(version="1.0.1"),
                                "https://api/x/releases/latest",
                                "MaaAuto_payload_v")
    assert info.has_update is False


def test_check_update_allows_downgrade(monkeypatch):
    monkeypatch.setattr(payload, "fetch_release",
                        lambda api, channel: _release("v1.0.0"))
    info = payload.check_update(manifest_mod.Manifest(version="1.0.1"),
                                "https://api/x/releases/latest",
                                "MaaAuto_payload_v",
                                allow_downgrade=True)
    assert info.has_update is True


def test_check_update_reports_api_error(monkeypatch):
    def boom(api, channel):
        raise OSError("network down")

    monkeypatch.setattr(payload, "fetch_release", boom)
    info = payload.check_update(manifest_mod.Manifest(version="1.0.0"),
                                "https://api/x/releases/latest",
                                "MaaAuto_payload_v")
    assert info.has_update is False
    assert "无法访问更新接口" in info.error


def test_check_update_missing_asset(monkeypatch):
    rel = _release("v1.0.2")
    rel["assets"] = []
    monkeypatch.setattr(payload, "fetch_release", lambda api, channel: rel)
    info = payload.check_update(manifest_mod.Manifest(version="1.0.0"),
                                "https://api/x/releases/latest",
                                "MaaAuto_payload_v")
    assert info.has_update is False
    assert "找不到" in info.error


def test_list_api_strips_latest():
    assert payload._list_api("https://api/repos/x/releases/latest") == \
        "https://api/repos/x/releases"
    assert payload._list_api("https://api/repos/x/releases/") == \
        "https://api/repos/x/releases"


def test_fetch_release_beta_picks_highest(monkeypatch):
    releases = [_release("v1.0.0"), _release("v1.0.2b1"), _release("v1.0.1b1"),
                dict(_release("v9.9.9"), draft=True)]
    monkeypatch.setattr(payload, "_request_json", lambda url, timeout=20: releases)
    rel = payload.fetch_release("https://api/x/releases/latest", "beta")
    assert rel["tag_name"] == "v1.0.2b1"


def test_fetch_release_stable_uses_latest(monkeypatch):
    calls = []

    def fake_json(url, timeout=20):
        calls.append(url)
        return _release("v1.0.0")

    monkeypatch.setattr(payload, "_request_json", fake_json)
    payload.fetch_release("https://api/x/releases/latest", "stable")
    assert calls == ["https://api/x/releases/latest"]


def test_version_file_matches_package_version():
    """build_release.py reads ``MaaAutoInstaller/VERSION`` for the manifest, so it must
    match ``installer.__version__`` -- a stale file shipped a Setup whose manifest said
    1.4.5 while the package was 1.4.6, and the release smoke test caught it only on CI."""
    from pathlib import Path

    import installer

    pkg_root = Path(__file__).resolve().parent.parent
    pkg_root = pkg_root if (pkg_root / "installer").is_dir() else pkg_root / "MaaAutoInstaller"
    version_file = pkg_root / "VERSION"
    assert version_file.read_text(encoding="utf-8").strip() == installer.__version__
