"""Users, roles and operator sessions. No Qt.

Roles and the password/session policy are engineering data, saved with the project in
``security.json`` and versioned. Accounts belong to each installation: they live in
``<project>/runtime/users.json`` (never versioned, never copied with the project) and
store only scrypt hashes. With ``enabled`` false (the default) everything is allowed, as
before; enabling it makes the runtime start logged out, read-only.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

PERMISSIONS = {
    "operate": "Mandos y consignas",
    "acknowledge": "Reconocer alarmas",
    "manage_users": "Gestionar usuarios",
    "opcua": "Acceso por OPC UA",
}

DEFAULT_ROLES = [
    dict(id="viewer", name="Observador", permissions=[]),
    dict(id="operator", name="Operador", permissions=["operate", "acknowledge"]),
    dict(id="supervisor", name="Supervisor", permissions=["operate", "acknowledge", "manage_users"]),
]


def default_security():
    return dict(enabled=False, session_timeout_minutes=15, password_min_length=10,
                max_failed_logins=5, lockout_minutes=5, roles=copy.deepcopy(DEFAULT_ROLES))


_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# scrypt cost: ~50 ms on a small ARM computer, negligible for an interactive login.
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def _integer(config, key, low, high):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"Seguridad: {key} debe ser un entero entre {low} y {high}")


def validate_security(security):
    if not isinstance(security, dict) or set(security) - set(default_security()):
        raise ValueError("Configuración de seguridad inválida")
    if not isinstance(security.get("enabled"), bool):
        raise ValueError("Seguridad: enabled debe ser booleano")
    _integer(security, "session_timeout_minutes", 0, 24 * 60)
    _integer(security, "password_min_length", 8, 128)
    _integer(security, "max_failed_logins", 1, 100)
    _integer(security, "lockout_minutes", 1, 24 * 60)
    roles = security.get("roles")
    if not isinstance(roles, list) or not roles:
        raise ValueError("Seguridad: define al menos un rol")
    ids = set()
    for role in roles:
        if not isinstance(role, dict) or set(role) != {"id", "name", "permissions"}:
            raise ValueError("Seguridad: rol inválido")
        if not isinstance(role["id"], str) or not _NAME.match(role["id"]) or role["id"] in ids:
            raise ValueError(f"Seguridad: identificador de rol inválido o repetido: {role.get('id')}")
        ids.add(role["id"])
        if not isinstance(role["name"], str) or not role["name"].strip():
            raise ValueError("Seguridad: el rol necesita un nombre")
        if not isinstance(role["permissions"], list) or set(role["permissions"]) - set(PERMISSIONS):
            raise ValueError(f"Seguridad: permiso desconocido en el rol {role['id']}")


def validate_element_permission(element):
    if "permission" in element and element["permission"] not in PERMISSIONS:
        raise ValueError(f"Permiso desconocido: {element['permission']}")


def required_permission(element):
    """Permission an operator needs to use a control; None for navigation."""
    if "permission" in element:
        return element["permission"]
    action = element.get("action", "toggle" if element.get("kind") == "button" else None)
    if element.get("kind") == "input" or action in {"toggle", "set", "momentary", "press_release", "script"}:
        return "operate"
    return None


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
class AuthenticationError(PermissionError):
    """Same message for unknown user and wrong password: do not reveal which accounts exist."""


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return dict(algorithm="scrypt", **{k: v for k, v in _SCRYPT.items()},
                salt=base64.b64encode(salt).decode("ascii"), hash=base64.b64encode(digest).decode("ascii"))


def verify_password(password, record):
    if not record or record.get("algorithm") != "scrypt":
        return False
    params = {k: record[k] for k in ("n", "r", "p", "dklen")}
    digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(record["salt"]), **params)
    return hmac.compare_digest(digest, base64.b64decode(record["hash"]))


def check_password_policy(name, password, policy):
    if not isinstance(password, str) or len(password) < policy["password_min_length"]:
        raise ValueError(f"La contraseña necesita al menos {policy['password_min_length']} caracteres")
    if password.strip().lower() == name.lower():
        raise ValueError("La contraseña no puede ser el nombre de usuario")
    if len(set(password)) < 4:
        raise ValueError("La contraseña es demasiado simple")


def users_path(project_root):
    return Path(project_root) / "runtime" / "users.json"


class UserStore:
    """Accounts of one installation. Every change is written atomically."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return dict(version=1, users=[])
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("users"), list):
            raise ValueError("Archivo de usuarios con formato desconocido")
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".users-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def users(self):
        return self.load()["users"]

    def find(self, name, data=None):
        data = data or self.load()
        return next((u for u in data["users"] if u["name"].lower() == name.lower()), None)

    def _update(self, name, change):
        data = self.load()
        user = self.find(name, data)
        if user is None:
            raise KeyError(f"Usuario inexistente: {name}")
        change(user)
        self.save(data)
        return user

    def create(self, name, password, roles, policy, full_name="", must_change=True):
        if not _NAME.match(name or ""):
            raise ValueError("Nombre de usuario inválido: letras, números, punto, guion y guion bajo")
        check_password_policy(name, password, policy)
        self._check_roles(roles, policy)
        data = self.load()
        if self.find(name, data):
            raise ValueError(f"El usuario ya existe: {name}")
        now = time.time()
        data["users"].append(dict(name=name, full_name=full_name, roles=list(roles), password=hash_password(password),
                                  must_change=must_change, disabled=False, failed=0, locked_until=0,
                                  created=now, password_changed=now))
        self.save(data)

    def set_password(self, name, password, policy, must_change=False):
        check_password_policy(name, password, policy)

        def change(user):
            user.update(password=hash_password(password), must_change=must_change, failed=0, locked_until=0,
                        password_changed=time.time())
        self._update(name, change)

    def set_roles(self, name, roles, policy):
        self._check_roles(roles, policy)
        self._update(name, lambda user: user.update(roles=list(roles)))

    def set_disabled(self, name, disabled):
        self._update(name, lambda user: user.update(disabled=bool(disabled), failed=0, locked_until=0))

    def set_full_name(self, name, full_name):
        self._update(name, lambda user: user.update(full_name=str(full_name)))

    def delete(self, name):
        data = self.load()
        user = self.find(name, data)
        if user is None:
            raise KeyError(f"Usuario inexistente: {name}")
        data["users"].remove(user)
        self.save(data)

    @staticmethod
    def _check_roles(roles, policy):
        known = {r["id"] for r in policy["roles"]}
        if not isinstance(roles, (list, tuple)) or not roles or set(roles) - known:
            raise ValueError("Asigna al menos un rol existente")

    def authenticate(self, name, password, policy, now=None):
        now = time.time() if now is None else now
        data = self.load()
        user = self.find(name or "", data)
        if user is None:
            # Spend the same time as a real check so response time does not reveal accounts.
            verify_password(password or "", _DUMMY)
            raise AuthenticationError("Usuario o contraseña incorrectos")
        if user.get("disabled"):
            raise AuthenticationError("Usuario desactivado")
        if user.get("locked_until", 0) > now:
            minutes = int((user["locked_until"] - now) // 60) + 1
            raise AuthenticationError(f"Usuario bloqueado por intentos fallidos; espera {minutes} min")
        if not verify_password(password or "", user["password"]):
            user["failed"] = user.get("failed", 0) + 1
            if user["failed"] >= policy["max_failed_logins"]:
                user["locked_until"] = now + policy["lockout_minutes"] * 60
                user["failed"] = 0
            self.save(data)
            raise AuthenticationError("Usuario o contraseña incorrectos")
        if user.get("failed") or user.get("locked_until"):
            user.update(failed=0, locked_until=0)
            self.save(data)
        return dict(user)


_DUMMY = hash_password(secrets.token_hex(8))


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@dataclass
class Session:
    user: str
    full_name: str
    roles: tuple
    permissions: frozenset
    must_change: bool = False
    started: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)

    @property
    def display(self):
        return self.full_name or self.user


