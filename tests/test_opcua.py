"""OPC UA end to end: abSCADA's client connector against abSCADA's own server, encrypted."""
import socket
import pytest
from abscada import pki
from abscada.connectors import create
from abscada.opcua_server import default_server, validate_server
from abscada.runtime import Runtime
from abscada.secrets_store import SecretStore, connection_secret_key, secrets_path
from abscada.security import UserStore, default_security, users_path
from abscada.storage import ArchiveReader, database_path
from test_operations import operational_project
from test_core import wait_for

pytest.importorskip("asyncua")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def served(operational_project):
    project = operational_project
    roles = default_security()["roles"] + [dict(id="scada_client", name="Cliente SCADA", permissions=["opcua", "operate"]),
                                            dict(id="opc_reader", name="Lector OPC", permissions=["opcua"])]
    project.security = dict(default_security(), enabled=True, roles=roles)
    store = UserStore(users_path(project.root))
    store.create("mes", "clave-del-mes-1", ["scada_client"], project.security, must_change=False)
    store.create("lector", "clave-lectura-1", ["opc_reader"], project.security, must_change=False)
    store.create("ana", "operar-la-planta", ["operator"], project.security, must_change=False)
    project.opcua_server = dict(default_server(), enabled=True, port=free_port())
    project.save()
    runtime = Runtime(project)
    runtime.start()
    yield project, runtime
    runtime.stop()


def connection(project, user, password, security="Basic256Sha256_SignAndEncrypt"):
    config = dict(id="srv_" + user, protocol="opcua", endpoint=f"opc.tcp://127.0.0.1:{project.opcua_server['port']}/abscada",
                  security=security, username=user, timeout_ms=4000)
    SecretStore(secrets_path(project.root)).set(connection_secret_key(config["id"]), password)
    return config


def connect(project, config):
    adapter = create(config, project.root)
    adapter.connect()
    return adapter


def trust_everything_rejected(project):
    for item in pki.listing(project.root, "rejected"):
        pki.trust(project.root, item["path"].read_bytes())


def test_certificates_must_be_trusted_on_both_sides(served):
    project, runtime = served
    config = connection(project, "mes", "clave-del-mes-1")
    with pytest.raises(Exception, match="BadSecurityChecksFailed"):
        connect(project, config)                       # CreateSession: the server does not trust the client
    assert [i["uri"] for i in pki.listing(project.root, "rejected")] == [pki.application_uri(project, "client")]
    trust_everything_rejected(project)
    with pytest.raises(pki.UntrustedCertificate):
        connect(project, config)                       # then the client does not trust the server
    assert [i["uri"] for i in pki.listing(project.root, "rejected")] == [pki.application_uri(project, "server")]
    trust_everything_rejected(project)
    connect(project, config).close()
    assert not pki.listing(project.root, "rejected") and len(pki.listing(project.root, "trusted")) == 2


def test_read_write_with_permissions_and_audit(served):
    project, runtime = served
    for _ in range(2):  # accept the client certificate, then the server certificate
        try:
            connect(project, connection(project, "mes", "clave-del-mes-1")).close()
        except Exception:
            trust_everything_rejected(project)
    mes = connect(project, connection(project, "mes", "clave-del-mes-1"))
    try:
        assert mes.read('ns=2;s=Level', "float") == 0.0
        assert mes.read(f"nsu=urn:abscada:{project.manifest['name']};s=Fault", "bool") is False
        mes.write("ns=2;s=Level", "float", 42.5)
        wait_for(lambda: runtime.snapshot()["Level"].value == 42.5)
        wait_for(lambda: mes.read("ns=2;s=Level", "float") == 42.5)
    finally:
        mes.close()
    reader_client = connect(project, connection(project, "lector", "clave-lectura-1"))
    try:
        assert reader_client.read("ns=2;s=Level", "float") == 42.5
        with pytest.raises(Exception):
            reader_client.write("ns=2;s=Level", "float", 1.0)  # no «operate»: BadUserAccessDenied
    finally:
        reader_client.close()
    assert runtime.snapshot()["Level"].value == 42.5
    for user, password in (("ana", "operar-la-planta"), ("mes", "clave-equivocada")):
        with pytest.raises(Exception):
            connect(project, connection(project, user, password))  # no «opcua» / wrong password
    archive = ArchiveReader(database_path(project))
    wait_for(lambda: archive.query("SELECT 1 FROM audit WHERE action='write_denied'")
             and archive.query("SELECT 1 FROM audit WHERE action='opcua_login_failed'"))
    actions = {(r["action"], r["actor"]) for r in archive.query("SELECT action, actor FROM audit")}
    assert ("opcua_login", "mes") in actions and ("write_requested", "mes") in actions
    assert ("opcua_login_denied", "ana") in actions and ("opcua_login_failed", "mes") in actions
    detail = archive.query("SELECT detail FROM audit WHERE action='write_requested' AND actor='mes'")[-1]["detail"]
    assert detail.startswith("opcua:")


def test_anonymous_is_rejected_unless_allowed(served):
    project, runtime = served
    config = connection(project, "mes", "x", security="None")
    config["username"] = ""
    with pytest.raises(Exception):
        connect(project, config)  # endpoint without security is not offered, and anonymous is off


@pytest.mark.parametrize("change", [dict(port=0), dict(security=[]), dict(security=["Basic128"]),
                                    dict(enabled="si"), dict(extra=True)])
def test_invalid_server_configuration(change):
    with pytest.raises(ValueError):
        validate_server(dict(default_server(), **change))


def test_client_binding_validation():
    from abscada.connectors import definition
    spec = definition("opcua")
    for good in ('ns=3;s="DB_Motor"."Speed"', "ns=2;i=1001", "nsu=http://example.org/UA/;s=Level"):
        assert spec.validate_binding(good, "float", True)["node"] == good
    for bad in ("Level", "ns=x;s=a", "ns=2;q=1"):
        with pytest.raises(ValueError):
            spec.validate_binding(bad, "float", True)
