"""Connection secrets (passwords of PLCs and OPC UA servers) outside the project. No Qt.

Projects never contain secrets: a connection only names a user, and its password is kept
per installation in ``<project>/runtime/secrets.json``. On Windows each value is encrypted
with DPAPI for the current Windows account, so a copied file is useless on another PC or
account. Elsewhere the file is restricted to its owner (0600) and the values are stored
base64-encoded: protect the account and the disk instead.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

_ENTROPY = b"abSCADA connection secret v1"


def secrets_path(project_root):
    return Path(project_root) / "runtime" / "secrets.json"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data):
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _crypt(function, data):
        source, keep = _blob(data)
        entropy, keep_entropy = _blob(_ENTROPY)
        target = _Blob()
        # CRYPTPROTECT_UI_FORBIDDEN: never show a prompt from a service or the runtime.
        if not function(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(target)):
            raise OSError(ctypes.FormatError())
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(target.pbData)

    def protect(data: bytes) -> str:
        return "dpapi:" + base64.b64encode(_crypt(ctypes.windll.crypt32.CryptProtectData, data)).decode("ascii")

    def unprotect(text: str) -> bytes:
        if not text.startswith("dpapi:"):
            raise ValueError("Secreto guardado en otro sistema: vuelve a introducirlo")
        # Same argument order as CryptProtectData; the description out-parameter is not needed.
        return _crypt(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(text[6:]))
else:
    def protect(data: bytes) -> str:
        return "plain:" + base64.b64encode(data).decode("ascii")

    def unprotect(text: str) -> bytes:
        if not text.startswith("plain:"):
            raise ValueError("Secreto guardado en otro sistema: vuelve a introducirlo")
        return base64.b64decode(text[6:])


class SecretStore:
    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".secrets-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get(self, key):
        value = self._load().get(key)
        return unprotect(value).decode("utf-8") if value else None

    def set(self, key, secret):
        data = self._load()
        if secret:
            data[key] = protect(secret.encode("utf-8"))
        else:
            data.pop(key, None)
        self._save(data)

    def has(self, key):
        return key in self._load()


def connection_secret_key(connection_id):
    return f"connection:{connection_id}:password"
