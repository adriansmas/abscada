"""Screenshot of examples/beckhoff running against the ADS simulator (temporary copy, private port).

    .venv\\Scripts\\python tools/capture_beckhoff.py
"""
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from plc_simulators.ads import DEMO_SYMBOLS, AdsSimulator, run_demo  # noqa: E402
from abscada.project import Project  # noqa: E402
from abscada.runtime_window import RuntimeWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)


def main():
    out = ROOT / "artifacts" / "beckhoff"
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="abscada-beckhoff-"))
    shutil.copytree(ROOT / "examples" / "beckhoff", work / "beckhoff", ignore=shutil.ignore_patterns("runtime"))
    sim = AdsSimulator(DEMO_SYMBOLS, port=0).start()
    stop = threading.Event()
    threading.Thread(target=run_demo, args=(sim, stop), daemon=True).start()
    app = QApplication.instance() or QApplication([])
    window = None
    try:
        project = Project.load(work / "beckhoff")
        project.connections[0]["port"] = sim.port
        window = RuntimeWindow(project)
        window.resize(1300, 830)
        window.show()
        window.start()
        pump(app, 2)
        sim.set("MAIN.rConsignaVelocidad", 2600.0)
        sim.set("MAIN.bMarcha", True)
        pump(app, 40)
        window.grab().save(str(out / "banco.png"))
        print(out / "banco.png")
    finally:
        if window:
            window.close()
            app.processEvents()
        stop.set()
        sim.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
