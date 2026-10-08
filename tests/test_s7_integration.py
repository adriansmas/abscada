"""Uses real Snap7 TCP messages rather than a mocked client."""
import socket
import pytest
pytest.importorskip("snap7")
from plc_simulators.s7 import create_server
from abscada.project import Project
from abscada.runtime import Runtime
from test_core import DEMO, wait_for


def test_tcp_s7_runtime_reads_and_writes():
    # Find an available unprivileged port for a local integration server.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server, memory = create_server(port)
    project = Project.load(DEMO)
    project.connections = [dict(id="plc", protocol="s7", host="127.0.0.1", rack=0, slot=1, port=port, poll_ms=100)]
    project.variables = [
        dict(name="Run", type="bool", initial=False, writable=True, binding=dict(connection="plc", address="%DB1.DBX0.0")),
        dict(name="Setpoint", type="float", initial=0.0, writable=True, binding=dict(connection="plc", address="%DB1.DBD8"))]
    project.screens = {"overview": dict(width=100, height=100, elements=[])}
    project.faceplates = {}
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["Setpoint"].quality == "good")
        assert runtime.snapshot()["Setpoint"].value == 60.0
        runtime.write("Setpoint", 37.25)
        runtime.write("Run", True)
        wait_for(lambda: runtime.snapshot()["Setpoint"].value == 37.25 and runtime.snapshot()["Run"].value is True)
        assert memory[0] == 1
    finally:
        runtime.stop()
        server.stop()
        server.destroy()


def test_missing_plc_marks_values_bad_instead_of_generating_them():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    project = Project.load(DEMO)
    project.connections[0]["port"] = port
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["TankLevel"].quality == "bad")
        assert runtime.snapshot()["TankLevel"].value == 0.0
        assert runtime.snapshot()["TankLevel"].error
        assert runtime.snapshot()["Pump1.setpoint"].quality == "bad"
    finally:
        runtime.stop()
