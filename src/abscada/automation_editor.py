"""Engineering surface for Python sources, startup hooks and cyclic tasks."""
import copy
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QPlainTextEdit,QAbstractItemView,
    QPushButton,QDialog,QTabWidget,QLabel,QLineEdit,QMenu,QTreeWidget,QTreeWidgetItem,QStyle,QInputDialog,QMessageBox)
from .engineering import RecordsPage, RecordDialog
from .scripting import validate_scripts
from . import script_tree
from .i18n import tr

ROLE = Qt.ItemDataRole.UserRole


class ScriptTree(QTreeWidget):
    """Scripts in folders. Drag a script or a folder onto a folder to move it; F2 renames."""
    def __init__(self, editor):
        super().__init__(); self.editor = editor
        self.setHeaderHidden(True); self.setIndentation(12)
        self.setDragEnabled(True); self.setAcceptDrops(True); self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F2:
            self.editor.rename(self.currentItem())
        else:
            super().keyPressEvent(event)

    def dropEvent(self, event):
        # The tree is rebuilt from the project after the move; Qt must not move the items itself.
        source, target = self.currentItem(), self.itemAt(event.position().toPoint())
        event.setDropAction(Qt.DropAction.IgnoreAction); event.accept()
        if source is not None:
            self.editor.drop(source.data(0, ROLE), target.data(0, ROLE) if target else None)


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
        split=QSplitter(); self.tree=ScriptTree(self)
        self.tree.customContextMenuRequested.connect(self.menu)
        # The last line of the list: type the name of a new script and press Enter.
        self.new_name=QLineEdit(); self.new_name.setObjectName('newScriptName'); self.new_name.setClearButtonEnabled(True)
        self.new_name.setPlaceholderText(tr('+ Nuevo script: escribe el nombre y pulsa Intro'))
        self.new_name.returnPressed.connect(self.create_from_field)
        side=QWidget(); side_layout=QVBoxLayout(side); side_layout.setContentsMargins(0,0,0,0); side_layout.setSpacing(2)
        side_layout.addWidget(self.tree,1); side_layout.addWidget(self.new_name)
        side.setMaximumWidth(260)
        from .python_editor import PythonHighlighter, PythonCodeEditor
        self.code=PythonCodeEditor(); self.code.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.highlighter=PythonHighlighter(self.code.document())
        self.code.setTabStopDistance(32)
        self.code.setEnabled(False)
        split.addWidget(side); split.addWidget(self.code); layout.addWidget(split,1)
        self.result=QLabel(); self.result.setWordWrap(True); self.result.setMaximumHeight(48); layout.addWidget(self.result)
        self.tree.currentItemChanged.connect(lambda item, _: self.select(self.script_of(item)))
        self.code.textChanged.connect(self.changed)
        self.addTab(page,tr('Scripts Python'))
        self.tasks=RecordsPage(host,lambda:host.project.automation.get('tasks',[]),
            lambda rows:host.project.automation.__setitem__('tasks',rows),
            [('id',tr('Tarea')),('script',tr('Script')),('interval_ms',tr('Periodo (ms)')),('enabled',tr('Activa'))],
            lambda:[('id',tr('Nombre'),'text','',()),('script',tr('Script'),'choice','',script_tree.choices(host.project)),
                    ('interval_ms',tr('Periodo (ms)'),'int',1000,()),('enabled',tr('Activa'),'bool',True,())], tr('Tarea'))
        self.addTab(self.tasks,tr('Tareas cíclicas'))
        self.diagnostics=QPlainTextEdit(); self.diagnostics.setReadOnly(True); self.addTab(self.diagnostics,tr('Ejecuciones'))
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh_diagnostics); self.timer.start(500)
        self.refresh()

    def refresh(self):
        self.end_edit_group()
        self.loading=True
        project=self.host.project
        name=self.current if self.current in project.scripts else None
        self.tree.clear()
        folder_icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        nodes={}
        def parent(path): return nodes[path] if path else self.tree.invisibleRootItem()
        for path in script_tree.folders(project):
            item=QTreeWidgetItem(parent(script_tree.parent_folder(path)),[path.rpartition('/')[2]])
            item.setIcon(0,folder_icon); item.setData(0,ROLE,('folder',path)); nodes[path]=item
        current=None
        for script in script_tree.ordered(project):
            item=QTreeWidgetItem(parent(script_tree.folder_of(project,script)),[script])
            item.setData(0,ROLE,('script',script))
            if script==name or (current is None and not name): current=item
        self.tree.expandAll()
        if current: self.tree.setCurrentItem(current)
        self.loading=False
        self.select(self.script_of(self.tree.currentItem()))
        self.code.setPlaceholderText(tr('Selecciona un script de la lista para editarlo.') if project.scripts else
            tr('Todavía no hay scripts. Escribe un nombre en el campo de abajo a la izquierda y pulsa Intro para crear el primero.'))
        self.tasks.refresh()

    @staticmethod
    def script_of(item):
        value=item.data(0,ROLE) if item else None
        return value[1] if value and value[0]=='script' else ''

    def selected_folder(self):
        """Folder that receives a new script: the selected folder, or the folder of the selected script."""
        item=self.tree.currentItem(); value=item.data(0,ROLE) if item else None
        if not value: return ''
        return value[1] if value[0]=='folder' else script_tree.folder_of(self.host.project,value[1])

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
        name=self.new_name.text().strip()
        if not name: return
        try: script_tree.check_new_name(self.host.project,name)
        except ValueError as exc: self.host.error(exc); return
        folder=self.selected_folder()
        if self.host.mutate(lambda:script_tree.add_script(self.host.project,name,self.TEMPLATE,folder)):
            self.current=name; self.new_name.clear(); self.refresh(); self.code.setFocus()

    def duplicate(self):
        if not self.current: return
        project=self.host.project
        source=self.current; name=source+'_copia'; number=2
        while name.casefold() in {n.casefold() for n in project.scripts}: name=f'{source}_copia{number}'; number+=1
        if self.host.mutate(lambda:script_tree.add_script(project,name,project.scripts[source],script_tree.folder_of(project,source))):
            self.current=name; self.refresh()

    def ask_text(self,title,label,text=''):
        value,ok=QInputDialog.getText(self,title,label,text=text)
        return value.strip() if ok and value.strip() else None

    def menu(self,position):
        item=self.tree.itemAt(position)
        if item: self.tree.setCurrentItem(item)
        value=item.data(0,ROLE) if item else None
        project=self.host.project
        menu=QMenu(self.tree)
        if value is None or value[0]=='folder':
            folder=value[1] if value else ''
            menu.addAction(tr('Nuevo script'),self.add)
            menu.addAction(tr('Nueva carpeta…'),lambda:self.new_folder(folder))
            if value:
                menu.addSeparator()
                menu.addAction(tr('Renombrar carpeta…'),lambda:self.rename(item))
                menu.addAction(tr('Eliminar carpeta (su contenido sube un nivel)'),
                               lambda:self.host.mutate(lambda:script_tree.delete_folder(project,folder)))
        else:
            name=value[1]
            menu.addAction(tr('Renombrar…'),lambda:self.rename(item))
            menu.addAction(tr('Duplicar'),self.duplicate)
            move=menu.addMenu(tr('Mover a carpeta'))
            current=script_tree.folder_of(project,name)
            for path in ['']+script_tree.folders(project):
                action=move.addAction(tr('(raíz de Scripts)') if not path else '    '*path.count('/')+path.rpartition('/')[2],
                                      lambda p=path:self.host.mutate(lambda:script_tree.move_script(project,name,p)))
                action.setEnabled(path!=current)
            menu.addSeparator()
            menu.addAction(tr('Eliminar'),self.remove)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def new_folder(self,parent):
        name=self.ask_text(tr('Nueva carpeta'),tr('Nombre de la carpeta')+(tr(' dentro de «{parent}»',parent=parent) if parent else ''))
        if name: self.host.mutate(lambda:script_tree.add_folder(self.host.project,parent,name))

    def rename(self,item):
        value=item.data(0,ROLE) if item else None
        if not value: return
        project=self.host.project
        if value[0]=='folder':
            name=self.ask_text(tr('Renombrar carpeta'),tr('Nuevo nombre'),value[1].rpartition('/')[2])
            if name: self.host.mutate(lambda:script_tree.rename_folder(project,value[1],name))
            return
        old=value[1]
        new=self.ask_text(tr('Renombrar script'),tr('Nuevo nombre de archivo (letras sin acentos, números, _ y -)'),old)
        if new and new!=old: self.rename_script(old,new)

    def rename_script(self,old,new):
        pending=[]
        if self.host.mutate(lambda:pending.extend(script_tree.rename_script(self.host.project,old,new))):
            self.current=new; self.refresh()
            if pending:
                QMessageBox.information(self,tr('Script renombrado'),
                    tr('Los botones, eventos y tareas se han actualizado. Revisa estos scripts, que mencionan «{old}» como texto: {join}',
                       old=old,join=', '.join(pending)))

    def drop(self,source,target):
        project=self.host.project
        if not source: return
        folder='' if target is None else target[1] if target[0]=='folder' else script_tree.folder_of(project,target[1])
        if source[0]=='script' and script_tree.folder_of(project,source[1])!=folder:
            self.host.mutate(lambda:script_tree.move_script(project,source[1],folder))
        elif source[0]=='folder' and script_tree.parent_folder(source[1])!=folder:
            self.host.mutate(lambda:script_tree.move_folder(project,source[1],folder))

    def remove(self):
        if self.current:
            name=self.current
            used=script_tree.references(self.host.project,name)
            if used:
                self.host.error(tr('No se puede eliminar «{name}» porque se usa en:\n· ',name=name)+'\n· '.join(used)); return
            self.host.mutate(lambda:script_tree.delete_script(self.host.project,name))

    def check(self):
        try:
            validate_scripts(self.host.project); self.result.setText(tr('Sintaxis y referencias correctas'))
        except ValueError as exc: self.result.setText(str(exc))

    def startup(self):
        d=RecordDialog(self,tr('Inicio del runtime'),[
            ('startup',tr('Scripts (orden de la lista)'),'multi',[],script_tree.choices(self.host.project,self.host.project.automation.get('startup',[]))),
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
