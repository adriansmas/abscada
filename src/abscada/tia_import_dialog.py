"""«Importar DB de TIA Portal»: paste the source of a DB, check the preview and create it."""
import copy
import re
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QFormLayout, QPlainTextEdit, QComboBox, QSpinBox, QCheckBox,
                               QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView, QFileDialog, QSplitter, QWidget)
from PySide6.QtCore import Qt
from .dialogs import EditorDialog
from .i18n import tr
from . import tia_import


class TiaImportDialog(EditorDialog):
    def __init__(self, studio, folder=""):
        super().__init__(studio)
        self.studio = studio
        self.result_plan = None
        self.setWindowTitle(tr("Importar DB de TIA Portal"))
        self.resize(980, 720)
        layout = QVBoxLayout(self)
        intro = QLabel(tr("En TIA Portal, clic derecho sobre el DB → «Generar fuente a partir de bloques» → «Incluir todos los bloques "
                          "dependientes». Abre el archivo generado y pega aquí todo su texto (TYPE y DATA_BLOCK). El DB se crea como "
                          "una variable estructurada con su nombre, con las direcciones calculadas para un DB no optimizado."))
        intro.setWordWrap(True); intro.setObjectName("muted")
        layout.addWidget(intro)
        splitter = QSplitter(Qt.Orientation.Vertical)
        top = QWidget(); top_layout = QVBoxLayout(top); top_layout.setContentsMargins(0, 0, 0, 0)
        self.source = QPlainTextEdit()
        self.source.setObjectName("tiaSource")
        self.source.setPlaceholderText('TYPE "MD012_VALVE"\n   STRUCT\n      Abierta : Bool;\n   …\nDATA_BLOCK "DB_Valvulas"\n   …\nEND_DATA_BLOCK')
        self.source.setFont(QFont("Consolas", 10))
        self.source.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        top_layout.addWidget(self.source, 1)
        row = QHBoxLayout()
        load = QPushButton(tr("Abrir archivo de fuente…")); load.clicked.connect(self.load_file); row.addWidget(load)
        row.addStretch()
        top_layout.addLayout(row)
        form = QFormLayout()
        self.connection = QComboBox(); self.connection.setObjectName("tiaConnection")
        self.connection.addItem(tr("Sin enlace (solo estructura y valores)"), "")
        for connection in studio.project.connections:
            if connection.get("protocol") == "s7":
                self.connection.addItem(f"{connection['id']} · {connection.get('host', '')}", connection["id"])
        if self.connection.count() > 1:
            self.connection.setCurrentIndex(1)
        self.db = QSpinBox(); self.db.setObjectName("tiaDb"); self.db.setRange(1, 65535)
        self.db.setToolTip(tr("Número del DB en el PLC; no viene en la fuente"))
        from .screen_tree import folders
        self.folder_field = QComboBox(); self.folder_field.setEditable(True); self.folder_field.setObjectName("tiaFolder")
        self.folder_field.addItems([""] + folders(studio.project, "variables"))
        self.folder_field.setCurrentText(folder)
        self.folder_field.setToolTip(tr("Carpeta de variables donde se crea; si no existe, se crea"))
        self.writable = QCheckBox(tr("Permitir escritura en todos sus campos"))
        self.replace = QCheckBox(tr("Sustituir la variable y los tipos que ya existan con el mismo nombre"))
        for title, field in [(tr("Conexión S7"), self.connection), (tr("Número de DB"), self.db), (tr("Carpeta"), self.folder_field), ("", self.writable), ("", self.replace)]:
            form.addRow(title, field)
        top_layout.addLayout(form)
        splitter.addWidget(top)
        bottom = QWidget(); bottom_layout = QVBoxLayout(bottom); bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel(tr("Vista previa: pega la fuente")); self.summary.setWordWrap(True)
        bottom_layout.addWidget(self.summary)
        self.preview = QTreeWidget(); self.preview.setObjectName("tiaPreview")
        self.preview.setHeaderLabels([tr("Variable"), tr("Tipo PLC"), tr("Tipo"), tr("Dirección"), tr("Valor inicial")])
        self.preview.setRootIsDecorated(False); self.preview.setAlternatingRowColors(True)
        self.preview.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        bottom_layout.addWidget(self.preview, 1)
        self.warnings = QLabel(); self.warnings.setWordWrap(True); self.warnings.setObjectName("tiaWarnings")
        self.warnings.setStyleSheet("color: #8a5a00;")
        bottom_layout.addWidget(self.warnings)
        splitter.addWidget(bottom)
        layout.addWidget(splitter, 1)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(300)
        self.timer.timeout.connect(self.update_preview)
        self.source.textChanged.connect(self.source_changed)
        for signal in (self.connection.currentIndexChanged, self.db.valueChanged, self.writable.toggled, self.replace.toggled):
            signal.connect(lambda *args: self.timer.start())
        self._db_touched = False
        self.db.valueChanged.connect(lambda *args: setattr(self, "_db_touched", True) if not getattr(self, "_setting_db", False) else None)
        self.validator = self.validate
        studio.dialog_buttons(self, layout)

    def folder(self):
        return self.folder_field.currentText().strip()

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Fuente de TIA Portal"), "", tr("Fuentes de TIA Portal (*.db *.udt *.scl *.txt);;Todos los archivos (*)"))
        if path:
            data = Path(path).read_bytes()
            for encoding in ("utf-8-sig", "cp1252"):
                try:
                    self.source.setPlainText(data.decode(encoding)); break
                except UnicodeDecodeError:
                    continue

    def source_changed(self):
        # A DB called DB10 (or …_DB10) gives its number, unless the user already chose one.
        match = re.search(r'DATA_BLOCK\s+"?[^"\n]*?DB_?(\d+)"?\s', self.source.toPlainText(), re.IGNORECASE)
        if match and not self._db_touched and 1 <= int(match[1]) <= 65535:
            self._setting_db = True
            self.db.setValue(int(match[1]))
            self._setting_db = False
        self.timer.start()

    def plan(self):
        return tia_import.plan(self.studio.project, self.source.toPlainText(), db=self.db.value(),
                               connection=self.connection.currentData(), writable=self.writable.isChecked(),
                               replace=self.replace.isChecked())

    def update_preview(self):
        self.preview.clear()
        try:
            result = self.plan()
        except ValueError as exc:
            self.result_plan = None
            self.summary.setText(tr("Vista previa: {error}", error=exc) if self.source.toPlainText().strip() else tr("Vista previa: pega la fuente"))
            self.warnings.setText("")
            return
        self.result_plan = result
        for row in result.rows:
            self.preview.addTopLevelItem(QTreeWidgetItem([str(cell) for cell in row]))
        if result.variable:
            self.summary.setText(tr("Se creará la variable «{name}» con {count} campos y {types} tipos de datos.",
                                    name=result.variable["name"], count=len(result.rows), types=len(result.types)))
        else:
            self.summary.setText(tr("Se crearán {types} tipos de datos.", types=len(result.types)))
        self.warnings.setText("\n".join("⚠ " + warning for warning in result.warnings))

    def validate(self):
        self.timer.stop()
        result = self.plan()
        candidate = copy.deepcopy(self.studio.project)
        tia_import.apply(candidate, result, self.folder())
        candidate.validate()
        self.result_plan = result
