"""Monitor layout of the operation: main window and start-up windows per monitor."""
import copy
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QComboBox, QCheckBox,
                               QTableWidget, QHeaderView, QPushButton, QLabel)
from .dialogs import EditorDialog
from .operation_windows import MAX_MONITORS, settings_key

MODE_TITLES = [("normal", "Ventana"), ("maximized", "Maximizada"), ("fullscreen", "Pantalla completa")]


def monitor_field(value, automatic):
    field = QComboBox()
    field.addItem(automatic, 0)
    for number in range(1, MAX_MONITORS + 1):
        field.addItem(f"Monitor {number}", number)
    field.setCurrentIndex(max(0, field.findData(value or 0)))
    return field


def mode_field(value):
    field = QComboBox()
    for key, title in MODE_TITLES:
        field.addItem(title, key)
    field.setCurrentIndex(max(0, field.findData(value or "normal")))
    return field


def placement(monitor, mode):
    result = {}
    if monitor.currentData():
        result["monitor"] = monitor.currentData()
    if mode.currentData() != "normal":
        result["mode"] = mode.currentData()
    return result


def detected_monitors():
    from .runtime_window import monitors
    rows = [f"Monitor {i}: {s.geometry().width()} × {s.geometry().height()} en ({s.geometry().x()}, {s.geometry().y()})"
            for i, s in enumerate(monitors(), 1)]
    return "Este equipo: " + ("; ".join(rows) or "sin monitores detectados") + \
        ". La numeración va de izquierda a derecha."


def forget_positions(project):
    """Window positions are operator preferences; this clears them for this project."""
    settings = QSettings("abSCADA", "Runtime")
    settings.remove(settings_key(project, "main").rsplit("/windows/", 1)[0])


def edit_display(studio):
    display = studio.project.manifest.get("display", {})
    dialog = EditorDialog(studio); dialog.setWindowTitle("Monitores de operación"); dialog.resize(760, 460)
    layout = QVBoxLayout(dialog)
    info = QLabel(detected_monitors()); info.setWordWrap(True); layout.addWidget(info)
    main = QGroupBox("Ventana principal"); form = QFormLayout(main)
    main_monitor = monitor_field(display.get("main", {}).get("monitor"), "Automático")
    main_mode = mode_field(display.get("main", {}).get("mode"))
    form.addRow("Monitor", main_monitor); form.addRow("Modo", main_mode)
    layout.addWidget(main)
    layout.addWidget(QLabel("Ventanas que se abren al arrancar (una por monitor, por ejemplo alarmas o vista general):"))
    table = QTableWidget(0, 4)
    table.setHorizontalHeaderLabels(["Pantalla", "Monitor", "Modo", "Siempre encima"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    layout.addWidget(table)

    def add(window=None):
        window = window or {}
        row = table.rowCount(); table.insertRow(row)
        screen = QComboBox(); screen.addItems(list(studio.project.screens))
        screen.setCurrentText(window.get("screen", studio.project.manifest["startup_screen"]))
        on_top = QCheckBox(); on_top.setChecked(window.get("on_top", False))
        for column, widget in enumerate((screen, monitor_field(window.get("monitor"), "Automático"),
                                         mode_field(window.get("mode")), on_top)):
            table.setCellWidget(row, column, widget)

    for window in display.get("windows", []):
        add(window)
    buttons = QHBoxLayout(); layout.addLayout(buttons)
    for title, callback in (("Añadir ventana", lambda: add()), ("Eliminar", lambda: table.removeRow(table.currentRow())),
                            ("Olvidar posiciones guardadas", lambda: forget_positions(studio.project))):
        button = QPushButton(title); button.clicked.connect(callback); buttons.addWidget(button)
    buttons.addStretch()

    def data():
        result = {}
        main_data = placement(main_monitor, main_mode)
        if main_data:
            result["main"] = main_data
        windows = []
        for row in range(table.rowCount()):
            window = dict(screen=table.cellWidget(row, 0).currentText())
            window.update(placement(table.cellWidget(row, 1), table.cellWidget(row, 2)))
            if table.cellWidget(row, 3).isChecked():
                window["on_top"] = True
            windows.append(window)
        if windows:
            result["windows"] = windows
        return result

    def apply(manifest, value):
        if value:
            manifest["display"] = value
        else:
            manifest.pop("display", None)

    def validate():
        candidate = copy.deepcopy(studio.project); apply(candidate.manifest, data()); candidate.validate()
    dialog.validator = validate
    studio.dialog_buttons(dialog, layout)
    if dialog.exec() == EditorDialog.DialogCode.Accepted:
        value = data()
        if value != display:
            studio.mutate(lambda: apply(studio.project.manifest, value))
