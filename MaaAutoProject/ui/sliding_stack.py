from PySide6.QtWidgets import QWidget
from PySide6.QtCore import (QPropertyAnimation, QParallelAnimationGroup,
                            QEasingCurve, QPoint, Signal)


class SlidingStack(QWidget):
    """
    Sliding page container, replacing QStackedWidget.
    - Shows the old and new pages together and animates a push in/out
    - Hides the old page when the animation ends, so nothing lingers
    - First setCurrentIndex shows directly, with no animation

    ★ Switching again mid-animation (a user rapidly clicking the sidebar) used to blank
      the UI: the old code hard-switched while `_busy`, but did **not stop** the running
      animation. When that animation finished its done() ran `old.hide()` — and old could
      be the page just hard-switched in, so the whole UI went blank.
      Now every switch runs `_abort_anim()` first: stop animations, restore each page,
      then decide slide or hard switch; done() only hides the page that is no longer current.
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
        """Stop any running animation, restore positions, and leave only the current page visible.

        Moving positions back to (0,0) is not enough: while sliding both the old and new
        pages are visible, and when the animation is interrupted neither gets done(), so
        they would stay stacked forever.
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

        # Key for rapid clicks: clean up state first, then switch
        self._abort_anim()

        if self._current < 0 or not self._anim_enabled or self._current == index:
            self._show_only(index)
            return

        self._slide(self._current, index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._busy:
            # Resizing mid-animation invalidates the offset basis; end it and re-place at the new size
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
            # Hide only the page that is no longer current; otherwise the hard-switched page disappears too
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
