"""Siemens S7-1200/1500 by symbol name: S7CommPlus over TLS (library ``s7commplus``, extra ``.[s7plus]``).

Bindings name the PLC symbol, ``DB_Horno.Temperatura``, and its PLC type, never a byte
offset: DBs may stay optimized and PUT/GET disabled. The CPU needs secure PG/HMI
communication (S7-1200 FW V4.5 / TIA V17 or later is the documented reference).

Security policy, deliberately without fallbacks:
- TLS is always required and the PLC certificate must verify against what an administrator
  trusted for *this* connection: ``<project>/pki/s7plus/<id>.pem``. Without it the connection
  is refused; it never degrades to an unverified or plain session and never uses the legacy
  (non-TLS) session-key authentication of the library.
- Two ways to trust, like TIA Portal and the HMI panels: «Leer del PLC y confiar» captures the
  certificate the PLC presents (no password is sent), shows its fingerprints and stores it
  after the user confirms; or a certificate / CA exported from TIA is imported from a file.
- A single end certificate (not a CA) is an exact pin: only that certificate is accepted,
  whatever the IP or name used. A CA (or a chain) also requires the PLC's IP or name in the
  certificate, because the CA could sign other devices.
- Trust never travels to the client: the PLC does not ask the SCADA for a certificate. Writes
  depend on the CPU access level, its password and the HMI attributes of each variable.
- The PLC password, when the CPU is protected, lives in the project's secrets.json.

Symbols are resolved and their PLC types checked once per connection, by browsing the PLC.
A failed symbol fails the whole connection (same policy as the other adapters); after any
failure the runtime reconnects and browses again, which picks up a downloaded program.
Writes are never retried: when the answer is lost, the result is reported as uncertain.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import re
import ssl
import struct
import threading
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


def _fingerprint(der, algorithm):
    return ":".join(f"{b:02X}" for b in hashlib.new(algorithm, der).digest())


def _is_ca(certificate):
    from cryptography import x509
    try:
        return certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        return False


def describe_certificates(data: bytes):
    """Subject, fingerprints (SHA-256 and the SHA-1 Windows shows), validity and addresses of each certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    result = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for certificate in _certificates(data):
        try:
            names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            addresses = [str(a) for a in names.get_values_for_type(x509.IPAddress)] + names.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            addresses = []
        der = certificate.public_bytes(Encoding.DER)
        result.append(dict(subject=certificate.subject.rfc4514_string(), issuer=certificate.issuer.rfc4514_string(),
                           fingerprint=_fingerprint(der, "sha256"), sha1=_fingerprint(der, "sha1"),
                           valid_from=certificate.not_valid_before_utc.isoformat()[:10],
                           valid_until=certificate.not_valid_after_utc.isoformat()[:10],
                           days_left=(certificate.not_valid_after_utc - now).days,
                           addresses=addresses, ca=_is_ca(certificate)))
    return result


def is_pin(data: bytes):
    """One end certificate (not a CA): only that exact certificate is accepted, whatever the IP used."""
    certificates = _certificates(data)
    return len(certificates) == 1 and not _is_ca(certificates[0])


