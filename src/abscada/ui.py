"""Engineering workspace. Live operation belongs to RuntimeWindow."""
from __future__ import annotations
import copy
import json
import uuid
import shutil
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QMimeData, QPointF, QSettings, QTimer
from PySide6.QtGui import QAction, QDrag, QColor, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QStackedWidget,
    QLineEdit, QTableWidget, QTableWidgetItem, QPushButton, QLabel, QComboBox,
    QPlainTextEdit, QFileDialog, QFormLayout, QDoubleSpinBox, QSpinBox,
    QScrollArea, QGroupBox, QDialog, QDialogButtonBox, QCheckBox, QColorDialog,
    QHeaderView, QMessageBox, QInputDialog, QTabWidget, QMenu, QToolButton,QSizePolicy,
)
from .project import coerce, PRIMITIVES
from .connectors import REGISTRY, definition, binding_summary
from .protocol_editor import ProtocolForm, BindingEditor
from .project_actions import ProjectActions
from .graphics import PALETTE, tool_icon, CanvasScene, CanvasView, ElementItem
from .theme import STYLE, STUDIO_STYLE, configure_fonts
from .runtime_window import RuntimeWindow
from .engineering import OperationalEngineering
from .drawing import PATH_KINDS, SHAPE_KINDS, set_points
from .graphic_properties import ScreenProperties, DrawingProperties, ColorField
from .drawing_actions import DrawingActions
from .text_list_editor import edit_text_list
from .dialogs import EditorDialog as QDialog


def label(text, name="muted"):
    widget = QLabel(text)
    widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


TOOL_GROUPS = (("Indicadores y mandos", ("text", "lamp", "button", "input", "bar", "gauge", "text_list", "image")),
               ("Trazados y formas", None),
               ("Visores y composición", ("faceplate", "trend", "alarm_view", "screen_container")))


