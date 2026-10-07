"""OPC UA client connector (asyncua). Reads and writes Value attributes by NodeId.

Security follows the usual OPC UA practice:
- Each project has its own application certificate (pki/own), created on
  first use. The server must trust it (in an S7-1500: TIA Portal > OPC UA > trusted clients,
  or "accept automatically" during commissioning).
- The server certificate is accepted only if an administrator trusted it. The first attempt
  stores it in pki/rejected and fails with a clear message; Studio offers to trust it.
- User names live in the connection; passwords live in the project's secrets.json.

Bindings name a NodeId in the standard string form: ``ns=3;s="Motor_DB"."Speed"``,
``ns=2;i=1001`` or with the namespace URI, ``nsu=http://example.org/UA/;s=Level``. The
namespace URI form survives servers that reorder their namespace table.
"""
from __future__ import annotations

import asyncio
import re

from .protocol_definition import Field, ProtocolDefinition

SECURITY = (
    ("Basic256Sha256_SignAndEncrypt", "Basic256Sha256 · firma y cifrado", ()),
    ("Aes256_Sha256_RsaPss_SignAndEncrypt", "Aes256-Sha256-RsaPss · firma y cifrado", ()),
    ("Aes128_Sha256_RsaOaep_SignAndEncrypt", "Aes128-Sha256-RsaOaep · firma y cifrado", ()),
    ("Basic256Sha256_Sign", "Basic256Sha256 · solo firma", ()),
    ("None", "Sin seguridad (solo pruebas)", ()),
)

_NODE = re.compile(r"^(?:ns=\d+|nsu=[^;]+);(?:i=\d+|s=.+|g=[0-9A-Fa-f-]{36}|b=[A-Za-z0-9+/=]+)$")


def normalize(address, kind):
    if isinstance(address, str):
        return dict(node=address.strip())
    if not isinstance(address, dict):
        raise ValueError("OPC UA necesita el NodeId de la variable")
    return dict(address)


def check_binding(address, kind, writable):
    if not _NODE.match(address.get("node", "")):
        raise ValueError('NodeId inválido; ejemplos: ns=3;s="DB_Motor"."Velocidad", ns=2;i=1001, nsu=http://…;s=Nivel')


def describe(address, kind):
    return normalize(address, kind)["node"]


DEFINITION = ProtocolDefinition(
    "OPC UA",
    (Field("endpoint", "Endpoint", "opc.tcp://127.0.0.1:4840"),
     Field("security", "Seguridad", "Basic256Sha256_SignAndEncrypt", choices=SECURITY),
     Field("username", "Usuario (vacío = anónimo)", "", optional=True),
     Field("timeout_ms", "Timeout (ms)", 4000, 500, 60000)),
    (Field("node", "NodeId", 'ns=3;s="DB".Variable'),),
    normalize, check_binding, describe)

_INTEGERS = {"SByte", "Byte", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64"}


class OpcUaClient:
    definition = DEFINITION

    def __init__(self, config):
        self.config = config
        self.root = None
        self.loop = None
        self.client = None
        self.nodes = {}
        self.types = {}

    def attach(self, project_root):
        self.root = project_root

    # The worker thread owns a private event loop: no extra threads, and close() is synchronous.
    def _run(self, coroutine):
        timeout = self.config.get("timeout_ms", 4000) / 1000
        return self.loop.run_until_complete(asyncio.wait_for(coroutine, timeout * 2))

    def connect(self):
        if self.root is None:
            raise RuntimeError("Conector OPC UA sin carpeta de proyecto (certificados y contraseñas)")
        self.loop = asyncio.new_event_loop()
        try:
            self._run(self._connect())
        except BaseException:
            self.close()
            raise

    async def _connect(self):
        from asyncua import Client, ua
        from asyncua.crypto import security_policies
        from . import pki
        from .secrets_store import SecretStore, connection_secret_key, secrets_path

        timeout = self.config.get("timeout_ms", 4000) / 1000
        client = Client(self.config["endpoint"], timeout=timeout)
        client.name = "abSCADA"
        client.application_uri = pki.application_uri(self.root, "client")
        client.description = "abSCADA"
        security = self.config.get("security", "Basic256Sha256_SignAndEncrypt")
        if security != "None":
            policy_name, mode_name = security.rsplit("_", 1)
            policy = getattr(security_policies, "SecurityPolicy" + policy_name.replace("_", ""))
            mode = getattr(ua.MessageSecurityMode, mode_name)
            certificate, key = pki.ensure_own_certificate(self.root, client.application_uri, "abSCADA client")
            root = self.root

            async def validate(certificate_object, _application):
                from cryptography.hazmat.primitives.serialization import Encoding
                der = certificate_object.public_bytes(Encoding.DER)
                if not pki.is_trusted(root, der):
                    raise pki.UntrustedCertificate(der, pki.reject(root, der))
            client.certificate_validator = validate
            await client.set_security(policy, str(certificate), str(key), mode=mode)
        username = self.config.get("username", "")
        if username:
            password = SecretStore(secrets_path(self.root)).get(connection_secret_key(self.config["id"]))
            if password is None:
                raise PermissionError("Falta la contraseña de esta conexión: introdúcela en Studio (Conexiones)")
            client.set_user(username)
            client.set_password(password)
        try:
            await client.connect()
        except Exception as exc:
            # asyncua wraps the validator error; surface the trust problem itself.
            cause = exc
            while cause is not None and not isinstance(cause, pki.UntrustedCertificate):
                cause = cause.__cause__ or cause.__context__
            raise cause or exc
        self.client = client

    def _node(self, address):
        from asyncua import ua
        text = normalize(address, None)["node"]
        if text not in self.nodes:
            if text.startswith("nsu="):
                uri, _, identifier = text[4:].partition(";")
                index = self._run(self.client.get_namespace_index(uri))
                node_id = ua.NodeId.from_string(f"ns={index};{identifier}")
            else:
                node_id = ua.NodeId.from_string(text)
            self.nodes[text] = self.client.get_node(node_id)
        return self.nodes[text]

    def read(self, address, kind):
        node = self._node(address)
        value = self._run(node.read_data_value())
        if not value.StatusCode.is_good():
            raise ConnectionError(f"Calidad OPC UA {value.StatusCode.name}")
        result = value.Value.Value
        if kind == "string" and result is not None and not isinstance(result, str):
            result = getattr(result, "Text", None) or str(result)
        return result

    def write(self, address, kind, value):
        from asyncua import ua
        node = self._node(address)
        key = describe(address, kind)
        if key not in self.types:
            self.types[key] = self._run(node.read_data_type_as_variant_type())
        variant_type = self.types[key]
        if variant_type.name in _INTEGERS:
            value = int(value)
        elif variant_type.name in {"Float", "Double"}:
            value = float(value)
        # No timestamps: many servers (S7-1500 among them) reject writes that carry one.
        self._run(node.write_value(ua.DataValue(ua.Variant(value, variant_type))))

    def close(self):
        try:
            if self.client is not None and self.loop is not None:
                try:
                    self._run(self.client.disconnect())
                except Exception:
                    pass
        finally:
            self.client = None
            self.nodes.clear()
            if self.loop is not None:
                self.loop.close()
                self.loop = None
