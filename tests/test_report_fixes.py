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


def test_renaming_a_screen_only_in_letter_case_keeps_its_file(tmp_path):
    project = Project.load(DEMO)
    project.root = tmp_path
    project.save()
    project.screens["OVERVIEW"] = project.screens.pop("overview")
    project.manifest["startup_screen"] = "OVERVIEW"
    project.save()
    assert "OVERVIEW.json" in [p.name for p in (tmp_path / "screens").iterdir()]
    assert "OVERVIEW" in Project.load(tmp_path).screens


def test_orphan_save_lock_of_a_dead_process_is_taken_over(tmp_path):
    project = Project.load(DEMO)
    project.root = tmp_path
    project.save()
    (tmp_path / ".abscada-save.lock").write_text("999999", encoding="ascii")
    project.manifest["name"] = "Otro nombre"
    project.save()
    assert not (tmp_path / ".abscada-save.lock").exists()


def test_disabled_or_locked_account_is_named_only_with_its_password(tmp_path):
    from abscada.security import AuthenticationError, UserStore, default_security
    policy = default_security()
    store = UserStore(tmp_path / "users.json")
    store.create("ana", "Clave-segura-123", ["operator"], policy, must_change=False)
    store._update("ana", lambda user: user.update(disabled=True))
    with pytest.raises(AuthenticationError, match="incorrectos"):
        store.authenticate("ana", "otra", policy)
    with pytest.raises(AuthenticationError, match="desactivado"):
        store.authenticate("ana", "Clave-segura-123", policy)


@pytest.mark.parametrize("example", ["hydro", "brewery"])
def test_parameters_offered_as_read_only_pass_the_popup_validation(example):
    from pathlib import Path
    from abscada.dynamics import parameter_writable
    from abscada.operation_windows import validate_popup_writes
    project = Project.load(Path(DEMO).parent / example)
    tags = project.tags()
    checked = 0
    for name, template in project.faceplates.items():
        parameters = template.get("parameters", {})
        if not parameters or any(kind not in ("bool", "int", "float", "string") for kind in parameters.values()):
            continue
        # Every parameter linked to a read-only variable wherever the editor would allow it.
        bindings = {}
        for parameter, kind in parameters.items():
            writable = parameter_writable(template, parameter, project.faceplates)
            choice = next((n for n, t in tags.items() if t["type"] == kind and t.get("writable", False) == writable), None)
            choice = choice or next((n for n, t in tags.items() if t["type"] == kind and (t.get("writable") or not writable)), None)
            if choice is None:
                break
            bindings[parameter] = choice
        else:
            validate_popup_writes(dict(id="x", template=name, bindings=bindings), project, tags)
            checked += 1
    assert checked


def test_names_cannot_start_with_a_dollar_or_have_spaces_at_the_ends():
    from abscada.structures import valid_name
    assert valid_name("Bomba1") and valid_name("Bomba 1")
    assert not valid_name("$motor") and not valid_name(" Bomba") and not valid_name("Bomba ")


def test_runtime_window_refreshes_only_items_of_changed_variables(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from abscada.runtime_window import RuntimeWindow
    project = Project.load(DEMO)
    project.root = tmp_path
    project.connections = []
    for variable in project.variables:
        variable.pop("binding", None); variable.pop("bindings", None)
    window = RuntimeWindow(project)
    try:
        window.refresh()   # first tick: everything
        refreshed = []
        for item in window.items_shown:
            item.refresh_state = lambda item=item: refreshed.append(item)
        window.refresh()
        assert refreshed == []   # nothing changed, nothing redrawn
        window.runtime.write("Operator", "Ana")
        window.refresh()
        assert refreshed and all("Operator" in item.dependencies for item in refreshed)
    finally:
        window.runtime.stop() if window.running else None
        window.close()
