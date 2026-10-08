"""Screenshots of examples/brewery with live data from the simulated PLC.

Runs on a temporary copy of the project, so the shipped example gets no runtime files
(certificates, accounts, archives). First the plant model runs 25 minutes ahead of the
clock: a Rubia brew into FV3, FV2 bottled, and a Tostada brew started towards FV2. Those
25 minutes are written to the copy's historian with past timestamps, so the trends have
a past. Then the simulator serves that same plant on a private port, the copy trusts its
certificate, and every screen is grabbed into artifacts/brewery/ while the kettle boils.

    .venv\\Scripts\\python tools/capture_brewery.py [--seconds 20]
"""
import argparse
import os
import shutil
import socket
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from abscada import pki  # noqa: E402
from abscada.project import Project  # noqa: E402
from abscada.recording import path  # noqa: E402
from abscada.runtime import Sample  # noqa: E402
from abscada.runtime_window import RuntimeWindow  # noqa: E402
from plc_simulators.brewery import DT, Brewery, BreweryServer  # noqa: E402
from abscada.storage import Repository, RuntimeLease  # noqa: E402
from abscada.viewers import TrendViewer  # noqa: E402

AHEAD_S = 1500

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ["10_general", "20_cocina", "30_bodega", "40_recetas", "50_servicios", "71_tend_fv1", "90_instructor"]
PUBLISH_TO = [ROOT / "docs" / "brewery"]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)


def operate(plant, t):
    """What the brewer does during the fast-forwarded past."""
    c = plant.v["Cocina"]
    if c["EsperaOperador"]:
        c["OrdenConfirmar"] = True
    if abs(t - 1.0) < DT / 2:
        c.update(RecetaSeleccionada=1, FVDestino=3, OrdenIniciar=True)
    if plant.v["FV2"]["Fase"] == 6:
        plant.v["FV2"]["OrdenVaciar"] = True
    if abs(t - (AHEAD_S - 150)) < DT / 2:  # boiling when the screens are grabbed
        c.update(RecetaSeleccionada=2, FVDestino=2, OrdenIniciar=True)


def fast_forward(project):
    """Run the plant AHEAD_S seconds and log it as the recent past of the copy's historian."""
    plant = Brewery()
    start = datetime.now(timezone.utc).timestamp() - AHEAD_S
    files = [(f["id"], set(f["variables"]), f["interval_ms"] / 1000) for f in project.historian["files"]]
    lease = RuntimeLease(project.root / "runtime" / "runtime.lock")
    lease.acquire()
    repositories = {}
    try:
        for scan in range(int(AHEAD_S / DT)):
            t = scan * DT
            operate(plant, t)
            plant.scan()
            if scan % 10:
                continue
            stamp = start + t
            values = plant.published()
            for file_id, tags, interval in files:
                if round(t / DT) % round(interval / DT):
                    continue
                target = path(project, file_id, stamp)
                if target not in repositories:
                    repositories[target] = Repository(target)
                for tag in tags:
                    repositories[target].sample(tag, Sample(values[tag], "good", stamp), stamp)
    finally:
        for repository in repositories.values():
            repository.connection.commit()
            repository.close()
        lease.close()
    return plant


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=20.0, help="Tiempo de operación en vivo antes de capturar")
    parser.add_argument("--publish", action="store_true",
                        help="Copia las capturas de la documentación a docs/brewery")
    args = parser.parse_args()
    out = ROOT / "artifacts" / "brewery"
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="abscada-brewery-"))
    shutil.copytree(ROOT / "examples" / "brewery", work / "brewery", ignore=shutil.ignore_patterns("runtime"))
    project = Project.load(work / "brewery")
    plant = fast_forward(project)
    server = BreweryServer(port=free_port(), folder=work / "simulador", plant=plant).start()
    app = QApplication.instance() or QApplication([])
    window = None
    try:
        project.connections[0]["endpoint"] = server.endpoint
        project.opcua_server["port"] = free_port()
        der = (pki.pki_root(server.folder) / "own" / "plc.der").read_bytes()
        pki.trust(project.root, der)  # what the administrator does once in Studio
        window = RuntimeWindow(project)
        window.resize(1600, 900)
        window.show()
        window.start()
        pump(app, args.seconds)
        print("Paso", plant.v["Cocina"]["Paso"], "· FV1 fase", plant.v["FV1"]["Fase"], "· FV2 fase", plant.v["FV2"]["Fase"])
        for name in project.screens:
            if name in ("00_layout", "01_cabecera", "02_menu"):
                continue
            window.select_screen("00_layout")
            if name[0] in "12345678" or name == "90_instructor":
                window.containers["contenido"].select_screen(name)
            else:
                window.select_screen(name)
            pump(app, 0.3)
            # Trends read the fast-forwarded past from the historian, not only what Runtime saw.
            # They live in the graphics scene (proxy widgets), not under the window.
            for widget in QApplication.allWidgets():
                if isinstance(widget, TrendViewer):
                    widget.source.setCurrentIndex(widget.source.findData("history"))
            pump(app, 2.0)
            window.grab().save(str(out / f"{name}.png"))
        print(out)
        if args.publish:
            for folder in PUBLISH_TO:
                folder.mkdir(parents=True, exist_ok=True)
                for name in PUBLISHED:
                    shutil.copyfile(out / f"{name}.png", folder / f"{name}.png")
            print("Publicadas en", ", ".join(str(f.relative_to(ROOT)) for f in PUBLISH_TO))
    finally:
        if window:
            window.close()
            app.processEvents()
        server.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
