"""OPC UA server that publishes the project's variables (asyncua). Runs inside the runtime.

Address space: Objects/abSCADA/<structure>/<field>, one Variable per tag, NodeId
``ns=<index>;s=<tag name>`` in namespace ``urn:abscada:<project name>``. Values and quality
come from the runtime snapshot; a client write is a command: it goes through
``Runtime.command`` (permission, audit with the OPC UA user, the connection's write queue)
and the published value only changes when the runtime observes it.

Access rules:
- Sign in with an abSCADA account whose role has «Acceso por OPC UA» (``opcua``).
  Failed attempts count towards the same lockout as the HMI.
- Writing also needs «Mandos y consignas» (``operate``).
- Anonymous access only if ``allow_anonymous`` is set, and always read-only.
- Client certificates must be trusted by an administrator (runtime/pki/trusted).
"""
from __future__ import annotations

import asyncio
import datetime
import threading

SECURITY = ("Basic256Sha256_SignAndEncrypt", "Aes256_Sha256_RsaPss_SignAndEncrypt",
            "Aes128_Sha256_RsaOaep_SignAndEncrypt", "Basic256Sha256_Sign", "None")
UPDATE_SECONDS = 0.2


def default_server():
    return dict(enabled=False, port=4840, security=["Basic256Sha256_SignAndEncrypt"], allow_anonymous=False)


def validate_server(config):
    if not isinstance(config, dict) or set(config) - set(default_server()):
        raise ValueError("Configuración del servidor OPC UA inválida")
    for key in ("enabled", "allow_anonymous"):
        if not isinstance(config.get(key, False), bool):
            raise ValueError(f"Servidor OPC UA: {key} debe ser booleano")
    port = config.get("port", 4840)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Servidor OPC UA: puerto entre 1 y 65535")
    security = config.get("security", [])
    if not isinstance(security, list) or not security or set(security) - set(SECURITY):
        raise ValueError("Servidor OPC UA: elige al menos una política de seguridad válida")


def endpoint(config):
    return f"opc.tcp://0.0.0.0:{config.get('port', 4840)}/abscada"


