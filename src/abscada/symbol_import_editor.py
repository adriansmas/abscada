"""Studio dialog «Importar símbolos del PLC…»: browse a connection and create variables by name."""
import copy
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)
from .connection_diagnostics import PROBES
from .dialogs import EditorDialog
from .i18n import tr
from . import symbol_import

ROLE = Qt.ItemDataRole.UserRole


class SymbolImportDialog(EditorDialog):
    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio
        self.rows = []
        self.pending = None
        self.setWindowTitle(tr("Importar símbolos del PLC"))
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        note = QLabel(tr("Lee los símbolos que el PLC ofrece por la conexión y crea una variable por cada símbolo marcado, "
                         "enlazada por su nombre. Los ya importados se muestran marcados en gris y no se duplican."))
        note.setWordWrap(True); layout.addWidget(note)
        form = QFormLayout(); layout.addLayout(form)
        self.connection = QComboBox()
        for config in studio.project.connections:
            if symbol_import.can_explore(config):
                self.connection.addItem(config["id"], config["id"])
        form.addRow(tr("Conexión"), self.connection)
        row = QHBoxLayout()
        self.read_button = QPushButton(tr("Leer símbolos del PLC")); self.read_button.clicked.connect(self.start)
        row.addWidget(self.read_button)
        self.status = QLabel(); self.status.setWordWrap(True); row.addWidget(self.status, 1)
        layout.addLayout(row)
        self.filter = QLineEdit(); self.filter.setPlaceholderText(tr("🔍 Filtrar símbolos…"))
        self.filter.textChanged.connect(self.apply_filter); layout.addWidget(self.filter)
        self.list = QListWidget(); layout.addWidget(self.list, 1)
        options = QHBoxLayout(); layout.addLayout(options)
        for title, state in ((tr("Marcar visibles"), True), (tr("Desmarcar visibles"), False)):
            button = QPushButton(title); button.clicked.connect(lambda _=False, s=state: self.check_visible(s)); options.addWidget(button)
        options.addStretch()
        self.writable = QCheckBox(tr("Permitir escritura desde el SCADA")); options.addWidget(self.writable)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Importar marcados"))
        box.accepted.connect(self.accept); box.rejected.connect(self.reject); layout.addWidget(box)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll)
        if not self.connection.count():
            self.read_button.setEnabled(False)
            self.status.setText(tr("Ninguna conexión permite explorar símbolos: crea una conexión «Siemens S7 simbólico»."))
        self.validator = self.check

    def config(self):
        identifier = self.connection.currentData()
        return next(c for c in self.studio.project.connections if c["id"] == identifier)

    def start(self):
        self.read_button.setEnabled(False); self.status.setText(tr("Leyendo símbolos…"))
        self.pending = PROBES.submit(symbol_import.explore, copy.deepcopy(self.config()), self.studio.project.root)
        self.timer.start(80)

    def poll(self):
        if not self.pending or not self.pending.done():
            return
        self.timer.stop(); self.read_button.setEnabled(True)
        try:
            found = self.pending.result()
        except Exception as exc:
            self.status.setText(tr("No se pudieron leer los símbolos: {exc}", exc=exc)); return
        self.show_rows(symbol_import.candidates(self.studio.project, self.config(), found))

    def show_rows(self, rows):
        self.rows = rows
        self.list.clear()
        for index, (address, kind, label, existing) in enumerate(rows):
            item = QListWidgetItem(f"{label} → {existing}" if existing else label)
            item.setData(ROLE, index)
            if existing:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        new = sum(1 for row in rows if not row[3])
        self.status.setText(tr("{count} símbolos; {new} sin importar", count=len(rows), new=new))
        self.apply_filter()

    def apply_filter(self):
        text = self.filter.text().casefold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(text) and text not in item.text().casefold())

    def check_visible(self, state):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def selected(self):
        return [self.rows[self.list.item(i).data(ROLE)] for i in range(self.list.count())
                if self.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled
                and self.list.item(i).checkState() == Qt.CheckState.Checked]

    def check(self):
        if not self.selected():
            raise ValueError(tr("Marca al menos un símbolo nuevo para importar"))
        candidate = copy.deepcopy(self.studio.project)
        symbol_import.import_symbols(candidate, self.config(), self.selected(), self.writable.isChecked())
        candidate.validate()


def import_from_plc(studio):
    dialog = SymbolImportDialog(studio)
    if dialog.exec():
        created = []
        config, rows, writable = dialog.config(), dialog.selected(), dialog.writable.isChecked()
        if studio.mutate(lambda: created.extend(symbol_import.import_symbols(studio.project, config, rows, writable))):
            studio.statusBar().showMessage(tr("{count} variables importadas", count=len(created)), 8000)
