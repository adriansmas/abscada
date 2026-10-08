"""Operational configuration UI. All edits use Studio's validation and undo history."""
import copy
import uuid
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QDialogButtonBox, QLineEdit, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QLabel,
    QListWidget, QListWidgetItem, QColorDialog, QFileDialog, QInputDialog)
from PySide6.QtGui import QColor
from .operational_config import OPERATORS, ALARM_COLUMNS, DEFAULT_ALARM_COLUMNS
from .dialogs import EditorDialog
from .i18n import tr
from .project_languages import resolve, default_language


def control(kind, value, options=()):
    if kind == "multi":
        widget = QListWidget(); widget.setMaximumHeight(120)
        for data, title in options:
            item = QListWidgetItem(title); item.setData(Qt.ItemDataRole.UserRole, data)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if data in value else Qt.CheckState.Unchecked)
            widget.addItem(item)
    elif kind == "color":
        widget = ColorControl(value)
    elif kind == "choice":
        widget = QComboBox()
        for data, text in options:
            widget.addItem(text, data)
        widget.setCurrentIndex(max(0, widget.findData(value)))
    elif kind == "bool":
        widget = QCheckBox(); widget.setChecked(value)
    elif kind in {"int", "number"}:
        widget = QSpinBox() if kind == "int" else QDoubleSpinBox()
        widget.setRange(-1000000000, 1000000000)
        if kind == "number":
            widget.setDecimals(4)
        widget.setValue(value)
    else:
        widget = QLineEdit(str(value))
    return widget


def value(widget):
    if isinstance(widget, QListWidget):
        return [widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(widget.count()) if widget.item(i).checkState()==Qt.CheckState.Checked]
    if isinstance(widget, QComboBox):
        return widget.currentData()
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        return widget.value()
    return widget.text().strip()


class ColorControl(QWidget):
    def __init__(self, initial):
        super().__init__()
        layout = QHBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.input = QLineEdit(initial); layout.addWidget(self.input)
        button = QPushButton("…"); button.setFixedWidth(36); button.clicked.connect(self.choose); layout.addWidget(button)

    def choose(self):
        selected = QColorDialog.getColor(QColor(self.input.text()), self, tr("Color"))
        if selected.isValid():
            self.input.setText(selected.name())

    def text(self):
        return self.input.text()


