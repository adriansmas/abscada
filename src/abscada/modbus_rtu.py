"""Modbus RTU master over a serial port or a transparent serial-to-TCP converter.

Same areas, zero-based offsets and encodings as Modbus TCP; the slave is chosen per variable,
because one port serves the whole RS-485 bus. Reads of contiguous data are grouped, and a
slave that does not answer only marks its own variables as bad.
"""
import struct
import time
from . import modbus
from .protocol_definition import Field, GroupError, ProtocolDefinition
from .serial_link import Link, transport_fields
from .i18n import tr

READ_FUNCTIONS = {"coils": 1, "discrete_inputs": 2, "holding_registers": 3, "input_registers": 4}
EXCEPTIONS = {1: tr("función no admitida"), 2: tr("dirección no válida"), 3: tr("valor no válido"),
              4: tr("fallo del esclavo"), 5: tr("orden aceptada, en curso"), 6: tr("esclavo ocupado"),
              8: tr("error de paridad de memoria"), 10: tr("pasarela sin ruta"), 11: tr("el equipo destino no responde")}


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def frame(unit, function, payload):
    body = bytes((unit, function)) + payload
    return body + struct.pack("<H", crc16(body))


class SlaveError(Exception):
    """The slave answered with a Modbus exception or did not answer at all."""


def check_binding(address, kind, writable):
    modbus.check_binding(address, kind, writable)


def describe(address, kind):
    return f"#{address.get('unit_id', 1)} · " + modbus.describe(address, kind)


DEFINITION = ProtocolDefinition(
    tr("Modbus RTU"),
    transport_fields() + (
        Field("single_register", tr("Escribir un solo registro con"), "fc16", choices=(
            ("fc16", tr("FC16 (varios registros)"), ()), ("fc06", tr("FC06 (un registro)"), ()))),
        Field("gap_ms", tr("Pausa entre peticiones (ms)"), 0, 0, 1000)),
    (Field("unit_id", tr("Esclavo (1-247)"), 1, 1, 247),) + modbus.DEFINITION.binding_fields,
    modbus.normalize, check_binding, describe)


def plan_reads(addresses, bits_limit=2000, registers_limit=125):
    """Group validated addresses into contiguous reads of one slave and area, without gaps.

    ``addresses`` = [(address, kind), ...]. Returns ``[(unit, area, start, count, [(index, address, kind)])]``.
    """
    spans = []
    for index, (a, kind) in enumerate(addresses):
        size = modbus.ENCODINGS[a["encoding"]][1]
        spans.append((a["unit_id"], a["area"], a["offset"], a["offset"] + size, index, a, kind))
    spans.sort(key=lambda s: s[:4])
    blocks = []
    for unit, area, begin, end, index, a, kind in spans:
        limit = bits_limit if area in ("coils", "discrete_inputs") else registers_limit
        last = blocks[-1] if blocks else None
        if last and last[:2] == [unit, area] and begin <= last[3] and max(end, last[3]) - last[2] <= limit:
            last[3] = max(end, last[3])
            last[4].append((index, a, kind))
        else:
            blocks.append([unit, area, begin, end, [(index, a, kind)]])
    return [(unit, area, begin, end - begin, members) for unit, area, begin, end, members in blocks]


def decode(area, start, data, a, kind):
    position = a["offset"] - start
    if area in ("coils", "discrete_inputs"):
        return bool(data[position // 8] >> (position % 8) & 1)
    fmt, count, _ = modbus.ENCODINGS[a["encoding"]]
    raw = data[position * 2:(position + count) * 2]
    return struct.unpack(">" + fmt, modbus.reorder(raw, a))[0]


class ModbusRTU:
    definition = DEFINITION

    def __init__(self, config):
        self.config, self.link, self.last_io = config, None, 0.0

    def connect(self):
        self.link = Link(self.config)
        self.link.open()
        # Silence of 3.5 characters between frames (fixed 1.75 ms above 19200 baud, per the standard).
        baud = self.config.get("baudrate", 9600)
        self.gap = max(0.00175 if baud > 19200 else 3.5 * 11 / baud, self.config.get("gap_ms", 0) / 1000)
        self.last_io = 0.0

    def _transaction(self, unit, function, payload):
        wait = self.last_io + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.link.discard_input()
        self.link.write(frame(unit, function, payload))
        deadline = time.monotonic() + self.config.get("timeout_ms", 1000) / 1000
        try:
            head = self.link.read_exact(2, deadline)
            if head[1] == function | 0x80:
                rest = self.link.read_exact(3, deadline)
            elif function <= 4:
                count = self.link.read_exact(1, deadline)
                rest = count + self.link.read_exact(count[0] + 2, deadline)
            else:
                rest = self.link.read_exact(6, deadline)
        except TimeoutError as exc:
            raise SlaveError(tr("El esclavo {unit} no responde ({error})", unit=unit, error=exc)) from None
        finally:
            self.last_io = time.monotonic()
        message = head + rest
        if crc16(message[:-2]) != struct.unpack("<H", message[-2:])[0]:
            raise SlaveError(tr("Respuesta del esclavo {unit} con CRC incorrecto", unit=unit))
        if message[0] != unit:
            raise SlaveError(tr("Respuesta del esclavo {got} en lugar del {unit}", got=message[0], unit=unit))
        if message[1] == function | 0x80:
            code = message[2]
            raise SlaveError(tr("Esclavo {unit}: excepción Modbus {code} ({text})",
                                unit=unit, code=code, text=EXCEPTIONS.get(code, "?")))
        return message[2:-2]

    def _read(self, unit, area, start, count):
        body = self._transaction(unit, READ_FUNCTIONS[area], struct.pack(">HH", start, count))
        expected = (count + 7) // 8 if area in ("coils", "discrete_inputs") else count * 2
        if body[0] != expected or len(body) != expected + 1:
            raise SlaveError(tr("Esclavo {unit}: respuesta de longitud inesperada", unit=unit))
        return body[1:]

    def read(self, address, kind):
        a = self.definition.validate_binding(address, kind, False)
        size = modbus.ENCODINGS[a["encoding"]][1]
        try:
            return decode(a["area"], a["offset"], self._read(a["unit_id"], a["area"], a["offset"], size), a, kind)
        except SlaveError as exc:
            raise ConnectionError(str(exc)) from None

    def prepare_reads(self, requests):
        addresses = [(self.definition.validate_binding(address, kind, False), kind) for address, kind in requests]
        return [lambda block=block: self._read_block(*block) for block in plan_reads(addresses)]

    def _read_block(self, unit, area, start, count, members):
        try:
            data = self._read(unit, area, start, count)
        except SlaveError as exc:
            raise GroupError([index for index, _, _ in members], str(exc)) from None
        return {index: decode(area, start, data, a, kind) for index, a, kind in members}

    def write(self, address, kind, value):
        a = self.definition.validate_binding(address, kind, True)
        unit, offset = a["unit_id"], a["offset"]
        try:
            if kind == "bool":
                self._transaction(unit, 5, struct.pack(">HH", offset, 0xFF00 if value else 0))
                return
            data = modbus.reorder(struct.pack(">" + modbus.ENCODINGS[a["encoding"]][0], value), a)
            if len(data) == 2 and self.config.get("single_register", "fc16") == "fc06":
                self._transaction(unit, 6, struct.pack(">H", offset) + data)
            else:
                self._transaction(unit, 16, struct.pack(">HHB", offset, len(data) // 2, len(data)) + data)
        except SlaveError as exc:
            raise ConnectionError(str(exc)) from None

    def close(self):
        if self.link:
            self.link.close()
            self.link = None
