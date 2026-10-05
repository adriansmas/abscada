"""Prepare a complete project save, rollback replaced files on I/O failure."""
import json
import os
import tempfile
import hashlib
import uuid
from pathlib import Path


def documents(project):
    data = {'project.json': project.manifest}
    for key in ('types','variables','connections','alarms','historian','trends','alarm_views','automation'):
        data[key+'.json'] = getattr(project, key)
    if project.libraries:
        data['libraries.json'] = project.libraries
    from .faceplate_libraries import owner
    for folder in ('screens','faceplates'):
        for name, value in getattr(project, folder).items():
            if folder == 'faceplates' and owner(project, name):
                continue
            if Path(name).name != name or name in ('.','..') or '/' in name or '\\' in name:
                raise ValueError('Nombre de documento inválido')
            data[f'{folder}/{name}.json'] = value
    result = {name: (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8') for name,value in data.items()}
    result.update({f'scripts/{name}.py': source.encode('utf-8') for name,source in project.scripts.items()})
    return result


def disk_state(root):
    paths = list(root.glob('*.json'))
    for folder, pattern in (('screens','*.json'),('faceplates','*.json'),('scripts','*.py')):
        paths.extend((root/folder).glob(pattern))
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def remember_disk(project):
    project._disk_root = project.root.resolve()
    project._disk_state = disk_state(project._disk_root)


def save_project(project):
    root = project.root.resolve(); root.mkdir(parents=True,exist_ok=True)
    lock = root/'.abscada-save.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('Hay otro guardado en curso. Si la aplicación se cerró inesperadamente, revisa y elimina .abscada-save.lock') from None
    os.close(descriptor)
    try:
        if getattr(project,'_disk_root',None) == root and disk_state(root) != project._disk_state:
            raise ValueError('Los archivos han cambiado fuera de Studio. Recarga el proyecto antes de guardar para evitar sobrescribirlos')
        _write_project(project)
        remember_disk(project)
    finally:
        lock.unlink(missing_ok=True)


def _write_project(project):
    content = documents(project)
    root = project.root.resolve(); root.mkdir(parents=True,exist_ok=True)
    stale = set()
    if (root/'libraries.json').exists():
        stale.add('libraries.json')
    for folder, pattern in (('screens','*.json'),('faceplates','*.json'),('scripts','*.py')):
        stale.update(p.relative_to(root).as_posix() for p in (root/folder).glob(pattern))
    targets = set(content) | stale
    for name in targets:
        if not (root/name).resolve().is_relative_to(root):
            raise ValueError('Archivo del proyecto fuera de su carpeta')
    previous = {name:(root/name).read_bytes() if (root/name).exists() else None for name in targets}
    changed = [name for name in sorted(targets) if previous[name] != content.get(name)]
    applied = []
    with tempfile.TemporaryDirectory(prefix='.abscada-save-',dir=root) as staging:
        stage = Path(staging)
        for name in changed:
            if previous[name] is not None:
                backup=stage/'backup'/name
                backup.parent.mkdir(parents=True,exist_ok=True)
                backup.write_bytes(previous[name])
            if name in content:
                target = stage/name; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(content[name])
        try:
            for name in changed:
                target = root/name; target.parent.mkdir(parents=True,exist_ok=True)
                if name in content: os.replace(stage/name,target)
                else: target.unlink()
                applied.append(name)
        except OSError as failure:
            restore_errors=[]
            for name in reversed(applied):
                try:
                    if previous[name] is None: (root/name).unlink(missing_ok=True)
                    else: os.replace(stage/'backup'/name,root/name)
                except OSError as exc:
                    restore_errors.append(str(exc))
            if restore_errors:
                recovery=root/('.abscada-recovery-'+uuid.uuid4().hex)
                os.rename(stage,recovery)
                raise OSError(f'Falló el guardado y su restauración. Copias recuperables en {recovery}: {failure}') from failure
            raise
