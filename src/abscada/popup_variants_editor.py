"""Alternatives of «Abrir objeto en ventana»: open another object when a condition holds."""
import copy
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QHeaderView, QWidget)
from .dialogs import EditorDialog
from .i18n import tr


def binding_combo(studio, template, parameter, kind, current):
    """Editable list of what can fill a parameter; also takes typed paths such as Juegos[Sel]."""
    combo = QComboBox(); combo.setEditable(True)
    combo.addItem(tr("(sin asignar)"), "")
    for option in studio.popup_binding_options(template, parameter, kind):
        combo.addItem(option, option)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(current)
    combo.setToolTip(tr("Tipo {kind}. También puedes escribir una ruta con índice variable, como Juegos[Seleccion]", kind=kind))
    return combo


def combo_value(combo):
    """The chosen option's value, or the text typed by hand."""
    if combo.currentIndex() >= 0 and combo.itemText(combo.currentIndex()) == combo.currentText():
        return combo.currentData() or ""
    return combo.currentText().strip()


def describe(variant):
    from .dynamic_editor import describe_condition
    return describe_condition(variant.get("when")), variant.get("template", "")


class VariantDialog(EditorDialog):
    def __init__(self, studio, element, variant):
        super().__init__(studio)
        from .dynamic_editor import ConditionList
        from .project_text_editor import ProjectTextField
        self.studio, self.element = studio, element
        self.setWindowTitle(tr("Alternativa")); self.resize(560, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Cuando se cumpla:")))
        self.condition = ConditionList(studio, variant.get("when"), False); layout.addWidget(self.condition)
        form = QFormLayout(); layout.addLayout(form)
        self.template = QComboBox(); self.template.addItems(list(studio.project.faceplates))
        self.template.setCurrentText(variant.get("template", element.get("template", "")))
        form.addRow(tr("Abrir el objeto"), self.template)
        self.bindings_box = QWidget(); self.bindings_form = QFormLayout(self.bindings_box); self.bindings_form.setContentsMargins(0, 0, 0, 0)
        form.addRow(self.bindings_box)
        self.title = ProjectTextField(studio, variant.get("title", "")); self.title.setPlaceholderText(tr("El del botón"))
        form.addRow(tr("Título"), self.title)
        self.fields = {}
        self.load(variant.get("bindings", element.get("bindings", {})))
        self.template.currentTextChanged.connect(lambda *_: self.load({}))
        self.validator = self.validate
        studio.dialog_buttons(self, layout)

    def load(self, bindings):
        from .dialogs import discard
        while self.bindings_form.count():
            entry = self.bindings_form.takeAt(0)
            if entry.widget():
                discard(entry.widget())
        self.fields = {}
        template = self.template.currentText()
        for parameter, kind in self.studio.project.faceplates.get(template, {}).get("parameters", {}).items():
            # Same parameter name in the button's object: proposed by default.
            current = bindings.get(parameter, self.element.get("bindings", {}).get(parameter, ""))
            combo = binding_combo(self.studio, template, parameter, kind, current)
            self.fields[parameter] = combo; self.bindings_form.addRow(parameter, combo)

    def variant(self):
        result = dict(when=self.condition.data(), template=self.template.currentText(),
                      bindings={parameter: combo_value(combo) for parameter, combo in self.fields.items()})
        if self.title.text() or isinstance(self.title.original, dict):
            result["title"] = self.title.translated_value()
        return result

    def validate(self):
        candidate = copy.deepcopy(self.studio.project)
        element = dict(copy.deepcopy(self.element), variants=[self.variant()])
        document = getattr(candidate, self.studio.document_kind)[self.studio.document_name]
        index = next(i for i, e in enumerate(document["elements"]) if e["id"] == element["id"])
        document["elements"][index] = element
        candidate.validate()


class VariantsDialog(EditorDialog):
    """Ordered list: the first alternative whose condition holds is opened."""
    def __init__(self, studio, element):
        super().__init__(studio)
        self.studio, self.element = studio, element
        self.variants = copy.deepcopy(element.get("variants", []))
        self.setWindowTitle(tr("Objetos alternativos · ") + element["id"]); self.resize(640, 420)
        layout = QVBoxLayout(self)
        note = QLabel(tr("Al pulsar se abre la primera alternativa cuya condición se cumpla; si no se cumple ninguna, "
                         "el objeto del botón ({template}).", template=element.get("template", "")))
        note.setWordWrap(True); note.setObjectName("muted"); layout.addWidget(note)
        self.table = QTableWidget(0, 2); self.table.setHorizontalHeaderLabels([tr("Cuando"), tr("Abre")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit(False))
        layout.addWidget(self.table, 1)
        row = QHBoxLayout(); layout.addLayout(row)
        for title, callback in [(tr("Añadir"), lambda: self.edit(True)), (tr("Editar"), lambda: self.edit(False)),
                                (tr("Eliminar"), self.remove), (tr("Subir"), self.up)]:
            button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
        row.addStretch()
        self.refresh()
        studio.dialog_buttons(self, layout)

    def refresh(self):
        self.table.setRowCount(len(self.variants))
        for row, variant in enumerate(self.variants):
            for column, text in enumerate(describe(variant)):
                self.table.setItem(row, column, QTableWidgetItem(text))

    def edit(self, new):
        index = -1 if new else self.table.currentRow()
        if not new and index < 0:
            return
        dialog = VariantDialog(self.studio, self.element, {} if new else self.variants[index])
        if dialog.exec() == EditorDialog.DialogCode.Accepted:
            if new:
                self.variants.append(dialog.variant())
            else:
                self.variants[index] = dialog.variant()
            self.refresh()

    def remove(self):
        index = self.table.currentRow()
        if index >= 0:
            self.variants.pop(index); self.refresh()

    def up(self):
        index = self.table.currentRow()
        if index > 0:
            self.variants[index - 1], self.variants[index] = self.variants[index], self.variants[index - 1]
            self.refresh(); self.table.selectRow(index - 1)


def edit_variants(studio, element):
    dialog = VariantsDialog(studio, element)
    if dialog.exec() == EditorDialog.DialogCode.Accepted:
        variants = dialog.variants
        def apply():
            if variants:
                element["variants"] = variants
            else:
                element.pop("variants", None)
        studio.mutate(apply, selected_ids=[element["id"]])
