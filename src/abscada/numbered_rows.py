"""Row numbers for the project lists: the position in the file, not an identifier.

A tree item carries its number in ``NUMBER_ROLE``; the delegate paints it in front of the name.
"""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

NUMBER_ROLE = Qt.ItemDataRole.UserRole + 1
GUTTER = 34


class NumberedDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        number = index.data(NUMBER_ROLE)
        if number is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text, opt.text = opt.text, ""
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setFont(opt.font)
        group = QPalette.ColorGroup.Normal if opt.state & QStyle.StateFlag.State_Enabled else QPalette.ColorGroup.Disabled
        strong = opt.palette.color(group, QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        muted = strong if selected else opt.palette.color(group, QPalette.ColorRole.PlaceholderText)
        rect = opt.rect
        painter.setPen(muted)
        painter.drawText(QRect(rect.left() + 2, rect.top(), GUTTER - 8, rect.height()),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(number))
        painter.setPen(strong)
        painter.drawText(QRect(rect.left() + GUTTER, rect.top(), rect.width() - GUTTER, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width() - GUTTER))
        painter.restore()
