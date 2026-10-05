"""Project-wide named colors, usage review and reversible updates."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QLabel
from .dialogs import EditorDialog
from .graphic_properties import ColorField


def uses(project,name):
    found=[]
    def walk(value,path):
        if isinstance(value,dict):
            for key,item in value.items():walk(item,path+'/'+key)
        elif isinstance(value,list):
            for i,item in enumerate(value):walk(item,path+'/'+str(i))
        elif value=='@'+name:found.append(path)
    for folder in ('screens','faceplates'):walk(getattr(project,folder),folder)
    return found


def edit_palette(studio):
    dialog=EditorDialog(studio); dialog.setWindowTitle('Paleta del proyecto');dialog.resize(780,480)
    layout=QVBoxLayout(dialog);table=QTableWidget(0,3);table.setHorizontalHeaderLabels(['Nombre','Color exacto','Referencias afectadas'])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(table)
    def add(name='',value='#147d75'):
        i=table.rowCount();table.insertRow(i);table.setItem(i,0,QTableWidgetItem(name))
        field=ColorField(lambda:None);field.setText(value);table.setCellWidget(i,1,field)
        references=uses(studio.project,name);item=QTableWidgetItem('\n'.join(references) or 'Sin referencias'); item.setToolTip('\n'.join(references));item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable);table.setItem(i,2,item)
    for name,value in studio.project.manifest.get('palette',{}).items():add(name,value)
    row=QHBoxLayout();layout.addLayout(row)
    for title,callback in [('Añadir color',lambda:add()),('Eliminar',lambda:table.removeRow(table.currentRow()))]:
        b=QPushButton(title);b.clicked.connect(callback);row.addWidget(b)
    def data():
        values=[(table.item(i,0).text().strip(),table.cellWidget(i,1).text()) for i in range(table.rowCount())]
        if len(dict(values))!=len(values):raise ValueError('Nombres de color duplicados')
        return dict(values)
    def validate():
        candidate=copy.deepcopy(studio.project);candidate.manifest['palette']=data();candidate.validate()
    dialog.validator=validate;studio.dialog_buttons(dialog,layout)
    if dialog.exec()==EditorDialog.DialogCode.Accepted:studio.mutate(lambda:studio.project.manifest.__setitem__('palette',data()))
