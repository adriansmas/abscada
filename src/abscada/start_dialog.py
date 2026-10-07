"""Start screen, recent projects and the «new / open project» file pickers."""
import shutil
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import __version__
from .app_paths import documents_root, examples_root
from .project_files import SUFFIX, is_project, locate, new_project_location

MAX_RECENT = 10
FILTER = f"Proyecto abSCADA (*{SUFFIX});;Proyecto antiguo (project.json)"

# Shipped examples, in the order a newcomer should try them.
EXAMPLES = [
    ("hydro", "Central hidroeléctrica · CH Valdearenas",
     "SCADA completo de dos grupos Francis: secuencias, protecciones, unifilar, alarmas y tendencias."),
    ("brewery", "Microcervecería por lotes · La Tolva",
     "Cocción por recetas, fermentación, OPC UA cifrado, usuarios y roles."),
    ("beckhoff", "Banco de ensayo Beckhoff (TwinCAT ADS)",
     "Indicadores de aguja, mando y alarmas sobre un PLC Beckhoff simulado."),
    ("showcase", "Laboratorio SCADA", "Todos los controles, estados, objetos de librería, gráficas, alarmas y scripts."),
    ("plant", "Planta de bombeo", "Ejemplo básico con layout, depósito, bombas, alarmas y registros."),
    ("library_author", "Autoría de bibliotecas", "Cómo crear y publicar librerías de objetos reutilizables."),
]


# -- recent projects ------------------------------------------------------------
def _settings():
    return QSettings("abSCADA", "Studio")


def recent_projects():
    paths = _settings().value("recentProjects", [], type=list) or []
    return [p for p in paths if is_project(p)]


def remember_project(manifest_path):
    path = str(Path(manifest_path).resolve())
    paths = [p for p in recent_projects() if Path(p).resolve() != Path(path)]
    _settings().setValue("recentProjects", [path, *paths][:MAX_RECENT])


# -- examples -------------------------------------------------------------------
def example_copy(folder):
    """Copy a shipped example to Documents/abSCADA/Ejemplos once; reuse the copy afterwards."""
    source = examples_root() / folder
    target = documents_root() / "Ejemplos" / folder
    if not is_project(target):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("runtime", "pki", "__pycache__", ".git"))
    root, manifest = locate(target)
    return root / manifest


# -- pickers used by the start screen and by Studio --------------------------------
def ask_open_project(parent):
    start = str(documents_root()) if documents_root().exists() else ""
    path, _ = QFileDialog.getOpenFileName(parent, "Abrir proyecto", start, FILTER)
    return path or None


def ask_new_project(parent):
    """Ask a name and location; create the project folder with its .abscada file."""
    from .project import Project
    documents_root().mkdir(parents=True, exist_ok=True)
    chosen, _ = QFileDialog.getSaveFileName(parent, "Nuevo proyecto · nombre y ubicación",
                                            str(documents_root() / f"Mi SCADA{SUFFIX}"), f"Proyecto abSCADA (*{SUFFIX})")
    if not chosen:
        return None
    try:
        folder, manifest_file = new_project_location(chosen)
    except ValueError as exc:
        QMessageBox.warning(parent, "Nuevo proyecto", str(exc))
        return None
    title, ok = QInputDialog.getText(parent, "Nuevo proyecto", "Título del proyecto", text=Path(manifest_file).stem)
    if not ok or not title.strip():
        return None
    project = Project(folder, dict(schema_version=1, name=title.strip(), startup_screen="main"),
                      {}, [], [], {"main": dict(width=1280, height=720, elements=[])}, {}, manifest_file=manifest_file)
    project.save()
    return project.manifest_path


class StartDialog(QDialog):
    """Shown when Studio starts without a project. `selected` holds the manifest path."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected = None
        self.setWindowTitle(f"abSCADA {__version__}")
        self.resize(820, 520)
        layout = QHBoxLayout(self)

        side = QVBoxLayout()
        title = QLabel(f"<h2>abSCADA</h2><p>SCADA libre · versión {__version__}</p>")
        title.setTextFormat(Qt.TextFormat.RichText)
        side.addWidget(title)
        for text, handler in (("Nuevo proyecto…", self.new_project), ("Abrir proyecto…", self.open_project)):
            button = QPushButton(text)
            button.setMinimumHeight(38)
            button.clicked.connect(handler)
            side.addWidget(button)
        side.addStretch()
        side.addWidget(QLabel(f"Proyectos y ejemplos en:\n{documents_root()}"))
        layout.addLayout(side, 1)

        lists = QVBoxLayout()
        lists.addWidget(QLabel("<b>Recientes</b>"))
        self.recent = QListWidget()
        for path in recent_projects():
            item = QListWidgetItem(f"{Path(path).stem}\n{Path(path).parent}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.recent.addItem(item)
        if not self.recent.count():
            self.recent.addItem("Todavía no has abierto ningún proyecto")
            self.recent.setEnabled(False)
        self.recent.itemActivated.connect(lambda item: self.finish(item.data(Qt.ItemDataRole.UserRole)))
        lists.addWidget(self.recent, 1)

        lists.addWidget(QLabel("<b>Ejemplos</b> · se copian a Documentos para que puedas modificarlos"))
        self.examples = QListWidget()
        for folder, name, description in EXAMPLES:
            if is_project(examples_root() / folder):
                item = QListWidgetItem(f"{name}\n{description}")
                item.setData(Qt.ItemDataRole.UserRole, folder)
                self.examples.addItem(item)
        self.examples.itemActivated.connect(self.open_example)
        lists.addWidget(self.examples, 1)
        row = QWidget()
        bottom = QHBoxLayout(row)
        bottom.setContentsMargins(0, 0, 0, 0)
        self.with_simulator = QCheckBox("Arrancar también su PLC simulado")
        self.with_simulator.setChecked(True)
        bottom.addWidget(self.with_simulator)
        bottom.addStretch()
        open_example = QPushButton("Abrir ejemplo")
        open_example.clicked.connect(lambda: self.open_example(self.examples.currentItem()))
        bottom.addWidget(open_example)
        lists.addWidget(row)
        layout.addLayout(lists, 2)

    def finish(self, path):
        if path:
            self.selected = path
            self.accept()

    def new_project(self):
        try:
            self.finish(ask_new_project(self))
        except Exception as exc:
            QMessageBox.critical(self, "Nuevo proyecto", str(exc))

    def open_project(self):
        self.finish(ask_open_project(self))

    def open_example(self, item):
        if item is None:
            QMessageBox.information(self, "Ejemplos", "Selecciona un ejemplo de la lista")
            return
        folder = item.data(Qt.ItemDataRole.UserRole)
        try:
            path = example_copy(folder)
        except OSError as exc:
            QMessageBox.critical(self, "Ejemplos", f"No se pudo copiar el ejemplo: {exc}")
            return
        if self.with_simulator.isChecked():
            from .simulators import for_example
            simulator = for_example(folder)
            if simulator:
                from . import simulator_manager
                try:
                    simulator_manager.start(simulator.id)
                except Exception as exc:
                    QMessageBox.warning(self, "Simulador",
                                        f"No se pudo arrancar «{simulator.title}»: {exc}\n\nEl proyecto se abrirá igualmente.")
        self.finish(str(path))
