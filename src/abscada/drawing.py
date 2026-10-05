"""Serializable vector geometry. No Qt or acquisition dependencies."""
import math

PATH_KINDS = {"line", "polyline", "pipe"}
SHAPE_KINDS = {"rectangle", "ellipse"}


def world_points(element):
    return [[element["x"]+x*element["w"], element["y"]+y*element["h"]] for x,y in element["points"]]


def set_points(element, points):
    x, y = min(p[0] for p in points), min(p[1] for p in points)
    w, h = max(1, max(p[0] for p in points)-x), max(1, max(p[1] for p in points)-y)
    element.update(x=x, y=y, w=w, h=h, points=[[(px-x)/w,(py-y)/h] for px,py in points])


def validate_drawing(element):
    if element["kind"] in PATH_KINDS:
        points = element.get("points", [])
        if not isinstance(points, list) or not 2 <= len(points) <= 1000:
            raise ValueError("Un trazado necesita entre 2 y 1000 puntos")
        if element["kind"] == "line" and len(points) != 2:
            raise ValueError("Una línea necesita dos extremos")
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
                raise ValueError("Puntos de trazado inválidos")
        if all(point == points[0] for point in points):
            raise ValueError("El trazado no puede tener longitud cero")
    if element["kind"] in PATH_KINDS | SHAPE_KINDS:
        width = element.get("stroke_width", 12 if element["kind"] == "pipe" else 2)
        if isinstance(width,bool) or not isinstance(width,(int,float)) or not math.isfinite(width) or not 1 <= width <= 100:
            raise ValueError("El grosor debe estar entre 1 y 100")
        if element.get("stroke_style", "solid") not in {"solid", "dash", "dot"}:
            raise ValueError("Estilo de línea inválido")
        if element.get("arrows", "none") not in {"none", "start", "end", "both"}:
            raise ValueError("Extremos de línea inválidos")
        if not isinstance(element.get("filled", True), bool):
            raise ValueError("El relleno debe ser booleano")
