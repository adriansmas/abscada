"""Script organisation in folders and script renaming (no Qt).

Folders are logical, an editing aid like screen folders: sources stay in ``scripts/<name>.py``
and every reference uses the name alone, so moving a script changes nothing else. They are
stored in automation.json: ``folders`` lists every folder (also empty ones) and
``script_folders`` maps a script name to its folder; scripts not listed are at the root.
"""
import re
from .i18n import tr
from .button_actions import with_steps
from .screen_tree import _rebase, clean_folder, parent_folder

NAME = re.compile(r"[A-Za-z0-9_-]+")


def folder_of(project, name):
    return project.automation.get("script_folders", {}).get(name, "")


def folders(project):
    """Every folder path (explicit, implied by a script, and all their parents), sorted."""
    result = set()
    located = [folder_of(project, name) for name in project.scripts]
    for path in project.automation.get("folders", []) + located:
        parts = path.split("/") if path else []
        result.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    return sorted(result, key=str.casefold)


def validate(project):
    explicit = project.automation.get("folders", [])
    if not isinstance(explicit, list) or any(not isinstance(p, str) or not p or clean_folder(p) != p for p in explicit):
        raise ValueError(tr("folders debe ser una lista de rutas de carpeta"))
    located = project.automation.get("script_folders", {})
    if not isinstance(located, dict) or any(not isinstance(folder, str) or not folder or clean_folder(folder) != folder
                                            for folder in located.values()):
        raise ValueError(tr("script_folders debe asociar cada script a una ruta de carpeta"))
    unknown = sorted(set(located) - set(project.scripts))
    if unknown:
        raise ValueError(tr("script_folders menciona un script inexistente: {name}", name=unknown[0]))


def ordered(project):
    """Script names grouped by folder, then by name; root scripts first."""
    return sorted(project.scripts, key=lambda name: (folder_of(project, name).casefold(), name.casefold()))


def label(project, name):
    folder = folder_of(project, name)
    return f"{folder}/{name}" if folder else name


def choices(project, first=()):
    """(name, text) pairs for script selectors, showing the folder of each script.

    ``first``: scripts already chosen in an ordered list (startup, screen opening); they keep
    their order at the top because the list order is the execution order.
    """
    first = [name for name in first if name in project.scripts]
    return [(name, label(project, name)) for name in first + [n for n in ordered(project) if n not in first]]


def _store(project, paths, located):
    paths = sorted({p for p in paths if p}, key=str.casefold)
    located = {name: folder for name, folder in located.items() if folder}
    for key, value in (("folders", paths), ("script_folders", located)):
        if value:
            project.automation[key] = value
        else:
            project.automation.pop(key, None)


def _located(project):
    return dict(project.automation.get("script_folders", {}))


def add_folder(project, parent, name):
    path = clean_folder(f"{parent}/{name}")
    if not clean_folder(name) or "/" in clean_folder(name):
        raise ValueError(tr("Escribe un nombre de carpeta sin «/»"))
    if path.casefold() in {f.casefold() for f in folders(project)}:
        raise ValueError(tr("Ya existe esa carpeta"))
    _store(project, project.automation.get("folders", []) + [path], _located(project))
    return path


def _rebase_all(project, old, new, drop=None):
    paths = [_rebase(p, old, new) for p in project.automation.get("folders", []) if p != drop]
    located = {name: _rebase(folder, old, new) for name, folder in _located(project).items()}
    _store(project, paths, located)


def rename_folder(project, path, name):
    name = clean_folder(name)
    if not name or "/" in name:
        raise ValueError(tr("Escribe un nombre de carpeta sin «/»"))
    new = clean_folder(f"{parent_folder(path)}/{name}")
    if new == path:
        return new
    if new.casefold() in {f.casefold() for f in folders(project)} and new.casefold() != path.casefold():
        raise ValueError(tr("Ya existe esa carpeta"))
    _rebase_all(project, path, new)
    return new


