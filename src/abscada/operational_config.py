"""Validation of engineering definitions for alarms, archives and operator views."""
import math
import re

OPERATORS = {"true": "Activo", "false": "Inactivo", "high": "Mayor o igual", "low": "Menor o igual", "equal": "Igual", "not_equal": "Distinto"}
ALARM_COLUMNS = (("priority","Prioridad"),("category","Categoría"),("message","Mensaje"),("tag","Variable"),
    ("state","Estado / evento"),("entered_at","Entrada"),("returned_at","Salida"),("ack_at","ACK"),("actor","Operador"),("quality","Calidad"))
DEFAULT_ALARM_COLUMNS = ["priority","category","message","state","entered_at","returned_at","ack_at"]


def number(value, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Se esperaba un número finito")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError("Valor fuera de rango")


def identifiers(items):
    ids = [item.get("id", "") for item in items]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Identificadores vacíos o duplicados")
    return set(ids)


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
        raise ValueError("El color debe tener formato #RRGGBB o #AARRGGBB")


def validate_operations(project, tags):
    categories = identifiers(project.alarms["categories"])
    identifiers(project.alarms["items"])
    for category in project.alarms["categories"]:
        if not category.get("name", "").strip():
            raise ValueError("La categoría necesita un nombre")
        color(category.get("color", "#d74c4c"))
    for alarm in project.alarms["items"]:
        if alarm.get("tag") not in tags or alarm.get("category") not in categories:
            raise ValueError(f"{alarm['id']}: variable o categoría de alarma inexistente")
        if not alarm.get("message", "").strip() or alarm.get("condition") not in OPERATORS:
            raise ValueError("Texto o condición de alarma inválidos")
        kind = tags[alarm["tag"]]["type"]
        if alarm["condition"] in {"true", "false"}:
            if kind != "bool":
                raise ValueError("La alarma digital necesita una variable bool")
        elif kind not in {"float", "int"}:
            raise ValueError("La alarma por valor necesita una variable numérica")
        number(alarm.get("threshold", 0))
        number(alarm.get("hysteresis", 0), 0)
        for key in ("on_delay_ms", "off_delay_ms"):
            number(alarm.get(key, 0), 0, 3600000)
        number(alarm.get("priority", 500), 1, 1000)
        for key in ("enabled", "ack_required"):
            if not isinstance(alarm.get(key, True), bool):
                raise ValueError(f"{key} debe ser booleano")
    number(project.historian.get("retention_days", 90), 1, 36500)
    number(project.alarms.get("retention_days", 365), 1, 36500)
    from . import recording
    if "files" in project.historian and project.historian.get("tags"):
        raise ValueError("No mezcles files y el formato antiguo tags")
    identifiers(recording.files(project))
    file_ids = [f["id"].casefold() for f in recording.files(project)]
    if len(file_ids) != len(set(file_ids)):
        raise ValueError("Identificadores de fichero duplicados")
    for file in recording.files(project):
        recording.path(project, file["id"])
        if not file.get("name", "").strip():
            raise ValueError("El fichero necesita un nombre")
        number(file["interval_ms"], 50, 3600000)
        if not isinstance(file["variables"], list):
            raise ValueError("Las variables del fichero deben ser una lista")
    logged = set()
    for log in recording.logs(project):
        if log.get("tag") not in tags or log["tag"] in logged:
            raise ValueError("Variable histórica inexistente o duplicada")
        logged.add(log["tag"])
        number(log.get("interval_ms", 1000), 50, 3600000)
        number(log.get("deadband", 0), 0)
        if log.get("mode", "cyclic") not in {"cyclic", "change"}:
            raise ValueError("Modo de registro desconocido")
    for name, trend in project.trends.items():
        if not name or not trend.get("title", "").strip():
            raise ValueError("La tendencia necesita nombre y título")
        number(trend.get("window_seconds", 600), 10, 31536000)
        axes = identifiers(trend["axes"])
        if not axes or len(axes) > 8:
            raise ValueError("Una tendencia necesita entre 1 y 8 ejes")
        for axis in trend["axes"]:
            if not isinstance(axis.get("title", axis["id"]), str) or not axis.get("title", axis["id"]).strip():
                raise ValueError("El eje necesita un título")
            if axis.get("side", "left") not in {"left", "right"}:
                raise ValueError("Posición del eje inválida")
            if not isinstance(axis.get("visible", True), bool) or not isinstance(axis.get("auto", True), bool):
                raise ValueError("Las opciones del eje deben ser booleanas")
            number(axis.get("min", 0)); number(axis.get("max", 100))
            if axis.get("min", 0) >= axis.get("max", 100):
                raise ValueError("Escala del eje inválida")
        identifiers(trend["curves"])
        for curve in trend["curves"]:
            if curve.get("tag") not in tags or tags[curve["tag"]]["type"] not in {"int", "float", "bool"}:
                raise ValueError("Las curvas necesitan variables numéricas o bool")
            if curve.get("axis") not in axes:
                raise ValueError("Eje de curva inexistente")
            color(curve.get("color", "#147d75"))
            number(curve.get("width", 2), 1, 10)
            if not isinstance(curve.get("visible", True), bool):
                raise ValueError("La visibilidad de la curva debe ser booleana")
    for name, view in project.alarm_views.items():
        if not name or not view.get("title", "").strip() or not set(view.get("categories", [])) <= categories:
            raise ValueError("Visor de alarmas inválido")
        number(view.get("min_priority", 1), 1, 1000)
        if not isinstance(view.get("allow_ack", True), bool):
            raise ValueError("allow_ack debe ser booleano")
        if not set(view.get("columns", DEFAULT_ALARM_COLUMNS)) <= {key for key, _ in ALARM_COLUMNS}:
            raise ValueError("Columnas del visor desconocidas")
        if view.get("mode", "pending") not in {"pending", "active", "history", "events"}:
            raise ValueError("Modo de visor de alarmas inválido")
