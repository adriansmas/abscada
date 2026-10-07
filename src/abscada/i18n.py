"""Language of the application (Studio, Runtime chrome and messages). No Qt.

The source language is Spanish: every user-facing text is written in Spanish and wrapped
in ``tr()``. Other languages are JSON catalogs in ``locales/<code>.json`` that map the
Spanish text to its translation; a text missing from a catalog is shown in Spanish.

    tr("Guardar")                                   -> "Save" in English
    tr("Contraseña para {connection}", connection=c) -> placeholders, as str.format

The language is a per-user application setting (``settings.json`` in the abSCADA state
folder), chosen in Studio under Ayuda → Idioma and applied on the next start, so module
constants translated at import time stay consistent. ``ABSCADA_LANG`` overrides it.
It has nothing to do with the language of a project's own texts.
"""
from __future__ import annotations

import json
import os
from contextvars import ContextVar
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

SOURCE = "es"
LANGUAGES = {"es": "Español", "en": "English"}
LOCALES = Path(__file__).with_name("locales")

_language: str | None = None
_catalog: dict[str, str] = {}
_scoped_language = ContextVar('abscada_language', default=None)


@contextmanager
def using_language(code):
    """Translate a runtime callback independently of Studio's process language."""
    token = _scoped_language.set(code)
    try:
        yield
    finally:
        _scoped_language.reset(token)


@lru_cache(maxsize=32)
def scoped_catalog(code):
    return load_catalog(code)


def settings_path() -> Path:
    from .app_paths import state_root
    return state_root() / "settings.json"


def _read_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def configured_language() -> str:
    """The language saved in the settings (what the next start will use)."""
    code = _read_settings().get("language", SOURCE)
    return code if code in LANGUAGES else SOURCE


def save_language(code: str) -> None:
    if code not in LANGUAGES:
        raise ValueError(tr("Idioma desconocido: {code}", code=code))
    data = _read_settings()
    data["language"] = code
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_catalog(code: str) -> dict[str, str]:
    if code == SOURCE:
        return {}
    path = LOCALES / f"{code}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_language(code: str) -> None:
    """Switch the active language for this process (tests, or the startup sequence)."""
    global _language, _catalog
    _language = code if code in LANGUAGES else SOURCE
    _catalog = load_catalog(_language)


def language() -> str:
    if _language is None:
        set_language(os.environ.get("ABSCADA_LANG") or configured_language())
    return _language


def tr(source: str, /, **values) -> str:
    """Translate a Spanish source text; keyword arguments fill its {placeholders}."""
    language()
    code = _scoped_language.get()
    catalog = scoped_catalog(code) if code else _catalog
    translated = catalog.get(source) or source
    if values:
        try:
            return translated.format(**values)
        except (KeyError, IndexError, ValueError):
            return source.format(**values)  # a broken translation never hides the message
    return translated


def N_(source: str) -> str:
    """Mark a text for the catalogs without translating it now (gettext convention)."""
    return source


def tr_existing(text: str) -> str:
    """Retranslate a caption which may have been created at import in Studio."""
    language()
    source = next((key for key, value in _catalog.items() if value == text), text)
    return tr(source)
