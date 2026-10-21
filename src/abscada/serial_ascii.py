"""Raw serial/TCP connector. It sends text and delivers received frames as text; it never
interprets them. Parsing a device's frames belongs to the project (a script)."""
import threading
import time
from collections import deque
from .protocol_definition import AddressError, Field, ProtocolDefinition
from .serial_link import Framer, Link, decode, encode, transport_fields, unescape
from .i18n import tr

FUNCTIONS = (("rx", tr("Última trama recibida"), ("string",)),
             ("count", tr("Tramas recibidas (contador)"), ("int",)),
             ("request", tr("Petición y respuesta"), ("string",)),
             ("send", tr("Enviar texto (escritura)"), ("string",)))


def normalize(address, kind):
    if not isinstance(address, dict):
        raise ValueError(tr("Serie/TCP necesita un enlace con función"))
    return dict(address)


def check_binding(address, kind, writable):
    function = address["function"]
    if function == "request" and not address.get("command", "").strip():
        raise ValueError(tr("La petición necesita un comando"))
    if writable and function != "send":
        raise ValueError(tr("Solo «Enviar texto» admite escritura"))


def describe(address, kind):
    a = normalize(address, kind)
    label = dict((value, title) for value, title, _ in FUNCTIONS).get(a.get("function"), a.get("function", "rx"))
    return f"{label}: {a.get('command', '')}" if a.get("function") == "request" else label


DEFINITION = ProtocolDefinition(
    tr("Serie / TCP en bruto"),
    transport_fields() + (
        Field("framing", tr("Fin de trama"), "terminator", choices=(
            ("terminator", tr("Terminador"), ()), ("start_end", tr("Inicio y fin"), ()),
            ("length", tr("Longitud fija"), ()), ("silence", tr("Silencio en la línea"), ()))),
        Field("terminator", tr("Terminador o fin de trama"), "\\r\\n"),
        Field("start", tr("Inicio de trama (solo «Inicio y fin»)"), "\\x02", optional=True),
        Field("frame_length", tr("Longitud de trama (bytes)"), 16, 1, 4096),
        Field("silence_ms", tr("Silencio que cierra la trama (ms)"), 50, 1, 10000),
        Field("encoding", tr("Codificación"), "ascii", choices=(
            ("ascii", "ASCII", ()), ("latin-1", "Latin-1", ()), ("utf-8", "UTF-8", ()), ("hex", tr("Hexadecimal"), ()))),
        Field("suffix", tr("Añadir a cada envío"), "", optional=True),
        Field("on_connect", tr("Enviar al conectar"), "", optional=True),
        Field("on_close", tr("Enviar al desconectar"), "", optional=True),
        Field("stale_ms", tr("Error si no llegan tramas en (ms, 0 = nunca)"), 0, 0, 3600000)),
    (Field("function", tr("Función"), "rx", choices=FUNCTIONS),
     Field("command", tr("Comando (escapes \\r \\n \\xNN)"), "", optional=True, kinds=("string",))),
    normalize, check_binding, describe)


class SerialAscii:
    """A reader thread cuts frames continuously; reads and writes come from the runtime worker."""
    definition = DEFINITION

    def __init__(self, config):
        self.config = config
        self.link = self.thread = None
        self.stop = threading.Event()
        self.lock = threading.Condition()
        self.frames = deque(maxlen=64)
        self.last, self.count, self.sent, self.error = "", 0, "", None
        self.received_at = 0.0

    def _bytes(self, text):
        return encode(text, self.encoding) + self.suffix

    def connect(self):
        c = self.config
        self.encoding = c.get("encoding", "ascii")
        self.suffix = encode(c.get("suffix", ""), self.encoding) if c.get("suffix") else b""
        self.framer = Framer(c.get("framing", "terminator"), unescape(c.get("start", "")).encode("latin-1"),
                             unescape(c.get("terminator", "\\r\\n")).encode("latin-1"),
                             c.get("frame_length", 16), c.get("silence_ms", 50) / 1000)
        self.link = Link(c)
        self.link.open()
        self.stop.clear()
        self.error, self.received_at = None, time.monotonic()
        self.thread = threading.Thread(target=self._receive, name="abscada-serial-rx", daemon=True)
        self.thread.start()
        if c.get("on_connect"):
            self.link.write(self._bytes(c["on_connect"]))

    def _receive(self):
        try:
            while not self.stop.is_set():
                data = self.link.read(0.05)
                now = time.monotonic()
                frames = self.framer.feed(data, now) if data else self.framer.expire(now)
                if frames:
                    with self.lock:
                        for frame in frames:
                            text = decode(frame, self.encoding)
                            self.frames.append(text)
                            self.last = text
                        self.count += len(frames)
                        self.received_at = now
                        self.lock.notify_all()
        except Exception as exc:
            if not self.stop.is_set():
                with self.lock:
                    self.error = exc
                    self.lock.notify_all()

    def _check(self):
        if self.error is not None:
            raise ConnectionError(tr("Fallo de lectura: {error}", error=self.error))
        stale = self.config.get("stale_ms", 0) / 1000
        if stale and time.monotonic() - self.received_at > stale:
            raise ConnectionError(tr("No llegan tramas desde hace {seconds} s", seconds=round(time.monotonic() - self.received_at, 1)))

    def read(self, address, kind):
        a = self.definition.validate_binding(address, kind, False)
        self._check()
        function = a["function"]
        if function == "rx":
            return self.last
        if function == "count":
            return self.count
        if function == "send":
            return self.sent
        command = self._bytes(a["command"])
        with self.lock:
            self.frames.clear()
        self.link.write(command)
        deadline = time.monotonic() + self.config.get("timeout_ms", 1000) / 1000
        with self.lock:
            while not self.frames:
                remaining = deadline - time.monotonic()
                if self.error is not None or remaining <= 0:
                    self._check()
                    raise AddressError(tr("Sin respuesta a «{command}»", command=a["command"]))
                self.lock.wait(remaining)
            return self.frames.popleft()

    def write(self, address, kind, value):
        self.definition.validate_binding(address, kind, True)
        self._check()
        self.link.write(self._bytes(str(value)))
        self.sent = str(value)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(1)
            self.thread = None
        if self.link:
            try:
                if self.config.get("on_close"):
                    self.link.write(self._bytes(self.config["on_close"]))
            except Exception:
                pass
            self.link.close()
            self.link = None
