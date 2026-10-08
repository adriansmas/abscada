"""Project-level dialogs: document creation and local version history."""
import re
from PySide6.QtWidgets import (QVBoxLayout,QFormLayout,QLineEdit,QSpinBox,QDialogButtonBox,
                              QLabel,QPushButton,QPlainTextEdit,QHBoxLayout,QTabWidget)
from .versioning import ProjectGit
from .dialogs import EditorDialog
from .i18n import tr


def file_name_from_title(title, taken=()):
    """File name derived from what the operator reads: no accents, only letters, digits, «_» and «-»."""
    import unicodedata
    plain = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^A-Za-z0-9_-]+', '_', plain).strip('_-')
    if not base:
        return ''
    used, name, number = {n.casefold() for n in taken}, base, 2
    while name.casefold() in used:
        name, number = f'{base}_{number}', number + 1
    return name


class NewDocumentDialog(EditorDialog):
    def __init__(self,host,faceplate=False):
        super().__init__(host); self.host=host; self.faceplate=faceplate
        self.setWindowTitle(tr('Nuevo objeto de librería') if faceplate else tr('Nueva pantalla'))
        self.resize(430,300); body=QVBoxLayout(self); form=QFormLayout()
        # The operator sees one name: the title. The file name is derived from it.
        self.name=QLineEdit(); self.name.setObjectName('documentName'); self.name.hide()
        self.title=QLineEdit(); self.title.setObjectName('documentTitle')
        self.file_hint=QLabel(); self.file_hint.setObjectName('muted')
        collection=host.project.faceplates if faceplate else host.project.screens
        def derive(text):
            self.name.setText(file_name_from_title(text,collection))
            self.file_hint.setText(tr('Archivo: {name}',name=self.name.text()) if self.name.text() else '')
        self.title.textChanged.connect(derive)
        self.width=QSpinBox(); self.height=QSpinBox()
        for field in (self.width,self.height): field.setRange(1,10000)
        from .project_settings import screen_size
        width,height=(320,180) if faceplate else screen_size(host.project)
        self.width.setValue(width); self.height.setValue(height)
        for label,field in [(tr('Nombre'),self.title),('',self.file_hint),(tr('Ancho (px)'),self.width),(tr('Alto (px)'),self.height)]: form.addRow(label,field)
        body.addLayout(form); self.error=QLabel(); body.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('Crear'))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); body.addWidget(buttons)

    def accept(self):
        name=self.name.text().strip()
        if not name:
            self.error.setText(tr('Escribe un nombre con letras o números')); return
        collection=self.host.project.faceplates if self.faceplate else self.host.project.screens
        from .validation import filename
        try: filename(name)
        except ValueError as exc:
            self.error.setText(str(exc)); return
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name) or name.casefold() in {n.casefold() for n in collection}:
            self.error.setText(tr('Nombre inválido o ya existente')); return
        super().accept()

    def document(self):
        doc=dict(title=self.title.text().strip() or self.name.text().strip(),width=self.width.value(),height=self.height.value(),background='#ffffff',elements=[])
        if self.faceplate: doc['parameters']={}
        return doc


class VersionDialog(EditorDialog):
    def __init__(self,host):
        super().__init__(host); self.host=host; self.setWindowTitle(tr('Versiones del proyecto')); self.resize(780,520)
        layout=QVBoxLayout(self); bar=QHBoxLayout()
        self.enable=QPushButton(tr('Activar Git')); self.enable.clicked.connect(self.initialize); bar.addWidget(self.enable)
        save=QPushButton(tr('Guardar proyecto y crear versión')); save.clicked.connect(self.save); bar.addWidget(save)
        refresh=QPushButton(tr('Actualizar')); refresh.clicked.connect(self.refresh); bar.addWidget(refresh)
        layout.addLayout(bar); tabs=QTabWidget(); layout.addWidget(tabs)
        self.history=QPlainTextEdit(); self.history.setReadOnly(True); tabs.addTab(self.history,tr('Historial'))
        self.changes=QPlainTextEdit(); self.changes.setReadOnly(True); tabs.addTab(self.changes,tr('Última versión'))
        self.refresh()

    def refresh(self):
        try:
            git=ProjectGit(self.host.project); self.enable.setEnabled(not git.enabled())
            self.history.setPlainText(git.history())
            self.changes.setPlainText(git.run('show','--format=medium','HEAD')[:200000] if git.enabled() else '')
        except Exception as exc: self.history.setPlainText(str(exc))

    def initialize(self):
        try:
            if not self.host.save_project(): return
            ProjectGit(self.host.project).initialize(); self.refresh()
        except Exception as exc: self.host.error(exc)

    def save(self):
        self.host.save_project(); self.refresh()
