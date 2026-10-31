import os
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt, QRect

# Blur at this reduced size, then scale back up: the background fills the window and is
# dimmed anyway; blur cost is roughly quadratic in side length, so half size is ~4x faster.
BLUR_MAX_SIDE = 1280


class BackgroundWidget(QWidget):
    """Root container with background image support (opacity / blur / scale mode)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BackgroundRoot")
        self._pixmap = None
        self._mode = "cover"
        # Parameters of the last actual render; used to skip redundant decoding
        self._params = None
        # Decoded and scaled base image, recomputed only on image/scale-mode change (blur and opacity reuse it)
        self._base = None
        self._base_key = None

    # ------------------------------------------------------------------ #
    def _load_base(self, image_path):
        """Load and (if needed) downscale to ``BLUR_MAX_SIDE``; the result is cached."""
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
        self._blur_cache = {}          # new image: drop previous blur results
        return img

    def _apply_blur(self, img, blur):
        from PIL import ImageFilter
        self._blur_cache = getattr(self, "_blur_cache", {})
        radius = int(blur)
        cached = self._blur_cache.get(radius)
        if cached is not None:
            return cached
        blurred = img.filter(ImageFilter.GaussianBlur(radius))
        # Keep only the 3 most recent buckets so dragging the slider cannot grow the cache unbounded
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
            # PIL could not open it (odd format/corrupt) → let Qt decode it so at least something shows
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
