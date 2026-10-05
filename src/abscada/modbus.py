"""Modbus TCP plugin. Register offsets are always zero-based, never 4xxxx references."""
import struct
from .protocol_definition import Field, ProtocolDefinition


ENCODINGS = {"uint16": ("H", 1, "int"), "int16": ("h", 1, "int"),
             "uint32": ("I", 2, "int"), "int32": ("i", 2, "int"),
             "float32": ("f", 2, "float"), "float64": ("d", 4, "float"),
             "bool": (None, 1, "bool")}
AREAS = ("coils", "discrete_inputs", "holding_registers", "input_registers")


def normalize(address, kind):
    if not isinstance(address, dict):
        raise ValueError("Modbus necesita un enlace con área y offset")
    return dict(address)


def check_binding(address, kind, writable):
    area = address.get("area", "coils" if kind == "bool" else "holding_registers")
    encoding = address.get("encoding", {"bool": "bool", "int": "int16", "float": "float32"}.get(kind))
    if encoding not in ENCODINGS or ENCODINGS[encoding][2] != kind:
        raise ValueError("Tipo SCADA incompatible con la codificación Modbus")
    if (area in {"coils", "discrete_inputs"}) != (kind == "bool"):
        raise ValueError("Coils y discrete inputs requieren bool; los registros requieren un número")
    if writable and area in {"discrete_inputs", "input_registers"}:
        raise ValueError("El área Modbus seleccionada solo permite lectura")
    if address.get("offset", 0) + ENCODINGS[encoding][1] > 65536:
        raise ValueError("El dato excede el rango Modbus")


def describe(address, kind):
    a = normalize(address, kind)
    return f"{a['area']}[{a['offset']}] · {a['encoding']}"


DEFINITION = ProtocolDefinition(
    "Modbus TCP",
    (Field("host", "IP / host", "127.0.0.1"), Field("port", "Puerto TCP", 502, 1, 65535),
     Field("unit_id", "Unit ID", 1, 0, 255), Field("timeout_ms", "Timeout (ms)", 1000, 100, 10000)),
    (Field("area", "Área", "holding_registers", choices=tuple(
        (a, a.replace('_', ' ').title(), ("bool",) if a in AREAS[:2] else ("int", "float")) for a in AREAS)),
     Field("offset", "Offset (base 0)", 0, 0, 65535),
     Field("encoding", "Codificación", "float32", choices=tuple((k, k, (v[2],)) for k, v in ENCODINGS.items())),
     Field("byte_order", "Orden de bytes", "big", choices=(("big", "AB", ()), ("little", "BA", ())), kinds=("int", "float")),
     Field("word_order", "Orden de registros", "big", choices=(("big", "ABCD", ()), ("little", "CDAB", ())), kinds=("int", "float"))),
    normalize, check_binding, describe)


def reorder(data, address):
    words = [data[i:i+2] for i in range(0, len(data), 2)]
    if address.get("byte_order", "big") == "little":
        words = [word[::-1] for word in words]
    if address.get("word_order", "big") == "little":
        words.reverse()
    return b"".join(words)


class ModbusTCP:
    definition = DEFINITION

    def __init__(self, config):
        self.config, self.client = config, None

    def connect(self):
        from pyModbusTCP.client import ModbusClient
        self.client = ModbusClient(host=self.config["host"], port=self.config.get("port", 502),
                                   unit_id=self.config.get("unit_id", 1),
                                   timeout=self.config.get("timeout_ms", 1000)/1000, auto_open=False)
        if not self.client.open():
            raise ConnectionError("No se pudo conectar con Modbus TCP")

    def read(self, address, kind):
        a = self.definition.validate_binding(address, kind, False)
        fmt, count, _ = ENCODINGS[a["encoding"]]
        values = getattr(self.client, "read_" + a["area"])(a["offset"], count)
        if values is None:
            raise ConnectionError(f"Lectura Modbus fallida: {self.client.last_error_as_txt}; {self.client.last_except_as_txt}")
        if kind == "bool":
            return values[0]
        data = b"".join(struct.pack(">H", v) for v in values)
        return struct.unpack(">" + fmt, reorder(data, a))[0]

    def write(self, address, kind, value):
        a = self.definition.validate_binding(address, kind, True)
        if kind == "bool":
            success = self.client.write_single_coil(a["offset"], value)
        else:
            fmt = ENCODINGS[a["encoding"]][0]
            data = reorder(struct.pack(">" + fmt, value), a)
            values = [struct.unpack(">H", data[i:i+2])[0] for i in range(0, len(data), 2)]
            success = self.client.write_multiple_registers(a["offset"], values)
        if not success:
            raise ConnectionError(f"Escritura Modbus fallida: {self.client.last_error_as_txt}; {self.client.last_except_as_txt}")

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
