"""Beckhoff TwinCAT ADS over AMS/TCP, implemented without the TwinCAT router.

Talks directly to the PLC on TCP 48898. The PLC must hold a static route for this
PC (its AMS Net ID and IP), as with any ADS client that does not run through a
local TwinCAT router.

A binding names either a PLC symbol ("MAIN.bStart", "GVL.rTemp") or a raw
index group / offset ("0x4020:0" = %MB0 on TwinCAT 2, "0xF030:4" = %QB4).
Symbol handles are cached per connection and refreshed once if the PLC
program changed underneath them.
"""
from __future__ import annotations

import re
import socket
import struct

from .protocol_definition import Field, ProtocolDefinition
from .i18n import tr

AMS_TCP_PORT = 48898
SOURCE_PORT = 32905

CMD_READ_DEVICE_INFO, CMD_READ, CMD_WRITE, CMD_READ_STATE, CMD_READ_WRITE = 1, 2, 3, 4, 9
STATE_REQUEST, STATE_RESPONSE = 0x0004, 0x0005
IG_SYM_HANDLE_BY_NAME, IG_SYM_VALUE_BY_HANDLE, IG_SYM_RELEASE_HANDLE = 0xF003, 0xF005, 0xF006

# PLC type -> (struct format, size, SCADA kind). Little endian, like the PLC.
TYPES = {
    "BOOL": ("?", 1, "bool"),
    "INT": ("h", 2, "int"), "DINT": ("i", 4, "int"), "SINT": ("b", 1, "int"), "USINT": ("B", 1, "int"),
    "BYTE": ("B", 1, "int"), "UINT": ("H", 2, "int"), "WORD": ("H", 2, "int"), "UDINT": ("I", 4, "int"),
    "DWORD": ("I", 4, "int"), "LINT": ("q", 8, "int"), "ULINT": ("Q", 8, "int"),
    "REAL": ("f", 4, "float"), "LREAL": ("d", 8, "float"),
    "STRING": (None, None, "string"),
}

ERRORS = {
    0x6: tr("puerto ADS de destino no encontrado (¿runtime PLC parado o puerto 851/801 incorrecto?)"),
    0x7: tr("AMS Net ID de destino no encontrado"),
    0x700: tr("error general del dispositivo"), 0x701: tr("servicio no soportado"), 0x702: tr("grupo de índice no válido"),
    0x703: tr("offset no válido"), 0x704: tr("lectura/escritura no permitida"), 0x705: tr("tamaño de datos incorrecto"),
    0x706: tr("valor de datos no válido"), 0x707: tr("dispositivo no preparado"), 0x708: "dispositivo ocupado",
    0x710: tr("símbolo no encontrado"), 0x711: tr("versión de símbolos no válida (programa del PLC cambiado)"),
    0x745: tr("tiempo de espera agotado"), 0x74C: "acceso denegado",
}
STALE_HANDLE = {0x710, 0x711, 0x702}

_RAW_ADDRESS = re.compile(r"^(0x[0-9a-fA-F]+|\d+):(0x[0-9a-fA-F]+|\d+)$")
_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[0-9, ]+\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[[0-9, ]+\])?)*$")
_NET_ID = re.compile(r"^\d{1,3}(\.\d{1,3}){5}$")


class AdsError(ConnectionError):
    def __init__(self, code, context=""):
        self.code = code
        detail = ERRORS.get(code, "error ADS")
        super().__init__(f"ADS 0x{code:X}: {detail}{' · ' + context if context else ''}")


def net_id_bytes(text):
    if not _NET_ID.match(text or "") or any(int(p) > 255 for p in text.split(".")):
        raise ValueError(tr("AMS Net ID inválido: {text!r} (ejemplo 5.80.201.232.1.1)", text=text))
    return bytes(int(p) for p in text.split("."))


def size_of(address):
    fmt, size, _ = TYPES[address["encoding"]]
    return address.get("length", 80) + 1 if address["encoding"] == "STRING" else size


