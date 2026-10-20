"""Visual conditions and state appearance, configured without expressions."""
import copy
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QCheckBox,QComboBox,QLineEdit,
    QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QTabWidget,QLabel,QGroupBox,QScrollArea,QDoubleSpinBox)
from .dialogs import EditorDialog
from .value_editor import ValueEditor
from .graphic_properties import ColorField
from . import dynamics
from .i18n import tr
from .structures import PRIMITIVES


def parameter_values(studio):
    """Primitive $references of the object being edited ($run, $motor.marcha, $temps[0])."""
    return {n:k for n,k in studio.document_references().items() if k in PRIMITIVES}


def available_tags(studio):
    result=studio.project.tags()
    result|={'$'+n:dict(type=k,writable=True) for n,k in parameter_values(studio).items()}
    return result


def check(studio,element):
    """dynamics.validate on the element, with variable indices checked and set to a sample index."""
    project=studio.project; tags=project.tags()
    roots={v['name']:v['type'] for v in project.variables}
    parameters=studio.document().get('parameters',{}) if studio.document_kind=='faceplates' else {}
    element=project._concrete(studio.document_name,element,tags,roots,parameters,parameter_values(studio))
    dynamics.validate(element,tags,parameter_values(studio))


def reference_kind(studio,tags,name):
    """Type of a variable, a $reference or a path with a variable index (Juegos[Sel].Temp)."""
    if name in tags: return tags[name]['type']
    from .structures import sample_path
    roots={v['name']:v['type'] for v in studio.project.variables}|{'$'+n:k for n,k in studio.document_references().items()}
    sample=sample_path(studio.project.types,roots,name)
    return tags.get(sample,{}).get('type') if sample else None


class ConditionForm(QWidget):
    def __init__(self,studio,value=None,optional=True):
        super().__init__(); self.tags=available_tags(studio); self.studio=studio
        form=QFormLayout(self); form.setContentsMargins(0,0,0,0)
        self.active=QCheckBox(tr('Cuando se cumpla')); self.active.setChecked(bool(value) or not optional)
        if optional: form.addRow(self.active)
        self.tag=QComboBox(); self.tag.setEditable(True); self.tag.addItems(list(self.tags))
        self.op=QComboBox()
        self.value=ValueEditor('bool',False)
        self.bad=QCheckBox(tr('Cumplir condición sin calidad válida'))
        for title,control in [(tr('Variable'),self.tag),(tr('Operador'),self.op),(tr('Valor'),self.value),('',self.bad)]: form.addRow(title,control)
        def update():
            kind=reference_kind(studio,self.tags,self.tag.currentText()) or 'bool'
            previous=self.op.currentData(); self.op.clear()
            for key,label in [('eq',tr('Igual a')),('ne',tr('Distinto de'))]+([('gt',tr('Mayor que')),('ge',tr('Mayor o igual')),('lt',tr('Menor que')),('le',tr('Menor o igual'))] if kind in {'int','float'} else []): self.op.addItem(label,key)
            self.op.setCurrentIndex(max(0,self.op.findData(previous))); self.value.set_kind(kind)
            # «es igual a» / «es distinto de» say the same for a bool: only «Verdadero / Falso» is asked.
            form.setRowVisible(self.op,kind!='bool')
            label=form.labelForField(self.value)
            if label: label.setText(tr('Cuando sea') if kind=='bool' else tr('Valor'))
        self.tag.currentTextChanged.connect(update); update()
        if value:
            self.tag.setCurrentText(value['tag']); update(); self.op.setCurrentIndex(self.op.findData(value['op']))
            shown=value['value']
            if isinstance(shown,bool) and value['op']=='ne': shown=not shown  # «≠ verdadero» is «falso»
            self.value.set_kind(reference_kind(studio,self.tags,value['tag']) or 'bool',shown); self.bad.setChecked(value.get('bad',False))
        def enable():
            for control in (self.tag,self.op,self.value,self.bad): control.setEnabled(self.active.isChecked())
        self.active.toggled.connect(enable); enable()

    def data(self):
        return dict(tag=self.tag.currentText(),op='eq' if self.value.kind=='bool' else self.op.currentData(),value=self.value.value(),bad=self.bad.isChecked()) if self.active.isChecked() else None


