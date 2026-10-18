"""Protocol adapters; called only from the runtime worker thread.

An adapter offers connect(), read(address, kind), write(address, kind, value) and close().
It may also offer prepare_reads(requests): see ``read_groups``.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
import struct
from .protocol_definition import Field, ProtocolDefinition
from .i18n import tr


@dataclass(frozen=True)
class Address:
    db: int
    offset: int
    kind: str
    bit: int = 0

    @property
    def size(self):
        return {"X": 1, "B": 1, "W": 2, "D": 4, "R": 4}[self.kind]


def parse_address(text, value_type=None):
    """Siemens absolute notation; DBD is REAL when the tag type is float."""
    if isinstance(text, dict):
        text = S7.definition.validate_binding(text, value_type, False)
        return Address(text["db"], text["offset"], {"bool": "X", "uint8": "B", "int16": "W", "int32": "D", "float32": "R"}[text["encoding"]], text.get("bit", 0))
    text = text.strip().upper()
    standard = re.fullmatch(r"%?DB(\d+)\.DB([XBWD])(\d+)(?:\.(\d))?", text)
    match = standard or re.fullmatch(r"DB(\d+)\.(X|B|W|D|R)(\d+)(?:\.(\d))?", text)
    if not match:
        raise ValueError(tr("Dirección S7 inválida: {text}; ejemplos %DB1.DBW0, %DB1.DBD4 o %DB1.DBX0.0", text=text))
    db, kind, offset, bit = match.groups()
    if int(db) < 1 or (kind == "X" and (bit is None or int(bit) > 7)) or (kind != "X" and bit is not None):
        raise ValueError(tr("Dirección S7 inválida: {text}", text=text))
    if standard and kind == "D" and value_type == "float":
        kind = "R"
    return Address(int(db), int(offset), kind, int(bit or 0))


def _decode(a, data, start):
    """Value of ``a`` inside ``data``, which begins at byte ``start`` of the DB."""
    position = a.offset - start
    if a.kind == "X":
        return bool(data[position] & (1 << a.bit))
    return struct.unpack_from({"B": ">B", "W": ">h", "D": ">i", "R": ">f"}[a.kind], data, position)[0]


# Smallest PDU a S7 CPU negotiates; python-snap7 answers (pdu_length - 18) data bytes per request.
S7_MIN_PDU = 240
S7_READ_OVERHEAD = 18


def plan_s7_reads(addresses, max_block):
    """Group S7 addresses into blocks of one DB without reading gaps.

    Returns ``[(db, start, size, [(index, address), ...]), ...]``. Overlapping or contiguous
    ranges share a block while it stays within ``max_block`` bytes; a value is never split.
    """
    spans = sorted(((a.db, a.offset, a.offset + a.size, index, a) for index, a in enumerate(addresses)),
                   key=lambda s: s[:3])
    blocks = []
    for db, begin, end, index, a in spans:
        last = blocks[-1] if blocks else None
        if last and last[0] == db and begin <= last[2] and max(end, last[2]) - last[1] <= max_block:
            last[2] = max(end, last[2])
            last[3].append((index, a))
        else:
            blocks.append([db, begin, end, [(index, a)]])
    return [(db, begin, end - begin, members) for db, begin, end, members in blocks]


class S7:
    def __init__(self, config):
        self.config = config
        self.client = None

    def connect(self):
        import snap7
        self.client = snap7.Client()
        self.client.connect(self.config["host"], int(self.config.get("rack", 0)),
                            int(self.config.get("slot", 1)), int(self.config.get("port", 102)))

    def read(self, address, kind):
        a = parse_address(address, kind)
        return _decode(a, self._db_read(a.db, a.offset, a.size), a.offset)

    def max_block(self):
        """Bytes per read that python-snap7 sends as a single request with the negotiated PDU."""
        pdu = getattr(self.client, "pdu_length", 0) or S7_MIN_PDU
        return max(4, pdu - S7_READ_OVERHEAD)

    def prepare_reads(self, requests):
        """One read per block of contiguous bytes; bits of one byte are read once."""
        addresses = [parse_address(address, kind) for address, kind in requests]
        return [lambda db=db, start=start, size=size, members=members: self._read_block(db, start, size, members)
                for db, start, size, members in plan_s7_reads(addresses, self.max_block())]

    def _read_block(self, db, start, size, members):
        data = self._db_read(db, start, size)
        return {index: _decode(a, data, start) for index, a in members}

    def _db_read(self, db, start, size):
        data = self.client.db_read(db, start, size)
        if len(data) != size:
            raise ConnectionError(tr("Respuesta S7 incompleta: DB{db}, byte {start}, {got} de {size} bytes",
                                     db=db, start=start, got=len(data), size=size))
        return data

    def write(self, address, kind, value):
        a = parse_address(address, kind)
        if a.kind == "X":
            data = bytearray(self.client.db_read(a.db, a.offset, 1))
            mask = 1 << a.bit
            data[0] = (data[0] | mask) if value else (data[0] & ~mask)
        else:
            data = bytearray(struct.pack({"B": ">B", "W": ">h", "D": ">i", "R": ">f"}[a.kind], value))
        self.client.db_write(a.db, a.offset, data)

    def close(self):
        if self.client:
            self.client.disconnect()
            self.client.destroy()
            self.client = None


def normalize_s7(address, kind):
    if isinstance(address, dict):
        return dict(address)
    a = parse_address(address, kind)
    result = dict(db=a.db, offset=a.offset, encoding={"X": "bool", "B": "uint8", "W": "int16", "D": "int32", "R": "float32"}[a.kind])
    if a.kind == "X":
        result["bit"] = a.bit
    return result


def check_s7(address, kind, writable):
    if address["offset"] + {"bool": 1, "uint8": 1, "int16": 2, "int32": 4, "float32": 4}[address["encoding"]] > 65536:
        raise ValueError(tr("El dato excede el rango del DB"))


def describe_s7(address, kind):
    a = normalize_s7(address, kind)
    width = {"bool": "X", "uint8": "B", "int16": "W", "int32": "D", "float32": "D"}[a["encoding"]]
    return f"%DB{a['db']}.DB{width}{a['offset']}" + (f".{a.get('bit', 0)}" if width == "X" else "")


S7.definition = ProtocolDefinition(
    tr("Siemens S7"),
    (Field("host", tr("IP / host"), "127.0.0.1"), Field("port", tr("Puerto TCP"), 102, 1, 65535),
     Field("rack", tr("Rack"), 0, 0, 7), Field("slot", tr("Slot"), 1, 0, 31)),
    (Field("db", tr("DB"), 1, 1, 65535), Field("offset", tr("Byte"), 0, 0, 65535),
     Field("encoding", tr("Codificación"), "float32", choices=(("bool", "BOOL", ("bool",)),
          ("uint8", "BYTE", ("int",)), ("int16", "INT", ("int",)),
          ("int32", "DINT", ("int",)), ("float32", "REAL", ("float",)))),
     Field("bit", tr("Bit"), 0, 0, 7, kinds=("bool",))), normalize_s7, check_s7, describe_s7)

from .modbus import ModbusTCP
from .ads import TwinCatADS
from .opcua import OpcUaClient
from .modbus_rtu import ModbusRTU
from .serial_ascii import SerialAscii

REGISTRY = {"s7": S7, "modbus_tcp": ModbusTCP, "ads": TwinCatADS, "opcua": OpcUaClient,
            "modbus_rtu": ModbusRTU, "serial_ascii": SerialAscii}


def definition(protocol):
    return REGISTRY[protocol].definition


def create(config, project_root=None):
    """Instantiate an adapter. Adapters that keep per-installation files (certificates,
    passwords) receive the project folder through ``attach``."""
    adapter = REGISTRY[config["protocol"]](config)
    if project_root is not None and hasattr(adapter, "attach"):
        adapter.attach(project_root)
    return adapter


def read_groups(adapter, requests):
    """Reads for one acquisition cycle over ``requests`` = [(address, kind), ...].

    Returns callables; each performs one read and returns {request index: value}. Adapters
    with ``prepare_reads`` group requests themselves; the rest read one request per call.
    Prepare once per connection and reuse every cycle.
    """
    prepare = getattr(adapter, "prepare_reads", None)
    if prepare:
        return prepare(requests)
    return [lambda index=index, address=address, kind=kind: {index: adapter.read(address, kind)}
            for index, (address, kind) in enumerate(requests)]


def binding_summary(binding, connections, kind):
    if not binding:
        return "—"
    config = next(c for c in connections if c["id"] == binding["connection"])
    spec = definition(config["protocol"])
    return spec.describe(spec.validate_binding(binding["address"], kind, False), kind)


def register(protocol, factory):
    if protocol in REGISTRY:
        raise ValueError(tr("Protocolo ya registrado: {protocol}", protocol=protocol))
    if not isinstance(getattr(factory, "definition", None), ProtocolDefinition):
        raise ValueError(tr("El adaptador necesita una ProtocolDefinition"))
    REGISTRY[protocol] = factory
