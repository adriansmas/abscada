"""Buttons with a list of actions (``"action": "sequence"``).

One click dispatches every step in order without waiting for any of them: writes enter the
queue of their connection, scripts the script queue, and navigation happens last. Sending
an order is not confirmation from the PLC, and nothing is undone when a later step fails.
"""
from .i18n import tr

SEQUENCE = "sequence"
# Press/release actions need the button held down: they cannot be a step of a click.
STEP_ACTIONS = ("set", "toggle", "script", "set_language", "screen", "popup", "faceplate_popup", "close_popup")
NAVIGATION = {"screen", "popup", "faceplate_popup", "close_popup"}
STEP_KEYS = {"action", "tag", "value", "script", "language", "screen", "target_container",
             "modal", "window", "template", "bindings", "title"}
MAX_STEPS = 20


def steps(element):
    """The steps of a sequence button; an empty list for any other element."""
    if element.get("kind", "button") == "button" and element.get("action") == SEQUENCE:
        return element.get("actions", [])
    return []


def with_steps(element):
    """The element followed by its steps: every dict that may carry an action reference."""
    return [element, *steps(element)]


def as_button(element, step):
    """A step seen as a single-action button, for the checks and code of single actions."""
    button = {key: value for key, value in step.items()}
    button.update(kind="button", id=element["id"])
    if "permission" in element:
        button["permission"] = element["permission"]
    return button


def validate_structure(element):
    """Shape of the list; each step is then checked like a single-action button.

    An empty list is allowed while editing: the button does nothing and the project review warns.
    """
    actions = element.get("actions")
    if not isinstance(actions, list):
        raise ValueError(tr("La lista de acciones del botón no es válida"))
    if len(actions) > MAX_STEPS:
        raise ValueError(tr("Un botón admite como máximo {count} acciones", count=MAX_STEPS))
    for number, step in enumerate(actions, 1):
        if not isinstance(step, dict) or step.get("action") not in STEP_ACTIONS:
            raise ValueError(tr("Acción {number}: tipo no admitido en una lista de acciones", number=number))
        unknown = set(step) - STEP_KEYS
        if unknown:
            raise ValueError(tr("Acción {number}: propiedad desconocida {key}", number=number, key=sorted(unknown)[0]))
        if step["action"] in NAVIGATION and number != len(actions):
            raise ValueError(tr("Acción {number}: abrir o cerrar pantallas solo puede ser la última acción", number=number))
    if element.get("tag"):
        raise ValueError(tr("Un botón con lista de acciones indica la variable en cada acción"))


def label(step):
    """Short description of a step for messages and the editor list."""
    action = step.get("action")
    if action == "set":
        return tr("Asignar {value} a {tag}", value=step.get("value", ""), tag=step.get("tag") or "—")
    if action == "toggle":
        return tr("Alternar {tag}", tag=step.get("tag") or "—")
    if action == "script":
        return tr("Ejecutar script {script}", script=step.get("script") or "—")
    if action == "set_language":
        return tr("Cambiar idioma a {language}", language=step.get("language") or "—")
    if action == "screen":
        return tr("Ir a la pantalla {screen}", screen=step.get("screen") or "—")
    if action == "popup":
        return tr("Abrir emergente {screen}", screen=step.get("screen") or "—")
    if action == "faceplate_popup":
        return tr("Abrir objeto emergente {template}", template=step.get("template") or "—")
    if action == "close_popup":
        return tr("Cerrar la ventana emergente")
    return str(action)
