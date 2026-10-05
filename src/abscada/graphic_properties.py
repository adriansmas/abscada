"""Contextual inspectors for documents and editable vector drawings."""
import copy
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout,
    QGroupBox, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QColorDialog, QTableWidget, QTableWidgetItem, QHeaderView, QMenu,QToolButton)
from .drawing import PATH_KINDS, SHAPE_KINDS, world_points, set_points


class ColorField(QWidget):
    def __init__(self, callback):
        super().__init__()
        row = QHBoxLayout(self); row.setContentsMargins(0,0,0,0)
        self.input = QLineEdit(); self.input.editingFinished.connect(callback)
        self.input.textChanged.connect(self.update_swatch)
        self.input.setPlaceholderText('#RRGGBB o @paleta')
        self.swatch = QPushButton(); self.swatch.setFixedWidth(28)
        self.palette_button=QToolButton();self.palette_button.setArrowType(Qt.ArrowType.DownArrow);self.palette_button.setFixedWidth(22)
        row.addWidget(self.input); row.addWidget(self.swatch);row.addWidget(self.palette_button)
        def palette():
            menu=QMenu(self)
            for name,value in self.project_palette().items():
                menu.addAction(f'{name} · {value}',lambda checked=False,n=name:(self.setText('@'+n),callback()))
            recent=QSettings('abSCADA','Studio').value('recentColors',[]) or []
            if recent:menu.addSeparator()
            for value in recent:menu.addAction(value,lambda checked=False,v=value:(self.setText(v),callback()))
            menu.exec(self.palette_button.mapToGlobal(self.palette_button.rect().bottomLeft()))
        self.palette_button.clicked.connect(palette)
        def choose():
            from .dynamics import resolve_color
            try: current=resolve_color(self.input.text(),self.project_palette())
            except ValueError: current='#ffffff'
            color = QColorDialog.getColor(QColor(current), self, 'Color exacto · HEX / RGB')
            if color.isValid():
                value=color.name();self.setText(value)
                settings=QSettings('abSCADA','Studio');recent=settings.value('recentColors',[]) or []
                settings.setValue('recentColors',([value]+[v for v in recent if v!=value])[:12]);callback()
        self.swatch.clicked.connect(choose)

    def setText(self, value):
        self.input.setText(value)
        self.update_swatch()

    def project_palette(self):
        node=self.parent()
        while node:
            if hasattr(node,'project'):return node.project.manifest.get('palette',{})
            node=node.parent()
        return {}

    def update_swatch(self):
        from .dynamics import resolve_color
        try:value=resolve_color(self.input.text(),self.project_palette())
        except ValueError:value=''
        color=QColor(value)
        self.swatch.setStyleSheet(f'background: {color.name()};' if color.isValid() else '')
        self.input.setToolTip(('Vinculado a paleta · ' if self.input.text().startswith('@') else 'Color local · ')+
            (f'{color.name()} · RGB {color.red()}, {color.green()}, {color.blue()}' if color.isValid() else 'Sin color'))

    def showEvent(self,event):
        self.update_swatch();super().showEvent(event)

    def text(self):
        return self.input.text().strip()


class ScreenProperties(QWidget):
    def __init__(self, host):
        super().__init__(); self.host = host; self.syncing = False
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        general = QGroupBox("Pantalla"); form = QFormLayout(general)
        self.name = QLineEdit(); self.name.setReadOnly(True)
        self.title = QLineEdit(); self.title.editingFinished.connect(self.apply)
        form.addRow("Documento", self.name); form.addRow("Título", self.title)
        self.startup = QCheckBox("Pantalla inicial")
        self.startup.clicked.connect(self.apply); form.addRow(self.startup)
        layout.addWidget(general)
        size = QGroupBox("Lienzo"); form = QFormLayout(size)
        self.width, self.height = QSpinBox(), QSpinBox()
        for label, field in (("Ancho (px)", self.width), ("Alto (px)", self.height)):
            field.setRange(1,10000); field.editingFinished.connect(self.apply); form.addRow(label,field)
        self.background = ColorField(self.apply); form.addRow("Fondo", self.background)
        layout.addWidget(size)
        grid = QGroupBox("Cuadrícula"); form = QFormLayout(grid)
        self.grid_size = QSpinBox(); self.grid_size.setRange(1,200)
        self.grid_size.editingFinished.connect(self.apply)
        self.show_grid = QCheckBox("Mostrar cuadrícula"); self.show_grid.clicked.connect(self.apply)
        self.snap = QCheckBox("Ajustar a cuadrícula"); self.snap.clicked.connect(self.apply)
        form.addRow("Paso (px)", self.grid_size); form.addRow(self.show_grid); form.addRow(self.snap)
        layout.addWidget(grid)
        advanced = QPushButton("Ajustes avanzados…"); advanced.clicked.connect(host.edit_graphic_document)
        layout.addWidget(advanced)
        self.events_button = QPushButton("Al abrir pantalla…")
        self.events_button.clicked.connect(self.edit_events)
        layout.addWidget(self.events_button)

    def edit_events(self):
        from .engineering import RecordDialog
        from PySide6.QtWidgets import QDialog
        dialog = RecordDialog(self, 'Apertura de pantalla', [
            ('on_open', 'Scripts', 'multi', [], [(n,n) for n in self.host.project.scripts])], self.host.document())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.host.mutate(lambda: self.host.document().update(dialog.data()))

    def refresh(self):
        self.syncing = True
        doc = self.host.document()
        self.name.setText(self.host.document_name); self.title.setText(doc.get("title", ""))
        self.width.setValue(int(doc["width"])); self.height.setValue(int(doc["height"]))
        self.background.setText(doc.get("background", "#ffffff"))
        self.grid_size.setValue(doc.get("grid_size",10))
        self.show_grid.setChecked(doc.get("show_grid",True)); self.snap.setChecked(doc.get("snap_to_grid",True))
        is_screen = self.host.document_kind == "screens"
        self.startup.setVisible(is_screen)
        self.events_button.setVisible(is_screen)
        current = self.host.project.manifest["startup_screen"] == self.host.document_name and is_screen
        self.startup.setChecked(current); self.startup.setEnabled(not current)
        self.syncing = False

    def apply(self):
        if self.syncing:
            return
        update = dict(title=self.title.text(), width=self.width.value(), height=self.height.value(),
            background=self.background.text(), grid_size=self.grid_size.value(),
            show_grid=self.show_grid.isChecked(), snap_to_grid=self.snap.isChecked())
        def save():
            self.host.document().update(update)
            if self.startup.isChecked() and self.host.document_kind == "screens":
                self.host.project.manifest["startup_screen"] = self.host.document_name
        if any(self.host.document().get(k) != v for k,v in update.items()) or (self.startup.isChecked() and self.host.project.manifest["startup_screen"] != self.host.document_name):
            self.host.mutate(save, selected_ids=[])


