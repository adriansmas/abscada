"""Raw serial/TCP connector and Modbus RTU, against devices simulated over TCP and pyserial's loop://."""
import socket
import struct
import threading
import time
import pytest
from abscada.modbus_rtu import DEFINITION as RTU, ModbusRTU, crc16, frame, plan_reads
from abscada.project import Project
from abscada.protocol_definition import AddressError, GroupError
from abscada.runtime import Runtime
from abscada.serial_ascii import DEFINITION as RAW, SerialAscii
from abscada.serial_link import Framer, decode, encode, unescape
from test_core import wait_for


class Device:
    """TCP server that hands every received chunk to ``handle(data, send)`` on its own thread."""

    def __init__(self, handle):
        self.handle, self.received, self.clients = handle, b"", []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen()
        self.port = self.server.getsockname()[1]
        self.stopped = threading.Event()
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while not self.stopped.is_set():
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            self.clients.append(client)
            threading.Thread(target=self.serve, args=(client,), daemon=True).start()

    def serve(self, client):
        def send(data):
            try:
                client.sendall(data)
            except OSError:
                pass
        while not self.stopped.is_set():
            try:
                data = client.recv(4096)
            except OSError:
                return
            if not data:
                return
            self.received += data
            self.handle(data, send)

    def stop(self):
        self.stopped.set()
        for sock in [self.server] + self.clients:
            try:
                sock.close()
            except OSError:
                pass


def tcp(port, **extra):
    return dict(dict(transport="tcp", host="127.0.0.1", tcp_port=port, timeout_ms=500), **extra)


# --- Escapes and frames ------------------------------------------------------------------

def test_escapes_and_encodings():
    assert unescape("O8\\r\\n") == "O8\r\n"
    assert encode("\\x02A\\x03", "ascii") == b"\x02A\x03"
    assert encode("01 03 00 0a", "hex") == b"\x01\x03\x00\x0a"
    assert encode("peso €", "utf-8") == "peso €".encode()
    assert decode(b"\x01\xff", "hex") == "01 FF"
    with pytest.raises(ValueError):
        encode("zz", "hex")
    with pytest.raises(ValueError):
        encode("€", "ascii")


def test_framer_modes():
    lines = Framer("terminator", end=b"\r\n")
    assert lines.feed(b"+0012.3", 0) == []
    assert lines.feed(b"4 G S\r\n\r\n+1", 0) == [b"+0012.34 G S"]
    assert lines.feed(b"\r\n", 0) == [b"+1"]
    stx = Framer("start_end", start=b"\x02", end=b"\x03")
    assert stx.feed(b"basura\x02AB", 0) == []
    assert stx.feed(b"C\x03\x02D\x03", 0) == [b"ABC", b"D"]
    fixed = Framer("length", length=3)
    assert fixed.feed(b"abcdefg", 0) == [b"abc", b"def"]
    quiet = Framer("silence", silence=0.05)
    assert quiet.feed(b"ab", 0.0) == [] and quiet.feed(b"c", 0.01) == []
    assert quiet.expire(0.03) == [] and quiet.expire(0.07) == [b"abc"]
    assert quiet.feed(b"x", 1.0) == [] and quiet.feed(b"y", 2.0) == [b"x"]
    with pytest.raises(ValueError):
        Framer("terminator", end=b"")


# --- Raw connector -----------------------------------------------------------------------

@pytest.fixture
def scale():
    """A scale like the KERN PNS: O8 answers once, O1 streams, O0 stops; acks the rest."""
    streaming = threading.Event()
    weight = ["+0012.34 G S"]

    def handle(data, send):
        for command in data.decode().split("\r\n"):
            if command == "O8":
                send((weight[0] + "\r\n").encode())
            elif command == "O1":
                streaming.set()
            elif command == "O0":
                streaming.clear()
            elif command and command != "SIN":
                send(b"A00\r\n")
    device = Device(handle)

    def stream():
        while not device.stopped.is_set():
            if streaming.is_set():
                for client in list(device.clients):
                    try:
                        client.sendall((weight[0] + "\r\n").encode())
                    except OSError:
                        pass
            time.sleep(0.02)
    threading.Thread(target=stream, daemon=True).start()
    try:
        yield device, weight, streaming
    finally:
        device.stop()


def test_raw_bindings_are_generic():
    assert RAW.supports_type("string") and RAW.supports_type("int") and not RAW.supports_type("float")
    assert RAW.validate_binding({}, "string", False)["function"] == "rx"
    assert RAW.validate_binding({}, "int", False)["function"] == "count"
    with pytest.raises(ValueError, match="comando"):
        RAW.validate_binding(dict(function="request"), "string", False)
    with pytest.raises(ValueError, match="escritura"):
        RAW.validate_binding(dict(function="rx"), "string", True)
    assert RAW.describe(dict(function="request", command="O8"), "string").endswith(": O8")


