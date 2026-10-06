"""«Ajustes del proyecto»: general data, size of new screens and the operation windows.

manifest["screen_defaults"] = {"width": 1920, "height": 1080} is the canvas size proposed for new
screens; it is usually the resolution of the operator's monitor.
"""
import copy

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .dialogs import EditorDialog

DEFAULT_SIZE = (1280, 720)


def screen_size(project):
    defaults = project.manifest.get("screen_defaults", {})
    return defaults.get("width", DEFAULT_SIZE[0]), defaults.get("height", DEFAULT_SIZE[1])


def validate_settings(project):
    defaults = project.manifest.get("screen_defaults", {})
    if not isinstance(defaults, dict) or set(defaults) - {"width", "height"}:
        raise ValueError("screen_defaults admite width y height")
    for value in defaults.values():
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10000:
            raise ValueError("El tamaño de las pantallas nuevas debe estar entre 1 y 10000 px")


def scale_screens(project, width, height, names):
    """Resize screens to a new canvas size, scaling the position and size of their elements."""
    for name in names:
        document = project.screens[name]
        fx, fy = width / document["width"], height / document["height"]
        document.update(width=width, height=height)
        for element in document["elements"]:
            element.update(x=round(element["x"] * fx, 1), y=round(element["y"] * fy, 1),
                           w=round(element["w"] * fx, 1), h=round(element["h"] * fy, 1))
            if "points" in element:
                element["points"] = [[round(x * fx, 1), round(y * fy, 1)] for x, y in element["points"]]


def edit_project_settings(studio):
    from .display_editor import DisplayPanel, apply_display
    project = studio.project
    dialog = EditorDialog(studio); dialog.setWindowTitle("Ajustes del proyecto"); dialog.resize(780, 560)
    layout = QVBoxLayout(dialog)
    tabs = QTabWidget(); layout.addWidget(tabs)

    general = QWidget(); body = QVBoxLayout(general)
    identity = QGroupBox("Proyecto"); form = QFormLayout(identity)
    name = QLineEdit(project.manifest["name"]); name.setObjectName("projectName")
    startup = QComboBox(); startup.setObjectName("startupScreen"); startup.addItems(list(project.screens))
    startup.setCurrentText(project.manifest["startup_screen"])
    form.addRow("Nombre", name)
    form.addRow("Pantalla de inicio", startup)
    body.addWidget(identity)

    size = QGroupBox("Tamaño de las pantallas"); form = QFormLayout(size)
    width, height = QSpinBox(), QSpinBox()
    for field, value in zip((width, height), screen_size(project)):
        field.setRange(1, 10000); field.setValue(value)
    width.setObjectName("screenWidth"); height.setObjectName("screenHeight")
    width.setFixedWidth(100); height.setFixedWidth(100)
    row = QHBoxLayout(); row.addWidget(width); row.addWidget(QLabel("×")); row.addWidget(height)
    monitor = QPushButton("Usar la resolución de este monitor")
    def use_monitor():
        geometry = (studio.screen() or QGuiApplication.primaryScreen()).geometry()
        width.setValue(geometry.width()); height.setValue(geometry.height())
    monitor.clicked.connect(use_monitor); row.addWidget(monitor); row.addStretch()
    form.addRow("Pantallas nuevas (px)", row)
    resize = QPushButton("Escalar las pantallas existentes a este tamaño…")
    resize.setObjectName("scaleScreens")
    form.addRow(resize)
    note = QLabel("Diseña las pantallas con la resolución del monitor de operación. En el runtime se escalan "
                  "a la ventana según la pestaña «Operación».")
    note.setWordWrap(True); note.setObjectName("muted"); form.addRow(note)
    body.addWidget(size); body.addStretch()
    tabs.addTab(general, "General")

    display = DisplayPanel(studio)
    tabs.addTab(display, "Operación")

    scale_request = []
    def ask_scale():
        from PySide6.QtWidgets import QMessageBox
        target = (width.value(), height.value())
        names = [n for n, d in project.screens.items() if (d["width"], d["height"]) != target]
        if not names:
            QMessageBox.information(dialog, "Escalar pantallas", "Todas las pantallas tienen ya ese tamaño.")
            return
        if QMessageBox.question(dialog, "Escalar pantallas",
                                f"Se cambiará el tamaño de {len(names)} pantallas a {target[0]} × {target[1]} px, moviendo y "
                                "escalando sus elementos (los textos mantienen su tamaño de letra). Se aplica al pulsar "
                                "Aceptar y se puede deshacer con Ctrl+Z. ¿Continuar?") == QMessageBox.StandardButton.Yes:
            scale_request[:] = [names]
            resize.setText(f"Se escalarán {len(names)} pantallas al aceptar")
    resize.clicked.connect(ask_scale)

    def apply(target):
        target.manifest["name"] = name.text().strip()
        target.manifest["startup_screen"] = startup.currentText()
        if (width.value(), height.value()) == DEFAULT_SIZE:
            target.manifest.pop("screen_defaults", None)
        else:
            target.manifest["screen_defaults"] = dict(width=width.value(), height=height.value())
        apply_display(target.manifest, display.data())
        if scale_request:
            scale_screens(target, width.value(), height.value(), scale_request[0])

    def validate():
        candidate = copy.deepcopy(project); apply(candidate); candidate.validate()
    dialog.validator = validate
    studio.dialog_buttons(dialog, layout)
    if dialog.exec() == EditorDialog.DialogCode.Accepted:
        candidate = copy.deepcopy(project); apply(candidate)
        if candidate != project:
            studio.mutate(lambda: apply(studio.project))
            studio.project_label.setText(studio.project.manifest["name"])
