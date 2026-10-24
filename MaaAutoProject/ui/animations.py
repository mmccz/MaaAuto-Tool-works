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
    """用 QPainter 手绘 pixmap 的遮罩层，不参与 QSS 样式计算。"""

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
            # 目标矩形铺满整个 overlay，防止 resize 时留白
            p.drawPixmap(self.rect(), self._pixmap)


def clear_transition_overlay(window):
    """立刻清掉换主题/换缩放时留下的「旧画面遮罩」。

    ★ 这个遮罩是一张旧界面的截图，几何尺寸在创建时就定死了。如果紧接着发生了
    布局变化（切界面缩放、窗口变大变小），遮罩没跟着变，淡出过程中就会看到
    旧布局残影 —— 实测 150% 切换时偶尔闪出旧侧栏的一角，点一下对话框又
    「自己好了」（因为动画跑完、遮罩被删）。所以改变窗口结构前必须先清掉它。
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

    # 0) 如果上一次的 overlay 还在，先清掉
    clear_transition_overlay(window)

    # 1) 抓旧画面
    pix = target.grab()
    overlay = _SnapshotOverlay(target, pix)
    overlay.setGeometry(target.rect())
    overlay.show()
    overlay.raise_()
    window._theme_overlay = overlay

    # 2) 延后一个 tick：确保 overlay 先稳定显示，再切主题 + 淡出
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