class Toolbox(QListWidget):
    """Every drawing tool, grouped under a title; the search box filters them."""
    def __init__(self):
        super().__init__()
        self.setObjectName("toolbox")
        self.setViewMode(QListWidget.ViewMode.ListMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setWrapping(False)
        self.setSpacing(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setIconSize(QSize(24, 24))

        self.setDragEnabled(True)
        self.setMinimumHeight(204)
        listed = set()
        for title, kinds in TOOL_GROUPS:
            kinds = kinds or tuple(k for k in PALETTE if k in PATH_KINDS | SHAPE_KINDS)
            header = QListWidgetItem(title.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setSizeHint(QSize(190, 24))
            font = header.font(); font.setBold(True); font.setPointSizeF(font.pointSizeF() * 0.85); header.setFont(font)
            self.addItem(header)
            for kind in kinds:
                self.add_tool(kind); listed.add(kind)
        for kind in PALETTE:
            if kind not in listed:
                self.add_tool(kind)

    def add_tool(self, kind):
        title = PALETTE[kind]
        item = QListWidgetItem(tool_icon(kind), title)
        item.setSizeHint(QSize(190, 30))
        item.setData(Qt.ItemDataRole.UserRole, kind)
        item.setToolTip(title + (" · clic para cada punto; Enter o doble clic para terminar; Esc para cancelar" if kind in PATH_KINDS else ""))
        self.addItem(item)

    def filter(self, text=""):
        query = text.casefold()
        for i in range(self.count()):
            item = self.item(i)
            is_header = item.data(Qt.ItemDataRole.UserRole) is None
            item.setHidden(bool(query) and (is_header or query not in item.text().casefold()))

    def startDrag(self, actions):
        item = self.currentItem()
        if item:
            mime = QMimeData()
            mime.setData("application/x-abscada-element", item.data(Qt.ItemDataRole.UserRole).encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(item.icon().pixmap(40, 40))
            drag.exec(Qt.DropAction.CopyAction)


from .variable_forms import VariableForms
from .project_tree import ProjectTree, ProjectTreeActions
from .clipboard_actions import ClipboardActions


class Window(VariableForms, DrawingActions, ProjectActions, ProjectTreeActions, ClipboardActions, QMainWindow):
    design_mode = True

    def __init__(self, project):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.project = project
        self.runtime_window = None
        self.samples = {}
        self.dirty = False
        self.document_kind = "screens"
        self.document_name = project.manifest["startup_screen"]
        self.undo_stack, self.redo_stack = [], []
        self._interaction_backup = None
        self._syncing = False
        self._insertion_counter = 0
        self.setFont(configure_fonts())
        self.setStyleSheet(STYLE + STUDIO_STYLE)
        self.setWindowTitle("abSCADA Studio · " + project.manifest["name"])
        self.resize(1440, 860)
        self.setMinimumSize(980, 650)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.workspace_row = row
        self.active_section = "screens"
        self.project_label = label(self.project.manifest["name"], "projectName")
        workspace = QWidget()
        main = QVBoxLayout(workspace)
        main.setContentsMargins(10, 8, 10, 6)
        main.setSpacing(6)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        self.page_title = label("Pantallas", "pageTitle")
        titles.addWidget(self.page_title)
        top.addLayout(titles)
        top.addStretch()
        self.unsaved_label = QPushButton("● Cambios sin guardar · Guardar (Ctrl+S)")
        self.unsaved_label.setObjectName("unsavedBadge")
        self.unsaved_label.setToolTip("Los cambios se conservan al pasar de una sección a otra, pero solo se escriben en disco al guardar.")
        self.unsaved_label.clicked.connect(lambda: self.save_project())
        self.unsaved_label.hide()
        top.addWidget(self.unsaved_label)
        self.mode_label = label("MODO DISEÑO", "designBadge")
        self.mode_label.setFixedHeight(28)
        top.addWidget(self.mode_label)
        self.runtime_changed=label('Cambios posteriores al arranque','muted');self.runtime_changed.hide();top.addWidget(self.runtime_changed)
        self.restart_button=button('Reiniciar con cambios',self.restart_runtime);self.restart_button.hide();top.addWidget(self.restart_button)
        self.stop_button = button("Detener runtime", self.stop_runtime)
        self.stop_button.hide()
        top.addWidget(self.stop_button)
        self.run_button = button("▶  Abrir runtime", self.start_runtime, True)
        top.addWidget(self.run_button)
        main.addLayout(top)
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        row.addWidget(workspace, 1)
        self.setCentralWidget(root)
        self.build_graphics()
        self.build_variables()
        self.build_catalogs()
        self.operational_editor = OperationalEngineering(self)
        from .automation_editor import AutomationEditor
        self.automation_editor = AutomationEditor(self)
        # Variables and their structure types share one section.
        self.variables_tabs = QTabWidget()
        self.variables_tabs.addTab(self.variables_page, "Variables")
        self.variables_tabs.addTab(self.types_page, "Tipos de datos (estructuras)")
        self.variables_tabs.currentChanged.connect(lambda index: self.page_title.setText("Variables" if index == 0 else "Tipos de datos"))
        self.section_pages = dict(screens=self.graphics_page, faceplates=self.graphics_page, variables=self.variables_tabs,
                                  types=self.variables_tabs, connections=self.connections_page, diagnostics=self.diagnostics_page,
                                  alarms=self.operational_editor.alarms, historian=self.operational_editor.historian,
                                  automation=self.automation_editor)
        for page in dict.fromkeys(self.section_pages.values()):
            self.pages.addWidget(page)
        from .studio_shell import SectionRail, build_menus
        self.section_rail = SectionRail(self)
        self.workspace_row.insertWidget(0, self.section_rail)
        self.section_rail.show_section("screens")
        build_menus(self)
        self.populate_navigation()
        self.refresh_variables()
        self.refresh_catalogs()
        self.render_scene()
        self.statusBar().setFixedHeight(22)
        settings=QSettings('abSCADA','Studio')
        if settings.contains('graphicsSplitter'):self.graphics_splitter.restoreState(settings.value('graphicsSplitter'))
        self.toolbox_title.setChecked(settings.value('toolsExpanded',True,type=bool))
        self.resources_panel.setFixedWidth(232)
        self.connection_status_timer=QTimer(self);self.connection_status_timer.timeout.connect(self.update_connection_status);self.connection_status_timer.start(1000)

    @property
    def runtime(self):
        return self.runtime_window.runtime if self.runtime_window else None

    def open_visual_preview(self):
        from .visual_preview import VisualPreview
        self.visual_preview=VisualPreview(self);self.visual_preview.show()

    def update_runtime_difference(self):
        changed=bool(self.runtime_window and self.project!=self.runtime_window.project)
        self.runtime_changed.setVisible(changed);self.restart_button.setVisible(changed)

    def restart_runtime(self):
        if self.runtime_window and QMessageBox.question(self,'Reiniciar runtime','Se interrumpirá la sesión de operación. ¿Reiniciar con los cambios actuales?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        if self.stop_runtime():self.start_runtime()

    def review_project(self):
        from .dynamics import issues
        try:
            self.project.validate(); messages=issues(self.project)
        except Exception as exc: messages=[str(exc)]
        QMessageBox.information(self,'Revisión del proyecto','\n'.join(messages) or 'No se han encontrado errores de configuración')

    def active_rail(self):
        from .studio_shell import RAIL_OF
        return RAIL_OF.get(self.active_section, self.active_section)

    def navigate(self, key):
        self.active_section = key
        self.update_connection_status()
        graphics = key in {"screens", "faceplates"}
        # The project tree and the drawing tools only make sense while editing screens.
        self.resources_panel.setVisible(graphics)
        titles = {"screens": "Pantallas", "faceplates": "Librerías", "variables": "Variables",
                  "types": "Tipos de datos", "connections": "Conexiones", "diagnostics": "Diagnóstico", "alarms": "Alarmas", "historian": "Registros", "automation": "Scripts y tareas"}
        self.page_title.setText(titles[key])
        self.pages.setCurrentWidget(self.section_pages[key])
        if key in {"variables", "types"}:
            self.variables_tabs.setCurrentIndex(1 if key == "types" else 0)
        if hasattr(self, "section_rail"):
            self.section_rail.show_section(key)
        if key in {"screens", "faceplates"} and getattr(self.project, key) and self.document_kind != key:
            from .faceplate_libraries import owner
            choices = [name for name in getattr(self.project,key) if key != 'faceplates' or not owner(self.project,name)]
            if not choices:
                return
            self.document_kind, self.document_name = key, choices[0]
            self.populate_navigation()
            self.render_scene()

    def build_graphics(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.document_label = label("", "sectionTitle")
        tools.addWidget(self.document_label)
        tools.addStretch()
        self.canvas_actions = []
        for title, callback, shortcut, visible in (("Copiar", self.copy_elements, "Ctrl+C", False), ("Cortar", self.cut_elements, "Ctrl+X", False),
                                                   ("Pegar", self.paste_elements, "Ctrl+V", False),
                                                   ("Duplicar", self.duplicate_element, "Ctrl+D", True), ("Eliminar", self.delete_element, "Delete", True)):
            action = QAction(title, page)
            action.setShortcut(shortcut)
            # Canvas only: in a text field Ctrl+C / Ctrl+V keep copying text.
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.canvas_actions.append(action)
            action.triggered.connect(lambda checked=False, c=callback: c())
            if visible:
                tools.addWidget(button(title, callback))
        self.snap_action = QCheckBox("Ajustar a cuadrícula")
        self.snap_action.setChecked(True)
        tools.addWidget(self.snap_action)
        self.zoom_field = QComboBox(); self.zoom_field.setMinimumWidth(112); self.zoom_field.addItems(["Encajar","50%","75%","100%","150%","200%"])
        def zoom():
            if self.zoom_field.currentIndex()==0:
                self.view.fit_canvas()
            else:
                factor = int(self.zoom_field.currentText().rstrip("%"))/100
                self.view.auto_fit=False; self.view.resetTransform(); self.view.scale(factor,factor)
        self.zoom_field.activated.connect(zoom); tools.addWidget(self.zoom_field)
        bar = QWidget(); bar.setObjectName("canvasBar"); bar.setLayout(tools)
        tools.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(bar)
        self.graphics_splitter = QSplitter()
        splitter = self.graphics_splitter
        layout.addWidget(splitter, 1)
        resources = QWidget()
        resources.setObjectName("resources")
        self.resources_panel = resources
        resources.setMinimumWidth(210)
        resources.setMaximumWidth(232)
        box = QVBoxLayout(resources)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(5)
        header = QHBoxLayout(); header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(label("PROYECTO", "sectionTitle")); header.addStretch()
        create = QToolButton(); create.setText("+ Crear"); create.setObjectName("createButton")
        create.setToolTip("Crear una pantalla, una carpeta o un objeto de librería (símbolo o plantilla de equipo)")
        create.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(create)
        menu.addAction("Pantalla…", lambda: self.new_document(False, folder=self.current_folder()))
        menu.addAction("Carpeta de pantallas…", lambda: self.tree_new_folder(self.current_folder()))
        menu.addAction("Objeto de librería…", lambda: self.new_document(True))
        create.setMenu(menu); header.addWidget(create)
        box.addLayout(header)
        box.addWidget(self.project_label)
        self.navigation = ProjectTree(self)
        self.navigation.currentItemChanged.connect(self.select_document)
        self.navigation.setToolTip("Clic derecho para crear, renombrar, duplicar o eliminar. Arrastra para mover a una carpeta.")
        self.resource_tabs = QTabWidget()
        self.resource_tabs.addTab(self.navigation, "Proyecto")
        self.layers = QListWidget(); self.layers.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layers.itemSelectionChanged.connect(self.select_layers)
        self.layers.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.layers.customContextMenuRequested.connect(self.layer_menu)
        self.layers.setToolTip("Elementos de la pantalla abierta, del fondo al frente. Selecciona aquí los que se tapan entre sí; "
                               "clic derecho para ocultar, bloquear u ordenar.")
        self.resource_tabs.addTab(self.layers, "Elementos")
        self.resource_tabs.setTabToolTip(1, self.layers.toolTip())
        box.addWidget(self.resource_tabs, 1)
        box.addSpacing(4)
        self.toolbox_title = QToolButton();self.toolbox_title.setText('Herramientas de dibujo ▾')
        self.toolbox_title.setCheckable(True);self.toolbox_title.setChecked(True)
        box.addWidget(self.toolbox_title)
        self.toolbox = Toolbox()
        self.toolbox.itemClicked.connect(lambda item: item.data(Qt.ItemDataRole.UserRole) and self.add_element(item.data(Qt.ItemDataRole.UserRole)))
        self.tool_options=QWidget(); options=QVBoxLayout(self.tool_options);options.setContentsMargins(0,0,0,0)
        self.tool_search=QLineEdit();self.tool_search.setPlaceholderText('🔍 Buscar herramienta…');self.tool_search.setClearButtonEnabled(True)
        options.addWidget(self.tool_search);box.addWidget(self.tool_options)
        self.tool_search.textChanged.connect(self.toolbox.filter)
        def collapse_tools(checked):
            self.toolbox.setVisible(checked);self.tool_options.setVisible(checked)
            QSettings('abSCADA','Studio').setValue('toolsExpanded',checked)
        self.toolbox_title.toggled.connect(collapse_tools)
        box.addWidget(self.toolbox)
        self.workspace_row.insertWidget(0, resources)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(6, 0, 6, 0)
        center_layout.setSpacing(3)
        self.scene = CanvasScene(self)
        self.scene.selectionChanged.connect(self.show_properties)
        self.view = CanvasView(self.scene, self)
        for action in self.canvas_actions:
            self.view.addAction(action)
        center_layout.addWidget(self.view, 1)
        splitter.addWidget(center)
        self.inspector_panel = self.build_inspector()
        splitter.addWidget(self.inspector_panel)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([850, 310])
        # Only while a line / pipe / polyline is being drawn: going back to selection.
        self.select_tool_button = button("✕ Terminar dibujo (Esc)", lambda: self.view.set_drawing_tool(None))
        self.select_tool_button.hide()
        tools.insertWidget(1, self.select_tool_button)
        self.snap_action.toggled.connect(self.set_document_snap)
        order = QToolButton(); order.setText("Orden"); order.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(order)
        for title, mode in (("Traer al frente","front"),("Subir un nivel","up"),("Bajar un nivel","down"),("Enviar al fondo","back")):
            menu.addAction(title, lambda checked=False, mode=mode: self.order_elements(mode))
        menu.addSeparator()
        from .selection_editor import copy_style,paste_style
        menu.addAction('Copiar formato',lambda:copy_style(self));menu.addAction('Pegar formato',lambda:paste_style(self))
        menu.addAction('Copiar solo colores',lambda:copy_style(self,colors_only=True))
        menu.addSeparator()
        menu.addAction('Agrupar',self.group_elements);menu.addAction('Desagrupar',self.ungroup_elements)
        order.setMenu(menu); tools.insertWidget(2,order)
        align = QToolButton(); align.setText("Alinear"); align.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(align)
        for title, mode in (("Izquierda","left"),("Centro horizontal","center"),("Derecha","right"),("Arriba","top"),("Centro vertical","middle"),("Abajo","bottom")):
            menu.addAction(title, lambda checked=False, mode=mode: self.align_elements(mode))
        align.setMenu(menu); tools.insertWidget(3,align)
        self.graphics_page = page

    def build_inspector(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(268)
        scroll.setMaximumWidth(360)
        inspector = QWidget()
        inspector.setObjectName("inspector")
        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        self.selection_label = label("PROPIEDADES", "sectionTitle")
        layout.addWidget(self.selection_label)
        self.screen_properties = ScreenProperties(self)
        layout.addWidget(self.screen_properties)
        self.inspector_fields = QWidget()
        body = QVBoxLayout(self.inspector_fields)
        body.setContentsMargins(0, 0, 0, 0)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.id_field = QLineEdit()
        identity = QFormLayout()
        identity.addRow("Nombre", self.id_field)
        body.addLayout(identity)
        self.id_field.editingFinished.connect(self.auto_apply)
        geometry = QGroupBox("Posición y tamaño")
        grid = QGridLayout(geometry)
        self.property_fields = {}
        for index, (key, title) in enumerate((("x", "X"), ("y", "Y"), ("w", "Ancho"), ("h", "Alto"))):
            field = QDoubleSpinBox()
            field.setRange(1 if key in {"w", "h"} else -10000, 10000)
            field.setDecimals(1)
            field.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            self.property_fields[key] = field
            grid.addWidget(QLabel(title), index//2, index%2*2)
            grid.addWidget(field, index//2, index%2*2+1)
            field.editingFinished.connect(self.auto_apply)
        body.addWidget(geometry)
        grid.setColumnStretch(1,1);grid.setColumnStretch(3,1)
        self.drawing_properties = DrawingProperties(self)
        body.addWidget(self.drawing_properties)
        self.content_group = QGroupBox("Contenido y variable")
        form = QFormLayout(self.content_group)
        self.text_field, self.unit_field = QLineEdit(), QLineEdit()
        self.tag_field = QComboBox()
        self.tag_field.setEditable(True)
        self.decimals_field = QSpinBox()
        self.decimals_field.setRange(0, 10)
        for title, field in (("Texto", self.text_field), ("Variable", self.tag_field), ("Unidad", self.unit_field), ("Decimales", self.decimals_field)):
            form.addRow(title, field)
        for field in (self.text_field, self.unit_field, self.decimals_field):
            field.editingFinished.connect(self.auto_apply)
        self.tag_field.activated.connect(self.auto_apply)
        self.tag_field.lineEdit().editingFinished.connect(self.auto_apply)
        from .selection_editor import select_tag
        self.tag_picker_button=button('Seleccionar variable…',lambda:select_tag(self))
        form.addRow(self.tag_picker_button)
        body.addWidget(self.content_group)
        self.text_list_button = button("Configurar textos…", lambda: edit_text_list(self))
        body.addWidget(self.text_list_button)
        appearance = QGroupBox("Apariencia")
        self.appearance_group = appearance
        form = QFormLayout(appearance)
        self.font_field = QSpinBox()
        self.font_field.setRange(8, 72)
        self.font_field.editingFinished.connect(self.auto_apply)
        form.addRow("Tamaño texto", self.font_field)
        self.bold_field = QCheckBox("Negrita"); self.bold_field.clicked.connect(self.auto_apply)
        self.align_field = QComboBox(); self.align_field.addItems(["Izquierda", "Centro", "Derecha"])
        self.align_field.activated.connect(self.auto_apply)
        self.text_color_field = ColorField(self.auto_apply)
        self.border_color_field = ColorField(self.auto_apply)
        form.addRow(self.bold_field); form.addRow("Alineación",self.align_field)
        form.addRow("Texto",self.text_color_field); form.addRow("Borde",self.border_color_field)
        self.color_field = ColorField(self.auto_apply)
        form.addRow('Fondo',self.color_field)
        body.addWidget(appearance)
        self.range_group = QGroupBox("Escala")
        form = QFormLayout(self.range_group)
        self.min_field, self.max_field = QDoubleSpinBox(), QDoubleSpinBox()
        for field in (self.min_field, self.max_field):
            field.setRange(-1e9, 1e9)
            field.editingFinished.connect(self.auto_apply)
        form.addRow("Mínimo", self.min_field)
        form.addRow("Máximo", self.max_field)
        from .gauges import STYLES as GAUGE_STYLES
        self.gauge_style_field = QComboBox()
        for key, title in GAUGE_STYLES.items():
            self.gauge_style_field.addItem(title, key)
        self.gauge_style_field.activated.connect(self.auto_apply)
        self.warning_field, self.alarm_field = QLineEdit(), QLineEdit()
        for field in (self.warning_field, self.alarm_field):
            field.setPlaceholderText("Sin umbral")
            field.editingFinished.connect(self.auto_apply)
        form.addRow("Estilo", self.gauge_style_field)
        form.addRow("Aviso desde", self.warning_field)
        form.addRow("Alarma desde", self.alarm_field)
        body.addWidget(self.range_group)
        self.action_group = QGroupBox("Acción de operación")
        form = QFormLayout(self.action_group)
        self.action_field = QComboBox()
        self.action_field.addItem("Alternar marcha / paro", "toggle")
        self.action_field.addItem("Escribir valor", "set")
        self.action_field.addItem("Abrir pantalla", "screen")
        self.action_field.addItem("Abrir emergente", "popup")
        self.action_field.addItem("Abrir objeto de librería emergente", "faceplate_popup")
        self.action_field.addItem("Cerrar emergente", "close_popup")
        self.action_field.addItem("Ejecutar script", "script")
        self.action_field.addItem("Pulsador momentáneo (1 / 0)", "momentary")
        self.action_field.addItem("Escribir al pulsar y soltar", "press_release")
        self.action_field.activated.connect(self.auto_apply)
        self.value_field = QLineEdit()
        self.value_field.editingFinished.connect(self.auto_apply)
        form.addRow("Acción", self.action_field)
        form.addRow("Valor", self.value_field)
        self.press_value_field=QLineEdit();self.release_value_field=QLineEdit()
        for title,field in [('Al pulsar',self.press_value_field),('Al soltar',self.release_value_field)]:
            field.editingFinished.connect(self.auto_apply);form.addRow(title,field)
        self.screen_field = QComboBox()
        self.screen_field.activated.connect(self.auto_apply)
        form.addRow("Pantalla", self.screen_field)
        self.script_field = QComboBox()
        self.script_field.activated.connect(self.auto_apply)
        form.addRow("Script", self.script_field)
        self.popup_template_field = QComboBox()
        self.popup_template_field.activated.connect(self.auto_apply)
        form.addRow("Objeto", self.popup_template_field)
        self.popup_bindings = QWidget()
        self.popup_binding_form = QFormLayout(self.popup_bindings)
        self.popup_binding_form.setContentsMargins(0, 0, 0, 0)
        self.popup_binding_fields = {}
        form.addRow(self.popup_bindings)
        self.popup_title_field = QLineEdit()
        self.popup_title_field.setPlaceholderText("Automático: objeto · equipo")
        self.popup_title_field.editingFinished.connect(self.auto_apply)
        form.addRow("Título", self.popup_title_field)
        self.popup_modal = QCheckBox("Bloquear la ventana principal")
        self.popup_modal.clicked.connect(self.auto_apply)
        form.addRow(self.popup_modal)
        self.popup_monitor = QComboBox()
        self.popup_monitor.addItem("Junto a la ventana que la abre", 0)
        from .operation_windows import MAX_MONITORS
        for number in range(1, MAX_MONITORS + 1):
            self.popup_monitor.addItem(f"Monitor {number}", number)
        self.popup_monitor.activated.connect(self.auto_apply)
        form.addRow("Monitor", self.popup_monitor)
        self.popup_mode = QComboBox()
        from .display_editor import MODE_TITLES
        for key, title in MODE_TITLES:
            self.popup_mode.addItem(title, key)
        self.popup_mode.activated.connect(self.auto_apply)
        form.addRow("Modo", self.popup_mode)
        self.popup_on_top = QCheckBox("Siempre encima de otras aplicaciones")
        self.popup_on_top.clicked.connect(self.auto_apply)
        form.addRow(self.popup_on_top)
        self.target_container_field = QComboBox()
        self.target_container_field.activated.connect(self.auto_apply)
        form.addRow("Abrir en", self.target_container_field)
        body.insertWidget(body.indexOf(appearance),self.action_group)
        self.container_group = QGroupBox("Contenedor de pantalla")
        container_form = QFormLayout(self.container_group)
        self.container_screen_field = QComboBox()
        self.container_screen_field.activated.connect(self.auto_apply)
        container_form.addRow("Pantalla inicial", self.container_screen_field)
        body.addWidget(self.container_group)
        self.image_group = QGroupBox("Archivo de imagen")
        image_layout = QVBoxLayout(self.image_group)
        self.image_label = label("Sin archivo")
        self.image_label.setWordWrap(True)
        image_layout.addWidget(self.image_label)
        image_layout.addWidget(button("Elegir imagen…", self.choose_image))
        body.addWidget(self.image_group)
        self.binding_group = QGroupBox("Parámetros del objeto de librería")
        self.binding_form = QFormLayout(self.binding_group)
        self.binding_fields = {}
        body.addWidget(self.binding_group)
        self.viewer_group = QGroupBox("Visor")
        viewer_form = QVBoxLayout(self.viewer_group)
        self.viewer_summary = label("")
        self.viewer_summary.setWordWrap(True)
        viewer_form.addWidget(self.viewer_summary)
        self.viewer_button = button("Configurar…", self.configure_viewer)
        viewer_form.addWidget(self.viewer_button)
        body.addWidget(self.viewer_group)
        # Every field applies on its own (auto_apply): there is no «Aplicar» button.
        from .dynamic_editor import edit_dynamics
        dynamic = button('Propiedades dinámicas…', lambda: edit_dynamics(self))
        dynamic.setToolTip("Cambiar color, visibilidad, habilitación o texto según el valor de las variables")
        body.insertWidget(body.indexOf(appearance), dynamic)
        advanced = QToolButton(); advanced.setText("Avanzado"); advanced.setObjectName("linkButton")
        advanced.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        advanced_menu = QMenu(advanced)
        advanced_menu.addAction("Editar el elemento como JSON…", self.edit_selected_json)
        advanced.setMenu(advanced_menu)
        body.addWidget(advanced, 0, Qt.AlignmentFlag.AlignRight)
        from .selection_editor import CommonProperties
        self.common_properties=CommonProperties(self);self.common_properties.hide()
        layout.addWidget(self.common_properties)
        layout.addWidget(self.inspector_fields)
        layout.addStretch()

        self.inspector_fields.hide()
        # Long combo items and wide numeric ranges must not force a horizontal scrollbar
        # (fonts are wider on Linux): let those fields shrink to the panel width.
        for combo in inspector.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        for spin in inspector.findChildren(QDoubleSpinBox) + inspector.findChildren(QSpinBox):
            spin.setMinimumWidth(64)
        scroll.setWidget(inspector)
        return scroll

    def build_variables(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        tools.addWidget(button("+ Nueva variable", self.add_variable, True))
        tools.addWidget(button("Editar…", self.edit_variable_form))
        tools.addWidget(button("Duplicar…", self.duplicate_variable))
        more = QToolButton(); more.setText("Más"); more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more)
        more_menu.addAction("Expandir todas las estructuras", lambda: self.table.expandAll())
        more_menu.addAction("Contraer todas las estructuras", lambda: self.table.collapseAll())
        more_menu.addSeparator()
        more_menu.addAction("Editar como JSON (avanzado)…", self.edit_variables)
        more.setMenu(more_menu); tools.addWidget(more)
        tools.addStretch()
        # A search box, clearly apart from the creation buttons: typing here only filters the list.
        self.filter = QLineEdit()
        self.filter.setObjectName("searchField")
        self.filter.setPlaceholderText("🔍 Filtrar la lista…")
        self.filter.setToolTip("Muestra solo las variables cuyo nombre, tipo, conexión o dirección contienen este texto")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(300)
        self.filter.textChanged.connect(self.refresh_variables)
        tools.addWidget(self.filter)
        layout.addLayout(tools)
        self.filter_notice = QLabel(); self.filter_notice.setObjectName("filterNotice"); self.filter_notice.hide()
        self.filter_notice.setTextFormat(Qt.TextFormat.RichText)
        self.filter_notice.linkActivated.connect(lambda link: self.filter.clear())
        layout.addWidget(self.filter_notice)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Variable", "Tipo", "Valor inicial", "Acceso", "PLC / conexión", "Ubicación", "Enlace", "Registro"])
        self.table.setAlternatingRowColors(True)
        self.table.setIndentation(18)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.table.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.header().setStretchLastSection(False)
        self.table.header().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(6, 96)
        self.table.header().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(7, 150)
        self.table.itemDoubleClicked.connect(self.edit_variable_form)
        layout.addWidget(self.table, 1)
        self.variables_page = page

    def make_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(42)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def build_catalogs(self):
        for key, title, headers in (("types", "tipo", ["Tipo", "Campos", "Definición"]),
                                    ("connections", "conexión", ["Nombre", "Protocolo", "Equipo", "Ciclo", "Configuración", "Runtime activo"])):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(button("+ Nuevo " + title, lambda checked=False, k=key: self.edit_catalog(k, True), True))
            row.addWidget(button("Editar…", lambda checked=False, k=key: self.edit_catalog(k, False)))
            row.addWidget(button("Eliminar", lambda checked=False, k=key: self.delete_catalog(k)))
            row.addWidget(button("JSON avanzado…", lambda checked=False, k=key: self.edit_catalog_json(k)))
            layout.addLayout(row)
            table = self.make_table(headers)
            table.cellDoubleClicked.connect(lambda row, col, k=key: self.edit_catalog(k, False))
            setattr(self, key + "_table", table)
            layout.addWidget(table)
            setattr(self, key + "_page", page)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        layout.addWidget(self.log)
        self.diagnostics_page = page

    def select_document(self, item, previous=None):
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not value or value[0] not in {"section", "screens", "faceplates"}:
            return
        if value[0] == "section":
            self.navigate(value[1]); return
        from .faceplate_libraries import owner
        if value[0] == 'faceplates' and owner(self.project, value[1]):
            # Read-only objects are used, not edited: drag them onto a screen or copy them first.
            self.statusBar().showMessage("Objeto de solo lectura: arrástralo al lienzo para usarlo, o clic derecho → "
                                         "«Copiar al proyecto para modificarlo»", 8000)
            return
        self.view.set_drawing_tool(None)
        self.document_kind, self.document_name = value
        self.navigate(self.document_kind)
        self.render_scene()

    def current_folder(self):
        """Folder of the selected tree item, where «Nuevo documento» creates screens."""
        item = self.navigation.currentItem()
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if value and value[0] == "folder":
            return value[1]
        if value and value[0] == "screens" and value[1] in self.project.screens:
            return self.project.screens[value[1]].get("folder", "")
        return ""

    def document(self):
        return getattr(self.project, self.document_kind)[self.document_name]

    def open_faceplate_template(self, template):
        from .faceplate_libraries import owner
        if owner(self.project, template):
            from .library_editor import LibraryDialog
            LibraryDialog(self).exec()
            return
        self.document_kind, self.document_name = "faceplates", template
        self.navigate("faceplates")
        self.populate_navigation()
        self.render_scene()

    def render_scene(self, selected_ids=()):
        self.scene.blockSignals(True)
        self.scene.clear()
        document = self.document()
        self.scene.setSceneRect(0, 0, document["width"], document["height"])
        for element in document["elements"]:
            item = ElementItem(self, element)
            self.scene.addItem(item)
            item.setSelected(element["id"] in selected_ids)
        self.scene.blockSignals(False)
        self.refresh_layers()
        self.snap_action.blockSignals(True); self.snap_action.setChecked(document.get("snap_to_grid",True)); self.snap_action.blockSignals(False)
        startup = self.document_kind == "screens" and self.document_name == self.project.manifest["startup_screen"]
        self.document_label.setText(self.document_name + ("  ▶ pantalla de inicio" if startup else ""))
        if self.view.auto_fit:
            self.view.fit_canvas()
        self.show_properties()

    def show_properties(self):
        if not hasattr(self, "inspector_fields"):
            return
        self._syncing = True
        items = self.scene.selectedItems()
        self.inspector_panel.setVisible(True)
        self.screen_properties.setVisible(not items)
        if not items:
            self.screen_properties.refresh()
        self.sync_layer_selection()
        self.common_properties.setVisible(len(items)>1)
        if len(items)>1:self.common_properties.refresh()
        self.inspector_fields.setVisible(len(items) == 1)
        self.inspector_fields.setEnabled(len(items) == 1)
        self.selection_label.setText(("PROPIEDADES DE PANTALLA" if self.document_kind == "screens" else "PROPIEDADES DEL OBJETO DE LIBRERÍA") if not items else f"{len(items)} ELEMENTOS" if len(items) > 1 else PALETTE[items[0].element["kind"]].upper())
        if len(items)!=1:
            self._syncing = False
            return
        e = items[0].element
        self.id_field.setText(e["id"])
        for key, field in self.property_fields.items():
            field.setValue(e[key])
        self.text_field.setText(e.get("text", ""))
        self.tag_field.clear()
        from .selection_editor import available_tags
        from .dynamics import compatible
        self.tag_field.addItems(['']+[name for name,tag in available_tags(self).items() if compatible(e,tag)])

        self.tag_field.setCurrentText(e.get("tag", ""))
        self.unit_field.setText(e.get("unit", ""))
        self.decimals_field.setValue(e.get("decimals", 2))
        self.font_field.setValue(e.get("font_size", 15))
        self.bold_field.setChecked(e.get("bold", False))
        self.align_field.setCurrentIndex({"left":0,"center":1,"right":2}[e.get("text_align","center")])
        self._display_text_color = e.get("text_color", "#f8fafc" if QColor(self.resolve_color(e.get("color", "#f1f5f9"))).lightness()<110 else "#273b53")
        self.text_color_field.setText(self._display_text_color)
        self.border_color_field.setText(e.get("border_color", "#ccd7e3"))
        self.color_field.setText(e.get("color", ""))
        self.min_field.setValue(e.get("min", 0))
        self.max_field.setValue(e.get("max", 100))
        self.gauge_style_field.setCurrentIndex(max(0, self.gauge_style_field.findData(e.get("gauge_style", "dial"))))
        self.warning_field.setText(f'{e["warning"]:g}' if "warning" in e else "")
        self.alarm_field.setText(f'{e["alarm"]:g}' if "alarm" in e else "")
        for field in (self.gauge_style_field, self.warning_field, self.alarm_field):
            self.range_group.layout().setRowVisible(field, e["kind"] == "gauge")
        self.action_field.setCurrentIndex(max(0, self.action_field.findData(e.get("action", "toggle"))))
        self.screen_field.clear(); self.screen_field.addItems(list(self.project.screens))
        self.screen_field.setCurrentText(e.get("screen", self.document_name))
        self.screen_field.setEnabled(e.get("action") in {"screen", "popup"})
        opens_window = e.get("action") in {"popup", "faceplate_popup"}
        self.popup_modal.setVisible(opens_window)
        self.popup_modal.setChecked(e.get("modal", False))
        window = e.get("window", {})
        self.popup_monitor.setCurrentIndex(max(0, self.popup_monitor.findData(window.get("monitor", 0))))
        self.popup_on_top.setChecked(window.get("on_top", False))
        self.popup_mode.setCurrentIndex(max(0, self.popup_mode.findData(window.get("mode", "normal"))))
        for widget in (self.popup_monitor, self.popup_mode, self.popup_on_top):
            self.action_group.layout().setRowVisible(widget, opens_window)
        self.refresh_popup_faceplate(e)
        self.target_container_field.clear()
        self.target_container_field.addItem("Zona actual", "")
        self.target_container_field.addItem("Ventana completa", "__window__")
        from .screen_layouts import containers
        for name in sorted({c['id'] for doc in self.project.screens.values() for c in containers(doc)}):
            self.target_container_field.addItem(name, name)
        self.target_container_field.setCurrentIndex(max(0, self.target_container_field.findData(e.get('target_container', ''))))
        self.action_group.layout().setRowVisible(self.target_container_field, e.get('action') == 'screen')
        self.container_group.setVisible(e['kind'] == 'screen_container')
        self.container_screen_field.clear()
        self.container_screen_field.addItems([name for name, doc in self.project.screens.items()
            if name != self.document_name and not containers(doc)])
        self.container_screen_field.setCurrentText(e.get('screen', ''))
        self.script_field.clear(); self.script_field.addItems(list(self.project.scripts))
        self.script_field.setCurrentText(e.get('script', ''))
        self.action_group.layout().setRowVisible(self.script_field, e.get('action') == 'script')
        self.action_group.layout().setRowVisible(self.screen_field, e.get('action') in {'screen','popup'})
        self.action_group.layout().setRowVisible(self.value_field, e.get('action') == 'set')
        for key,field in [('press_value',self.press_value_field),('release_value',self.release_value_field)]:
            field.setText(str(e.get(key,'')));self.action_group.layout().setRowVisible(field,e.get('action')=='press_release')
        self.value_field.setText(str(e.get("value", "")))
        self.value_field.setEnabled(e.get("action") == "set")
        self.content_group.setVisible(e["kind"] not in {"screen_container", "faceplate", "trend", "alarm_view"} | PATH_KINDS | SHAPE_KINDS)
        self.text_list_button.setVisible(e["kind"] == "text_list")
        for field,kinds in [(self.text_field,{'text','input','button','gauge'}),(self.unit_field,{'text','input','gauge'}),(self.decimals_field,{'text','input','gauge'})]:
            self.content_group.layout().setRowVisible(field,e['kind'] in kinds)
        show_tag=e['kind'] in {'text','input','lamp','bar','gauge','text_list'} or (e['kind']=='button' and e.get('action','toggle') in {'toggle','set','momentary','press_release'})
        self.content_group.layout().setRowVisible(self.tag_field,show_tag)
        self.tag_picker_button.setVisible(show_tag)
        self.appearance_group.setVisible(e["kind"] in {"text","button","input","text_list","gauge"} | SHAPE_KINDS)
        for widget in (self.font_field,self.bold_field,self.align_field,self.text_color_field,self.border_color_field):
            visible = e["kind"] in {"text","button","input","text_list"}
            widget.setVisible(visible)
            title = self.appearance_group.layout().labelForField(widget)
            if title: title.setVisible(visible)
        self.drawing_properties.setVisible(e["kind"] in PATH_KINDS | SHAPE_KINDS)
        if e["kind"] in PATH_KINDS | SHAPE_KINDS:
            self.drawing_properties.refresh(e)
        self.viewer_group.setVisible(e["kind"] in {"trend", "alarm_view"})
        if e["kind"] == "trend":
            trend = self.project.trends.get(e.get("view"), {})
            self.viewer_group.setTitle("Gráfica")
            self.viewer_summary.setText(f"{trend.get('title', '')}\n{len(trend.get('curves', []))} curvas · "
                                        f"{len(trend.get('axes', []))} ejes · ventana {trend.get('window_seconds', 600)} s")
            self.viewer_button.setText("Configurar gráfica…")
        elif e["kind"] == "alarm_view":
            view = self.project.alarm_views.get(e.get("view"), {})
            self.viewer_group.setTitle("Visor de alarmas")
            self.viewer_summary.setText(view.get("title", ""))
            self.viewer_button.setText("Configurar visor…")
        self.range_group.setVisible(e["kind"] in {"bar", "gauge"})
        self.action_group.setVisible(e["kind"] == "button")
        self.image_group.setVisible(e["kind"] == "image")
        self.image_label.setText(e.get("source", "Sin archivo"))
        self.binding_group.setVisible(e["kind"] == "faceplate")
        while self.binding_form.count():
            entry = self.binding_form.takeAt(0)
            if entry.widget():
                entry.widget().deleteLater()
        self.binding_fields = {}
        if e["kind"] == "faceplate":
            for parameter, kind in self.project.faceplates[e["template"]].get("parameters", {}).items():
                combo = QComboBox()
                from .dynamics import parameter_writable
                needs_write=parameter_writable(self.project.faceplates[e['template']],parameter)
                combo.addItems([name for name,tag in self.project.tags().items() if tag['type']==kind and (not needs_write or tag.get('writable'))])
                combo.setCurrentText(e["bindings"][parameter])
                combo.activated.connect(self.auto_apply)
                self.binding_fields[parameter] = combo
                self.binding_form.addRow(parameter, combo)
        self._syncing = False

    def popup_binding_options(self, template, parameter, kind):
        """Variables for a faceplate pop-up; inside a faceplate also its own $parameters."""
        from .dynamics import parameter_writable
        needs_write = parameter_writable(self.project.faceplates[template], parameter)
        options = [name for name, tag in self.project.tags().items()
                   if tag["type"] == kind and (not needs_write or tag.get("writable"))]
        if self.document_kind == "faceplates":
            options = ["$" + name for name, own in self.document().get("parameters", {}).items() if own == kind] + options
        return options

    def refresh_popup_faceplate(self, e):
        visible = e.get("action") == "faceplate_popup"
        layout = self.action_group.layout()
        for widget in (self.popup_template_field, self.popup_bindings, self.popup_title_field):
            layout.setRowVisible(widget, visible)
        self.popup_template_field.clear()
        self.popup_template_field.addItems(list(self.project.faceplates))
        self.popup_template_field.setCurrentText(e.get("template", ""))
        self.popup_title_field.setText(e.get("title", ""))
        while self.popup_binding_form.count():
            entry = self.popup_binding_form.takeAt(0)
            if entry.widget():
                entry.widget().deleteLater()
        self.popup_binding_fields = {}
        template = e.get("template")
        if not visible or template not in self.project.faceplates:
            return
        for parameter, kind in self.project.faceplates[template].get("parameters", {}).items():
            combo = QComboBox()
            combo.addItems(self.popup_binding_options(template, parameter, kind))
            combo.setCurrentText(e.get("bindings", {}).get(parameter, ""))
            combo.activated.connect(self.auto_apply)
            self.popup_binding_fields[parameter] = combo
            self.popup_binding_form.addRow(parameter, combo)

    def popup_faceplate_fields(self, e, previous):
        template = self.popup_template_field.currentText()
        if template not in self.project.faceplates:
            raise ValueError("Crea primero un objeto de librería para abrirlo en una ventana")
        same = template == previous.get("template")
        bindings = {}
        for parameter, kind in self.project.faceplates[template].get("parameters", {}).items():
            combo = self.popup_binding_fields.get(parameter) if same else None
            value = combo.currentText() if combo else ""
            if not value:
                # New template: forward a parameter with the same name, else the first match.
                options = self.popup_binding_options(template, parameter, kind)
                value = "$" + parameter if "$" + parameter in options else options[0] if options else ""
            bindings[parameter] = value
        e.update(template=template, bindings=bindings)
        title = self.popup_title_field.text().strip()
        if title:
            e["title"] = title
        else:
            e.pop("title", None)
        e.pop("tag", None); e.pop("screen", None)

    def auto_apply(self, *args):
        if not self._syncing:
            self.apply_fields()

    def apply_fields(self):
        selected = self.scene.selectedItems()
        if len(selected) != 1 or self._syncing:
            return
        previous = selected[0].element
        e = copy.deepcopy(previous)
        e.update({key: field.value() for key, field in self.property_fields.items()})
        e.update(id=self.id_field.text().strip())
        if e["kind"] in {"text","button","input","text_list"}:
            e.update(text=self.text_field.text(),font_size=self.font_field.value())
            e.update(bold=self.bold_field.isChecked(),text_align=["left","center","right"][self.align_field.currentIndex()],
                text_color=self.text_color_field.text(),border_color=self.border_color_field.text())
            if not QColor(self.resolve_color(e["text_color"])).isValid() or not QColor(self.resolve_color(e["border_color"])).isValid():
                self.error("Color inválido"); self.show_properties(); return
            if "text_color" not in previous and e["text_color"] == self._display_text_color:
                e.pop("text_color")
        color = self.color_field.text().strip()
        if color and not QColor(self.resolve_color(color)).isValid():
            self.error("Color inválido; usa un valor como #147d75")
            self.show_properties()
            return
        if color:
            e["color"] = color
        else:
            e.pop("color", None)
        if e["kind"] == "faceplate":
            e["bindings"] = {p: combo.currentText() for p, combo in self.binding_fields.items()}
        else:
            if self.tag_field.currentText().strip():
                e["tag"] = self.tag_field.currentText().strip()
            else:
                e.pop("tag", None)
            if e["kind"] in {"text", "input"}:
                e.update(unit=self.unit_field.text(), decimals=self.decimals_field.value())
        if e['kind'] == 'screen_container':
            e['screen'] = self.container_screen_field.currentText()
            e.pop('tag', None)
        if e["kind"] == "bar":
            e.update(min=self.min_field.value(), max=self.max_field.value())
        if e["kind"] == "gauge":
            e.update(min=self.min_field.value(), max=self.max_field.value(), text=self.text_field.text(),
                     unit=self.unit_field.text(), decimals=self.decimals_field.value(),
                     gauge_style=self.gauge_style_field.currentData())
            for key, field in (("warning", self.warning_field), ("alarm", self.alarm_field)):
                raw = field.text().strip().replace(",", ".")
                if not raw:
                    e.pop(key, None)
                    continue
                try:
                    e[key] = float(raw)
                except ValueError:
                    self.error("Umbral inválido: escribe un número o déjalo vacío")
                    self.show_properties()
                    return
        if e["kind"] == "button":
            e["action"] = self.action_field.currentData()
            tag = e.get('tag', '')
            tags = self.project.tags()
            kind = tags[tag]['type'] if tag in tags else self.document().get('parameters', {}).get(tag.lstrip('$'))
            if e['action'] == 'toggle' and kind and kind != 'bool' and tag != previous.get('tag', ''):
                e['action'] = 'set'
            if e['action'] == 'screen':
                e['target_container'] = self.target_container_field.currentData() or ''
            else:
                e.pop('target_container', None)
            if e["action"] in {"screen", "popup"}:
                e["screen"] = self.screen_field.currentText()
                e.pop("tag", None)
            if e["action"] in {"popup", "faceplate_popup"}:
                e["modal"] = self.popup_modal.isChecked()
                window = {}
                if self.popup_monitor.currentData():
                    window["monitor"] = self.popup_monitor.currentData()
                if self.popup_mode.currentData() != "normal":
                    window["mode"] = self.popup_mode.currentData()
                if self.popup_on_top.isChecked():
                    window["on_top"] = True
                if window:
                    e["window"] = window
                else:
                    e.pop("window", None)
            else:
                e.pop("modal", None); e.pop("window", None)
            if e["action"] == "faceplate_popup":
                try:
                    self.popup_faceplate_fields(e, previous)
                except ValueError as exc:
                    self.error(exc); self.show_properties(); return
            else:
                for key in ("template", "bindings", "title"):
                    e.pop(key, None)
            if e['action'] == 'script':
                e['script'] = self.script_field.currentText()
                e.pop('tag', None); e.pop('screen', None)
            else:
                e.pop('script', None)
            if e["action"] == "close_popup":
                e.pop("tag", None)
                e.pop("screen", None)
            if e['action']=='press_release':
                from .value_editor import engineering_value
                try:
                    for key,field,default in [('press_value',self.press_value_field,True if kind=='bool' else 1),('release_value',self.release_value_field,False if kind=='bool' else 0)]:
                        raw=field.text() or ('' if kind=='string' else str(default))
                        e[key]=engineering_value(raw,kind or 'string')
                except ValueError as exc:self.error(exc);self.show_properties();return
            if e["action"] == "set":
                try:
                    tag = e.get("tag", "")
                    tags = self.project.tags()
                    kind = tags[tag]["type"] if tag in tags else self.document().get("parameters", {}).get(tag.lstrip("$"))
                    raw_value = self.value_field.text()
                    if not raw_value and previous.get("action", "toggle") != "set":
                        raw_value = {"bool": False, "int": 0, "float": 0.0, "string": ""}.get(kind, "")
                    from .value_editor import engineering_value
                    e["value"] = engineering_value(raw_value, kind or "string")
                except (ValueError, TypeError) as exc:
                    self.error(exc)
                    self.show_properties()
                    return
        if e != previous:
            index = self.document()["elements"].index(previous)
            self.mutate(lambda: self.document()["elements"].__setitem__(index, e), selected_ids=[e["id"]])

    def resolve_color(self,value):
        from .dynamics import resolve_color
        try:return resolve_color(value,self.project.manifest.get('palette',{}))
        except ValueError:return ''

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color_field.text() or "#f1f5f9"), self, "Color de fondo")
        if color.isValid():
            self.color_field.setText(color.name())
            self.apply_fields()

    def choose_image(self):
        selected = self.scene.selectedItems()
        if len(selected) != 1:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Seleccionar imagen", "", "Imágenes (*.png *.jpg *.jpeg *.bmp *.svg)")
        if filename:
            try:
                source = Path(filename).resolve()
                if not source.is_relative_to(self.project.root):
                    assets = self.project.root / "assets"
                    assets.mkdir(exist_ok=True)
                    target = assets / source.name
                    if target.exists():
                        target = assets / f"{source.stem}_{uuid.uuid4().hex[:6]}{source.suffix}"
                    shutil.copy2(source, target)
                    source = target
                e = selected[0].element
                self.mutate(lambda: e.__setitem__("source", source.relative_to(self.project.root).as_posix()))
            except OSError as exc:
                self.error(exc)

    def edit_selected_json(self):
        selected = self.scene.selectedItems()
        if len(selected) == 1:
            try:
                index = self.document()["elements"].index(selected[0].element)
                data = self.json_dialog("Propiedades avanzadas", selected[0].element)
                if data is not None:
                    self.mutate(lambda: self.document()["elements"].__setitem__(index, data), selected_ids=[data["id"]])
            except Exception as exc:
                self.error(exc)

    def editable(self):
        return True

    @property
    def dirty(self):
        return getattr(self, "_dirty", False)

    @dirty.setter
    def dirty(self, value):
        self._dirty = value
        if hasattr(self, "unsaved_label"):
            self.unsaved_label.setVisible(value)

    def mark_dirty(self):
        self.dirty = True
        self.update_runtime_difference()
        self.setWindowTitle("abSCADA Studio · " + self.project.manifest["name"] + " *")

    def error(self, exc):
        self.log.appendPlainText(str(exc))
        QMessageBox.warning(self, "Revisar configuración", str(exc))

    def record_history(self, previous):
        self.undo_stack.append(previous)
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()
        self.update_history_actions()

    def mutate(self, callback, selected_ids=None):
        previous = copy.deepcopy(self.project)
        if selected_ids is None:
            selected_ids = [item.element["id"] for item in self.scene.selectedItems()]
        try:
            callback()
            self.project.validate()
            self.record_history(previous)
            self.mark_dirty()
            self.refresh_variables()
            self.refresh_catalogs()
            self.populate_navigation()
            self.render_scene(selected_ids)
            return True
        except Exception as exc:
            self.project = previous
            self.error(exc)
            self.render_scene(selected_ids)
            return False

    def begin_interaction(self):
        self._interaction_backup = copy.deepcopy(self.project)

    def end_interaction(self):
        previous, self._interaction_backup = self._interaction_backup, None
        if previous and previous != self.project:
            self.project.validate()
            self.record_history(previous)
            self.mark_dirty()
        self.show_properties()

    def edit_graphic_document(self):
        """Ordinary screen settings; JSON remains an explicit advanced option."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Ajustes de pantalla / plantilla")
        dialog.resize(480, 400)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        dimensions = {}
        for key, title in (("width", "Ancho"), ("height", "Alto")):
            field = QSpinBox()
            field.setRange(100, 10000)
            field.setValue(int(self.document()[key]))
            dimensions[key] = field
            form.addRow(title, field)
        layout.addLayout(form)
        parameters = None
        if self.document_kind == "faceplates":
            layout.addWidget(label("PARÁMETROS DE LA PLANTILLA", "sectionTitle"))
            parameters = QTableWidget(0, 2)
            parameters.setHorizontalHeaderLabels(["Nombre", "Tipo"])
            parameters.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            def add_parameter(name="", kind="float"):
                row = parameters.rowCount()
                parameters.insertRow(row)
                parameters.setItem(row, 0, QTableWidgetItem(name))
                combo = QComboBox()
                combo.addItems(["bool", "int", "float", "string"])
                combo.setCurrentText(kind)
                parameters.setCellWidget(row, 1, combo)
            for name, kind in self.document().get("parameters", {}).items():
                add_parameter(name, kind)
            layout.addWidget(parameters)
            row = QHBoxLayout()
            row.addWidget(button("+ Parámetro", lambda: add_parameter()))
            row.addWidget(button("Eliminar", lambda: parameters.removeRow(parameters.currentRow())))
            layout.addLayout(row)
        advanced = button("Documento JSON avanzado…", lambda: (dialog.reject(), ProjectActions.edit_graphic_document(self)))
        layout.addWidget(advanced)
        self.dialog_buttons(dialog, layout)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = copy.deepcopy(self.document())
            data.update({key: field.value() for key, field in dimensions.items()})
            if parameters is not None:
                definitions = [(parameters.item(i, 0).text().strip(), parameters.cellWidget(i, 1).currentText()) for i in range(parameters.rowCount())]
                if len({name for name, kind in definitions}) != len(definitions) or any(not name for name, kind in definitions):
                    self.error("Los parámetros deben tener nombres únicos y no vacíos")
                    return
                data["parameters"] = dict(definitions)
            self.mutate(lambda: getattr(self.project, self.document_kind).__setitem__(self.document_name, data))

    def update_history_actions(self):
        self.undo_action.setEnabled(bool(self.undo_stack))
        self.redo_action.setEnabled(bool(self.redo_stack))

    def restore_history(self, source, target):
        if source:
            target.append(copy.deepcopy(self.project))
            current_project = self.project
            self.project = source.pop()
            for key in ('_disk_root','_disk_state'):
                if hasattr(current_project,key): setattr(self.project,key,getattr(current_project,key))
            if self.document_name not in getattr(self.project, self.document_kind):
                self.document_kind, self.document_name = "screens", self.project.manifest["startup_screen"]
            self.mark_dirty()
            self.populate_navigation()
            self.refresh_variables()
            self.refresh_catalogs()
            self.render_scene()
            self.update_history_actions()

    def undo(self):
        self.restore_history(self.undo_stack, self.redo_stack)

    def redo(self):
        self.restore_history(self.redo_stack, self.undo_stack)

    def add_element(self, kind="text", position=None):
        if kind not in PALETTE:
            return
        if kind in PATH_KINDS and position is None:
            self.view.set_drawing_tool(kind)
            return
        self.view.set_drawing_tool(None)
        document = self.document()
        self._insertion_counter += 1
        offset = (self._insertion_counter % 5) * 20
        position = position or QPointF(document["width"]/2 - 90 + offset, document["height"]/2 - 30 + offset)
        e = dict(id=kind + "_" + uuid.uuid4().hex[:6], kind=kind, x=round(position.x()), y=round(position.y()), w=180, h=48, text=PALETTE[kind])
        if kind in PATH_KINDS:
            points = [[position.x(),position.y()],[position.x()+180,position.y()]]
            if kind != "line":
                points += [[position.x()+180,position.y()+100]]
            self.insert_path(kind,points); return
        if kind in SHAPE_KINDS:
            e.update(w=180,h=100,color="#e9eef3",stroke_color="#334155",stroke_width=2,filled=True)
        if kind == 'screen_container':
            from .screen_layouts import containers
            candidates = [name for name, doc in self.project.screens.items()
                          if name != self.document_name and not containers(doc)]
            if self.document_kind == 'faceplates' or not candidates:
                self.error('Crea primero una pantalla de contenido para alojar en el contenedor')
                return
            e.update(screen=candidates[0], w=600, h=400)
        if kind == "text_list":
            e.update(texts=[], default_text="—", w=220)
        if kind == "lamp":
            e.update(w=48, h=48)
        if kind == "bar":
            e.update(w=80, h=180, min=0, max=100)
        if kind == "gauge":
            e.update(w=200, h=200, min=0, max=100, unit="", decimals=1, gauge_style="dial", text="")
        if kind == "image":
            e.update(w=200, h=140)
        if kind in {"trend", "alarm_view"}:
            if self.document_kind == "faceplates":
                self.error("Los visores deben colocarse en una pantalla")
                return
            from .screen_tree import new_view_id
            e.update(view=new_view_id(self.project, kind, e["id"]), w=720, h=420)
        if kind == "faceplate":
            if self.document_kind == "faceplates":
                self.error("Un objeto de librería no puede contener otros objetos de librería todavía")
                return
            from .library_browser import LibraryPicker
            picker = LibraryPicker(self, self.project)
            if picker.exec() != QDialog.DialogCode.Accepted or not picker.selected():
                return
            self.insert_library_object(picker.selected(), position)
            return
        def insert():
            if kind == "trend":
                self.project.trends[e["view"]] = dict(title="Gráfica", window_seconds=600,
                    axes=[dict(id="y", title="Valor", side="left", auto=True, min=0, max=100, visible=True)], curves=[])
            elif kind == "alarm_view":
                self.project.alarm_views[e["view"]] = dict(title="Alarmas", categories=[], min_priority=1, mode="pending", allow_ack=True)
            self.document()["elements"].append(e)
        if self.mutate(insert, selected_ids=[e["id"]]):
            self.statusBar().showMessage(f"{PALETTE[kind]} añadido", 3000)

    def insert_library_object(self, name, position=None):
        """Add an instance of a library object; its parameters are linked to variables right away."""
        if self.document_kind != "screens":
            self.error("Los objetos de librería se colocan en pantallas")
            return False
        template = self.project.faceplates[name]
        bindings = {}
        for parameter, tag_type in template.get("parameters", {}).items():
            from .dynamics import parameter_writable
            needs_write = parameter_writable(template, parameter)
            candidates = [n for n, tag in self.project.tags().items() if tag["type"] == tag_type and (not needs_write or tag.get("writable"))]
            if not candidates:
                self.error(f"Este objeto necesita una variable {tag_type} para «{parameter}»: créala primero")
                return False
            tag, ok = QInputDialog.getItem(self, "Enlazar parámetros", f"Variable para «{parameter}» ({tag_type})", candidates, 0, False)
            if not ok:
                return False
            bindings[parameter] = tag
        document = self.document()
        width, height = template["width"], template["height"]
        if position is None:
            self._insertion_counter += 1
            offset = (self._insertion_counter % 5) * 20
            position = QPointF(document["width"] / 2 - width / 2 + offset, document["height"] / 2 - height / 2 + offset)
        else:
            position = QPointF(position.x() - width / 2, position.y() - height / 2)  # dropped by its centre
        base = name.split("__", 1)[-1]
        e = dict(id=f"{base}_{uuid.uuid4().hex[:6]}", kind="faceplate", x=round(position.x()), y=round(position.y()),
                 w=width, h=height, template=name, bindings=bindings)
        if self.mutate(lambda: self.document()["elements"].append(e), selected_ids=[e["id"]]):
            from .system_library import is_system, title
            self.statusBar().showMessage(f"{title(name) if is_system(name) else name} añadido", 3000)
            return True
        return False

    def configure_viewer(self):
        selected = self.scene.selectedItems()
        if len(selected) != 1:
            return
        element = selected[0].element
        if element["kind"] == "trend":
            self.operational_editor.edit_trend(element["view"])
        elif element["kind"] == "alarm_view":
            self.operational_editor.edit_alarm_view(element["view"])

    def delete_element(self):
        ids = {i.element["id"] for i in self.scene.selectedItems()}
        if ids:
            from .screen_tree import release_viewers
            def delete():
                elements = self.document()["elements"]
                release_viewers(self.project, [e for e in elements if e["id"] in ids])
                self.document()["elements"] = [e for e in elements if e["id"] not in ids]
            self.mutate(delete, selected_ids=[])

    def duplicate_element(self):
        elements = []
        groups={}
        for item in self.scene.selectedItems():
            e = copy.deepcopy(item.element)
            e.update(id=e["kind"]+"_"+uuid.uuid4().hex[:6], x=e["x"]+20, y=e["y"]+20)
            if e.get('group'):e['group']=groups.setdefault(e['group'],'grupo_'+uuid.uuid4().hex[:6])
            elements.append(e)
        if elements:
            from .screen_tree import clone_viewers
            def add():
                clone_viewers(self.project, elements)
                self.document()["elements"].extend(elements)
            self.mutate(add, selected_ids=[e["id"] for e in elements])

    def refresh_variables(self, *args):
        role = Qt.ItemDataRole.UserRole
        selected = self.table.currentItem()
        selected_name = selected.data(0, role) if selected else None
        expanded = set()
        def visit(item):
            if item.isExpanded():
                expanded.add(item.data(0, role))
            for i in range(item.childCount()):
                visit(item.child(i))
        for i in range(self.table.topLevelItemCount()):
            visit(self.table.topLevelItem(i))
        self.table.clear()
        tags = self.project.tags()
        query = self.filter.text().casefold()
        for source in self.project.variables:
            root_name = source["name"]
            matching = []
            for name, tag in tags.items():
                if name != root_name and not name.startswith(root_name + "."):
                    continue
                binding = tag.get("binding", {})
                searchable = f"{name} {source['type']} {tag['type']} {tag['initial']} {binding.get('connection', '')} {binding.get('address', '')}"
                if query in searchable.casefold():
                    matching.append((name, tag))
            if not matching:
                continue
            groups = {}
            if source["type"] not in PRIMITIVES:
                root = QTreeWidgetItem([root_name, source["type"], f"{len(matching)} campos", "Por campo", "", ""])
                root.setData(0, role, root_name)
                root.setSizeHint(0, QSize(0, 38))
                self.table.addTopLevelItem(root)
                root.setExpanded(bool(query) or root_name in expanded)
                groups[root_name] = root
                self.table.setItemWidget(root, 6, button("Campos", lambda checked=False, item=root: item.setExpanded(not item.isExpanded())))
                if selected_name == root_name:
                    self.table.setCurrentItem(root)
            for name, tag in matching:
                binding = tag.get("binding", {})
                structured = name != root_name
                parts = name.split(".")
                parent = None
                group_type = source["type"]
                if structured:
                    parent = groups[root_name]
                    for depth, field in enumerate(parts[1:-1], start=1):
                        path = ".".join(parts[:depth+1])
                        group_type = self.project.types[group_type][field]
                        if path not in groups:
                            group = QTreeWidgetItem([field, group_type, "Estructura", "Por campo", "", ""])
                            group.setData(0, role, path)
                            group.setSizeHint(0, QSize(0, 38))
                            parent.addChild(group)
                            group.setExpanded(bool(query) or path in expanded)
                            groups[path] = group
                        parent = groups[path]
                item = QTreeWidgetItem([parts[-1] if structured else name, tag["type"], str(tag["initial"]), "Lectura / escritura" if tag.get("writable") else "Solo lectura", binding.get("connection", "Local"), binding_summary(binding, self.project.connections, tag["type"])])
                item.setData(0, role, name)
                item.setSizeHint(0, QSize(0, 38))
                item.setToolTip(0, name)
                item.setToolTip(5, "El DB y el desplazamiento se indican en esta dirección")
                if parent:
                    parent.addChild(item)
                else:
                    self.table.addTopLevelItem(item)
                self.table.setItemWidget(item, 6, button("Enlace…", lambda checked=False, n=name: self.tag_form(n)))
                from . import recording
                record = QComboBox()
                record.addItem("Ninguno", "")
                for file in recording.files(self.project):
                    record.addItem(file["name"], file["id"])
                record.setCurrentIndex(max(0, record.findData(recording.assignment(self.project, name))))
                record.currentIndexChanged.connect(lambda index, n=name, combo=record:
                    self.mutate(lambda: recording.assign(self.project, n, combo.currentData())))
                self.table.setItemWidget(item, 7, record)
                if name == selected_name:
                    self.table.setCurrentItem(item)
        shown = self.table.topLevelItemCount()
        total = len(self.project.variables)
        self.filter_notice.setVisible(bool(query))
        if query:
            self.filter_notice.setText(f"Filtro «{self.filter.text()}»: se muestran {shown} de {total} variables · "
                                       f"<a href='clear'>Quitar el filtro</a>")

    def fill_table(self, table, rows):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                table.setItem(i, j, item)

    def refresh_catalogs(self):
        if hasattr(self, "automation_editor"):
            self.automation_editor.refresh()
        if hasattr(self, "operational_editor"):
            self.operational_editor.refresh()
        if hasattr(self, "types_table"):
            self.fill_table(self.types_table, [[name, len(fields), " · ".join(f"{k}: {v}" for k, v in fields.items())] for name, fields in self.project.types.items()])
            self.fill_table(self.connections_table, [[c["id"], definition(c["protocol"]).label, c.get("host", ""), f"{c.get('poll_ms', 250)} ms", " · ".join(f"{f.label}: {c.get(f.key, f.default)}" for f in definition(c["protocol"]).connection_fields if f.key != "host")] for c in self.project.connections])

    def update_connection_status(self):
        if self.active_section!='connections':return
        live=self.runtime_window
        statuses=live.runtime.status() if live else {}
        for row,c in enumerate(self.project.connections):
            if not live:text='Detenido'
            else:
                source=next((r for r in live.project.connections if r['id']==c['id']),None)
                text=statuses.get(c['id'],'No incluida en esta ejecución')
                if source is not None and source!=c:text='Configuración distinta · '+text
            self.connections_table.setItem(row,5,QTableWidgetItem(text))

    def add_variable(self):
        before = {v["name"] for v in self.project.variables}
        self.variable_form(None)
        created = [v["name"] for v in self.project.variables if v["name"] not in before]
        if created:
            # A new variable must always be visible, even if the list was filtered.
            self.filter.clear()
            for item in self.table.findItems(created[0], Qt.MatchFlag.MatchExactly, 0):
                self.table.setCurrentItem(item)

    def edit_variable_form(self, *args):
        item = self.table.currentItem()
        if item:
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name in self.project.tags():
                self.tag_form(name)
            else:
                root=name.split(".")[0]
                self.variable_form(next(i for i,v in enumerate(self.project.variables) if v["name"]==root))

    def dialog_buttons(self, dialog, layout):
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Aceptar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

    def edit_catalog_json(self, key):
        try:
            data = self.json_dialog("Definiciones avanzadas", getattr(self.project, key))
            if data is not None:
                self.mutate(lambda: setattr(self.project, key, data))
        except Exception as exc:
            self.error(exc)

    def edit_catalog(self, key, new):
        table = getattr(self, key + "_table")
        item = table.item(table.currentRow(), 0)
        if new or item:
            (self.connection_form if key == "connections" else self.type_form)(None if new else item.text())

    def delete_catalog(self, key):
        table = getattr(self, key + "_table")
        item = table.item(table.currentRow(), 0)
        if item:
            name = item.text()
            if key == "types":
                self.mutate(lambda: self.project.types.pop(name))
            else:
                self.mutate(lambda: self.project.connections.__setitem__(slice(None), [c for c in self.project.connections if c["id"] != name]))

    def connection_form(self, name):
        previous = next((copy.deepcopy(c) for c in self.project.connections if c["id"] == name), dict(id="", protocol="s7", poll_ms=250))
        dialog = QDialog(self)
        dialog.setWindowTitle("Conexión de adquisición")
        dialog.resize(440, 420)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        identifier = QLineEdit(previous["id"])
        identifier.setReadOnly(name is not None)
        protocol = QComboBox()
        for key, factory in REGISTRY.items():
            protocol.addItem(factory.definition.label, key)
        protocol.setCurrentIndex(max(0, protocol.findData(previous["protocol"])))
        cycle = QSpinBox()
        cycle.setObjectName("connectionCycle")
        cycle.setRange(50, 60000)
        cycle.setValue(previous.get("poll_ms", 250))
        for title, widget in (("Nombre", identifier), ("Protocolo", protocol), ("Ciclo (ms)", cycle)):
            form.addRow(title, widget)
        layout.addLayout(form)
        drafts = {previous["protocol"]: previous}
        active = None
        fields = None
        def state():
            nonlocal active, fields
            if fields:
                drafts[active] = fields.values()
                layout.removeWidget(fields)
                fields.setParent(None)
                fields.deleteLater()
            active = protocol.currentData()
            fields = ProtocolForm(definition(active).connection_fields, drafts.get(active, {}))
            layout.insertWidget(1, fields)
            secured.setVisible(any(f.key == "username" for f in definition(active).connection_fields))
        from .security_editor import set_connection_password, certificates_dialog
        secured = QWidget(); secured_row = QHBoxLayout(secured); secured_row.setContentsMargins(0, 0, 0, 0)
        for title, callback in (("Contraseña…", lambda: set_connection_password(dialog, self.project.root, identifier.text().strip())),
                                ("Certificados…", lambda: certificates_dialog(self))):
            secured_button = QPushButton(title); secured_button.clicked.connect(callback); secured_row.addWidget(secured_button)
        secured_row.addStretch()
        layout.addWidget(secured)
        protocol.currentIndexChanged.connect(state)
        state()
        def current_data():
            return dict(id=identifier.text().strip(), protocol=protocol.currentData(), poll_ms=cycle.value(), **fields.values())
        def validate():
            from .value_editor import FieldError
            if not identifier.text().strip() or (name is None and any(c['id']==identifier.text().strip() for c in self.project.connections)):
                raise FieldError('El nombre de la conexión debe ser único y no vacío', identifier)
            candidate=copy.deepcopy(self.project)
            if name is None: candidate.connections.append(current_data())
            else: candidate.connections[next(i for i,c in enumerate(candidate.connections) if c['id']==name)]=current_data()
            candidate.validate()
        dialog.validator=validate
        from .connection_diagnostics import add_diagnostic
        add_diagnostic(dialog,layout,lambda:(current_data(),None,None,False),self)
        self.dialog_buttons(dialog, layout)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dict(id=identifier.text().strip(), protocol=protocol.currentData(),
                        poll_ms=cycle.value(), **fields.values())
            if name is None:
                self.mutate(lambda: self.project.connections.append(data))
            else:
                index = next(i for i, c in enumerate(self.project.connections) if c["id"] == name)
                self.mutate(lambda: self.project.connections.__setitem__(index, data))

    def type_form(self, name):
        dialog = QDialog(self)
        dialog.setWindowTitle("Estructura de datos")
        dialog.resize(540, 480)
        layout = QVBoxLayout(dialog)
        identifier = QLineEdit(name or "")
        identifier.setPlaceholderText("Nombre del tipo, por ejemplo Motor")
        identifier.setReadOnly(name is not None)
        layout.addWidget(identifier)
        fields = QTableWidget(0, 2)
        fields.setHorizontalHeaderLabels(["Campo", "Tipo"])
        fields.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        def add_field(field="", kind="float"):
            row = fields.rowCount()
            fields.insertRow(row)
            fields.setItem(row, 0, QTableWidgetItem(field))
            combo = QComboBox()
            combo.addItems(["bool", "int", "float", "string"] + [n for n in self.project.types if n != name])
            combo.setCurrentText(kind)
            fields.setCellWidget(row, 1, combo)
        for field, kind in self.project.types.get(name, {}).items():
            add_field(field, kind)
        layout.addWidget(fields)
        row = QHBoxLayout()
        row.addWidget(button("+ Campo", lambda: add_field()))
        row.addWidget(button("Eliminar campo", lambda: fields.removeRow(fields.currentRow())))
        layout.addLayout(row)
        def validate():
            definitions=[(fields.item(i,0).text().strip(),fields.cellWidget(i,1).currentText()) for i in range(fields.rowCount())]
            from .value_editor import FieldError
            if len({field for field,kind in definitions}) != len(definitions) or not identifier.text().strip() or (name is None and identifier.text().strip() in self.project.types):
                raise FieldError('El nombre del tipo y sus campos deben ser únicos y no vacíos',identifier)
            candidate=copy.deepcopy(self.project); candidate.types[identifier.text().strip()]=dict(definitions); candidate.validate()
        dialog.validator=validate
        self.dialog_buttons(dialog, layout)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            definitions = [(fields.item(i, 0).text().strip(), fields.cellWidget(i, 1).currentText()) for i in range(fields.rowCount())]
            new_name = identifier.text().strip()
            if len({field for field, kind in definitions}) != len(definitions) or (name is None and new_name in self.project.types):
                self.error("El nombre del tipo y sus campos deben ser únicos")
                return
            self.mutate(lambda: self.project.types.__setitem__(new_name, dict(definitions)))

    def start_runtime(self):
        if self.runtime_window:
            self.runtime_window.showNormal()
            self.runtime_window.raise_()
            self.runtime_window.activateWindow()
            return
        runtime = None
        try:
            self.project.validate()
            screen = self.document_name if self.document_kind == "screens" else self.project.manifest["startup_screen"]
            runtime = RuntimeWindow(self.project, screen)
            runtime.closed.connect(self.runtime_closed)
            runtime.diagnostic.connect(self.log.appendPlainText)
            runtime.start()
            self.runtime_window = runtime
            self.update_runtime_difference()
            runtime.show_operation()
            self.run_button.setText("Mostrar runtime")
            self.stop_button.show()
            self.log.appendPlainText("Runtime iniciado")
        except Exception as exc:
            if runtime is not None:
                runtime.close()
            self.error(exc)

    def runtime_closed(self):
        self.runtime_window = None
        self.update_runtime_difference()
        self.run_button.setText("▶  Abrir runtime")
        self.stop_button.hide()
        self.log.appendPlainText("Runtime detenido")

    def stop_runtime(self):
        return self.runtime_window.close() if self.runtime_window else True

    def refresh(self):
        if self.runtime_window:
            self.runtime_window.refresh()

    def closeEvent(self, event):
        if self.maybe_save() and self.stop_runtime():
            settings=QSettings('abSCADA','Studio');settings.setValue('graphicsSplitter',self.graphics_splitter.saveState())
            event.accept()
        else:
            event.ignore()
