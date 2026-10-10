"""Grouped S7 acquisition: one read per block of contiguous bytes, same decoded values."""
import socket
import struct
import time
import pytest
from abscada.connectors import S7, parse_address, plan_s7_reads, read_groups
from abscada.project import Project
from abscada.runtime import Runtime
from test_core import DEMO, wait_for


class MemoryClient:
    """In-memory DB client that records every db_read call."""
    def __init__(self, pdu_length=480, size=200, short=False):
        self.pdu_length = pdu_length
        self.dbs = {1: bytearray(size), 2: bytearray(size)}
        self.calls = []
        self.short = short

    def db_read(self, db, start, size):
        self.calls.append((db, start, size))
        data = self.dbs[db][start:start + size]
        return data[:-1] if self.short else data

    def db_write(self, db, start, data):
        self.dbs[db][start:start + len(data)] = data


def adapter(**options):
    s7 = S7({})
    s7.client = MemoryClient(**options)
    return s7


def read_all(groups):
    values = {}
    for read in groups:
        values.update(read())
    return values


def test_eight_bits_of_one_byte_read_once():
    s7 = adapter()
    s7.client.dbs[1][3] = 0b10100101
    groups = read_groups(s7, [(f"%DB1.DBX3.{bit}", "bool") for bit in range(8)])
    assert read_all(groups) == {bit: bool(0b10100101 & (1 << bit)) for bit in range(8)}
    assert s7.client.calls == [(1, 3, 1)]


def test_ten_consecutive_reals_in_one_read():
    s7 = adapter()
    for i in range(10):
        struct.pack_into(">f", s7.client.dbs[1], 20 + 4 * i, i - 4.5)
    groups = read_groups(s7, [(f"%DB1.DBD{20 + 4 * i}", "float") for i in range(10)])
    assert read_all(groups) == {i: i - 4.5 for i in range(10)}
    assert s7.client.calls == [(1, 20, 40)]


def test_values_match_individual_reads_for_every_type_and_notation():
    s7 = adapter()
    memory = s7.client.dbs[1]
    memory[0] = 0b10000010
    memory[2] = 255
    struct.pack_into(">h", memory, 4, -123)
    struct.pack_into(">i", memory, 6, -123456)
    struct.pack_into(">f", memory, 10, -42.5)
    struct.pack_into(">i", memory, 14, 7)
    requests = [("%DB1.DBX0.1", "bool"), ("DB1.X0.7", "bool"), ("DB1.X0.0", "bool"), ("%DB1.DBB2", "int"),
                ("DB1.W4", "int"), ("%DB1.DBD6", "int"), ("%DB1.DBD10", "float"), ("DB1.R10", "float"),
                ("%DB1.DBD14", "int"), (dict(db=1, offset=4, encoding="int16"), "int")]
    individual = [s7.read(address, kind) for address, kind in requests]
    s7.client.calls.clear()
    values = read_all(read_groups(s7, requests))
    assert [values[i] for i in range(len(requests))] == individual == [True, True, False, 255, -123, -123456, -42.5, -42.5, 7, -123]
    # Byte 0, byte 2 and 4..17 are separated by gaps (bytes 1 and 3), which are not read.
    assert s7.client.calls == [(1, 0, 1), (1, 2, 1), (1, 4, 14)]


def test_blocks_split_by_db_gaps_overlaps_and_size_limit():
    a = [parse_address(text, "float" if "D" in text else "int") for text in
         ("%DB2.DBW0", "%DB1.DBD0", "%DB1.DBW2", "%DB1.DBD4", "%DB1.DBW10", "%DB1.DBD12", "%DB1.DBD16")]
    plan = plan_s7_reads(a, max_block=8)
    assert [(db, start, size) for db, start, size, _ in plan] == [(1, 0, 8), (1, 10, 6), (1, 16, 4), (2, 0, 2)]
    assert [sorted(i for i, _ in members) for *_, members in plan] == [[1, 2, 3], [4, 5], [6], [0]]
    # Duplicated addresses share their block.
    assert plan_s7_reads([a[1], a[1]], 8) == [(1, 0, 4, [(0, a[1]), (1, a[1])])]


