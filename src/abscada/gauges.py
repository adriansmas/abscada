"""Analog indicators: dial, semicircular panel meter and thermometer.

The geometry helpers have no Qt dependency so they can be validated and tested
alone; paint_gauge draws with a QPainter supplied by graphics.py.
"""
import math
from .i18n import tr

STYLES = {"dial": "Esfera 240°", "semi": tr("Semicírculo 180°"), "thermometer": tr("Termómetro")}
SWEEP = {"dial": 240.0, "semi": 180.0}
WARNING_COLOR = "#e5a339"
ALARM_COLOR = "#d64545"
FACE_COLOR = "#ffffff"
INK = "#273b53"


def nice_step(span, target_ticks=5):
    """Major tick spacing of 1, 2, 2.5 or 5 × 10^n giving about target_ticks intervals."""
    raw = span / max(1, target_ticks)
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def ticks(low, high, target_ticks=5):
    step = nice_step(high - low, target_ticks)
    first = math.ceil(low / step - 1e-9) * step
    values, value = [], first
    while value <= high + step * 1e-6:
        values.append(round(value, 10))
        value += step
    return values, step


def fraction(value, low, high):
    try:
        return max(0.0, min(1.0, (float(value) - low) / (high - low)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def angle(style, frac):
    """Needle angle in degrees, Qt convention (0° = 3 o'clock, counter-clockwise positive)."""
    sweep = SWEEP[style]
    start = 90 + sweep / 2  # e.g. 210° for a 240° dial: lower-left
    return start - sweep * frac


def label(value, step):
    decimals = 0 if float(step).is_integer() else min(2, len(f"{step:g}".split(".")[-1]))
    return f"{value:.{decimals}f}"


def validate(element):
    style = element.get("gauge_style", "dial")
    if style not in STYLES:
        raise ValueError(tr("Estilo de indicador desconocido"))
    low, high = element.get("min", 0), element.get("max", 100)
    for key in ("min", "max", "warning", "alarm"):
        if key in element and (isinstance(element[key], bool) or not isinstance(element[key], (int, float))
                               or not math.isfinite(element[key])):
            raise ValueError(tr("{key}: se esperaba un número", key=key))
    if high <= low:
        raise ValueError(tr("El máximo del indicador debe ser mayor que el mínimo"))
    if "warning" in element and "alarm" in element and element["alarm"] < element["warning"]:
        raise ValueError(tr("El umbral de alarma no puede ser menor que el de aviso"))
    if not isinstance(element.get("decimals", 1), int) or not 0 <= element.get("decimals", 1) <= 10:
        raise ValueError(tr("decimals debe estar entre 0 y 10"))


# --------------------------------------------------------------------------
# Painting (Qt imported lazily so the helpers above stay Qt-free)
# --------------------------------------------------------------------------
def paint_gauge(painter, e, rect, value, good, design):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPen

    style = e.get("gauge_style", "dial")
    low, high = float(e.get("min", 0)), float(e.get("max", 100))
    frac = 0.4 if design else fraction(value, low, high)
    pointer = QColor(e.get("color", "#c0392b") if (good or design) else "#97a9ba")
    ink = QColor(INK)
    marks, step = ticks(low, high)
    decimals = int(e.get("decimals", 1))
    if design:
        reading = "—"
    elif value is None or not good:
        reading = "—"
    else:
        try:
            reading = f"{float(value):.{decimals}f}"
        except (TypeError, ValueError):
            reading = "—"
    unit = e.get("unit", "")
    caption = e.get("text", "")
    zones = [(e["warning"], e.get("alarm", high), WARNING_COLOR)] if "warning" in e else []
    if "alarm" in e:
        zones.append((e["alarm"], high, ALARM_COLOR))
    base_font = QFont(painter.font())

    def font(size, bold=False):
        f = QFont(base_font)
        f.setPixelSize(max(6, int(size)))
        f.setBold(bold)
        return f

    if style == "thermometer":
        _paint_thermometer(painter, rect, e, frac, low, high, marks, step, zones, pointer, ink, reading, unit, caption, font, good, design)
        return

    sweep = SWEEP[style]
    # Square dial area; a semicircle only needs a bit more than half its height.
    width, height = rect.width(), rect.height()
    if style == "semi":
        # Leave a strip under the pivot for caption and reading.
        strip = max(18.0, height * 0.2)
        radius = min(width / 2 - 10, height - strip - 14)
        center = QPointF(rect.center().x(), rect.top() + 8 + radius)
    else:
        radius = min(width, height) / 2 - 4
        center = QPointF(rect.center().x(), rect.top() + 4 + radius)
    face = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)

    painter.setPen(QPen(QColor("#9fb0c0"), max(1.0, radius * 0.03)))
    painter.setBrush(QColor(FACE_COLOR))
    if style == "semi":
        painter.drawRoundedRect(QRectF(rect.left() + 1, rect.top() + 1, width - 2, height - 2), 8, 8)
    else:
        painter.drawEllipse(face)

    start = 90 + sweep / 2
    arc_rect = face.adjusted(radius * 0.12, radius * 0.12, -radius * 0.12, -radius * 0.12)
    for zone_low, zone_high, color in zones:
        a = fraction(zone_low, low, high)
        b = fraction(zone_high, low, high)
        if b <= a:
            continue
        painter.setPen(QPen(QColor(color), radius * 0.09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(arc_rect, int((start - sweep * a) * 16), int(-sweep * (b - a) * 16))

    # Scale: major ticks with labels, four minor ticks between them.
    painter.setPen(QPen(ink, max(1.0, radius * 0.018)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(arc_rect, int(start * 16), int(-sweep * 16))
    painter.setFont(font(radius * 0.13))
    minor = step / 5
    value_tick = math.ceil(low / minor - 1e-9) * minor
    while value_tick <= high + minor * 1e-6:
        theta = math.radians(angle(style, fraction(value_tick, low, high)))
        major = any(abs(value_tick - m) < minor * 1e-3 for m in marks)
        outer = radius * 0.88
        inner = radius * (0.72 if major else 0.80)
        painter.setPen(QPen(ink, max(1.0, radius * (0.022 if major else 0.012))))
        painter.drawLine(QPointF(center.x() + outer * math.cos(theta), center.y() - outer * math.sin(theta)),
                         QPointF(center.x() + inner * math.cos(theta), center.y() - inner * math.sin(theta)))
        if major:
            text_r = radius * 0.56
            box = QRectF(center.x() + text_r * math.cos(theta) - radius * 0.22, center.y() - text_r * math.sin(theta) - radius * 0.09,
                         radius * 0.44, radius * 0.18)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label(value_tick, step))
        value_tick += minor

    # Reading and caption
    reading_color = ink if good or design else QColor("#b57519")
    if style == "semi":
        # Caption on the left and reading on the right of the strip below the pivot.
        strip_box = QRectF(rect.left() + 12, center.y() + 6, width - 24, rect.bottom() - center.y() - 10)
        text_size = min(strip_box.height() * 0.62, radius * 0.15)
        if caption:
            painter.setPen(QColor("#63768b"))
            painter.setFont(font(text_size * 0.7))
            painter.drawText(strip_box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, caption)
        painter.setPen(reading_color)
        painter.setFont(font(text_size, True))
        painter.drawText(strip_box, (Qt.AlignmentFlag.AlignRight if caption else Qt.AlignmentFlag.AlignHCenter) | Qt.AlignmentFlag.AlignVCenter,
                         f"{reading} {unit}".strip())
    else:
        # Caption just under the hub, reading below it: the needle never crosses either.
        if caption:
            painter.setPen(QColor("#63768b"))
            painter.setFont(font(radius * 0.12))
            painter.drawText(QRectF(center.x() - radius * 0.62, center.y() + radius * 0.13, radius * 1.24, radius * 0.17),
                             Qt.AlignmentFlag.AlignCenter, caption)
        painter.setPen(reading_color)
        painter.setFont(font(radius * 0.19, True))
        painter.drawText(QRectF(center.x() - radius * 0.62, center.y() + radius * 0.32, radius * 1.24, radius * 0.25),
                         Qt.AlignmentFlag.AlignCenter, f"{reading} {unit}".strip())

    # Needle and hub
    theta = math.radians(angle(style, frac))
    tip = QPointF(center.x() + radius * 0.84 * math.cos(theta), center.y() - radius * 0.84 * math.sin(theta))
    tail = QPointF(center.x() - radius * 0.14 * math.cos(theta), center.y() + radius * 0.14 * math.sin(theta))
    painter.setPen(QPen(pointer, max(1.5, radius * 0.035), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(tail, tip)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#34495e"))
    hub = radius * 0.08
    painter.drawEllipse(QRectF(center.x() - hub, center.y() - hub, 2 * hub, 2 * hub))
    if not design and not good:
        painter.setPen(QColor("#b57519"))
        painter.setFont(font(radius * 0.2, True))
        painter.drawText(QRectF(rect.right() - radius * 0.35, rect.top(), radius * 0.35, radius * 0.3), Qt.AlignmentFlag.AlignCenter, "!")


def _paint_thermometer(painter, rect, e, frac, low, high, marks, step, zones, pointer, ink, reading, unit, caption, font, good, design):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPen

    width, height = rect.width(), rect.height()
    reading_h = max(14.0, height * 0.1)
    caption_h = reading_h if caption else 0.0
    top = rect.top() + caption_h + 4
    bulb = min(width * 0.32, (height - caption_h - reading_h) * 0.18)
    tube_w = bulb * 0.48
    cx = rect.left() + width * 0.38
    tube_top = top + tube_w / 2
    bulb_center = QPointF(cx, rect.bottom() - reading_h - bulb / 2 - 4)
    tube_bottom = bulb_center.y() - bulb * 0.35
    scale_len = tube_bottom - tube_top - tube_w * 0.3

    painter.setPen(QPen(QColor("#9fb0c0"), 1.5))
    painter.setBrush(QColor(FACE_COLOR))
    painter.drawRoundedRect(QRectF(cx - tube_w / 2, tube_top - tube_w / 2, tube_w, tube_bottom - tube_top + tube_w), tube_w / 2, tube_w / 2)
    painter.drawEllipse(bulb_center, bulb / 2, bulb / 2)

    def y_of(f):
        return tube_bottom - tube_w * 0.3 - scale_len * f

    for zone_low, zone_high, color in zones:
        a, b = fraction(zone_low, low, high), fraction(zone_high, low, high)
        if b > a:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRect(QRectF(cx - tube_w / 2 - tube_w * 0.45, y_of(b), tube_w * 0.25, y_of(a) - y_of(b)))

    liquid = pointer
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(liquid)
    inner = tube_w * 0.5
    painter.drawEllipse(bulb_center, bulb / 2 - 3, bulb / 2 - 3)
    painter.drawRect(QRectF(cx - inner / 2, y_of(frac), inner, bulb_center.y() - y_of(frac)))

    painter.setFont(font(min(width * 0.11, height * 0.05)))
    minor = step / 5
    value_tick = math.ceil(low / minor - 1e-9) * minor
    while value_tick <= high + minor * 1e-6:
        y = y_of(fraction(value_tick, low, high))
        major = any(abs(value_tick - m) < minor * 1e-3 for m in marks)
        x0 = cx + tube_w / 2 + 3
        painter.setPen(QPen(ink, 1.5 if major else 1))
        painter.drawLine(QPointF(x0, y), QPointF(x0 + (tube_w * 0.6 if major else tube_w * 0.3), y))
        if major:
            painter.drawText(QRectF(x0 + tube_w * 0.7, y - 8, width - (x0 - rect.left()) - tube_w * 0.7, 16),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label(value_tick, step))
        value_tick += minor

    painter.setPen(ink if good or design else QColor("#b57519"))
    painter.setFont(font(reading_h * 0.8, True))
    painter.drawText(QRectF(rect.left(), rect.bottom() - reading_h - 2, width, reading_h), Qt.AlignmentFlag.AlignCenter, f"{reading} {unit}".strip())
    if caption:
        painter.setPen(QColor("#63768b"))
        painter.setFont(font(caption_h * 0.75))
        painter.drawText(QRectF(rect.left(), rect.top(), width, caption_h), Qt.AlignmentFlag.AlignCenter, caption)
