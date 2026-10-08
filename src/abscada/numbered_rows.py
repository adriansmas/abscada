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
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # Row background (selection, hover, stripes) over the whole width, as the style sheet defines it ...
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, widget)
        # ... then the item itself, pushed right to leave room for the number.
        shifted = QStyleOptionViewItem(opt)
        shifted.rect = opt.rect.adjusted(GUTTER, 0, 0, 0)
        shifted.state &= ~QStyle.StateFlag.State_HasFocus
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, shifted, painter, widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setFont(opt.font)
        group = QPalette.ColorGroup.Normal if opt.state & QStyle.StateFlag.State_Enabled else QPalette.ColorGroup.Disabled
        painter.setPen(opt.palette.color(group, QPalette.ColorRole.Text) if selected else opt.palette.color(group, QPalette.ColorRole.PlaceholderText))
        painter.drawText(QRect(opt.rect.left() + 2, opt.rect.top(), GUTTER - 8, opt.rect.height()),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(number))
        painter.restore()
