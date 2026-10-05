"""Visual conditions and state appearance, configured without expressions."""
import copy
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QCheckBox,QComboBox,QLineEdit,
    QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QTabWidget,QDialogButtonBox,QLabel)
from .dialogs import EditorDialog
from .value_editor import ValueEditor
from .graphic_properties import ColorField
from . import dynamics


def available_tags(studio):
    result=studio.project.tags()
    if studio.document_kind=='faceplates': result|={'$'+n:dict(type=k,writable=True) for n,k in studio.document().get('parameters',{}).items()}
    return result


class ConditionForm(QWidget):
    def __init__(self,studio,value=None,optional=True):
        super().__init__(); self.tags=available_tags(studio)
        form=QFormLayout(self); form.setContentsMargins(0,0,0,0)
        self.active=QCheckBox('Cuando se cumpla'); self.active.setChecked(bool(value) or not optional)
        if optional: form.addRow(self.active)
        self.tag=QComboBox(); self.tag.setEditable(True); self.tag.addItems(list(self.tags))
        self.op=QComboBox()
        self.value=ValueEditor('bool',False)
        self.bad=QCheckBox('Cumplir condición sin calidad válida')
        for title,control in [('Variable',self.tag),('Operador',self.op),('Valor',self.value),('',self.bad)]: form.addRow(title,control)
        def update():
            kind=self.tags.get(self.tag.currentText(),{}).get('type','bool')
            previous=self.op.currentData(); self.op.clear()
            for key,label in [('eq','Igual a'),('ne','Distinto de')]+([('gt','Mayor que'),('ge','Mayor o igual'),('lt','Menor que'),('le','Menor o igual')] if kind in {'int','float'} else []): self.op.addItem(label,key)
            self.op.setCurrentIndex(max(0,self.op.findData(previous))); self.value.set_kind(kind)
        self.tag.currentTextChanged.connect(update); update()
        if value:
            self.tag.setCurrentText(value['tag']); update(); self.op.setCurrentIndex(self.op.findData(value['op']))
            self.value.set_kind(self.tags[value['tag']]['type'],value['value']); self.bad.setChecked(value.get('bad',False))
        def enable():
            for control in (self.tag,self.op,self.value,self.bad): control.setEnabled(self.active.isChecked())
        self.active.toggled.connect(enable); enable()

    def data(self):
        return dict(tag=self.tag.currentText(),op=self.op.currentData(),value=self.value.value(),bad=self.bad.isChecked()) if self.active.isChecked() else None


class StyleForm(QWidget):
    def __init__(self,value=None,kind='button'):
        super().__init__(); self.fields={}; form=QFormLayout(self)
        supported=dynamics.style_keys(kind)
        for key,title in [('color','Fondo / relleno'),('text_color','Texto'),('border_color','Borde'),('stroke_color','Trazo'),('text','Texto mostrado'),('source','Imagen (ruta del proyecto)')]:
            if key not in supported: continue
            field=ColorField(lambda:None) if key in dynamics.COLOR_KEYS else QLineEdit()
            field.setText((value or {}).get(key,'')); self.fields[key]=field; form.addRow(title,field)
        hint=QLabel('Vacío: conservar la propiedad del objeto'); form.addRow(hint)

    def data(self): return {key:field.text() for key,field in self.fields.items() if field.text()}


