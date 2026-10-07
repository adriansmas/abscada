"""Project-level dialogs: document creation and local version history."""
import re
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QSpinBox,QDialogButtonBox,
                              QLabel,QPushButton,QPlainTextEdit,QHBoxLayout,QTabWidget)
from .versioning import ProjectGit
from .dialogs import EditorDialog as QDialog


class NewDocumentDialog(QDialog):
    def __init__(self,host,faceplate=False):
        super().__init__(host); self.host=host; self.faceplate=faceplate
        self.setWindowTitle('Nuevo objeto de librería' if faceplate else 'Nueva pantalla')
        self.resize(430,300); body=QVBoxLayout(self); form=QFormLayout()
        self.name=QLineEdit(); self.name.setObjectName('documentName')
        self.title=QLineEdit(); self.title.setObjectName('documentTitle')
        self.width=QSpinBox(); self.height=QSpinBox()
        for field in (self.width,self.height): field.setRange(1,10000)
        from .project_settings import screen_size
        width,height=(320,180) if faceplate else screen_size(host.project)
        self.width.setValue(width); self.height.setValue(height)
        for label,field in [('Nombre de archivo',self.name),('Título',self.title),('Ancho (px)',self.width),('Alto (px)',self.height)]: form.addRow(label,field)
        body.addLayout(form); self.error=QLabel(); body.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Crear')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); body.addWidget(buttons)

    def accept(self):
        name=self.name.text().strip()
        collection=self.host.project.faceplates if self.faceplate else self.host.project.screens
        from .validation import filename
        try: filename(name)
        except ValueError as exc:
            self.error.setText(str(exc)); return
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name) or name.casefold() in {n.casefold() for n in collection}:
            self.error.setText('Nombre inválido o ya existente'); return
        super().accept()

    def document(self):
        doc=dict(title=self.title.text().strip() or self.name.text().strip(),width=self.width.value(),height=self.height.value(),background='#ffffff',elements=[])
        if self.faceplate: doc['parameters']={}
        return doc


class VersionDialog(QDialog):
    def __init__(self,host):
        super().__init__(host); self.host=host; self.setWindowTitle('Versiones del proyecto'); self.resize(780,520)
        layout=QVBoxLayout(self); bar=QHBoxLayout()
        self.enable=QPushButton('Activar Git'); self.enable.clicked.connect(self.initialize); bar.addWidget(self.enable)
        save=QPushButton('Guardar proyecto y crear versión'); save.clicked.connect(self.save); bar.addWidget(save)
        refresh=QPushButton('Actualizar'); refresh.clicked.connect(self.refresh); bar.addWidget(refresh)
        layout.addLayout(bar); tabs=QTabWidget(); layout.addWidget(tabs)
        self.history=QPlainTextEdit(); self.history.setReadOnly(True); tabs.addTab(self.history,'Historial')
        self.changes=QPlainTextEdit(); self.changes.setReadOnly(True); tabs.addTab(self.changes,'Última versión')
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