class RecordDialog(EditorDialog):
    def __init__(self, parent, title, fields, data=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 300)
        self.fields = {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        data = data or {}
        from .project_text_editor import ProjectTextField
        for key, label, kind, default, options in fields:
            from .project_languages import TEXT_KEYS
            translatable = key in TEXT_KEYS or (key == 'name' and 'color' in {f[0] for f in fields})
            widget = ProjectTextField(parent, data.get(key, default)) if kind == 'text' and translatable else control(kind, data.get(key, default), options)
            widget.setObjectName("field_"+key)
            if isinstance(widget, ColorControl):
                widget.input.setObjectName("field_"+key)
            self.fields[key] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Aceptar"))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def data(self):
        return {key: widget.translated_value() if hasattr(widget, 'translated_value') else value(widget) for key, widget in self.fields.items()}


class RecordsPage(QWidget):
    def __init__(self, host, getter, setter, columns, fields, title, identity="id"):
        super().__init__()
        self.host, self.getter, self.setter = host, getter, setter
        self.columns, self.fields, self.title, self.identity = columns, fields, title, identity
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 6, 0, 0)
        toolbar = QHBoxLayout()
        for text, callback in ((tr("+ Añadir"), lambda: self.edit(None)), (tr("Editar…"), self.edit_selected), (tr("Eliminar"), self.delete)):
            button = QPushButton(text); button.clicked.connect(callback); toolbar.addWidget(button)
            if text == tr("+ Añadir"):
                button.setObjectName("primary")
        toolbar.addStretch()
        # Search box apart from the buttons: it only filters the list.
        self.search = QLineEdit(); self.search.setPlaceholderText(tr("🔍 Filtrar la lista…")); self.search.setObjectName("searchField")
        self.search.setClearButtonEnabled(True); self.search.setFixedWidth(280)
        self.search.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search)
        layout.addLayout(toolbar)
        self.notice = QLabel(); self.notice.setObjectName("filterNotice"); self.notice.hide()
        self.notice.linkActivated.connect(lambda link: self.search.clear())
        layout.addWidget(self.notice)
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([label for _, label in columns])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().hide()
        self.table.cellDoubleClicked.connect(lambda r, c: self.edit_selected())
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self, *args):
        needle = self.search.text().casefold()
        everything = self.getter()
        self.rows = [row for row in everything if needle in str(row).casefold()]
        self.notice.setVisible(bool(needle))
        if needle:
            self.notice.setText(tr("Filtro «{text}»: se muestran {len} de {len2} · <a href='clear'>Quitar el filtro</a>", text=self.search.text(), len=len(self.rows), len2=len(everything)))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            for column, (key, _) in enumerate(self.columns):
                val = row.get(key, '')
                if isinstance(val, dict):
                    from .project_languages import resolve, default_language
                    val = resolve(val, getattr(self.host, 'editing_language', default_language(self.host.project)), default_language(self.host.project))
                translated = {"cyclic":tr("Cíclico"),"change":tr("Por cambio"),"left":tr("Izquierda"),"right":tr("Derecha"),
                    "pending":tr("Pendientes"),"active":tr("Activas"),"history":tr("Histórico"),"events":tr("Eventos")}
                if key=="condition":
                    val=OPERATORS.get(val,val)
                elif key in {"mode","side"}:
                    val=translated.get(val,val)
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                item = QTableWidgetItem(tr("Sí") if val is True else tr("No") if val is False else str(val))
                item.setData(Qt.ItemDataRole.UserRole,row[self.identity])
                if isinstance(val,(int,float)) and not isinstance(val,bool):
                    item.setData(Qt.ItemDataRole.DisplayRole,val)
                self.table.setItem(index,column,item)
        self.table.setSortingEnabled(True)

    def selected(self):
        row = self.table.currentRow()
        if row<0 or self.table.item(row,0) is None:
            return None
        key=self.table.item(row,0).data(Qt.ItemDataRole.UserRole)
        return next((record for record in self.rows if record[self.identity]==key),None)

    def edit_selected(self):
        data = self.selected()
        if data:
            self.edit(data)

    def edit(self, previous):
        dialog = RecordDialog(self.host if isinstance(self.host, QWidget) else self, self.title, self.fields(), previous)
        if hasattr(self, "prepare_dialog"):
            self.prepare_dialog(dialog)
        if previous and self.identity in dialog.fields and isinstance(dialog.fields[self.identity], QLineEdit):
            dialog.fields[self.identity].setReadOnly(True)
        # Invalid definitions remain editable instead of losing the user's input.
        def accept():
            data = dialog.data()
            rows = copy.deepcopy(self.getter())
            if previous:
                rows[next(i for i, row in enumerate(rows) if row[self.identity] == previous[self.identity])] = data
            else:
                rows.append(data)
            if self.host.mutate(lambda: self.setter(rows)):
                dialog.accept()
                if not previous:
                    self.search.clear()
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.accepted.disconnect(); buttons.accepted.connect(accept)
        dialog.exec()
        self.refresh()

    def delete(self):
        selected = self.selected()
        if selected:
            self.host.mutate(lambda: self.setter([r for r in self.getter() if r[self.identity] != selected[self.identity]]))


def text(key, label, default=""):
    return key, label, "text", default, ()


def numeric(key, label, default=0, integer=False):
    return key, label, "int" if integer else "number", default, ()


def boolean(key, label, default=True):
    return key, label, "bool", default, ()


def choice(key, label, choices, default=None):
    return key, label, "choice", default, choices


def color_field(default="#147d75"):
    return "color", tr("Color"), "color", default, ()