class DynamicDialog(EditorDialog):
    def __init__(self,studio,element):
        super().__init__(studio); self.studio=studio; self.element=element
        self.setWindowTitle('Condiciones y estados · '+element['id']); self.resize(690,580)
        layout=QVBoxLayout(self); tabs=QTabWidget(); layout.addWidget(tabs)
        d=element.get('dynamics',{})
        self.visible=ConditionForm(studio,d.get('visible')); tabs.addTab(self.visible,'Visibilidad')
        enabled=QWidget(); form=QVBoxLayout(enabled); self.enabled=ConditionForm(studio,d.get('enabled')); form.addWidget(self.enabled)
        self.reason=QLineEdit(d.get('disabled_reason','')); self.reason.setPlaceholderText('Motivo de bloqueo (tooltip)'); form.addWidget(self.reason); form.addStretch()
        tabs.addTab(enabled,'Habilitación')
        page=QWidget(); box=QVBoxLayout(page)
        self.states=copy.deepcopy(d.get('states',[])); self.table=QTableWidget(0,2); self.table.setHorizontalHeaderLabels(['Condición (primera coincidencia)','Apariencia'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        box.addWidget(self.table); row=QHBoxLayout(); box.addLayout(row)
        def refresh():
            self.table.setRowCount(len(self.states))
            for i,state in enumerate(self.states):
                c=state['when']; self.table.setItem(i,0,QTableWidgetItem(f"{c['tag']} {c['op']} {c['value']}")); self.table.setItem(i,1,QTableWidgetItem(' · '.join(f'{k}: {v}' for k,v in state['style'].items())))
        def edit(new):
            index=-1 if new else self.table.currentRow()
            if not new and index<0: return
            current={} if new else self.states[index]
            dialog=EditorDialog(self); dialog.setWindowTitle('Estado'); content=QVBoxLayout(dialog)
            cond=ConditionForm(studio,current.get('when'),False); style=StyleForm(current.get('style'),element['kind'])
            content.addWidget(cond); content.addWidget(style)
            def state(): return dict(when=cond.data(),style=style.data())
            def validate():
                candidate=copy.deepcopy(element); candidate['dynamics']={'states':[state()]}
                dynamics.validate(candidate,studio.project.tags(),studio.document().get('parameters',{}),studio.project.manifest.get('palette',{}))
            dialog.validator=validate; studio.dialog_buttons(dialog,content)
            if dialog.exec()==EditorDialog.DialogCode.Accepted:
                if new:self.states.append(state())
                else:self.states[index]=state()
                refresh()
        def remove():
            i=self.table.currentRow()
            if i>=0: self.states.pop(i); refresh()
        def move():
            i=self.table.currentRow()
            if i>0:self.states[i-1],self.states[i]=self.states[i],self.states[i-1];refresh();self.table.selectRow(i-1)
        for title,callback in [('Añadir',lambda:edit(True)),('Editar',lambda:edit(False)),('Eliminar',remove),('Subir',move)]:
            b=QPushButton(title);b.clicked.connect(callback);row.addWidget(b)
        refresh(); tabs.addTab(page,'Estados')
        self.styles={}
        for key,title in [('default','Predeterminado'),('bad','Mala calidad'),('disabled','Deshabilitado')]:
            field=StyleForm(d.get(key),element['kind']); self.styles[key]=field; tabs.addTab(field,title)
        self.lamp={}
        if element['kind']=='lamp':
            page=QWidget();form=QFormLayout(page)
            for key,title,default in [('off','Falso / 0','#d7e0e9'),('on','Verdadero / 1','#14b889'),('bad','Sin calidad válida','#e5a339')]:
                field=ColorField(lambda:None); field.setText(element.get('lamp_colors',{}).get(key,default));self.lamp[key]=field; form.addRow(title,field)
            tabs.insertTab(0,page,'Piloto');tabs.setCurrentIndex(0)
        self.validator=self.validate; studio.dialog_buttons(self,layout)
        if element['kind'] in {'faceplate','screen_container','trend','alarm_view'}:
            for i in range(tabs.count()-1,1,-1):tabs.setTabVisible(i,False)

    def data(self):
        d={key:field.data() for key,field in self.styles.items() if field.data()}
        if self.visible.data(): d['visible']=self.visible.data()
        if self.enabled.data(): d['enabled']=self.enabled.data()
        if self.reason.text(): d['disabled_reason']=self.reason.text()
        if self.states:d['states']=copy.deepcopy(self.states)
        result=copy.deepcopy(self.element); result['dynamics']=d
        if self.lamp:result['lamp_colors']={key:field.text() for key,field in self.lamp.items()}
        return result

    def validate(self):
        dynamics.validate(self.data(),self.studio.project.tags(),self.studio.document().get('parameters',{}),self.studio.project.manifest.get('palette',{}))


def edit_dynamics(studio):
    items=studio.scene.selectedItems()
    if len(items)!=1:return
    source=items[0].element; dialog=DynamicDialog(studio,source)
    if dialog.exec()==EditorDialog.DialogCode.Accepted:
        data=dialog.data(); studio.mutate(lambda:source.update(data))
