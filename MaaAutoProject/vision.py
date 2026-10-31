"""Screen image search adapted to multiple resolutions and DPI scales.

Why this was rewritten
----------------------
In 1.0.x the search was this single line:

    pyautogui.locateCenterOnScreen("maa_start.png", confidence=0.75, grayscale=True)

It had three hard flaws:

1. **Size mismatch**: templates were captured at one DPI scale. At 125% / 150%, or on
   a machine with another resolution, the on-screen button is a size larger, the
   correlation drops across the board, and the button "cannot be found" while it is
   plainly there.
2. **Full-screen scan every time**: 1-2 s per scan at 1920x1080, and anything on screen
   that merely looks similar can match (say the same icon on another button).
3. **No window restriction**: a hit need not come from the target app, and a stray
   click has consequences no one can control.

What this module does
---------------------
    grab(region)  captures only the target window client area (or the whole screen)
    find(...)     multi-scale template matching in memory
      - the scale range comes from config, default [0.6, 2.0], centred on the current
        system DPI;
      - the coarse pass runs on a half-resolution image (~4x faster), then the hit is
        refined at full resolution in a small window;
      - templates can be overridden per user: ``config/templates/<name>`` wins over the
        bundled ``resources/<name>``, so a user can re-capture after a resolution
        change instead of waiting for a release.

Coordinate system
-----------------
``main.py`` declares per-monitor-v2 DPI awareness with
``SetProcessDpiAwarenessContext(-4)``, so ``ImageGrab`` pixels, the ``GetWindowRect``
rectangle and ``SetCursorPos`` coordinates all share **one screen physical pixel
space**. No logical/physical conversion happens here; returned coordinates go
straight to input_driver for clicking.

Dependencies: opencv (opencv-python-headless) + Pillow. Without cv2, find() errors
out rather than silently degrading to "exact pixel matching", which would only
surface the problem on an installed build.
"""

import ctypes
import dataclasses
import logging
import os

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except Exception:                                  # pragma: no cover - environment dependent
    cv2 = None
    HAS_CV2 = False

from PIL import ImageGrab

logger = logging.getLogger("MaaAuto")

# score at which the coarse pass stops trying further scales (refined later anyway)
FAST_ACCEPT = 0.92


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class Match:
    """One hit; coordinates are screen physical pixels."""

    left: int
    top: int
    width: int
    height: int
    score: float
    scale: float
    template: str = ""

    @property
    def center(self):
        return (self.left + self.width // 2, self.top + self.height // 2)

    def __str__(self):
        cx, cy = self.center
        return (f"{self.template or '?'}@({cx},{cy}) "
                f"score={self.score:.3f} scale={self.scale:.2f} "
                f"box={self.width}x{self.height}")


# --------------------------------------------------------------------------- #
# DPI
# --------------------------------------------------------------------------- #
def dpi_scale() -> float:
    """System DPI as a multiple of 96 (1.0 = 100%, 1.25 = 125%).

    Used only as the search's **preferred centre**; a wrong value costs a few extra scales, never a miss.
    """
    try:
        # Win10 1607+; the process already declares DPI awareness, so this is the physical DPI
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        try:
            dpi = int(gdi32.GetDeviceCaps(hdc, 88))   # LOGPIXELSX
        finally:
            user32.ReleaseDC(0, hdc)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


# --------------------------------------------------------------------------- #
# Screenshot
# --------------------------------------------------------------------------- #
def grab(region=None):
    """Capture the screen as a BGR ndarray.

    :param region: ``(left, top, right, bottom)`` in screen physical pixels; None = the whole virtual screen.
    :return: ndarray, or None on failure.
    """
    bbox = None
    if region is not None:
        left, top, right, bottom = (int(round(v)) for v in region)
        if right - left < 2 or bottom - top < 2:
            return None
        bbox = (left, top, right, bottom)

    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception as e:
        logger.debug(f"截图失败 region={region}: {e}")
        return None

    arr = np.asarray(img.convert("RGB"))
    if arr.size == 0:
        return None
    if HAS_CV2:
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr


def grab_gray(region=None):
    """Capture the screen in grayscale (matching only needs gray, and it saves 2/3 of the memory)."""
    img = grab(region)
    if img is None:
        return None
    if HAS_CV2:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img[:, :, 0].copy()


def save_png(bgr_image, path):
    """Save a grab() BGR image as PNG (used for failure screenshots)."""
    from PIL import Image
    if bgr_image is None:
        return False
    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB) if HAS_CV2 else bgr_image
    Image.fromarray(rgb).save(path)
    return True


