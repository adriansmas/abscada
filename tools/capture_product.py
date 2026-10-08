"""Capture operation against an external Snap7 TCP server; no app value generator."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import math
import socket
import struct
import time
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from abscada.project import Project
from abscada.ui import Window
from plc_simulators.s7 import create_server

root = Path(__file__).resolve().parents[1]
app = QApplication([])
with socket.socket() as probe:
    probe.bind(("127.0.0.1",0)); port = probe.getsockname()[1]
server, memory = create_server(port)
project = Project.load(root/"examples/plant")
project.root = Path(tempfile.mkdtemp(prefix="abscada-capture-"))
project.connections[0]["port"] = port
project.trends["process"]["window_seconds"] = 10
window = Window(project); window.show(); app.processEvents()
window.navigate("alarms"); window.grab().save(str(root/"docs/studio-alarms.png"))
window.navigate("variables"); window.grab().save(str(root/"docs/studio-variable-recording.png"))
window.navigate("historian"); window.grab().save(str(root/"docs/studio-historian.png"))
window.navigate("trends"); window.grab().save(str(root/"docs/studio-trends.png"))
def capture_dialog():
    dialog = app.activeModalWidget()
    dialog.grab().save(str(root/"docs/trend-configuration.png")); dialog.reject()
QTimer.singleShot(50,capture_dialog)
window.operational_editor.edit_trend(dict(id="process"))
window.navigate("screens"); window.start_runtime(); live = window.runtime_window
memory[0] = memory[16] = 1
begin = time.monotonic()
try:
    while time.monotonic()-begin < 10:
        elapsed = time.monotonic()-begin
        struct.pack_into(">f",memory,12,90 if 3<elapsed<5 else 50+20*math.sin(elapsed))
        struct.pack_into(">f",memory,4,90 if elapsed>6 else 55+15*math.sin(elapsed/2))
        struct.pack_into(">f",memory,20,40+10*math.cos(elapsed/2))
        app.processEvents(); QTest.qWait(40); time.sleep(0.01)
    live.select_screen("history")
    graph = next(item.proxy.widget() for item in live.scene.items() if hasattr(item, "proxy"))
    graph.source.setCurrentIndex(graph.source.findData("history"))
    for _ in range(30):
        app.processEvents(); QTest.qWait(40); time.sleep(0.01)
    live.grab().save(str(root/"docs/runtime-trends.png"))
    live.select_screen("alarms")
    for _ in range(30):
        app.processEvents(); QTest.qWait(40); time.sleep(0.01)
    live.grab().save(str(root/"docs/runtime-alarms.png"))
    viewer = next(item.proxy.widget() for item in live.scene.items() if hasattr(item, "proxy"))
    viewer.mode.setCurrentIndex(viewer.mode.findData("events"))
    viewer.end.setDateTime(viewer.end.dateTime().addSecs(30))
    for _ in range(30):
        app.processEvents(); QTest.qWait(40); time.sleep(0.01)
    live.grab().save(str(root/"docs/runtime-events.png"))
finally:
    window.dirty = False; window.close(); server.stop(); server.destroy()
