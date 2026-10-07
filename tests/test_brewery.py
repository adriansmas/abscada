"""examples/brewery: generated project, brewery model, recipes, roles and live OPC UA acquisition."""
import importlib.util
import socket
import sys
from pathlib import Path

import pytest
from abscada import pki
from abscada.project import Project
from abscada.security import required_permission
from abscada.simulators import SIMULATORS
from abscada.simulators.brewery import DT, Brewery
from abscada.simulators.brewery_map import (BREWHOUSE_FIELDS, FERMENTER_FIELDS, FERMENTERS, OBJECTS,
                                            RECIPE_EDITOR_FIELDS, SERVICES_FIELDS, node)

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


def run(plant, seconds, until=None, confirm=True):
    for _ in range(int(seconds / DT)):
        if confirm and plant.v["Cocina"]["EsperaOperador"]:
            plant.v["Cocina"]["OrdenConfirmar"] = True
        plant.scan()
        if until and until():
            return True
    return False


def test_shipped_project_matches_generator(tmp_path):
    shipped = Project.load(ROOT / "examples/brewery")
    generated = tool("build_brewery").build_project(tmp_path / "brewery")
    assert generated.tags() == shipped.tags()
    assert generated.screens == shipped.screens
    assert generated.alarms == shipped.alarms
    assert generated.security == shipped.security and generated.opcua_server == shipped.opcua_server
    with pytest.raises(ValueError, match="ya existe"):
        tool("build_brewery").build_project(generated.root)


def test_bindings_follow_the_shared_address_space():
    project = Project.load(ROOT / "examples/brewery")
    tags = project.tags()
    for obj, fields in OBJECTS:
        for name, kind, writable in fields:
            tag = tags[f"{obj}.{name}"]
            assert tag["binding"]["address"] == dict(node=node(obj, name))
            assert tag["type"] == kind and tag["writable"] == writable
    (connection,) = project.connections
    assert connection["protocol"] == "opcua" and connection["security"] == "Basic256Sha256_SignAndEncrypt"
    assert SIMULATORS["cerveceria"].example == "brewery"


def test_security_is_on_and_only_brewers_edit_recipes():
    project = Project.load(ROOT / "examples/brewery")
    assert project.security["enabled"] and project.opcua_server["enabled"]
    roles = {r["id"]: set(r["permissions"]) for r in project.security["roles"]}
    assert "recipes" in roles["maestro"] and "recipes" not in roles["operador"]
    assert roles["mes"] == {"opcua"}
    editor = project.screens["40_recetas"]["elements"]
    writes = [e for e in editor if e.get("tag", "").startswith("Recetas.") and e.get("tag") != "Recetas.Numero"
              and e["kind"] in ("input", "button")]
    assert writes and all(required_permission(e) == "recipes" for e in writes)
    # Choosing which recipe to brew is an operator's job.
    brewhouse = project.screens["20_cocina"]["elements"]
    assert all(required_permission(e) == "operate" for e in brewhouse if e.get("tag") == "Cocina.RecetaSeleccionada")


def test_demo_accounts_come_with_the_project():
    from abscada.security import SecurityService
    project = Project.load(ROOT / "examples/brewery")
    service = SecurityService(project)
    accounts = tool("build_brewery").DEMO_ACCOUNTS
    assert {u["name"] for u in service.store.users()} == {name for name, *_ in accounts}
    for name, _, role, password in accounts:
        session = service.login(name, password)
        assert session.roles == (role,) and not session.must_change
    assert "recipes" in service.login("maestro", "Tolva-Maestro-2026").permissions
    assert "recipes" not in service.login("operador", "Tolva-Operador-2026").permissions


