"""Siemens S7-1200/1500 by symbol name: S7CommPlus over TLS (library ``s7commplus``, extra ``.[s7plus]``).

Bindings name the PLC symbol, ``DB_Horno.Temperatura``, and its PLC type, never a byte
offset: DBs may stay optimized and PUT/GET disabled. The CPU needs secure PG/HMI
communication (S7-1200 FW V4.5 / TIA V17 or later is the documented reference).

Security policy, deliberately without fallbacks:
- TLS is always required and the PLC certificate must verify against the certificate (or
  CA) an administrator imported for *this* connection: ``<project>/pki/s7plus/<id>.pem``.
  Without it the connection is refused; it never degrades to an unverified or plain session
  and never uses the legacy (non-TLS) session-key authentication of the library.
- The PLC password, when the CPU is protected, lives in the project's secrets.json.

Symbols are resolved and their PLC types checked once per connection, by browsing the PLC.
A failed symbol fails the whole connection (same policy as the other adapters); after any
failure the runtime reconnects and browses again, which picks up a downloaded program.
Writes are never retried: when the answer is lost, the result is reported as uncertain.
"""
from __future__ import annotations

import hashlib
import re
import ssl
import struct
from pathlib import Path

from .protocol_definition import Field, ProtocolDefinition
from .i18n import tr

# PLC type: (struct format, logical abSCADA type). Strings, arrays and structures come later.
ENCODINGS = {
    "BOOL": (">?", "bool"),
    "BYTE": (">B", "int"), "USINT": (">B", "int"), "SINT": (">b", "int"),
    "WORD": (">H", "int"), "UINT": (">H", "int"), "INT": (">h", "int"),
    "DWORD": (">I", "int"), "UDINT": (">I", "int"), "DINT": (">i", "int"),
    "REAL": (">f", "float"), "LREAL": (">d", "float"),
}
# Types the PLC reports under another name with the same encoding.
ALIASES = {"BBOOL": "BOOL"}

_SYMBOL = re.compile(r"^[^\s.\[\]]+(?:\[[0-9, ]+\])*(?:\.[^\s.\[\]]+(?:\[[0-9, ]+\])*)+$")


def clean_symbol(text):
    """``"DB_Horno".Temperatura`` (TIA notation) and ``DB_Horno.Temperatura`` are the same symbol."""
    return ".".join(part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part
                    for part in str(text).strip().split("."))


def normalize(address, kind):
    if isinstance(address, str):
        address = dict(symbol=address)
    if not isinstance(address, dict):
        raise ValueError(tr("S7 simbólico necesita el nombre del símbolo del PLC"))
    result = dict(address)
    if "symbol" in result:
        result["symbol"] = clean_symbol(result["symbol"])
    result.setdefault("encoding", {"bool": "BOOL", "int": "INT", "float": "REAL"}.get(kind, ""))
    return result


def check_binding(address, kind, writable):
    if not _SYMBOL.match(address.get("symbol", "")):
        raise ValueError(tr("Símbolo inválido; escribe el bloque y la variable, p. ej. DB_Horno.Temperatura"))


def describe(address, kind):
    a = normalize(address, kind)
    return f"{a['symbol']} ({a['encoding']})"


def _choices():
    return tuple((name, name, (logical,)) for name, (_, logical) in ENCODINGS.items())


DEFINITION = ProtocolDefinition(
    tr("Siemens S7 simbólico (S7CommPlus TLS)"),
    (Field("host", tr("IP / host"), "192.168.0.1"),
     Field("port", tr("Puerto TCP"), 102, 1, 65535),
     Field("batch", tr("Variables por petición"), 20, 1, 200)),
    (Field("symbol", tr("Símbolo del PLC"), "DB_Prueba.Contador"),
     Field("encoding", tr("Tipo en el PLC"), "DINT", choices=_choices())),
    normalize, check_binding, describe, secret=True, trust_store=True)


# --- trust of the PLC certificate, one file per connection (no Qt) -----------------------------

