import os
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt, QRect


class BackgroundWidget(QWidget):
    """支持背景图片（透明度/模糊/缩放模式）的根容器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BackgroundRoot")
        self._pixmap = None
        self._mode = "cover"
        # 上次真正渲染用的参数；用于跳过重复解码
        self._params = None

    def set_background(self, image_path, opacity=0.3, blur=0, mode="cover"):
        # 参数没变就不要再解码：主窗口每次配置变更都会调到这里，
        # 而 PIL 解码 + 高斯模糊对大图很贵（表现为设置页输入卡顿）。
        # mtime 参与比较，保证"同一路径换了图片"仍然刷新。
        try:
            mtime = os.path.getmtime(image_path) if image_path else None
        except OSError:
            mtime = None
        params = (image_path or "", float(opacity or 0), int(blur or 0), mode, mtime)
        if params == self._params:
            return
        self._params = params

        self._mode = mode
        if not image_path or not os.path.exists(image_path):
            self._pixmap = None
            self.update()
            return
        try:
            from PIL import Image, ImageFilter, ImageQt
            img = Image.open(image_path).convert("RGBA")
            if blur and blur > 0:
                img = img.filter(ImageFilter.GaussianBlur(blur))
            if opacity < 1.0:
                alpha = img.split()[3]
                alpha = alpha.point(lambda p: int(p * max(0.0, min(1.0, opacity))))
                img.putalpha(alpha)
            self._pixmap = ImageQt.toqpixmap(img)
        except Exception:
            self._pixmap = QPixmap(image_path)
        self.update()

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