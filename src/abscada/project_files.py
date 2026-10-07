"""Where a project lives on disk: its main `.abscada` file and the folder around it.

A project is opened through one file, `<Name>.abscada` (the manifest), stored in
the project folder next to screens/, faceplates/, scripts/... Older projects
whose manifest is `project.json` keep working unchanged.
"""
import re
from pathlib import Path
from .i18n import tr

SUFFIX = ".abscada"
LEGACY_MANIFEST = "project.json"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def locate(path):
    """Return (root folder, manifest file name) for a project file or folder."""
    path = Path(path).expanduser().resolve()
    if path.is_file():
        if path.suffix.lower() == SUFFIX or path.name == LEGACY_MANIFEST:
            return path.parent, path.name
        raise ValueError(tr("{name} no es un proyecto abSCADA (se esperaba un archivo {SUFFIX})", name=path.name, SUFFIX=SUFFIX))
    if not path.is_dir():
        raise ValueError(tr("No existe el proyecto {path}", path=path))
    candidates = sorted(p.name for p in path.iterdir() if p.is_file() and p.suffix.lower() == SUFFIX)
    if len(candidates) > 1:
        raise ValueError(tr("La carpeta contiene varios proyectos ({join}); abre el archivo concreto", join=', '.join(candidates)))
    if candidates:
        return path, candidates[0]
    if (path / LEGACY_MANIFEST).is_file():
        return path, LEGACY_MANIFEST
    raise ValueError(tr("La carpeta {path} no contiene ningún proyecto abSCADA ({SUFFIX})", path=path, SUFFIX=SUFFIX))


def is_project(path):
    try:
        locate(path)
        return True
    except (ValueError, OSError):
        return False


def manifest_path(project):
    return Path(project.root) / getattr(project, "manifest_file", LEGACY_MANIFEST)


def safe_stem(name):
    """File name for a project title: portable on Windows and Linux."""
    stem = _INVALID.sub("_", name).strip().rstrip(".")
    if not stem or stem.lower() in _RESERVED:
        raise ValueError(tr("Nombre de proyecto no válido para un archivo"))
    return stem


def new_project_location(chosen):
    """For a file picked in «Nuevo proyecto», return (folder to create, manifest file name).

    Picking `D:/Plantas/Depuradora.abscada` creates `D:/Plantas/Depuradora/Depuradora.abscada`,
    so the project files never mix with whatever else lives in the chosen folder.
    """
    chosen = Path(chosen)
    stem = safe_stem(chosen.stem if chosen.suffix.lower() == SUFFIX else chosen.name)
    folder = chosen.parent / stem
    if folder.exists() and any(folder.iterdir()):
        raise ValueError(tr("Ya existe la carpeta {folder} y no está vacía", folder=folder))
    return folder, stem + SUFFIX