def import_certificate(project_root, connection_id, data: bytes):
    """Trust a PLC certificate or its CA chain (exported from TIA Portal or read from the PLC), PEM or DER.

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


# --- TLS policy applied to the library's context ---------------------------------------------
#
# The library builds its own SSLContext. A hook adds abSCADA's policy to the contexts created in
# the thread that is inside ``_tls_policy``: one acquisition worker per connection, so the policy
# of one connection never leaks to another, also when the library reconnects by itself.

_POLICY = threading.local()


def _install_hook():
    from s7commplus.connection import S7CommPlusConnection
    original = S7CommPlusConnection._setup_ssl_context
    if getattr(original, "abscada_policy", False):
        return

    def setup(self, *args, **kwargs):
        context = original(self, *args, **kwargs)
        policy = getattr(_POLICY, "value", None)
        if policy is not None:
            policy(context)
        return context
    setup.abscada_policy = True
    S7CommPlusConnection._setup_ssl_context = setup


@contextlib.contextmanager
def _tls_policy(policy):
    _install_hook()
    previous = getattr(_POLICY, "value", None)
    _POLICY.value = policy
    try:
        yield
    finally:
        _POLICY.value = previous


def _verify_policy(pin):
    def apply(context):
        if context.verify_mode != ssl.CERT_REQUIRED:
            raise ssl.SSLError(tr("Política TLS sin verificación: conexión rechazada"))
        # The trusted file is the anchor even when it is not a self-signed root (exact pin).
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        if pin:
            context.check_hostname = False
    return apply


def _library():
    try:
        from s7commplus import Client
    except ImportError as exc:
        raise RuntimeError(tr("Falta la biblioteca S7CommPlus: instala abSCADA con el extra s7plus "
                              "(pip install -e '.[s7plus]'). No se incluye todavía en el ejecutable de Windows.")) from exc
    return Client


def capture_certificate(config):
    """Certificate the PLC presents, for the user to confirm in Studio. Runs outside the Qt thread.

    This is the only unverified TLS session: it sends no password, reads nothing and closes at
    once. Trust is stored only when the user accepts the fingerprints shown.
    """
    client = _library()()
    der = None
    try:
        with _tls_policy(None):
            try:
                client.connect(config["host"], int(config.get("port", 102)), use_tls=True, tls_ca=None, password=None,
                               allow_legacy_key_fallback=False, legacy_session_key_refresh_interval=None)
            except Exception as exc:
                # The handshake may have succeeded before the PLC refused the session: keep the certificate.
                failure = exc
            else:
                failure = None
            connection = getattr(client, "_connection", None)
            ssl_object = getattr(connection, "_ssl_object", None)
            if ssl_object is not None:
                der = ssl_object.getpeercert(binary_form=True)
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    if not der:
        raise ConnectionError(tr("El PLC no ha presentado certificado TLS: {exc}. Comprueba que tiene activada la "
                                 "comunicación PG/HMI segura.", exc=failure or tr("sin TLS")))
    return der


# --- errors ------------------------------------------------------------------------------------

def explain(exc):
    """A readable error that says what to check: certificate, permission, symbol, type or network."""
    if isinstance(exc, (PermissionError, LookupError)) and not isinstance(exc, KeyError):
        return exc
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ConnectionError(tr("Certificado del PLC rechazado ({reason}). Comprueba que el certificado importado para esta "
                                  "conexión es el del PLC (o su CA) y que no ha caducado. Si el PLC tiene un certificado nuevo, vuelve a "
                                  "confiar en él (Certificado del PLC… → Leer del PLC y confiar).",
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
    capture_certificate = staticmethod(capture_certificate)
    describe_certificates = staticmethod(describe_certificates)

    def __init__(self, config):
        self.config = config
        self.root = None
        self.client = None
        self.policy = None
        self.tags = {}  # symbol -> SymbolicTag, checked against the expected PLC type

    def attach(self, project_root):
        self.root = project_root

    def connect(self):
        if self.root is None:
            raise RuntimeError(tr("Conector S7 simbólico sin carpeta de proyecto (certificado y contraseña)"))
        ca = trust_path(self.root, self.config.get("id", ""))
        if not ca.exists():
            raise PermissionError(tr("No hay certificado de confianza para el PLC de esta conexión: en Studio, Conexiones → "
                                     "Certificado del PLC… → «Leer del PLC y confiar» o importa el de TIA. Sin él no se "
                                     "establece TLS verificado."))
        self.policy = _verify_policy(is_pin(ca.read_bytes()))
        from .secrets_store import SecretStore, connection_secret_key, secrets_path
        password = SecretStore(secrets_path(self.root)).get(connection_secret_key(self.config["id"])) or None
        client = _library()()
        try:
            with _tls_policy(self.policy):
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
                with _tls_policy(self.policy):
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
            with _tls_policy(self.policy):
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
            with _tls_policy(self.policy):
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
        with _tls_policy(self.policy):
            items = self.client.browse()
        for item in items:
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
