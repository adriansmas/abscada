"""Studio dialog that edits the action list of a button (``"action": "sequence"``)."""
import copy
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget)
from .button_actions import STEP_ACTIONS, label
from .dialogs import EditorDialog
from .i18n import tr
from .structures import PRIMITIVES
from .project_text_editor import ProjectTextField

TITLES = {"set": tr("Escribir valor"), "toggle": tr("Alternar marcha / paro"), "script": tr("Ejecutar script"),
          "set_language": tr("Cambiar idioma"), "screen": tr("Abrir pantalla"), "popup": tr("Abrir emergente"),
          "faceplate_popup": tr("Abrir objeto de librería emergente"), "close_popup": tr("Cerrar emergente")}


def seed(element):
    """First step when a single-action button becomes a list: its current action, if a step can do it."""
    action = element.get("action", "toggle")
    if action not in STEP_ACTIONS:
        return []
    step = {key: copy.deepcopy(value) for key, value in element.items()
            if key in {"tag", "value", "script", "language", "screen", "target_container",
                       "modal", "window", "template", "bindings", "title"}}
    return [dict(action=action, **step)]


class ButtonActionsDialog(EditorDialog):
    def __init__(self, studio, element):
        super().__init__(studio)
        self.studio, self.element = studio, element
        self.steps = copy.deepcopy(element.get("actions", []))
        self.current = -1
        self._loading = False
        self.setWindowTitle(tr("Acciones del botón {id}", id=element["id"]))
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        body = QHBoxLayout(); layout.addLayout(body)

        left = QVBoxLayout(); body.addLayout(left, 1)
        self.list = QListWidget(); left.addWidget(self.list)
        self.list.currentRowChanged.connect(self.select)
        buttons = QHBoxLayout(); left.addLayout(buttons)
        for title, callback in ((tr("Añadir"), self.add), (tr("Eliminar"), self.remove),
                                (tr("Subir"), lambda: self.move(-1)), (tr("Bajar"), lambda: self.move(1))):
            button = QPushButton(title); button.clicked.connect(callback); buttons.addWidget(button)

        self.form_group = QGroupBox(tr("Acción")); body.addWidget(self.form_group, 1)
        form = self.form = QFormLayout(self.form_group)
        self.type_field = QComboBox()
        for action in STEP_ACTIONS:
            self.type_field.addItem(TITLES[action], action)
        self.type_field.activated.connect(self.change_type)
        form.addRow(tr("Tipo"), self.type_field)
        self.tag_field = QComboBox(); self.tag_field.setEditable(True)
        self.tag_field.activated.connect(self.changed)
        self.tag_field.lineEdit().editingFinished.connect(self.changed)
        form.addRow(tr("Variable"), self.tag_field)
        self.value_field = QLineEdit(); self.value_field.editingFinished.connect(self.changed)
        form.addRow(tr("Valor"), self.value_field)
        self.script_field = QComboBox(); self.script_field.activated.connect(self.changed)
        form.addRow(tr("Script"), self.script_field)
        self.language_field = QComboBox(); self.language_field.activated.connect(self.changed)
        form.addRow(tr("Idioma"), self.language_field)
        self.screen_field = QComboBox(); self.screen_field.activated.connect(self.changed)
        form.addRow(tr("Pantalla"), self.screen_field)
        self.container_field = QComboBox(); self.container_field.activated.connect(self.changed)
        form.addRow(tr("Abrir en"), self.container_field)
        self.template_field = QComboBox(); self.template_field.activated.connect(self.change_template)
        form.addRow(tr("Objeto"), self.template_field)
        self.bindings = QWidget(); self.binding_form = QFormLayout(self.bindings)
        self.binding_form.setContentsMargins(0, 0, 0, 0)
        self.binding_fields = {}
        form.addRow(self.bindings)
        self.title_field = ProjectTextField(studio)
        self.title_field.setPlaceholderText(tr("Automático: objeto · equipo"))
        self.title_field.editingFinished.connect(self.changed)
        form.addRow(tr("Título"), self.title_field)
        self.modal_field = QCheckBox(tr("Bloquear la ventana principal")); self.modal_field.clicked.connect(self.changed)
        form.addRow(self.modal_field)

        note = QLabel(tr("Al soltar el botón se envían las acciones en orden, sin esperar a que termine ninguna. "
                         "Una escritura enviada no confirma que el PLC la haya aplicado, y las escrituras de un script "
                         "se envían cuando el script termina. Si una acción no se puede realizar no se envía ninguna; "
                         "abrir o cerrar pantallas solo puede ser la última acción."))
        note.setWordWrap(True); layout.addWidget(note)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.validator = self.check
        self.refresh_list(0 if self.steps else -1)

    # --- list ------------------------------------------------------------------------------
    def refresh_list(self, row):
        self._loading = True
        self.list.clear()
        for number, step in enumerate(self.steps, 1):
            self.list.addItem(f"{number}. {label(step)}")
        self._loading = False
        self.current = -1
        self.list.setCurrentRow(row)
        self.form_group.setEnabled(row >= 0)
        if row < 0:
            self.load({"action": "set"})

    def select(self, row):
        if self._loading:
            return
        self.store()
        self.current = row
        self.form_group.setEnabled(row >= 0)
        if row >= 0:
            self.load(self.steps[row])

    def add(self):
        self.store()
        self.steps.append({"action": "set", "tag": "", "value": ""})
        self.refresh_list(len(self.steps) - 1)

    def remove(self):
        row = self.list.currentRow()
        if row >= 0:
            del self.steps[row]
            self.current = -1
            self.refresh_list(min(row, len(self.steps) - 1))

    def move(self, offset):
        self.store()
        row = self.list.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < len(self.steps):
            self.steps[row], self.steps[target] = self.steps[target], self.steps[row]
            self.current = -1
            self.refresh_list(target)

    # --- form ------------------------------------------------------------------------------
    def tag_kind(self, tag):
        tags = self.studio.project.tags()
        if tag in tags:
            return tags[tag]["type"]
        return self.studio.document_references().get(tag.lstrip("$"))

    def load(self, step):
        self._loading = True
        project, action = self.studio.project, step.get("action", "set")
        self.type_field.setCurrentIndex(max(0, self.type_field.findData(action)))
        self.tag_field.clear()
        options = [name for name, tag in project.tags().items() if tag.get("writable")
                   and (action != "toggle" or tag["type"] == "bool")]
        if self.studio.document_kind == "faceplates":
            options = ["$" + name for name, kind in self.studio.document_references().items()
                       if kind in PRIMITIVES and (action != "toggle" or kind == "bool")] + options
        self.tag_field.addItems(options)
        self.tag_field.setCurrentText(step.get("tag", ""))
        self.value_field.setText(str(step.get("value", "")))
        from .script_tree import choices as script_choices
        self.script_field.clear()
        for name, text in script_choices(project):
            self.script_field.addItem(text, name)
        self.script_field.setCurrentIndex(max(0, self.script_field.findData(step.get("script", ""))))
        self.language_field.clear(); self.language_field.addItems(project.manifest.get("languages", ["es"]))
        self.language_field.setCurrentText(step.get("language", self.studio.editing_language))
        self.screen_field.clear(); self.screen_field.addItems(list(project.screens))
        self.screen_field.setCurrentText(step.get("screen", ""))
        self.container_field.clear()
        self.container_field.addItem(tr("Zona actual"), "")
        self.container_field.addItem(tr("Ventana completa"), "__window__")
        from .screen_layouts import containers
        for name in sorted({c["id"] for doc in project.screens.values() for c in containers(doc)}):
            self.container_field.addItem(name, name)
        self.container_field.setCurrentIndex(max(0, self.container_field.findData(step.get("target_container", ""))))
        self.template_field.clear(); self.template_field.addItems(list(project.faceplates))
        self.template_field.setCurrentText(step.get("template", ""))
        self.title_field.set_value(step.get("title", ""))
        self.modal_field.setChecked(step.get("modal", False))
        self.load_bindings(step.get("template", ""), step.get("bindings", {}))
        visible = {self.tag_field: action in {"set", "toggle"}, self.value_field: action == "set",
                   self.script_field: action == "script", self.language_field: action == "set_language",
                   self.screen_field: action in {"screen", "popup"}, self.container_field: action == "screen",
                   self.template_field: action == "faceplate_popup", self.bindings: action == "faceplate_popup",
                   self.title_field: action == "faceplate_popup", self.modal_field: action in {"popup", "faceplate_popup"}}
        for widget, shown in visible.items():
            self.form.setRowVisible(widget, shown)
        self._loading = False

    def load_bindings(self, template, bindings):
        from .dialogs import discard
        while self.binding_form.count():
            entry = self.binding_form.takeAt(0)
            if entry.widget():
                discard(entry.widget())
        self.binding_fields = {}
        if template not in self.studio.project.faceplates:
            return
        for parameter, kind in self.studio.project.faceplates[template].get("parameters", {}).items():
            from .popup_variants_editor import binding_combo
            combo = binding_combo(self.studio, template, parameter, kind, bindings.get(parameter, ""))
            combo.activated.connect(self.changed)
            combo.lineEdit().editingFinished.connect(self.changed)
            self.binding_fields[parameter] = combo
            self.binding_form.addRow(parameter, combo)

    def change_type(self, *args):
        self.store()
        if self.current >= 0:
            self.load(self.steps[self.current])

    def change_template(self, *args):
        if not self._loading:
            self.load_bindings(self.template_field.currentText(), {})
            self.changed()

    def changed(self, *args):
        if self._loading or self.current < 0:
            return
        self.store()
        item = self.list.item(self.current)
        if item:
            item.setText(f"{self.current + 1}. {label(self.steps[self.current])}")

    def store(self):
        """Copy the form into the selected step; keeps the window options set in advanced JSON."""
        if self.current < 0 or self.current >= len(self.steps):
            return
        previous = self.steps[self.current]
        action = self.type_field.currentData()
        step = {"action": action}
        if action in {"set", "toggle"}:
            step["tag"] = self.tag_field.currentText().strip()
        if action == "set":
            from .value_editor import engineering_value
            raw, kind = self.value_field.text(), self.tag_kind(step["tag"])
            try:
                step["value"] = engineering_value(raw, kind or "string")
            except (ValueError, TypeError):
                step["value"] = raw  # the check on OK reports it
        if action == "script":
            step["script"] = self.script_field.currentData() or ""
        if action == "set_language":
            step["language"] = self.language_field.currentText()
        if action in {"screen", "popup"}:
            step["screen"] = self.screen_field.currentText()
        if action == "screen" and self.container_field.currentData():
            step["target_container"] = self.container_field.currentData()
        if action in {"popup", "faceplate_popup"}:
            if self.modal_field.isChecked():
                step["modal"] = True
            if previous.get("action") == action and "window" in previous:
                step["window"] = copy.deepcopy(previous["window"])
        if action == "faceplate_popup":
            step["template"] = self.template_field.currentText()
            from .popup_variants_editor import combo_value
            step["bindings"] = {parameter: combo_value(combo) for parameter, combo in self.binding_fields.items()}
            if self.title_field.text().strip() or isinstance(self.title_field.original, dict):
                step["title"] = self.title_field.translated_value()
        self.steps[self.current] = step

    # --- result ----------------------------------------------------------------------------
    def check(self):
        """Validate the project with this list before closing the dialog."""
        self.store()
        candidate = copy.deepcopy(self.studio.project)
        document = getattr(candidate, self.studio.document_kind)[self.studio.document_name]
        element = next(e for e in document["elements"] if e["id"] == self.element["id"])
        element["actions"] = copy.deepcopy(self.steps)
        candidate.validate()

    def result_steps(self):
        return copy.deepcopy(self.steps)
