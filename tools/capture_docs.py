"""Regenerate the screenshots of the documentation in docs/img/.

Every capture works on a temporary copy of an example with its simulated PLC on a
private port, so neither the shipped examples nor a simulator already open are touched.

    .venv\\Scripts\\python tools/capture_docs.py                  # all
    .venv\\Scripts\\python tools/capture_docs.py hydro beckhoff   # some

studio    docs/img/studio.png     Studio editing the hydro layout (no PLC)
hydro     docs/img/hydro.png      hydro overview, G1 on load
          docs/img/trends.png     production trend over yesterday's synthetic history
          docs/img/alarms.png     alarms after a G1 bearing trip (takes a few minutes)
brewery   docs/img/brewery.png    brewery overview while the kettle boils
beckhoff  docs/img/beckhoff.png   test bench at 2600 rpm
"""
import argparse
import os
import shutil
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QDateTime, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from abscada import pki  # noqa: E402
from abscada.project import Project  # noqa: E402
from abscada.runtime_window import RuntimeWindow  # noqa: E402
from abscada.viewers import TrendViewer  # noqa: E402
import seed_hydro_history  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img"
# Screens shown inside the content container of the hydro and brewery layouts.
LAYOUT, CONTENT = "00_layout", "contenido"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def pump(seconds):
    app = QApplication.instance()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)


@contextmanager
def copy_of(example):
    work = Path(tempfile.mkdtemp(prefix=f"abscada-{example}-"))
    # Window positions and recent projects go to the temporary folder, not to the user's settings.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(work / "preferences"))
    shutil.copytree(ROOT / "examples" / example, work / example, ignore=shutil.ignore_patterns("runtime"))
    try:
        yield Project.load(work / example), work
    finally:
        shutil.rmtree(work, ignore_errors=True)


@contextmanager
def runtime(project, size):
    window = RuntimeWindow(project)
    window.resize(*size)
    window.show()
    window.start()
    try:
        yield window
    finally:
        window.close()
        QApplication.instance().processEvents()


def show(window, screen):
    window.select_screen(LAYOUT)
    window.containers[CONTENT].select_screen(screen)


def save(widget, name):
    widget.grab().save(str(OUT / name))
    print(OUT / name)


def studio():
    from abscada.ui import Window
    with copy_of("hydro") as (project, _):
        window = Window(project)
        window.resize(1600, 950)
        window.show()
        try:
            pump(1)
            save(window, "studio.png")
        finally:
            window.dirty = False
            window.close()


def hydro():
    from plc_simulators.hydro import HydroPLCs
    from plc_simulators.hydro_map import PORTS
    plcs = HydroPLCs(ports={name: free_port() for name in PORTS}).start()
    try:
        with copy_of("hydro") as (project, _):
            for connection in project.connections:
                connection["port"] = plcs.ports[connection["id"]]
            yesterday = seed_hydro_history.seed(project)[-1]
            with runtime(project, (1600, 900)) as window:
                g1, g2 = plcs.plant.units
                pump(3)
                g1.db["OrdenArranque"] = True
                pump(48)
                g2.db["ConsignaP"] = 3.5  # G2 will sit in the rough zone
                g2.db["OrdenArranque"] = True
                pump(22)
                show(window, "10_general")
                pump(1.2)
                save(window, "hydro.png")
                # Yesterday from the synthetic week: the live buffer restarts with every screen.
                show(window, "70_tend_produccion")
                pump(0.5)
                start = QDateTime.fromSecsSinceEpoch(int(yesterday.timestamp()))
                for viewer in (w for w in QApplication.allWidgets() if isinstance(w, TrendViewer)):
                    viewer.live.setChecked(False)
                    viewer.source.setCurrentIndex(viewer.source.findData("history"))
                    viewer.start.setDateTime(start)
                    viewer.end.setDateTime(start.addDays(1))
                    viewer.reload()
                pump(3)
                save(window, "trends.png")
                g1.db["SimCojinete"] = True
                # Wait for the trip itself (Paso 10); heating time depends on the load reached.
                deadline = time.monotonic() + 180
                while g1.db["Paso"] != 10 and time.monotonic() < deadline:
                    pump(1)
                pump(3)
                show(window, "80_alarmas")
                pump(1.2)
                save(window, "alarms.png")
    finally:
        plcs.stop()


def brewery():
    from plc_simulators.brewery import DT, Brewery, BreweryServer
    # 25 minutes of brewing before the capture: a Rubia into FV3, FV2 emptied, a Tostada boiling.
    ahead = 1500
    plant = Brewery()
    for scan in range(int(ahead / DT)):
        c, t = plant.v["Cocina"], scan * DT
        if c["EsperaOperador"]:
            c["OrdenConfirmar"] = True
        if abs(t - 1.0) < DT / 2:
            c.update(RecetaSeleccionada=1, FVDestino=3, OrdenIniciar=True)
        if plant.v["FV2"]["Fase"] == 6:
            plant.v["FV2"]["OrdenVaciar"] = True
        if abs(t - (ahead - 150)) < DT / 2:
            c.update(RecetaSeleccionada=2, FVDestino=2, OrdenIniciar=True)
        plant.scan()
    with copy_of("brewery") as (project, work):
        server = BreweryServer(port=free_port(), folder=work / "simulador", plant=plant).start()
        try:
            project.connections[0]["endpoint"] = server.endpoint
            project.opcua_server["port"] = free_port()
            # What the administrator does once in Studio: trust the PLC certificate.
            pki.trust(project.root, (pki.pki_root(server.folder) / "own" / "plc.der").read_bytes())
            with runtime(project, (1600, 900)) as window:
                pump(20)
                show(window, "10_general")
                pump(2)
                save(window, "brewery.png")
        finally:
            server.stop()


def beckhoff():
    from plc_simulators.ads import DEMO_SYMBOLS, AdsSimulator, run_demo
    sim = AdsSimulator(DEMO_SYMBOLS, port=0).start()
    stop = threading.Event()
    threading.Thread(target=run_demo, args=(sim, stop), daemon=True).start()
    try:
        with copy_of("beckhoff") as (project, _):
            project.connections[0]["port"] = sim.port
            with runtime(project, (1300, 830)) as window:
                pump(2)
                sim.set("MAIN.rConsignaVelocidad", 2600.0)
                sim.set("MAIN.bMarcha", True)
                pump(40)
                save(window, "beckhoff.png")
    finally:
        stop.set()
        sim.stop()


CAPTURES = {"studio": studio, "hydro": hydro, "brewery": brewery, "beckhoff": beckhoff}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", metavar="captura", help="studio, hydro, brewery o beckhoff; sin argumentos, todas")
    names = parser.parse_args().names or list(CAPTURES)
    if unknown := set(names) - set(CAPTURES):
        parser.error(f"capturas desconocidas: {', '.join(sorted(unknown))}")
    OUT.mkdir(parents=True, exist_ok=True)
    QApplication.instance() or QApplication([])
    for name in names:
        CAPTURES[name]()


if __name__ == "__main__":
    main()
