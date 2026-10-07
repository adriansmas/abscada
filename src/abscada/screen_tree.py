"""Screen organisation and ownership rules (no Qt).

- Screens live in folders: ``screen["folder"] = "Proceso/Grupo 1"``; empty folders are kept in
  ``manifest["screen_folders"]``. Folders are only an editing aid: runtime ignores them.
- A layout is an ordinary screen that contains screen containers (the old ``layout`` flag is migrated).
- Every trend / alarm viewer element owns its configuration in trends.json / alarm_views.json:
  copying the element copies the configuration, deleting it deletes the configuration.
"""
import copy
import re

NAME = re.compile(r"[A-Za-z0-9_-]+")
VIEWERS = {"trend": "trends", "alarm_view": "alarm_views"}
LAYOUT_FOLDER = "Layouts"


# --- folders -----------------------------------------------------------------------------------

def clean_folder(path):
    return "/".join(part.strip() for part in str(path).replace("\\", "/").split("/") if part.strip())


def parent_folder(path):
    return path.rpartition("/")[0]


# Screens and the project's library objects (faceplate documents) have their own folder trees.
# Objects of the standard library and of linked libraries are read-only and keep theirs.
FOLDER_KEYS = {"screens": "screen_folders", "faceplates": "library_folders"}


def _documents(project, kind):
    if kind == "screens":
        return project.screens
    from .faceplate_libraries import owner
    return {name: document for name, document in project.faceplates.items() if not owner(project, name)}


def folders(project, kind="screens"):
    """Every folder path (explicit, implied by a document, and all their parents), sorted."""
    result = set()
    documents = _documents(project, kind).values()
    for path in project.manifest.get(FOLDER_KEYS[kind], []) + [d.get("folder", "") for d in documents]:
        parts = path.split("/") if path else []
        result.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    return sorted(result, key=str.casefold)


def validate_folders(project):
    for kind, key in FOLDER_KEYS.items():
        explicit = project.manifest.get(key, [])
        if not isinstance(explicit, list) or any(not isinstance(p, str) or not p or clean_folder(p) != p for p in explicit):
            raise ValueError(f"{key} debe ser una lista de rutas de carpeta")
        for name, document in getattr(project, kind).items():
            folder = document.get("folder", "")
            if not isinstance(folder, str) or clean_folder(folder) != folder:
                raise ValueError(f"{name}: carpeta inválida")


def _store_folders(project, paths, kind="screens"):
    paths = sorted({p for p in paths if p}, key=str.casefold)
    if paths:
        project.manifest[FOLDER_KEYS[kind]] = paths
    else:
        project.manifest.pop(FOLDER_KEYS[kind], None)


def _rebase(path, old, new):
    if path == old:
        return new
    if path.startswith(old + "/"):
        return (new + path[len(old):]) if new else path[len(old) + 1:]
    return path


def add_folder(project, parent, name, kind="screens"):
    path = clean_folder(f"{parent}/{name}")
    if not clean_folder(name) or "/" in clean_folder(name):
        raise ValueError("Escribe un nombre de carpeta sin «/»")
    if path.casefold() in {f.casefold() for f in folders(project, kind)}:
        raise ValueError("Ya existe esa carpeta")
    _store_folders(project, project.manifest.get(FOLDER_KEYS[kind], []) + [path], kind)
    return path


def rename_folder(project, path, name, kind="screens"):
    name = clean_folder(name)
    if not name or "/" in name:
        raise ValueError("Escribe un nombre de carpeta sin «/»")
    new = clean_folder(f"{parent_folder(path)}/{name}")
    if new == path:
        return new
    if new.casefold() in {f.casefold() for f in folders(project, kind)} and new.casefold() != path.casefold():
        raise ValueError("Ya existe esa carpeta")
    _store_folders(project, [_rebase(p, path, new) for p in project.manifest.get(FOLDER_KEYS[kind], [])], kind)
    for document in _documents(project, kind).values():
        _set_folder(document, _rebase(document.get("folder", ""), path, new))
    return new


def delete_folder(project, path, kind="screens"):
    """Remove a folder; its documents and subfolders move up to the parent folder."""
    parent = parent_folder(path)
    _store_folders(project, [_rebase(p, path, parent) for p in project.manifest.get(FOLDER_KEYS[kind], []) if p != path], kind)
    for document in _documents(project, kind).values():
        _set_folder(document, _rebase(document.get("folder", ""), path, parent))