# --------------------------------------------------------------------------- #
# Template loading (cached)
# --------------------------------------------------------------------------- #
_TEMPLATE_CACHE = {}
_TEMPLATE_CACHE_LIMIT = 32


def _template_gray(path):
    """Load a template as grayscale, cached by (path, mtime, size).

    Uses ``np.fromfile + cv2.imdecode`` rather than ``cv2.imread``: the latter silently
    returns None for paths with non-ASCII characters (common with CJK user names).
    """
    try:
        st = os.stat(path)
    except OSError:
        return None

    key = (os.path.abspath(path), int(st.st_mtime_ns), st.st_size)
    hit = _TEMPLATE_CACHE.get(key)
    if hit is not None:
        return hit

    try:
        buf = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    except Exception as e:
        logger.error(f"读取模板失败 {path}: {e}")
        return None
    if img is None:
        logger.error(f"模板无法解码（不是有效图片？）: {path}")
        return None

    if len(_TEMPLATE_CACHE) >= _TEMPLATE_CACHE_LIMIT:
        _TEMPLATE_CACHE.clear()
    _TEMPLATE_CACHE[key] = img
    return img


# --------------------------------------------------------------------------- #
# Multi-scale matching
# --------------------------------------------------------------------------- #
def _resize(gray, scale):
    h, w = gray.shape[:2]
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    if (nh, nw) == (h, w):
        return gray
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(gray, (nw, nh), interpolation=interp)


MIN_TEMPLATE_PX = 16        # templates smaller than this after scaling are not matched (noise matches too well)
BLUR_KSIZE = 3              # soften before matching: tolerant of 1px strokes and half-pixel misalignment


