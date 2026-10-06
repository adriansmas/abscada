"""Paths and child-process commands that differ between a source checkout and the .exe.

In a PyInstaller build `sys.executable` is abscada.exe itself, so helper processes
(script runner, PLC simulators) are started by re-launching the executable with a
private flag instead of `python -m ...`.
"""
import os
import sys
from pathlib import Path

APP_NAME = "abSCADA"


def frozen():
    return bool(getattr(sys, "frozen", False))


def bundle_root():
    """Folder holding shipped resources: the PyInstaller bundle or the repository root."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def examples_root():
    return bundle_root() / "examples"


def documents_root():
    """User-visible working folder: Documents/abSCADA."""
    home = Path.home()
    documents = home / "Documents"
    if sys.platform == "win32":
        documents = Path(os.environ.get("USERPROFILE", home)) / "Documents"
    elif not documents.exists() and (home / "Documentos").exists():
        documents = home / "Documentos"
    return documents / APP_NAME


def state_root():
    """Private per-user state: logs and settings that are not project data."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "abscada"


def log_dir():
    return state_root() / "logs"


def script_runner_command():
    if frozen():
        return [sys.executable, "--script-runner"]
    return [sys.executable, "-I", str(Path(__file__).with_name("script_runner.py"))]


def simulator_command(simulator_id):
    if frozen():
        return [sys.executable, "--simulador", simulator_id]
    return [sys.executable, "-m", "abscada", "--simulador", simulator_id]
