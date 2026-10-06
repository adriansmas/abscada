"""Operation windows: main window (monitor, mode, scaling) and start-up windows per monitor.

Shown as the «Operación» tab of the project settings dialog.
"""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QComboBox, QCheckBox,
                               QTableWidget, QHeaderView, QPushButton, QLabel, QWidget)
from .operation_windows import MAX_MONITORS, MAIN_MODE, settings_key

MODE_TITLES = [("normal", "Ventana"), ("maximized", "Maximizada"), ("fullscreen", "Pantalla completa")]
SCALE_TITLES = [("fit", "Ajustar a la ventana manteniendo la proporción"),
                ("stretch", "Rellenar toda la ventana (puede deformar)"),
                ("none", "Tamaño real (100 %, con barras de desplazamiento)")]


def monitor_field(value, automatic):
    field = QComboBox()
    field.addItem(automatic, 0)
    for number in range(1, MAX_MONITORS + 1):
        field.addItem(f"Monitor {number}", number)
    field.setCurrentIndex(max(0, field.findData(value or 0)))
    return field


def choice_field(options, value):
    field = QComboBox()
    for key, title in options:
        field.addItem(title, key)
    field.setCurrentIndex(max(0, field.findData(value)))
    return field


def mode_field(value, default="normal"):
    return choice_field(MODE_TITLES, value or default)


def placement(monitor, mode, default_mode="normal"):
    result = {}
    if monitor.currentData():
        result["monitor"] = monitor.currentData()
    if mode.currentData() != default_mode:
        result["mode"] = mode.currentData()
    return result


def detected_monitors():
    from .runtime_window import monitors
    rows = [f"Monitor {i}: {s.geometry().width()} × {s.geometry().height()}" for i, s in enumerate(monitors(), 1)]
    return "Este equipo: " + ("; ".join(rows) or "sin monitores detectados") + \
        ". La numeración va de izquierda a derecha."


def forget_positions(project):
    """Window positions are operator preferences; this clears them for this project."""
    settings = QSettings("abSCADA", "Runtime")
    settings.remove(settings_key(project, "main").rsplit("/windows/", 1)[0])


class DisplayPanel(QWidget):
    def __init__(self, studio):
        super().__init__()
        display = studio.project.manifest.get("display", {})
        main_settings = display.get("main", {})
        layout = QVBoxLayout(self)
        info = QLabel(detected_monitors()); info.setWordWrap(True); layout.addWidget(info)
        main = QGroupBox("Ventana principal del runtime"); form = QFormLayout(main)
        self.main_monitor = monitor_field(main_settings.get("monitor"), "Automático")
        self.main_mode = mode_field(main_settings.get("mode"), MAIN_MODE)
        self.main_scale = choice_field(SCALE_TITLES, main_settings.get("scale", "fit"))
        self.main_scale.setObjectName("runtimeScale")
        form.addRow("Monitor", self.main_monitor); form.addRow("Al abrir", self.main_mode); form.addRow("Escalado", self.main_scale)
        hint = QLabel("Las pantallas se dibujan en vectorial: textos, líneas y controles se escalan sin perder nitidez.")
        hint.setWordWrap(True); hint.setObjectName("muted"); form.addRow(hint)
        layout.addWidget(main)
        layout.addWidget(QLabel("Ventanas adicionales que se abren al arrancar (por ejemplo alarmas en otro monitor):"))
        self.table = table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Pantalla", "Monitor", "Modo", "Siempre encima"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        self.screens = list(studio.project.screens)
        self.startup = studio.project.manifest["startup_screen"]
        for window in display.get("windows", []):
            self.add(window)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        for title, callback in (("Añadir ventana", lambda: self.add()), ("Eliminar", lambda: table.removeRow(table.currentRow())),
                                ("Olvidar posiciones guardadas", lambda: forget_positions(studio.project))):
            button = QPushButton(title); button.clicked.connect(callback); buttons.addWidget(button)
        buttons.addStretch()

    def add(self, window=None):
        window = window or {}
        row = self.table.rowCount(); self.table.insertRow(row)
        screen = QComboBox(); screen.addItems(self.screens)
        screen.setCurrentText(window.get("screen", self.startup))
        on_top = QCheckBox(); on_top.setChecked(window.get("on_top", False))
        for column, widget in enumerate((screen, monitor_field(window.get("monitor"), "Automático"),
                                         mode_field(window.get("mode")), on_top)):
            self.table.setCellWidget(row, column, widget)

    def data(self):
        result = {}
        main = placement(self.main_monitor, self.main_mode, MAIN_MODE)
        if self.main_scale.currentData() != "fit":
            main["scale"] = self.main_scale.currentData()
        if main:
            result["main"] = main
        windows = []
        for row in range(self.table.rowCount()):
            window = dict(screen=self.table.cellWidget(row, 0).currentText())
            window.update(placement(self.table.cellWidget(row, 1), self.table.cellWidget(row, 2)))
            if self.table.cellWidget(row, 3).isChecked():
                window["on_top"] = True
            windows.append(window)
        if windows:
            result["windows"] = windows
        return result


def apply_display(manifest, value):
    if value:
        manifest["display"] = value
    else:
        manifest.pop("display", None)
