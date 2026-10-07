"""Transactional editor for an element's discrete text mapping."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QLineEdit,
    QDialogButtonBox, QLabel)
from .text_lists import validate_text_list
from .dialogs import EditorDialog as QDialog
from .i18n import tr
from .project_languages import resolve
from .project_text_editor import editing_context


class TextListDialog(QDialog):
    def __init__(self, element, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle(tr('Lista de textos'))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr('Valor'), tr('Texto')])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        add = QPushButton(tr('Añadir')); add.clicked.connect(lambda: self.add_row())
        remove = QPushButton(tr('Eliminar')); remove.clicked.connect(self.remove_rows)
        actions.addWidget(add); actions.addWidget(remove); actions.addStretch()
        layout.addLayout(actions)
        from .project_text_editor import ProjectTextField
        self.original_rows = {r['value']: r['text'] for r in element.get('texts', [])}
        self.host = parent
        self.default = ProjectTextField(parent, element.get('default_text', '—'))
        form = QFormLayout(); form.addRow(tr('Texto por defecto'), self.default)
        layout.addLayout(form)
        self.error = QLabel(); self.error.setStyleSheet('color: #b43838;'); self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Aceptar"))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for row in element.get('texts', []):
            self.add_row(row['value'], row['text'])

    def add_row(self, value='', text=''):
        row = self.table.rowCount(); self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(value))
        self.table.setItem(row, 1, QTableWidgetItem(resolve(text, *editing_context(self.host))))
        self.table.setCurrentCell(row, 0)

    def remove_rows(self):
        for row in sorted({item.row() for item in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def row_text(self, row):
        from .project_languages import resolve, edited
        from .project_text_editor import editing_context
        code, default = editing_context(self.host)
        text = self.table.item(row, 1).text()
        old = self.original_rows.get(self.table.item(row, 0).text(), '')
        return old if text == resolve(old, code, default) else edited(old, text, code, default)

    def mapping(self):
        return dict(texts=[dict(value=self.table.item(row, 0).text(), text=self.row_text(row))
                           for row in range(self.table.rowCount())], default_text=self.default.translated_value())

    def accept(self):
        try:
            validate_text_list(self.mapping(), self.kind)
        except ValueError as exc:
            self.error.setText(str(exc)); return
        super().accept()


def edit_text_list(host):
    selected = host.scene.selectedItems()
    if len(selected) != 1 or selected[0].element['kind'] != 'text_list':
        return
    element = selected[0].element
    tag = element.get('tag', '')
    kind = host.project.tags().get(tag, {}).get('type')
    if tag.startswith('$'):
        kind = host.document().get('parameters', {}).get(tag[1:])
    dialog = TextListDialog(element, kind, host)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        host.mutate(lambda: element.update(dialog.mapping()), selected_ids=[element['id']])
