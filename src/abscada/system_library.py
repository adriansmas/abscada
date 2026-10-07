"""abSCADA's standard library (system library). No Qt.

Ships with the application in ``standard_library/`` (built by tools/build_standard_library.py):
SVG symbols in «Gráficos» and animated objects in «Objetos». It is read-only and is never
saved into projects: every project sees its objects as ``estandar__<name>`` templates, and a
screen only stores which one it uses. Resources are addressed as ``library://estandar/<path>``.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from .i18n import tr

SYSTEM = "estandar"
PREFIX = SYSTEM + "__"
FOLDER = Path(__file__).with_name("standard_library")


@lru_cache(maxsize=1)
def package():
    return json.loads((FOLDER / "library.json").read_text(encoding="utf-8"))


def _with_uris(value):
    if isinstance(value, list):
        return [_with_uris(item) for item in value]
    if isinstance(value, dict):
        return {key: (f"library://{SYSTEM}/{item}" if key == "source" and isinstance(item, str) and item else _with_uris(item))
                for key, item in value.items()}
    return value


@lru_cache(maxsize=1)
def _templates():
    return {PREFIX + name: _with_uris(document) for name, document in package()["faceplates"].items()}


def templates():
    return copy.deepcopy(_templates())


def is_system(name):
    return isinstance(name, str) and name in _templates()


def inject(project):
    """Make the standard objects available to a project (in memory only)."""
    for name, document in _templates().items():
        if name not in project.faceplates:
            project.faceplates[name] = project_template(project, document)
        else:
            from .project_languages import localized
            # A legacy, unmodified system object can acquire inline translations
            # when its project first declares languages.
            if project.faceplates[name] == localized(document, 'es', 'es'):
                project.faceplates[name] = project_template(project, document)


def project_template(project, document):
    from .project_languages import languages, default_language, TEXT_KEYS, resolve
    result = copy.deepcopy(document)
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in TEXT_KEYS and isinstance(child, dict):
                    if 'languages' not in project.manifest:
                        value[key] = resolve(child, 'es', 'es')
                    else:
                        value[key] = {code: child[code] for code in languages(project) if code in child}
                        default = default_language(project)
                        if default not in value[key]:
                            value[key][default] = resolve(child, default, 'es')
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(result)
    return result


def check(project):
    """System objects are read-only, and their prefix is reserved."""
    for name, document in project.faceplates.items():
        if name.startswith(PREFIX):
            if name not in _templates():
                raise ValueError(tr("El prefijo «{PREFIX}» está reservado a la librería estándar: {name}", PREFIX=PREFIX, name=name))
            if document != project_template(project, _templates()[name]):
                raise ValueError(tr("{name}: objeto de la librería estándar, de solo lectura", name=name))


def asset(relative):
    from .faceplate_libraries import resource_name
    resource_name(relative)
    path = (FOLDER / relative).resolve()
    if not path.is_relative_to(FOLDER.resolve()) or not path.is_file():
        raise ValueError(tr("Recurso inexistente en la librería estándar: ") + relative)
    return path


def title(name):
    from .project_languages import resolve
    from .i18n import language
    return resolve(_templates()[name].get("title", name.removeprefix(PREFIX)), language(), 'es')
