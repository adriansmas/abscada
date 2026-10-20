"""Variable creation and editing without JSON, including nested structures."""
import copy
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QCheckBox, QLabel, QMenu,
                               QMessageBox, QTreeWidgetItem)
from .dialogs import EditorDialog
from .value_editor import ValueEditor, StructureEditor, FieldError
from .protocol_editor import BindingEditor
from .i18n import tr
from .structures import PRIMITIVES, known, default_value, root as root_of, valid_name, steps as steps_of


NEW_ROW = "\0new-variable"   # role value of the row where the next variable is typed
FOLDER_ROW = "\0folder:"     # role value of a folder row: the prefix and the folder path
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
        # The row goes before the variable it is inserted above, or at the end of its folder.
        target = self.project.variables[index]["name"] if index is not None else FOLDER_ROW + self.pending_variable_folder
        found = self.variable_item(target) if index is not None or self.pending_variable_folder else None
        if found is not None and index is not None:
            parent = found.parent()
            if parent is not None:
                parent.insertChild(parent.indexOfChild(found), row)
            else:
                self.table.insertTopLevelItem(self.table.indexOfTopLevelItem(found), row)
        elif found is not None:
            found.addChild(row); found.setExpanded(True)
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

    def variable_item(self, value):
        """The row of a variable (by name) or a folder (FOLDER_ROW + path); None if not shown."""
        # A plain walk: wrappers from QTreeWidgetItemIterator crash PySide when the tree is cleared.
        def search(item):
            if item.data(0, Qt.ItemDataRole.UserRole) == value:
                return item
            return next((found for i in range(item.childCount()) if (found := search(item.child(i))) is not None), None)
        return next((found for i in range(self.table.topLevelItemCount())
                     if (found := search(self.table.topLevelItem(i))) is not None), None)

    def add_variable(self, folder=""):
        """«+ Nueva variable»: put the cursor in the last row (of ``folder``)."""
        self.pending_variable_index = None
        self.pending_variable_folder = folder if isinstance(folder, str) else ""
        if self.filter.text():
            self.filter.clear()
        self.focus_new_variable = True
        self.refresh_variables()
        self.table.scrollToBottom()

    def insert_variable_at(self, index):
        self.pending_variable_index = index
        self.pending_variable_folder = self.project.variables[index].get("folder", "") if index < len(self.project.variables) else ""
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

        folder = self.pending_variable_folder

        def create():
            if not valid_name(name) or any(v["name"] == name for v in self.project.variables):
                self._committing_variable = False
                self.error(tr("Nombre vacío, duplicado, con puntos o con corchetes"))
                field.setFocus()
                return
            self.pending_variable_index = None
            self.focus_new_variable = index is None   # keep typing: the next variable goes right below
            position = len(self.project.variables) if index is None else index
            variable = dict(name=name, type="float", initial=0.0, writable=False)
            if folder:
                variable["folder"] = folder
            if not self.mutate(lambda: self.project.variables.insert(position, variable)):
                self.focus_new_variable = False
        QTimer.singleShot(0, create)

    def variable_type_combo(self, name, current):
        combo = QComboBox()
        combo.setObjectName("variableType")
        combo.setEditable(True)
        combo.addItems(["bool", "int", "float", "string"] + list(self.project.types))
        combo.setCurrentText(current)
        combo.setToolTip(tr("Tipo de la variable; un array se escribe como float[8] o Motor[4]"))
        combo.activated.connect(lambda _i, n=name, c=combo: self.change_variable_type(n, c.currentText()))
        return combo

    def change_variable_type(self, name, kind):
        index = next((i for i, v in enumerate(self.project.variables) if v["name"] == name), None)
        kind = kind.strip()
        if index is None or self.project.variables[index]["type"] == kind:
            return
        if not known(kind, self.project.types):
            self.error(tr("Tipo desconocido: {kind}", kind=kind))
            self.refresh_variables()
            return

        def apply():
            variable = self.project.variables[index]
            variable["type"] = kind
            # The old value and the PLC address belong to the old type.
            variable.pop("binding", None); variable.pop("bindings", None); variable.pop("overrides", None)
            variable["initial"] = default_value(self.project.types, kind)
            if kind not in PRIMITIVES:
                variable["overrides"] = {}
        self.mutate(apply)

    def variable_menu(self, item, position):
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = QMenu(self)
        names = [v["name"] for v in self.project.variables]
        if value in (None, NEW_ROW):
            menu.addAction(tr("Nueva variable"), self.add_variable)
            menu.addAction(tr("Nueva carpeta…"), lambda: self.new_variable_folder(""))
            menu.addAction(tr("Importar DB de TIA Portal…"), self.import_tia_db)
        elif value.startswith(FOLDER_ROW):
            folder = value[len(FOLDER_ROW):]
            menu.addAction(tr("Nueva variable aquí"), lambda: self.add_variable(folder))
            menu.addAction(tr("Importar DB de TIA Portal aquí…"), lambda: self.import_tia_db(folder))
            menu.addAction(tr("Nueva subcarpeta…"), lambda: self.new_variable_folder(folder))
            menu.addSeparator()
            menu.addAction(tr("Renombrar carpeta…"), lambda: self.rename_variable_folder(folder))
            menu.addAction(tr("Mover carpeta a…"), lambda: self.move_variable_folder(folder))
            menu.addAction(tr("Eliminar carpeta"), lambda: self.delete_variable_folder(folder))
        else:
            root = root_of(value)
            index = names.index(root) if root in names else None
            if value in self.project.tags():
                menu.addAction(tr("Enlace y valor…"), lambda: self.tag_form(value))
            if value == root and index is not None:
                menu.addAction(tr("Renombrar…"), lambda: self.rename_variable_dialog(root))
            elif index is not None and isinstance((steps_of(value) or [None])[-1], str):
                field = steps_of(value)[-1]
                menu.addAction(tr("Renombrar campo «{field}»…", field=field), lambda: self.rename_field_dialog(value))
            menu.addAction(tr("¿Dónde se usa?"), lambda: self.show_usages(value))
            if index is not None:
                menu.addAction(tr("Editar variable…"), lambda: self.variable_form(index))
                menu.addAction(tr("Duplicar…"), lambda: self.variable_form(None, duplicate=self.project.variables[index]))
                menu.addSeparator()
                menu.addAction(tr("Insertar variable encima"), lambda: self.insert_variable_at(index))
                menu.addAction(tr("Insertar variable debajo"),
                               lambda: self.insert_variable_at(index + 1) if index + 1 < len(names) else self.add_variable())
                up = menu.addAction(tr("Subir"), lambda: self.move_variable(index, -1)); up.setEnabled(index > 0)
                down = menu.addAction(tr("Bajar"), lambda: self.move_variable(index, 1)); down.setEnabled(index + 1 < len(names))
                menu.addAction(tr("Mover a carpeta…"), lambda: self.move_variable_to_folder(root))
                menu.addSeparator()
                menu.addAction(tr("Eliminar"), lambda: self.delete_variable(root))
        menu.exec(position)

    # --- folders: an editing aid; names stay global and nothing else changes ---------------------

    def choose_variable_folder(self, title, exclude=None):
        """A folder picked from a list ("" = root); None if cancelled."""
        from PySide6.QtWidgets import QInputDialog
        from .screen_tree import folders
        root_label = tr("(raíz)")
        options = [root_label] + [f for f in folders(self.project, "variables")
                                  if exclude is None or (f != exclude and not f.startswith(exclude + "/"))]
        choice, ok = QInputDialog.getItem(self, title, tr("Carpeta de destino"), options, 0, False)
        if not ok:
            return None
        return "" if choice == root_label else choice

    def new_variable_folder(self, parent):
        from .screen_tree import add_folder
        name = self.ask_text(tr("Nueva carpeta"), tr("Nombre de la carpeta"))
        if name:
            self.mutate(lambda: add_folder(self.project, parent, name, "variables"))

    def rename_variable_folder(self, path):
        from .screen_tree import rename_folder
        name = self.ask_text(tr("Renombrar carpeta"), tr("Nuevo nombre"), path.rpartition("/")[2])
        if name:
            self.mutate(lambda: rename_folder(self.project, path, name, "variables"))

    def move_variable_folder(self, path):
        from .screen_tree import move_folder
        target = self.choose_variable_folder(tr("Mover carpeta"), exclude=path)
        if target is not None:
            self.mutate(lambda: move_folder(self.project, path, target, "variables"))

    def delete_variable_folder(self, path):
        from .screen_tree import delete_folder
        if QMessageBox.question(self, tr("Eliminar carpeta"), tr("¿Eliminar la carpeta «{path}»? Sus variables y subcarpetas pasan a la carpeta superior; "
                                "no se elimina ninguna variable.", path=path)) == QMessageBox.StandardButton.Yes:
            self.mutate(lambda: delete_folder(self.project, path, "variables"))

    def move_variable_to_folder(self, name):
        from .screen_tree import move_variable
        target = self.choose_variable_folder(tr("Mover «{name}»", name=name))
        if target is not None:
            self.mutate(lambda: move_variable(self.project, name, target))

    def import_tia_db(self, folder=""):
        from .tia_import_dialog import TiaImportDialog
        dialog = TiaImportDialog(self, folder if isinstance(folder, str) else "")
        if dialog.exec() == EditorDialog.DialogCode.Accepted:
            from . import tia_import
            result, target = dialog.result_plan, dialog.folder()
            if self.mutate(lambda: tia_import.apply(self.project, result, target)) and result.variable:
                self.statusBar().showMessage(tr("{name} importado: {count} variables", name=result.variable["name"], count=len(result.rows)), 5000)

    def move_variable(self, index, step):
        def apply():
            variables = self.project.variables
            variables[index], variables[index + step] = variables[index + step], variables[index]
        self.mutate(apply)

    # --- renaming: every reference changes with the variable ------------------------------------

    def show_usages(self, path):
        from .variable_references import usages, scripts_mentioning
        found = usages(self.project, path)
        lines = [f"· {where}: {used}" for where, used in found[:40]]
        if len(found) > 40:
            lines.append(tr("… y {count} más", count=len(found) - 40))
        scripts = scripts_mentioning(self.project, path)
        if scripts:
            lines.append(tr("Scripts que la mencionan: {names}", names=", ".join(scripts)))
        QMessageBox.information(self, tr("¿Dónde se usa {path}?", path=path),
                                "\n".join(lines) if lines else tr("No se usa en pantallas, objetos, alarmas, registros, tendencias ni scripts."))

    def rename_variable_dialog(self, name):
        from .variable_references import rename_variable, check_name
        new = self.ask_text(tr("Renombrar variable"), tr("Nuevo nombre de «{name}»", name=name), name)
        if not new or new == name:
            return
        try:
            check_name(self.project, new, name)
        except ValueError as exc:
            self.error(exc); return
        self.confirm_rename([(name, new)], lambda: rename_variable(self.project, name, new), tr("Renombrar «{old}» a «{new}»", old=name, new=new))

    def rename_field_dialog(self, path):
        from .structures import steps as steps_of, path_kind, join
        from .variable_references import rename_field, field_renames
        parts = steps_of(path)
        field = parts[-1]
        parent = path[:len(path) - len(field)].removesuffix(".")
        type_name = path_kind(self.project.types, {v["name"]: v["type"] for v in self.project.variables}, parent)
        new = self.ask_text(tr("Renombrar campo"), tr("Nuevo nombre del campo «{field}» del tipo {kind}. Cambia en todas sus variables.",
                                                      field=field, kind=type_name), field)
        if not new or new == field:
            return
        renames = field_renames(self.project, type_name, field, new)
        self.confirm_rename(renames, lambda: rename_field(self.project, type_name, field, new),
                            tr("Renombrar el campo «{old}» de {kind} a «{new}»", old=field, kind=type_name, new=new))

    def confirm_rename(self, renames, operation, title):
        """Show what changes, offer to update the scripts that quote the old name, then rename."""
        from .variable_references import usages, scripts_mentioning, replace_in_scripts
        found = [entry for old, _ in renames for entry in usages(self.project, old)]
        scripts = sorted({name for old, _ in renames for name in scripts_mentioning(self.project, old)})
        dialog = EditorDialog(self); dialog.setWindowTitle(title); dialog.resize(560, 360)
        layout = QVBoxLayout(dialog)
        places = sorted({where for where, _ in found})
        text = tr("Se actualizarán {count} usos en: {places}.", count=len(found), places=", ".join(places[:12]) + (" …" if len(places) > 12 else "")) \
            if found else tr("No se usa en pantallas, objetos, alarmas, registros ni tendencias.")
        text += "\n\n" + tr("Los enlaces PLC de sus campos se conservan. El historial ya grabado se seguirá mostrando con el nombre nuevo.")
        if self.project.opcua_server.get("enabled"):
            text += "\n\n" + tr("El servidor OPC UA publicará la variable con el nombre nuevo: los clientes que lean el nombre antiguo dejarán de encontrarla.")
        label = QLabel(text); label.setWordWrap(True); layout.addWidget(label)
        replace = QCheckBox(tr("Sustituir también el nombre entre comillas en los scripts: {names}", names=", ".join(scripts)))
        if scripts:
            replace.setChecked(True); layout.addWidget(replace)
            note = QLabel(tr("Revisa después esos scripts: un nombre construido por partes en el código no se puede detectar."))
            note.setWordWrap(True); note.setObjectName("muted"); layout.addWidget(note)
        layout.addStretch()
        self.dialog_buttons(dialog, layout)
        if dialog.exec() != EditorDialog.DialogCode.Accepted:
            return False
        update = scripts and replace.isChecked()
        def apply():
            operation()
            if update:
                for old, new in renames:
                    replace_in_scripts(self.project, old, new)
        return self.mutate(apply)

    def delete_variable(self, name):
        from .variable_references import usages
        found = usages(self.project, name)
        if found:
            self.error(tr("No se puede eliminar «{name}» porque se usa en:\n· ", name=name)
                       + "\n· ".join(sorted({where for where, _ in found})[:20]))
            return
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
        kind=QComboBox(); kind.setEditable(True); kind.addItems(['bool','int','float','string']+list(self.project.types)); kind.setCurrentText(previous['type'])
        kind.setToolTip(tr('Un tipo básico, un tipo de datos o un array: float[8], Motor[4]'))
        initial=ValueEditor(previous['type'] if previous['type'] in PRIMITIVES else 'float',
                            previous['initial'] if previous['type'] in PRIMITIVES else 0.)
        initial.edit.setObjectName('variableInitial')
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
            # While a type is being typed (Motor[ …) the form keeps the last valid one.
            if not known(kind.currentText().strip(), self.project.types): return
            if active:
                try: drafts[active]=structure.values() if active not in PRIMITIVES else initial.value()
                except ValueError: pass
            active=kind.currentText().strip(); structured=active not in PRIMITIVES
            for field in (initial,writable,connection): form.setRowVisible(field,not structured)
            structure.setVisible(structured)
            if structured:
                value,overrides=drafts.get(active,(previous['initial'],previous.get('overrides',{})) if active==previous['type'] else ({},{}))
                structure.configure(active,value,previous.get('writable',False),overrides)
            else: initial.set_kind(active,drafts.get(active,previous['initial'] if active==previous['type'] else None))
            endpoint.kind=active
            endpoint.clear_form(); endpoint.drafts.clear(); endpoint.rebuild()
            if structured: endpoint.hide()
        state(); kind.currentTextChanged.connect(state)
        if duplicate:
            info=QLabel(tr('La copia se crea sin enlaces PLC. Revisa y asigna las direcciones de sus campos.')); info.setWordWrap(True); layout.addWidget(info)
            original=duplicate.get('bindings',{}) or ({duplicate['name']:duplicate['binding']} if duplicate.get('binding') else {})
            from .connectors import binding_summary
            details=QLabel('\n'.join(f'{key}: {value["connection"]} · {binding_summary(value,self.project.connections,self.project.tags()[key]["type"])}' for key,value in original.items()))
            details.setWordWrap(True); layout.addWidget(details)
        def data():
            value=copy.deepcopy(previous); value.update(name=name.text().strip(),type=kind.currentText().strip())
            if not known(value['type'], self.project.types): raise FieldError(tr('Tipo desconocido: {kind}', kind=value['type']),kind)
            if value['type'] not in PRIMITIVES:
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
            if not name.text().strip() or not valid_name(name.text()) or (index is None and any(v['name']==name.text().strip() for v in self.project.variables)):
                raise FieldError(tr('Nombre vacío, duplicado, con puntos o con corchetes'),name)
            candidate=copy.deepcopy(self.project); apply(candidate); candidate.validate()
        dialog.validator=validate; self.dialog_buttons(dialog,layout)
        if dialog.exec()==EditorDialog.DialogCode.Accepted: self.mutate(lambda:apply(self.project))

    def duplicate_variable(self):
        item=self.table.currentItem()
        if item and not item.data(0,Qt.ItemDataRole.UserRole).startswith((NEW_ROW, FOLDER_ROW)):
            root=root_of(item.data(0,Qt.ItemDataRole.UserRole))
            self.variable_form(None,duplicate=next(v for v in self.project.variables if v['name']==root))
