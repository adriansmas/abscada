"""Validate a library and reject unrecognized serialized graphic properties."""
import argparse
import json
from pathlib import Path
from abscada.faceplate_libraries import validate_package
from abscada.dynamics import KNOWN_PROPERTIES as PROPERTIES


def validate(package):
    validate_package(package)
    for name, document in package['faceplates'].items():
        for element in document['elements']:
            unknown = set(element) - PROPERTIES
            if unknown:
                raise ValueError(f'{name}/{element["id"]}: propiedades desconocidas: {", ".join(sorted(unknown))}')
            if element['kind'] == 'button':
                from abscada.project import coerce
                tag = element.get('tag', '')
                if tag.startswith('$'):
                    from abscada.structures import parameter_references
                    kind = parameter_references(document['parameters'], package.get('types', {}))[tag[1:]]
                    for key in ('value', 'press_value', 'release_value'):
                        if key in element:
                            coerce(element[key], kind)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    try:
        package = json.loads(args.package.read_text(encoding='utf-8'))
        validate(package)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Biblioteca inválida: {exc}\n')
    print(f'OK · {package["name"]} {package["version"]} · {len(package["faceplates"])} plantillas')
