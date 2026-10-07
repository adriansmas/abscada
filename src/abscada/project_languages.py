"""Project text translations. Identifiers, bindings and process values stay untouched."""
from __future__ import annotations

import copy
import csv
import io
import re
from dataclasses import dataclass

TEXT_KEYS = {'text', 'title', 'message', 'default_text', 'disabled_reason', 'tooltip', 'description'}


def languages(project):
    return project.manifest.get('languages', ['es'])


def default_language(project):
    return project.manifest.get('default_language', languages(project)[0])


def is_text(value):
    return isinstance(value, str) or (isinstance(value, dict) and bool(value)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()))


def resolve(value, language, default='es'):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get(language) or value.get(default) or ''
    return ''


def edited(value, text, language, default='es'):
    if isinstance(value, str) and language == default:
        return text
    result = dict(value) if isinstance(value, dict) else {default: value}
    result[language] = text
    return result


def localized(document, language, default='es', *, category=False):
    if isinstance(document, list):
        return [localized(v, language, default, category=category) for v in document]
    if not isinstance(document, dict):
        return document
    return {k: resolve(v, language, default) if k in TEXT_KEYS or (category and k == 'name')
            else localized(v, language, default) for k, v in document.items()}


@dataclass
class TextEntry:
    path: str
    owner: dict
    key: str

    @property
    def value(self):
        return self.owner[self.key]


def entries(project):
    def walk(value, path, category=False):
        if isinstance(value, dict):
            for key, child in value.items():
                pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
                if key in TEXT_KEYS or (category and key == 'name'):
                    yield TextEntry(pointer, value, key)
                else:
                    yield from walk(child, pointer, category=key == 'categories')
        elif isinstance(value, list):
            for index, child in enumerate(value):
                identity = str(index)
                if isinstance(child, dict):
                    if isinstance(child.get('id'), str):
                        identity = '@' + child['id']
                    elif 'text' in child and isinstance(child.get('value'), str):
                        identity = '=' + child['value']
                identity = identity.replace('~', '~0').replace('/', '~1')
                yield from walk(child, path + '/' + identity, category)
    for key in ('screens', 'faceplates', 'alarms', 'trends', 'alarm_views'):
        yield from walk(getattr(project, key), key)


def validate(project):
    codes = languages(project)
    if (not isinstance(codes, list) or not codes
            or any(not isinstance(c, str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', c) for c in codes)
            or len(codes) != len(set(codes))):
        raise ValueError('Idiomas de proyecto inválidos')
    default = default_language(project)
    if default not in codes:
        raise ValueError('El idioma por defecto debe pertenecer a los idiomas del proyecto')
    if project.manifest.get('initial_language', 'project') not in {'project', 'station', 'user'}:
        raise ValueError('Origen del idioma inicial inválido')
    for entry in entries(project):
        value = entry.value
        if not is_text(value):
            raise ValueError(f'{entry.path}: texto o traducciones inválidos')
        if isinstance(value, dict) and (set(value) - set(codes) or default not in value):
            raise ValueError(f'{entry.path}: traducciones sin idioma por defecto o con idioma no declarado')


def missing(project):
    for entry in entries(project):
        value = entry.value
        for code in languages(project):
            text = value.get(code, '') if isinstance(value, dict) else value if code == default_language(project) else ''
            if not text.strip() and resolve(value, default_language(project)).strip():
                yield f'{entry.path}: falta traducción {code}'


def resolved_project(project, language):
    result = copy.deepcopy(project)
    default = default_language(project)
    for key in ('screens', 'faceplates', 'trends', 'alarm_views'):
        setattr(result, key, localized(getattr(project, key), language, default))
    result.alarms = localized(project.alarms, language, default)
    result.alarms['categories'] = localized(project.alarms['categories'], language, default, category=True)
    return result


def export_csv(project):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['path', *languages(project)])
    for entry in entries(project):
        value = entry.value
        writer.writerow([entry.path, *[value.get(c, '') if isinstance(value, dict)
            else value if c == default_language(project) else '' for c in languages(project)]])
    return output.getvalue()


def import_csv(project, content):
    """Validate the whole import before changing anything; paths identify source fields."""
    reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')))
    if reader.fieldnames != ['path', *languages(project)]:
        raise ValueError('Las columnas deben ser path y los idiomas del proyecto')
    available = {e.path: e for e in entries(project)}
    updates, seen = [], set()
    for row in reader:
        path = row['path']
        if path not in available or path in seen or None in row or any(v is None for v in row.values()):
            raise ValueError(f'Fila de traducción inválida: {path}')
        seen.add(path)
        entry = available[path]
        if path.startswith('faceplates/'):
            from .faceplate_libraries import owner
            template = path.split('/')[1].replace('~1', '/').replace('~0', '~')
            if owner(project, template):
                expected = {c: entry.value.get(c, '') if isinstance(entry.value, dict)
                    else entry.value if c == default_language(project) else '' for c in languages(project)}
                if any(row[c] != expected[c] for c in languages(project)):
                    raise ValueError(f'{path}: librería de solo lectura; traduce la biblioteca en su proyecto de origen')
                continue
        updates.append((entry, {c: row[c] for c in languages(project)}))
    for entry, value in updates:
        entry.owner[entry.key] = value
