"""屏幕找图：多分辨率 / 多 DPI 缩放适配。

为什么重写
----------
1.0.x 的找图是这一行：

    pyautogui.locateCenterOnScreen("maa_start.png", confidence=0.75, grayscale=True)

三个硬伤：

1. **尺寸不匹配**：模板是在某个 DPI 缩放比下截的。换到 125% / 150% 缩放、
   或者换一台分辨率不同的机器后，屏幕上的按钮比模板大一圈，相关系数被整体
   压低，于是「找不到按钮」——而图明明就在屏幕上。
2. **每次全屏扫**：1920×1080 下扫一次 1~2 秒；而且整个屏幕里任何长得像的
   元素都可能被命中（比如另一个按钮上的同款图标）。
3. **无法限定窗口**：命中的位置未必来自目标程序，误点后果不可控。

本模块的做法
------------
    grab(region)  只截目标窗口客户区（或全屏）
    find(...)     在内存里做多尺度模板匹配
      · 缩放比由配置给出，默认覆盖 [0.6, 2.0]，并用当前系统 DPI 作为优先中心；
      · 粗搜在半分辨率图上跑（约快 4 倍），命中后回原分辨率、小范围精修；
      · 模板支持用户覆盖：``config/templates/<name>`` 优先于内置
        ``resources/<name>``，用户换分辨率后可以自己重截模板，不必等发版。

坐标系约定
----------
main.py 里已用 ``SetProcessDpiAwarenessContext(-4)`` 声明 per-monitor-v2 DPI 感知，
因此 ``ImageGrab`` 的像素、``GetWindowRect`` 的窗口矩形、``SetCursorPos`` 的
坐标**都在同一套屏幕物理像素空间**里。本模块内部不做逻辑/物理换算，
返回的坐标可以直接交给 input_driver 点击。

依赖：opencv（opencv-python-headless）+ Pillow。cv2 缺失时 find() 会直接报错，
不会静默降级成「精确像素匹配」——那会让问题在安装版上才暴露。
"""

import ctypes
import dataclasses
import logging
import os

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except Exception:                                  # pragma: no cover - 环境相关
    cv2 = None
    HAS_CV2 = False

from PIL import ImageGrab

logger = logging.getLogger("MaaAuto")

# 粗搜命中多少分就不必再试别的尺度（后面还会精修）
FAST_ACCEPT = 0.92


# --------------------------------------------------------------------------- #
# 结果
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class Match:
    """一次命中。坐标全部是屏幕物理像素，left/top 为模板左上角。"""

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
    """当前系统 DPI 相对于 96 的倍数（1.0=100%，1.25=125%）。

    只作为多尺度搜索的**优先中心**，判错也不会导致找不到图，只会多试几个尺度。
    """
    try:
        # Win10 1607+；进程已声明 DPI 感知，返回值即物理 DPI
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
# 截图
# --------------------------------------------------------------------------- #
def grab(region=None):
    """截取屏幕（BGR ndarray）。

    :param region: ``(left, top, right, bottom)`` 屏幕物理像素；None 表示整个虚拟屏幕。
    :return: ndarray，失败返回 None。
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
    """截取屏幕并转灰度（匹配只需要灰度，省 2/3 内存）。"""
    img = grab(region)
    if img is None:
        return None
    if HAS_CV2:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img[:, :, 0].copy()


def save_png(bgr_image, path):
    """把 grab() 返回的 BGR 图存成 PNG（用于失败现场截图）。"""
    from PIL import Image
    if bgr_image is None:
        return False
    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB) if HAS_CV2 else bgr_image
    Image.fromarray(rgb).save(path)
    return True


# --------------------------------------------------------------------------- #
# 模板加载（带缓存）
# --------------------------------------------------------------------------- #
_TEMPLATE_CACHE = {}
_TEMPLATE_CACHE_LIMIT = 32


def _template_gray(path):
    """读取模板为灰度图，按 (路径, mtime, 大小) 缓存。

    用 ``np.fromfile + cv2.imdecode`` 而不是 ``cv2.imread``：后者在含非 ASCII
    字符的路径上（常见于中文用户名）会静默返回 None。
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
# 多尺度匹配
# --------------------------------------------------------------------------- #
def _resize(gray, scale):
    h, w = gray.shape[:2]
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    if (nh, nw) == (h, w):
        return gray
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(gray, (nw, nh), interpolation=interp)


MIN_TEMPLATE_PX = 16        # 缩放后小于这个尺寸的模板不参与匹配（噪声会长得像）
BLUR_KSIZE = 3              # 匹配前柔和一下：对 1px 笔画与半像素错位不敏感


def _match_one(screen, tpl, scale):
    """在 screen 里按给定缩放比找一次，返回 (score, x, y, w, h) 或 None。

    匹配前对画面和模板做同样的 3×3 高斯模糊。不模糊时，文字按钮只要缩放比
    差 1%（132px 宽差 1px），1px 笔画就整体错位，相关系数从 0.99 掉到 0.83——
    明明在屏幕上却「找不到」；模糊后同样的错位仍有 0.96。
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
    """把离 DPI 中心最近的尺度排前面：常见情况（模板与屏幕同缩放）第一次就命中。"""
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
    """在屏幕（或 region 内）寻找模板，返回最优 Match，找不到返回 None。

    :param image_path: 模板 PNG 路径
    :param region:     ``(l, t, r, b)``，一般传目标窗口客户区；None = 全屏
    :param threshold:  相关系数阈值（0~1）
    :param dpi_hint:   是否用当前系统 DPI 作为搜索优先中心
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
    # DPI 只是「优先顺序」的提示，不擅自扩大用户设定的区间：
    # 有人把区间设成 100%~100% 是为了提速，硬塞 1.25 会让他白等一轮。
    scales = _ordered_scales(scales, center)

    # ---- 粗搜：半分辨率 ----
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

    # ---- 精修：取前两个尺度，回原分辨率、围绕候选点小范围重匹配 ----
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
    """在多个模板里找最优的一个（同一目标的多种尺寸/样式）。

    模板列表按优先级排列；命中分数差距很小时仍取最高分。
    """
    best = None
    for path in paths:
        m = find(path, region=region, threshold=threshold, scale_min=scale_min,
                 scale_max=scale_max, scale_step=scale_step, dpi_hint=dpi_hint)
        if m and (best is None or m.score > best.score):
            best = m
    return best


# --------------------------------------------------------------------------- #
# 模板路径解析
# --------------------------------------------------------------------------- #
def template_candidates(name, user_dir=None, bundled_dir=None):
    """返回候选模板路径：用户目录优先，其次内置资源。"""
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
