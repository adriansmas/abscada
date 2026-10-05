"""Beckhoff TwinCAT ADS: definition, AMS/TCP client and Runtime against the pure-Python simulator."""
import struct
import time

import pytest
from abscada.ads import AdsClient, AdsError, TwinCatADS, decode, encode, net_id_bytes, raw_address
from abscada.ads_simulator import AdsSimulator
from abscada.connectors import REGISTRY, definition
from abscada.project import Project
from abscada.runtime import Runtime
from test_core import wait_for

SYMBOLS = {
    "MAIN.bRun": ("BOOL", True),
    "MAIN.nCount": ("DINT", -42),
    "MAIN.wFlags": ("WORD", 0xBEEF),
    "MAIN.iSmall": ("SINT", -5),
    "MAIN.rTemp": ("REAL", 21.5),
    "MAIN.lrPrecise": ("LREAL", 3.141592653589793),
    "GVL.sName": ("STRING", "Línea 1", 20),
}


@pytest.fixture
def sim():
    server = AdsSimulator(SYMBOLS, port=0).start()
    yield server
    server.stop()


def config(sim, **extra):
    return dict(dict(id="plc", protocol="ads", host="127.0.0.1", port=sim.port, ams_net_id="127.0.0.1.1.1",
                     ams_port=851, local_ams_net_id="auto", timeout_ms=1000, poll_ms=100), **extra)


def test_registered_and_validates_bindings():
    assert REGISTRY["ads"] is TwinCatADS
    spec = definition("ads")
    assert spec.validate_binding("MAIN.rTemp", "float", False) == {"symbol": "MAIN.rTemp", "encoding": "REAL"}
    assert spec.validate_binding({"symbol": "GVL.aData[3].nValue", "encoding": "DINT"}, "int", True)["encoding"] == "DINT"
    assert spec.validate_binding({"symbol": "GVL.s", "encoding": "STRING"}, "string", False)["length"] == 80
    assert spec.validate_binding("0x4020:8", "int", False)["encoding"] == "INT"
    with pytest.raises(ValueError, match="inválido"):
        spec.validate_binding("MAIN bad", "float", False)
    with pytest.raises(ValueError):
        spec.validate_binding({"symbol": "MAIN.x", "encoding": "REAL"}, "bool", False)
    assert spec.describe({"symbol": "GVL.s", "encoding": "STRING", "length": 20}, "string") == "GVL.s · STRING(20)"


def test_codec_and_helpers():
    a = {"symbol": "x", "encoding": "UINT"}
    assert decode(a, encode(a, "int", 65535)) == 65535
    with pytest.raises(ValueError, match="no cabe"):
        encode(a, "int", 70000)
    s = {"symbol": "x", "encoding": "STRING", "length": 4}
    assert encode(s, "string", "abcdef") == b"abcd\x00" and decode(s, b"ab\x00zz") == "ab"
    assert raw_address("0xF030:4") == (0xF030, 4) and raw_address("MAIN.x") is None
    assert net_id_bytes("5.80.201.232.1.1") == bytes([5, 80, 201, 232, 1, 1])
    with pytest.raises(ValueError):
        net_id_bytes("5.80.201.232.1")


def test_adapter_reads_and_writes_every_type(sim):
    adapter = TwinCatADS(config(sim))
    adapter.connect()
    try:
        for name, (encoding, value, *_) in SYMBOLS.items():
            kind = {"BOOL": "bool", "REAL": "float", "LREAL": "float", "STRING": "string"}.get(encoding, "int")
            address = {"symbol": name, "encoding": encoding, **({"length": 20} if encoding == "STRING" else {})}
            got = adapter.read(address, kind)
            assert got == pytest.approx(value) if kind == "float" else got == value
        adapter.write({"symbol": "MAIN.rTemp", "encoding": "REAL"}, "float", 55.25)
        adapter.write({"symbol": "GVL.sName", "encoding": "STRING", "length": 20}, "string", "Prueba ñ")
        adapter.write({"symbol": "main.brun", "encoding": "BOOL"}, "bool", False)  # TwinCAT names are case-insensitive
        assert sim.get("MAIN.rTemp") == 55.25 and sim.get("GVL.sName") == "Prueba ñ" and sim.get("MAIN.bRun") is False
        # Raw %MB area through index group/offset
        adapter.write({"symbol": "0x4020:10", "encoding": "INT"}, "int", -1234)
        assert struct.unpack_from("<h", sim.areas[0x4020], 10)[0] == -1234
        assert adapter.read({"symbol": "0x4020:10", "encoding": "INT"}, "int") == -1234
        assert len(adapter.handles) == 7
    finally:
        adapter.close()
    assert not sim.handles, "handles must be released on close"


