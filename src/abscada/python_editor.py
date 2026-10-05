"""Small Python syntax highlighter for project sources."""
import keyword
import re
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtGui import QPainter
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor); self.editor=editor

    def paintEvent(self,event):
        editor=self.editor; painter=QPainter(self)
        painter.fillRect(event.rect(),QColor('#f4f7fa'));painter.setPen(QColor('#8492a4'))
        block=editor.firstVisibleBlock()
        top=int(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
        while block.isValid() and top<=event.rect().bottom():
            height=int(editor.blockBoundingRect(block).height())
            if block.isVisible():
                painter.drawText(0,top,self.width()-8,editor.fontMetrics().height(),Qt.AlignmentFlag.AlignRight,str(block.blockNumber()+1))
            top+=height;block=block.next()


class PythonCodeEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__();self.numbers=LineNumbers(self)
        self.blockCountChanged.connect(self.update_margin)
        self.updateRequest.connect(lambda *args:self.numbers.update())
        self.setStyleSheet('QPlainTextEdit { font-family: Consolas; font-size: 14px; }')
        self.update_margin()

    def update_margin(self,*args):
        self.gutter_width=18+self.fontMetrics().horizontalAdvance('9')*max(3,len(str(self.blockCount())))
        self.setViewportMargins(self.gutter_width,0,0,0)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        rect=self.contentsRect();self.numbers.setGeometry(QRect(rect.left(),rect.top(),self.gutter_width,rect.height()))

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and not event.modifiers():
            text=self.textCursor().block().text();indent=text[:len(text)-len(text.lstrip())]
            if text.rstrip().endswith(':'):indent+='    '
            self.insertPlainText('\n'+indent);return
        if event.key()==Qt.Key.Key_Tab and not event.modifiers() and not self.textCursor().hasSelection():
            self.insertPlainText('    ');return
        super().keyPressEvent(event)


class PythonHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text):
        styles = [(r'\b(?:'+ '|'.join(keyword.kwlist) +r')\b','#8353a2',True),
                  (r'\b(?:ctx|print|range|len|str|int|float|bool)\b','#126e89',False),
                  (r'\b\d+(?:\.\d+)?\b','#a96822',False),
                  (r'"[^"\n]*"', '#27825c', False),
                  (r"'[^'\n]*'", '#27825c', False),
                  (r'#.*$','#738197',False)]
        for pattern,color,bold in styles:
            fmt=QTextCharFormat();fmt.setForeground(QColor(color))
            if bold:fmt.setFontWeight(QFont.Weight.Bold)
            for match in re.finditer(pattern,text):self.setFormat(match.start(),match.end()-match.start(),fmt)
