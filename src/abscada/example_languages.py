"""Reproducible inline Spanish/English texts for all shipped demo projects."""
import json
from pathlib import Path
from abscada.project_languages import TEXT_KEYS, entries

CATALOG = Path(__file__).with_name('example_translations.json')


def translate_document(document, translations, category=False):
    if isinstance(document, dict):
        for key, value in document.items():
            if key in TEXT_KEYS or (category and key == 'name'):
                if isinstance(value, str):
                    document[key] = {'es': value}
                    if value in translations:
                        document[key]['en'] = translations[value]
                elif isinstance(value, dict) and value.get('es') in translations:
                    value['en'] = translations[value['es']]
            else:
                translate_document(value, translations, key == 'categories')
    elif isinstance(document, list):
        for value in document:
            translate_document(value, translations, category)


def bilingual(project):
    project.manifest.update(languages=['es', 'en'], default_language='es')
    translations = json.loads(CATALOG.read_text(encoding='utf-8'))
    for entry in entries(project):
        if isinstance(entry.value, str):
            source = entry.value
            entry.owner[entry.key] = {'es': source}
            if source in translations:
                entry.owner[entry.key]['en'] = translations[source]
    # Linked objects must match their embedded package exactly.
    for entry in project.libraries.values():
        entry['package'].update(languages=['es', 'en'], default_language='es')
        translate_document(entry['package'], translations)
        from abscada.faceplate_libraries import digest
        entry['sha256'] = digest(entry['package'])
    if project.manifest_file == 'la_tolva.abscada':
        language_buttons(project.screens['02_menu'])
    return project


def language_buttons(menu):
    for code, x in [('es', 12), ('en', 102)]:
        if not any(e['id'] == 'language_' + code for e in menu['elements']):
            menu['elements'].append(dict(id='language_' + code, kind='button', x=x, y=692, w=86, h=32,
                text={'es': code.upper(), 'en': code.upper()}, action='set_language', language=code,
                font_size=13, bold=True, color='#273b53', text_color='#ffffff', border_color='#387b91'))


def update_examples():
    root = Path(__file__).resolve().parents[2]
    translations = json.loads(CATALOG.read_text(encoding='utf-8'))
    for directory in sorted((root / 'examples').iterdir()):
        if not directory.is_dir():
            continue
        for manifest in directory.glob('*.abscada'):
            data = json.loads(manifest.read_text(encoding='utf-8'))
            data.update(languages=['es', 'en'], default_language='es')
            manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
        paths = list(directory.glob('screens/*.json')) + list(directory.glob('faceplates/*.json'))
        paths += [directory / f'{key}.json' for key in ('alarms', 'trends', 'alarm_views', 'libraries') if (directory / f'{key}.json').exists()]
        if directory.name == 'libraries':
            paths += list(directory.glob('*.json'))
        for path in paths:
            data = json.loads(path.read_text(encoding='utf-8'))
            translate_document(data, translations)
            if directory.name == 'brewery' and path.stem == '02_menu':
                language_buttons(data)
            if path.stem == 'libraries':
                from abscada.faceplate_libraries import digest
                for entry in data.values():
                    entry['package'].update(languages=['es', 'en'], default_language='es')
                    entry['sha256'] = digest(entry['package'])
            elif directory.name == 'libraries':
                data.update(languages=['es', 'en'], default_language='es')
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    update_examples()
