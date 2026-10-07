"""Studio library linking and publication workflow."""
from html import escape
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QInputDialog, QTextBrowser, QFormLayout,
    QLineEdit, QListWidget, QListWidgetItem, QDialogButtonBox, QAbstractItemView, QHeaderView)
from .dialogs import EditorDialog
from . import faceplate_libraries as libraries
from .i18n import tr


class PublishDialog(EditorDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle(tr('Publicar librería'))
        self.resize(550, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(host.project.manifest['name'])
        self.version = QLineEdit('1.0.0')
        self.author = QLineEdit()
        self.license = QLineEdit('GPL-3.0-or-later')
        for title, field in [(tr('Nombre'),self.name),(tr('Versión'),self.version),(tr('Autor'),self.author),(tr('Licencia'),self.license)]:
            form.addRow(title, field)
        layout.addLayout(form)
        self.faces = QListWidget()
        for name in host.project.faceplates:
            if libraries.owner(host.project, name):
                continue
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.faces.addItem(item)
        layout.addWidget(self.faces)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr('Publicar…'))
        buttons.accepted.connect(self.publish)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def publish(self):
        names = [self.faces.item(i).text() for i in range(self.faces.count()) if self.faces.item(i).checkState() == Qt.CheckState.Checked]
        target, _ = QFileDialog.getSaveFileName(self, tr('Archivo de biblioteca nuevo'), '', tr('Biblioteca abSCADA (*.abscada-library.json)'))
        if not target:
            return
        try:
            libraries.export_library(self.host.project, names, target, self.name.text().strip(), self.version.text().strip(), self.author.text().strip(), self.license.text().strip())
            self.host.statusBar().showMessage(tr('Biblioteca publicada: ') + target, 8000)
            self.accept()
        except Exception as exc:
            self.host.error(exc)


class LibraryDialog(EditorDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle(tr('Librerías externas'))
        self.resize(900, 610)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr('Alias'), tr('Biblioteca'), tr('Versión'), tr('Origen')])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for title, callback in [(tr('Vincular…'),self.link),(tr('Actualizar desde…'),self.update),(tr('Desvincular'),self.unlink),(tr('Publicar biblioteca…'),lambda:PublishDialog(host).exec())]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        layout.addWidget(self.details)
        self.table.itemSelectionChanged.connect(self.inspect)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        for alias, entry in self.host.project.libraries.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate([alias, entry['package']['name'], entry['package']['version'], entry['source']]):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.details.clear()
        if self.table.rowCount():
            self.table.selectRow(0)

    def selected(self):
        row = self.table.currentRow()
        return self.table.item(row, 0).text() if row >= 0 else None

    def inspect(self):
        alias = self.selected()
        if alias not in self.host.project.libraries:
            return
        entry = self.host.project.libraries[alias]
        package = entry['package']
        rows = []
        types = {'bool':tr('Booleano'),'int':tr('Entero'),'float':tr('Real'),'string':tr('Texto')}
        for name, doc in package['faceplates'].items():
            parameters = '<br>'.join(escape(key)+' · '+types[kind] for key,kind in doc.get('parameters',{}).items()) or tr('Sin parámetros')
            rows.append('<tr><td><b>'+escape(alias+'__'+name)+'</b><br>'+escape(doc.get('title',''))+'</td><td>'+parameters+'</td></tr>')
        self.details.setHtml('<h3>'+escape(package['name'])+' · '+escape(package['version'])+'</h3>'
            +'<p>Autor: '+escape(str(package.get('author',''))) +'<br>Licencia: '+escape(str(package.get('license','')))+'</p>'
            +tr('<table cellpadding="8"><tr><th align="left">Objeto</th><th align="left">Parámetros</th></tr>')+''.join(rows)+'</table>')
        self.details.setToolTip('SHA-256: '+entry['sha256'])

    def source(self, initial=''):
        return QFileDialog.getOpenFileName(self, tr('Librería'), initial, tr('Biblioteca abSCADA (*.json)'))[0]

    def apply(self, operation):
        if self.host.mutate(operation):
            self.refresh()

    def link(self):
        source = self.source()
        if not source:
            return
        alias, ok = QInputDialog.getText(self, tr('Vincular biblioteca'), tr('Alias en este proyecto'), text=tr('equipos'))
        if ok:
            self.apply(lambda:libraries.link(self.host.project, source, alias.strip()))

    def update(self):
        alias = self.selected()
        if alias:
            source = self.source(self.host.project.libraries[alias]['source'])
            if source:
                self.apply(lambda:libraries.link(self.host.project, source, alias, update=True))

    def unlink(self):
        alias = self.selected()
        if alias:
            self.apply(lambda:libraries.unlink(self.host.project, alias))
