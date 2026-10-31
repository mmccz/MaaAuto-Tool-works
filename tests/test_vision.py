"""Unit tests for vision's multi-scale template matching.

Covers the core behavior behind the "buttons not found after a resolution/scale change" bug:
* same-size template -> exact hit;
* template shrunk/enlarged still matches, with the correct inferred scale back;
* never falsely matches an unrelated screen;
* region offset must be added back to screen coordinates;
* the user template directory takes precedence over bundled resources.
"""

import numpy as np
import pytest

import vision


# --------------------------------------------------------------------------- #
# Synthetic scene: low-frequency blocks + light noise + structure, so enough
# features survive rescaling
# --------------------------------------------------------------------------- #
def make_scene(width=400, height=300, seed=7):
    rng = np.random.default_rng(seed)
    coarse = rng.integers(40, 216, size=(height // 20, width // 20), dtype=np.uint8)
    scene = np.kron(coarse, np.ones((20, 20), dtype=np.uint8))
    noise = rng.integers(-6, 7, size=(height, width))
    scene = np.clip(scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    # Draw a few lines to keep high-frequency detail (pure block images produce
    # peaks that are too wide after rescaling)
    for i in range(0, width, 37):
        scene[10:height - 10, i:i + 3] = 20
    for j in range(0, height, 29):
        scene[j:j + 2, 10:width - 10] = 230
    return scene


def save_template(path, gray):
    """Write a grayscale PNG directly via cv2 (vision._template_gray reads it with imdecode)."""
    assert vision.HAS_CV2
    ok = vision.cv2.imwrite(str(path), gray)
    assert ok


@pytest.fixture
def scene():
    return make_scene()


def match_against(scene, tmp_path, template, monkeypatch, region=None, **kwargs):
    """Run vision.find on the synthetic scene instead of the real screen."""
    path = tmp_path / "tpl.png"
    save_template(path, template)

    def fake_grab_gray(region_arg=None):
        if region is None:
            return scene
        left, top, right, bottom = region
        return scene[top:bottom, left:right]

    monkeypatch.setattr(vision, "grab_gray", fake_grab_gray)
    return vision.find(str(path), region=region, **kwargs)


def test_find_exact_scale(scene, tmp_path, monkeypatch):
    tpl = scene[80:80 + 60, 120:120 + 90].copy()
    match = match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.8)

    assert match is not None
    assert match.score > 0.95
    assert abs(match.scale - 1.0) < 0.06
    assert abs(match.left - 120) <= 2
    assert abs(match.top - 80) <= 2
    assert match.width == pytest.approx(90, abs=4)
    assert match.center[0] == pytest.approx(165, abs=3)


@pytest.mark.parametrize("factor", [0.75, 0.85, 1.25, 1.4])
def test_find_scaled_template(scene, tmp_path, monkeypatch, factor):
    """Template and screen differ in size (equivalent to a different DPI/resolution) and still match."""
    base = scene[70:70 + 70, 100:100 + 100].copy()
    tpl = vision.cv2.resize(base, None, fx=factor, fy=factor,
                            interpolation=vision.cv2.INTER_AREA)

    match = match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.6)

    assert match is not None, f"模板缩放 {factor}x 时未命中"
    # Matching runs against the "original size", so the inferred scale is ~1/factor
    assert match.scale == pytest.approx(1.0 / factor, abs=0.12)
    assert match.center[0] == pytest.approx(150, abs=6)
    assert match.center[1] == pytest.approx(105, abs=6)


def test_one_percent_scale_error_still_matches(scene, tmp_path, monkeypatch):
    """A 1% scale error (1px on a 132px button) must not lose score: this is the 1.4.4 regression."""
    tpl = scene[80:80 + 60, 120:120 + 90].copy()
    tpl = vision.cv2.resize(tpl, None, fx=1.01, fy=1.01,
                            interpolation=vision.cv2.INTER_CUBIC)
    match = match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.8)
    assert match is not None
    assert match.score > 0.9


def test_find_rejects_unrelated(scene, tmp_path, monkeypatch):
    other = make_scene(seed=999)
    tpl = other[40:40 + 60, 40:40 + 60].copy()
    match = match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.8)
    assert match is None


def test_threshold_filters_weak_match(scene, tmp_path, monkeypatch):
    # Since 1.4.4 matching blurs with a 3x3 kernel first, so resampling/noise are
    # tolerated (0.96+). A "squashed template" therefore makes a stable mid score
    # (about 0.74) for testing the threshold.
    base = scene[70:70 + 70, 100:100 + 100].copy()
    tpl = vision.cv2.resize(base, (100, 40), interpolation=vision.cv2.INTER_AREA)

    assert match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.8) is None
    assert match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.6) is not None


def test_no_absurdly_small_scales(scene, tmp_path, monkeypatch):
    """Tiny scales make noise "look like" the template, so they must be skipped outright."""
    tpl = scene[100:100 + 40, 60:60 + 40].copy()
    # Force a 0.05~0.15 search: only 2~6 pixels after scaling, so MIN_TEMPLATE_PX rejects it
    match = match_against(scene, tmp_path, tpl, monkeypatch,
                          threshold=0.3, scale_min=0.05, scale_max=0.15)
    assert match is None


def test_region_offset_is_added_back(scene, tmp_path, monkeypatch):
    """When searching a limited window region, returned coordinates must be absolute screen coordinates."""
    region = (200, 60, 400, 300)
    tpl = scene[100:100 + 50, 260:260 + 60].copy()
    match = match_against(scene, tmp_path, tpl, monkeypatch,
                          region=region, threshold=0.8)

    assert match is not None
    # Absolute screen position = region top-left + offset inside the region
    assert match.left == pytest.approx(260, abs=3)
    assert match.top == pytest.approx(100, abs=3)


def test_missing_template_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "grab_gray", lambda region=None: make_scene())
    assert vision.find(str(tmp_path / "nope.png")) is None


def test_template_candidates_user_dir_first(tmp_path):
    user = tmp_path / "user"
    bundled = tmp_path / "bundled"
    user.mkdir()
    bundled.mkdir()
    (user / "a.png").write_bytes(b"x")
    (bundled / "a.png").write_bytes(b"y")

    paths = vision.template_candidates("a.png", str(user), str(bundled))
    assert len(paths) == 2
    assert paths[0].startswith(str(user))


def test_template_candidates_only_bundled(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "b.png").write_bytes(b"y")
    paths = vision.template_candidates("b.png", str(tmp_path / "missing"), str(bundled))
    assert len(paths) == 1
    assert paths[0].startswith(str(bundled))
    assert vision.template_candidates("zzz.png", None, str(bundled)) == []


def test_scale_list_and_ordering():
    scales = vision._scale_list(0.6, 2.0, 0.05)
    assert scales[0] == pytest.approx(0.6)
    assert scales[-1] == pytest.approx(2.0)
    assert all(b > a for a, b in zip(scales, scales[1:]))

    ordered = vision._ordered_scales(scales, 1.25)
    assert ordered[0] == pytest.approx(1.25, abs=0.05)
    assert set(ordered) == set(scales)

    refined = vision._refine_scales(1.0)
    assert all(0.8 <= s <= 1.2 for s in refined)
    assert refined[0] == pytest.approx(1.0)


def test_dpi_scale_is_sane():
    scale = vision.dpi_scale()
    assert 0.5 <= scale <= 4.0


def test_match_center_and_str():
    m = vision.Match(left=100, top=50, width=60, height=20, score=0.9,
                     scale=1.0, template="a.png")
    assert m.center == (130, 60)
    assert "a.png" in str(m) and "0.900" in str(m)