def test_raw_request_response(scale):
    device, weight, _ = scale
    adapter = SerialAscii(tcp(device.port, suffix="\\r\\n"))
    adapter.connect()
    try:
        request = dict(function="request", command="O8")
        assert adapter.read(request, "string") == "+0012.34 G S"
        weight[0] = "-0001.00 G U"
        assert adapter.read(request, "string") == "-0001.00 G U"
        assert adapter.read(dict(function="rx"), "string") == "-0001.00 G U"
        assert adapter.read(dict(function="count"), "int") == 2
        assert adapter.read(dict(function="request", command="T"), "string") == "A00"
        with pytest.raises(AddressError, match="SIN"):
            adapter.read(dict(function="request", command="SIN"), "string")
    finally:
        adapter.close()


def test_raw_continuous_stream_send_and_close_command(scale):
    device, weight, streaming = scale
    adapter = SerialAscii(tcp(device.port, suffix="\\r\\n", on_connect="O1", on_close="O0"))
    adapter.connect()
    try:
        wait_for(lambda: adapter.read(dict(function="count"), "int") >= 3)
        assert adapter.read(dict(function="rx"), "string") == "+0012.34 G S"
        weight[0] = "+0020.00 G S"
        wait_for(lambda: adapter.read(dict(function="rx"), "string") == "+0020.00 G S")
        adapter.write(dict(function="send"), "string", "T")
        assert adapter.read(dict(function="send"), "string") == "T"
        wait_for(lambda: b"T\r\n" in device.received)
    finally:
        adapter.close()
    wait_for(lambda: not streaming.is_set())
    assert device.received.startswith(b"O1\r\n") and device.received.endswith(b"O0\r\n")
    adapter.close()  # idempotent


def test_raw_stale_line_and_lost_device(scale):
    device, _, _ = scale
    adapter = SerialAscii(tcp(device.port, stale_ms=150))
    adapter.connect()
    try:
        assert adapter.read(dict(function="rx"), "string") == ""
        time.sleep(0.25)
        with pytest.raises(ConnectionError, match="tramas"):
            adapter.read(dict(function="rx"), "string")
    finally:
        adapter.close()
    adapter = SerialAscii(tcp(device.port))
    adapter.connect()
    try:
        device.stop()
        wait_for(lambda: adapter.error is not None)
        with pytest.raises(ConnectionError):
            adapter.read(dict(function="rx"), "string")
    finally:
        adapter.close()


def test_raw_over_a_serial_port_url():
    pytest.importorskip("serial")
    adapter = SerialAscii(dict(transport="serial", port="loop://", baudrate=115200, framing="start_end",
                               start="\\x02", terminator="\\x03", timeout_ms=500))
    adapter.connect()
    try:
        adapter.write(dict(function="send"), "string", "\\x02hola\\x03")
        wait_for(lambda: adapter.read(dict(function="rx"), "string") == "hola")
        assert adapter.read(dict(function="request", command="\\x02eco\\x03"), "string") == "eco"
    finally:
        adapter.close()


def test_runtime_reads_frames_and_sends_commands(scale, tmp_path):
    device, _, _ = scale
    variables = [dict(name="BasculaTrama", type="string", initial="", writable=False,
                      binding=dict(connection="scale", version=1, address=dict(function="rx"))),
                 dict(name="BasculaOrden", type="string", initial="", writable=True,
                      binding=dict(connection="scale", version=1, address=dict(function="send")))]
    connection = dict(id="scale", protocol="serial_ascii", poll_ms=50, **tcp(device.port, suffix="\\r\\n", on_connect="O1"))
    project = Project(tmp_path, dict(schema_version=1, name="Bascula", startup_screen="main"), {}, variables,
                      [connection], {"main": dict(width=100, height=100, elements=[])}, {})
    project.validate()
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["BasculaTrama"].value == "+0012.34 G S")
        wait_for(lambda: runtime.snapshot()["BasculaOrden"].quality == "good")
        runtime.write("BasculaOrden", "T").result(3)
        wait_for(lambda: b"T\r\n" in device.received)
    finally:
        runtime.stop()


# --- Modbus RTU --------------------------------------------------------------------------

def test_crc_matches_the_specification_example():
    assert frame(1, 3, bytes.fromhex("0000000A")).hex() == "01030000000ac5cd"
    assert crc16(bytes.fromhex("01030000000ac5cd")) == 0


