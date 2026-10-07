"""Connection secrets (passwords of PLCs and OPC UA servers), saved with the project. No Qt.

A connection names a user; its password lives in ``<project>/secrets.json`` so the project
works on any PC it is copied to. The runtime has to send the password itself to the PLC,
so it is stored recoverable: base64-encoded, never encrypted. That keeps it out of plain
sight in a diff, nothing more: whoever can read the project can read its passwords, so
protect the project folder and its repository as the credentials they contain.

Like the accounts, the file is written at once from Studio's connection form, not by the
project's bulk save. Version 0.5.0b2 kept the secrets per PC in ``runtime/secrets.json``,
encrypted with Windows DPAPI; they move into the project the first time they are read on
the PC and Windows account that wrote them.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

SECRETS_FILE = "secrets.json"
_ENTROPY = b"abSCADA connection secret v1"


def secrets_path(project_root):
    return Path(project_root) / SECRETS_FILE


def legacy_secrets_path(project_root):
    return Path(project_root) / "runtime" / SECRETS_FILE


def protect(data: bytes) -> str:
    return "plain:" + base64.b64encode(data).decode("ascii")


def unprotect(text: str) -> bytes:
    if text.startswith("plain:"):
        return base64.b64decode(text[6:])
    if text.startswith("dpapi:"):
        return _dpapi_unprotect(base64.b64decode(text[6:]))
    raise ValueError("Secreto con formato desconocido: vuelve a introducirlo")


def _dpapi_unprotect(data: bytes) -> bytes:
    """Read a 0.5.0b2 secret. Only works for the same Windows account on the same PC."""
    if sys.platform != "win32":
        raise ValueError("Secreto cifrado en otro equipo con Windows: vuelve a introducirlo")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(value):
        buffer = ctypes.create_string_buffer(value, len(value))
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    source, keep = blob(data)
    entropy, keep_entropy = blob(_ENTROPY)
    target = Blob()
    # CRYPTPROTECT_UI_FORBIDDEN: never show a prompt from a service or the runtime.
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None,
                                                    0x1, ctypes.byref(target)):
        raise ValueError("Secreto cifrado por otra cuenta de Windows: vuelve a introducirlo")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".secrets-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class SecretStore:
    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            self._migrate()
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _migrate(self):
        legacy = legacy_secrets_path(self.path.parent)
        if self.path.name != SECRETS_FILE or not legacy.exists():
            return
        moved, kept = {}, {}
        for key, value in json.loads(legacy.read_text(encoding="utf-8")).items():
            try:
                moved[key] = protect(unprotect(value))
            except (ValueError, OSError):
                kept[key] = value  # another PC or account: leave it for the user to re-enter
        if moved:
            _write(self.path, moved)
        if kept:
            _write(legacy, kept)
        else:
            legacy.unlink()

    def get(self, key):
        value = self._load().get(key)
        return unprotect(value).decode("utf-8") if value else None

    def set(self, key, secret):
        data = self._load()
        if secret:
            data[key] = protect(secret.encode("utf-8"))
        else:
            data.pop(key, None)
        _write(self.path, data)

    def has(self, key):
        return key in self._load()


def connection_secret_key(connection_id):
    return f"connection:{connection_id}:password"
