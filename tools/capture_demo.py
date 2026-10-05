"""Render reproducible application previews without starting an interactive GUI."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import time
from PySide6.QtWidgets import QApplication
from abscada.project import Project
from abscada.ui import Window
from abscada.s7_simulator import create_server
import socket

root = Path(__file__).resolve().parents[1]
app = QApplication([])
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
server, memory = create_server(port)
project = Project.load(root / "examples" / "demo")
project.connections[0]["port"] = port
window = Window(project)
window.show()
app.processEvents()
item = next(item for item in window.scene.items() if item.element["id"] == "pump1")
item.setSelected(True)
app.processEvents()
window.grab().save(str(root / "docs" / "editor.png"))
window.start_runtime()
time.sleep(0.4)
window.refresh()
app.processEvents()
window.runtime_window.grab().save(str(root / "docs" / "runtime.png"))
window.grab().save(str(root / "docs" / "editor-runtime-active.png"))
window.stop_runtime()
window.navigate("variables")
window.table.expandAll()
app.processEvents()
window.grab().save(str(root / "docs" / "variables.png"))
window.navigate("connections")
app.processEvents()
window.grab().save(str(root / "docs" / "connections.png"))
window.close()
server.stop()
server.destroy()
