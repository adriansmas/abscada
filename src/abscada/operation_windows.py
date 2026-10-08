"""Operation windows: faceplate pop-ups, window options and monitor layout (no Qt).

Monitors are numbered from 1 in project files, as operators see them.
"""
import hashlib
from .i18n import tr

MODES = {"normal", "maximized", "fullscreen"}
# The operation window opens maximized unless the project says otherwise.
MAIN_MODE = "maximized"
# fit: keep proportions · stretch: fill the window · none: actual size
SCALES = {"fit", "stretch", "none"}
MAX_MONITORS = 16


def monitor_number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_MONITORS:
        raise ValueError(tr("El monitor debe ser un número entre 1 y {MAX_MONITORS}", MAX_MONITORS=MAX_MONITORS))
    return value


def validate_window(options):
    """Placement of a pop-up opened from a button."""
    if not isinstance(options, dict) or set(options) - {"monitor", "on_top", "mode"}:
        raise ValueError(tr("Opciones de ventana inválidas"))
    monitor_number(options.get("monitor"))
    if options.get("mode", "normal") not in MODES:
        raise ValueError(tr("Modo de ventana desconocido"))
    if not isinstance(options.get("on_top", False), bool):
        raise ValueError(tr("«Siempre encima» debe ser booleano"))


def validate_display(project):
    """manifest.display = {main: {monitor, mode, scale}, windows: [{screen, monitor, mode, on_top}]}"""
    display = project.manifest.get("display", {})
    if not isinstance(display, dict) or set(display) - {"main", "windows"}:
        raise ValueError(tr("Configuración de monitores inválida"))
    main = display.get("main", {})
    if not isinstance(main, dict) or set(main) - {"monitor", "mode", "scale"}:
        raise ValueError(tr("Configuración de la ventana principal inválida"))
    monitor_number(main.get("monitor"))
    if main.get("mode", MAIN_MODE) not in MODES:
        raise ValueError(tr("Modo de ventana desconocido"))
    if main.get("scale", "fit") not in SCALES:
        raise ValueError(tr("Escalado desconocido"))
    windows = display.get("windows", [])
    if not isinstance(windows, list):
        raise ValueError(tr("La lista de ventanas de arranque es inválida"))
    for window in windows:
        if not isinstance(window, dict) or set(window) - {"screen", "monitor", "mode", "on_top"}:
            raise ValueError(tr("Ventana de arranque inválida"))
        if window.get("screen") not in project.screens:
            raise ValueError(tr("Ventana de arranque: pantalla inexistente {get}", get=window.get('screen')))
        monitor_number(window.get("monitor"))
        if window.get("mode", "normal") not in MODES:
            raise ValueError(tr("Modo de ventana desconocido"))
        if not isinstance(window.get("on_top", False), bool):
            raise ValueError(tr("«Siempre encima» debe ser booleano"))


def validate_popup_button(element, project, tags, parameters):
    """Checks a button that opens a faceplate in its own window.

    Inside a faceplate template the bindings may forward the template's own
    parameters with ``$name``; they are resolved when the instance is expanded.
    """
    template = project.faceplates.get(element.get("template"))
    if template is None:
        raise ValueError(tr("Objeto de librería emergente inexistente"))
    bindings = element.get("bindings", {})
    expected = template.get("parameters", {})
    if not isinstance(bindings, dict) or set(bindings) != set(expected):
        raise ValueError(tr("Parámetros del objeto emergente incompletos"))
    for parameter, kind in expected.items():
        source = bindings[parameter]
        if not isinstance(source, str):
            raise ValueError(tr("Parámetro {parameter}: se esperaba una variable", parameter=parameter))
        if source == "":
            continue  # not assigned yet
        if source.startswith("$"):
            actual = parameters.get(source[1:])
        else:
            actual = tags[source]["type"] if source in tags else None
        if actual != kind:
            raise ValueError(tr("Tipo incorrecto en parámetro {parameter} del objeto emergente", parameter=parameter))
    if not isinstance(element.get("title", ""), str):
        raise ValueError(tr("Título de ventana inválido"))


def validate_popup_writes(element, project, tags):
    """After expansion every binding is a real tag; commands need writable tags."""
    from .dynamics import parameter_writable
    template = project.faceplates[element["template"]]
    for parameter, source in element.get("bindings", {}).items():
        if source and parameter_writable(template, parameter) and not tags.get(source, {}).get("writable", False):
            raise ValueError(tr("Objeto emergente: variable de solo lectura {source}", source=source))


def resolve_popup_bindings(child, instance_bindings):
    """Forward ``$parameter`` references of a nested pop-up button to real tags."""
    if child.get("action") == "faceplate_popup":
        child["bindings"] = {key: instance_bindings[value[1:]] if isinstance(value, str) and value.startswith("$") else value
                             for key, value in child.get("bindings", {}).items()}
    return child


def popup_key(template, bindings):
    """One window per faceplate and equipment; opening it again focuses it."""
    return ("faceplate", template, tuple(sorted(bindings.items())))


def popup_title(project, template, bindings, title="", *, language=None):
    from .project_languages import resolve, default_language
    code = language or default_language(project)
    title = resolve(title, code, default_language(project))
    if title:
        return title
    base = resolve(project.faceplates[template].get("title", ''), code, default_language(project)) or template
    roots = [value.split(".") for value in bindings.values()]
    common = []
    for parts in zip(*roots) if roots else ():
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    # A single binding names the leaf itself (Pump1.running); keep its owner.
    if len(roots) == 1 and len(common) > 1:
        common = common[:-1]
    return f"{base} · {'.'.join(common)}" if common else base


def settings_key(project, key):
    """Stable QSettings key per project folder and window."""
    project_id = hashlib.sha1(str(project.root).encode("utf-8")).hexdigest()[:12]
    if isinstance(key, tuple):
        _, template, bindings = key
        digest = hashlib.sha1(repr(bindings).encode("utf-8")).hexdigest()[:12]
        name = f"faceplate_{template}_{digest}"
    else:
        name = str(key)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return f"projects/{project_id}/windows/{safe}"
