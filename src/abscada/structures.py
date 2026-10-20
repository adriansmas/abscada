"""Composite data types: structures and fixed-length arrays. No Qt.

A kind is a primitive (bool, int, float, string), a structure declared in
types.json, or an array of either: ``<kind>[n]`` has indices 0..n-1 (``float[8]``,
``Bomba[4]``) and ``<kind>[a..b]`` indices a..b, as in a Siemens DB (``Int[1..10]``).
Tag paths join fields with dots and indices with brackets:
``Bombas[2].temperaturas[0]``. A relative path is what follows the root
variable: ``[2].temperaturas[0]`` loses its leading dot only after a field.
"""
import re
from .i18n import tr

PRIMITIVES = {"bool", "int", "float", "string"}
DEFAULTS = {"bool": False, "int": 0, "float": 0.0, "string": ""}
MAX_LENGTH = 1000
_ARRAY = re.compile(r"(.+)\[(?:(-?\d+)\.\.)?(-?\d+)\]")
_STEP = re.compile(r"\.([^.\[\]]+)|\[(-?\d+)\]")
_NAME = re.compile(r"[^.\[\]]+")


def split_kind(kind):
    """``float[8]`` → ("float", 8); ``Int[1..10]`` → ("Int", 10); any other kind → (kind, None)."""
    match = _ARRAY.fullmatch(kind) if isinstance(kind, str) else None
    if not match:
        return kind, None
    low = int(match[2]) if match[2] is not None else 0
    return match[1], int(match[3]) - low + (1 if match[2] is not None else 0)


def lower(kind):
    """First index of an array kind: 0 for ``float[8]``, a for ``float[a..b]``."""
    match = _ARRAY.fullmatch(kind) if isinstance(kind, str) else None
    return int(match[2]) if match and match[2] is not None else 0


def indices(kind):
    base, length = split_kind(kind)
    return range(lower(kind), lower(kind) + length)


def known(kind, types):
    """A primitive, a declared structure or an array of them with 1..MAX_LENGTH elements."""
    base, length = split_kind(kind)
    if length is not None:
        return 1 <= length <= MAX_LENGTH and known(base, types)
    return kind in PRIMITIVES or kind in types


def structure_of(kind):
    """The structure an array (or array of arrays) is made of; the kind itself otherwise."""
    base, length = split_kind(kind)
    return structure_of(base) if length is not None else kind


def valid_name(name):
    """Names of variables, fields and parameters: no dots or brackets."""
    return isinstance(name, str) and bool(_NAME.fullmatch(name))


def root(path):
    return re.match(r"[^.\[]*", path)[0]


def relative(path):
    """``Bomba1.marcha`` → ``marcha``; ``T[3]`` → ``[3]``; ``Bomba1`` → ``""``."""
    return path[len(root(path)):].removeprefix(".")


def join(base, rel):
    if not rel:
        return base
    if not base or rel.startswith("["):
        return base + rel
    return base + "." + rel


def steps(path):
    """Fields and indices after the root: ``B.t[2].x`` → ["t", 2, "x"]; None if malformed."""
    rest, result, position = path[len(root(path)):], [], 0
    for match in _STEP.finditer(rest):
        if match.start() != position:
            return None
        result.append(match[1] if match[1] is not None else int(match[2]))
        position = match.end()
    return result if position == len(rest) else None


def relative_steps(rel):
    """Steps of a relative path: ``temps[2].x`` → ["temps", 2, "x"]; ``[0]`` → [0]."""
    if not rel:
        return []
    return steps("_" + (rel if rel.startswith("[") else "." + rel))


def kind_at(types, kind, path_steps):
    """Kind reached from ``kind`` following ``path_steps``; None if the path does not exist."""
    for step in path_steps:
        base, length = split_kind(kind)
        if isinstance(step, int):
            if length is None or step not in indices(kind):
                return None
            kind = base
        else:
            if length is not None or kind not in types or step not in types[kind]:
                return None
            kind = types[kind][step]
    return kind


def path_kind(types, roots, path):
    """Kind of any variable path (whole structure, array, element or leaf); None if unknown.

    ``roots`` maps each variable name to its declared kind.
    """
    if not isinstance(path, str) or root(path) not in roots:
        return None
    path_steps = steps(path)
    return None if path_steps is None else kind_at(types, roots[root(path)], path_steps)


