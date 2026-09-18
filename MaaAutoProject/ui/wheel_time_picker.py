from PySide6.QtWidgets import (QWidget, QHBoxLayout, QListWidget, QListWidgetItem,
                               QLabel, QAbstractItemView, QFrame, QSizePolicy)
from PySide6.QtCore import (Qt, Signal, QTimer, QPropertyAnimation,
                            QEasingCurve, QSize, QAbstractAnimation, QTime)


class WheelColumn(QListWidget):
    """单行滚轮：只显示当前值，滚轮/拖动切换，点击激活。"""

    ITEM_HEIGHT = 26
    VISIBLE_ITEMS = 1

    valueChanged = Signal(str)

    def __init__(self, values, parent=None):
        super().__init__(parent)
        self._values = [str(v) for v in values]
        self._current_index = 0
        self._snapping = False

        self.setObjectName("WheelColumn")
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.NoSelection)   # 不要选中框，避免色块偏移
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFrameShape(QFrame.NoFrame)
        self.setUniformItemSizes(True)

        self.setFixedWidth(48)
        self.setFixedHeight(self.ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        for v in self._values:
            it = QListWidgetItem(v)
            it.setSizeHint(QSize(0, self.ITEM_HEIGHT))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.addItem(it)

        self.setCurrentRow(0)

        self._snap_timer = QTimer(self)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.setInterval(80)
        self._snap_timer.timeout.connect(self._snap)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.itemClicked.connect(self._on_item_clicked)

        QTimer.singleShot(0, lambda: self._scroll_to(0, animate=False))

    # ------------------------------------------------------------------
    # 焦点 / 拖动
    # ------------------------------------------------------------------
    def focusInEvent(self, e):
        super().focusInEvent(e)
        try:
            from PySide6.QtWidgets import QScroller
            QScroller.grabGesture(self.viewport(),
                                  QScroller.LeftMouseButtonGesture)
        except Exception:
            pass

    def focusOutEvent(self, e):
        try:
            from PySide6.QtWidgets import QScroller
            QScroller.ungrabGesture(self.viewport())
        except Exception:
            pass
        super().focusOutEvent(e)

    def mousePressEvent(self, e):
        if not self.hasFocus():
            self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(e)

    def wheelEvent(self, e):
        if not self.hasFocus():
            e.ignore()
            return
        delta = e.angleDelta().y()
        if delta == 0:
            return
        step = -1 if delta > 0 else 1
        new_index = self._current_index + step
        new_index = max(0, min(len(self._values) - 1, new_index))
        if new_index != self._current_index:
            self._scroll_to(new_index, animate=True)
        e.accept()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _on_scroll(self, _):
        if self._snapping:
            return
        self._snap_timer.start()

    def _snap(self):
        sb = self.verticalScrollBar()
        real = round(sb.value() / self.ITEM_HEIGHT)
        real = max(0, min(len(self._values) - 1, real))
        self._scroll_to(real, animate=True)

    def _on_item_clicked(self, item):
        self.setFocus(Qt.MouseFocusReason)
        self._snap_timer.stop()
        real = self.row(item)
        if 0 <= real < len(self._values):
            self._scroll_to(real, animate=True)

    def _scroll_to(self, real_index, animate=True):
        sb = self.verticalScrollBar()
        target = real_index * self.ITEM_HEIGHT
        distance = abs(target - sb.value())

        if not animate or distance == 0 or distance <= self.ITEM_HEIGHT:
            sb.setValue(target)
            self._apply(real_index)
            return

        self._snapping = True
        anim = QPropertyAnimation(sb, b"value", self)
        anim.setDuration(70)
        anim.setStartValue(sb.value())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutQuad)

        def done():
            self._snapping = False
            self._apply(real_index)

        anim.finished.connect(done)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        self._anim = anim

    def _apply(self, real_index):
        self._snapping = True
        self.setCurrentRow(real_index)
        self._snapping = False
        if real_index != self._current_index:
            self._current_index = real_index
            self.valueChanged.emit(self._values[real_index])

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def value(self):
        return self._values[self._current_index]

    def set_value(self, v):
        v = str(v)
        if v not in self._values:
            return
        self._scroll_to(self._values.index(v), animate=False)


class WheelTimePicker(QWidget):
    """小时 + 分钟 单行滚轮。"""

    timeChanged = Signal(QTime)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._hour_col = WheelColumn([f"{h:02d}" for h in range(24)])
        self._min_col = WheelColumn([f"{m:02d}" for m in range(60)])

        colon = QLabel(":")
        colon.setObjectName("WheelColon")
        colon.setAlignment(Qt.AlignCenter)
        colon.setFixedWidth(10)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._hour_col)
        layout.addWidget(colon)
        layout.addWidget(self._min_col)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._hour_col.valueChanged.connect(lambda *_: self.timeChanged.emit(self.time()))
        self._min_col.valueChanged.connect(lambda *_: self.timeChanged.emit(self.time()))

    def time(self) -> QTime:
        return QTime(int(self._hour_col.value()), int(self._min_col.value()))

    def setTime(self, t: QTime):
        if not t.isValid():
            return
        self._hour_col.set_value(f"{t.hour():02d}")
        self._min_col.set_value(f"{t.minute():02d}")

    def setDisplayFormat(self, fmt): pass
    def toString(self, fmt="HH:mm"): return self.time().toString(fmt)