OPERATORS={'eq':'=','ne':'≠','gt':'>','ge':'≥','lt':'<','le':'≤'}


def describe_condition(condition):
    """«Bomba.Fallo es verdadero y Nivel > 80»."""
    parts=[]
    for c in dynamics.conditions(condition):
        if isinstance(c['value'],bool):
            shown=c['value'] if c['op']=='eq' else not c['value']
            parts.append(f"{c['tag']} "+(tr('es verdadero') if shown else tr('es falso')))
        else: parts.append(f"{c['tag']} {OPERATORS.get(c['op'],c['op'])} {c['value']}")
    return tr(' y ').join(parts)


class ConditionList(QWidget):
    """One condition or several that must all hold («Y además…»)."""
    def __init__(self,studio,value=None,optional=True):
        super().__init__(); self.studio=studio; self.rows=[]
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.active=QCheckBox(tr('Cuando se cumpla')); self.active.setChecked(bool(value) or not optional)
        if optional: layout.addWidget(self.active)
        self.box=QVBoxLayout(); layout.addLayout(self.box)
        self.more=QPushButton(tr('+ Y además…')); self.more.setToolTip(tr('Otra condición que también se tiene que cumplir'))
        self.more.clicked.connect(lambda: self.add(None)); layout.addWidget(self.more)
        for item in dynamics.conditions(value) or [None]: self.add(item)
        self.active.toggled.connect(self.enable); self.enable()

    def add(self,value):
        frame=QWidget(); row=QVBoxLayout(frame); row.setContentsMargins(0,0,0,0)
        if self.rows:
            head=QHBoxLayout(); head.addWidget(QLabel(tr('Y además'))); head.addStretch()
            remove=QPushButton(tr('Quitar')); head.addWidget(remove); row.addLayout(head)
        form=ConditionForm(self.studio,value,False); row.addWidget(form)
        entry=(frame,form); self.rows.append(entry); self.box.addWidget(frame)
        if len(self.rows)>1:
            remove.clicked.connect(lambda: self.remove(entry))
        self.enable()

    def remove(self,entry):
        self.rows.remove(entry); entry[0].hide(); entry[0].setParent(None); entry[0].deleteLater()

    def enable(self):
        on=self.active.isChecked()
        for frame,_ in self.rows: frame.setEnabled(on)
        self.more.setEnabled(on)

    def data(self):
        if not self.active.isChecked(): return None
        found=[form.data() for _,form in self.rows]
        return found[0] if len(found)==1 else found


class StyleForm(QWidget):
    def __init__(self,value=None,kind='button',hint=True,host=None):
        super().__init__(); self.fields={}; form=QFormLayout(self); form.setContentsMargins(0,0,0,0)
        from .project_text_editor import ProjectTextField
        supported=dynamics.style_keys(kind)
        for key,title in [('color',tr('Fondo')),('text_color',tr('Color del texto')),('border_color',tr('Borde')),('stroke_color',tr('Trazo')),('text',tr('Texto mostrado')),('source',tr('Imagen (ruta del proyecto)'))]:
            if key not in supported: continue
            field=ColorField(lambda:None) if key in dynamics.COLOR_KEYS else ProjectTextField(host) if key == 'text' else QLineEdit()
            if isinstance(field, ProjectTextField):
                field.set_value((value or {}).get(key, ''))
            else:
                field.setText((value or {}).get(key, ''))
            self.fields[key]=field; form.addRow(title,field)
        if hint: form.addRow(QLabel(tr('Vacío: conservar la propiedad del objeto')))

    def data(self):
        return {key: field.translated_value() if hasattr(field, 'translated_value') else field.text()
            for key, field in self.fields.items()
            if field.text() or isinstance(getattr(field, 'original', None), dict)}


def number_field(value,low=-1e9,high=1e9,decimals=2,suffix=''):
    field=QDoubleSpinBox(); field.setRange(low,high); field.setDecimals(decimals); field.setValue(value)
    if suffix: field.setSuffix(suffix)
    return field


