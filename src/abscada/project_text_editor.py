"""Studio project translations, including CSV interchange for spreadsheet editors."""
from pathlib import Path
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLineEdit, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QCheckBox, QFileDialog, QHeaderView)
from .dialogs import EditorDialog
from .project_languages import (resolve, edited, entries, languages, default_language,
    export_csv, import_csv)
from .i18n import tr


def editing_context(host):
    while host is not None:
        if hasattr(host, 'project'):
            return getattr(host, 'editing_language', default_language(host.project)), default_language(host.project)
        if hasattr(host, 'host') and hasattr(host.host, 'project'):
            return editing_context(host.host)
        host = host.parent() if hasattr(host, 'parent') else None
    return 'es', 'es'


class ProjectTextField(QLineEdit):
    def __init__(self, host, value=''):
        self.host = host
        super().__init__()
        self.set_value(value)

    def set_value(self, value):
        self.original = copy.deepcopy(value)
        code, default = editing_context(self.host)
        super().setText(resolve(value, code, default))

    def translated_value(self):
        code, default = editing_context(self.host)
        # An unrelated inspector edit must not create a missing translation.
        if self.text() == resolve(self.original, code, default):
            return copy.deepcopy(self.original)
        return edited(self.original, self.text(), code, default)


class ProjectTextsDialog(EditorDialog):
    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio
        self.setWindowTitle(tr('Textos del proyecto'))
        self.resize(1050, 650)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.filter = QCheckBox(tr('Sin traducir'))
        self.filter.toggled.connect(self.refresh)
        toolbar.addWidget(self.filter)
        for title, callback in ((tr('Exportar CSV'), self.export), (tr('Importar CSV'), self.import_file)):
            button = QPushButton(title); button.clicked.connect(callback); toolbar.addWidget(button)
        toolbar.addStretch(); layout.addLayout(toolbar)
        self.table = QTableWidget(); layout.addWidget(self.table)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellChanged.connect(self.change)
        self.refresh()

    def refresh(self):
        project = self.studio.project
        self.codes = languages(project)
        self.rows = list(entries(project))
        default = default_language(project)
        if self.filter.isChecked():
            self.rows = [e for e in self.rows if resolve(e.value, default, default).strip() and
                any(not (e.value.get(c, '') if isinstance(e.value, dict) else e.value if c == default else '').strip()
                    for c in self.codes)]
        self.table.blockSignals(True)
        self.table.setColumnCount(len(self.codes) + 1)
        self.table.setHorizontalHeaderLabels(['path', *self.codes])
        self.table.setRowCount(len(self.rows))
        for row, entry in enumerate(self.rows):
            item = QTableWidgetItem(entry.path)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            for column, code in enumerate(self.codes, 1):
                value = entry.value.get(code, '') if isinstance(entry.value, dict) else entry.value if code == default else ''
                item = QTableWidgetItem(value)
                if entry.path.startswith('faceplates/'):
                    from .faceplate_libraries import owner
                    template = entry.path.split('/')[1].replace('~1', '/').replace('~0', '~')
                    if owner(project, template):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setToolTip(tr('Librería vinculada · solo lectura'))
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def change(self, row, column):
        if not column:
            return
        path = self.rows[row].path
        code = self.codes[column - 1]
        text = self.table.item(row, column).text()
        def apply():
            entry = next(e for e in entries(self.studio.project) if e.path == path)
            entry.owner[entry.key] = edited(entry.value, text, code, default_language(self.studio.project))
        self.studio.mutate(apply)
        self.refresh()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('Exportar CSV'), 'textos.csv', 'CSV (*.csv)')
        if path:
            try:
                Path(path).write_text(export_csv(self.studio.project), encoding='utf-8-sig', newline='')
            except Exception as exc:
                self.studio.error(exc)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Importar CSV'), '', 'CSV (*.csv)')
        if path:
            try:
                content = Path(path).read_text(encoding='utf-8-sig')
                self.studio.mutate(lambda: import_csv(self.studio.project, content))
                self.refresh()
            except Exception as exc:
                self.studio.error(exc)