def _match_one(screen, tpl, scale):
    """Match once at the given scale; returns (score, x, y, w, h) or None.

    Image and template get the same 3x3 Gaussian blur first. Without it, a text button
    off by 1% in scale (1 px on 132 px) shifts every 1 px stroke and the correlation
    falls from 0.99 to 0.83 - "not found" while it is right there; with the blur the
    same shift still scores 0.96.
    """
    t = _resize(tpl, scale)
    th, tw = t.shape[:2]
    sh, sw = screen.shape[:2]
    if th > sh or tw > sw or th < MIN_TEMPLATE_PX or tw < MIN_TEMPLATE_PX:
        return None
    if BLUR_KSIZE >= 3:
        screen = cv2.GaussianBlur(screen, (BLUR_KSIZE, BLUR_KSIZE), 0)
        t = cv2.GaussianBlur(t, (BLUR_KSIZE, BLUR_KSIZE), 0)
    res = cv2.matchTemplate(screen, t, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    return float(max_val), int(max_loc[0]), int(max_loc[1]), tw, th


def _scale_list(scale_min, scale_max, step):
    step = max(0.01, float(step))
    lo = max(0.1, float(scale_min))
    hi = max(lo + step, float(scale_max))
    count = int(round((hi - lo) / step)) + 1
    out = [round(lo + i * step, 4) for i in range(count)]
    if out[-1] < hi - 1e-9:
        out.append(round(hi, 4))
    return out


def _ordered_scales(scales, center):
    """Sort scales by distance from the DPI centre."""
    center = max(0.1, float(center))
    return sorted(scales, key=lambda s: abs(s - center))


def _refine_scales(center, span=0.12, step=0.02):
    lo = max(0.1, center - span)
    hi = center + span
    out = [round(lo + i * step, 4)
           for i in range(int(round((hi - lo) / step)) + 1)]
    return _ordered_scales(out + [round(center, 4)], center)


def find(image_path, region=None, threshold=0.8, scale_min=0.6,
         scale_max=2.0, scale_step=0.05, dpi_hint=True):
    """Find a template on screen (or inside region); returns the best Match, or None.

    :param image_path: path of the template PNG
    :param region:     ``(l, t, r, b)``, usually the target window client area; None = full screen
    :param threshold:  correlation threshold (0-1)
    :param dpi_hint:   whether to centre the search on the current system DPI
    """
    if not HAS_CV2:
        logger.error("缺少 opencv，无法执行多尺度找图。请安装 opencv-python-headless。")
        return None

    tpl = _template_gray(image_path)
    if tpl is None:
        return None

    screen = grab_gray(region)
    if screen is None:
        return None

    off_x, off_y = (int(round(region[0])), int(round(region[1]))) if region else (0, 0)

    scales = _scale_list(scale_min, scale_max, scale_step)
    center = dpi_scale() if dpi_hint else 1.0
    # DPI only reorders the search, it never widens the user's range:
    # some set 100%-100% purely for speed, and forcing 1.25 makes them wait a pass for nothing.
    scales = _ordered_scales(scales, center)

    # ---- coarse pass: half resolution ----
    sh, sw = screen.shape[:2]
    if sh >= 120 and sw >= 120:
        half = cv2.resize(screen, (sw // 2, sh // 2), interpolation=cv2.INTER_AREA)
        factor = 2.0
    else:
        half = screen
        factor = 1.0

    coarse = []
    for s in scales:
        r = _match_one(half, tpl, s / factor)
        if r is None:
            continue
        coarse.append((r[0], s, int(r[1] * factor), int(r[2] * factor),
                       int(r[3] * factor), int(r[4] * factor)))
        if r[0] >= FAST_ACCEPT:
            break

    if not coarse:
        return None
    coarse.sort(key=lambda item: item[0], reverse=True)

    # ---- refine: top two scales, back to full resolution, small window around each hit ----
    best = None
    pad = 24
    for score, s, x, y, tw, th in coarse[:2]:
        left = max(0, x - pad)
        top = max(0, y - pad)
        right = min(sw, x + tw + pad)
        bottom = min(sh, y + th + pad)
        if right - left < 8 or bottom - top < 8:
            continue
        roi = screen[top:bottom, left:right]
        for fs in _refine_scales(s):
            m = _match_one(roi, tpl, fs)
            if m is None:
                continue
            candidate = (m[0], fs, left + m[1], top + m[2], m[3], m[4])
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        return None

    score, scale, x, y, w, h = best
    if score < threshold:
        logger.debug(
            f"找图未达阈值: {os.path.basename(image_path)} "
            f"best={score:.3f} (阈值 {threshold:.2f}, 尺度 {scale:.2f})")
        return None

    return Match(left=x + off_x, top=y + off_y, width=w, height=h,
                 score=score, scale=scale,
                 template=os.path.basename(image_path))


def find_any(paths, region=None, threshold=0.8, scale_min=0.6, scale_max=2.0,
             scale_step=0.05, dpi_hint=True):
    """Find the best match among several templates (one target in several sizes/styles).

    The list is ordered by priority; when scores are close the highest still wins.
    """
    best = None
    for path in paths:
        m = find(path, region=region, threshold=threshold, scale_min=scale_min,
                 scale_max=scale_max, scale_step=scale_step, dpi_hint=dpi_hint)
        if m and (best is None or m.score > best.score):
            best = m
    return best


# --------------------------------------------------------------------------- #
# Template path resolution
# --------------------------------------------------------------------------- #
def template_candidates(name, user_dir=None, bundled_dir=None):
    """Candidate template paths: the user directory first, then the bundled resources."""
    out = []
    if user_dir:
        p = os.path.join(user_dir, name)
        if os.path.isfile(p):
            out.append(p)
    if bundled_dir:
        p = os.path.join(bundled_dir, name)
        if os.path.isfile(p):
            out.append(p)
    return out