def delete_folder(project, path):
    """Remove a folder; its scripts and subfolders move up to the parent folder. No source is deleted."""
    _rebase_all(project, path, parent_folder(path), drop=path)


def move_folder(project, path, target):
    if target == path or target.startswith(path + "/"):
        raise ValueError(tr("No se puede mover una carpeta dentro de sí misma"))
    new = clean_folder(f"{target}/{path.rpartition('/')[2]}")
    if new == path:
        return new
    if new.casefold() in {f.casefold() for f in folders(project)}:
        raise ValueError(tr("Ya existe una carpeta con ese nombre en el destino"))
    _rebase_all(project, path, new)
    _store(project, project.automation.get("folders", []) + [new], _located(project))
    return new


def move_script(project, name, folder):
    folder = clean_folder(folder)
    if name not in project.scripts:
        raise ValueError(tr("Script inexistente"))
    if folder and folder not in folders(project):
        raise ValueError(tr("Carpeta inexistente"))
    located = _located(project)
    located[name] = folder
    _store(project, project.automation.get("folders", []), located)


def check_new_name(project, name):
    if not NAME.fullmatch(name or ""):
        raise ValueError(tr("Usa solo letras sin acentos, números, «_» y «-»"))
    if name.casefold() in {n.casefold() for n in project.scripts}:
        raise ValueError(tr("El script ya existe"))


def add_script(project, name, source, folder=""):
    check_new_name(project, name)
    project.scripts[name] = source
    if folder:
        move_script(project, name, folder)


def delete_script(project, name):
    """Delete a source; the project validation refuses it while something still uses it."""
    project.scripts.pop(name)
    located = _located(project)
    located.pop(name, None)
    _store(project, project.automation.get("folders", []), located)


def references(project, name):
    """Human readable places that run script ``name``."""
    found = []
    if name in project.automation.get("startup", []):
        found.append(tr("eventos de inicio"))
    found += [tr("tarea {id}", id=task.get("id")) for task in project.automation.get("tasks", []) if task.get("script") == name]
    for collection in ("screens", "faceplates"):
        for document_name, document in getattr(project, collection).items():
            prefix = "objeto " if collection == "faceplates" else ""
            if name in document.get("on_open", []):
                found.append(tr("{document} · al abrir", document=prefix + document_name))
            for element in document["elements"]:
                if any(t.get("action") == "script" and t.get("script") == name for t in with_steps(element)):
                    found.append(f"{prefix}{document_name} · {element['id']}")
    return found


def scripts_mentioning(project, name):
    """Other scripts whose code mentions ``name`` as a quoted text; they need a manual review."""
    pattern = re.compile(r"""['"]%s['"]""" % re.escape(name))
    return sorted(script for script, source in project.scripts.items() if script != name and pattern.search(source))


def rename_script(project, old, new):
    """Rename a script and every structured reference. Returns the scripts that still mention it in code."""
    if new == old:
        return []
    if new.casefold() != old.casefold():
        check_new_name(project, new)
    elif not NAME.fullmatch(new):
        raise ValueError(tr("Usa solo letras sin acentos, números, «_» y «-»"))
    mentions = scripts_mentioning(project, old)
    swap = lambda value: new if value == old else value
    project.scripts = {swap(key): source for key, source in project.scripts.items()}
    automation = project.automation
    if "startup" in automation:
        automation["startup"] = [swap(n) for n in automation["startup"]]
    for task in automation.get("tasks", []):
        task["script"] = swap(task.get("script"))
    located = {swap(key): folder for key, folder in _located(project).items()}
    _store(project, automation.get("folders", []), located)
    for collection in ("screens", "faceplates"):
        for document in getattr(project, collection).values():
            if "on_open" in document:
                document["on_open"] = [swap(n) for n in document["on_open"]]
            for element in document["elements"]:
                for target in with_steps(element):
                    if target.get("action") == "script" and target.get("script") == old:
                        target["script"] = new
    return [swap(name) for name in mentions]
