from PySide6.QtWidgets import (QWidget, QGraphicsOpacityEffect, QApplication)
from PySide6.QtCore import (Qt, QPropertyAnimation, QEasingCurve,
                            QAbstractAnimation, QTimer)
from PySide6.QtGui import QPainter


def fade_in(widget, duration=220):
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    widget._fade_anim = anim
    return anim


class _SnapshotOverlay(QWidget):
    """Mask layer that paints onto a pixmap with QPainter; bypasses QSS styling."""

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        if self._pixmap and not self._pixmap.isNull():
            p = QPainter(self)
            # Target rect spans the whole overlay so no gap shows on resize
            p.drawPixmap(self.rect(), self._pixmap)


def clear_transition_overlay(window):
    """Drop the stale-screen mask left behind by a theme or scale change.

    ★ The mask is a screenshot of the old UI whose geometry is frozen at creation.
    If the layout changes right after (scale switch, window resize) the mask no longer
    matches, and the old layout ghosts through the fade-out — at 150% the old sidebar
    corner occasionally flashes, and clicking a dialog only seems to "fix" it because the
    animation finished and the mask was deleted. Drop the mask before changing structure.
    """
    old = getattr(window, "_theme_overlay", None)
    if old is not None:
        try:
            old.setGraphicsEffect(None)
            old.setParent(None)
            old.deleteLater()
        except Exception:
            pass
        window._theme_overlay = None
    anim = getattr(window, "_theme_anim", None)
    if anim is not None:
        try:
            anim.stop()
        except Exception:
            pass
        window._theme_anim = None


def theme_transition(window, switch_callback, duration=260):
    target = window.centralWidget() or window

    # 0) Drop any overlay left over from the previous transition
    clear_transition_overlay(window)

    # 1) Capture the old frame
    pix = target.grab()
    overlay = _SnapshotOverlay(target, pix)
    overlay.setGeometry(target.rect())
    overlay.show()
    overlay.raise_()
    window._theme_overlay = overlay

    # 2) Defer one tick: let the overlay settle, then switch theme and fade out
    def do_switch_and_fade():
        switch_callback()
        QApplication.processEvents()

        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(duration)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def cleanup():
            try:
                overlay.setParent(None)
                overlay.deleteLater()
            except Exception:
                pass
            if getattr(window, "_theme_overlay", None) is overlay:
                window._theme_overlay = None

        anim.finished.connect(cleanup)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        window._theme_anim = anim

    QTimer.singleShot(0, do_switch_and_fade)