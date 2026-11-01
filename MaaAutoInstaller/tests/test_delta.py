"""Delta update tests (new in 1.2.0).

Covers three areas:
* ``bspatch``: the patch applier (pure stdlib) must byte-match ``bsdiff4`` output;
* ``delta``: build -> restore round trip, base mismatch rejection, delete list;
* ``payload.apply_delta``: replace / rollback / protected dirs untouched on a real install dir.
"""

import zipfile
from pathlib import Path

import pytest

from installer.core import bspatch, delta, payload


# --------------------------------------------------------------------------- #
# bspatch
# --------------------------------------------------------------------------- #
def test_bspatch_roundtrip_shapes():
    import bsdiff4

    cases = [
        (b"", b"hello"),
        (b"abc" * 500, b"abc" * 400 + b"tail"),
        (bytes(range(256)) * 40, bytes(range(256)) * 39 + b"END"),
    ]
    for old, new in cases:
        patch = bsdiff4.diff(old, new)
        assert bspatch.apply_patch(old, patch) == new


def test_bspatch_rejects_garbage():
    with pytest.raises(ValueError):
        bspatch.apply_patch(b"abc", b"not a patch")
    # header declares a negative length (top bit set) -> must be rejected
    bad_header = b"BSDIFF40" + b"\xff" * 8 + b"\x00" * 8 + b"\x00" * 8
    with pytest.raises(ValueError):
        bspatch.apply_patch(b"abc", bad_header)
    # declared block length exceeds the actual data -> must be rejected
    truncated = (b"BSDIFF40" + bspatch._offtout(100)
                 + bspatch._offtout(0) + bspatch._offtout(10))
    with pytest.raises(ValueError):
        bspatch.apply_patch(b"abc", truncated)