def encode(address, kind, value):
    if address["encoding"] == "STRING":
        data = str(value).encode("cp1252", errors="replace")[: address.get("length", 80)]
        return data + b"\x00" * (size_of(address) - len(data))
    fmt = TYPES[address["encoding"]][0]
    if kind == "int":
        low, high = _int_range(fmt)
        if not low <= int(value) <= high:
            raise ValueError(tr("{value} no cabe en {encoding}", value=value, encoding=address['encoding']))
    return struct.pack("<" + fmt, value)


def decode(address, data):
    if address["encoding"] == "STRING":
        return data.split(b"\x00", 1)[0].decode("cp1252", errors="replace")
    return struct.unpack("<" + TYPES[address["encoding"]][0], data[: size_of(address)])[0]


def _int_range(fmt):
    bits = struct.calcsize(fmt) * 8
    return (0, 2 ** bits - 1) if fmt.isupper() else (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)


def raw_address(symbol):
    match = _RAW_ADDRESS.match(symbol)
    return (int(match.group(1), 0), int(match.group(2), 0)) if match else None


# --------------------------------------------------------------------------
# Protocol definition used by Studio forms and project validation
# --------------------------------------------------------------------------
def normalize(address, kind):
    if isinstance(address, str):
        return {"symbol": address}
    if not isinstance(address, dict):
        raise ValueError(tr("ADS necesita un símbolo o grupo:offset"))
    return dict(address)


def check_binding(address, kind, writable):
    symbol = address["symbol"].strip()
    if not (raw_address(symbol) or _SYMBOL.match(symbol)):
        raise ValueError(tr("Símbolo ADS inválido: {symbol!r}; ejemplos MAIN.bMarcha, GVL.aDatos[3] o 0x4020:0", symbol=symbol))
    if TYPES[address["encoding"]][2] != kind:
        raise ValueError(tr("Tipo SCADA incompatible con el tipo del PLC"))


def describe(address, kind):
    a = normalize(address, kind)
    detail = f"STRING({a.get('length', 80)})" if a.get("encoding") == "STRING" else a.get("encoding", "")
    return f"{a.get('symbol', '?')} · {detail}"


