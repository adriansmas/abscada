"""S7CommPlus by symbol name over verified TLS, against the s7commplus emulator.

The emulator does not serve the PLC type-info tree that ``browse()`` parses, so the tests
replace ``Client.browse`` with entries whose access paths the emulator does serve (DB
area + classic blob LIDs). Everything else runs over the wire: TLS with certificate
verification, multi-variable reads, typed writes, errors, disconnection and reconnection.
The real browse, firmware behaviour and permissions need the physical PLC.
"""
import datetime
import ipaddress
import socket
import struct
import pytest

pytest.importorskip("s7commplus")
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from abscada import s7plus
from abscada.connectors import create, definition
from abscada.project import Project
from abscada.runtime import Runtime
from abscada.symbol_import import candidates, import_symbols, variable_name
from test_core import DEMO, wait_for

# DB1 of the emulator: name -> (type, offset). Browse entries point at these bytes.
LAYOUT = {"Habilitado": ("BOOL", 0, 1), "Vecino": ("BOOL", 1, 1), "Contador": ("DINT", 2, 4),
          "Consigna": ("REAL", 6, 4), "SoloLectura": ("INT", 10, 2), "Lista": ("INT", 12, 4)}


def browse_entries():
    entries = []
    for name, (kind, offset, size) in LAYOUT.items():
        entry = dict(name=f"DB_Prueba.{name}", access_sequence=f"{0x8A0E0001:X}.3.{offset:X}.{size:X}", data_type=kind)
        if name == "Lista":
            entry["array_dimensions"] = ((0, 2),)
        entries.append(entry)
    return entries


