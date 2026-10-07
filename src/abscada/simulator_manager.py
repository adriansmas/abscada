"""Start and stop the development PLC simulators as child processes of Studio."""
import atexit
import subprocess
import sys

from .app_paths import log_dir, simulator_command
from .simulators import SIMULATORS
from .i18n import tr

_processes = {}


def running(simulator_id):
    process = _processes.get(simulator_id)
    return process is not None and process.poll() is None


def log_path(simulator_id):
    return log_dir() / f"simulador-{simulator_id}.log"


def start(simulator_id):
    """Start a simulator once; raise if it exits immediately (e.g. its ports are busy)."""
    if simulator_id not in SIMULATORS:
        raise ValueError(tr("Simulador desconocido: {simulator_id}", simulator_id=simulator_id))
    if running(simulator_id):
        return _processes[simulator_id]
    log_dir().mkdir(parents=True, exist_ok=True)
    output = open(log_path(simulator_id), "w", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(simulator_command(simulator_id), stdout=output, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, creationflags=flags)
    output.close()
    try:
        process.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        _processes[simulator_id] = process
        return process
    detail = log_path(simulator_id).read_text(encoding="utf-8", errors="replace").strip().splitlines()
    raise RuntimeError(detail[-1] if detail else tr("El simulador terminó con código {returncode}", returncode=process.returncode))


def stop(simulator_id):
    process = _processes.pop(simulator_id, None)
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def stop_all():
    for simulator_id in list(_processes):
        stop(simulator_id)


atexit.register(stop_all)
