"""Typed engineering values, with unambiguous decimal-comma input."""
import re
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QComboBox, QTreeWidget, QTreeWidgetItem, QCheckBox,QHeaderView
from .project import coerce, PRIMITIVES
from .i18n import tr


class FieldError(ValueError):
    def __init__(self, message, field):
        super().__init__(message)
        self.field = field


def engineering_value(text, kind):
    if kind in {'int', 'float'} and isinstance(text, str):
        text = text.strip()
        if not re.fullmatch(r'[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?', text):
            raise ValueError(tr('Introduce un número sin separadores de miles; usa coma o punto decimal'))
        text = text.replace(',', '.')
    try:
        return coerce(text, kind)
    except (ValueError, TypeError, OverflowError):
        raise ValueError({'bool':tr('Elige Verdadero o Falso'), 'int':tr('Introduce un número entero'),
                          'float':tr('Introduce un número real finito'), 'string':tr('Introduce un texto')}[kind]) from None


class ValueEditor(QWidget):
    def __init__(self, kind='float', value=0.0, parent=None):
        super().__init__(parent)
        layout=QHBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.edit=QLineEdit(); self.boolean=QComboBox()
        self.boolean.addItem(tr('Falso'),False); self.boolean.addItem(tr('Verdadero'),True)
        layout.addWidget(self.edit); layout.addWidget(self.boolean)
        self.set_kind(kind,value)

    def set_kind(self, kind, value=None):
        self.kind=kind
        if value is None:
            try: value=engineering_value(self.edit.text(),kind)
            except ValueError: value={'bool':False,'int':0,'float':0.0,'string':''}[kind]
        self.boolean.setVisible(kind=='bool'); self.edit.setVisible(kind!='bool')
        self.boolean.setCurrentIndex(1 if value is True else 0)
        self.edit.setText(str(value))
        self.edit.setToolTip(tr('Sin separadores de miles. Decimal con coma o punto.') if kind in {'int','float'} else '')

    def value(self):
        if self.kind=='bool': return self.boolean.currentData()
        try: return engineering_value(self.edit.text(),self.kind)
        except ValueError as exc: raise FieldError(str(exc),self.edit) from exc


class StructureEditor(QTreeWidget):
    def __init__(self, project):
        super().__init__()
        self.project=project; self.fields={}
        self.setHeaderLabels([tr('Campo'),tr('Tipo'),tr('Valor inicial'),tr('Escribible')])
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        self.setMinimumHeight(210)

    def configure(self, kind, initial=None, writable=False, overrides=None):
        self.clear(); self.fields={}; overrides=overrides or {}
        def add(parent, typename, data, prefix=''):
            for name, childkind in self.project.types[typename].items():
                path=prefix+name; row=QTreeWidgetItem([name,childkind])
                row.setSizeHint(0,QSize(0,38))
                row.setToolTip(0,path)
                (parent.addChild if parent else self.addTopLevelItem)(row)
                if childkind in PRIMITIVES:
                    field=ValueEditor(childkind, data.get(name,{'bool':False,'int':0,'float':0.,'string':''}[childkind]))
                    access=QCheckBox(); access.setChecked(overrides.get(path,{}).get('writable',writable))
                    self.setItemWidget(row,2,field); self.setItemWidget(row,3,access)
                    self.fields[path]=(field,access)
                else: add(row,childkind,data.get(name,{}),path+'.')
        add(None,kind,initial or {}); self.expandAll()
        self.resizeColumnToContents(0); self.resizeColumnToContents(1)
        self.setColumnWidth(0,max(140,self.columnWidth(0)));self.setColumnWidth(1,max(70,self.columnWidth(1)))

    def values(self):
        initial={}; overrides={}
        for path,(field,access) in self.fields.items():
            parts=path.split('.'); target=initial
            for part in parts[:-1]: target=target.setdefault(part,{})
            target[parts[-1]]=field.value(); overrides[path]={'writable':access.isChecked()}
        return initial,overrides