def trust_path(project_root, connection_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", connection_id or ""):
        raise ValueError(tr("Nombre de conexión inválido para guardar su certificado"))
    return Path(project_root) / "pki" / "s7plus" / f"{connection_id}.pem"


def _certificates(data: bytes):
    from cryptography import x509
    if b"-----BEGIN CERTIFICATE-----" in data:
        return x509.load_pem_x509_certificates(data)
    return [x509.load_der_x509_certificate(data)]


def describe_certificates(data: bytes):
    """Subject, SHA-256 fingerprint, validity and addresses of each certificate in a file."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    result = []
    for certificate in _certificates(data):
        try:
            names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            addresses = [str(a) for a in names.get_values_for_type(x509.IPAddress)] + names.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            addresses = []
        der = certificate.public_bytes(Encoding.DER)
        result.append(dict(subject=certificate.subject.rfc4514_string(), issuer=certificate.issuer.rfc4514_string(),
                           fingerprint=":".join(f"{b:02X}" for b in hashlib.sha256(der).digest()),
                           valid_from=certificate.not_valid_before_utc.isoformat()[:10],
                           valid_until=certificate.not_valid_after_utc.isoformat()[:10], addresses=addresses))
    return result


def import_certificate(project_root, connection_id, data: bytes):
    """Trust the PLC certificate (or its CA chain) exported from TIA Portal, PEM or DER.

    Replaces the previous one: changing the PLC or renewing its certificate is a conscious act.
    """
    from cryptography.hazmat.primitives.serialization import Encoding
    try:
        certificates = _certificates(data)
    except ValueError as exc:
        raise ValueError(tr("El archivo no contiene un certificado X.509 (PEM o DER)")) from exc
    path = trust_path(project_root, connection_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(c.public_bytes(Encoding.PEM) for c in certificates))
    return describe_certificates(path.read_bytes())


def trusted_certificates(project_root, connection_id):
    path = trust_path(project_root, connection_id)
    return describe_certificates(path.read_bytes()) if path.exists() else []


def remove_certificate(project_root, connection_id):
    trust_path(project_root, connection_id).unlink(missing_ok=True)


# --- errors ------------------------------------------------------------------------------------

def explain(exc):
    """A readable error that says what to check: certificate, permission, symbol, type or network."""
    if isinstance(exc, (PermissionError, LookupError)) and not isinstance(exc, KeyError):
        return exc
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ConnectionError(tr("Certificado del PLC rechazado ({reason}). Comprueba que el certificado importado para esta "
                                  "conexión es el del PLC (o su CA), que no ha caducado y que incluye la IP usada.",
                                  reason=exc.verify_message or exc.reason or exc))
    if isinstance(exc, ssl.SSLError):
        return ConnectionError(tr("No se pudo establecer TLS con el PLC: {exc}. Comprueba que la CPU tiene activada la "
                                  "comunicación PG/HMI segura.", exc=exc))
    try:
        from s7commplus.error import S7AuthenticationError
        if isinstance(exc, S7AuthenticationError):
            return PermissionError(tr("El PLC rechaza la contraseña o el nivel de acceso: {exc}", exc=exc))
    except ImportError:
        pass
    return exc


class SymbolError(LookupError):
    """A binding that the PLC does not offer as configured."""


class S7Plus:
    definition = DEFINITION
    # Trust store used by Studio's «Certificado del PLC…» (definition.trust_store).
    import_certificate = staticmethod(import_certificate)
    trusted_certificates = staticmethod(trusted_certificates)
    remove_certificate = staticmethod(remove_certificate)

    def __init__(self, config):
        self.config = config
        self.root = None
        self.client = None
        self.tags = {}  # symbol -> SymbolicTag, checked against the expected PLC type

    def attach(self, project_root):
        self.root = project_root

    def connect(self):
        if self.root is None:
            raise RuntimeError(tr("Conector S7 simbólico sin carpeta de proyecto (certificado y contraseña)"))
        ca = trust_path(self.root, self.config.get("id", ""))
        if not ca.exists():
            raise PermissionError(tr("No hay certificado de confianza para el PLC de esta conexión: impórtalo en Studio "
                                     "(Conexiones → Certificado del PLC…). Sin él no se establece TLS verificado."))
        from .secrets_store import SecretStore, connection_secret_key, secrets_path
        password = SecretStore(secrets_path(self.root)).get(connection_secret_key(self.config["id"])) or None
        try:
            from s7commplus import Client
        except ImportError as exc:
            raise RuntimeError(tr("Falta la biblioteca S7CommPlus: instala abSCADA con el extra s7plus "
                                  "(pip install -e '.[s7plus]'). No se incluye todavía en el ejecutable de Windows.")) from exc
        client = Client()
        try:
            client.connect(self.config["host"], int(self.config.get("port", 102)), use_tls=True, tls_ca=str(ca),
                           password=password, allow_legacy_key_fallback=False, legacy_session_key_refresh_interval=None)
            if not client.tls_active:
                raise ConnectionError(tr("El PLC no ha activado TLS: conexión rechazada"))
        except Exception as exc:
            try:
                client.disconnect()
            except Exception:
                pass
            raise explain(exc) from exc
        self.client = client
        self.tags = {}

    # --- symbols -------------------------------------------------------------------------------

    def resolve(self, address, kind):
        """Descriptor of a binding, refusing an unknown symbol or another PLC type."""
        a = normalize(address, kind)
        symbol, encoding = a["symbol"], a["encoding"]
        if symbol not in self.tags:
            try:
                tag = self.client.resolve_tag(symbol)
            except KeyError as exc:
                raise SymbolError(tr("El PLC no tiene el símbolo {symbol} (o no es accesible desde HMI)", symbol=symbol)) from exc
            actual = ALIASES.get(tag.softdatatype.name, tag.softdatatype.name)
            if tag.array_dimensions:
                raise SymbolError(tr("{symbol} es un array: enlaza un elemento, p. ej. {symbol}[0]", symbol=symbol))
            if actual != encoding:
                raise SymbolError(tr("{symbol} es {actual} en el PLC, no {encoding}", symbol=symbol, actual=actual, encoding=encoding))
            self.tags[symbol] = tag
        return self.tags[symbol], encoding

    @staticmethod
    def decode(symbol, encoding, raw):
        fmt = ENCODINGS[encoding][0]
        if raw is None or len(raw) != struct.calcsize(fmt):
            raise ConnectionError(tr("Respuesta incompleta del PLC para {symbol}", symbol=symbol))
        return struct.unpack(fmt, raw)[0]

    @staticmethod
    def encode(encoding, value):
        fmt, logical = ENCODINGS[encoding]
        if logical == "float":
            value = float(value)
        elif logical == "int":
            if isinstance(value, float) and not value.is_integer():
                raise ValueError(tr("{encoding} necesita un número entero", encoding=encoding))
            value = int(value)
        else:
            value = bool(value)
        try:
            return struct.pack(fmt, value)
        except struct.error as exc:
            raise ValueError(tr("{value} está fuera del rango de {encoding}", value=value, encoding=encoding)) from exc

    def _read(self, entries):
        """entries: [(index, symbol, encoding)]; one request for all of them."""
        try:
            results = self.client.read_tags([symbol for _, symbol, _ in entries])
        except Exception as exc:
            raise explain(exc) from exc
        values = {}
        for (index, symbol, encoding), result in zip(entries, results):
            if result.error is not None:
                raise ConnectionError(tr("El PLC no devuelve {symbol}: {error}", symbol=symbol, error=result.error))
            values[index] = self.decode(symbol, encoding, result.value)
        return values

    def read(self, address, kind):
        tag, encoding = self.resolve(address, kind)
        return self._read([(0, tag.name, encoding)])[0]

    def prepare_reads(self, requests):
        """Resolve and type-check every binding now, then read them in batches of ``batch`` symbols."""
        entries = []
        for index, (address, kind) in enumerate(requests):
            tag, encoding = self.resolve(address, kind)
            entries.append((index, tag.name, encoding))
        size = int(self.config.get("batch", 20))
        return [lambda chunk=entries[i:i + size]: self._read(chunk) for i in range(0, len(entries), size)]

    def write(self, address, kind, value):
        tag, encoding = self.resolve(address, kind)
        data = self.encode(encoding, value)
        try:
            result = self.client.write_tags({tag.name: data})[0]
        except Exception as exc:
            # The request may have reached the PLC: never claim it did not, never repeat it.
            raise ConnectionError(tr("Resultado de la escritura de {symbol} incierto (el PLC pudo aplicarla): {exc}",
                                     symbol=tag.name, exc=explain(exc))) from exc
        if result.error is not None:
            raise PermissionError(tr("El PLC rechaza la escritura de {symbol}: {error}", symbol=tag.name, error=result.error))

    # --- engineering ---------------------------------------------------------------------------

    def browse(self):
        """Readable scalar symbols of the PLC: [(address, logical kind)] for Studio's import."""
        found = []
        for item in self.client.browse():
            encoding = ALIASES.get(item["data_type"], item["data_type"])
            if encoding in ENCODINGS and not item.get("array_dimensions"):
                found.append((dict(symbol=item["name"], encoding=encoding), ENCODINGS[encoding][1]))
        return found

    def close(self):
        client, self.client = self.client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
