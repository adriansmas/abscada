"""Visual conditions and state appearance, configured without expressions."""
import copy
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QCheckBox,QComboBox,QLineEdit,
    QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QTabWidget,QDialogButtonBox,QLabel,QGroupBox,QScrollArea)
from .dialogs import EditorDialog
from .value_editor import ValueEditor
from .graphic_properties import ColorField
from . import dynamics
from .i18n import tr


def available_tags(studio):
    result=studio.project.tags()
    if studio.document_kind=='faceplates': result|={'$'+n:dict(type=k,writable=True) for n,k in studio.document().get('parameters',{}).items()}
    return result


class ConditionForm(QWidget):
    def __init__(self,studio,value=None,optional=True):
        super().__init__(); self.tags=available_tags(studio)
        form=QFormLayout(self); form.setContentsMargins(0,0,0,0)
        self.active=QCheckBox(tr('Cuando se cumpla')); self.active.setChecked(bool(value) or not optional)
        if optional: form.addRow(self.active)
        self.tag=QComboBox(); self.tag.setEditable(True); self.tag.addItems(list(self.tags))
        self.op=QComboBox()
        self.value=ValueEditor('bool',False)
        self.bad=QCheckBox(tr('Cumplir condición sin calidad válida'))
        for title,control in [(tr('Variable'),self.tag),(tr('Operador'),self.op),(tr('Valor'),self.value),('',self.bad)]: form.addRow(title,control)
        def update():
            kind=self.tags.get(self.tag.currentText(),{}).get('type','bool')
            previous=self.op.currentData(); self.op.clear()
            for key,label in [('eq',tr('Igual a')),('ne',tr('Distinto de'))]+([('gt',tr('Mayor que')),('ge',tr('Mayor o igual')),('lt',tr('Menor que')),('le',tr('Menor o igual'))] if kind in {'int','float'} else []): self.op.addItem(label,key)
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
    def __init__(self,value=None,kind='button',hint=True):
        super().__init__(); self.fields={}; form=QFormLayout(self); form.setContentsMargins(0,0,0,0)
        supported=dynamics.style_keys(kind)
        for key,title in [('color',tr('Fondo')),('text_color',tr('Color del texto')),('border_color',tr('Borde')),('stroke_color',tr('Trazo')),('text',tr('Texto mostrado')),('source',tr('Imagen (ruta del proyecto)'))]:
            if key not in supported: continue
            field=ColorField(lambda:None) if key in dynamics.COLOR_KEYS else QLineEdit()
            field.setText((value or {}).get(key,'')); self.fields[key]=field; form.addRow(title,field)
        if hint: form.addRow(QLabel(tr('Vacío: conservar la propiedad del objeto')))

    def data(self): return {key:field.text() for key,field in self.fields.items() if field.text()}


class DynamicDialog(EditorDialog):
    """Appearance (one page, in the order it is applied), visibility and enabling of one element."""
    def __init__(self,studio,element):
        super().__init__(studio); self.studio=studio; self.element=element
        self.setWindowTitle(tr('Propiedades dinámicas · ')+element['id']); self.resize(720,640)
        layout=QVBoxLayout(self); tabs=QTabWidget(); layout.addWidget(tabs)
        d=element.get('dynamics',{})
        appearance=QWidget(); page=QVBoxLayout(appearance)
        intro=QLabel(tr('Cómo se ve el elemento en el runtime. Se aplica en este orden; lo que dejes vacío conserva '
                     'la propiedad normal del elemento.'))
        intro.setWordWrap(True); intro.setObjectName('muted'); page.addWidget(intro)
        self.lamp={}
        if element['kind']=='lamp':
            group=QGroupBox(tr('Colores del piloto'));form=QFormLayout(group)
            for key,title,default in [('off',tr('Apagado (falso / 0)'),'#d7e0e9'),('on',tr('Encendido (verdadero / 1)'),'#14b889'),('bad',tr('Sin comunicación'),'#e5a339')]:
                field=ColorField(lambda:None); field.setText(element.get('lamp_colors',{}).get(key,default));self.lamp[key]=field; form.addRow(title,field)
            page.addWidget(group)
        self.styles={}
        def style_group(key,title,hint):
            group=QGroupBox(title); box=QVBoxLayout(group)
            if hint:
                note=QLabel(hint); note.setWordWrap(True); note.setObjectName('muted'); box.addWidget(note)
            field=StyleForm(d.get(key),element['kind'],hint=False); self.styles[key]=field; box.addWidget(field)
            return group
        page.addWidget(style_group('default','1 · Normal',tr('Apariencia fija en el runtime.')))
        states=QGroupBox(tr('2 · Según el valor de variables')); box=QVBoxLayout(states)
        note=QLabel(tr('Por ejemplo: rojo si Bomba.Fallo es verdadero. Se usa el primer estado que se cumpla.'))
        note.setWordWrap(True); note.setObjectName('muted'); box.addWidget(note)
        self.states=copy.deepcopy(d.get('states',[])); self.table=QTableWidget(0,2); self.table.setHorizontalHeaderLabels([tr('Cuando'),tr('Apariencia')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(110)
        box.addWidget(self.table); row=QHBoxLayout(); box.addLayout(row)
        operators={'eq':'=','ne':'≠','gt':'>','ge':'≥','lt':'<','le':'≤'}
        def refresh():
            self.table.setRowCount(len(self.states))
            for i,state in enumerate(self.states):
                c=state['when']; self.table.setItem(i,0,QTableWidgetItem(f"{c['tag']} {operators.get(c['op'],c['op'])} {c['value']}")); self.table.setItem(i,1,QTableWidgetItem(' · '.join(f'{k}: {v}' for k,v in state['style'].items())))
        def edit(new):
            index=-1 if new else self.table.currentRow()
            if not new and index<0: return
            current={} if new else self.states[index]
            dialog=EditorDialog(self); dialog.setWindowTitle(tr('Estado')); content=QVBoxLayout(dialog)
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
        for title,callback in [(tr('Añadir estado'),lambda:edit(True)),(tr('Editar'),lambda:edit(False)),(tr('Eliminar'),remove),(tr('Subir'),move)]:
            b=QPushButton(title);b.clicked.connect(callback);row.addWidget(b)
        row.addStretch()
        self.table.cellDoubleClicked.connect(lambda r,c: edit(False))
        refresh(); page.addWidget(states)
        page.addWidget(style_group('bad',tr('3 · Sin comunicación (mala calidad)'),tr('Cuando alguna de sus variables no tiene un valor válido del PLC.')))
        page.addWidget(style_group('disabled','4 · Deshabilitado',tr('Cuando no se cumple la condición de la pestaña «Habilitación».')))
        page.addStretch()
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(appearance)
        has_style=bool(dynamics.style_keys(element['kind'])) or element['kind']=='lamp'
        if has_style:
            tabs.addTab(scroll,tr('Apariencia'))
        self.visible=ConditionForm(studio,d.get('visible')); tabs.addTab(self.visible,tr('Visibilidad'))
        enabled=QWidget(); form=QVBoxLayout(enabled); self.enabled=ConditionForm(studio,d.get('enabled')); form.addWidget(self.enabled)
        self.reason=QLineEdit(d.get('disabled_reason','')); self.reason.setPlaceholderText(tr('Motivo de bloqueo (se muestra al pasar el ratón)')); form.addWidget(self.reason); form.addStretch()
        tabs.addTab(enabled,tr('Habilitación'))
        self.validator=self.validate; studio.dialog_buttons(self,layout)

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
