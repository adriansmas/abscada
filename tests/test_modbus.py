import copy
import socket
import struct
import pytest
from abscada.modbus import ModbusTCP, DEFINITION, ENCODINGS, reorder
from abscada.project import Project
from abscada.runtime import Runtime
from test_core import DEMO, wait_for


@pytest.fixture
def modbus_server():
    pytest.importorskip("pyModbusTCP")
    from pyModbusTCP.server import ModbusServer
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = ModbusServer(host="127.0.0.1", port=port, no_block=True)
    server.start()
    try:
        yield server, dict(host="127.0.0.1", port=port, unit_id=1, timeout_ms=500)
    finally:
        server.stop()


@pytest.mark.parametrize("encoding,value", [("uint16", 65535), ("int16", -321),
    ("uint32", 4294967295), ("int32", -123456), ("float32", 37.25), ("float64", 0.125)])
@pytest.mark.parametrize("orders", [("big", "big"), ("big", "little"), ("little", "big"), ("little", "little")])
def test_tcp_numeric_roundtrip_and_wire_layout(modbus_server, encoding, value, orders):
    server, config = modbus_server
    adapter = ModbusTCP(config)
    kind = ENCODINGS[encoding][2]
    address = dict(area="holding_registers", offset=5, encoding=encoding,
                   byte_order=orders[0], word_order=orders[1])
    adapter.connect()
    try:
        adapter.write(address, kind, value)
        fmt, count, _ = ENCODINGS[encoding]
        expected = reorder(struct.pack(">"+fmt, value), address)
        assert server.data_bank.get_holding_registers(5, count) == [int.from_bytes(expected[i:i+2], "big") for i in range(0, len(expected), 2)]
        assert adapter.read(address, kind) == value
    finally:
        adapter.close()


def test_tcp_coils_discrete_inputs_and_input_registers(modbus_server):
    server, config = modbus_server
    adapter = ModbusTCP(config)
    adapter.connect()
    try:
        coil = dict(area="coils", offset=7, encoding="bool")
        adapter.write(coil, "bool", True)
        assert adapter.read(coil, "bool") is True
        assert server.data_bank.get_coils(6, 3) == [False, True, False]
        server.data_bank.set_discrete_inputs(3, [True])
        assert adapter.read(dict(area="discrete_inputs", offset=3, encoding="bool"), "bool") is True
        server.data_bank.set_input_registers(2, [65535])
        assert adapter.read(dict(area="input_registers", offset=2, encoding="int16"), "int") == -1
        with pytest.raises(ValueError, match="lectura"):
            adapter.write(dict(area="input_registers", offset=2, encoding="int16"), "int", 1)
    finally:
        adapter.close()


@pytest.mark.parametrize("address,kind,writable", [
    (dict(area="coils", offset=0, encoding="int16"), "int", False),
    (dict(area="holding_registers", offset=0, encoding="bool"), "bool", False),
    (dict(area="input_registers", offset=0, encoding="float32"), "float", True),
    (dict(area="discrete_inputs", offset=0, encoding="bool"), "bool", True),
    (dict(area="holding_registers", offset=65535, encoding="float32"), "float", False),
    (dict(area="holding_registers", offset=-1, encoding="int16"), "int", False),
    (dict(area="holding_registers", offset=0, encoding="float32", word_order="invalid"), "float", False),
    ("40001", "int", False),
])
def test_invalid_modbus_bindings(address, kind, writable):
    with pytest.raises(ValueError):
        DEFINITION.validate_binding(address, kind, writable)


def test_runtime_s7_and_modbus_simultaneously(plc_project, modbus_server, tmp_path):
    server, config = modbus_server
    project = copy.deepcopy(plc_project)
    project.connections.append(dict(id="meter", protocol="modbus_tcp", poll_ms=50, **config))
    project.variables.append(dict(name="Energy", type="int", initial=0, writable=True,
        binding=dict(connection="meter", version=1, address=dict(area="holding_registers", offset=10, encoding="uint32", byte_order="big", word_order="little"))))
    project.root = tmp_path
    project.save()
    project = Project.load(tmp_path)
    server.data_bank.set_holding_registers(10, [42, 0])
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["Energy"].quality == "good")
        wait_for(lambda: runtime.snapshot()["Pump1.setpoint"].quality == "good")
        assert runtime.snapshot()["Energy"].value == 42
        assert runtime.snapshot()["Pump1.setpoint"].value == 60
        runtime.write("Energy", 123456)
        wait_for(lambda: runtime.snapshot()["Energy"].value == 123456)
        server.stop()
        wait_for(lambda: runtime.snapshot()["Energy"].quality == "bad")
        assert runtime.snapshot()["Pump1.setpoint"].quality == "good"
    finally:
        runtime.stop()
    assert not any(worker.is_alive() for worker in runtime._workers)
