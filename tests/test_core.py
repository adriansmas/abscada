import copy
import time
from pathlib import Path
import pytest
from abscada.project import Project, coerce
from abscada.runtime import Runtime
from abscada.connectors import parse_address, S7, register, REGISTRY

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo"


def wait_for(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Condition did not become true")


def test_structures_faceplates_and_roundtrip(tmp_path):
    project = Project.load(DEMO)
    assert len(project.tags()) == 8
    assert project.tags()["Pump1.running"]["type"] == "bool"
    elements = list(project.elements("overview"))
    assert next(e for e in elements if e["id"] == "pump2.command")["tag"] == "Pump2.running"
    project.root = tmp_path
    project.save()
    reloaded = Project.load(tmp_path)
    assert reloaded.tags() == project.tags()
    assert list(reloaded.elements("overview")) == elements


def test_validation_rejects_references_and_cycles():
    project = Project.load(DEMO)
    project.screens["overview"]["elements"][0]["tag"] = "missing"
    with pytest.raises(ValueError, match="inexistente"):
        project.validate()
    project = Project.load(DEMO)
    project.types["Cycle"] = {"child": "Cycle"}
    with pytest.raises(ValueError, match="recursivo"):
        project.validate()


def test_s7_write_read_and_readonly(plc_project):
    runtime = Runtime(plc_project)
    with pytest.raises(ValueError, match="solo lectura"):
        runtime.write("TankLevel", 10)
    runtime.write("Operator", "Alice")
    assert runtime.snapshot()["Operator"].value == "Alice"
    with pytest.raises(ValueError, match="solo lectura"):
        runtime.write("Pump1.flow", 50)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["Pump1.setpoint"].quality == "good")
        runtime.write("Pump1.setpoint", "42.5")
        wait_for(lambda: runtime.snapshot()["Pump1.setpoint"].value == 42.5)
        assert runtime.write_results()[0][1] is True
        with pytest.raises(ValueError):
            runtime.write("Pump1.running", "maybe")
    finally:
        runtime.stop()


def test_fault_marks_all_connection_tags_bad_and_reconnects():
    class Broken:
        definition = S7.definition
        instances = 0
        def __init__(self, config):
            Broken.instances += 1
        def connect(self):
            if Broken.instances == 1:
                raise ConnectionError("offline")
        def read(self, address, kind):
            return {"bool": False, "float": 12.0}[kind]
        def close(self):
            pass
    register("test_broken", Broken)
    project = Project.load(DEMO)
    project.connections[0]["protocol"] = "test_broken"
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["TankLevel"].quality == "bad")
        assert runtime.snapshot()["TankLevel"].error == "offline"
        runtime.write("Pump1.setpoint", 99)
        wait_for(lambda: bool(runtime._results))
        assert runtime.write_results()[0][1] is False
        wait_for(lambda: runtime.snapshot()["TankLevel"].quality == "good")
        assert runtime.snapshot()["TankLevel"].value == 12
    finally:
        runtime.stop()
        del REGISTRY["test_broken"]


@pytest.mark.parametrize("address", ["DB1.X0.8", "DB0.R4", "DB1.R4.0", "DB1.X0", "invalid"])
def test_invalid_addresses(address):
    with pytest.raises(ValueError):
        parse_address(address)


def test_s7_endianness_and_preserve_neighbor_bits():
    class MemoryClient:
        memory = bytearray(20)
        def db_read(self, db, start, size):
            return self.memory[start:start+size]
        def db_write(self, db, start, data):
            self.memory[start:start+len(data)] = data
    s7 = S7({})
    s7.client = MemoryClient()
    s7.client.memory[0] = 0b10100000
    s7.write("DB1.X0.1", "bool", True)
    assert s7.client.memory[0] == 0b10100010
    assert s7.read("DB1.X0.1", "bool") is True
    s7.write("DB1.R4", "float", 42.5)
    assert s7.read("DB1.R4", "float") == 42.5
    s7.write("DB1.W8", "int", -123)
    assert s7.read("DB1.W8", "int") == -123
    s7.write("DB1.D12", "int", -123456)
    assert s7.read("DB1.D12", "int") == -123456
    s7.write("%DB1.DBB2", "int", 255)
    assert s7.read("%DB1.DBB2", "int") == 255


@pytest.mark.parametrize("value, kind", [("NaN", "float"), ("1.5", "int"), (True, "int"), ("yes", "bool")])
def test_bad_values(value, kind):
    with pytest.raises((ValueError, TypeError)):
        coerce(value, kind)


def test_asset_cannot_escape_project():
    with pytest.raises(ValueError):
        Project.load(DEMO).asset("../../outside.png")


@pytest.mark.parametrize("text, kind, expected", [
    ("%db1.dbw0", "int", (1, 0, "W", 0)),
    (" DB2.DBD8 ", "float", (2, 8, "R", 0)),
    ("%DB2.DBD8", "int", (2, 8, "D", 0)),
    ("%DB3.DBX10.7", "bool", (3, 10, "X", 7)),
    ("%DB1.DBB4", "int", (1, 4, "B", 0)),
    ("DB1.R4", "float", (1, 4, "R", 0)),
])
def test_siemens_absolute_addresses(text, kind, expected):
    a = parse_address(text, kind)
    assert (a.db, a.offset, a.kind, a.bit) == expected


@pytest.mark.parametrize("text", ["%DB1.DBX0.8", "%DB0.DBW0", "%DB1.DBW0.1", "%DB1.DBX0", "PLC.Temperature"])
def test_bad_siemens_absolute_addresses(text):
    with pytest.raises(ValueError):
        parse_address(text)


def test_structured_field_configuration_keeps_other_fields(tmp_path):
    project = Project.load(DEMO)
    original = copy.deepcopy(project.tags()["Pump1.running"])
    project.connections.append(dict(id="siemens", protocol="s7", host="127.0.0.1"))
    project.configure_tag("Pump1.flow", "18.5", False, dict(connection="siemens", address="%DB2.DBD4"))
    project.validate()
    assert project.tags()["Pump1.flow"]["binding"]["address"] == "%DB2.DBD4"
    assert project.tags()["Pump1.flow"]["initial"] == 18.5
    assert project.tags()["Pump1.running"]["binding"] == original["binding"]
    project.root = tmp_path
    project.save()
    assert Project.load(tmp_path).tags()["Pump1.flow"]["binding"]["connection"] == "siemens"
    project.set_binding("Pump1.flow", None)
    assert "binding" not in project.tags()["Pump1.flow"]


def test_absolute_address_type_mismatch_rejected():
    project = Project.load(DEMO)
    project.connections.append(dict(id="siemens", protocol="s7", host="127.0.0.1"))
    project.set_binding("Pump1.flow", dict(connection="siemens", address="%DB1.DBW0"))
    with pytest.raises(ValueError, match="incompatible"):
        project.validate()


def test_internal_simulator_protocol_is_not_available():
    assert "simulator" not in REGISTRY
    project = Project.load(DEMO)
    project.connections[0]["protocol"] = "simulator"
    with pytest.raises(ValueError, match="Protocolo desconocido"):
        project.validate()
