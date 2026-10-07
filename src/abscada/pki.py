"""OPC UA application certificates and trust lists, saved with the project. No Qt.

    <project>/pki/own/        the project's certificate (DER) and private key (PEM, 0600)
    <project>/pki/trusted/    peer certificates the administrator accepted
    <project>/pki/rejected/   peers that tried to connect and were not trusted yet

They travel with the project, as in TIA Portal: a copy on another PC keeps the identity
the PLCs already trust. The application URI is derived from the project folder name, not
from the host, for the same reason. An unknown peer is never trusted automatically: its
certificate lands in ``rejected`` and an administrator moves it to ``trusted``.
Version 0.5.0b2 kept all this in ``runtime/pki``; it moves the first time it is used.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import re
import shutil
import socket
from pathlib import Path
from .i18n import tr

PKI = ("own", "trusted", "rejected")


def pki_root(project_root):
    root = Path(project_root) / "pki"
    legacy = Path(project_root) / "runtime" / "pki"
    if legacy.is_dir() and not root.exists():
        shutil.move(str(legacy), str(root))
    return root


def application_uri(project_root, role):
    name = re.sub(r"[^a-z0-9._-]+", "-", Path(project_root).resolve().name.lower()).strip("-") or "proyecto"
    return f"urn:abscada:{name}:{role}"


def certificate_uri(der: bytes) -> str:
    from cryptography import x509
    certificate = x509.load_der_x509_certificate(der)
    try:
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return ""
    uris = names.get_values_for_type(x509.UniformResourceIdentifier)
    return uris[0] if uris else ""


def fingerprint(der: bytes) -> str:
    return hashlib.sha1(der).hexdigest().upper()  # OPC UA tools show SHA-1 thumbprints


def ensure_own_certificate(project_root, uri, common_name, years=5):
    """Return (certificate_path, key_path), creating a self-signed pair the first time."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    own = pki_root(project_root) / "own"
    role = uri.rsplit(":", 1)[-1]
    certificate_path, key_path = own / f"{role}.der", own / f"{role}.pem"
    # A renamed project folder means a new application URI: the old certificate no longer matches it.
    if certificate_path.exists() and key_path.exists() and certificate_uri(certificate_path.read_bytes()) == uri:
        return certificate_path, key_path
    own.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    host = socket.gethostname()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "abSCADA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365 * years))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri), x509.DNSName(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=True,
                                     data_encipherment=True, key_agreement=False, key_cert_sign=True, crl_sign=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
    return certificate_path, key_path


def folder(project_root, name):
    path = pki_root(project_root) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_trusted(project_root, der: bytes) -> bool:
    return any(p.read_bytes() == der for p in folder(project_root, "trusted").glob("*.der"))


def reject(project_root, der: bytes) -> Path:
    path = folder(project_root, "rejected") / f"{fingerprint(der)}.der"
    if not path.exists():
        path.write_bytes(der)
    return path


def trust(project_root, der: bytes) -> Path:
    path = folder(project_root, "trusted") / f"{fingerprint(der)}.der"
    path.write_bytes(der)
    (folder(project_root, "rejected") / path.name).unlink(missing_ok=True)
    return path


def describe(der: bytes) -> dict:
    from cryptography import x509
    certificate = x509.load_der_x509_certificate(der)
    try:
        uris = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value \
            .get_values_for_type(x509.UniformResourceIdentifier)
    except x509.ExtensionNotFound:
        uris = []
    return dict(subject=certificate.subject.rfc4514_string(), uri=", ".join(uris), fingerprint=fingerprint(der),
                valid_until=certificate.not_valid_after_utc.isoformat())


def listing(project_root, name):
    return [dict(describe(p.read_bytes()), path=p) for p in sorted(folder(project_root, name).glob("*.der"))]


class UntrustedCertificate(ConnectionError):
    def __init__(self, der, path):
        self.der, self.path = der, path
        info = describe(der)
        super().__init__(tr("Certificado del servidor no confiable ({subject}, huella {info_fingerprint_16}…). Revísalo y acéptalo en la conexión para continuar.", subject=info['subject'], info_fingerprint_16=info['fingerprint'][:16]))
