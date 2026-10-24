"""vision 多尺度找图的单元测试。

覆盖的核心行为（对应「换分辨率/缩放就找不到按钮」这个 bug）：
* 同尺寸模板 → 精确命中；
* 模板被缩小/放大后仍能命中，并且能报出正确的反推缩放比；
* 绝不误命中无关画面；
* region 偏移必须加回屏幕坐标；
* 用户模板目录优先于内置资源。
"""

import numpy as np
import pytest

import vision


# --------------------------------------------------------------------------- #
# 合成画面：低频块 + 少量噪声 + 结构，缩放后仍保留足够特征
# --------------------------------------------------------------------------- #
def make_scene(width=400, height=300, seed=7):
    rng = np.random.default_rng(seed)
    coarse = rng.integers(40, 216, size=(height // 20, width // 20), dtype=np.uint8)
    scene = np.kron(coarse, np.ones((20, 20), dtype=np.uint8))
    noise = rng.integers(-6, 7, size=(height, width))
    scene = np.clip(scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    # 画几条线，保证有高频细节（纯块状图在缩放后峰值太宽）
    for i in range(0, width, 37):
        scene[10:height - 10, i:i + 3] = 20
    for j in range(0, height, 29):
        scene[j:j + 2, 10:width - 10] = 230
    return scene


def save_template(path, gray):
    """用 cv2 直接写灰度 PNG（vision._template_gray 用 imdecode 读）。"""
    assert vision.HAS_CV2
    ok = vision.cv2.imwrite(str(path), gray)
    assert ok


@pytest.fixture
def scene():
    return make_scene()


def match_against(scene, tmp_path, template, monkeypatch, region=None, **kwargs):
    """在合成画面上跑 vision.find（不截真实屏幕）。"""
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
    """模板与屏幕尺寸不同（等价于 DPI/分辨率不同）时仍能找到。"""
    base = scene[70:70 + 70, 100:100 + 100].copy()
    tpl = vision.cv2.resize(base, None, fx=factor, fy=factor,
                            interpolation=vision.cv2.INTER_AREA)

    match = match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.6)

    assert match is not None, f"模板缩放 {factor}x 时未命中"
    # 匹配时用的是「原尺寸」，所以反推的 scale ≈ 1/factor
    assert match.scale == pytest.approx(1.0 / factor, abs=0.12)
    assert match.center[0] == pytest.approx(150, abs=6)
    assert match.center[1] == pytest.approx(105, abs=6)


def test_find_rejects_unrelated(scene, tmp_path, monkeypatch):
    other = make_scene(seed=999)
    tpl = other[40:40 + 60, 40:40 + 60].copy()
    match = match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.8)
    assert match is None


def test_threshold_filters_weak_match(scene, tmp_path, monkeypatch):
    # 缩放过的模板得分只有 ~0.9（重采样会损失细节），用它来测阈值最稳
    base = scene[70:70 + 70, 100:100 + 100].copy()
    tpl = vision.cv2.resize(base, None, fx=0.75, fy=0.75,
                            interpolation=vision.cv2.INTER_AREA)

    assert match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.99) is None
    assert match_against(scene, tmp_path, tpl, monkeypatch, threshold=0.6) is not None


def test_no_absurdly_small_scales(scene, tmp_path, monkeypatch):
    """极小缩放比会让噪声也「长得像」模板，必须直接跳过。"""
    tpl = scene[100:100 + 40, 60:60 + 40].copy()
    # 强制只搜 0.05~0.15：缩放后只有 2~6 像素，应被 MIN_TEMPLATE_PX 挡掉
    match = match_against(scene, tmp_path, tpl, monkeypatch,
                          threshold=0.3, scale_min=0.05, scale_max=0.15)
    assert match is None


def test_region_offset_is_added_back(scene, tmp_path, monkeypatch):
    """限定窗口区域搜索时，返回的坐标必须是屏幕绝对坐标。"""
    region = (200, 60, 400, 300)
    tpl = scene[100:100 + 50, 260:260 + 60].copy()
    match = match_against(scene, tmp_path, tpl, monkeypatch,
                          region=region, threshold=0.8)

    assert match is not None
    # 屏幕绝对坐标 = region 左上角 + 区域内偏移
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
