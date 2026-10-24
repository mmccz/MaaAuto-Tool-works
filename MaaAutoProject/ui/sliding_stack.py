from PySide6.QtWidgets import QWidget
from PySide6.QtCore import (QPropertyAnimation, QParallelAnimationGroup,
                            QEasingCurve, QPoint, Signal)


class SlidingStack(QWidget):
    """
    左右滑动页面容器，替代 QStackedWidget。
    - 同时显示旧页与新页，做推入/推出动画
    - 动画结束旧页 hide()，避免渲染残留
    - 首次 setCurrentIndex 直接显示，无动画

    ★ 动画进行中再次切换（用户快速连点侧边栏）曾经会把界面切没：
      旧实现里 `_busy` 时直接「硬切」，但**没有停掉**正在跑的动画组；
      等旧动画跑完，它的 done() 会执行 `old.hide()` —— 而 old 此时可能
      正是刚刚硬切出来的当前页，于是整页被隐藏，界面空白。
      现在任何一次切换都先 `_abort_anim()`：停动画、把各页归位，
      再决定是滑动还是硬切；done() 里也只隐藏「已经不是当前页」的那一页。
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

    # ------------------------------------------------------------------ #
    def _abort_anim(self):
        """停掉正在进行的动画，归位并只保留当前页可见。

        只把位置挪回 (0,0) 是不够的：滑动中「旧页 + 新页」都是 show 状态，
        动画被中断时它们谁也等不到 done()，会一直叠着显示。
        """
        group, self._anim_group = self._anim_group, None
        if group is not None:
            try:
                group.stop()
                group.deleteLater()
            except Exception:
                pass
        for i, w in enumerate(self._widgets):
            w.setGeometry(self.rect())
            if i != self._current:
                w.hide()
        self._busy = False

    def _show_only(self, index):
        for i, w in enumerate(self._widgets):
            if i == index:
                w.setGeometry(self.rect())
                w.show()
                w.raise_()
            else:
                w.hide()
        self._current = index
        self.animation_finished.emit(index)

    def setCurrentIndex(self, index):
        if index < 0 or index >= len(self._widgets):
            return
        if index == self._current and not self._busy:
            return

        # 快速连点时的关键：先收拾残局，再切换
        self._abort_anim()

        if self._current < 0 or not self._anim_enabled or self._current == index:
            self._show_only(index)
            return

        self._slide(self._current, index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._busy:
            # 动画中改尺寸会让位移基准失效，直接结束动画按新尺寸归位
            self._abort_anim()
        for w in self._widgets:
            w.setGeometry(self.rect())

    # ------------------------------------------------------------------ #
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
            # 只隐藏「已经不是当前页」的那一页；否则会把硬切出来的当前页也藏掉
            if old is not self._widgets[self._current]:
                old.hide()
            old.setGeometry(self.rect())
            new.setGeometry(self.rect())
            new.raise_()
            self._busy = False
            self._anim_group = None
            self.animation_finished.emit(new_index)

        group.finished.connect(done)
        self._anim_group = group
        group.start()