DEFINITION = ProtocolDefinition(
    tr("Beckhoff TwinCAT ADS"),
    (Field("host", tr("IP del PLC"), "192.168.1.100"),
     Field("port", tr("Puerto TCP"), AMS_TCP_PORT, 1, 65535),
     Field("ams_net_id", tr("AMS Net ID del PLC"), "192.168.1.100.1.1"),
     Field("ams_port", tr("Puerto ADS (851 TC3 · 801 TC2)"), 851, 1, 65535),
     Field("local_ams_net_id", tr("AMS Net ID local (auto = IP + .1.1)"), "auto"),
     Field("timeout_ms", tr("Timeout (ms)"), 1000, 100, 10000)),
    (Field("symbol", tr("Símbolo o grupo:offset"), "MAIN.variable"),
     Field("encoding", tr("Tipo PLC"), "REAL", choices=tuple((name, name, (spec[2],)) for name, spec in TYPES.items())),
     Field("length", tr("Longitud STRING"), 80, 1, 255, kinds=("string",))),
    normalize, check_binding, describe)


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
class AdsClient:
    """Minimal synchronous AMS/TCP client: one request in flight at a time."""

    def __init__(self, host, target_net_id, target_port=851, tcp_port=AMS_TCP_PORT, local_net_id="auto", timeout=1.0):
        self.host, self.tcp_port, self.timeout = host, tcp_port, timeout
        self.target = net_id_bytes(target_net_id)
        self.target_port = target_port
        self.local_net_id = local_net_id
        self.source = None
        self.sock = None
        self.invoke = 0

    def open(self):
        self.sock = socket.create_connection((self.host, self.tcp_port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        local = self.local_net_id
        if not local or local == "auto":
            local = self.sock.getsockname()[0] + ".1.1"
        self.source = net_id_bytes(local)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _recv(self, count):
        chunks = bytearray()
        while len(chunks) < count:
            chunk = self.sock.recv(count - len(chunks))
            if not chunk:
                raise ConnectionError(tr("El PLC cerró la conexión ADS"))
            chunks += chunk
        return bytes(chunks)

    def request(self, command, payload=b""):
        if not self.sock:
            raise ConnectionError(tr("Conexión ADS no abierta"))
        self.invoke = (self.invoke + 1) & 0xFFFFFFFF
        header = struct.pack("<6sH6sHHHIII", self.target, self.target_port, self.source, SOURCE_PORT,
                             command, STATE_REQUEST, len(payload), 0, self.invoke)
        self.sock.sendall(struct.pack("<HI", 0, len(header) + len(payload)) + header + payload)
        while True:
            _, length = struct.unpack("<HI", self._recv(6))
            frame = self._recv(length)
            (_, _, _, _, cmd, state, data_length, error, invoke) = struct.unpack("<6sH6sHHHIII", frame[:32])
            if invoke != self.invoke or cmd != command:
                continue  # stale answer from a timed-out request
            if error:
                raise AdsError(error)
            return frame[32:32 + data_length]

    @staticmethod
    def _result(data, context=""):
        code = struct.unpack_from("<I", data)[0]
        if code:
            raise AdsError(code, context)

    def read(self, group, offset, size, context=""):
        data = self.request(CMD_READ, struct.pack("<III", group, offset, size))
        self._result(data, context)
        length = struct.unpack_from("<I", data, 4)[0]
        return data[8:8 + length]

    def write(self, group, offset, payload, context=""):
        data = self.request(CMD_WRITE, struct.pack("<III", group, offset, len(payload)) + payload)
        self._result(data, context)

    def read_write(self, group, offset, read_size, payload, context=""):
        data = self.request(CMD_READ_WRITE, struct.pack("<IIII", group, offset, read_size, len(payload)) + payload)
        self._result(data, context)
        length = struct.unpack_from("<I", data, 4)[0]
        return data[8:8 + length]

    def read_state(self):
        data = self.request(CMD_READ_STATE)
        self._result(data)
        return struct.unpack_from("<HH", data, 4)  # (ADS state, device state); 5 = RUN

    def handle(self, symbol):
        data = self.read_write(IG_SYM_HANDLE_BY_NAME, 0, 4, symbol.encode("cp1252") + b"\x00", symbol)
        return struct.unpack("<I", data[:4])[0]

    def release(self, handle):
        self.write(IG_SYM_RELEASE_HANDLE, 0, struct.pack("<I", handle))


class TwinCatADS:
    """Connector contract (connect/read/write/close) on top of AdsClient."""
    definition = DEFINITION

    def __init__(self, config):
        self.config = config
        self.client = None
        self.handles = {}

    def connect(self):
        c = self.config
        self.client = AdsClient(c["host"], c.get("ams_net_id", "") or c["host"] + ".1.1", c.get("ams_port", 851),
                                c.get("port", AMS_TCP_PORT), c.get("local_ams_net_id", "auto"), c.get("timeout_ms", 1000) / 1000)
        self.client.open()
        ads_state, _ = self.client.read_state()
        if ads_state != 5:
            raise ConnectionError(tr("El PLC no está en RUN (estado ADS {ads_state})", ads_state=ads_state))

    def _access(self, address, operation):
        """Run operation(group, offset) on a symbol handle, re-resolving it once if stale."""
        symbol = address["symbol"].strip()
        raw = raw_address(symbol)
        if raw:
            return operation(*raw)
        key = symbol.lower()  # TwinCAT symbol names are case-insensitive
        for attempt in (0, 1):
            if key not in self.handles:
                self.handles[key] = self.client.handle(symbol)
            try:
                return operation(IG_SYM_VALUE_BY_HANDLE, self.handles[key])
            except AdsError as error:
                self.handles.pop(key, None)
                if attempt or error.code not in STALE_HANDLE:
                    raise

    def read(self, address, kind):
        a = self.definition.validate_binding(address, kind, False)
        data = self._access(a, lambda group, offset: self.client.read(group, offset, size_of(a), a["symbol"]))
        return decode(a, data)

    def write(self, address, kind, value):
        a = self.definition.validate_binding(address, kind, True)
        payload = encode(a, kind, value)
        self._access(a, lambda group, offset: self.client.write(group, offset, payload, a["symbol"]))

    def close(self):
        if not self.client:
            return
        try:
            for handle in self.handles.values():
                try:
                    self.client.release(handle)
                except (OSError, AdsError):
                    break
        finally:
            self.handles.clear()
            self.client.close()
            self.client = None