class OpcUaServer:
    def __init__(self, runtime):
        self.runtime = runtime
        self.config = runtime.project.opcua_server
        self.thread = None
        self.loop = None
        self.ready = threading.Event()
        self.stopping = None
        self.error = ""
        self.namespace = None
        self.nodes = {}       # tag -> NodeId
        self.by_node = {}     # NodeId -> tag
        self.sessions = {}    # OPC UA user name -> abSCADA Session

    # -- lifecycle ---------------------------------------------------------
    def start(self, timeout=20):
        self.thread = threading.Thread(target=self._thread, name="abscada-opcua-server", daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout) or self.error:
            self.stop()
            raise RuntimeError(self.error or "El servidor OPC UA no arranca")

    def stop(self, timeout=5):
        if self.loop and self.stopping and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.stopping.set)
        if self.thread:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise TimeoutError("El servidor OPC UA sigue cerrando")

    def _thread(self):
        self.loop = asyncio.new_event_loop()
        try:
            self.loop.run_until_complete(self._main())
        except Exception as exc:
            self.error = f"Servidor OPC UA: {exc}"
        finally:
            self.ready.set()
            self.loop.close()

    async def _main(self):
        from asyncua import Server, ua
        from . import pki

        self.stopping = asyncio.Event()
        project = self.runtime.project
        server = Server(user_manager=_Users(self))
        await server.init()
        server.set_endpoint(endpoint(self.config))
        server.set_server_name(f"abSCADA · {project.manifest['name']}")
        uri = pki.application_uri(project, "server")
        await server.set_application_uri(uri)
        policies = [getattr(ua.SecurityPolicyType, "NoSecurity" if p == "None" else p) for p in self.config["security"]]
        if any(p != "None" for p in self.config["security"]):
            certificate, key = pki.ensure_own_certificate(project.root, uri, "abSCADA server")
            await server.load_certificate(str(certificate))
            await server.load_private_key(str(key))
        server.set_security_policy(policies, permission_ruleset=_Rules(self))
        tokens = [ua.UserNameIdentityToken]
        if self.config.get("allow_anonymous"):
            tokens.append(ua.AnonymousIdentityToken)
        server.set_identity_tokens(tokens)
        root = project.root

        async def validate_client(certificate, _application):
            from asyncua.common.utils import ServiceError
            from cryptography.hazmat.primitives.serialization import Encoding
            der = certificate.public_bytes(Encoding.DER)
            if not pki.is_trusted(root, der):
                pki.reject(root, der)
                self.runtime.audit("opcua_certificate_rejected", pki.fingerprint(der), detail=pki.describe(der)["subject"])
                raise ServiceError(ua.StatusCodes.BadSecurityChecksFailed)
        server.set_certificate_validator(validate_client)

        self.namespace = await server.register_namespace(f"urn:abscada:{project.manifest['name']}")
        await self._build(server, ua)
        async with server:
            self.runtime.audit("opcua_server_start", endpoint(self.config))
            self.ready.set()
            published = {}
            while not self.stopping.is_set():
                for name, sample in self.runtime.snapshot().items():
                    if published.get(name) is sample or name not in self.nodes:
                        continue
                    published[name] = sample
                    await server.write_attribute_value(self.nodes[name], self._data_value(ua, name, sample))
                try:
                    await asyncio.wait_for(self.stopping.wait(), UPDATE_SECONDS)
                except asyncio.TimeoutError:
                    pass
            self.runtime.audit("opcua_server_stop", endpoint(self.config))

    async def _build(self, server, ua):
        variant = {"bool": ua.VariantType.Boolean, "int": ua.VariantType.Int64,
                   "float": ua.VariantType.Double, "string": ua.VariantType.String}
        self.types = {}
        top = await server.nodes.objects.add_folder(ua.NodeId("abSCADA", self.namespace), "abSCADA")
        folders = {"": top}
        for name, tag in sorted(self.runtime.tags.items()):
            parts = name.split(".")
            for depth in range(1, len(parts)):
                path = ".".join(parts[:depth])
                if path not in folders:
                    folders[path] = await folders[".".join(parts[:depth - 1])].add_folder(
                        ua.NodeId(path + "/", self.namespace), parts[depth - 1])
            node_id = ua.NodeId(name, self.namespace)
            self.types[name] = variant[tag["type"]]
            node = await folders[".".join(parts[:-1])].add_variable(
                node_id, parts[-1], ua.Variant(tag["initial"], variant[tag["type"]]))
            if tag.get("writable"):
                await node.set_writable()
            self.nodes[name], self.by_node[node_id] = node_id, name

    def _data_value(self, ua, name, sample):
        code = {"good": ua.StatusCodes.Good, "uncertain": ua.StatusCodes.UncertainInitialValue}.get(
            sample.quality, ua.StatusCodes.BadCommunicationError)
        value = sample.value
        if self.types[name] == ua.VariantType.Int64:
            value = int(value)
        elif self.types[name] == ua.VariantType.Double:
            value = float(value)
        stamp = datetime.datetime.fromtimestamp(sample.timestamp, datetime.timezone.utc)
        return ua.DataValue(ua.Variant(value, self.types[name]), ua.StatusCode(code),
                            SourceTimestamp=stamp, ServerTimestamp=stamp)

    # -- access control (called on the server's event loop) -----------------
    def login(self, username, password):
        security = self.runtime.security
        if not security.enabled:
            return None  # no accounts to check: only anonymous read access, if allowed
        try:
            session = security.login(username, password)
        except PermissionError as exc:
            if self.runtime.operations:  # actor = the name tried, as for the HMI login
                self.runtime.operations.audit("opcua_login_failed", username or "", actor=username or "", detail=str(exc))
            return None
        if "opcua" not in session.permissions or session.must_change:
            self.runtime.audit("opcua_login_denied", session.user, session, "sin permiso de acceso OPC UA")
            return None
        self.sessions[session.user] = session
        self.runtime.audit("opcua_login", session.user, session)
        return session

    def authorize_write(self, user_name, body):
        from asyncua import ua
        from asyncua.ua.ua_binary import struct_from_binary
        session = self.sessions.get(user_name)
        if session is None:
            return False
        self.runtime.security.touch(session)
        # Parse a copy: asyncua decodes the same buffer again after this check.
        params = struct_from_binary(ua.WriteParameters, body.copy() if hasattr(body, "copy") else body)
        requests = []
        for item in params.NodesToWrite:
            tag = self.by_node.get(item.NodeId)
            if tag is None or item.AttributeId != ua.AttributeIds.Value:
                self.runtime.audit("write_denied", str(item.NodeId), session, "opcua: nodo no escribible")
                return False
            requests.append((tag, item.Value.Value.Value))
        # Check every item before sending any, so a request is applied entirely or not at all.
        from .project import coerce
        try:
            for tag, value in requests:
                if not self.runtime.tags[tag].get("writable"):
                    raise ValueError(f"Variable de solo lectura: {tag}")
                coerce(value, self.runtime.tags[tag]["type"])
                if not self.runtime.security.permits(session, "operate"):
                    raise PermissionError("sin permiso de mando")
        except (ValueError, PermissionError) as exc:
            self.runtime.audit("write_denied", requests[0][0] if requests else "", session, f"opcua: {exc}")
            return False
        for tag, value in requests:
            try:
                self.runtime.command(tag, value, session, origin="opcua")
            except Exception:
                return False
        return True


class _Users:
    def __init__(self, server):
        self.server = server

    def get_user(self, iserver, username=None, password=None, certificate=None):
        from asyncua.crypto.permission_rules import User, UserRole
        if username:
            session = self.server.login(username, password)
            return User(role=UserRole.User, name=session.user) if session else None
        if self.server.config.get("allow_anonymous"):
            return User(role=UserRole.Anonymous)
        return None


class _Rules:
    def __init__(self, server):
        from asyncua import ua
        from asyncua.crypto.permission_rules import USER_TYPES
        self.server = server
        self.allowed = {ua.NodeId(t) for t in USER_TYPES}
        self.write = ua.NodeId(ua.ObjectIds.WriteRequest_Encoding_DefaultBinary)

    def check_validity(self, user, action_type_id, body):
        from asyncua.crypto.permission_rules import UserRole
        if action_type_id not in self.allowed:
            return False  # never let a client change the address space
        if action_type_id == self.write:
            if user is None or user.role != UserRole.User:
                return False
            return self.server.authorize_write(user.name, body)
        if user is not None and user.name in self.server.sessions:
            self.server.runtime.security.touch(self.server.sessions[user.name])
        return True
