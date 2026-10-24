"""自动换行的流式布局（Qt 官方 FlowLayout 示例的 Python 移植）。

用在设置页顶部的「分组跳转 chips」：分组从 6 个增加到 7 个后，一行放不下，
最后一个 chip 会顶到窗口边缘；用流式布局让它在窄窗口下自动折行。
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidgetItem


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # ---------------- QLayout 接口 ----------------
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    # ---------------- 布局算法 ----------------
    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            space_x = self._h_spacing
            space_y = self._v_spacing
            hint = item.sizeHint()
            next_x = x + hint.width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + hint.width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()

    def addWidget(self, widget):
        # 必须自己完成 QLayout::addWidget 的「挂到父控件上」这一步：
        # 直接 addItem(QWidgetItem(w)) 不会 reparent，控件会变成从不显示的孤儿窗口。
        parent = self.parentWidget()
        if parent is not None and widget.parentWidget() is not parent:
            widget.setParent(parent)
        self.addItem(QWidgetItem(widget))
