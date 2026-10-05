"""Portable project identifiers shared by model and authoring dialogs."""
import re


def filename(name):
    reserved = {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
    if (not isinstance(name,str) or not name.strip() or name in {'.','..'} or
        re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith((' ','.')) or
        name.split('.')[0].upper() in reserved):
        raise ValueError('Nombre de archivo inválido o reservado')


def filenames(names):
    seen=set()
    for name in names:
        filename(name)
        if name.casefold() in seen:
            raise ValueError('Nombres de archivo duplicados (mayúsculas/minúsculas)')
        seen.add(name.casefold())
