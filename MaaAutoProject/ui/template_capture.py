"""Template capture: let users re-capture button images on their own machine, matching resolution and scaling.

Background
----------
The bundled template (``resources/maa_start.png``) was captured on one machine at one
scale. :mod:`vision` does multi-scale matching over 60%-200%, but with very different
resolutions, or when button text/skin changes, a self-captured template is the most
reliable fix. This dialog is the entry point:

1. Pick a template name (Link Start / Start task / Custom);
2. Hide the window and grab the current screen;
3. Drag a box around the button on a full-screen translucent overlay;
4. Convert by screen DPI, crop at physical pixels, and save to ``config/templates/``;
5. Grab the screen again for a self-check and report similarity — below 0.85 the box was off.

Mind the coordinate conversion: Qt widget geometry is in **logical pixels** (affected by
DPI scaling), while ``vision.grab`` returns **physical pixels**. The difference is one
``devicePixelRatio``.
"""

import logging
import os
import traceback

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

import vision

logger = logging.getLogger("MaaAuto")

KNOWN_TEMPLATES = [
    ("maa_start.png", "MAA · Link Start!"),
    ("maaend_start.png", "MaaEnd · 开始任务"),
]
CUSTOM_NAME = "__custom__"
MIN_SELECT_PX = 8


class _Selector(QWidget):
    """Full-screen translucent overlay to drag a selection; Esc cancels.

    The background paints the screenshot grabbed when capture started, so the image
    the user sees is frozen and the target cannot move while dragging.
    """

    finished = Signal()        # selection finished (also emitted on cancel)

    def __init__(self, screen, captured_bgr):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.CrossCursor)
        self._screen = screen
        self.setGeometry(screen.geometry())
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._done = False
        self.selection = None      # logical-pixel QRect

        self._pixmap = None
        if captured_bgr is not None:
            self._pixmap = QPixmap(_pixmap_from_bgr(captured_bgr))

    # ------------------------------------------------------------------ #
    def paintEvent(self, _):
        p = QPainter(self)
        if self._pixmap is not None and not self._pixmap.isNull():
            p.drawPixmap(self.rect(), self._pixmap)

        # Dim the whole screen to highlight the selection
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if self._dragging or self.selection is not None:
            sel = self._current_rect()
            cut = sel.normalized()
            # Repaint the source inside the selection (undo the dimming)
            if self._pixmap is not None and not self._pixmap.isNull() and cut.width() > 0:
                p.drawPixmap(cut, self._pixmap, self._source_rect(cut))
            p.setPen(QPen(QColor(59, 130, 246), 2))
            p.drawRect(cut)

    def _source_rect(self, logical_rect):
        """Map the selection (logical px) to the matching rect in the source image (physical px)."""
        dpr = max(0.5, float(self._screen.devicePixelRatio()))
        img_w = self._pixmap.width()
        img_h = self._pixmap.height()
        x = int(round(logical_rect.x() * dpr))
        y = int(round(logical_rect.y() * dpr))
        w = int(round(logical_rect.width() * dpr))
        h = int(round(logical_rect.height() * dpr))
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = max(1, min(w, img_w - x))
        h = max(1, min(h, img_h - y))
        return QRect(x, y, w, h)

    def _current_rect(self):
        if self.selection is not None:
            return self.selection
        return QRect(self._origin, self._current)

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._current = e.position().toPoint()
        rect = QRect(self._origin, self._current).normalized()
        if rect.width() >= MIN_SELECT_PX and rect.height() >= MIN_SELECT_PX:
            self.selection = rect
            self._finish()
        else:
            # Treat a tiny click as a misclick and cancel
            self.selection = None
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.selection = None
            self._finish()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self.finished.emit()
        self.close()


def _pixmap_from_bgr(bgr):
    """BGR ndarray -> QPixmap (in memory, avoiding temp files and encoding issues)."""
    if vision.HAS_CV2:
        rgb = vision.cv2.cvtColor(bgr, vision.cv2.COLOR_BGR2RGB)
    else:
        rgb = bgr
    h, w = rgb.shape[:2]
    from PySide6.QtGui import QImage
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())      # copy(): the backing buffer belongs to numpy


