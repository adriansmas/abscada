"""Byte transport shared by the serial connectors: serial port or raw TCP (serial-to-Ethernet
converters). It knows nothing about the device; it only moves bytes and cuts frames."""
import codecs
import select
import socket
import time
from .protocol_definition import Field
from .i18n import tr


def transport_fields(baudrate=9600):
    """Connection fields of the link. Studio shows all of them; each transport uses its own."""
    return (
        Field("transport", tr("Medio"), "serial", choices=(
            ("serial", tr("Puerto serie"), ()), ("tcp", tr("TCP (conversor serie-Ethernet)"), ()))),
        Field("port", tr("Puerto serie (COM3, /dev/ttyUSB0…)"), "COM1"),
        Field("baudrate", tr("Baudios"), baudrate, 50, 4000000),
        Field("bytesize", tr("Bits de datos"), 8, 5, 8, choices=tuple((n, str(n), ()) for n in (7, 8))),
        Field("parity", tr("Paridad"), "N", choices=(("N", tr("Ninguna"), ()), ("E", tr("Par"), ()),
                                                    ("O", tr("Impar"), ()), ("M", tr("Marca"), ()), ("S", tr("Espacio"), ()))),
        Field("stopbits", tr("Bits de parada"), 1, 1, 2, choices=((1, "1", ()), (2, "2", ()))),
        Field("host", tr("IP / host (TCP)"), "127.0.0.1"),
        Field("tcp_port", tr("Puerto TCP"), 4001, 1, 65535),
        Field("timeout_ms", tr("Timeout de respuesta (ms)"), 1000, 10, 60000))


def unescape(text):
    """Text typed in Studio with escapes (``\\r``, ``\\n``, ``\\t``, ``\\x02``) as characters."""
    try:
        return codecs.decode(text.encode("latin-1", "backslashreplace"), "unicode_escape")
    except (UnicodeError, ValueError) as exc:
        raise ValueError(tr("Secuencia de escape inválida: {text}", text=text)) from exc


def encode(text, encoding):
    """Text to send. ``hex`` takes byte pairs ("01 03 00 0A"); the rest accept escapes."""
    if encoding == "hex":
        try:
            return bytes.fromhex(text)
        except ValueError as exc:
            raise ValueError(tr("Hexadecimal inválido: {text}", text=text)) from exc
    try:
        return unescape(text).encode("latin-1" if encoding == "ascii" else encoding)
    except UnicodeError as exc:
        raise ValueError(tr("El texto no se puede enviar en {encoding}: {text}", encoding=encoding, text=text)) from exc


def decode(data, encoding):
    if encoding == "hex":
        return data.hex(" ").upper()
    return data.decode(encoding, "replace")


class Framer:
    """Cut a byte stream into frames. Delimiters are not part of the frame; empty frames are dropped."""
    LIMIT = 65536

    def __init__(self, mode="terminator", start=b"", end=b"\r\n", length=16, silence=0.05):
        if mode in ("terminator", "start_end") and not end:
            raise ValueError(tr("El terminador de trama no puede estar vacío"))
        if mode == "start_end" and not start:
            raise ValueError(tr("El inicio de trama no puede estar vacío"))
        self.mode, self.start, self.end, self.length, self.silence = mode, start, end, length, silence
        self.buffer, self.last = b"", 0.0

    def feed(self, data, now):
        frames = self.expire(now) if self.mode == "silence" else []
        self.buffer += data
        self.last = now
        if self.mode == "terminator":
            *frames_, self.buffer = self.buffer.split(self.end)
            frames += frames_
        elif self.mode == "start_end":
            while True:
                begin = self.buffer.find(self.start)
                if begin < 0:
                    self.buffer = self.buffer[-(len(self.start) - 1):] if len(self.start) > 1 else b""
                    break
                finish = self.buffer.find(self.end, begin + len(self.start))
                if finish < 0:
                    self.buffer = self.buffer[begin:]
                    break
                frames.append(self.buffer[begin + len(self.start):finish])
                self.buffer = self.buffer[finish + len(self.end):]
        elif self.mode == "length":
            while len(self.buffer) >= self.length:
                frames.append(self.buffer[:self.length])
                self.buffer = self.buffer[self.length:]
        if len(self.buffer) > self.LIMIT:  # wrong terminator: never grow without bound
            self.buffer = self.buffer[-self.LIMIT:]
        return [f for f in frames if f]

    def expire(self, now):
        """In silence mode, the pending bytes are a frame once the line has been quiet long enough."""
        if self.mode == "silence" and self.buffer and now - self.last >= self.silence:
            frame, self.buffer = self.buffer, b""
            return [frame]
        return []


class Link:
    """Open byte stream. One thread may read while another writes."""

    def __init__(self, config):
        self.config = config
        self.serial = self.socket = None
        self.buffer = b""

    def open(self):
        c = self.config
        if c.get("transport", "serial") == "tcp":
            self.socket = socket.create_connection((c.get("host", "127.0.0.1"), c.get("tcp_port", 4001)),
                                                   timeout=c.get("timeout_ms", 1000) / 1000)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        else:
            import serial
            # serial_for_url also accepts pyserial URLs (loop://, socket://, rfc2217://).
            self.serial = serial.serial_for_url(
                c.get("port", "COM1"), baudrate=c.get("baudrate", 9600), bytesize=c.get("bytesize", 8),
                parity=c.get("parity", "N"), stopbits=c.get("stopbits", 1), timeout=0.02, write_timeout=2)

    def read(self, timeout):
        """Bytes received within ``timeout`` seconds; b"" when none arrived."""
        if self.buffer:
            data, self.buffer = self.buffer, b""
            return data
        if self.socket:
            ready, _, _ = select.select([self.socket], [], [], timeout)
            if not ready:
                return b""
            data = self.socket.recv(4096)
            if not data:
                raise ConnectionError(tr("El equipo ha cerrado la conexión TCP"))
            return data
        if self.serial is None:
            raise ConnectionError(tr("Puerto cerrado"))
        deadline = time.monotonic() + timeout
        while True:
            data = self.serial.read(max(1, self.serial.in_waiting))
            if data or time.monotonic() >= deadline:
                return data

    def read_exact(self, size, deadline):
        """Exactly ``size`` bytes before ``deadline`` (monotonic), or TimeoutError."""
        data = b""
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(tr("Respuesta incompleta: {got} de {size} bytes", got=len(data), size=size))
            data += self.read(remaining)
        data, self.buffer = data[:size], data[size:]
        return data

    def discard_input(self):
        self.buffer = b""
        if self.serial:
            self.serial.reset_input_buffer()
        elif self.socket:
            while select.select([self.socket], [], [], 0)[0]:
                if not self.socket.recv(4096):
                    raise ConnectionError(tr("El equipo ha cerrado la conexión TCP"))

    def write(self, data):
        if self.socket:
            self.socket.sendall(data)
        elif self.serial is not None:
            self.serial.write(data)
            self.serial.flush()
        else:
            raise ConnectionError(tr("Puerto cerrado"))

    def close(self):
        for stream in (self.serial, self.socket):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self.serial = self.socket = None