def certificate(tmp_path, name, ip="127.0.0.1", days=30):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=2))
            .not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True).sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (tmp_path / f"{name}.pem").write_bytes(pem)
    (tmp_path / f"{name}.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                             serialization.NoEncryption()))
    return pem, cert.public_bytes(serialization.Encoding.DER)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def plc(tmp_path, monkeypatch):
    from s7commplus import Client, Server
    from s7commplus.protocol import ProtocolVersion
    certificate(tmp_path, "plc")
    port = free_port()
    server = Server(protocol_version=ProtocolVersion.V2)
    db = server.register_raw_db(1, bytearray(64))
    db.write(0, b"\x01\x01"); db.write(2, struct.pack(">i", 1234)); db.write(6, struct.pack(">f", 42.5))
    db.write(10, struct.pack(">h", -7))
    server.start(port=port, use_tls=True, tls_cert=str(tmp_path / "plc.pem"), tls_key=str(tmp_path / "plc.key"))
    monkeypatch.setattr(Client, "browse", lambda self: browse_entries())
    root = tmp_path / "project"; root.mkdir()
    config = dict(id="plc1", protocol="s7plus", host="127.0.0.1", port=port, batch=2, poll_ms=50)
    try:
        yield dict(server=server, db=db, port=port, root=root, config=config, pem=(tmp_path / "plc.pem").read_bytes(),
                   tmp=tmp_path)
    finally:
        server.stop()


def connected(plc):
    adapter = create(plc["config"], plc["root"])
    adapter.connect()
    return adapter


# --- bindings and values ----------------------------------------------------------------------

def test_bindings_store_the_symbol_and_the_plc_type():
    spec = definition("s7plus")
    assert spec.validate_binding('"DB_Horno".Temperatura', "float", True) == dict(symbol="DB_Horno.Temperatura", encoding="REAL")
    assert spec.validate_binding(dict(symbol="DB.Zona[2].T", encoding="LREAL"), "float", False)["symbol"] == "DB.Zona[2].T"
    assert spec.describe(dict(symbol="DB.Marcha", encoding="BOOL"), "bool") == "DB.Marcha (BOOL)"
    for wrong in ("Temperatura", "DB. Temp", "", "DB..T"):
        with pytest.raises(ValueError):
            spec.validate_binding(dict(symbol=wrong, encoding="REAL"), "float", False)
    with pytest.raises(ValueError):
        spec.validate_binding(dict(symbol="DB.T", encoding="DINT"), "float", False)  # DINT is not a float
    assert not spec.supports_type("string")
    assert spec.secret and spec.trust_store


@pytest.mark.parametrize("encoding, value, raw", [("BOOL", True, b"\x01"), ("INT", -2, b"\xff\xfe"),
                                                   ("UDINT", 4000000000, struct.pack(">I", 4000000000)),
                                                   ("REAL", 1.5, struct.pack(">f", 1.5)), ("LREAL", -0.25, struct.pack(">d", -0.25))])
def test_values_are_encoded_with_the_plc_type(encoding, value, raw):
    assert s7plus.S7Plus.encode(encoding, value) == raw
    assert s7plus.S7Plus.decode("x", encoding, raw) == value


@pytest.mark.parametrize("encoding, value", [("INT", 40000), ("USINT", -1), ("BYTE", 256), ("DINT", 1.5)])
def test_out_of_range_writes_are_refused_before_sending(encoding, value):
    with pytest.raises(ValueError):
        s7plus.S7Plus.encode(encoding, value)


def test_incomplete_answers_are_not_published():
    with pytest.raises(ConnectionError, match="incompleta"):
        s7plus.S7Plus.decode("DB.T", "REAL", b"\x00\x01")


# --- trust ------------------------------------------------------------------------------------

def test_plc_certificate_is_trusted_per_connection(tmp_path):
    pem, der = certificate(tmp_path, "otro")
    assert s7plus.trusted_certificates(tmp_path, "plc1") == []
    info = s7plus.import_certificate(tmp_path, "plc1", der)  # DER is stored as PEM
    assert info[0]["addresses"] == ["127.0.0.1"] and len(info[0]["fingerprint"]) == 95
    assert s7plus.trust_path(tmp_path, "plc1").read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert s7plus.trusted_certificates(tmp_path, "plc2") == []  # not shared with other connections
    with pytest.raises(ValueError, match="X.509"):
        s7plus.import_certificate(tmp_path, "plc1", b"not a certificate")
    with pytest.raises(ValueError):
        s7plus.trust_path(tmp_path, "../fuera")
    s7plus.remove_certificate(tmp_path, "plc1")
    assert s7plus.trusted_certificates(tmp_path, "plc1") == []


def test_without_a_trusted_certificate_nothing_is_sent(tmp_path, monkeypatch):
    from s7commplus import Client
    monkeypatch.setattr(Client, "connect", lambda *a, **k: pytest.fail("connected without trust"))
    adapter = create(dict(id="plc1", protocol="s7plus", host="127.0.0.1", port=102, batch=20), tmp_path)
    with pytest.raises(PermissionError, match="certificado"):
        adapter.connect()


def test_the_library_is_called_with_tls_verification_and_no_legacy_authentication(tmp_path, monkeypatch):
    from s7commplus import Client
    calls = []
    monkeypatch.setattr(Client, "connect", lambda self, *a, **k: calls.append((a, k)))
    monkeypatch.setattr(Client, "tls_active", property(lambda self: False))
    _, der = certificate(tmp_path, "plc")
    s7plus.import_certificate(tmp_path, "plc1", der)
    adapter = create(dict(id="plc1", protocol="s7plus", host="10.0.0.5", port=102, batch=20), tmp_path)
    with pytest.raises(ConnectionError, match="TLS"):
        adapter.connect()  # a session without TLS is refused even if the library allowed it
    (host, port), options = calls[0]
    assert (host, port) == ("10.0.0.5", 102)
    assert options["use_tls"] is True and options["tls_ca"] == str(s7plus.trust_path(tmp_path, "plc1"))
    assert options["allow_legacy_key_fallback"] is False and options["legacy_session_key_refresh_interval"] is None


# --- over the wire ----------------------------------------------------------------------------

def test_reads_and_writes_by_symbol_over_verified_tls(plc):
    s7plus.import_certificate(plc["root"], "plc1", plc["pem"])
    adapter = connected(plc)
    try:
        assert adapter.client.tls_active
        requests = [(dict(symbol="DB_Prueba.Habilitado", encoding="BOOL"), "bool"),
                    (dict(symbol="DB_Prueba.Contador", encoding="DINT"), "int"),
                    ('"DB_Prueba".Consigna', "float"), (dict(symbol="DB_Prueba.SoloLectura", encoding="INT"), "int"),
                    (dict(symbol="DB_Prueba.Vecino", encoding="BOOL"), "bool")]
        groups = adapter.prepare_reads(requests)
        assert len(groups) == 3  # batch=2
        values = {}
        for read in groups:
            values.update(read())
        assert values == {0: True, 1: 1234, 2: 42.5, 3: -7, 4: True}
        adapter.write(dict(symbol="DB_Prueba.Consigna", encoding="REAL"), "float", 12.25)
        adapter.write(dict(symbol="DB_Prueba.Habilitado", encoding="BOOL"), "bool", False)
        adapter.write(dict(symbol="DB_Prueba.Contador", encoding="DINT"), "int", -5)
        assert bytes(plc["db"].data[:10]) == b"\x00\x01" + struct.pack(">i", -5) + struct.pack(">f", 12.25)  # neighbour intact
        assert adapter.read(dict(symbol="DB_Prueba.Consigna", encoding="REAL"), "float") == 12.25
    finally:
        adapter.close()


@pytest.mark.parametrize("address, kind, message", [
    (dict(symbol="DB_Prueba.NoExiste", encoding="INT"), "int", "no tiene el símbolo"),
    (dict(symbol="DB_Prueba.Contador", encoding="INT"), "int", "es DINT en el PLC"),
    (dict(symbol="DB_Prueba.Lista", encoding="INT"), "int", "array"),
])
def test_bindings_that_do_not_match_the_plc_are_refused(plc, address, kind, message):
    s7plus.import_certificate(plc["root"], "plc1", plc["pem"])
    adapter = connected(plc)
    try:
        with pytest.raises(LookupError, match=message):
            adapter.prepare_reads([(address, kind)])
        with pytest.raises(LookupError, match=message):
            adapter.write(address, kind, 1)
    finally:
        adapter.close()


@pytest.mark.parametrize("trusted, message", [("other", "rechazado"), ("wrong_ip", "rechazado")])
def test_an_unexpected_plc_identity_is_rejected(plc, trusted, message):
    if trusted == "other":
        pem, _ = certificate(plc["tmp"], "other")
        s7plus.import_certificate(plc["root"], "plc1", pem)
    else:
        # The right certificate for another address: the PLC is not the one configured.
        s7plus.import_certificate(plc["root"], "plc1", plc["pem"])
        plc["config"]["host"] = "localhost"
    adapter = create(plc["config"], plc["root"])
    with pytest.raises(ConnectionError, match=message):
        adapter.connect()
    assert adapter.client is None


def test_runtime_acquires_by_symbol_and_recovers_after_losing_the_plc(plc):
    s7plus.import_certificate(plc["root"], "plc1", plc["pem"])
    project = Project.load(DEMO)
    project.root = plc["root"]
    project.connections = [plc["config"]]
    project.variables = [
        dict(name="Habilitado", type="bool", initial=False, writable=True,
             binding=dict(connection="plc1", address=dict(symbol="DB_Prueba.Habilitado", encoding="BOOL"))),
        dict(name="Consigna", type="float", initial=0.0, writable=True,
             binding=dict(connection="plc1", address=dict(symbol="DB_Prueba.Consigna", encoding="REAL"))),
        dict(name="Contador", type="int", initial=0, writable=False,
             binding=dict(connection="plc1", address=dict(symbol="DB_Prueba.Contador", encoding="DINT")))]
    project.screens = {"overview": dict(width=100, height=100, elements=[])}
    project.faceplates = {}; project.alarms = dict(categories=[], items=[]); project.historian = dict(files=[])
    project.trends = {}; project.alarm_views = {}; project.scripts = {}; project.automation = dict(startup=[], tasks=[])
    project.validate()
    runtime = Runtime(project)
    runtime.start()
    try:
        wait_for(lambda: runtime.snapshot()["Contador"].quality == "good", timeout=10)
        assert (runtime.snapshot()["Consigna"].value, runtime.snapshot()["Contador"].value) == (42.5, 1234)
        runtime.write("Consigna", 37.25).result(timeout=5)
        wait_for(lambda: runtime.snapshot()["Consigna"].value == 37.25, timeout=5)
        plc["server"].stop()
        wait_for(lambda: runtime.snapshot()["Consigna"].quality == "bad", timeout=15)
        assert runtime.snapshot()["Consigna"].value == 37.25
        plc["server"].start(port=plc["port"], use_tls=True, tls_cert=str(plc["tmp"] / "plc.pem"), tls_key=str(plc["tmp"] / "plc.key"))
        wait_for(lambda: runtime.snapshot()["Consigna"].quality == "good", timeout=15)
    finally:
        runtime.stop()


# --- import of symbols ------------------------------------------------------------------------

def test_symbols_are_imported_as_variables_once(plc):
    s7plus.import_certificate(plc["root"], "plc1", plc["pem"])
    from abscada.symbol_import import explore
    found = explore(plc["config"], plc["root"])
    assert (dict(symbol="DB_Prueba.Contador", encoding="DINT"), "int") in found
    assert not any(address["symbol"] == "DB_Prueba.Lista" for address, _ in found)  # arrays come later
    project = Project.load(DEMO)
    project.connections.append(plc["config"])
    rows = candidates(project, plc["config"], found)
    created = import_symbols(project, plc["config"], rows[:2])
    assert created == ["DB_Prueba_Habilitado", "DB_Prueba_Vecino"]
    project.validate()
    variable = next(v for v in project.variables if v["name"] == "DB_Prueba_Habilitado")
    assert variable["binding"] == dict(connection="plc1", address=dict(symbol="DB_Prueba.Habilitado", encoding="BOOL"))
    assert variable["writable"] is False
    rows = candidates(project, plc["config"], found)
    assert rows[0][3] == "DB_Prueba_Habilitado"  # already imported: kept, not duplicated
    assert import_symbols(project, plc["config"], rows) == ["DB_Prueba_Contador", "DB_Prueba_Consigna", "DB_Prueba_SoloLectura"]
    assert variable_name("DB_Horno.Zona[2].Temperatura") == "DB_Horno_Zona_2_Temperatura"


# --- Studio -----------------------------------------------------------------------------------

@pytest.fixture
def studio(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from abscada.ui import Window
    app = QApplication.instance() or QApplication([])
    project = Project(tmp_path, dict(schema_version=1, name="Simbolico", startup_screen="main"), {}, [],
                      [dict(id="plc1", protocol="s7plus", host="127.0.0.1", port=102, batch=20, poll_ms=250)],
                      {"main": dict(width=800, height=600, elements=[])}, {})
    project.save()
    window = Window(Project.load(tmp_path))
    monkeypatch.setattr(window, "error", lambda exc: pytest.fail(f"Unexpected UI error: {exc}"))
    window.show(); app.processEvents()
    yield window
    window.dirty = False
    window.close(); app.processEvents()


def test_connection_form_offers_password_and_plc_certificate(studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPushButton
    seen = {}
    def inspect():
        dialog = QApplication.activeModalWidget()
        seen.update({b.text(): b.isVisibleTo(dialog) for b in dialog.findChildren(QPushButton)})
        dialog.reject()
    QTimer.singleShot(0, inspect)
    studio.connection_form("plc1")
    assert seen["Contraseña…"] and seen["Certificado del PLC…"] and not seen["Certificados…"]


def test_import_dialog_lists_new_symbols_and_creates_variables(studio, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from abscada import symbol_import
    from abscada.symbol_import_editor import SymbolImportDialog
    found = [(dict(symbol="DB_Prueba.Marcha", encoding="BOOL"), "bool"), (dict(symbol="DB_Prueba.Consigna", encoding="REAL"), "float")]
    monkeypatch.setattr(symbol_import, "explore", lambda config, root: found)
    dialog = SymbolImportDialog(studio)
    assert dialog.connection.currentData() == "plc1"
    dialog.start()
    wait_for(lambda: (QApplication.processEvents(), dialog.list.count() == 2)[1])
    dialog.filter.setText("consigna"); dialog.check_visible(True); dialog.filter.clear()
    assert [r[2] for r in dialog.selected()] == ["DB_Prueba.Consigna (REAL)"]
    dialog.writable.setChecked(True)
    dialog.check()
    created = symbol_import.import_symbols(studio.project, dialog.config(), dialog.selected(), True)
    assert created == ["DB_Prueba_Consigna"] and studio.project.tags()["DB_Prueba_Consigna"]["writable"]
    dialog.start()
    wait_for(lambda: (QApplication.processEvents(), not dialog.timer.isActive())[1])
    QApplication.processEvents()
    item = next(dialog.list.item(i) for i in range(2) if "Consigna" in dialog.list.item(i).text())
    assert "→ DB_Prueba_Consigna" in item.text() and not item.flags() & Qt.ItemFlag.ItemIsEnabled
    dialog.reject()