class TemplateCaptureDialog(QDialog):
    """Main template-capture dialog; used like a normal QDialog."""

    def __init__(self, i18n, config, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.config = dict(config or {})
        self._saved_file = None
        self._saved_dir = None
        self._saved_score = 0.0

        self.setWindowTitle(self.i18n.t("capture.title"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        self.title_label = QLabel(self.i18n.t("capture.title"))
        self.title_label.setObjectName("PageTitle")
        layout.addWidget(self.title_label)

        self.hint_label = QLabel(self.i18n.t("capture.hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setObjectName("SettingDesc")
        layout.addWidget(self.hint_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.name_combo = QComboBox()
        for filename, display in KNOWN_TEMPLATES:
            self.name_combo.addItem(f"{display}  ({filename})", filename)
        self.name_combo.addItem(self.i18n.t("capture.custom"), CUSTOM_NAME)
        self.name_combo.currentIndexChanged.connect(self._on_name_changed)
        row.addWidget(self.name_combo, 1)

        self.custom_edit = QLineEdit("")
        self.custom_edit.setPlaceholderText("my_button.png")
        self.custom_edit.setVisible(False)
        row.addWidget(self.custom_edit, 1)
        layout.addLayout(row)

        self.name_label = QLabel(self.i18n.t("capture.name"))
        self.name_label.setObjectName("SettingDesc")
        layout.addWidget(self.name_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_start = QPushButton(self.i18n.t("capture.start"))
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_capture)
        btns.addWidget(self.btn_start)
        self.btn_close = QPushButton(self.i18n.t("common.cancel"))
        self.btn_close.setObjectName("GhostButton")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_close)
        layout.addLayout(btns)

    # ------------------------------------------------------------------ #
    def saved_dir(self):
        return self._saved_dir

    def saved_file(self):
        return self._saved_file

    def saved_score(self):
        return self._saved_score

    # ------------------------------------------------------------------ #
    def _on_name_changed(self, *_):
        is_custom = self.name_combo.currentData() == CUSTOM_NAME
        self.custom_edit.setVisible(is_custom)

    def _target_filename(self):
        data = self.name_combo.currentData()
        if data == CUSTOM_NAME:
            name = (self.custom_edit.text() or "").strip()
            if not name:
                return None
            name = os.path.basename(name.replace("\\", "/"))
            if not name.lower().endswith(".png"):
                name += ".png"
            return name
        return data

    def _target_dir(self):
        try:
            import automation
            return automation._user_template_dir(self.config)
        except Exception:
            return os.path.join(os.getcwd(), "config", "templates")

    # ------------------------------------------------------------------ #
    def _start_capture(self):
        filename = self._target_filename()
        if not filename:
            QMessageBox.warning(self, self.i18n.t("common.warning"),
                                self.i18n.t("capture.no_name"))
            return

        target_dir = self._target_dir()
        target = os.path.join(target_dir, filename)
        if os.path.exists(target):
            if QMessageBox.question(
                    self, self.i18n.t("capture.title"),
                    self.i18n.t("capture.overwrite", file=filename)) != \
                    QMessageBox.Yes:
                return

        # Flash the target window first so the click does not look like a no-op
        proc = self._target_process(filename)
        if proc:
            self.status_label.setText(
                self.i18n.t("capture.foreground", process=proc))

        # Hide the dialog first so it does not end up in the screenshot
        self.hide()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        QTimer.singleShot(260, lambda: self._do_capture(filename, target_dir, target))

    # ------------------------------------------------------------------ #
    # 1.4.5: bring the MAA / MaaEnd window to the front before capturing
    #
    # The old code grabbed the screen directly: when users clicked "Capture template" in
    # settings, MAA was often behind the MaaAuto window or minimized, so the grab had no
    # Link Start at all and the cropped template could not match.
    # ------------------------------------------------------------------ #
    def _target_process(self, filename):
        """Process name for the template; Custom returns "" (the caller arranges the window)."""
        try:
            import automation
            return automation.template_process(filename, self.config)
        except Exception:
            return ""

    def _bring_target_front(self, filename):
        proc = self._target_process(filename)
        if not proc:
            return ""
        try:
            from process_utils import bring_process_to_front, interruptible_sleep
            if bring_process_to_front([proc]):
                interruptible_sleep(0.5)
                return proc
        except Exception as e:
            logger.warning(f"把 {proc} 窗口前置失败: {e}")
        return ""

    def _do_capture(self, filename, target_dir, target):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        dpr = max(0.5, float(screen.devicePixelRatio()))
        geom = screen.geometry()
        region = (int(round(geom.x() * dpr)), int(round(geom.y() * dpr)),
                  int(round((geom.x() + geom.width()) * dpr)),
                  int(round((geom.y() + geom.height()) * dpr)))

        self._bring_target_front(filename)
        captured = vision.grab(region)
        if captured is None:
            self.show()
            QMessageBox.critical(self, self.i18n.t("common.error"),
                                 self.i18n.t("capture.failed", err="截屏失败"))
            return

        self._selector = _Selector(screen, captured)
        self._selector.finished.connect(
            lambda: self._on_selection_done(captured, dpr, target_dir, target, filename))
        self._selector.showFullScreen()
        self._selector.raise_()
        self._selector.activateWindow()

    def _on_selection_done(self, captured, dpr, target_dir, target, filename):
        selector = self._selector
        self._selector = None
        rect = selector.selection if selector is not None else None
        if rect is None:
            self.show()
            return
        # The overlay closes only after finished; wait for it to leave the screen before
        # the self-check, or the grab still contains the translucent mask and scores low.
        QTimer.singleShot(
            180, lambda: self._crop_and_save(captured, rect, dpr,
                                             target_dir, target, filename))

    def _crop_and_save(self, captured, rect, dpr, target_dir, target, filename):
        # Wrap the whole block: this is a windowed app, so exceptions are invisible and
        # users only see "nothing happened" — exactly the 1.0.2 feedback.
        try:
            x = max(0, int(round(rect.x() * dpr)))
            y = max(0, int(round(rect.y() * dpr)))
            w = max(1, int(round(rect.width() * dpr)))
            h = max(1, int(round(rect.height() * dpr)))

            crop = captured[y:y + h, x:x + w]
            if crop.size == 0:
                self.show()
                QMessageBox.warning(self, self.i18n.t("common.warning"),
                                    self.i18n.t("capture.empty"))
                return

            os.makedirs(target_dir, exist_ok=True)
            vision.save_png(crop, target)

            score = self._self_check(target)
            self._saved_file = target
            self._saved_dir = target_dir
            self._saved_score = score

            logger.info(f"已保存模板 {target} ({w}x{h} @dpr={dpr:.2f})，"
                        f"自检相似度 {score:.3f}")
            self.status_label.setText(self.i18n.t(
                "capture.saved_detail", file=filename, size=f"{w}×{h}",
                score=f"{score:.3f}", dir=target_dir))
            # Do not auto-close: let users see the save path and self-check score (1.0.2 flashed by)
            self.btn_start.setText(self.i18n.t("capture.again"))
            self.btn_close.setText(self.i18n.t("common.close"))
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception as e:
            logger.error(f"截取模板失败: {e}\n{traceback.format_exc()}")
            self.show()
            QMessageBox.critical(self, self.i18n.t("common.error"),
                                 self.i18n.t("capture.failed", err=str(e)))

    def _self_check(self, path):
        """Grab the screen again to verify the template: it must find the same button.

        A low score means either an imprecise box or the dialog itself covering the
        target, so only report the score and never hard-fail; the user decides.
        """
        try:
            match = vision.find(path, threshold=0.30, scale_min=0.8, scale_max=1.3)
        except Exception as e:
            logger.debug(f"模板自检失败: {e}")
            return 0.0
        return float(match.score) if match is not None else 0.0