def move_folder(project, path, target, kind="screens"):
    """Move a folder (with its content) inside ``target`` ("" = root)."""
    if target == path or target.startswith(path + "/"):
        raise ValueError("No se puede mover una carpeta dentro de sí misma")
    new = clean_folder(f"{target}/{path.rpartition('/')[2]}")
    if new == path:
        return new
    if new.casefold() in {f.casefold() for f in folders(project, kind)}:
        raise ValueError("Ya existe una carpeta con ese nombre en el destino")
    _store_folders(project, [_rebase(p, path, new) for p in project.manifest.get(FOLDER_KEYS[kind], [])] + [new], kind)
    for document in _documents(project, kind).values():
        _set_folder(document, _rebase(document.get("folder", ""), path, new))
    return new


def _set_folder(document, folder):
    if folder:
        document["folder"] = folder
    else:
        document.pop("folder", None)


def move_screen(project, name, folder):
    folder = clean_folder(folder)
    if folder and folder not in folders(project):
        raise ValueError("Carpeta inexistente")
    _set_folder(project.screens[name], folder)


def move_faceplate(project, name, folder):
    folder = clean_folder(folder)
    if name not in _documents(project, "faceplates"):
        raise ValueError("Los objetos de la librería estándar y de librerías vinculadas no se pueden mover")
    if folder and folder not in folders(project, "faceplates"):
        raise ValueError("Carpeta inexistente")
    _set_folder(project.faceplates[name], folder)


# --- screens ----------------------------------------------------------------------------------

def is_layout(document):
    return any(e["kind"] == "screen_container" for e in document.get("elements", []))


def check_new_name(project, name, collection="screens"):
    if not NAME.fullmatch(name or ""):
        raise ValueError("Usa solo letras sin acentos, números, «_» y «-»")
    from .validation import filename
    filename(name)
    if name.casefold() in {n.casefold() for n in getattr(project, collection)}:
        raise ValueError(f"Ya existe «{name}»")


def _editable_documents(project):
    from .faceplate_libraries import owner
    for collection in ("screens", "faceplates"):
        for name, document in getattr(project, collection).items():
            if collection == "faceplates" and owner(project, name):
                continue
            yield collection, name, document


def _opens_screen(element):
    return element["kind"] == "screen_container" or (element["kind"] == "button" and element.get("action") in {"screen", "popup"})


def screen_references(project, name):
    """Human readable places that open or embed screen ``name`` (outside the screen itself)."""
    found = []
    if project.manifest.get("startup_screen") == name:
        found.append("es la pantalla inicial")
    if any(w.get("screen") == name for w in project.manifest.get("display", {}).get("windows", [])):
        found.append("ventana de arranque en Monitores…")
    for collection, document_name, document in _editable_documents(project):
        if (collection, document_name) == ("screens", name):
            continue
        for element in document["elements"]:
            if _opens_screen(element) and element.get("screen") == name:
                found.append(f"{'objeto ' if collection == 'faceplates' else ''}{document_name} · {element['id']}")
    return found


def scripts_mentioning(project, name):
    pattern = re.compile(r"""['"]%s['"]""" % re.escape(name))
    return sorted(script for script, source in project.scripts.items() if pattern.search(source))


def rename_screen(project, old, new):
    """Rename and update every reference. Returns the scripts that still mention the old name."""
    if new == old:
        return []
    if new.casefold() != old.casefold():
        check_new_name(project, new)
    elif not NAME.fullmatch(new):
        raise ValueError("Usa solo letras sin acentos, números, «_» y «-»")
    project.screens = {new if key == old else key: value for key, value in project.screens.items()}
    if project.manifest.get("startup_screen") == old:
        project.manifest["startup_screen"] = new
    for window in project.manifest.get("display", {}).get("windows", []):
        if window.get("screen") == old:
            window["screen"] = new
    for _, _, document in _editable_documents(project):
        for element in document["elements"]:
            if _opens_screen(element) and element.get("screen") == old:
                element["screen"] = new
    return scripts_mentioning(project, old)


def duplicate_screen(project, name, new):
    check_new_name(project, new)
    document = copy.deepcopy(project.screens[name])
    document["title"] = f"{document.get('title', name)} (copia)"
    clone_viewers(project, document["elements"])
    screens = list(project.screens.items())
    position = next(i for i, (key, _) in enumerate(screens) if key == name) + 1
    screens.insert(position, (new, document))
    project.screens = dict(screens)


