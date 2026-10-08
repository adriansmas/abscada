"""Compatible tag selection and common properties without overwriting bindings."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QFormLayout, QDoubleSpinBox, QVBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem, QLabel
from .dialogs import EditorDialog
from .dynamic_editor import available_tags
from .dynamics import compatible,COLOR_KEYS
from .graphic_properties import ColorField
from .i18n import tr




def select_tag(studio):
    items=studio.scene.selectedItems()
    if len(items)!=1:return
    element=items[0].element
    dialog=EditorDialog(studio);dialog.setWindowTitle(tr('Seleccionar variable'));dialog.resize(700,460)
    box=QVBoxLayout(dialog);search=QLineEdit();search.setPlaceholderText(tr('Buscar variable, tipo o conexión'));box.addWidget(search)
    tree=QTreeWidget();tree.setHeaderLabels([tr('Variable'),tr('Tipo'),tr('Acceso'),tr('Conexión / ubicación')]);box.addWidget(tree)
    from .connectors import binding_summary
    def refresh():
        tree.clear();groups={}
        for name,tag in available_tags(studio).items():
            binding=tag.get('binding',{});location=binding_summary(binding,studio.project.connections,tag['type']) if binding else 'Local'
            text=[name,tag['type'],tr('Escribible') if tag.get('writable') else tr('Solo lectura'),binding.get('connection','')+' '+location]
            if search.text().casefold() not in ' '.join(text).casefold():continue
            row=QTreeWidgetItem(text);row.setData(0,Qt.ItemDataRole.UserRole,name)
            if not compatible(element,tag):
                row.setDisabled(True);row.setToolTip(0,tr('Tipo o acceso incompatible con este objeto'))
            root=name.split('.')[0]
            if '.' in name:
                if root not in groups:groups[root]=QTreeWidgetItem([root]);tree.addTopLevelItem(groups[root]);groups[root].setExpanded(True)
                groups[root].addChild(row)
            else:tree.addTopLevelItem(row)
        tree.resizeColumnToContents(0)
    search.textChanged.connect(refresh);refresh()
    def validate():
        item=tree.currentItem()
        if not item or item.isDisabled() or not item.data(0,Qt.ItemDataRole.UserRole):raise ValueError(tr('Selecciona una variable compatible'))
    dialog.validator=validate;studio.dialog_buttons(dialog,box)
    tree.itemDoubleClicked.connect(lambda *_:dialog.accept())
    if dialog.exec()==EditorDialog.DialogCode.Accepted:
        studio.tag_field.setCurrentText(tree.currentItem().data(0,Qt.ItemDataRole.UserRole));studio.apply_fields()


class CommonProperties(QWidget):
    def __init__(self,studio):
        super().__init__();self.studio=studio;self.syncing=False;self.fields={}
        form=QFormLayout(self);form.setContentsMargins(0,0,0,0)
        self.info=QLabel(tr('Valores distintos: campo vacío'));form.addRow(self.info)
        for key,title in [('w',tr('Ancho')),('h',tr('Alto')),('font_size',tr('Tamaño de texto')),('color',tr('Fondo')),('text_color',tr('Color de texto')),('border_color',tr('Borde')),('stroke_color',tr('Trazo'))]:
            if key in COLOR_KEYS:
                field=ColorField(lambda k=key:self.apply(k))
            else:
                field=QDoubleSpinBox();field.setRange(0,10000 if key!='font_size' else 72);field.setSpecialValueText('—');field.setDecimals(0 if key=='font_size' else 1)
                field.editingFinished.connect(lambda k=key:self.apply(k))
            form.addRow(title,field);self.fields[key]=field
        self.form=form

    def refresh(self):
        self.syncing=True;elements=[i.element for i in self.studio.scene.selectedItems()]
        for key,field in self.fields.items():
            valid=key in {'w','h'} or all(key in allowed_style(e) for e in elements)
            self.form.setRowVisible(field,valid)
            values=[e.get(key,15 if key=='font_size' else '' if key in COLOR_KEYS else 0) for e in elements]
            value=values[0] if values and all(v==values[0] for v in values) else '' if key in COLOR_KEYS else 0
            field.setText(value) if key in COLOR_KEYS else field.setValue(value)
        self.syncing=False

    def apply(self,key):
        if self.syncing:return
        field=self.fields[key];value=field.text() if key in COLOR_KEYS else field.value()
        if value in ('',0):return
        if key=='font_size':value=int(value)
        elements=[i.element for i in self.studio.scene.selectedItems()]
        if any(e.get('editor_locked') for e in elements) and key in {'w','h'}:return
        def update():
            for e in elements:e[key]=value
        self.studio.mutate(update)


def allowed_style(e):
    kind=e['kind']
    if kind in {'text','button','input','text_list'}:return {'font_size','bold','text_align','color','text_color','border_color'}
    if kind=='lamp':return {'lamp_colors'}
    if kind in {'rectangle','ellipse'}:return {'stroke_color','stroke_width','stroke_style','color','filled'}
    if kind in {'pipe','line','polyline'}:return {'stroke_color','stroke_width','stroke_style'}
    return set()


def copy_style(studio,colors_only=False):
    items=studio.scene.selectedItems()
    if len(items)==1:
        e=items[0].element;keys=allowed_style(e)
        if colors_only:keys&=COLOR_KEYS|{'lamp_colors'}
        studio.copied_style={key:copy.deepcopy(e[key]) for key in keys if key in e}


def paste_style(studio):
    style=getattr(studio,'copied_style',{})
    def apply():
        for item in studio.scene.selectedItems():
            for key,value in style.items():
                if key in allowed_style(item.element):item.element[key]=copy.deepcopy(value)
    if style:studio.mutate(apply)
