"""Contextual inspectors for documents and editable vector drawings."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout,
    QGroupBox, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QColorDialog, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QMessageBox)
from .drawing import PATH_KINDS, SHAPE_KINDS, world_points, set_points
from .i18n import tr


class ColorField(QWidget):
    def __init__(self, callback):
        super().__init__()
        row = QHBoxLayout(self); row.setContentsMargins(0,0,0,0)
        self.input = QLineEdit(); self.input.editingFinished.connect(callback)
        self.input.textChanged.connect(self.update_swatch)
        self.input.setPlaceholderText('#RRGGBB / #AARRGGBB')
        self.swatch = QPushButton(); self.swatch.setFixedWidth(28)
        row.addWidget(self.input); row.addWidget(self.swatch)
        def choose():
            current=self.input.text() or '#ffffff'
            color = QColorDialog.getColor(QColor(current), self, tr('Color exacto · HEX / RGB'), QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if color.isValid():
                value=color.name(QColor.NameFormat.HexArgb) if color.alpha()<255 else color.name()
                self.setText(value);callback()
        self.swatch.clicked.connect(choose)

    def setText(self, value):
        self.input.setText(value)
        self.update_swatch()

    def update_swatch(self):
        color=QColor(self.input.text())
        self.swatch.setStyleSheet(f'background: {color.name()};' if color.isValid() else '')
        self.input.setToolTip(f'{self.input.text()} · RGB {color.red()}, {color.green()}, {color.blue()}' if color.isValid() else tr('Sin color'))

    def showEvent(self,event):
        self.update_swatch();super().showEvent(event)

    def text(self):
        return self.input.text().strip()


class ScreenProperties(QWidget):
    def __init__(self, host):
        super().__init__(); self.host = host; self.syncing = False
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        general = QGroupBox(tr("Pantalla")); form = QFormLayout(general)
        self.name = QLineEdit(); self.name.setReadOnly(True)
        from .project_text_editor import ProjectTextField
        self.title = ProjectTextField(host); self.title.editingFinished.connect(self.apply)
        form.addRow(tr("Documento"), self.name); form.addRow(tr("Título"), self.title)
        # The start screen is chosen in the project tree (right click) or in «Ajustes del proyecto».
        self.startup = QLabel(tr("▶ Pantalla de inicio del runtime")); self.startup.setObjectName("muted"); form.addRow(self.startup)
        layout.addWidget(general)
        size = QGroupBox(tr("Lienzo")); form = QFormLayout(size)
        self.width, self.height = QSpinBox(), QSpinBox()
        for label, field in ((tr("Ancho (px)"), self.width), (tr("Alto (px)"), self.height)):
            field.setRange(1,10000); field.editingFinished.connect(self.apply); form.addRow(label,field)
        self.background = ColorField(self.apply); form.addRow(tr("Fondo"), self.background)
        layout.addWidget(size)
        grid = QGroupBox(tr("Cuadrícula")); form = QFormLayout(grid)
        self.grid_size = QSpinBox(); self.grid_size.setRange(1,200)
        self.grid_size.editingFinished.connect(self.apply)
        self.show_grid = QCheckBox(tr("Mostrar cuadrícula")); self.show_grid.clicked.connect(self.apply)
        # «Ajustar a cuadrícula» is in the bar above the canvas.
        form.addRow(tr("Paso (px)"), self.grid_size); form.addRow(self.show_grid)
        layout.addWidget(grid)
        advanced = QPushButton(tr("Ajustes avanzados…")); advanced.clicked.connect(host.edit_graphic_document)
        layout.addWidget(advanced)
        self.events_button = QPushButton(tr("Scripts al abrir la pantalla…"))
        self.events_button.clicked.connect(self.edit_events)
        layout.addWidget(self.events_button)

    def edit_events(self):
        """Scripts that run every time this screen is shown in the runtime."""
        from .engineering import RecordDialog
        from PySide6.QtWidgets import QDialog, QLabel
        project = self.host.project
        if not project.scripts:
            box = QMessageBox(self.host)
            box.setWindowTitle(tr('Scripts al abrir la pantalla'))
            box.setText(tr('Aquí eliges qué scripts se ejecutan cada vez que se abre esta pantalla en el runtime. '
                           'Todavía no hay ningún script en el proyecto: créalo primero en la sección «Scripts».'))
            go = box.addButton(tr('Ir a Scripts'), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is go:
                self.host.navigate('automation')
            return
        dialog = RecordDialog(self, tr('Scripts al abrir la pantalla'), [
            ('on_open', tr('Scripts'), 'multi', [], [(n,n) for n in project.scripts])], self.host.document())
        note = QLabel(tr('Marca los scripts que deben ejecutarse al abrir esta pantalla (también cuando se muestra dentro de un '
                         'contenedor). Se ejecutan por el orden de esta lista.'))
        note.setWordWrap(True); note.setObjectName('muted')
        dialog.layout().insertWidget(0, note)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.host.mutate(lambda: self.host.document().update(dialog.data()))

    def refresh(self):
        self.syncing = True
        doc = self.host.document()
        self.name.setText(self.host.document_name); self.title.set_value(doc.get("title", ""))
        self.width.setValue(int(doc["width"])); self.height.setValue(int(doc["height"]))
        self.background.setText(doc.get("background", "#ffffff"))
        self.grid_size.setValue(doc.get("grid_size",10))
        self.show_grid.setChecked(doc.get("show_grid",True))
        is_screen = self.host.document_kind == "screens"
        self.events_button.setVisible(is_screen)
        count = len(doc.get("on_open", []))
        self.events_button.setText(tr("Scripts al abrir la pantalla ({count})…", count=count) if count else tr("Scripts al abrir la pantalla…"))
        self.startup.setVisible(is_screen and self.host.project.manifest["startup_screen"] == self.host.document_name)
        self.syncing = False

    def apply(self):
        if self.syncing:
            return
        update = dict(title=self.title.translated_value(), width=self.width.value(), height=self.height.value(),
            background=self.background.text(), grid_size=self.grid_size.value(),
            show_grid=self.show_grid.isChecked())
        if any(self.host.document().get(k) != v for k,v in update.items()):
            self.host.mutate(lambda: self.host.document().update(update), selected_ids=[])


class DrawingProperties(QGroupBox):
    def __init__(self, host):
        super().__init__(tr("Trazo")); self.host = host; self.syncing = False
        layout = QVBoxLayout(self); form = QFormLayout(); self.form=form
        self.color = ColorField(self.apply)
        self.width = QDoubleSpinBox(); self.width.setRange(1,100); self.width.setDecimals(1); self.width.editingFinished.connect(self.apply)
        self.style = QComboBox()
        for title, key in ((tr("Continuo"),"solid"),(tr("Discontinuo"),"dash"),(tr("Punteado"),"dot")):
            self.style.addItem(title,key)
        self.style.activated.connect(self.apply)
        self.arrows = QComboBox()
        for title, key in ((tr("Sin flechas"),"none"),(tr("Al inicio"),"start"),(tr("Al final"),"end"),(tr("Ambos"),"both")):
            self.arrows.addItem(title,key)
        self.arrows.activated.connect(self.apply)
        self.filled = QCheckBox(tr("Relleno")); self.filled.clicked.connect(self.apply)
        for title, field in ((tr("Color"), self.color),(tr("Grosor"),self.width),(tr("Estilo"),self.style),(tr("Extremos"),self.arrows)):
            form.addRow(title,field)
        form.addRow(self.filled); layout.addLayout(form)
        self.points = QTableWidget(0,2); self.points.setHorizontalHeaderLabels([tr("X"), tr("Y")])
        self.points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.points.setMaximumHeight(160); self.points.itemChanged.connect(self.apply_points)
        layout.addWidget(self.points)
        self.point_buttons = QWidget(); row = QHBoxLayout(self.point_buttons); row.setContentsMargins(0,0,0,0)
        for text, callback in ((tr("+ Punto"),self.add_point),("− Punto",self.remove_point),(tr("Invertir"),self.reverse)):
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
            self.host.error(tr("Coordenadas inválidas")); self.refresh(element)

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
