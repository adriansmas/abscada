"""Variable creation and editing without JSON, including nested structures."""
import copy
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QCheckBox, QLabel, QPushButton,
                               QMenu, QMessageBox, QTreeWidgetItem)
from .dialogs import EditorDialog
from .value_editor import ValueEditor, StructureEditor, FieldError
from .protocol_editor import BindingEditor
from .i18n import tr


NEW_ROW = "\0new-variable"   # role value of the row where the next variable is typed
DEFAULTS = {"bool": False, "int": 0, "float": 0.0, "string": ""}


class VariableForms:
    # --- inline creation: the last row of the list is where a new variable is typed ---------------

    def add_variable_row(self):
        """The editing row: type a name and press Enter. Called at the end of every refresh."""
        index = self.pending_variable_index
        if index is not None and index >= len(self.project.variables):
            index = self.pending_variable_index = None
        row = QTreeWidgetItem([""])
        row.setData(0, Qt.ItemDataRole.UserRole, NEW_ROW)
        row.setSizeHint(0, QSize(0, 38))
        before = []
        if index is not None:
            name = self.project.variables[index]["name"]
            before = [self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())
                      if self.table.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == name]
        if before:
            self.table.insertTopLevelItem(self.table.indexOfTopLevelItem(before[0]), row)
        else:
            self.table.addTopLevelItem(row)
        field = QLineEdit()
        field.setObjectName("newVariableName")
        field.setFrame(False)
        field.setPlaceholderText(tr("+ Nueva variable: escribe el nombre y pulsa Intro"))
        field.editingFinished.connect(lambda: self.commit_variable_row(field))
        self.table.setItemWidget(row, 0, field)
        self.new_variable_field = field
        self._committing_variable = False
        if self.focus_new_variable:
            self.focus_new_variable = False
            QTimer.singleShot(0, lambda: field.setFocus() if self.new_variable_field is field else None)

    def add_variable(self):
        """«+ Nueva variable»: put the cursor in the last row."""
        self.pending_variable_index = None
        if self.filter.text():
            self.filter.clear()
        self.focus_new_variable = True
        self.refresh_variables()
        self.table.scrollToBottom()

    def insert_variable_at(self, index):
        self.pending_variable_index = index
        if self.filter.text():
            self.filter.clear()
        self.focus_new_variable = True
        self.refresh_variables()

    def commit_variable_row(self, field):
        if getattr(self, "_committing_variable", False) or field is not getattr(self, "new_variable_field", None):
            return
        name = field.text().strip()
        index = self.pending_variable_index
        if not name:
            if index is not None:   # a row opened in the middle and left empty goes away
                self.pending_variable_index = None
                QTimer.singleShot(0, self.refresh_variables)
            return
        self._committing_variable = True

        def create():
            if "." in name or any(v["name"] == name for v in self.project.variables):
                self._committing_variable = False
                self.error(tr("Nombre vacío, duplicado o con puntos"))
                field.setFocus()
                return
            self.pending_variable_index = None
            self.focus_new_variable = index is None   # keep typing: the next variable goes right below
            position = len(self.project.variables) if index is None else index
            if not self.mutate(lambda: self.project.variables.insert(position, dict(name=name, type="float", initial=0.0, writable=False))):
                self.focus_new_variable = False
        QTimer.singleShot(0, create)

    def variable_type_combo(self, name, current):
        combo = QComboBox()
        combo.setObjectName("variableType")
        combo.addItems(["bool", "int", "float", "string"] + list(self.project.types))
        combo.setCurrentText(current)
        combo.setToolTip(tr("Tipo de la variable"))
        combo.activated.connect(lambda _i, n=name, c=combo: self.change_variable_type(n, c.currentText()))
        return combo

    def change_variable_type(self, name, kind):
        index = next((i for i, v in enumerate(self.project.variables) if v["name"] == name), None)
        if index is None or self.project.variables[index]["type"] == kind:
            return

        def apply():
            variable = self.project.variables[index]
            variable["type"] = kind
            # The old value and the PLC address belong to the old type.
            variable.pop("binding", None); variable.pop("bindings", None); variable.pop("overrides", None)
            variable["initial"] = {} if kind in self.project.types else DEFAULTS[kind]
            if kind in self.project.types:
                variable["overrides"] = {}
        self.mutate(apply)

    def variable_menu(self, item, position):
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = QMenu(self)
        names = [v["name"] for v in self.project.variables]
        if value in (None, NEW_ROW):
            menu.addAction(tr("Nueva variable"), self.add_variable)
        else:
            root = value.split(".")[0]
            index = names.index(root) if root in names else None
            if value in self.project.tags():
                menu.addAction(tr("Enlace y valor…"), lambda: self.tag_form(value))
            if index is not None:
                menu.addAction(tr("Editar variable…"), lambda: self.variable_form(index))
                menu.addAction(tr("Duplicar…"), lambda: self.variable_form(None, duplicate=self.project.variables[index]))
                menu.addSeparator()
                menu.addAction(tr("Insertar variable encima"), lambda: self.insert_variable_at(index))
                menu.addAction(tr("Insertar variable debajo"),
                               lambda: self.insert_variable_at(index + 1) if index + 1 < len(names) else self.add_variable())
                up = menu.addAction(tr("Subir"), lambda: self.move_variable(index, -1)); up.setEnabled(index > 0)
                down = menu.addAction(tr("Bajar"), lambda: self.move_variable(index, 1)); down.setEnabled(index + 1 < len(names))
                menu.addSeparator()
                menu.addAction(tr("Eliminar"), lambda: self.delete_variable(root))
        menu.exec(position)

    def move_variable(self, index, step):
        def apply():
            variables = self.project.variables
            variables[index], variables[index + step] = variables[index + step], variables[index]
        self.mutate(apply)

    def delete_variable(self, name):
        if QMessageBox.question(self, tr("Eliminar variable"), tr("¿Eliminar la variable «{name}»? Se puede deshacer con Ctrl+Z.", name=name)) \
                != QMessageBox.StandardButton.Yes:
            return
        self.mutate(lambda: self.project.variables.__setitem__(slice(None), [v for v in self.project.variables if v["name"] != name]))


    def tag_form(self, name):
        tag=self.project.tags()[name]
        dialog=EditorDialog(self); dialog.setWindowTitle('Variable · '+name); dialog.resize(560,330)
        layout=QVBoxLayout(dialog); form=QFormLayout(); layout.addLayout(form)
        initial=ValueEditor(tag['type'],tag['initial']); initial.edit.setObjectName('tagInitial')
        writable=QCheckBox(tr('Permitir escritura')); writable.setChecked(tag.get('writable',False))
        connection=QComboBox(); connection.setObjectName('tagConnection'); connection.addItem(tr('Local'),'')
        configs={c['id']:c for c in self.project.connections}
        for cid,c in configs.items(): connection.addItem(f"{cid} · {c.get('host','')}",cid)
        binding=tag.get('binding',{})
        connection.setCurrentIndex(max(0,connection.findData(binding.get('connection',''))))
        form.addRow(tr('Valor inicial'),initial); form.addRow(tr('Acceso'),writable); form.addRow(tr('Conexión'),connection)
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
        dialog=EditorDialog(self); dialog.setWindowTitle(tr('Duplicar variable') if duplicate else tr('Nueva variable') if index is None else tr('Editar variable'))
        dialog.resize(650,460); layout=QVBoxLayout(dialog); form=QFormLayout(); layout.addLayout(form)
        name=QLineEdit(previous['name']); name.setReadOnly(index is not None); name.setObjectName('variableName')
        kind=QComboBox(); kind.addItems(['bool','int','float','string']+list(self.project.types)); kind.setCurrentText(previous['type'])
        initial=ValueEditor(previous['type'] if previous['type'] not in self.project.types else 'float',
                            previous['initial'] if previous['type'] not in self.project.types else 0.)
        writable=QCheckBox(tr('Permitir escritura')); writable.setChecked(previous.get('writable',False))
        connection=QComboBox(); connection.addItem(tr('Local'),'')
        configs={c['id']:c for c in self.project.connections}
        for cid in configs: connection.addItem(cid,cid)
        binding=previous.get('binding',{})
        connection.setCurrentIndex(max(0,connection.findData(binding.get('connection',''))))
        for title,field in [(tr('Nombre'),name),(tr('Tipo'),kind),(tr('Valor inicial'),initial),(tr('Acceso'),writable),(tr('Conexión'),connection)]: form.addRow(title,field)
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
            info=QLabel(tr('La copia se crea sin enlaces PLC. Revisa y asigna las direcciones de sus campos.')); info.setWordWrap(True); layout.addWidget(info)
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
                raise FieldError(tr('Nombre vacío, duplicado o con puntos'),name)
            candidate=copy.deepcopy(self.project); apply(candidate); candidate.validate()
        dialog.validator=validate; self.dialog_buttons(dialog,layout)
        if dialog.exec()==EditorDialog.DialogCode.Accepted: self.mutate(lambda:apply(self.project))

    def duplicate_variable(self):
        item=self.table.currentItem()
        if item:
            root=item.data(0,Qt.ItemDataRole.UserRole).split('.')[0]
            self.variable_form(None,duplicate=next(v for v in self.project.variables if v['name']==root))
