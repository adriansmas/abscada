"""Layout that wraps its widgets onto new lines when the width runs out.

The operator viewers use it for their toolbars and curve toggles: with many curves or in a small
control the rows grow downwards instead of forcing a minimum width.
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.gap = spacing

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def arrange(self, rect, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_height:
                x, y, line_height = area.x(), y + line_height + self.gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.gap
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