def test_a_full_brew_reaches_the_fermenter_with_the_recipe_gravity():
    plant = Brewery()
    c = plant.v["Cocina"]
    plant.scan()
    assert c["ListoIniciar"] and plant.v["FV3"]["Fase"] == 0
    c.update(RecetaSeleccionada=1, OrdenIniciar=True)
    seen = set()
    assert run(plant, 400, lambda: seen.add(c["Paso"]) or (c["Paso"] == 0 and 12 in seen))
    assert seen >= set(range(13))  # Rubia has a protein rest: every step runs
    fv = plant.v["FV3"]
    assert fv["Fase"] == 2 and fv["Lote"] == 1042 and fv["NombreReceta"] == "Rubia"
    assert fv["DensidadOriginal"] == pytest.approx(12.0, abs=0.2)
    assert fv["Nivel"] == pytest.approx(10.0)
    assert not c["ListoIniciar"]  # FV3 is now busy


def test_rests_hold_their_temperature_and_the_kettle_boils_the_recipe_time():
    plant = Brewery()
    c = plant.v["Cocina"]
    c.update(RecetaSeleccionada=3, OrdenIniciar=True)  # IPA: 75 min at 65 °C, 75 min boil
    assert run(plant, 200, lambda: c["Paso"] == 4 and c["TiempoPaso"] > 30)
    assert c["TempMT"] == pytest.approx(65.0, abs=0.6) and not c["FueraTemperaturaMT"]
    assert run(plant, 300, lambda: c["Paso"] == 9)
    boiling = []
    assert run(plant, 300, lambda: boiling.append(c["Paso"]) or c["Paso"] == 10)
    assert (len(boiling) - 1) * DT == pytest.approx(75.0, abs=0.5)  # 1 recipe minute = 1 s
    assert c["DensidadMosto"] == pytest.approx(15.5, abs=0.2)


def test_fermentation_follows_the_phases_of_the_recipe():
    plant = Brewery()
    fv = plant.v["FV1"]  # IPA on day 2.5
    phases = []
    assert run(plant, 900, lambda: phases.append(fv["Fase"]) or fv["Fase"] == 6)
    assert [p for i, p in enumerate(phases) if i == 0 or phases[i - 1] != p] == [2, 3, 4, 5, 6]
    assert fv["Temperatura"] == pytest.approx(1.0, abs=0.5) and fv["Densidad"] == pytest.approx(2.8, abs=0.35)
    assert not fv["Alarma"]
    fv["OrdenVaciar"] = True
    assert run(plant, 20, lambda: fv["Fase"] == 0)
    assert fv["Nivel"] == 0 and fv["Lote"] == 0


@pytest.mark.parametrize("fault, flag, seconds", [
    ("SimSobrepresion", "Presion", 60),
    ("SimValvulaAtascada", "Desviacion", 60),
    ("SimFermentacionParada", "FermentacionParada", 150),
])
def test_cellar_faults_raise_the_fermenter_alarm(fault, flag, seconds):
    plant = Brewery()
    fv = plant.v["FV3"]
    plant.fill("FV3", plant.recipes[0], 1050, 12.0, day=0.8)
    run(plant, 30)
    assert not fv["Alarma"]
    fv[fault] = True
    assert run(plant, seconds, lambda: fv["Alarma"])
    assert fv[flag] if flag == "FermentacionParada" else fv[flag] > 1.5


def test_a_healthy_fermentation_is_never_reported_as_stuck():
    plant = Brewery()
    plant.fill("FV3", plant.recipes[1], 1050, 13.5, day=0.0)
    assert not run(plant, 420, lambda: plant.v["FV3"]["FermentacionParada"] or plant.v["FV1"]["FermentacionParada"])


def test_boil_over_and_stuck_lauter_are_detected():
    plant = Brewery()
    c = plant.v["Cocina"]
    c.update(RecetaSeleccionada=2, OrdenIniciar=True, SimLechoColmatado=True)
    assert run(plant, 200, lambda: c["PresionLecho"] > 200)
    assert c["Rastrillos"] and c["AlarmaCocina"]
    c["SimLechoColmatado"] = False
    c["SimEspuma"] = True
    assert run(plant, 400, lambda: c["NivelEspuma"] > 80)
    run(plant, 2)
    assert c["VaporBK"] == pytest.approx(40.0)  # the PLC backs off the steam


