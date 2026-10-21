"""Regressions from the October 2026 review: acquisition, archive and storage faults."""
import math
import time
import pytest
from abscada.connectors import REGISTRY, S7, register
from abscada.project import Project
from abscada.protocol_definition import AddressError
from abscada.runtime import Runtime
from test_core import DEMO, wait_for
from test_operations import operational_project  # noqa: F401  (fixture)


def fake_adapter(name, values):
    """An adapter whose reads come from ``values`` (address -> value or exception), counting connects."""
    class Fake:
        definition = S7.definition
        connects = 0
        writes = []
        def __init__(self, config):
            pass
        def connect(self):
            Fake.connects += 1
        def read(self, address, kind):
            value = values.get(address, {"bool": False, "float": 12.0, "int": 1, "string": ""}[kind])
            if isinstance(value, Exception):
                raise value
            return value
        def write(self, address, kind, value):
            Fake.writes.append((address, value))
        def close(self):
            pass
    register(name, Fake)
    return Fake


@pytest.fixture
def faked(tmp_path):
    created = []
    def make(values):
        name = f"test_fake_{len(created)}"
        adapter = fake_adapter(name, values)
        created.append(name)
        project = Project.load(DEMO)
        project.root = tmp_path   # its own runtime lock, apart from the example
        project.connections[0]["protocol"] = name
        project.connections[0]["poll_ms"] = 50
        return adapter, Runtime(project)
    yield make
    for name in created:
        REGISTRY.pop(name, None)


def address_of(runtime, name):
    return runtime.tags[name]["binding"]["address"]


def test_nan_or_bad_address_marks_only_its_variable(faked):
    project = Project.load(DEMO)
    tags = project.tags()
    level = tags["TankLevel"]["binding"]["address"]
    setpoint = tags["Pump1.setpoint"]["binding"]["address"]
    adapter, runtime = faked({level: math.nan, setpoint: AddressError("símbolo no encontrado")})
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["Pump1.running"].quality == "good")
        time.sleep(0.3)
        snapshot = runtime.snapshot()
        assert snapshot["TankLevel"].quality == "bad" and "finito" in snapshot["TankLevel"].error
        assert snapshot["Pump1.setpoint"].quality == "bad" and "símbolo" in snapshot["Pump1.setpoint"].error
        assert runtime.status()[project.connections[0]["id"]] == "Conectado"
        # No reconnection loop: the connection stayed open.
        assert adapter.connects == 1
        # The faulty address refuses orders; the rest of the connection takes them.
        with pytest.raises(ValueError, match="Dirección con error"):
            runtime.write("Pump1.setpoint", 5).result(timeout=3)
        runtime.write("Pump1.running", True).result(timeout=3)
    finally:
        runtime.stop()


def test_unchanged_readings_keep_their_sample_and_report_changes(faked):
    adapter, runtime = faked({})
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["TankLevel"].quality == "good")
        revision, everything = runtime.changes(None)
        assert everything is None
        first = runtime.sample("TankLevel")
        time.sleep(0.25)
        assert runtime.sample("TankLevel") is first
        assert runtime.changes(revision)[1] == set()
        runtime.write("Operator", "Ana")
        assert runtime.changes(revision)[1] == {"Operator"}
    finally:
        runtime.stop()


def test_full_order_queue_gives_a_message(faked, monkeypatch):
    from queue import Full
    adapter, runtime = faked({})
    runtime.start()
    try:
        connection = runtime.tags["Pump1.setpoint"]["binding"]["connection"]
        monkeypatch.setattr(runtime._writes[connection], "put_nowait", lambda item: (_ for _ in ()).throw(Full()))
        with pytest.raises(ValueError, match="Cola de órdenes llena"):
            runtime.write("Pump1.setpoint", 3)
    finally:
        monkeypatch.undo()
        runtime.stop()


def test_lease_is_released_when_stop_times_out(faked, monkeypatch):
    adapter, runtime = faked({})
    runtime.start()
    monkeypatch.setattr(runtime.scripts, "stop", lambda timeout: (_ for _ in ()).throw(TimeoutError("lento")))
    with pytest.raises(TimeoutError):
        runtime.stop()
    from abscada.storage import RuntimeLease
    lease = RuntimeLease(runtime.project.root / "runtime" / "runtime.lock")
    lease.acquire()
    lease.close()


def test_failed_acknowledgement_keeps_archiving(operational_project):
    from abscada.operations import Operations
    service = Operations(operational_project)
    service.start()
    try:
        with pytest.raises(ValueError, match="operador"):
            service.acknowledge([1], " ")
        assert service.thread.is_alive() and not service.error
        assert service.acknowledge([12345], "Ana") == 0
    finally:
        service.stop()


def test_full_archive_queue_merges_samples_and_recovers(operational_project, monkeypatch):
    from queue import Full
    from abscada.operations import Operations
    from abscada.runtime import Sample
    service = Operations(operational_project)
    service.start()
    try:
        monkeypatch.setattr(service.queue, "put_nowait", lambda item: (_ for _ in ()).throw(Full()))
        service.submit("Level", Sample(1.0, "good", time.time()))
        service.submit("Level", Sample(2.0, "good", time.time()))
        assert service.dropped == 1 and "sobrecargado" in service.notice()
        monkeypatch.undo()
        wait_for(lambda: service.queue.empty() and not service._overflow, timeout=10)
        assert not service.error
        assert service.acknowledge([12345], "Ana") == 0
    finally:
        service.stop()