class RtuSlaves:
    """Slave 1 answers, slave 2 is silent, slave 3 answers every request with exception 2."""

    def __init__(self):
        self.registers = {1: [0] * 200}
        self.coils = {1: [False] * 64}
        self.requests = []
        self.device = Device(self.handle)

    def handle(self, data, send):
        unit, function = data[0], data[1]
        assert crc16(data) == 0
        self.requests.append((unit, function))
        if unit == 2:
            return
        if unit == 3:
            send(frame(unit, function | 0x80, b"\x02"))
            return
        start, value = struct.unpack(">HH", data[2:6])
        regs, coils = self.registers[unit], self.coils[unit]
        if function in (3, 4):
            send(frame(unit, function, bytes([value * 2]) + b"".join(struct.pack(">H", r) for r in regs[start:start + value])))
        elif function in (1, 2):
            bits = coils[start:start + value]
            packed = bytes(sum(1 << i for i, b in enumerate(bits[n:n + 8]) if b) for n in range(0, len(bits), 8))
            send(frame(unit, function, bytes([len(packed)]) + packed))
        elif function == 5:
            coils[start] = value == 0xFF00
            send(frame(unit, function, data[2:6]))
        elif function == 6:
            regs[start] = value
            send(frame(unit, function, data[2:6]))
        elif function == 16:
            for i in range(value):
                regs[start + i] = struct.unpack(">H", data[7 + 2 * i:9 + 2 * i])[0]
            send(frame(unit, function, data[2:6]))


@pytest.fixture
def slaves():
    bus = RtuSlaves()
    try:
        yield bus
    finally:
        bus.device.stop()


def test_rtu_plan_groups_contiguous_data_of_one_slave():
    binding = lambda **a: RTU.validate_binding(a, "float" if a.get("encoding") == "float32" else "int", False)
    addresses = [(binding(unit_id=1, offset=0, encoding="float32"), "float"),
                 (binding(unit_id=1, offset=2, encoding="int16"), "int"),
                 (binding(unit_id=1, offset=10, encoding="int16"), "int"),
                 (binding(unit_id=2, offset=3, encoding="int16"), "int")]
    plan = [(unit, area, start, count, [m[0] for m in members]) for unit, area, start, count, members in plan_reads(addresses)]
    assert plan == [(1, "holding_registers", 0, 3, [0, 1]), (1, "holding_registers", 10, 1, [2]),
                    (2, "holding_registers", 3, 1, [3])]


def test_rtu_reads_writes_and_reports_slave_errors(slaves):
    adapter = ModbusRTU(tcp(slaves.device.port, single_register="fc06"))
    adapter.connect()
    try:
        level = dict(unit_id=1, area="holding_registers", offset=4, encoding="float32")
        adapter.write(level, "float", 12.5)
        assert adapter.read(level, "float") == 12.5
        assert (1, 16) in slaves.requests
        adapter.write(dict(unit_id=1, offset=9, encoding="int16"), "int", -2)
        assert (1, 6) in slaves.requests and slaves.registers[1][9] == 65534
        coil = dict(unit_id=1, area="coils", offset=11, encoding="bool")
        adapter.write(coil, "bool", True)
        assert adapter.read(coil, "bool") is True and slaves.coils[1][11]
        with pytest.raises(ConnectionError, match="no responde"):
            adapter.read(dict(unit_id=2, offset=0, encoding="int16"), "int")
        with pytest.raises(ConnectionError, match="excepción Modbus 2"):
            adapter.read(dict(unit_id=3, offset=0, encoding="int16"), "int")
        groups = adapter.prepare_reads([(level, "float"), (dict(unit_id=2, offset=0, encoding="int16"), "int")])
        assert groups[0]() == {0: 12.5}
        with pytest.raises(GroupError) as failed:
            groups[1]()
        assert failed.value.indices == [1]
    finally:
        adapter.close()


def test_runtime_keeps_answering_slaves_when_one_is_silent(slaves, tmp_path):
    slaves.registers[1][0] = 321
    variables = [dict(name="Caudal", type="int", initial=0, writable=True,
                      binding=dict(connection="bus", version=1, address=dict(unit_id=1, offset=0, encoding="int16"))),
                 dict(name="Muerto", type="int", initial=0, writable=False,
                      binding=dict(connection="bus", version=1, address=dict(unit_id=2, offset=0, encoding="int16")))]
    connection = dict(id="bus", protocol="modbus_rtu", poll_ms=50, **tcp(slaves.device.port, timeout_ms=100))
    project = Project(tmp_path, dict(schema_version=1, name="RTU", startup_screen="main"), {}, variables,
                      [connection], {"main": dict(width=100, height=100, elements=[])}, {})
    project.validate()
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["Caudal"].value == 321 and runtime.snapshot()["Caudal"].quality == "good")
        wait_for(lambda: runtime.snapshot()["Muerto"].quality == "bad")
        assert "no responde" in runtime.snapshot()["Muerto"].error
        runtime.write("Caudal", 7).result(3)
        wait_for(lambda: runtime.snapshot()["Caudal"].value == 7)
        assert runtime.snapshot()["Caudal"].quality == "good"
    finally:
        runtime.stop()
