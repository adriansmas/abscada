"""Modbus TCP plugin. Register offsets are always zero-based, never 4xxxx references."""
import struct
from .protocol_definition import AddressError, Field, GroupError, ProtocolDefinition
from .i18n import tr


ENCODINGS = {"uint16": ("H", 1, "int"), "int16": ("h", 1, "int"),
             "uint32": ("I", 2, "int"), "int32": ("i", 2, "int"),
             "float32": ("f", 2, "float"), "float64": ("d", 4, "float"),
             "bool": (None, 1, "bool")}
AREAS = ("coils", "discrete_inputs", "holding_registers", "input_registers")


def normalize(address, kind):
    if not isinstance(address, dict):
        raise ValueError(tr("Modbus necesita un enlace con área y offset"))
    return dict(address)


def check_binding(address, kind, writable):
    area = address.get("area", "coils" if kind == "bool" else "holding_registers")
    encoding = address.get("encoding", {"bool": "bool", "int": "int16", "float": "float32"}.get(kind))
    if encoding not in ENCODINGS or ENCODINGS[encoding][2] != kind:
        raise ValueError(tr("Tipo SCADA incompatible con la codificación Modbus"))
    if (area in {"coils", "discrete_inputs"}) != (kind == "bool"):
        raise ValueError(tr("Coils y discrete inputs requieren bool; los registros requieren un número"))
    if writable and area in {"discrete_inputs", "input_registers"}:
        raise ValueError(tr("El área Modbus seleccionada solo permite lectura"))
    if address.get("offset", 0) + ENCODINGS[encoding][1] > 65536:
        raise ValueError(tr("El dato excede el rango Modbus"))


def describe(address, kind):
    a = normalize(address, kind)
    return f"{a['area']}[{a['offset']}] · {a['encoding']}"


DEFINITION = ProtocolDefinition(
    tr("Modbus TCP"),
    (Field("host", tr("IP / host"), "127.0.0.1"), Field("port", tr("Puerto TCP"), 502, 1, 65535),
     Field("unit_id", tr("Unit ID"), 1, 0, 255), Field("timeout_ms", tr("Timeout (ms)"), 1000, 100, 10000),
     Field("gap_registers", tr("Leer huecos de hasta (registros)"), 0, 0, 100)),
    (Field("area", tr("Área"), "holding_registers", choices=tuple(
        (a, a.replace('_', ' ').title(), ("bool",) if a in AREAS[:2] else ("int", "float")) for a in AREAS)),
     Field("offset", tr("Offset (base 0)"), 0, 0, 65535),
     Field("encoding", tr("Codificación"), "float32", choices=tuple((k, k, (v[2],)) for k, v in ENCODINGS.items())),
     Field("byte_order", tr("Orden de bytes"), "big", choices=(("big", "AB", ()), ("little", "BA", ())), kinds=("int", "float")),
     Field("word_order", tr("Orden de registros"), "big", choices=(("big", "ABCD", ()), ("little", "CDAB", ())), kinds=("int", "float"))),
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
            raise ConnectionError(tr("No se pudo conectar con Modbus TCP"))

    def _failure(self, message):
        """The device refused this request (a Modbus exception: address, value...) or the link failed."""
        from pyModbusTCP.constants import MB_EXCEPT_ERR
        return AddressError(message) if self.client.last_error == MB_EXCEPT_ERR else ConnectionError(message)

    def _registers(self, area, start, count):
        values = getattr(self.client, "read_" + area)(start, count)
        if values is None:
            raise self._failure(tr("Lectura Modbus fallida: {last_error_as_txt}; {last_except_as_txt}", last_error_as_txt=self.client.last_error_as_txt, last_except_as_txt=self.client.last_except_as_txt))
        return values

    def read(self, address, kind):
        a = self.definition.validate_binding(address, kind, False)
        fmt, count, _ = ENCODINGS[a["encoding"]]
        values = self._registers(a["area"], a["offset"], count)
        if kind == "bool":
            return values[0]
        data = b"".join(struct.pack(">H", v) for v in values)
        return struct.unpack(">" + fmt, reorder(data, a))[0]

    def prepare_reads(self, requests):
        """Contiguous data of one area in one request (validated once, not every cycle)."""
        from .modbus_rtu import plan_reads
        addresses = [(dict(self.definition.validate_binding(address, kind, False), unit_id=0), kind) for address, kind in requests]
        gap = self.config.get("gap_registers", 0)
        return [lambda block=block: self._read_block(*block) for block in plan_reads(addresses, gap=gap)]

    def _read_block(self, unit, area, start, count, members):
        from .modbus_rtu import decode
        try:
            values = self._registers(area, start, count)
        except AddressError as exc:
            raise GroupError([index for index, _, _ in members], str(exc)) from None
        if area in ("coils", "discrete_inputs"):
            data = bytearray((count + 7) // 8)
            for position, bit in enumerate(values):
                if bit:
                    data[position // 8] |= 1 << (position % 8)
        else:
            data = b"".join(struct.pack(">H", v) for v in values)
        return {index: decode(area, start, data, a, kind) for index, a, kind in members}

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
            raise self._failure(tr("Escritura Modbus fallida: {last_error_as_txt}; {last_except_as_txt}", last_error_as_txt=self.client.last_error_as_txt, last_except_as_txt=self.client.last_except_as_txt))

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
