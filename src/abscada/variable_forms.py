"""Variable creation and editing without JSON, including nested structures."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QCheckBox, QLabel, QPushButton
from .dialogs import EditorDialog
from .value_editor import ValueEditor, StructureEditor, FieldError
from .protocol_editor import BindingEditor


class VariableForms:
    def tag_form(self, name):
        tag=self.project.tags()[name]
        dialog=EditorDialog(self); dialog.setWindowTitle('Variable · '+name); dialog.resize(560,330)
        layout=QVBoxLayout(dialog); form=QFormLayout(); layout.addLayout(form)
        initial=ValueEditor(tag['type'],tag['initial']); initial.edit.setObjectName('tagInitial')
        writable=QCheckBox('Permitir escritura'); writable.setChecked(tag.get('writable',False))
        connection=QComboBox(); connection.setObjectName('tagConnection'); connection.addItem('Local','')
        configs={c['id']:c for c in self.project.connections}
        for cid,c in configs.items(): connection.addItem(f"{cid} · {c.get('host','')}",cid)
        binding=tag.get('binding',{})
        connection.setCurrentIndex(max(0,connection.findData(binding.get('connection',''))))
        form.addRow('Valor inicial',initial); form.addRow('Acceso',writable); form.addRow('Conexión',connection)
        endpoint=BindingEditor(connection,configs,tag['type'],binding or None); layout.addWidget(endpoint)
        def apply(project): project.configure_tag(name,initial.value(),writable.isChecked(),endpoint.binding())
        def validate():
            candidate=copy.deepcopy(self.project); apply(candidate); candidate.validate()
        dialog.validator=validate
        from .connection_diagnostics import add_diagnostic
        add_diagnostic(dialog,layout,lambda:(configs.get(connection.currentData()), endpoint.binding(), tag['type'],writable.isChecked()),self,name)
        self.dialog_buttons(dialog,layout)
        if dialog.exec()==EditorDialog.DialogCode.Accepted: self.mutate(lambda:apply(self.project))

    def variable_form(self, index, duplicate=None):
        previous=copy.deepcopy(duplicate if duplicate else self.project.variables[index] if index is not None else
                                dict(name='',type='float',initial=0.,writable=False))
        if duplicate:
            previous['name']=''; previous.pop('binding',None); previous.pop('bindings',None)
        dialog=EditorDialog(self); dialog.setWindowTitle('Duplicar variable' if duplicate else 'Nueva variable' if index is None else 'Editar variable')
        dialog.resize(650,460); layout=QVBoxLayout(dialog); form=QFormLayout(); layout.addLayout(form)
        name=QLineEdit(previous['name']); name.setReadOnly(index is not None); name.setObjectName('variableName')
        kind=QComboBox(); kind.addItems(['bool','int','float','string']+list(self.project.types)); kind.setCurrentText(previous['type'])
        initial=ValueEditor(previous['type'] if previous['type'] not in self.project.types else 'float',
                            previous['initial'] if previous['type'] not in self.project.types else 0.)
        writable=QCheckBox('Permitir escritura'); writable.setChecked(previous.get('writable',False))
        connection=QComboBox(); connection.addItem('Local','')
        configs={c['id']:c for c in self.project.connections}
        for cid in configs: connection.addItem(cid,cid)
        binding=previous.get('binding',{})
        connection.setCurrentIndex(max(0,connection.findData(binding.get('connection',''))))
        for title,field in [('Nombre',name),('Tipo',kind),('Valor inicial',initial),('Acceso',writable),('Conexión',connection)]: form.addRow(title,field)
        structure=StructureEditor(self.project); layout.addWidget(structure)
        endpoint=BindingEditor(connection,configs,kind.currentText(),binding or None); layout.addWidget(endpoint)
        drafts={}; active=None
        def state():
            nonlocal active
            if active:
                try: drafts[active]=structure.values() if active in self.project.types else initial.value()
                except ValueError: pass
            active=kind.currentText(); structured=active in self.project.types
            for field in (initial,writable,connection): form.setRowVisible(field,not structured)
            structure.setVisible(structured)
            if structured:
                value,overrides=drafts.get(active,(previous['initial'],previous.get('overrides',{})) if active==previous['type'] else ({},{}))
                structure.configure(active,value,previous.get('writable',False),overrides)
            else: initial.set_kind(active,drafts.get(active,previous['initial'] if active==previous['type'] else None))
            endpoint.kind=active
            if endpoint.form:
                endpoint.layout.removeWidget(endpoint.form); endpoint.form.deleteLater(); endpoint.form=None
            endpoint.drafts.clear(); endpoint.rebuild()
            if structured: endpoint.hide()
        state(); kind.currentTextChanged.connect(state)
        if duplicate:
            info=QLabel('La copia se crea sin enlaces PLC. Revisa y asigna las direcciones de sus campos.'); info.setWordWrap(True); layout.addWidget(info)
            original=duplicate.get('bindings',{}) or ({duplicate['name']:duplicate['binding']} if duplicate.get('binding') else {})
            from .connectors import binding_summary
            details=QLabel('\n'.join(f'{key}: {value["connection"]} · {binding_summary(value,self.project.connections,self.project.tags()[key]["type"])}' for key,value in original.items()))
            details.setWordWrap(True); layout.addWidget(details)
        def data():
            value=copy.deepcopy(previous); value.update(name=name.text().strip(),type=kind.currentText())
            if kind.currentText() in self.project.types:
                value['initial'],value['overrides']=structure.values(); value.pop('binding',None)
            else:
                value.update(initial=initial.value(),writable=writable.isChecked()); value.pop('bindings',None); value.pop('overrides',None)
                endpoint_value=endpoint.binding()
                if endpoint_value: value['binding']=endpoint_value
                else: value.pop('binding',None)
            return value
        def apply(project):
            value=data()
            if index is None: project.variables.append(value)
            else: project.variables[index]=value
        def validate():
            if not name.text().strip() or '.' in name.text() or (index is None and any(v['name']==name.text().strip() for v in self.project.variables)):
                raise FieldError('Nombre vacío, duplicado o con puntos',name)
            candidate=copy.deepcopy(self.project); apply(candidate); candidate.validate()
        dialog.validator=validate; self.dialog_buttons(dialog,layout)
        if dialog.exec()==EditorDialog.DialogCode.Accepted: self.mutate(lambda:apply(self.project))

    def duplicate_variable(self):
        item=self.table.currentItem()
        if item:
            root=item.data(0,Qt.ItemDataRole.UserRole).split('.')[0]
            self.variable_form(None,duplicate=next(v for v in self.project.variables if v['name']==root))
