"""Discrete value-to-text mappings, independent of Qt and acquisition."""
from decimal import Decimal, InvalidOperation
from .i18n import tr


def value_key(value, kind):
    raw = str(value)
    if kind == 'bool':
        key = raw.strip().lower()
        if key in {'true', '1'}:
            return True
        if key in {'false', '0'}:
            return False
        raise ValueError(tr('Un valor booleano debe ser 0, 1, false o true'))
    if kind in {'int', 'float'}:
        try:
            number = Decimal(raw.strip())
        except InvalidOperation:
            raise ValueError(tr('Valor numérico inválido')) from None
        if not number.is_finite() or (kind == 'int' and number != number.to_integral_value()):
            raise ValueError(tr('Valor numérico inválido para el tipo de variable'))
        return number
    return raw


def validate_text_list(element, kind=None):
    rows = element.get('texts', [])
    if not isinstance(rows, list):
        raise ValueError(tr('La lista de textos debe contener filas de valor y texto'))
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('value'), str) or not isinstance(row.get('text'), str):
            raise ValueError(tr('Cada fila necesita un valor y un texto de tipo string'))
        key = value_key(row['value'], kind)
        if key in seen:
            raise ValueError(tr('Hay valores duplicados en la lista de textos'))
        seen.add(key)
    if not isinstance(element.get('default_text', '—'), str):
        raise ValueError(tr('El texto por defecto debe ser string'))


def display_text(element, sample=None, *, design=False):
    if design:
        return tr('Lista de textos')
    if sample is None or sample.quality != 'good':
        return '—'
    value = sample.value
    kind = 'bool' if isinstance(value, bool) else 'int' if isinstance(value, int) else 'float' if isinstance(value, float) else 'string'
    key = value_key(value, kind)
    for row in element.get('texts', []):
        if value_key(row['value'], kind) == key:
            return row['text']
    return element.get('default_text', '—')
