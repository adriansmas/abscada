"""Prepare a complete project save, rollback replaced files on I/O failure."""
import json
import os
import tempfile
import hashlib
import uuid
from pathlib import Path
from .i18n import tr


def documents(project):
    data = {getattr(project, 'manifest_file', 'project.json'): project.manifest}
    for key in ('types','variables','connections','alarms','historian','trends','alarm_views','automation'):
        data[key+'.json'] = getattr(project, key)
    from .faceplate_libraries import type_owner
    # Types of linked libraries live in libraries.json, like their objects.
    data['types.json'] = {name: fields for name, fields in project.types.items() if not type_owner(project, name)}
    if project.libraries:
        data['libraries.json'] = project.libraries
    # Optional documents: written only when they differ from the default, so projects
    # that do not use security or the OPC UA server keep the same files as before.
    from .security import default_security
    from .opcua_server import default_server
    for key, default in (('security', default_security()), ('opcua_server', default_server())):
        if getattr(project, key) != default:
            data[key+'.json'] = getattr(project, key)
    from .faceplate_libraries import owner
    for folder in ('screens','faceplates'):
        for name, value in getattr(project, folder).items():
            if folder == 'faceplates' and owner(project, name):
                continue
            if Path(name).name != name or name in ('.','..') or '/' in name or '\\' in name:
                raise ValueError(tr('Nombre de documento inválido'))
            data[f'{folder}/{name}.json'] = value
    result = {name: (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8') for name,value in data.items()}
    result.update({f'scripts/{name}.py': source.encode('utf-8') for name,source in project.scripts.items()})
    return result


def disk_state(root, known=None):
    """{relative path: (mtime_ns, size, sha256)} of the project documents.

    A file whose time and size match ``known`` keeps its hash without being read again."""
    # users.json and secrets.json are written at once (accounts editor, runtime, connection form), never by a save.
    paths = [p for p in root.glob('*.json') if p.name not in ('users.json', 'secrets.json')] + list(root.glob('*.abscada'))
    for folder, pattern in (('screens','*.json'),('faceplates','*.json'),('scripts','*.py')):
        paths.extend((root/folder).glob(pattern))
    known = known or {}
    state = {}
    for path in paths:
        name = path.relative_to(root).as_posix()
        stat = path.stat()
        previous = known.get(name)
        if previous and previous[:2] == (stat.st_mtime_ns, stat.st_size):
            state[name] = previous
        else:
            state[name] = (stat.st_mtime_ns, stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    return state


def same_disk(state, other):
    """The same files with the same contents (times may differ)."""
    return state.keys() == other.keys() and all(state[name][2] == other[name][2] for name in state)


def remember_disk(project):
    project._disk_root = project.root.resolve()
    project._disk_state = disk_state(project._disk_root, getattr(project, '_disk_state', None))


def _take_save_lock(lock):
    """The save lock holds the process id: a lock left by a process that died is taken over."""
    for attempt in (0, 1):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            from .durable import process_alive
            try:
                owner = int(lock.read_text(encoding='ascii').strip() or 0)
            except (OSError, ValueError):
                owner = 0
            if attempt == 0 and owner and owner != os.getpid() and not process_alive(owner):
                lock.unlink(missing_ok=True)
                continue
            raise ValueError(tr('Hay otro guardado en curso. Si la aplicación se cerró inesperadamente, revisa y elimina .abscada-save.lock')) from None
        os.write(descriptor, str(os.getpid()).encode('ascii'))
        os.close(descriptor)
        return


def save_project(project):
    root = project.root.resolve(); root.mkdir(parents=True,exist_ok=True)
    lock = root/'.abscada-save.lock'
    _take_save_lock(lock)
    try:
        if getattr(project,'_disk_root',None) == root and not same_disk(disk_state(root, project._disk_state), project._disk_state):
            raise ValueError(tr('Los archivos han cambiado fuera de Studio. Recarga el proyecto antes de guardar para evitar sobrescribirlos'))
        _write_project(project)
        remember_disk(project)
    finally:
        lock.unlink(missing_ok=True)


def _write_project(project):
    content = documents(project)
    project._saved_documents = set(content)
    root = project.root.resolve(); root.mkdir(parents=True,exist_ok=True)
    stale = set()
    for optional in ('libraries.json', 'security.json', 'opcua_server.json'):
        if (root/optional).exists():
            stale.add(optional)
    for folder, pattern in (('screens','*.json'),('faceplates','*.json'),('scripts','*.py')):
        stale.update(p.relative_to(root).as_posix() for p in (root/folder).glob(pattern))
    targets = set(content) | stale
    for name in targets:
        if not (root/name).resolve().is_relative_to(root):
            raise ValueError(tr('Archivo del proyecto fuera de su carpeta'))
    from .durable import exact_exists, sync_directory, write_synced
    # Exact names: on Windows «00_LAYOUT.json» opens «00_layout.json», so a rename that only
    # changes letter case would look unchanged and the old name would then delete the file.
    previous = {name:(root/name).read_bytes() if exact_exists(root/name) else None for name in targets}
    # Removals first: the new name of a case-only rename is written after the old one is gone.
    changed = sorted((name for name in targets if previous[name] != content.get(name)), key=lambda name: (name in content, name))
    applied = []
    with tempfile.TemporaryDirectory(prefix='.abscada-save-',dir=root) as staging:
        stage = Path(staging)
        for name in changed:
            if previous[name] is not None:
                backup=stage/'backup'/name
                backup.parent.mkdir(parents=True,exist_ok=True)
                write_synced(backup, previous[name])
            if name in content:
                target = stage/name; target.parent.mkdir(parents=True,exist_ok=True)
                write_synced(target, content[name])
        try:
            for name in changed:
                target = root/name; target.parent.mkdir(parents=True,exist_ok=True)
                if name in content: os.replace(stage/name,target)
                else: target.unlink()
                applied.append(name)
            for folder in {(root/name).parent for name in changed}:
                sync_directory(folder)
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
                raise OSError(tr("Falló el guardado y su restauración. Copias recuperables en {recovery}: {failure}", recovery=recovery, failure=failure)) from failure
            raise
