"""Screenshots of Studio for the documentation: libraries, users and roles, OPC UA.

Works on a temporary copy of examples/brewery with an extra screen of standard library
objects, so the shipped example is never touched. Writes PNG files to artifacts/studio_docs/.

    .venv\\Scripts\\python tools/capture_studio_docs.py
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402
from abscada import pki  # noqa: E402
from abscada.project import Project  # noqa: E402
from abscada.simulators.brewery import BreweryServer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "studio_docs"
DEMO = "15_objetos_estandar"
EVERYWHERE = Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive


def port(preferred):
    """The example's own port when it is free, so the screenshots show real endpoints."""
    import socket
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
        except OSError:
            probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.03)


def grab_modal(app, name, tab=None, after=None):
    """Grab the next modal dialog (optionally on a tab), then close it."""
    def shoot():
        dialog = app.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(50, shoot)
            return
        if tab is not None:
            dialog.findChild(QTabWidget).setCurrentIndex(tab)
        if after:
            after(dialog)
        app.processEvents()
        dialog.grab().save(str(OUT / f"{name}.png"))
        dialog.reject()
    QTimer.singleShot(150, shoot)


def demo_screen(project):
    """A screen built only from the standard library, linked to brewery variables."""
    elements = [dict(id="titulo", kind="text", x=20, y=14, w=900, h=34, text="Objetos de la librería estándar",
                     font_size=20, bold=True, text_color="@Texto")]
    animated = [("bomba", "estandar__bomba_estado", dict(marcha="Servicios.Caldera", fallo="Servicios.FalloCaldera")),
                ("motor", "estandar__motor_estado", dict(marcha="Cocina.AgitadorMT", fallo="Cocina.FueraTemperaturaMT")),
                ("ventilador", "estandar__ventilador_estado", dict(marcha="Servicios.Enfriadora", fallo="Servicios.FalloEnfriadora")),
                ("valvula", "estandar__valvula_estado", dict(abierta="Cocina.Ebullicion")),
                ("interruptor", "estandar__interruptor_estado", dict(cerrado="Servicios.Caldera")),
                ("deposito", "estandar__deposito_nivel", dict(nivel="Servicios.NivelGlicol"))]
    x = 30
    for key, template, bindings in animated:
        fp = project.faceplates[template]
        elements.append(dict(id=key, kind="faceplate", x=x, y=80, w=fp["width"], h=fp["height"], template=template,
                             bindings=bindings))
        elements.append(dict(id=key + "_t", kind="text", x=x - 10, y=230, w=fp["width"] + 20, h=22, text=key.capitalize(),
                             font_size=12, text_align="center", text_color="@TextoSuave"))
        x += fp["width"] + 50
    statics = ["deposito_vertical", "silo", "valvula_motorizada", "valvula_tres_vias", "bomba_centrifuga", "compresor",
               "intercambiador", "caldera", "columna", "transmisor_nivel", "transmisor_temperatura", "transformador"]
    for i, name in enumerate(statics):
        fp = project.faceplates["estandar__" + name]
        scale = min(90 / fp["width"], 90 / fp["height"])
        w, h = round(fp["width"] * scale), round(fp["height"] * scale)
        cx = 30 + (i % 6) * 150
        cy = 300 + (i // 6) * 170
        elements.append(dict(id=name, kind="faceplate", x=cx, y=cy, w=w, h=h, template="estandar__" + name, bindings={}))
        elements.append(dict(id=name + "_t", kind="text", x=cx - 30, y=cy + 100, w=150, h=22,
                             text=name.replace("_", " "), font_size=11, text_align="center", text_color="@TextoSuave"))
    project.screens[DEMO] = dict(title="Objetos estándar", width=1000, height=660, background="@Fondo", grid_size=10,
                                 show_grid=False, snap_to_grid=True, elements=elements, folder="Proceso")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="abscada-studio-docs-"))
    shutil.copytree(ROOT / "examples" / "brewery", work / "brewery", ignore=shutil.ignore_patterns("runtime"))
    server = BreweryServer(port=port(4841), folder=work / "simulador").start()
    app = QApplication.instance() or QApplication([])
    from abscada.ui import Window
    window = None
    try:
        project = Project.load(work / "brewery")
        project.connections[0]["endpoint"] = server.endpoint
        project.opcua_server["port"] = port(4850)
        demo_screen(project)
        project.validate()
        project.save()
        # A PLC certificate waiting in «Rechazados», as after the first connection attempt.
        pki.reject(project.root, (pki.pki_root(server.folder) / "own" / "plc.der").read_bytes())
        window = Window(project)
        window.resize(1600, 900)
        window.show()
        pump(app, 0.5)

        # Libraries: the tree with the standard library open and a screen made of its objects.
        window.navigation.setCurrentItem(window.navigation.findItems(DEMO, EVERYWHERE)[0])
        pump(app, 0.3)
        anchor = None
        for item in window.navigation.findItems("", EVERYWHERE):
            if item.text(0) in ("Librerías", "Estándar (sistema)", "Objetos"):
                item.setExpanded(True)
            if item.text(0) == "Librerías":
                anchor = item
        if anchor is not None:
            window.navigation.scrollToItem(anchor, window.navigation.ScrollHint.PositionAtTop)
        pump(app, 0.5)
        window.grab().save(str(OUT / "studio-librerias.png"))

        from abscada.library_browser import LibraryPicker
        picker = LibraryPicker(window, project)
        picker.resize(560, 640)
        picker.show()
        for i in range(picker.tree.topLevelItemCount()):
            picker.tree.topLevelItem(i).setExpanded(True)
        pump(app, 0.3)
        picker.grab().save(str(OUT / "studio-selector-objetos.png"))
        picker.close()

        # Users and roles, OPC UA server and certificates.
        from abscada.security_editor import certificates_dialog, edit_opcua_server, edit_security
        grab_modal(app, "studio-usuarios-roles", tab=1)
        edit_security(window)
        grab_modal(app, "studio-usuarios-cuentas", tab=2)
        edit_security(window)
        grab_modal(app, "studio-usuarios-politica", tab=0)
        edit_security(window)
        grab_modal(app, "studio-servidor-opcua")
        edit_opcua_server(window)
        grab_modal(app, "studio-certificados-opcua")
        certificates_dialog(window)

        window.navigate("connections")
        window.connections_table.selectRow(0)
        pump(app, 0.3)
        grab_modal(app, "studio-conexion-opcua")
        window.edit_catalog("connections", False)

        # Runtime: login dialog and the standard objects with live data.
        pki.trust(project.root, (pki.pki_root(server.folder) / "own" / "plc.der").read_bytes())
        window.navigate("screens")
        window.start_runtime()
        live = window.runtime_window
        live.resize(1100, 760)
        pump(app, 4)
        grab_modal(app, "runtime-inicio-sesion")
        live.request_login("Esta orden necesita el permiso «Mandos y consignas».")
        live.showNormal()
        live.resize(1060, 760)
        live.select_screen(DEMO)
        pump(app, 3)
        live.grab().save(str(OUT / "runtime-objetos-estandar.png"))
        live.close()
        print(OUT)
    finally:
        if window:
            window.close()
            app.processEvents()
        server.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