# --------------------------------------------------------------------------- #
# delta build / restore
# --------------------------------------------------------------------------- #
def _write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_pair(tmp_path: Path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    # unchanged
    _write(old / "_internal/stable.dll", b"S" * 4096)
    _write(new / "_internal/stable.dll", b"S" * 4096)
    # small change (good fit for a patch)
    _write(old / "MaaAuto.exe", b"M" * 20000)
    _write(new / "MaaAuto.exe", b"M" * 19000 + b"CHANGED" * 100)
    # added
    _write(new / "_internal/new.dll", b"N" * 1024)
    # deleted
    _write(old / "_internal/gone.dll", b"G" * 1024)
    return old, new


def test_build_and_materialize_roundtrip(tmp_path):
    old, new = make_pair(tmp_path)
    out = tmp_path / "delta.zip"
    stat = delta.build_delta(new, old, out, "1.2.0", "1.1.1")

    assert out.exists()
    assert stat["patch_files"] >= 1          # MaaAuto.exe should go through a patch
    assert stat["deleted"] == 1              # gone.dll is on the delete list

    stage = tmp_path / "stage"
    count, deletes = delta.materialize(out, old, stage)
    assert count == stat["patch_files"] + stat["full_files"]
    assert deletes == ["_internal/gone.dll"]

    # restored files must be byte-identical to the target
    for rel in ("MaaAuto.exe", "_internal/new.dll"):
        assert (stage / rel).read_bytes() == (new / rel).read_bytes()
    # unchanged files should not be in the package
    assert not (stage / "_internal/stable.dll").exists()


def test_base_mismatch_is_detected(tmp_path):
    old, new = make_pair(tmp_path)
    out = tmp_path / "delta.zip"
    delta.build_delta(new, old, out, "1.2.0", "1.1.1")

    # tamper with the local base file (simulates a user replacing files by hand)
    _write(old / "MaaAuto.exe", b"X" * 20000)
    with pytest.raises(delta.BaseMismatch):
        delta.materialize(out, old, tmp_path / "stage")


def test_delta_delete_list_is_applied_by_apply_delta(tmp_path):
    """apply_delta on a real install dir: replace + delete + protect config."""
    install = tmp_path / "app"
    old, new = make_pair(tmp_path)
    # make the install dir start out identical to old
    for src in old.rglob("*"):
        if src.is_file():
            _write(install / src.relative_to(old), src.read_bytes())
    _write(install / "config" / "config.json", b'{"keep": true}')
    _write(install / "_internal/gone.dll", b"G" * 1024)

    out = tmp_path / "delta.zip"
    delta.build_delta(new, old, out, "1.2.0", "1.1.1")

    result = payload.apply_delta(install, out)
    assert result.success and result.via_delta

    assert (install / "MaaAuto.exe").read_bytes() == (new / "MaaAuto.exe").read_bytes()
    assert (install / "_internal/new.dll").exists()
    assert not (install / "_internal/gone.dll").exists()      # delete list applied
    assert (install / "config" / "config.json").exists()      # user data untouched


def test_apply_delta_reports_base_mismatch(tmp_path):
    install = tmp_path / "app"
    old, new = make_pair(tmp_path)
    for src in old.rglob("*"):
        if src.is_file():
            _write(install / src.relative_to(old), src.read_bytes())
    out = tmp_path / "delta.zip"
    delta.build_delta(new, old, out, "1.2.0", "1.1.1")

    _write(install / "MaaAuto.exe", b"tampered")

    result = payload.apply_delta(install, out)
    assert not result.success
    assert result.base_mismatch          # caller falls back to the full package based on this
    # a failure must not leave stray directories
    leftovers = list(tmp_path.glob(".MaaAuto_new_*")) + list(tmp_path.glob(".MaaAuto_bak_*"))
    assert leftovers == []


# --------------------------------------------------------------------------- #
# asset selection
# --------------------------------------------------------------------------- #
def _release(assets):
    return {"tag_name": "v1.2.0", "assets": assets}


def test_pick_delta_asset_matches_exact_pair():
    assets = [
        {"name": "MaaAuto_payload_v1.2.0.zip", "browser_download_url": "u"},
        {"name": "MaaAuto_delta_v1.1.1_to_1.2.0.zip", "browser_download_url": "d"},
    ]
    got = payload.pick_delta_asset(_release(assets), "1.1.1", "1.2.0")
    assert got and got["browser_download_url"] == "d"
    # no match when the versions do not line up
    assert payload.pick_delta_asset(_release(assets), "1.0.0", "1.2.0") is None
    assert payload.pick_delta_asset(_release(assets), "0.0.0", "1.2.0") is None


def test_check_update_exposes_delta(monkeypatch):
    assets = [
        {"name": "MaaAuto_payload_v1.2.0.zip", "browser_download_url": "p",
         "size": 100, "digest": "sha256:" + "a" * 64},
        {"name": "MaaAuto_delta_v1.1.1_to_1.2.0.zip", "browser_download_url": "d",
         "size": 10, "digest": "sha256:" + "b" * 64},
    ]
    monkeypatch.setattr(payload, "fetch_release", lambda *a, **k: _release(assets))

    class M:
        version = "1.1.1"

    info = payload.check_update(M(), "http://x", "MaaAuto_payload_v")
    assert info.has_update
    assert info.delta_url == "d"
    assert info.delta_size == 10
    assert info.delta_sha == "b" * 64


def test_check_update_without_delta_still_works(monkeypatch):
    assets = [{"name": "MaaAuto_payload_v1.2.0.zip", "browser_download_url": "p",
               "size": 100, "digest": "sha256:" + "a" * 64}]
    monkeypatch.setattr(payload, "fetch_release", lambda *a, **k: _release(assets))

    class M:
        version = "0.9.0"

    info = payload.check_update(M(), "http://x", "MaaAuto_payload_v")
    assert info.has_update
    assert info.delta_url == ""


# --------------------------------------------------------------------------- #
# skipping versions: serial delta chain
# --------------------------------------------------------------------------- #
def _asset(name, size=100):
    return {"name": name, "browser_download_url": "http://x/" + name,
            "size": size, "digest": "sha256:" + "a" * 64}


def test_collect_delta_edges_from_releases():
    releases = [
        {"tag_name": "v1.4.0", "assets": [
            _asset("MaaAuto_payload_v1.4.0.zip"),
            _asset("MaaAuto_delta_v1.3.0_to_1.4.0.zip")]},
        {"tag_name": "v1.3.0", "assets": [
            _asset("MaaAuto_delta_v1.2.0_to_1.3.0.zip")]},
        {"tag_name": "v1.2.0", "draft": True, "assets": [
            _asset("MaaAuto_delta_v1.1.0_to_1.2.0.zip")]},   # draft, must be ignored
    ]
    edges = payload.collect_delta_edges(releases)
    assert "1.2.0" in edges and "1.3.0" in edges["1.2.0"]
    assert "1.3.0" in edges and "1.4.0" in edges["1.3.0"]
    assert "1.1.0" not in edges          # draft does not count


def test_find_delta_chain_multi_hop():
    edges = {
        "1.2.0": {"1.3.0": _asset("MaaAuto_delta_v1.2.0_to_1.3.0.zip")},
        "1.3.0": {"1.4.0": _asset("MaaAuto_delta_v1.3.0_to_1.4.0.zip")},
    }
    chain = payload.find_delta_chain(edges, "1.2.0", "1.4.0")
    assert [a["name"] for a in chain] == [
        "MaaAuto_delta_v1.2.0_to_1.3.0.zip",
        "MaaAuto_delta_v1.3.0_to_1.4.0.zip"]


def test_find_delta_chain_no_path_or_too_many_hops():
    edges = {"1.0.0": {"1.1.0": _asset("MaaAuto_delta_v1.0.0_to_1.1.0.zip")}}
    assert payload.find_delta_chain(edges, "1.0.0", "1.4.0") == []
    assert payload.find_delta_chain(edges, "1.4.0", "1.0.0") == []
    assert payload.find_delta_chain(edges, "1.1.0", "1.1.0") == []


def test_apply_delta_chain_two_steps(tmp_path):
    """A is installed, then A->B and B->C are applied; the result must match C exactly."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    _write(a / "MaaAuto.exe", b"A" * 20000)
    _write(a / "keep.dll", b"K" * 1000)
    _write(b / "MaaAuto.exe", b"A" * 19000 + b"B" * 1000)
    _write(b / "keep.dll", b"K" * 1000)
    _write(b / "_internal/mid.dll", b"M" * 500)
    _write(c / "MaaAuto.exe", b"A" * 18000 + b"B" * 1000 + b"C" * 1000)
    _write(c / "keep.dll", b"K" * 1000)
    _write(c / "_internal/mid.dll", b"M" * 500)
    _write(c / "_internal/new.dll", b"N" * 400)

    d_ab = tmp_path / "ab.zip"
    d_bc = tmp_path / "bc.zip"
    delta.build_delta(b, a, d_ab, "1.3.0", "1.2.0")
    delta.build_delta(c, b, d_bc, "1.4.0", "1.3.0")

    install = tmp_path / "app"
    for src in a.rglob("*"):
        if src.is_file():
            _write(install / src.relative_to(a), src.read_bytes())
    _write(install / "config" / "config.json", b'{"keep": true}')

    result = payload.apply_delta_chain(install, [d_ab, d_bc])
    assert result.success and result.via_delta

    for rel in ("MaaAuto.exe", "keep.dll", "_internal/mid.dll", "_internal/new.dll"):
        assert (install / rel).read_bytes() == (c / rel).read_bytes(), rel
    assert (install / "config" / "config.json").exists()


def test_apply_delta_chain_reports_mismatch_without_touching_install(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a / "MaaAuto.exe", b"A" * 5000)
    _write(b / "MaaAuto.exe", b"B" * 5000)
    d_ab = tmp_path / "ab.zip"
    delta.build_delta(b, a, d_ab, "1.3.0", "1.2.0")

    install = tmp_path / "app"
    _write(install / "MaaAuto.exe", b"tampered")

    result = payload.apply_delta_chain(install, [d_ab])
    assert not result.success and result.base_mismatch
    # not a single byte of the install dir may change
    assert (install / "MaaAuto.exe").read_bytes() == b"tampered"
