"""Reproducible editor/runtime screenshots using an external S7 TCP server."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import socket
import tempfile
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QSettings
from abscada.project import Project
from abscada.ui import Window
from abscada.s7_simulator import create_server

root = Path(__file__).resolve().parents[1]
app = QApplication([])
project = Project.load(root/"examples/plant")
project.root = Path(tempfile.mkdtemp(prefix="abscada-visual-editor-"))
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(project.root/'preferences'))
project.manifest["startup_screen"] = "process_design"
with socket.socket() as probe:
    probe.bind(("127.0.0.1",0)); port = probe.getsockname()[1]
server, memory = create_server(port)
project.connections[0]["port"] = port
window = Window(project); window.resize(1600,950); window.show()
try:
    for _ in range(5):
        app.processEvents(); QTest.qWait(30)
    window.grab().save(str(root/"docs/editor-screen-properties.png"))
    item = next(i for i in window.scene.items() if i.element["id"] == "feed_one")
    item.setSelected(True)
    app.processEvents()
    window.grab().save(str(root/"docs/editor-pipe-properties.png"))
    window.start_runtime()
    for _ in range(30):
        app.processEvents(); QTest.qWait(30); time.sleep(.005)
    window.runtime_window.grab().save(str(root/"docs/runtime-process-design.png"))
    popup = window.runtime_window.open_popup("pump_settings")
    app.processEvents(); QTest.qWait(150)
    popup.grab().save(str(root/"docs/runtime-popup-settings.png"))
    popup.close()
    window.runtime_window.select_screen("main_layout")
    app.processEvents(); QTest.qWait(200)
    window.runtime_window.grab().save(str(root/"docs/runtime-layout.png"))
    window.project.manifest['startup_screen'] = 'main_layout'
    window.document_name = "main_layout"; window.populate_navigation(); window.render_scene()
    app.processEvents()
    window.grab().save(str(root/"docs/editor-layout.png"))
    window.navigate('automation')
    window.automation_editor.current = 'check_quality'; window.automation_editor.refresh()
    app.processEvents()
    window.grab().save(str(root/'docs/editor-automation.png'))
    from abscada.project_dialogs import NewDocumentDialog
    dialog = NewDocumentDialog(window)
    dialog.name.setText('sensor_settings'); dialog.title.setText('Configuración de sensores')
    dialog.show(); app.processEvents()
    dialog.grab().save(str(root/'docs/new-screen-dialog.png')); dialog.close()
finally:
    window.dirty = False; window.close(); server.stop(); server.destroy()