def members(types, kind):
    """Every relative path inside a kind with its kind: structures, arrays and leaves."""
    base, length = split_kind(kind)
    if length is not None:
        children = [(f"[{i}]", base) for i in indices(kind)]
    elif kind in types:
        children = list(types[kind].items())
    else:
        return {}
    result = {}
    for name, child in children:
        result[name] = child
        result.update({join(name, rel): sub for rel, sub in members(types, child).items()})
    return result


def leaves(types, kind):
    """Primitive leaves by relative path: {"marcha": "bool", "t[0]": "float"}; a primitive gives {"": kind}."""
    if kind in PRIMITIVES:
        return {"": kind}
    return {rel: sub for rel, sub in members(types, kind).items() if sub in PRIMITIVES}


def compatible(types, actual, expected):
    """A variable path of kind ``actual`` can fill a parameter of kind ``expected``.

    Primitives must match. Structures and arrays match by shape: every leaf the
    parameter expects must exist with the same type (extra fields are allowed),
    so a project type can feed an identical type published by a library.
    """
    if actual is None or expected is None:
        return False
    if actual == expected:
        return True
    if actual in PRIMITIVES or expected in PRIMITIVES:
        return False
    available = leaves(types, actual)
    return all(available.get(rel) == sub for rel, sub in leaves(types, expected).items())


def default_value(types, kind):
    base, length = split_kind(kind)
    if length is not None:
        return [default_value(types, base) for _ in range(length)]
    if kind in PRIMITIVES:
        return DEFAULTS[kind]
    return {field: default_value(types, sub) for field, sub in types[kind].items()}


def set_at(types, kind, value, path_steps, new):
    """Write ``new`` inside a nested initial value of ``kind`` and return the whole value.

    Lists start at index 0 whatever the first index of the array is.
    """
    if not path_steps:
        return new
    keys = []
    for step in path_steps:
        if isinstance(step, int):
            keys.append(step - lower(kind)); kind = split_kind(kind)[0]
        else:
            keys.append(step); kind = types[kind][step]
    target = value
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = new
    return value


def segments(path):
    """Each level of a path with its own label: ``B.t[2]`` → [("B","B"), ("t","B.t"), ("[2]","B.t[2]")]."""
    result, current = [(root(path), root(path))], root(path)
    for step in steps(path) or []:
        current = join(current, f"[{step}]" if isinstance(step, int) else step)
        result.append((f"[{step}]" if isinstance(step, int) else step, current))
    return result


def composite_paths(types, variables):
    """Every structure or array a variable holds (the variable itself or a part), with its kind."""
    result = {}
    for variable in variables:
        kind = variable["type"]
        if kind not in PRIMITIVES:
            result[variable["name"]] = kind
        for rel, sub in members(types, kind).items():
            if sub not in PRIMITIVES:
                result[join(variable["name"], rel)] = sub
    return result


def parameter_references(parameters, types):
    """Every ``name`` and ``name.field`` / ``name[i]`` a faceplate can reference, with its kind."""
    result = {}
    for name, kind in parameters.items():
        result[name] = kind
        result.update({join(name, rel): sub for rel, sub in members(types, kind).items()})
    return result


def substitute(reference, bindings):
    """``$motor.marcha`` with ``motor → Bomba1`` gives ``Bomba1.marcha``.

    A parameter not assigned yet ("") gives "". Anything that is not a ``$``
    reference is returned unchanged.
    """
    if not isinstance(reference, str) or not reference.startswith("$"):
        return reference
    name = root(reference[1:])
    base = bindings[name]
    return base + reference[1 + len(name):] if base else ""


def check_definitions(types):
    """types.json: names, field names and kinds, without recursion."""
    for name, fields in types.items():
        if not valid_name(name) or name in PRIMITIVES or not isinstance(fields, dict) or not fields:
            raise ValueError(tr("Definición de tipo inválida: {name}", name=name))
        for field, kind in fields.items():
            if not valid_name(field) or not known(kind, types):
                raise ValueError(tr("Campo inválido: {name}.{field}", name=name, field=field))

    def visit(kind, stack):
        kind = structure_of(kind)
        if kind in stack:
            raise ValueError(tr("Tipo recursivo: {kind}", kind=kind))
        for child in types.get(kind, {}).values():
            visit(child, stack + (kind,))
    for name in types:
        visit(name, ())
