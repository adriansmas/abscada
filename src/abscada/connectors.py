"""Protocol adapters; called only from the runtime worker thread."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import re
import struct
from .protocol_definition import Field, ProtocolDefinition


class Connector(Protocol):
    def connect(self): ...
    def read(self, address: dict | str, kind: str): ...
    def write(self, address: dict | str, kind: str, value): ...
    def close(self): ...




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
        raise ValueError(f"Dirección S7 inválida: {text}; ejemplos %DB1.DBW0, %DB1.DBD4 o %DB1.DBX0.0")
    db, kind, offset, bit = match.groups()
    if int(db) < 1 or (kind == "X" and (bit is None or int(bit) > 7)) or (kind != "X" and bit is not None):
        raise ValueError(f"Dirección S7 inválida: {text}")
    if standard and kind == "D" and value_type == "float":
        kind = "R"
    return Address(int(db), int(offset), kind, int(bit or 0))


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
        data = self.client.db_read(a.db, a.offset, a.size)
        if a.kind == "X":
            return bool(data[0] & (1 << a.bit))
        return struct.unpack({"B": ">B", "W": ">h", "D": ">i", "R": ">f"}[a.kind], data)[0]

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
        raise ValueError("El dato excede el rango del DB")


def describe_s7(address, kind):
    a = normalize_s7(address, kind)
    width = {"bool": "X", "uint8": "B", "int16": "W", "int32": "D", "float32": "D"}[a["encoding"]]
    return f"%DB{a['db']}.DB{width}{a['offset']}" + (f".{a.get('bit', 0)}" if width == "X" else "")


S7.definition = ProtocolDefinition(
    "Siemens S7",
    (Field("host", "IP / host", "127.0.0.1"), Field("port", "Puerto TCP", 102, 1, 65535),
     Field("rack", "Rack", 0, 0, 7), Field("slot", "Slot", 1, 0, 31)),
    (Field("db", "DB", 1, 1, 65535), Field("offset", "Byte", 0, 0, 65535),
     Field("encoding", "Codificación", "float32", choices=(("bool", "BOOL", ("bool",)),
          ("uint8", "BYTE", ("int",)), ("int16", "INT", ("int",)),
          ("int32", "DINT", ("int",)), ("float32", "REAL", ("float",)))),
     Field("bit", "Bit", 0, 0, 7, kinds=("bool",))), normalize_s7, check_s7, describe_s7)

from .modbus import ModbusTCP
from .ads import TwinCatADS

REGISTRY = {"s7": S7, "modbus_tcp": ModbusTCP, "ads": TwinCatADS}


def definition(protocol):
    return REGISTRY[protocol].definition


def binding_summary(binding, connections, kind):
    if not binding:
        return "—"
    config = next(c for c in connections if c["id"] == binding["connection"])
    spec = definition(config["protocol"])
    return spec.describe(spec.validate_binding(binding["address"], kind, False), kind)


def register(protocol, factory):
    if protocol in REGISTRY:
        raise ValueError(f"Protocolo ya registrado: {protocol}")
    if not isinstance(getattr(factory, "definition", None), ProtocolDefinition):
        raise ValueError("El adaptador necesita una ProtocolDefinition")
    REGISTRY[protocol] = factory