def test_stale_handles_are_resolved_again(sim):
    adapter = TwinCatADS(config(sim))
    adapter.connect()
    try:
        address = {"symbol": "MAIN.nCount", "encoding": "DINT"}
        assert adapter.read(address, "int") == -42
        old = adapter.handles["main.ncount"]
        sim.online_change()
        sim.set("MAIN.nCount", 7)
        assert adapter.read(address, "int") == 7
        assert adapter.handles["main.ncount"] != old
    finally:
        adapter.close()


def test_errors_are_explicit(sim):
    adapter = TwinCatADS(config(sim))
    adapter.connect()
    with pytest.raises(AdsError, match="símbolo no encontrado · MAIN.missing"):
        adapter.read({"symbol": "MAIN.missing", "encoding": "REAL"}, "float")
    adapter.close()
    with pytest.raises(AdsError, match="puerto ADS de destino"):
        TwinCatADS(config(sim, ams_port=801)).connect()
    sim.running = False
    with pytest.raises(ConnectionError, match="no está en RUN"):
        TwinCatADS(config(sim)).connect()
    client = AdsClient("127.0.0.1", "127.0.0.1.1.1", tcp_port=sim.port)
    client.open()
    assert client.read_state()[0] == 6
    client.close()


def test_beckhoff_example_matches_generator_and_reads_demo_plc(tmp_path):
    import importlib.util
    import threading
    from pathlib import Path
    from abscada.ads_simulator import DEMO_SYMBOLS, run_demo
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_beckhoff", root / "tools" / "build_beckhoff.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    shipped = Project.load(root / "examples/beckhoff")
    generated = builder.build_project(tmp_path / "beckhoff")
    assert generated.tags() == shipped.tags() and generated.screens == shipped.screens
    demo = AdsSimulator(DEMO_SYMBOLS, port=0).start()
    stop = threading.Event()
    threading.Thread(target=run_demo, args=(demo, stop), daemon=True).start()
    generated.connections[0]["port"] = demo.port
    runtime = Runtime(generated)
    try:
        runtime.start()
        wait_for(lambda: all(s.quality == "good" for s in runtime.snapshot().values()), timeout=5)
        assert runtime.snapshot()["Banco.Estado"].value == "PARADO"
        runtime.write("Banco.Consigna", 1200.0).result(3)
        runtime.write("Banco.Marcha", True).result(3)
        wait_for(lambda: runtime.snapshot()["Banco.Velocidad"].value > 100, timeout=5)
    finally:
        runtime.stop()
        stop.set()
        demo.stop()


def test_runtime_acquisition_and_commands(sim, tmp_path):
    variables = [
        dict(name="Run", type="bool", initial=False, writable=True,
             binding=dict(connection="plc", version=1, address={"symbol": "MAIN.bRun", "encoding": "BOOL"})),
        dict(name="Temp", type="float", initial=0.0, writable=False,
             binding=dict(connection="plc", version=1, address={"symbol": "MAIN.rTemp", "encoding": "REAL"})),
        dict(name="Name", type="string", initial="", writable=True,
             binding=dict(connection="plc", version=1, address={"symbol": "GVL.sName", "encoding": "STRING", "length": 20})),
    ]
    project = Project(tmp_path / "ads", dict(schema_version=1, name="ADS", startup_screen="main"), {}, variables, [config(sim)],
                      {"main": dict(width=100, height=100, elements=[])}, {})
    project.validate()
    runtime = Runtime(project)
    try:
        runtime.start()
        wait_for(lambda: runtime.snapshot()["Temp"].quality == "good" and runtime.snapshot()["Temp"].value == 21.5, timeout=5)
        runtime.write("Run", False).result(3)
        runtime.write("Name", "Lote 7").result(3)
        wait_for(lambda: runtime.snapshot()["Run"].value is False and runtime.snapshot()["Name"].value == "Lote 7", timeout=5)
        sim.stop()  # PLC disappears: quality goes bad, last value kept
        wait_for(lambda: runtime.snapshot()["Temp"].quality == "bad", timeout=6)
        assert runtime.snapshot()["Temp"].value == 21.5
    finally:
        runtime.stop()
    time.sleep(0.1)
