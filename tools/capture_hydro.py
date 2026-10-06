"""Screenshots of examples/hydro with live data from the simulated PLCs.

Runs on a temporary copy of the project, so the shipped example gets no runtime
files. Starts the simulator, puts G1 on load and G2 in the start sequence, then
grabs every screen into artifacts/hydro/.

    .venv\\Scripts\\python tools/capture_hydro.py [--seconds 70]
"""
import argparse
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication  # noqa: E402
from abscada.project import Project  # noqa: E402
from abscada.runtime_window import RuntimeWindow  # noqa: E402
from hydro_map import PORTS  # noqa: E402
from hydro_plc import HydroPLCs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Screens shown in the documentation; --publish copies them to both places.
PUBLISHED = {"normal": ["10_general", "20_embalse", "30_grupo1", "40_unifilar", "50_auxiliares", "60_control",
                        "72_tend_g1", "90_instructor", "95_emergencia_g1"],
             "averia": ["30_grupo1", "80_alarmas"]}
PUBLISH_TO = [ROOT / "docs" / "hydro"]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=70.0, help="Tiempo de operación antes de capturar")
    parser.add_argument("--averia", action="store_true",
                        help="Calienta el cojinete de empuje de G1 hasta el disparo antes de capturar")
    parser.add_argument("--publish", action="store_true",
                        help="Copia las capturas de la documentación a docs/hydro")
    args = parser.parse_args()
    out = ROOT / "artifacts" / ("hydro_averia" if args.averia else "hydro")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="abscada-hydro-"))
    shutil.copytree(ROOT / "examples" / "hydro", work / "hydro", ignore=shutil.ignore_patterns("runtime"))
    # Private ports, so a simulator the user already has open is never touched.
    plcs = HydroPLCs(ports={name: free_port() for name in PORTS}).start()
    app = QApplication.instance() or QApplication([])
    window = None
    try:
        project = Project.load(work / "hydro")
        for connection in project.connections:
            connection["port"] = plcs.ports[connection["id"]]
        window = RuntimeWindow(project)
        window.resize(1600, 900)
        window.show()
        window.start()
        g1, g2 = plcs.plant.units
        pump(app, 3)
        g1.db["OrdenArranque"] = True
        pump(app, args.seconds - 22)
        g2.db["ConsignaP"] = 3.5           # G2 will sit in the rough zone
        g2.db["OrdenArranque"] = True
        pump(app, 22)
        if args.averia:
            g1.db["SimCojinete"] = True
            # Wait for the trip itself (Paso 10); heating time depends on the load reached.
            deadline = time.monotonic() + 180
            while g1.db["Paso"] != 10 and time.monotonic() < deadline:
                pump(app, 1)
            pump(app, 3)
            print("G1 paso", g1.db["Paso"], "causa", g1.db["CausaDisparo"], "empuje", round(g1.db["TempEmpuje"], 1))
        for name in project.screens:
            if name in ("00_layout", "01_cabecera", "02_menu"):
                continue
            window.select_screen("00_layout")
            if name[0] in "12345678" or name == "90_instructor":
                window.containers["contenido"].select_screen(name)
            else:
                window.select_screen(name)
            pump(app, 1.2)
            window.grab().save(str(out / f"{name}.png"))
        print(out)
        if args.publish:
            kind = "averia" if args.averia else "normal"
            suffix = "_averia" if args.averia else ""
            for folder in PUBLISH_TO:
                folder.mkdir(parents=True, exist_ok=True)
                for name in PUBLISHED[kind]:
                    shutil.copyfile(out / f"{name}.png", folder / f"{name}{suffix}.png")
            print("Publicadas en", ", ".join(str(f.relative_to(ROOT)) for f in PUBLISH_TO))
    finally:
        if window:
            window.close()
            app.processEvents()
        plcs.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
