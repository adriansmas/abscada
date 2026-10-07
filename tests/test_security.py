import time
import pytest
from abscada.security import (SecurityService, UserStore, AuthenticationError, default_security, hash_password,
                              verify_password, validate_security, required_permission, users_path)
from abscada.runtime import Runtime
from abscada.storage import ArchiveReader, database_path
from test_operations import operational_project
from test_core import wait_for


POLICY = default_security()


def secured(project, **policy):
    project.security = dict(default_security(), enabled=True, **policy)
    store = UserStore(users_path(project.root))
    store.create("ana", "operar-la-planta", ["operator"], project.security, full_name="Ana Pérez", must_change=False)
    store.create("vera", "solo-mirar-123", ["viewer"], project.security, must_change=False)
    return store


def test_password_hashes_are_salted_and_verified():
    first, second = hash_password("una-clave-larga"), hash_password("una-clave-larga")
    assert first["hash"] != second["hash"] and first["algorithm"] == "scrypt"
    assert verify_password("una-clave-larga", first) and not verify_password("otra-clave-larga", first)


@pytest.mark.parametrize("password", ["corta", "ana", "aaaaaaaaaaaa"])
def test_password_policy(tmp_path, password):
    with pytest.raises(ValueError):
        UserStore(tmp_path / "users.json").create("ana", password, ["operator"], POLICY)


def test_accounts_file_never_holds_passwords(tmp_path):
    store = UserStore(tmp_path / "users.json")
    store.create("ana", "operar-la-planta", ["operator"], POLICY)
    text = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "operar-la-planta" not in text and "scrypt" in text


def test_lockout_after_failed_attempts_and_generic_errors(tmp_path):
    store = UserStore(tmp_path / "users.json")
    policy = dict(POLICY, max_failed_logins=3, lockout_minutes=5)
    store.create("ana", "operar-la-planta", ["operator"], policy, must_change=False)
    with pytest.raises(AuthenticationError, match="Usuario o contraseña incorrectos"):
        store.authenticate("nadie", "x", policy)
    for _ in range(3):
        with pytest.raises(AuthenticationError, match="incorrectos"):
            store.authenticate("ana", "mala", policy)
    with pytest.raises(AuthenticationError, match="bloqueado"):
        store.authenticate("ana", "operar-la-planta", policy)
    assert store.authenticate("ana", "operar-la-planta", policy, now=time.time() + 301)["name"] == "ana"
    store.set_disabled("ana", True)
    with pytest.raises(AuthenticationError, match="desactivado"):
        store.authenticate("ana", "operar-la-planta", policy)


@pytest.mark.parametrize("change", [dict(enabled="yes"), dict(roles=[]), dict(password_min_length=4),
                                    dict(roles=[dict(id="x", name="X", permissions=["volar"])]),
                                    dict(roles=[dict(id="x", name="X", permissions=[])] * 2), dict(extra=1)])
def test_invalid_security_configuration(change):
    with pytest.raises(ValueError):
        validate_security(dict(default_security(), **change))


def test_required_permission_by_control():
    assert required_permission(dict(kind="button", action="set", tag="A")) == "operate"
    assert required_permission(dict(kind="input", tag="A")) == "operate"
    assert required_permission(dict(kind="button", action="script", script="s")) == "operate"
    assert required_permission(dict(kind="button", action="screen", screen="x")) is None
    assert required_permission(dict(kind="button", action="screen", screen="x", permission="manage_users")) == "manage_users"


def test_disabled_security_allows_everything(operational_project):
    service = SecurityService(operational_project)
    assert not service.enabled and service.permits(None, "operate")


def test_sessions_permissions_and_timeout(operational_project):
    secured(operational_project, session_timeout_minutes=1)
    service = SecurityService(operational_project)
    ana, vera = service.login("ana", "operar-la-planta"), service.login("vera", "solo-mirar-123")
    assert ana.display == "Ana Pérez" and service.permits(ana, "operate") and service.permits(ana, "acknowledge")
    assert not service.permits(vera, "operate") and not service.permits(None, "operate")
    ana.last_activity -= 61
    assert service.expired(ana) and not service.permits(ana, "operate")


def test_runtime_commands_are_checked_and_audited(operational_project):
    secured(operational_project)
    operational_project.save()
    runtime = Runtime(operational_project)
    runtime.start()
    try:
        with pytest.raises(PermissionError):
            runtime.command("Level", 12.0, None)
        with pytest.raises(AuthenticationError):
            runtime.login("ana", "mala-clave-larga")
        session = runtime.login("ana", "operar-la-planta")
        runtime.command("Level", 12.0, session).result(2)
        assert runtime.snapshot()["Level"].value == 12.0
        runtime.logout()
        reader = ArchiveReader(database_path(operational_project))
        wait_for(lambda: len(reader.query("SELECT * FROM audit WHERE action IN ('login','login_failed','write_denied','logout')")) == 4)
        write = reader.query("SELECT actor, detail FROM audit WHERE action='write_requested'")
        assert write and write[-1]["actor"] == "ana" and write[-1]["detail"].startswith("hmi:")
    finally:
        runtime.stop()


def test_must_change_password_blocks_commands(operational_project):
    secured(operational_project)
    UserStore(users_path(operational_project.root)).create("nuevo", "temporal-12345", ["operator"], operational_project.security)
    service = SecurityService(operational_project)
    session = service.login("nuevo", "temporal-12345")
    assert session.must_change and not service.permits(session, "operate")