def test_services_faults_block_the_brewhouse_and_warm_the_glycol():
    plant = Brewery()
    s = plant.v["Servicios"]
    s["SimFalloCaldera"] = True
    assert run(plant, 30, lambda: s["PresionVapor"] < 4)
    assert not plant.v["Cocina"]["ListoIniciar"] and s["AlarmaServicios"]
    s["SimFalloEnfriadora"] = True
    assert run(plant, 120, lambda: s["TempGlicol"] > 0)
    s.update(SimFalloCaldera=False, SimFalloEnfriadora=False, SimFugaGlicol=True)
    assert run(plant, 200, lambda: s["FalloEnfriadora"])
    assert s["NivelGlicol"] < 20


def test_recipe_manager_loads_clamps_saves_and_discards():
    plant = Brewery()
    r = plant.v["Recetas"]
    r["Numero"] = 3
    plant.scan()
    assert r["Nombre"] == "IPA" and not r["Modificada"]
    r["TiempoHervido"] = 500.0
    plant.scan()
    assert r["Modificada"]
    r["OrdenGuardar"] = True
    plant.scan()
    assert plant.recipes[2]["TiempoHervido"] == 120.0 and r["TiempoHervido"] == 120.0 and not r["Modificada"]
    r["TempGuarda"] = 4.0
    r["OrdenDescartar"] = True
    plant.scan()
    assert r["TempGuarda"] == 1.0 and not r["Modificada"]
    # A brew uses the copy taken at start: saving afterwards does not change it.
    plant.v["Cocina"].update(RecetaSeleccionada=3, OrdenIniciar=True)
    plant.scan()
    plant.scan()
    assert r["EnUso"]
    r["TiempoHervido"] = 60.0
    r["OrdenGuardar"] = True
    plant.scan()
    assert plant.batch["TiempoHervido"] == 120.0


def test_live_acquisition_over_encrypted_opcua(tmp_path):
    pytest.importorskip("asyncua")
    from abscada.connectors import create
    from abscada.simulators.brewery import BreweryServer

    server = BreweryServer(port=free_port(), folder=tmp_path / "simulador").start()
    try:
        config = dict(Project.load(ROOT / "examples/brewery").connections[0], endpoint=server.endpoint)
        root = tmp_path / "proyecto"
        root.mkdir()
        with pytest.raises(pki.UntrustedCertificate):
            create(config, root).connect()  # the first time the administrator has to trust the PLC
        (rejected,) = pki.listing(root, "rejected")
        assert rejected["uri"].endswith(":latolva:plc")
        pki.trust(root, rejected["path"].read_bytes())
        adapter = create(config, root)
        adapter.connect()
        try:
            assert adapter.read(node("Cocina", "NombreReceta"), "string") == "Tostada"
            assert adapter.read(node("FV1", "Fase"), "int") == 2
            adapter.write(node("Cocina", "RecetaSeleccionada"), "int", 4)
            adapter.write(node("Cocina", "OrdenIniciar"), "bool", True)
            import time
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and adapter.read(node("Cocina", "Paso"), "int") == 0:
                time.sleep(0.1)
            assert adapter.read(node("Cocina", "RecetaLote"), "string") == "Negra"
            assert adapter.read(node("Cocina", "OrdenIniciar"), "bool") is False  # pulses are cleared by the PLC
        finally:
            adapter.close()
    finally:
        server.stop()


def test_every_field_is_published():
    plant = Brewery()
    published = plant.published()
    for obj, fields in OBJECTS:
        for name, *_ in fields:
            assert f"{obj}.{name}" in published
    assert len(published) == len(BREWHOUSE_FIELDS) + 3 * len(FERMENTER_FIELDS) + len(SERVICES_FIELDS) + len(RECIPE_EDITOR_FIELDS)
    assert FERMENTERS == ("FV1", "FV2", "FV3")
