"""Validation of engineering definitions for alarms, archives and operator views."""
import math
import re
from .i18n import tr

OPERATORS = {"true": tr("Activo"), "false": tr("Inactivo"), "high": tr("Mayor o igual"), "low": tr("Menor o igual"), "equal": tr("Igual"), "not_equal": tr("Distinto")}
ALARM_COLUMNS = (("priority",tr("Prioridad")),("category",tr("Categoría")),("message",tr("Mensaje")),("tag",tr("Variable")),
    ("state",tr("Estado / evento")),("entered_at",tr("Entrada")),("returned_at",tr("Salida")),("ack_at","ACK"),("actor",tr("Operador")),("quality",tr("Calidad")))
DEFAULT_ALARM_COLUMNS = ["priority","category","message","state","entered_at","returned_at","ack_at"]


def number(value, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(tr("Se esperaba un número finito"))
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(tr("Valor fuera de rango"))


def identifiers(items):
    ids = [item.get("id", "") for item in items]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)):
        raise ValueError(tr("Identificadores vacíos o duplicados"))
    return set(ids)


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
        raise ValueError(tr("El color debe tener formato #RRGGBB o #AARRGGBB"))


def validate_operations(project, tags):
    categories = identifiers(project.alarms["categories"])
    identifiers(project.alarms["items"])
    for category in project.alarms["categories"]:
        if not category.get("name", "").strip():
            raise ValueError(tr("La categoría necesita un nombre"))
        color(category.get("color", "#d74c4c"))
    for alarm in project.alarms["items"]:
        if alarm.get("tag") not in tags or alarm.get("category") not in categories:
            raise ValueError(tr("{id}: variable o categoría de alarma inexistente", id=alarm['id']))
        if not alarm.get("message", "").strip() or alarm.get("condition") not in OPERATORS:
            raise ValueError(tr("Texto o condición de alarma inválidos"))
        kind = tags[alarm["tag"]]["type"]
        if alarm["condition"] in {"true", "false"}:
            if kind != "bool":
                raise ValueError(tr("La alarma digital necesita una variable bool"))
        elif kind not in {"float", "int"}:
            raise ValueError(tr("La alarma por valor necesita una variable numérica"))
        number(alarm.get("threshold", 0))
        number(alarm.get("hysteresis", 0), 0)
        for key in ("on_delay_ms", "off_delay_ms"):
            number(alarm.get(key, 0), 0, 3600000)
        number(alarm.get("priority", 500), 1, 1000)
        for key in ("enabled", "ack_required"):
            if not isinstance(alarm.get(key, True), bool):
                raise ValueError(tr("{key} debe ser booleano", key=key))
    number(project.historian.get("retention_days", 90), 1, 36500)
    number(project.alarms.get("retention_days", 365), 1, 36500)
    from . import recording
    if "files" in project.historian and project.historian.get("tags"):
        raise ValueError(tr("No mezcles files y el formato antiguo tags"))
    identifiers(recording.files(project))
    file_ids = [f["id"].casefold() for f in recording.files(project)]
    if len(file_ids) != len(set(file_ids)):
        raise ValueError(tr("Identificadores de fichero duplicados"))
    for file in recording.files(project):
        recording.path(project, file["id"])
        if not file.get("name", "").strip():
            raise ValueError(tr("El fichero necesita un nombre"))
        number(file["interval_ms"], 50, 3600000)
        if not isinstance(file["variables"], list):
            raise ValueError(tr("Las variables del fichero deben ser una lista"))
    logged = set()
    for log in recording.logs(project):
        if log.get("tag") not in tags or log["tag"] in logged:
            raise ValueError(tr("Variable histórica inexistente o duplicada"))
        logged.add(log["tag"])
        number(log.get("interval_ms", 1000), 50, 3600000)
        number(log.get("deadband", 0), 0)
        if log.get("mode", "cyclic") not in {"cyclic", "change"}:
            raise ValueError(tr("Modo de registro desconocido"))
    for name, trend in project.trends.items():
        if not name or not trend.get("title", "").strip():
            raise ValueError(tr("La tendencia necesita nombre y título"))
        number(trend.get("window_seconds", 600), 10, 31536000)
        axes = identifiers(trend["axes"])
        if not axes or len(axes) > 8:
            raise ValueError(tr("Una tendencia necesita entre 1 y 8 ejes"))
        for axis in trend["axes"]:
            if not isinstance(axis.get("title", axis["id"]), str) or not axis.get("title", axis["id"]).strip():
                raise ValueError(tr("El eje necesita un título"))
            if axis.get("side", "left") not in {"left", "right"}:
                raise ValueError(tr("Posición del eje inválida"))
            if not isinstance(axis.get("visible", True), bool) or not isinstance(axis.get("auto", True), bool):
                raise ValueError(tr("Las opciones del eje deben ser booleanas"))
            number(axis.get("min", 0)); number(axis.get("max", 100))
            if axis.get("min", 0) >= axis.get("max", 100):
                raise ValueError(tr("Escala del eje inválida"))
        identifiers(trend["curves"])
        for curve in trend["curves"]:
            if curve.get("tag") not in tags or tags[curve["tag"]]["type"] not in {"int", "float", "bool"}:
                raise ValueError(tr("Las curvas necesitan variables numéricas o bool"))
            if curve.get("axis") not in axes:
                raise ValueError(tr("Eje de curva inexistente"))
            color(curve.get("color", "#147d75"))
            number(curve.get("width", 2), 1, 10)
            if not isinstance(curve.get("visible", True), bool):
                raise ValueError(tr("La visibilidad de la curva debe ser booleana"))
    for name, view in project.alarm_views.items():
        if not name or not view.get("title", "").strip() or not set(view.get("categories", [])) <= categories:
            raise ValueError(tr("Visor de alarmas inválido"))
        number(view.get("min_priority", 1), 1, 1000)
        if not isinstance(view.get("allow_ack", True), bool):
            raise ValueError(tr("allow_ack debe ser booleano"))
        if not set(view.get("columns", DEFAULT_ALARM_COLUMNS)) <= {key for key, _ in ALARM_COLUMNS}:
            raise ValueError(tr("Columnas del visor desconocidas"))
        if view.get("mode", "pending") not in {"pending", "active", "history", "events"}:
            raise ValueError(tr("Modo de visor de alarmas inválido"))
