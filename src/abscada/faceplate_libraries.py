"""Version-pinned, self-contained faceplate libraries, independent of Qt.

Packages are JSON, including base64 image resources. Linking never executes code
and never follows the source on load. Updating is an explicit validated operation.
"""
import base64
import copy
import hashlib
import json
import re
import tempfile
from pathlib import Path, PurePosixPath
from .validation import filenames
from .i18n import tr

_cache = None


def digest(package):
    return hashlib.sha256(json.dumps(package, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}', value):
        raise ValueError(tr('El alias admite letras, números, _ y -; comienza con una letra (máximo 40)'))


def resource_name(name):
    if not isinstance(name, str) or '\\' in name or ':' in name or any(p in ('', '.', '..') for p in name.split('/')) or PurePosixPath(name).is_absolute():
        raise ValueError(tr('Ruta de recurso de biblioteca inválida'))
    for part in name.split('/'):
        filenames([part])


def transform(value, assets, palette=None, alias=None):
    if isinstance(value, list):
        return [transform(v, assets, palette, alias) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == 'source' and isinstance(item, str) and item:
            result[key] = assets(item) if callable(assets) else f'library://{alias}/{item}'
        elif palette is not None and (key.endswith('color') or key in ('background', 'on', 'off', 'bad')) and isinstance(item, str) and item.startswith('@'):
            if item[1:] not in palette:
                raise ValueError(tr('Color de paleta inexistente: ') + item)
            result[key] = palette[item[1:]]
        else:
            result[key] = transform(item, assets, palette, alias)
    return result


def validate_package(package):
    if not isinstance(package, dict) or package.get('schema_version') != 1:
        raise ValueError(tr('Versión de biblioteca no soportada'))
    for key in ('name', 'version'):
        if not isinstance(package.get(key), str) or not package[key].strip():
            raise ValueError(tr('La biblioteca necesita nombre y versión'))
    faces, assets = package.get('faceplates'), package.get('assets')
    if not isinstance(faces, dict) or not faces or not isinstance(assets, dict):
        raise ValueError(tr('La librería necesita objetos y recursos válidos'))
    filenames(faces)
    for name, encoded in assets.items():
        resource_name(name)
        try:
            base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(tr('Recurso base64 inválido: ') + name) from exc
    # A library cannot depend on variables, scripts, views or screens in a consumer.
    from .project import Project
    project = Project(Path.cwd(), dict(name='Library validation', startup_screen='main'), {}, [], [],
                      {'main':dict(width=800,height=600,elements=[])}, copy.deepcopy(faces))
    def asset(name):
        from .system_library import SYSTEM, asset as system_asset
        if name.startswith(f'library://{SYSTEM}/'):
            return system_asset(name.removeprefix(f'library://{SYSTEM}/'))
        resource_name(name)
        if name not in assets:
            raise ValueError(tr('Falta el recurso de biblioteca: ') + name)
        return Path(name)
    project.asset = asset
    project.validate()


def export_library(project, names, target, name, version, author='', license=''):
    """Publish a new immutable package. Existing files are never overwritten."""
    if not names or any(n not in project.faceplates for n in names):
        raise ValueError(tr('Selecciona al menos un objeto de librería existente'))
    assets = {}
    def capture(source):
        raw = project.asset(source).read_bytes()
        key = 'assets/' + hashlib.sha256(raw).hexdigest() + Path(source).suffix.lower()
        assets[key] = base64.b64encode(raw).decode('ascii')
        return key
    package = dict(schema_version=1, name=name, version=version, author=author, license=license,
                   faceplates={n:transform(project.faceplates[n], capture, project.manifest.get('palette', {})) for n in names}, assets=assets)
    validate_package(package)
    target = Path(target)
    # Exclusive creation keeps published versions immutable, including from other processes.
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(package, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return package


def expected_faces(alias, package):
    return {alias + '__' + name: transform(doc, package['assets'], alias=alias) for name, doc in package['faceplates'].items()}


def owner(project, template):
    """Library a template comes from (linked package or the standard library); None if local."""
    from .system_library import SYSTEM, is_system
    if is_system(template):
        return SYSTEM
    return next((alias for alias, entry in project.libraries.items()
                 if template.startswith(alias+'__') and template[len(alias)+2:] in entry['package']['faceplates']), None)


def hydrate(project):
    from .system_library import inject
    inject(project)
    if not isinstance(project.libraries, dict):
        raise ValueError(tr('Las bibliotecas deben ser un objeto'))
    for alias, entry in project.libraries.items():
        identifier(alias)
        if not isinstance(entry,dict) or not isinstance(entry.get('package'),dict) or not isinstance(entry.get('source'),str):
            raise ValueError(tr('Vínculo de biblioteca inválido: ') + alias)
        package = entry['package']
        validate_package(package)
        if digest(package) != entry.get('sha256'):
            raise ValueError(tr("{alias}: la huella de la biblioteca no coincide", alias=alias))
        for name, document in expected_faces(alias, package).items():
            if name in project.faceplates:
                raise ValueError(tr('Colisión con un objeto de librería local: ') + name)
            project.faceplates[name] = document


def validate_links(project):
    from .system_library import SYSTEM, check, inject
    # Projects built in code (not loaded from disk) also see the standard library.
    inject(project)
    check(project)
    if not isinstance(project.libraries, dict):
        raise ValueError(tr('Las bibliotecas deben ser un objeto'))
    if SYSTEM in project.libraries:
        raise ValueError(tr("El alias «{SYSTEM}» está reservado a la librería estándar", SYSTEM=SYSTEM))
    filenames(project.libraries)
    for alias, entry in project.libraries.items():
        identifier(alias)
        if not isinstance(entry,dict) or not isinstance(entry.get('package'),dict) or not isinstance(entry.get('source'),str):
            raise ValueError(tr('Vínculo de biblioteca inválido: ') + alias)
        package = entry['package']
        if digest(package) != entry.get('sha256'):
            raise ValueError(tr("{alias}: biblioteca modificada; utiliza Actualizar", alias=alias))
        for name, document in expected_faces(alias, package).items():
            if project.faceplates.get(name) != document:
                raise ValueError(tr("{name}: plantilla vinculada de solo lectura", name=name))


def link(project, source, alias, update=False):
    identifier(alias)
    source = Path(source).resolve()
    package = json.loads(source.read_text(encoding='utf-8'))
    validate_package(package)
    candidate = copy.deepcopy(project)
    existing = candidate.libraries.get(alias)
    if bool(existing) != bool(update):
        raise ValueError(tr('El alias ya existe') if existing else tr('Biblioteca no vinculada'))
    if existing:
        if package['name'] != existing['package']['name']:
            raise ValueError(tr('La actualización pertenece a otra biblioteca'))
        if package['version'] == existing['package']['version'] and digest(package) != existing['sha256']:
            raise ValueError(tr('Una versión publicada es inmutable; publica una versión nueva'))
        for name in expected_faces(alias, existing['package']):
            candidate.faceplates.pop(name, None)
    candidate.libraries[alias] = dict(source=str(source), sha256=digest(package), package=package)
    for name, doc in expected_faces(alias, package).items():
        if any(n.casefold() == name.casefold() for n in candidate.faceplates):
            raise ValueError(tr('Colisión de nombre de objeto de librería: ') + name)
        candidate.faceplates[name] = doc
    candidate.validate()  # Checks every existing instance against the new interface.
    project.libraries, project.faceplates = candidate.libraries, candidate.faceplates


def unlink(project, alias):
    names = set(expected_faces(alias, project.libraries[alias]['package']))
    used = [screen for screen, doc in project.screens.items() if any(e.get('template') in names for e in doc['elements'])]
    if used:
        raise ValueError(tr('Biblioteca en uso en: ') + ', '.join(used))
    del project.libraries[alias]
    for name in names:
        del project.faceplates[name]


def asset(project, uri):
    global _cache
    alias, separator, name = uri.removeprefix('library://').partition('/')
    from .system_library import SYSTEM, asset as system_asset
    if separator and alias == SYSTEM:
        return system_asset(name)
    if not separator or alias not in project.libraries:
        raise ValueError(tr('Biblioteca de recurso inexistente'))
    resource_name(name)
    encoded = project.libraries[alias]['package']['assets'].get(name)
    if encoded is None:
        raise ValueError(tr('Recurso de biblioteca inexistente: ') + name)
    raw = base64.b64decode(encoded, validate=True)
    if _cache is None:
        _cache = tempfile.TemporaryDirectory(prefix='abscada-library-assets-')
    target = Path(_cache.name) / (hashlib.sha256(raw).hexdigest() + Path(name).suffix)
    if not target.exists():
        target.write_bytes(raw)
    return target
