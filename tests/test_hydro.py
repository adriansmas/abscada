"""examples/hydro: generated project, plant model and live TCP acquisition."""
import importlib.util
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from abscada.project import Project
from abscada.runtime import Runtime
from abscada.storage import ArchiveReader, ProjectSampleReader, database_path
from test_core import wait_for

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(plant, seconds, until=None):
    for _ in range(int(seconds / tool("hydro_plc").DT)):
        plant.scan()
        if until and until():
            return True
    return False


def test_shipped_project_matches_generator(tmp_path):
    shipped = Project.load(ROOT / "examples/hydro")
    generated = tool("build_hydro").build_project(tmp_path / "hydro")
    assert generated.tags() == shipped.tags()
    assert generated.screens == shipped.screens
    assert generated.alarms == shipped.alarms
    with pytest.raises(ValueError, match="ya existe"):
        tool("build_hydro").build_project(generated.root)


def test_bindings_follow_the_shared_memory_map():
    project = Project.load(ROOT / "examples/hydro")
    tags = project.tags()
    hydro_map = tool("hydro_map")
    for unit in ("G1", "G2"):
        for field, kind, address, writable in hydro_map.UNIT_FIELDS:
            tag = tags[f"{unit}.{field}"]
            assert tag["binding"]["address"] == address and tag["type"] == kind and tag["writable"] == writable
    assert {c["id"]: c["port"] for c in project.connections} == hydro_map.PORTS


def test_start_stop_and_trip_sequences():
    plant = tool("hydro_plc").Plant()
    unit = plant.units[0]
    run(plant, 5)
    assert unit.db["ListoArranque"]
    unit.db["OrdenArranque"] = True
    assert run(plant, 60, lambda: unit.db["Paso"] == 6), "no llega a «En carga»"
    assert unit.db["Interruptor52G"] and abs(unit.db["Tension"] - 6.3) < 0.2
    run(plant, 40)
    assert abs(unit.db["Potencia"] - unit.db["ConsignaP"]) < 0.2
    unit.db["OrdenParada"] = True
    assert run(plant, 90, lambda: unit.db["Paso"] == 0), "la parada normal no termina"
    assert not unit.db["Disparo"] and unit.db["ValvulaCerrada"] and unit.db["Frenos"]
    unit.db["OrdenArranque"] = True
    run(plant, 60, lambda: unit.db["Paso"] == 6)
    plant.common["SimFalloRed"] = True
    assert run(plant, 2, lambda: unit.db["Paso"] == 10)
    assert unit.db["CausaDisparo"] == 7 and not plant.common["Interruptor52L"]
    plant.common["SimFalloRed"] = False
    run(plant, 40)
    unit.db["OrdenRearme"] = True
    run(plant, 1)
    assert unit.db["Paso"] == 0 and not unit.db["ListoArranque"], "sin 52L cerrado no debe estar listo"
    plant.common["OrdenCerrar52L"] = True
    run(plant, 1)
    assert unit.db["ListoArranque"]


def test_live_acquisition_commands_alarms_and_scripts(tmp_path):
    plcs = tool("hydro_plc").HydroPLCs(ports={name: free_port() for name in tool("hydro_map").PORTS}).start()
    project = tool("build_hydro").build_project(tmp_path / "hydro")
    for connection in project.connections:
        connection["port"] = plcs.ports[connection["id"]]
    runtime = Runtime(project)
    try:
        runtime.start()
        wait_for(lambda: all(s.quality == "good" for n, s in runtime.snapshot().items() if n.startswith(("G1.", "SSCC.", "Contador."))), timeout=10)
        wait_for(lambda: runtime.snapshot()["Sistema.ComTodas"].value and runtime.snapshot()["Sistema.Hora"].value, timeout=5)
        runtime.write("G1.ConsignaP", 6.0).result(3)
        runtime.write("G1.OrdenArranque", True).result(3)
        wait_for(lambda: runtime.snapshot()["G1.Paso"].value == 6, timeout=60)
        wait_for(lambda: runtime.snapshot()["Sistema.PotenciaTotal"].value > 5.5, timeout=40)
        # Plant control redistributes the setpoint through a project script.
        runtime.write("Planta.ConsignaPlanta", 9.0).result(3)
        runtime.write("Planta.ControlConjunto", True).result(3)
        wait_for(lambda: runtime.snapshot()["G1.ConsignaP"].value == 9.0, timeout=8)
        # Emergency stop: trip alarm with lockout cause.
        runtime.write("G1.OrdenEmergencia", True).result(3)
        wait_for(lambda: runtime.snapshot()["G1.Paso"].value == 10, timeout=5)
        reader = ArchiveReader(database_path(project))
        wait_for(lambda: any(a["alarm_id"] == "g1_disparo" for a in reader.alarms()), timeout=5)
        assert runtime.snapshot()["G1.CausaDisparo"].value == 1
        wait_for(lambda: bool(ProjectSampleReader(project).samples("G1.Potencia", 0, time.time() + 1)), timeout=6)
        assert not [d for d in runtime.scripts.diagnostics() if d["status"] == "error"]
    finally:
        runtime.stop()
        plcs.stop()


def test_synthetic_history_spans_a_week(tmp_path):
    project = tool("build_hydro").build_project(tmp_path / "hydro")
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    days = tool("seed_hydro_history").seed(project, now)
    assert len(days) == 7
    samples = ProjectSampleReader(project).raw_samples("G1.Potencia", days[0].timestamp(), now.timestamp())
    assert len(samples) == 7 * 24 * 60
    values = [float(s["value"]) for s in samples]
    assert max(values) > 9 and min(values) == 0
    with pytest.raises(ValueError, match="no se sobrescribe"):
        tool("seed_hydro_history").seed(project, now)
