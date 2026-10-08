"""Engineering surface for Python sources, startup hooks and cyclic tasks."""
import copy
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QListWidget,QPlainTextEdit,
    QPushButton,QDialog,QTabWidget,QLabel,QLineEdit,QMenu)
from .engineering import RecordsPage, RecordDialog
from .scripting import validate_scripts
from .i18n import tr


class AutomationEditor(QTabWidget):
    def __init__(self, host):
        super().__init__(); self.host=host; self.loading=False; self.current=None
        self.edit_group=False
        self.edit_timer=QTimer(self); self.edit_timer.setSingleShot(True)
        self.edit_timer.timeout.connect(self.end_edit_group)
        page=QWidget(); layout=QVBoxLayout(page)
        intro=QLabel(tr('Un script es un programa Python que automatiza el proyecto. Se ejecuta desde un botón (acción «Ejecutar script»), '
                        'al abrir una pantalla, al arrancar el runtime («Eventos de inicio…») o cada cierto tiempo (pestaña «Tareas cíclicas»).'))
        intro.setWordWrap(True); intro.setObjectName('muted'); layout.addWidget(intro)
        actions=QHBoxLayout()
        for text, callback in [(tr('Nuevo script'),self.add),(tr('Eliminar'),self.remove),(tr('Comprobar'),self.check),(tr('Eventos de inicio…'),self.startup)]:
            b=QPushButton(text); b.clicked.connect(callback); actions.addWidget(b)
        actions.addStretch(); layout.addLayout(actions)
        split=QSplitter(); self.list=QListWidget(); self.list.setMaximumWidth(260)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.menu)
        # The last line of the list: type the name of a new script and press Enter.
        self.new_name=QLineEdit(); self.new_name.setObjectName('newScriptName'); self.new_name.setClearButtonEnabled(True)
        self.new_name.setPlaceholderText(tr('+ Nuevo script: escribe el nombre y pulsa Intro'))
        self.new_name.returnPressed.connect(self.create_from_field)
        side=QWidget(); side_layout=QVBoxLayout(side); side_layout.setContentsMargins(0,0,0,0); side_layout.setSpacing(2)
        side_layout.addWidget(self.list,1); side_layout.addWidget(self.new_name)
        side.setMaximumWidth(260)
        from .python_editor import PythonHighlighter, PythonCodeEditor
        self.code=PythonCodeEditor(); self.code.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.highlighter=PythonHighlighter(self.code.document())
        self.code.setTabStopDistance(32)
        self.code.setEnabled(False)
        split.addWidget(side); split.addWidget(self.code); layout.addWidget(split,1)
        self.result=QLabel(); self.result.setWordWrap(True); self.result.setMaximumHeight(48); layout.addWidget(self.result)
        self.list.currentTextChanged.connect(self.select); self.code.textChanged.connect(self.changed)
        self.addTab(page,tr('Scripts Python'))
        self.tasks=RecordsPage(host,lambda:host.project.automation.get('tasks',[]),
            lambda rows:host.project.automation.__setitem__('tasks',rows),
            [('id',tr('Tarea')),('script',tr('Script')),('interval_ms',tr('Periodo (ms)')),('enabled',tr('Activa'))],
            lambda:[('id',tr('Nombre'),'text','',()),('script',tr('Script'),'choice','',[(n,n) for n in host.project.scripts]),
                    ('interval_ms',tr('Periodo (ms)'),'int',1000,()),('enabled',tr('Activa'),'bool',True,())], tr('Tarea'))
        self.addTab(self.tasks,tr('Tareas cíclicas'))
        self.diagnostics=QPlainTextEdit(); self.diagnostics.setReadOnly(True); self.addTab(self.diagnostics,tr('Ejecuciones'))
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
        self.code.setPlaceholderText(tr('Selecciona un script de la lista para editarlo.') if self.list.count() else
            tr('Todavía no hay scripts. Escribe un nombre en el campo de abajo a la izquierda y pulsa Intro para crear el primero.'))
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

    TEMPLATE='# API: ctx.read, ctx.quality, ctx.write, ctx.state\nprint(ctx.event)\n'

    def add(self):
        self.new_name.setFocus()

    def create_from_field(self):
        import re
        name=self.new_name.text().strip()
        if not name: return
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):
            self.host.error(tr('Usa solo letras sin acentos, números, «_» y «-»')); return
        if name in self.host.project.scripts: self.host.error(tr('El script ya existe')); return
        if self.host.mutate(lambda:self.host.project.scripts.__setitem__(name,self.TEMPLATE)):
            self.current=name; self.new_name.clear(); self.refresh(); self.code.setFocus()

    def duplicate(self):
        if not self.current: return
        source=self.current; name=source+'_copia'; number=2
        while name in self.host.project.scripts: name=f'{source}_copia{number}'; number+=1
        if self.host.mutate(lambda:self.host.project.scripts.__setitem__(name,self.host.project.scripts[source])):
            self.current=name; self.refresh()

    def menu(self,position):
        item=self.list.itemAt(position)
        if item: self.list.setCurrentItem(item)
        menu=QMenu(self.list)
        menu.addAction(tr('Nuevo script'),self.add)
        if item:
            menu.addAction(tr('Duplicar'),self.duplicate)
            menu.addSeparator()
            menu.addAction(tr('Eliminar'),self.remove)
        menu.exec(self.list.mapToGlobal(position))

    def remove(self):
        if self.current:
            name=self.current
            self.host.mutate(lambda:self.host.project.scripts.pop(name))

    def check(self):
        try:
            validate_scripts(self.host.project); self.result.setText(tr('Sintaxis y referencias correctas'))
        except ValueError as exc: self.result.setText(str(exc))

    def startup(self):
        d=RecordDialog(self,tr('Inicio del runtime'),[
            ('startup',tr('Scripts (orden de la lista)'),'multi',[],[(n,n) for n in self.host.project.scripts]),
            ('timeout_seconds',tr('Límite por ejecución (s)'),'number',10,())], self.host.project.automation)
        if d.exec()==QDialog.DialogCode.Accepted:
            self.host.mutate(lambda:self.host.project.automation.update(d.data()))

    def refresh_diagnostics(self):
        runtime=self.host.runtime
        if runtime:
            import datetime
            text='\n'.join(f"{datetime.datetime.fromtimestamp(row['time']).strftime('%H:%M:%S')}  {row['script']}  {row['status']}\n{row['message']}"
                           for row in runtime.scripts.diagnostics())
            if self.diagnostics.toPlainText()!=text: self.diagnostics.setPlainText(text)
