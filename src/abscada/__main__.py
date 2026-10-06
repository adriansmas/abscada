"""CLI: Studio, Runtime, headless validation/acquisition, simulators and helper modes."""
import argparse
import sys
import time
from pathlib import Path

from . import __version__


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Helper modes used by the packaged .exe re-launching itself; no Qt, no logging setup.
    if argv[:1] == ["--script-runner"]:
        from .script_runner import main as run_script
        run_script()
        return
    if argv[:1] == ["--simulador"]:
        from .simulators import SIMULATORS
        if len(argv) < 2 or argv[1] not in SIMULATORS:
            raise SystemExit("Uso: abscada --simulador {" + ",".join(SIMULATORS) + "} [opciones]")
        SIMULATORS[argv[1]].run(argv[2:])
        return

    parser = argparse.ArgumentParser(prog="abscada", description="abSCADA: Studio, Runtime y herramientas")
    parser.add_argument("project", nargs="?", help="Archivo .abscada (o carpeta del proyecto). Sin él se muestra la pantalla de inicio")
    parser.add_argument("--validate", action="store_true", help="Validar el proyecto y salir")
    parser.add_argument("--headless", action="store_true", help="Adquirir sin interfaz y mostrar valores")
    parser.add_argument("--runtime", action="store_true", help="Abrir solo la ventana de operación")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--simulador", metavar="ID", help="Arrancar un PLC simulado (hydro, ads, laboratorio, s7)")
    parser.add_argument("--version", action="version", version=f"abSCADA {__version__}")
    args = parser.parse_args(argv)

    from .app_logging import setup
    mode = "validate" if args.validate else "headless" if args.headless else "runtime" if args.runtime else "studio"
    setup(mode)

    from .project import Project
    project = None
    if args.project:
        try:
            project = Project.load(Path(args.project))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            parser.exit(2, f"Proyecto inválido: {exc}\n")
    elif args.validate or args.headless or args.runtime:
        parser.error("indica el archivo .abscada del proyecto")

    if args.validate:
        print(f"Proyecto válido: {project.manifest['name']} · {len(project.tags())} variables")
        return
    if args.headless:
        from .runtime import Runtime
        runtime = Runtime(project)
        runtime.start()
        try:
            end = time.monotonic() + args.seconds
            while time.monotonic() < end:
                print({k: (v.value, v.quality) for k, v in runtime.snapshot().items()})
                time.sleep(1)
        finally:
            runtime.stop()
        return

    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    app.setApplicationName("abSCADA")
    app.setApplicationVersion(__version__)
    _set_icon(app)
    if args.runtime:
        from .runtime_window import RuntimeWindow
        window = RuntimeWindow(project)
        window.start()
        window.show_operation()
        raise SystemExit(app.exec())

    from .start_dialog import StartDialog, remember_project
    while project is None:
        dialog = StartDialog()
        if dialog.exec() != StartDialog.DialogCode.Accepted or not dialog.selected:
            return
        try:
            project = Project.load(dialog.selected)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            QMessageBox.critical(None, "Abrir proyecto", f"No se pudo abrir el proyecto:\n{exc}")
    remember_project(project.manifest_path)
    from .ui import Window
    window = Window(project)
    window.show()
    raise SystemExit(app.exec())


def _set_icon(app):
    from PySide6.QtGui import QIcon
    from .app_paths import bundle_root
    for candidate in (bundle_root() / "packaging" / "abscada.ico", Path(__file__).with_name("abscada.ico")):
        if candidate.exists():
            app.setWindowIcon(QIcon(str(candidate)))
            return


if __name__ == "__main__":
    main()
