from PySide6.QtWidgets import QWidget
from PySide6.QtCore import (Qt, QPropertyAnimation, QParallelAnimationGroup,
                            QEasingCurve, QPoint, Signal)


class SlidingStack(QWidget):
    """
    左右滑动页面容器，替代 QStackedWidget。
    - 同时显示旧页与新页，做推入/推出动画
    - 动画结束旧页 hide()，避免渲染残留
    - 首次 setCurrentIndex 直接显示，无动画
    """

    animation_finished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widgets = []
        self._current = -1
        self._busy = False
        self._anim_group = None
        self._anim_enabled = True

    def set_animation_enabled(self, enabled):
        self._anim_enabled = bool(enabled)

    def addWidget(self, w):
        w.setParent(self)
        w.setGeometry(self.rect())
        w.hide()
        self._widgets.append(w)

    def count(self):
        return len(self._widgets)

    def widget(self, i):
        if 0 <= i < len(self._widgets):
            return self._widgets[i]
        return None

    def currentIndex(self):
        return self._current

    def currentWidget(self):
        return self.widget(self._current)

    def setCurrentIndex(self, index):
        if index < 0 or index >= len(self._widgets):
            return
        if index == self._current:
            return

        # 首次显示：直接切换
        if self._current < 0 or not self._anim_enabled or self._busy:
            if self._current >= 0:
                self._widgets[self._current].hide()
            new = self._widgets[index]
            new.setGeometry(self.rect())
            new.show()
            new.raise_()
            self._current = index
            self.animation_finished.emit(index)
            return

        self._slide(self._current, index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for w in self._widgets:
            w.setGeometry(self.rect())

    def _slide(self, old_index, new_index):
        old = self._widgets[old_index]
        new = self._widgets[new_index]

        w = self.width()
        h = self.height()
        direction = 1 if new_index > old_index else -1

        old.setGeometry(0, 0, w, h)
        old.show()
        old.raise_()

        new.setGeometry(w * direction, 0, w, h)
        new.show()
        new.raise_()

        anim_old = QPropertyAnimation(old, b"pos", self)
        anim_old.setDuration(300)
        anim_old.setStartValue(QPoint(0, 0))
        anim_old.setEndValue(QPoint(-w * direction, 0))
        anim_old.setEasingCurve(QEasingCurve.OutCubic)

        anim_new = QPropertyAnimation(new, b"pos", self)
        anim_new.setDuration(300)
        anim_new.setStartValue(QPoint(w * direction, 0))
        anim_new.setEndValue(QPoint(0, 0))
        anim_new.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_old)
        group.addAnimation(anim_new)

        self._busy = True
        self._current = new_index

        def done():
            old.hide()
            old.setGeometry(self.rect())
            new.setGeometry(self.rect())
            new.raise_()
            self._busy = False
            self.animation_finished.emit(new_index)

        group.finished.connect(done)
        self._anim_group = group
        group.start()