def delete_screen(project, name):
    if len(project.screens) == 1:
        raise ValueError("El proyecto necesita al menos una pantalla")
    used = screen_references(project, name)
    if used:
        raise ValueError(f"No se puede eliminar «{name}» porque se usa en:\n· " + "\n· ".join(used))
    release_viewers(project, project.screens[name]["elements"], removing_screen=name)
    del project.screens[name]


# --- faceplates -------------------------------------------------------------------------------

def _uses_template(element, name):
    return element.get("template") == name and (element["kind"] == "faceplate" or element.get("action") == "faceplate_popup")


def faceplate_references(project, name):
    return [f"{'objeto ' if collection == 'faceplates' else ''}{document_name} · {element['id']}"
            for collection, document_name, document in _editable_documents(project)
            for element in document["elements"] if _uses_template(element, name)]


def rename_faceplate(project, old, new):
    if new == old:
        return
    if new.casefold() != old.casefold():
        check_new_name(project, new, "faceplates")
    elif not NAME.fullmatch(new):
        raise ValueError("Usa solo letras sin acentos, números, «_» y «-»")
    project.faceplates = {new if key == old else key: value for key, value in project.faceplates.items()}
    for _, _, document in _editable_documents(project):
        for element in document["elements"]:
            if _uses_template(element, old):
                element["template"] = new


def duplicate_faceplate(project, name, new):
    from .faceplate_libraries import owner
    check_new_name(project, new, "faceplates")
    document = copy.deepcopy(project.faceplates[name])
    if owner(project, name):
        # Copy of a read-only object into the project's library: it starts at the root.
        document.pop("folder", None)
    else:
        document["title"] = f"{document.get('title', name)} (copia)"
    project.faceplates[new] = document


def delete_faceplate(project, name):
    used = faceplate_references(project, name)
    if used:
        raise ValueError(f"No se puede eliminar «{name}» porque se usa en:\n· " + "\n· ".join(used))
    del project.faceplates[name]


# --- viewers (trends and alarm views) ---------------------------------------------------------

def _viewer_elements(project, skip_screen=None):
    for name, document in project.screens.items():
        if name == skip_screen:
            continue
        for element in document["elements"]:
            if element["kind"] in VIEWERS:
                yield element


def new_view_id(project, kind, base):
    views = getattr(project, VIEWERS[kind])
    base = re.sub(r"[^A-Za-z0-9_-]", "_", base) or kind
    candidate, number = base, 1
    while candidate in views:
        number += 1
        candidate = f"{base}_{number}"
    return candidate


def clone_viewers(project, elements):
    """Give copied viewer elements their own copy of the configuration."""
    for element in elements:
        if element["kind"] in VIEWERS and element.get("view") in getattr(project, VIEWERS[element["kind"]]):
            views = getattr(project, VIEWERS[element["kind"]])
            new = new_view_id(project, element["kind"], element["id"])
            views[new] = copy.deepcopy(views[element["view"]])
            element["view"] = new


def release_viewers(project, elements, removing_screen=None):
    """Delete the configuration of removed viewer elements when nothing else uses it."""
    removed = {id(e) for e in elements}
    still_used = {(e["kind"], e.get("view")) for e in _viewer_elements(project, removing_screen) if id(e) not in removed}
    for element in elements:
        if element["kind"] in VIEWERS and (element["kind"], element.get("view")) not in still_used:
            getattr(project, VIEWERS[element["kind"]]).pop(element.get("view"), None)


def own_viewers(project):
    """Old projects could share one configuration between several viewers: give each its own copy."""
    seen = set()
    for element in _viewer_elements(project):
        key = (element["kind"], element.get("view"))
        views = getattr(project, VIEWERS[element["kind"]])
        if key in seen and element.get("view") in views:
            new = new_view_id(project, element["kind"], element["id"])
            views[new] = copy.deepcopy(views[element["view"]])
            element["view"] = new
            key = (element["kind"], new)
        seen.add(key)


def migrate(project):
    """Bring older projects to the current organisation rules."""
    for document in project.screens.values():
        if document.pop("layout", False) and not document.get("folder"):
            document["folder"] = LAYOUT_FOLDER
    own_viewers(project)