def test_block_limit_follows_negotiated_pdu():
    s7 = adapter(pdu_length=240, size=300)
    assert s7.max_block() == 222
    # 60 REAL = 240 bytes: 55 fit in 222 bytes without splitting one, the other 5 go in a second read.
    values = read_all(read_groups(s7, [(f"%DB1.DBD{4 * i}", "float") for i in range(60)]))
    assert len(values) == 60
    assert s7.client.calls == [(1, 0, 220), (1, 220, 20)]
    assert adapter(pdu_length=480).max_block() == 462


def test_incomplete_response_raises_instead_of_publishing():
    s7 = adapter(short=True)
    groups = read_groups(s7, [("%DB1.DBD0", "float"), ("%DB1.DBD4", "float")])
    with pytest.raises(ConnectionError, match="incompleta"):
        read_all(groups)
    with pytest.raises(ConnectionError):
        s7.read("%DB1.DBD0", "float")


def test_adapters_without_grouping_read_one_request_per_call():
    class Plain:
        def __init__(self):
            self.calls = []
        def read(self, address, kind):
            self.calls.append(address)
            return len(self.calls)
    plain = Plain()
    groups = read_groups(plain, [("a", "int"), ("b", "int")])
    assert len(groups) == 2 and read_all(groups) == {0: 1, 1: 2} and plain.calls == ["a", "b"]


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_runtime_reads_s7_blocks_over_tcp(monkeypatch):
    pytest.importorskip("snap7")
    from plc_simulators.s7 import create_server
    port = free_port()
    server, memory = create_server(port)
    memory[0] = 0b00000101
    struct.pack_into(">f", memory, 12, 12.5)
    calls = []
    original = S7._db_read
    monkeypatch.setattr(S7, "_db_read", lambda self, db, start, size: calls.append((db, start, size)) or original(self, db, start, size))
    project = Project.load(DEMO)
    project.connections = [dict(id="plc", protocol="s7", host="127.0.0.1", rack=0, slot=1, port=port, poll_ms=50)]
    project.variables = ([dict(name=f"Bit{b}", type="bool", initial=False, writable=True,
                               binding=dict(connection="plc", address=f"%DB1.DBX0.{b}")) for b in range(8)]
                         + [dict(name=f"Real{o}", type="float", initial=0.0, writable=True,
                                 binding=dict(connection="plc", address=f"%DB1.DBD{o}")) for o in (4, 8, 12)])
    project.screens = {"overview": dict(width=100, height=100, elements=[])}
    project.faceplates = {}
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["Real12"].quality == "good")
        snapshot = runtime.snapshot()
        assert [snapshot[f"Bit{b}"].value for b in range(8)] == [True, False, True, False, False, False, False, False]
        assert (snapshot["Real8"].value, snapshot["Real12"].value) == (60.0, 12.5)
        # One cycle: byte 0 alone (bytes 1..3 are a gap) and bytes 4..15 together.
        assert set(calls) == {(1, 0, 1), (1, 4, 12)}
        # Writes keep their contract and are read back by the next cycle.
        runtime.write("Bit1", True).result(timeout=3)
        runtime.write("Real8", 37.25).result(timeout=3)
        wait_for(lambda: runtime.snapshot()["Bit1"].value is True and runtime.snapshot()["Real8"].value == 37.25)
        assert memory[0] == 0b00000111
        # Losing the PLC marks every variable bad and keeps the last values.
        server.stop()
        wait_for(lambda: runtime.snapshot()["Real8"].quality == "bad", timeout=5)
        assert runtime.snapshot()["Real8"].value == 37.25 and runtime.snapshot()["Bit0"].quality == "bad"
        # The same port comes back: the plan is prepared again and values become good.
        server.start(tcp_port=port)
        wait_for(lambda: runtime.snapshot()["Real8"].quality == "good", timeout=6)
    finally:
        runtime.stop()
        server.stop()
        server.destroy()
