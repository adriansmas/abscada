"""Version-pinned, self-contained faceplate libraries, independent of Qt.

Packages are JSON, including base64 image resources. Linking never executes code
and never follows the source on load. Updating is an explicit validated operation.

Schema 1 carries objects and resources. Schema 2 adds the data types their
parameters use (``types``), linked read-only as ``<alias>__<Type>`` like objects.
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
SCHEMAS = (1, 2)


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


def transform(value, assets, alias=None, names=None):
    """Resources become package paths (export) or ``library://`` URIs (link).

    When linking, ``names`` lists the package's own objects and types: references
    to them get the alias prefix (nested objects, pop-ups, parameter types).
    """
    if isinstance(value, list):
        return [transform(v, assets, alias, names) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == 'source' and isinstance(item, str) and item:
            result[key] = assets(item) if callable(assets) else f'library://{alias}/{item}'
        elif key == 'template' and names and isinstance(item, str) and item in names['faceplates']:
            result[key] = alias + '__' + item
        elif key == 'parameters' and names and isinstance(item, dict):
            result[key] = {name: prefixed_kind(kind, alias, names['types']) for name, kind in item.items()}
        else:
            result[key] = transform(item, assets, alias, names)
    return result


def prefixed_kind(kind, alias, types):
    """``Motor[4]`` of a package linked as ``vendor`` → ``vendor__Motor[4]``; primitives unchanged."""
    from .structures import split_kind
    base, length = split_kind(kind)
    if length is not None:
        return prefixed_kind(base, alias, types) + kind[len(base):]
    return alias + '__' + kind if isinstance(kind, str) and kind in types else kind


def package_names(package):
    return dict(faceplates=set(package['faceplates']), types=set(package.get('types', {})))


def validate_package(package):
    if not isinstance(package, dict) or package.get('schema_version') not in SCHEMAS:
        raise ValueError(tr('Versión de biblioteca no soportada'))
    types = package.get('types', {})
    if not isinstance(types, dict) or (types and package['schema_version'] < 2):
        raise ValueError(tr('Los tipos de datos de una librería requieren el formato 2'))
    from .structures import check_definitions
    check_definitions(types)
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
    project = Project(Path.cwd(), dict(name='Library validation', startup_screen='main',
                      languages=package.get('languages', ['es']), default_language=package.get('default_language', 'es')), copy.deepcopy(types), [], [],
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
    names, types = dependencies(project, names)
    assets = {}
    def capture(source):
        raw = project.asset(source).read_bytes()
        key = 'assets/' + hashlib.sha256(raw).hexdigest() + Path(source).suffix.lower()
        assets[key] = base64.b64encode(raw).decode('ascii')
        return key
    from .project_languages import languages, default_language
    package = dict(schema_version=2 if types else 1, name=name, version=version, author=author, license=license,
                   languages=languages(project), default_language=default_language(project),
                   faceplates={n:transform(project.faceplates[n], capture) for n in names}, assets=assets)
    if types:
        package['types'] = {t: copy.deepcopy(project.types[t]) for t in types}
    validate_package(package)
    target = Path(target)
    # Exclusive creation keeps published versions immutable, including from other processes.
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(package, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return package


def dependencies(project, names):
    """Objects to publish with the chosen ones (nested objects, pop-ups) and the types they use."""
    from .button_actions import with_steps, popup_targets
    from .structures import structure_of
    from .system_library import is_system
    chosen, pending = [], list(names)
    while pending:
        name = pending.pop(0)
        if name in chosen:
            continue
        chosen.append(name)
        for element in project.faceplates[name]['elements']:
            for target in popup_targets(element):
                template = target.get('template')
                if template and template in project.faceplates and not is_system(template) and template not in chosen:
                    pending.append(template)
    types, pending = [], [kind for name in chosen for kind in project.faceplates[name].get('parameters', {}).values()]
    while pending:
        kind = structure_of(pending.pop(0))
        if kind in project.types and kind not in types:
            types.append(kind)
            pending.extend(project.types[kind].values())
    return chosen, types


def expected_faces(alias, package):
    names = package_names(package)
    return {alias + '__' + name: transform(doc, package['assets'], alias=alias, names=names) for name, doc in package['faceplates'].items()}


def expected_types(alias, package):
    names = package.get('types', {})
    return {alias + '__' + name: {field: prefixed_kind(kind, alias, names) for field, kind in fields.items()}
            for name, fields in names.items()}


def type_owner(project, name):
    """Library a data type comes from; None if it belongs to the project."""
    return next((alias for alias, entry in project.libraries.items()
                 if name.startswith(alias+'__') and name[len(alias)+2:] in entry['package'].get('types', {})), None)


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
        for name, fields in expected_types(alias, package).items():
            if name in project.types:
                raise ValueError(tr('Colisión con un tipo de datos local: ') + name)
            project.types[name] = fields


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
        for name, fields in expected_types(alias, package).items():
            if project.types.get(name) != fields:
                raise ValueError(tr("{name}: tipo de datos vinculado de solo lectura", name=name))


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
        for name in expected_types(alias, existing['package']):
            candidate.types.pop(name, None)
    candidate.libraries[alias] = dict(source=str(source), sha256=digest(package), package=package)
    for name, doc in expected_faces(alias, package).items():
        if any(n.casefold() == name.casefold() for n in candidate.faceplates):
            raise ValueError(tr('Colisión de nombre de objeto de librería: ') + name)
        candidate.faceplates[name] = doc
    for name, fields in expected_types(alias, package).items():
        if name in candidate.types:
            raise ValueError(tr('Colisión de nombre de tipo de datos: ') + name)
        candidate.types[name] = fields
    candidate.validate()  # Checks every existing instance and variable against the new interface.
    project.libraries, project.faceplates, project.types = candidate.libraries, candidate.faceplates, candidate.types


def unlink(project, alias):
    names = set(expected_faces(alias, project.libraries[alias]['package']))
    from .button_actions import with_steps, popup_targets
    used = [screen for screen, doc in project.screens.items()
            if any(t.get('template') in names for e in doc['elements'] for t in popup_targets(e))]
    used += [name for name, doc in project.faceplates.items() if name not in names
             and any(t.get('template') in names for e in doc['elements'] for t in popup_targets(e))]
    from .structures import structure_of
    types = set(expected_types(alias, project.libraries[alias]['package']))
    used += [v['name'] for v in project.variables if structure_of(v['type']) in types]
    used += [name for name, fields in project.types.items() if name not in types
             and any(structure_of(kind) in types for kind in fields.values())]
    used += [name for name, doc in project.faceplates.items() if name not in names
             and any(structure_of(kind) in types for kind in doc.get('parameters', {}).values())]
    if used:
        raise ValueError(tr('Biblioteca en uso en: ') + ', '.join(used))
    del project.libraries[alias]
    for name in names:
        del project.faceplates[name]
    for name in types:
        del project.types[name]


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