class MotionForm(QWidget):
    """Rotation by value, continuous rotation and fill level, each one optional."""
    def __init__(self,studio,element):
        super().__init__(); d=element.get('dynamics',{}); page=QVBoxLayout(self)
        numeric=[name for name,tag in available_tags(studio).items() if tag['type'] in {'int','float'}]
        def variable(current):
            combo=QComboBox(); combo.setEditable(True); combo.addItems(numeric); combo.setCurrentText(current); return combo
        self.rotation=self.fill=self.spin=self.move=self.scale=None
        if element['kind'] in dynamics.ROTATABLE:
            spec=d.get('rotation',{})
            group=QGroupBox(tr('Girar según una variable')); group.setCheckable(True); group.setChecked(bool(spec)); form=QFormLayout(group)
            note=QLabel(tr('El ángulo sigue al valor: el mínimo da el ángulo inicial y el máximo el final. Gira sobre su centro.'))
            note.setWordWrap(True); note.setObjectName('muted'); form.addRow(note)
            fields=dict(tag=variable(spec.get('tag','')),min=number_field(spec.get('min',0)),max=number_field(spec.get('max',100)),
                        **{'from':number_field(spec.get('from',0),-36000,36000,1,' °'),'to':number_field(spec.get('to',360),-36000,36000,1,' °')})
            for key,title in [('tag',tr('Variable')),('min',tr('Valor mínimo')),('max',tr('Valor máximo')),('from',tr('Ángulo en el mínimo')),('to',tr('Ángulo en el máximo'))]:
                form.addRow(title,fields[key])
            self.rotation=(group,fields); page.addWidget(group)
            spin=d.get('spin',{})
            group=QGroupBox(tr('Girar continuamente')); group.setCheckable(True); group.setChecked(bool(spin)); box=QVBoxLayout(group)
            note=QLabel(tr('Por ejemplo, un ventilador o un agitador que gira mientras el motor está en marcha.'))
            note.setWordWrap(True); note.setObjectName('muted'); box.addWidget(note)
            condition=ConditionList(studio,spin.get('when'),False); box.addWidget(condition)
            seconds=number_field(spin.get('seconds',2),0.2,3600,1,' s'); row=QFormLayout(); row.addRow(tr('Una vuelta cada'),seconds); box.addLayout(row)
            self.spin=(group,condition,seconds); page.addWidget(group)
        if element['kind'] in dynamics.FILLABLE:
            spec=d.get('fill',{})
            group=QGroupBox(tr('Nivel de llenado')); group.setCheckable(True); group.setChecked(bool(spec)); form=QFormLayout(group)
            note=QLabel(tr('Pinta el nivel sobre la propia figura: en una imagen SVG o PNG solo se colorea el dibujo, no el fondo transparente.'))
            note.setWordWrap(True); note.setObjectName('muted'); form.addRow(note)
            color=ColorField(lambda:None); color.setText(spec.get('color',dynamics.FILL_COLOR))
            direction=QComboBox()
            for key,title in [('up',tr('De abajo arriba')),('down',tr('De arriba abajo')),('right',tr('De izquierda a derecha')),('left',tr('De derecha a izquierda'))]: direction.addItem(title,key)
            direction.setCurrentIndex(max(0,direction.findData(spec.get('direction','up'))))
            fields=dict(tag=variable(spec.get('tag','')),min=number_field(spec.get('min',0)),max=number_field(spec.get('max',100)),color=color,direction=direction)
            for key,title in [('tag',tr('Variable')),('min',tr('Vacío en')),('max',tr('Lleno en')),('color',tr('Color (admite transparencia)')),('direction',tr('Dirección'))]:
                form.addRow(title,fields[key])
            self.fill=(group,fields); page.addWidget(group)
        if element['kind'] in dynamics.MOVABLE:
            spec=d.get('move',{})
            group=QGroupBox(tr('Desplazar según una variable')); group.setCheckable(True); group.setChecked(bool(spec)); form=QFormLayout(group)
            note=QLabel(tr('En el mínimo está donde lo dibujas; en el máximo, desplazado lo que indiques (en píxeles de la pantalla).'))
            note.setWordWrap(True); note.setObjectName('muted'); form.addRow(note)
            fields=dict(tag=variable(spec.get('tag','')),min=number_field(spec.get('min',0)),max=number_field(spec.get('max',100)),
                        x=number_field(spec.get('x',0),-10000,10000,1,' px'),y=number_field(spec.get('y',0),-10000,10000,1,' px'))
            for key,title in [('tag',tr('Variable')),('min',tr('Valor mínimo')),('max',tr('Valor máximo')),('x',tr('Horizontal en el máximo')),('y',tr('Vertical en el máximo'))]:
                form.addRow(title,fields[key])
            self.move=(group,fields); page.addWidget(group)
            spec=d.get('scale',{})
            group=QGroupBox(tr('Escalar según una variable')); group.setCheckable(True); group.setChecked(bool(spec)); form=QFormLayout(group)
            axis=QComboBox()
            for key,title in [('both',tr('Ancho y alto')),('x',tr('Solo el ancho')),('y',tr('Solo el alto'))]: axis.addItem(title,key)
            axis.setCurrentIndex(max(0,axis.findData(spec.get('axis','both'))))
            anchor=QComboBox()
            for key,title in [('center',tr('Centro')),('bottom',tr('Borde inferior')),('top',tr('Borde superior')),('left',tr('Borde izquierdo')),('right',tr('Borde derecho'))]: anchor.addItem(title,key)
            anchor.setCurrentIndex(max(0,anchor.findData(spec.get('anchor','center'))))
            fields=dict(tag=variable(spec.get('tag','')),min=number_field(spec.get('min',0)),max=number_field(spec.get('max',100)),
                        **{'from':number_field(spec.get('from',1),0,20,2,' ×'),'to':number_field(spec.get('to',2),0,20,2,' ×')},axis=axis,anchor=anchor)
            for key,title in [('tag',tr('Variable')),('min',tr('Valor mínimo')),('max',tr('Valor máximo')),('from',tr('Escala en el mínimo')),('to',tr('Escala en el máximo')),('axis',tr('Escalar')),('anchor',tr('Punto fijo'))]:
                form.addRow(title,fields[key])
            self.scale=(group,fields); page.addWidget(group)
        page.addStretch()

    def data(self):
        result={}
        if self.rotation and self.rotation[0].isChecked():
            f=self.rotation[1]; result['rotation']={'tag':f['tag'].currentText(),'min':f['min'].value(),'max':f['max'].value(),'from':f['from'].value(),'to':f['to'].value()}
        if self.spin and self.spin[0].isChecked():
            result['spin']={'when':self.spin[1].data(),'seconds':self.spin[2].value()}
        if self.fill and self.fill[0].isChecked():
            f=self.fill[1]; result['fill']={'tag':f['tag'].currentText(),'min':f['min'].value(),'max':f['max'].value(),'color':f['color'].text(),'direction':f['direction'].currentData()}
        if self.move and self.move[0].isChecked():
            f=self.move[1]; result['move']={'tag':f['tag'].currentText(),'min':f['min'].value(),'max':f['max'].value(),'x':f['x'].value(),'y':f['y'].value()}
        if self.scale and self.scale[0].isChecked():
            f=self.scale[1]; result['scale']={'tag':f['tag'].currentText(),'min':f['min'].value(),'max':f['max'].value(),'from':f['from'].value(),'to':f['to'].value(),
                                               'axis':f['axis'].currentData(),'anchor':f['anchor'].currentData()}
        return result


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
            field=StyleForm(d.get(key),element['kind'],hint=False,host=studio); self.styles[key]=field; box.addWidget(field)
            return group
        page.addWidget(style_group('default','1 · Normal',tr('Apariencia fija en el runtime.')))
        states=QGroupBox(tr('2 · Según el valor de variables')); box=QVBoxLayout(states)
        note=QLabel(tr('Por ejemplo: rojo si Bomba.Fallo es verdadero. Se usa el primer estado que se cumpla.'))
        note.setWordWrap(True); note.setObjectName('muted'); box.addWidget(note)
        self.states=copy.deepcopy(d.get('states',[])); self.table=QTableWidget(0,2); self.table.setHorizontalHeaderLabels([tr('Cuando'),tr('Apariencia')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(110)
        box.addWidget(self.table); row=QHBoxLayout(); box.addLayout(row)
        def refresh():
            self.table.setRowCount(len(self.states))
            for i,state in enumerate(self.states):
                text=describe_condition(state['when'])
                appearance=' · '.join(f'{k}: {v}' for k,v in state['style'].items())+(' · '+tr('parpadea') if state.get('blink') else '')
                self.table.setItem(i,0,QTableWidgetItem(text)); self.table.setItem(i,1,QTableWidgetItem(appearance))
        def edit(new):
            index=-1 if new else self.table.currentRow()
            if not new and index<0: return
            current={} if new else self.states[index]
            dialog=EditorDialog(self); dialog.setWindowTitle(tr('Estado')); content=QVBoxLayout(dialog)
            cond=ConditionList(studio,current.get('when'),False); style=StyleForm(current.get('style'),element['kind'],host=studio)
            blink=QCheckBox(tr('Parpadear (alterna con la apariencia normal)')); blink.setChecked(current.get('blink',False))
            content.addWidget(cond); content.addWidget(style); content.addWidget(blink)
            def state(): return dict(when=cond.data(),style=style.data(),**({'blink':True} if blink.isChecked() else {}))
            def validate():
                candidate=copy.deepcopy(element); candidate['dynamics']={'states':[state()]}
                check(studio,candidate)
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
        self.format={}
        if element['kind'] in dynamics.FORMATTED:
            group=QGroupBox(tr('Unidad y decimales desde variables')); form=QFormLayout(group)
            note=QLabel(tr('Opcional. Si la variable no tiene un valor válido se usan la unidad y los decimales del elemento.'))
            note.setWordWrap(True); note.setObjectName('muted'); form.addRow(note)
            for key,kind,title in [('unit','string',tr('Unidad (variable de texto)')),('decimals','int',tr('Decimales (variable entera)'))]:
                combo=QComboBox(); combo.setEditable(True); combo.addItem('')
                combo.addItems([name for name,tag in available_tags(studio).items() if tag['type']==kind])
                combo.setCurrentText(d.get(key,{}).get('tag','')); self.format[key]=combo; form.addRow(title,combo)
            page.addWidget(group)
        page.addStretch()
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(appearance)
        has_style=bool(dynamics.style_keys(element['kind'])) or element['kind']=='lamp'
        if has_style:
            tabs.addTab(scroll,tr('Apariencia'))
        if self.format and not has_style:
            tabs.addTab(scroll,tr('Apariencia'))
        self.motion=MotionForm(studio,element)
        if element['kind'] in dynamics.ROTATABLE|dynamics.FILLABLE|dynamics.MOVABLE:
            tabs.addTab(self.motion,tr('Movimiento y nivel'))
        self.visible=ConditionList(studio,d.get('visible')); tabs.addTab(self.visible,tr('Visibilidad'))
        enabled=QWidget(); form=QVBoxLayout(enabled); self.enabled=ConditionList(studio,d.get('enabled')); form.addWidget(self.enabled)
        from .project_text_editor import ProjectTextField
        self.reason=ProjectTextField(studio,d.get('disabled_reason','')); self.reason.setPlaceholderText(tr('Motivo de bloqueo (se muestra al pasar el ratón)')); form.addWidget(self.reason); form.addStretch()
        tabs.addTab(enabled,tr('Habilitación'))
        self.validator=self.validate; studio.dialog_buttons(self,layout)

    def data(self):
        d={key:field.data() for key,field in self.styles.items() if field.data()}
        if self.visible.data(): d['visible']=self.visible.data()
        if self.enabled.data(): d['enabled']=self.enabled.data()
        if self.reason.text() or isinstance(self.reason.original, dict): d['disabled_reason']=self.reason.translated_value()
        if self.states:d['states']=copy.deepcopy(self.states)
        d.update(self.motion.data())
        d.update({key:{'tag':combo.currentText().strip()} for key,combo in self.format.items() if combo.currentText().strip()})
        result=copy.deepcopy(self.element); result['dynamics']=d
        if self.lamp:result['lamp_colors']={key:field.text() for key,field in self.lamp.items()}
        return result

    def validate(self):
        check(self.studio,self.data())


def edit_dynamics(studio):
    items=studio.scene.selectedItems()
    if len(items)!=1:return
    source=items[0].element; dialog=DynamicDialog(studio,source)
    if dialog.exec()==EditorDialog.DialogCode.Accepted:
        data=dialog.data(); studio.mutate(lambda:source.update(data))
