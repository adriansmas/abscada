"""«Simuladores de PLC» and «Acerca de» dialogs of Studio."""
import platform

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout)

from . import __version__, simulator_manager
from .app_paths import frozen, log_dir
from .simulators import SIMULATORS


def build_info():
    try:
        from ._build_info import BUILD
    except ImportError:
        BUILD = "desarrollo (código fuente)"
    return BUILD


class SimulatorsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Simuladores de PLC")
        self.resize(640, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("PLC simulados para probar los ejemplos y para formación, sin equipos reales.\n"
                                "No los arranques en un equipo conectado a una instalación real. Se detienen al cerrar abSCADA."))
        grid = QGridLayout()
        self.rows = {}
        for row, simulator in enumerate(SIMULATORS.values()):
            grid.addWidget(QLabel(f"<b>{simulator.title}</b><br><small>{simulator.endpoints}</small>"), row, 0)
            state = QLabel()
            grid.addWidget(state, row, 1)
            button = QPushButton()
            button.clicked.connect(lambda checked=False, sid=simulator.id: self.toggle(sid))
            grid.addWidget(button, row, 2)
            self.rows[simulator.id] = (state, button)
        layout.addLayout(grid)
        logs = QPushButton("Abrir carpeta de registros")
        logs.clicked.connect(open_log_folder)
        layout.addWidget(logs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self):
        for simulator_id, (state, button) in self.rows.items():
            on = simulator_manager.running(simulator_id)
            state.setText("<span style='color:#147d75'>● en marcha</span>" if on else "○ parado")
            button.setText("Detener" if on else "Arrancar")

    def toggle(self, simulator_id):
        try:
            if simulator_manager.running(simulator_id):
                simulator_manager.stop(simulator_id)
            else:
                simulator_manager.start(simulator_id)
        except Exception as exc:
            QMessageBox.warning(self, "Simulador", str(exc))
        self.refresh()


def open_log_folder():
    log_dir().mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))


def about(parent=None):
    QMessageBox.about(parent, "Acerca de abSCADA",
                      f"<h3>abSCADA {__version__}</h3>"
                      f"<p>SCADA de escritorio libre · GPL-3.0-or-later</p>"
                      f"<p>Compilación: {build_info()}<br>"
                      f"{'Ejecutable' if frozen() else 'Python'} {platform.python_version()} · {platform.platform()}</p>"
                      f"<p>Registros: {log_dir()}</p>"
                      "<p>Esta es una versión beta: guarda a menudo y envía los fallos con el registro adjunto.</p>")
