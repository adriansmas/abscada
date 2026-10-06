"""Rotating log file plus a crash dialog, so beta testers can send useful reports."""
import faulthandler
import logging
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from . import __version__
from .app_paths import frozen, log_dir

log = logging.getLogger("abscada")


def log_file():
    return log_dir() / "abscada.log"


def setup(mode="studio"):
    """Log to %LOCALAPPDATA%/abSCADA/logs (or ~/.local/state/abscada/logs); never fatal."""
    if getattr(setup, "done", False):
        return log_file()
    setup.done = True
    handlers = []
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file(), maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass  # read-only profile: keep running without a file log
    if sys.stderr is not None and not frozen():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")
    log.info("abSCADA %s · %s · Python %s · %s%s", __version__, mode, platform.python_version(),
             platform.platform(), " · ejecutable" if frozen() else "")
    try:
        # Native crashes (Qt, drivers) bypass Python's excepthook: dump their traceback too.
        setup.fault_file = open(log_dir() / "fallos-nativos.log", "a", encoding="utf-8")
        faulthandler.enable(setup.fault_file, all_threads=True)
    except OSError:
        pass
    sys.excepthook = _excepthook
    threading.excepthook = lambda args: _excepthook(args.exc_type, args.exc_value, args.exc_traceback, args.thread)
    return log_file()


def report(exc_type, exc_value, tb):
    return "".join(traceback.format_exception(exc_type, exc_value, tb))


def _excepthook(exc_type, exc_value, tb, thread=None):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, tb)
        return
    where = f" en el hilo {thread.name}" if thread else ""
    log.critical("Error no controlado%s\n%s", where, report(exc_type, exc_value, tb))
    if thread is None:
        show_crash_dialog(exc_type, exc_value, tb)


def show_crash_dialog(exc_type, exc_value, tb):
    """Only when a Qt application is running and we are on its thread."""
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        return
    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        return
    box = QMessageBox(QMessageBox.Icon.Critical, "abSCADA · error inesperado",
                      f"Se ha producido un error inesperado:\n\n{exc_value}\n\n"
                      f"Se ha guardado el detalle en:\n{log_file()}\n\n"
                      "Puedes seguir trabajando, pero guarda el proyecto y reinicia si algo no responde.")
    box.setDetailedText(f"abSCADA {__version__}\n{platform.platform()}\n\n{report(exc_type, exc_value, tb)}")
    box.exec()
