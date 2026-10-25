import os
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt, QRect

# 模糊前把图缩到这个尺寸再放大：背景图本来就铺满窗口、还要压暗，
# 细节看不出来，但高斯模糊的耗时对边长近似平方 —— 缩一半就快 4 倍。
BLUR_MAX_SIDE = 1280


class BackgroundWidget(QWidget):
    """支持背景图片（透明度/模糊/缩放模式）的根容器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BackgroundRoot")
        self._pixmap = None
        self._mode = "cover"
        # 上次真正渲染用的参数；用于跳过重复解码
        self._params = None
        # 解码 + 缩放后的底图，只在「换图/换缩放模式」时重算（模糊/透明度都不重复解码）
        self._base = None
        self._base_key = None

    # ------------------------------------------------------------------ #
    def _load_base(self, image_path):
        """读取并（按需）缩放到 ``BLUR_MAX_SIDE``，结果缓存。"""
        try:
            mtime = os.path.getmtime(image_path)
        except OSError:
            mtime = None
        key = (image_path, mtime)
        if key == self._base_key and self._base is not None:
            return self._base
        try:
            from PIL import Image
            img = Image.open(image_path).convert("RGBA")
        except Exception:
            self._base_key = key
            self._base = None
            return None
        longest = max(img.width, img.height)
        if longest > BLUR_MAX_SIDE:
            scale = BLUR_MAX_SIDE / float(longest)
            img = img.resize((max(1, int(img.width * scale)),
                              max(1, int(img.height * scale))), Image.LANCZOS)
        self._base_key = key
        self._base = img
        self._blur_cache = {}          # 换了图，旧的模糊结果作废
        return img

    def _apply_blur(self, img, blur):
        from PIL import ImageFilter
        self._blur_cache = getattr(self, "_blur_cache", {})
        radius = int(blur)
        cached = self._blur_cache.get(radius)
        if cached is not None:
            return cached
        blurred = img.filter(ImageFilter.GaussianBlur(radius))
        # 只保留最近 3 档，避免拖滑杆时缓存无限涨
        if len(self._blur_cache) > 3:
            self._blur_cache.pop(next(iter(self._blur_cache)))
        self._blur_cache[radius] = blurred
        return blurred

    def set_background(self, image_path, opacity=0.3, blur=0, mode="cover"):
        try:
            mtime = os.path.getmtime(image_path) if image_path else None
        except OSError:
            mtime = None
        params = (image_path or "", round(float(opacity or 0), 3),
                  int(blur or 0), mode, mtime)
        if params == self._params:
            return
        self._params = params
        self._mode = mode

        if not image_path or not os.path.exists(image_path):
            self._pixmap = None
            self._base = None
            self._base_key = None
            self._blur_cache = {}
            self.update()
            return

        base = self._load_base(image_path)
        if base is None:
            # PIL 打不开（少见格式/损坏）→ 交给 Qt 自己解码，至少能显示
            self._pixmap = QPixmap(image_path)
            self.update()
            return

        try:
            from PIL import Image, ImageQt
            img = base
            if blur and int(blur) > 0:
                img = self._apply_blur(img, int(blur))
            if opacity < 1.0:
                img = img.copy()
                alpha = img.split()[3]
                factor = max(0.0, min(1.0, float(opacity)))
                if factor < 0.999:
                    alpha = alpha.point(lambda p: int(p * factor))
                img.putalpha(alpha)
            self._pixmap = ImageQt.toqpixmap(img)
        except Exception:
            self._pixmap = QPixmap(image_path)
        self.update()

    # ------------------------------------------------------------------ #
    def paintEvent(self, event):
        if self._pixmap and not self._pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            rect = self.rect()
            pw, ph = self._pixmap.width(), self._pixmap.height()
            if pw <= 0 or ph <= 0:
                return
            if self._mode == "stretch":
                painter.drawPixmap(rect, self._pixmap)
            elif self._mode == "contain":
                scaled = self._pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap((rect.width() - scaled.width()) // 2,
                                   (rect.height() - scaled.height()) // 2, scaled)
            elif self._mode == "tile":
                for x in range(0, rect.width(), pw):
                    for y in range(0, rect.height(), ph):
                        painter.drawPixmap(x, y, self._pixmap)
            else:  # cover
                scaled = self._pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = (scaled.width() - rect.width()) // 2
                y = (scaled.height() - rect.height()) // 2
                painter.drawPixmap(rect, scaled, QRect(x, y, rect.width(), rect.height()))
        super().paintEvent(event)