class OperationalEngineering:
    def __init__(self, host):
        from . import recording
        recording.migrate(host.project)
        self.host, self.pages = host, []
        self.alarms = QTabWidget()
        self.alarm_definitions = self.records(lambda: host.project.alarms["items"], lambda rows: host.project.alarms.__setitem__("items", rows),
            [("id", "ID"), ("message", tr("Mensaje")), ("tag", tr("Variable")), ("category", tr("Categoría")), ("condition", tr("Condición")), ("threshold", tr("Umbral")), ("priority", tr("Prioridad")), ("enabled", tr("Habilitada"))], self.alarm_fields, tr("Alarma"))
        self.alarm_definitions.prepare_dialog = self.configure_alarm_dialog
        self.categories = self.records(lambda: host.project.alarms["categories"], lambda rows: host.project.alarms.__setitem__("categories", rows),
            [("id", "ID"), ("name", tr("Nombre")), ("color", tr("Color"))], lambda: [text("id", "ID"), text("name", tr("Nombre")), color_field("#d74c4c")], tr("Categoría de alarmas"))
        self.alarms.addTab(self.alarm_definitions, tr("Alarmas"))
        self.alarms.addTab(self.categories, tr("Categorías"))
        # Retention lives in «Ajustes del proyecto → Registros»; the SQLite copy in «Herramientas».
        self.historian = QWidget(); layout = QVBoxLayout(self.historian); layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(tr("Cada fichero de registro guarda un grupo de variables con su frecuencia. Las gráficas los consultan "
                      "para mostrar el histórico."))
        hint.setWordWrap(True); hint.setObjectName("muted"); layout.addWidget(hint)
        self.logs = self.records(lambda: self.host.project.historian["files"],
            lambda rows: self.host.project.historian.__setitem__("files", rows),
            [("id", tr("Fichero")), ("name", tr("Nombre")), ("interval_ms", tr("Frecuencia (ms)")), ("variables", tr("Variables"))], self.log_fields, tr("Fichero de registro"))
        layout.addWidget(self.logs)
        # Trends and alarm viewers are configured from their control on the screen (configure_viewer).
        self.refresh()

    def records(self, *args):
        page = RecordsPage(self.host, *args); self.pages.append(page); return page

    def tags(self, kinds=None):
        return [(name, name) for name, tag in self.host.project.tags().items() if not kinds or tag["type"] in kinds]

    def configure_alarm_dialog(self, dialog):
        tag, op = dialog.fields["tag"], dialog.fields["condition"]
        def state(*args):
            kind = self.host.project.tags().get(tag.currentData(), {}).get("type")
            current = op.currentData()
            keys = ("true", "false") if kind == "bool" else ("high", "low", "equal", "not_equal")
            op.blockSignals(True); op.clear()
            for key in keys:
                op.addItem(OPERATORS[key],key)
            op.setCurrentIndex(max(0,op.findData(current))); op.blockSignals(False)
            dialog.fields["threshold"].setEnabled(kind!="bool")
            dialog.fields["hysteresis"].setEnabled(op.currentData() in {"high","low"})
        tag.currentIndexChanged.connect(state)
        op.currentIndexChanged.connect(lambda: dialog.fields["hysteresis"].setEnabled(op.currentData() in {"high","low"}))
        state()

    def alarm_fields(self):
        categories = [(c["id"], c["name"]) for c in self.host.project.alarms["categories"]]
        return [text("id", "ID"), text("message", tr("Mensaje")), choice("tag", tr("Variable"), self.tags({"bool", "int", "float"})),
            choice("category", tr("Categoría"), categories), choice("condition", tr("Condición"), list(OPERATORS.items()), "high"),
            numeric("threshold", tr("Umbral")), numeric("hysteresis", tr("Histéresis")), numeric("on_delay_ms", tr("Retardo entrada (ms)"), integer=True),
            numeric("off_delay_ms", tr("Retardo salida (ms)"), integer=True), numeric("priority", "Prioridad (1–1000)", 500, True),
            boolean("ack_required", tr("Requiere ACK")), boolean("enabled", tr("Habilitada"))]

    def alarm_view_fields(self):
        return [text("title", tr("Título"), tr("Alarmas")),
            choice("mode", tr("Vista inicial"), [("pending", tr("Pendientes")), ("active", tr("Activas")), ("history", tr("Histórico")), ("events", tr("Eventos"))], "pending"),
            numeric("min_priority", tr("Prioridad mínima"), 1, True),
            ("categories", tr("Categorías"), "multi", [], [(c["id"],c["name"]) for c in self.host.project.alarms["categories"]]),
            ("columns", tr("Columnas"), "multi", DEFAULT_ALARM_COLUMNS, ALARM_COLUMNS), boolean("allow_ack", tr("Permitir ACK"))]

    def edit_alarm_view(self, name):
        """Configuration of one alarm viewer control (each control owns its configuration)."""
        dialog = RecordDialog(self.host, tr("Configurar visor de alarmas"), self.alarm_view_fields(), self.host.project.alarm_views[name])
        def accept():
            data = dialog.data()
            if self.host.mutate(lambda: self.host.project.alarm_views[name].update(data)):
                dialog.accept()
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.accepted.disconnect(); buttons.accepted.connect(accept)
        dialog.exec()

    def log_fields(self):
        return [text("id", tr("Fichero"), "registro_"+uuid.uuid4().hex[:6]), text("name", tr("Nombre"), tr("Registro")),
            numeric("interval_ms", tr("Frecuencia (ms)"), 1000, True),
            ("variables", tr("Variables"), "multi", [], self.tags())]

    def backup(self):
        from .storage import ArchiveReader, database_path
        from .viewers import READERS
        sources = [database_path(self.host.project)] + sorted((self.host.project.root / "runtime" / "records").rglob("*.sqlite3"))
        sources = [p for p in sources if p.exists()]
        if not sources:
            self.host.error(tr("No hay archivos SQLite para copiar"))
            return
        labels = [str(p.relative_to(self.host.project.root / "runtime")) for p in sources]
        selected, ok = QInputDialog.getItem(self.host, tr("Copia SQLite"), tr("Archivo"), labels, 0, False)
        if not ok:
            return
        source = sources[labels.index(selected)]
        filename, _ = QFileDialog.getSaveFileName(self.host, tr("Copia SQLite"), source.name, tr("SQLite (*.sqlite3)"))
        if not filename:
            return
        future = READERS.submit(ArchiveReader(source).backup, filename)
        timer = QTimer(self.historian)
        def completed():
            if not future.done():
                return
            timer.stop(); timer.deleteLater()
            try:
                future.result(); self.host.statusBar().showMessage(tr("Copia SQLite guardada"), 5000)
            except Exception as exc:
                self.host.error(exc)
        timer.timeout.connect(completed); timer.start(100)

    def refresh(self):
        for page in self.pages:
            page.refresh()

    def edit_trend(self, name):
        """Configuration of one trend control (each control owns its configuration)."""
        draft = copy.deepcopy(self.host.project.trends[name])
        dialog = EditorDialog(self.host); dialog.setWindowTitle(tr("Configurar gráfica")); dialog.resize(880, 570)
        layout = QVBoxLayout(dialog); form = QFormLayout()
        from .project_text_editor import ProjectTextField
        title = ProjectTextField(self.host, draft['title'])
        title.setObjectName("trendTitle")
        seconds = QSpinBox(); seconds.setRange(10, 31536000); seconds.setValue(draft.get("window_seconds", 600))
        for label, widget in ((tr("Título"), title), (tr("Ventana (s)"), seconds)):
            form.addRow(label, widget)
        layout.addLayout(form); tabs = QTabWidget(); layout.addWidget(tabs)
        class DraftHost:
            project = self.host.project
            editing_language = self.host.editing_language
            def mutate(inner, callback):
                callback(); axes.refresh(); curves.refresh(); return True
        holder = DraftHost()
        axes = RecordsPage(holder, lambda: draft["axes"], lambda rows: draft.__setitem__("axes", rows),
            [("id", "ID"), ("title", tr("Título")), ("side", tr("Lado")), ("auto", tr("Auto")), ("min", tr("Mínimo")), ("max", tr("Máximo")), ("visible", tr("Visible"))],
            lambda: [text("id", "ID"), text("title", tr("Título")), choice("side", tr("Lado"), [("left", tr("Izquierda")), ("right", tr("Derecha"))], "left"),
                boolean("auto", tr("Escala automática")), numeric("min", tr("Mínimo")), numeric("max", tr("Máximo"), 100), boolean("visible", tr("Visible"))], tr("Eje"))
        curves = RecordsPage(holder, lambda: draft["curves"], lambda rows: draft.__setitem__("curves", rows),
            [("id", "ID"), ("tag", tr("Variable")), ("axis", tr("Eje")), ("color", tr("Color")), ("width", tr("Grosor")), ("visible", tr("Visible"))],
            lambda: [text("id", "ID", "curve_"+uuid.uuid4().hex[:6]), choice("tag", tr("Variable"), self.tags({"int", "float", "bool"})),
                choice("axis", tr("Eje"), [(a["id"], resolve(a.get('title', a['id']), self.host.editing_language, default_language(self.host.project))) for a in draft["axes"]]), color_field(),
                numeric("width", tr("Grosor"), 2), boolean("visible", tr("Visible"))], tr("Curva"))
        # Draft dialogs are parented to their QWidget page, not the draft controller.
        axes.host = curves.host = holder
        tabs.addTab(axes, tr("Ejes")); tabs.addTab(curves, tr("Curvas"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Aceptar"))
        def save():
            draft.update(title=title.translated_value(), window_seconds=seconds.value())
            if self.host.mutate(lambda: self.host.project.trends.__setitem__(name, copy.deepcopy(draft))):
                dialog.accept()
        buttons.accepted.connect(save); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        dialog.exec()