class SecurityService:
    """Policy + accounts of a project. Thread-safe enough for the GUI and the OPC UA server:
    every authentication re-reads the account file, so changes made in Studio apply at once."""

    def __init__(self, project):
        self.policy = project.security
        self.store = UserStore(users_path(project.root))

    @property
    def enabled(self):
        return self.policy.get("enabled", False)

    def permissions_of(self, roles):
        granted = set()
        for role in self.policy["roles"]:
            if role["id"] in roles:
                granted.update(role["permissions"])
        return frozenset(granted)

    def login(self, name, password):
        user = self.store.authenticate(name, password, self.policy)
        return Session(user["name"], user.get("full_name", ""), tuple(user["roles"]),
                       self.permissions_of(user["roles"]), user.get("must_change", False))

    def expired(self, session, now=None):
        timeout = self.policy.get("session_timeout_minutes", 0)
        if not timeout or session is None:
            return False
        return (time.monotonic() if now is None else now) - session.last_activity > timeout * 60

    def permits(self, session, permission):
        if not self.enabled or permission is None:
            return True
        return session is not None and not session.must_change and not self.expired(session) \
            and permission in session.permissions

    @staticmethod
    def touch(session):
        if session is not None:
            session.last_activity = time.monotonic()

    def actor(self, session):
        return session.user if session is not None else ""
