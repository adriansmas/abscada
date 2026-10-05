"""CLI: editor, headless validation and acquisition."""
import argparse
from pathlib import Path
import time
from .project import Project


def main():
    parser = argparse.ArgumentParser(description="abSCADA editor / runtime")
    parser.add_argument("project", nargs="?", default="examples/plant")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--runtime", action="store_true", help="Abrir solo la ventana de operación")
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    try:
        project = Project.load(Path(args.project))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"Proyecto inválido: {exc}\n")
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
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    if args.runtime:
        from .runtime_window import RuntimeWindow
        window = RuntimeWindow(project)
        window.start()
        window.show_operation()
    else:
        from .ui import Window
        window = Window(project)
        window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
