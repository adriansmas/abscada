import time
from threading import Event
import pytest
from abscada.connectors import REGISTRY, S7, register, definition
from abscada.protocol_definition import Field, ProtocolDefinition
from abscada.project import Project
from abscada.runtime import Runtime
from test_core import DEMO, wait_for


def test_structured_s7_encoding_is_independent_of_tag_type():
    assert S7.definition.validate_binding("%DB3.DBD8", "float", False) == dict(db=3, offset=8, encoding="float32")
    with pytest.raises(ValueError):
        S7.definition.validate_binding(dict(db=1, offset=0, encoding="int16"), "float", False)


def test_future_protocol_owns_schema_without_changes_to_project_or_editor(tmp_path):
    """A test-only symbol adapter proves the extension contract, not ADS support."""
    class SymbolAdapter:
        definition = ProtocolDefinition("Test symbols", (Field("target", "Target", "device"),),
            (Field("symbol", "Symbol", "MAIN.level"),), lambda a, k: dict(a),
            lambda a, k, w: None, lambda a, k: a["symbol"])
    register("test_symbols", SymbolAdapter)
    try:
        project = Project.load(DEMO)
        project.connections = [dict(id="symbols", protocol="test_symbols", target="machine", poll_ms=100)]
        for name, tag in project.tags().items():
            if tag.get("binding"):
                project.set_binding(name, dict(connection="symbols", version=1, address=dict(symbol="MAIN."+name)))
        project.root = tmp_path
        project.save()
        assert Project.load(tmp_path).tags()["TankLevel"]["binding"]["address"] == {"symbol": "MAIN.TankLevel"}
        from PySide6.QtWidgets import QApplication, QLineEdit
        from abscada.protocol_editor import ProtocolForm
        app = QApplication.instance() or QApplication([])
        form = ProtocolForm(definition("test_symbols").fields_for("float"), dict(symbol="MAIN.test"), "float")
        assert form.findChild(QLineEdit, "protocol_symbol").text() == "MAIN.test"
        form.close()
        project.set_binding("TankLevel", dict(connection="symbols", version=99, address=dict(symbol="MAIN.test")))
        with pytest.raises(ValueError, match="versión"):
            project.validate()
    finally:
        del REGISTRY["test_symbols"]


def test_slow_connection_cannot_delay_other_cycles():
    entered, release = Event(), Event()
    calls = []
    class Adapter:
        definition = S7.definition
        def __init__(self, config):
            self.slow = config["id"] == "slow"
        def connect(self):
            pass
        def read(self, address, kind):
            if self.slow:
                entered.set()
                release.wait(3)
            else:
                calls.append(time.monotonic())
            return 1.0
        def close(self):
            pass
    register("test_isolation", Adapter)
    runtime = None
    try:
        project = Project.load(DEMO)
        project.connections = [dict(id=id, protocol="test_isolation", host="localhost", poll_ms=cycle) for id, cycle in [("slow", 500), ("fast", 50)]]
        project.variables = [dict(name=id, type="float", initial=0.0, writable=False,
             binding=dict(connection=id, address="%DB1.DBD0")) for id in ["slow", "fast"]]
        project.faceplates = {}
        project.screens["overview"]["elements"] = []
        runtime = Runtime(project)
        runtime.start()
        assert entered.wait(1)
        wait_for(lambda: len(calls) >= 5, timeout=1)
        assert runtime.snapshot()["slow"].quality == "uncertain"
        assert runtime.snapshot()["fast"].quality == "good"
        assert calls[4] - calls[0] < 0.7
    finally:
        release.set()
        if runtime:
            runtime.stop()
        del REGISTRY["test_isolation"]
