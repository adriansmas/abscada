"""Engineering surface for Python sources, startup hooks and cyclic tasks."""
import copy
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QListWidget,QPlainTextEdit,
    QPushButton,QInputDialog,QDialog,QTabWidget,QLabel)
from .engineering import RecordsPage, RecordDialog
from .scripting import validate_scripts


class AutomationEditor(QTabWidget):
    def __init__(self, host):
        super().__init__(); self.host=host; self.loading=False; self.current=None
        self.edit_group=False
        self.edit_timer=QTimer(self); self.edit_timer.setSingleShot(True)
        self.edit_timer.timeout.connect(self.end_edit_group)
        page=QWidget(); layout=QVBoxLayout(page)
        actions=QHBoxLayout()
        for text, callback in [('Nuevo script',self.add),('Eliminar',self.remove),('Comprobar',self.check),('Eventos de inicio…',self.startup)]:
            b=QPushButton(text); b.clicked.connect(callback); actions.addWidget(b)
        actions.addStretch(); layout.addLayout(actions)
        split=QSplitter(); self.list=QListWidget(); self.list.setMaximumWidth(260)
        from .python_editor import PythonHighlighter, PythonCodeEditor
        self.code=PythonCodeEditor(); self.code.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.highlighter=PythonHighlighter(self.code.document())
        self.code.setTabStopDistance(32); self.code.setPlaceholderText('Selecciona o crea un script Python')
        self.code.setEnabled(False)
        split.addWidget(self.list); split.addWidget(self.code); layout.addWidget(split,1)
        self.result=QLabel(); self.result.setWordWrap(True); self.result.setMaximumHeight(48); layout.addWidget(self.result)
        self.list.currentTextChanged.connect(self.select); self.code.textChanged.connect(self.changed)
        self.addTab(page,'Scripts Python')
        self.tasks=RecordsPage(host,lambda:host.project.automation.get('tasks',[]),
            lambda rows:host.project.automation.__setitem__('tasks',rows),
            [('id','Tarea'),('script','Script'),('interval_ms','Periodo (ms)'),('enabled','Activa')],
            lambda:[('id','Nombre','text','',()),('script','Script','choice','',[(n,n) for n in host.project.scripts]),
                    ('interval_ms','Periodo (ms)','int',1000,()),('enabled','Activa','bool',True,())], 'Tarea')
        self.addTab(self.tasks,'Tareas cíclicas')
        self.diagnostics=QPlainTextEdit(); self.diagnostics.setReadOnly(True); self.addTab(self.diagnostics,'Ejecuciones')
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh_diagnostics); self.timer.start(500)
        self.refresh()

    def refresh(self):
        self.end_edit_group()
        self.loading=True
        name=self.current
        self.list.clear(); self.list.addItems(sorted(self.host.project.scripts))
        matches=self.list.findItems(name or '',Qt.MatchFlag.MatchExactly)
        if matches: self.list.setCurrentItem(matches[0])
        elif self.list.count(): self.list.setCurrentRow(0)
        self.loading=False
        self.select(self.list.currentItem().text() if self.list.currentItem() else '')
        self.tasks.refresh()

    def select(self,name):
        if self.loading: return
        if name != self.current: self.end_edit_group()
        self.loading=True; self.current=name or None
        source=self.host.project.scripts.get(name,'')
        if self.code.toPlainText()!=source: self.code.setPlainText(source)
        self.code.setEnabled(bool(name)); self.loading=False

    def changed(self):
        if self.loading or not self.current: return
        if not self.edit_group:
            self.host.record_history(copy.deepcopy(self.host.project))
            self.edit_group=True
        self.host.project.scripts[self.current]=self.code.toPlainText()
        self.host.mark_dirty(); self.edit_timer.start(600)

    def end_edit_group(self):
        self.edit_group=False; self.edit_timer.stop()

    def add(self):
        name,ok=QInputDialog.getText(self,'Nuevo script','Nombre de archivo (sin .py)')
        if not ok: return
        if name in self.host.project.scripts: self.host.error('El script ya existe'); return
        if self.host.mutate(lambda:self.host.project.scripts.__setitem__(name,'# API: ctx.read, ctx.quality, ctx.write, ctx.state\nprint(ctx.event)\n')):
            self.current=name; self.refresh()

    def remove(self):
        if self.current:
            name=self.current
            self.host.mutate(lambda:self.host.project.scripts.pop(name))

    def check(self):
        try:
            validate_scripts(self.host.project); self.result.setText('Sintaxis y referencias correctas')
        except ValueError as exc: self.result.setText(str(exc))

    def startup(self):
        d=RecordDialog(self,'Inicio del runtime',[
            ('startup','Scripts (orden de la lista)','multi',[],[(n,n) for n in self.host.project.scripts]),
            ('timeout_seconds','Límite por ejecución (s)','number',10,())], self.host.project.automation)
        if d.exec()==QDialog.DialogCode.Accepted:
            self.host.mutate(lambda:self.host.project.automation.update(d.data()))

    def refresh_diagnostics(self):
        runtime=self.host.runtime
        if runtime:
            import datetime
            text='\n'.join(f"{datetime.datetime.fromtimestamp(row['time']).strftime('%H:%M:%S')}  {row['script']}  {row['status']}\n{row['message']}"
                           for row in runtime.scripts.diagnostics())
            if self.diagnostics.toPlainText()!=text: self.diagnostics.setPlainText(text)