class DrawingProperties(QGroupBox):
    def __init__(self, host):
        super().__init__("Trazo"); self.host = host; self.syncing = False
        layout = QVBoxLayout(self); form = QFormLayout(); self.form=form
        self.color = ColorField(self.apply)
        self.width = QDoubleSpinBox(); self.width.setRange(1,100); self.width.setDecimals(1); self.width.editingFinished.connect(self.apply)
        self.style = QComboBox()
        for title, key in (("Continuo","solid"),("Discontinuo","dash"),("Punteado","dot")):
            self.style.addItem(title,key)
        self.style.activated.connect(self.apply)
        self.arrows = QComboBox()
        for title, key in (("Sin flechas","none"),("Al inicio","start"),("Al final","end"),("Ambos","both")):
            self.arrows.addItem(title,key)
        self.arrows.activated.connect(self.apply)
        self.filled = QCheckBox("Relleno"); self.filled.clicked.connect(self.apply)
        for title, field in (("Color", self.color),("Grosor",self.width),("Estilo",self.style),("Extremos",self.arrows)):
            form.addRow(title,field)
        form.addRow(self.filled); layout.addLayout(form)
        self.points = QTableWidget(0,2); self.points.setHorizontalHeaderLabels(["X", "Y"])
        self.points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.points.setMaximumHeight(160); self.points.itemChanged.connect(self.apply_points)
        layout.addWidget(self.points)
        self.point_buttons = QWidget(); row = QHBoxLayout(self.point_buttons); row.setContentsMargins(0,0,0,0)
        for text, callback in (("+ Punto",self.add_point),("− Punto",self.remove_point),("Invertir",self.reverse)):
            button = QPushButton(text); button.clicked.connect(callback); row.addWidget(button)
        layout.addWidget(self.point_buttons)

    def selected(self):
        items = self.host.scene.selectedItems()
        return items[0].element if len(items)==1 else None

    def refresh(self, element):
        self.syncing = True
        self.color.setText(element.get("stroke_color", "#75879a" if element["kind"] == "pipe" else "#334155"))
        self.width.setValue(element.get("stroke_width",12 if element["kind"]=="pipe" else 2))
        self.style.setCurrentIndex(self.style.findData(element.get("stroke_style","solid")))
        self.arrows.setCurrentIndex(self.arrows.findData(element.get("arrows","none")))
        self.filled.setChecked(element.get("filled", True)); self.filled.setVisible(element["kind"] in SHAPE_KINDS)
        path = element["kind"] in PATH_KINDS
        self.form.setRowVisible(self.arrows,path)
        self.points.setVisible(path); self.point_buttons.setVisible(path)
        self.points.setRowCount(len(element.get("points", [])))
        if path:
            for row, point in enumerate(world_points(element)):
                for col, val in enumerate(point):
                    self.points.setItem(row,col,QTableWidgetItem(f"{val:.1f}"))
        self.syncing = False

    def apply(self, *args):
        element = self.selected()
        if self.syncing or not element:
            return
        self.host.mutate(lambda: element.update(stroke_color=self.color.text(), stroke_width=self.width.value(),
            stroke_style=self.style.currentData(), arrows=self.arrows.currentData(), filled=self.filled.isChecked()))

    def apply_points(self, *args):
        element = self.selected()
        if self.syncing or not element or element["kind"] not in PATH_KINDS:
            return
        try:
            points = [[float(self.points.item(r,c).text()) for c in range(2)] for r in range(self.points.rowCount())]
            self.host.mutate(lambda: set_points(element, points))
        except (ValueError, AttributeError) as exc:
            self.host.error("Coordenadas inválidas"); self.refresh(element)

    def add_point(self):
        element = self.selected()
        if not element or element["kind"] not in {"pipe","polyline"}:
            return
        points = world_points(element); index = max(0,min(self.points.currentRow(),len(points)-2))
        points.insert(index+1, [(a+b)/2 for a,b in zip(points[index],points[index+1])])
        self.host.mutate(lambda: set_points(element,points))

    def remove_point(self):
        element = self.selected()
        if element and element["kind"] in PATH_KINDS and len(element["points"])>2 and self.points.currentRow()>=0:
            points = world_points(element); points.pop(self.points.currentRow())
            self.host.mutate(lambda: set_points(element,points))

    def reverse(self):
        element = self.selected()
        if element and element["kind"] in PATH_KINDS:
            self.host.mutate(lambda: element["points"].reverse())
