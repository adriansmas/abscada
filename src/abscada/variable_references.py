"""Where variables are used, and renaming a variable or a field of a data type. No Qt.

A reference is any stored text that names a variable path: element ``tag`` values (also
inside dynamics, states, motion and button steps), the ``bindings`` of library object
instances and pop-ups, alarms, recording files and trend curves. A rename changes every
reference to the renamed path or to anything inside it (``Bomba1`` also changes
``Bomba1.marcha`` and ``Bomba1.temps[2]``), the PLC links of the fields, and records the
old name so the history already archived under it is still read (``historian.renames``).

Script code is not rewritten on its own: ``scripts_mentioning`` lists the scripts that
quote the name, and ``replace_in_scripts`` replaces only those quoted texts.
"""
import copy
import re
from .i18n import tr
from . import structures


def inside(value, path):
    """``value`` is ``path`` or something inside it."""
    return isinstance(value, str) and (value == path or value.startswith((path + ".", path + "[")))


def mentions(value, path):
    """``value`` uses ``path``: as itself, as a part of it, or as a variable index (``A[Sel]``)."""
    return inside(value, path) or any(inside(index, path) for index in structures.index_tags(value))


def moved(value, old, new):
    if not isinstance(value, str):
        return value
    if inside(value, old):
        value = new + value[len(old):]
    if "[" in value:
        value = re.sub(r"\[([^\[\]]+)\]", lambda m: "[" + (new + m[1].strip()[len(old):] if inside(m[1].strip(), old) else m[1]) + "]", value)
    return value


def moved_any_index(value, old, new):
    """``moved`` for a path with variable indices: ``Sets[Sel].temp`` also matches ``Sets[1].temp``.

    ``old`` and ``new`` have the same indices (a field rename), so the value keeps its own.
    """
    if not structures.index_tags(value):
        return value
    pattern = re.escape(old)
    pattern = re.sub(r"\\\[(?:-?\d+)\\\]", lambda m: r"\[([^\[\]]+)\]", pattern)
    match = re.match(pattern + r"(?=$|[.\[])", value)
    if not match:
        return value
    indices = iter(match.groups())
    rebuilt = re.sub(r"\[(-?\d+)\]", lambda m: f"[{next(indices)}]", new)
    return rebuilt + value[match.end():]


# --- every reference --------------------------------------------------------------------------

def _element_slots(element):
    """(container, key) pairs of one element that hold a variable path, at any depth."""
    slots = []
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("tag"), str):
                slots.append((value, "tag"))
            if (value.get("kind") == "faceplate" or value.get("action") == "faceplate_popup" or "template" in value) and isinstance(value.get("bindings"), dict):
                slots.extend((value["bindings"], key) for key, item in value["bindings"].items() if isinstance(item, str))
            for key, item in value.items():
                if key != "bindings":
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(element)
    return slots


def slots(project):
    """Every stored variable path as (where, container, key); ``$`` references are not paths."""
    from .faceplate_libraries import owner
    result = []
    for collection, prefix in (("screens", tr("Pantalla")), ("faceplates", tr("Objeto"))):
        for name, document in getattr(project, collection).items():
            if collection == "faceplates" and owner(project, name):
                continue   # read-only: libraries cannot name the project's variables
            for element in document.get("elements", []):
                for container, key in _element_slots(element):
                    result.append((f"{prefix} {name} · {element.get('id', '')}", container, key))
    for alarm in project.alarms.get("items", []):
        result.append((tr("Alarma {id}", id=alarm.get("id", "")), alarm, "tag"))
    for file in project.historian.get("files", []):
        variables = file.get("variables", [])
        result.extend((tr("Registro {name}", name=file.get("name", file.get("id", ""))), variables, index) for index in range(len(variables)))
    for log in project.historian.get("tags", []):
        result.append((tr("Registro"), log, "tag"))
    for name, trend in project.trends.items():
        for curve in trend.get("curves", []):
            result.append((tr("Tendencia {name}", name=trend.get("title", name) if isinstance(trend.get("title"), str) else name), curve, "tag"))
    return [(where, container, key) for where, container, key in result
            if isinstance(container[key], str) and container[key] and not container[key].startswith("$")]


def usages(project, path):
    """Places that use ``path`` or something inside it: [(where, the stored path)]."""
    return [(where, container[key]) for where, container, key in slots(project) if mentions(container[key], path)]


def used_paths(project, paths):
    """The ``paths`` used somewhere (as in ``usages``), looking at every place only once."""
    reached = set()
    for _, container, key in slots(project):
        value = container[key]
        for candidate in [value] + structures.index_tags(value):
            try:
                reached.update(path for _, path in structures.segments(candidate))
            except (ValueError, TypeError):
                reached.add(candidate)
    return [path for path in paths if path in reached]


def scripts_mentioning(project, path):
    """Scripts whose code quotes ``path`` or a path inside it; they need a review."""
    pattern = _quoted(path)
    return sorted(name for name, source in project.scripts.items() if pattern.search(source))


def _quoted(path):
    return re.compile(r"""(['"])%s(?=[.\[]|\1)""" % re.escape(path))


def replace_in_scripts(project, old, new):
    """Replace quoted ``old`` (and quoted paths inside it) with ``new`` in every script."""
    pattern = _quoted(old)
    for name, source in project.scripts.items():
        project.scripts[name] = pattern.sub(lambda match: match[1] + new, source)


# --- renaming ---------------------------------------------------------------------------------

def _apply(project, renames):
    """Move every reference, PLC link and history alias from each old prefix to its new one."""
    for _, container, key in slots(project):
        for old, new in renames:
            container[key] = moved_any_index(moved(container[key], old, new), old, new)
    for variable in project.variables:
        if variable.get("bindings"):
            updated = {}
            for leaf, binding in variable["bindings"].items():
                for old, new in renames:
                    leaf = moved(leaf, old, new)
                updated[leaf] = binding
            variable["bindings"] = updated
    if renames:
        project.historian.setdefault("renames", []).extend(dict(old=old, new=new) for old, new in renames)


def check_name(project, name, current=None):
    if not structures.valid_name(name) or not name.strip() or name != name.strip():
        raise ValueError(tr("Nombre vacío, con puntos o con corchetes"))
    if name != current and any(v["name"] == name for v in project.variables):
        raise ValueError(tr("Ya existe una variable «{name}»", name=name))


def rename_variable(project, old, new):
    """Rename a variable and everything that uses it."""
    if new == old:
        return
    check_name(project, new, old)
    variable = next(v for v in project.variables if v["name"] == old)
    variable["name"] = new
    _apply(project, [(old, new)])


def _type_paths(types, kind, target):
    """Relative paths inside ``kind`` whose kind is the structure ``target`` ("" for itself)."""
    found = [""] if kind == target else []
    found += [rel for rel, sub in structures.members(types, kind).items() if sub == target]
    return found


def _rename_in_value(types, kind, value, target, old, new):
    """The initial value of ``kind`` with the field ``old`` of every ``target`` renamed."""
    base, length = structures.split_kind(kind)
    if length is not None:
        return [_rename_in_value(types, base, item, target, old, new) for item in value] if isinstance(value, list) else value
    if kind not in types or not isinstance(value, dict):
        return value
    result = {}
    for field, item in value.items():
        child = _rename_in_value(types, types[kind].get(field, ""), item, target, old, new)
        result[new if kind == target and field == old else field] = child
    return result


def field_renames(project, type_name, old, new):
    """(old path, new path) of the field in every variable that holds the type."""
    renames = []
    for variable in project.variables:
        for rel in _type_paths(project.types, variable["type"], type_name):
            base = structures.join(variable["name"], rel)
            renames.append((structures.join(base, old), structures.join(base, new)))
    return renames


def rename_field(project, type_name, old, new):
    """Rename a field of a data type: the type, the values and links of its variables,
    the ``$parameter`` paths inside objects and every reference to the field."""
    from .faceplate_libraries import type_owner
    if new == old:
        return
    if type_owner(project, type_name):
        raise ValueError(tr("{name} pertenece a una librería vinculada y es de solo lectura", name=type_name))
    fields = project.types[type_name]
    if not structures.valid_name(new) or not new.strip():
        raise ValueError(tr("Nombre de campo vacío, con puntos o con corchetes"))
    if new in fields:
        raise ValueError(tr("El tipo {name} ya tiene un campo «{field}»", name=type_name, field=new))
    renames = field_renames(project, type_name, old, new)
    for variable in project.variables:
        variable["initial"] = _rename_in_value(project.types, variable["type"], variable["initial"], type_name, old, new)
        if variable.get("overrides"):
            updated = {}
            for path, value in variable["overrides"].items():
                for rel in _type_paths(project.types, variable["type"], type_name):
                    path = moved(path, structures.join(rel, old), structures.join(rel, new))
                updated[path] = value
            variable["overrides"] = updated
    # Inside objects whose parameters are (or contain) the type: $motor.old → $motor.new.
    for name, document in project.faceplates.items():
        local = []
        for parameter, kind in document.get("parameters", {}).items():
            for rel in _type_paths(project.types, kind, type_name):
                base = "$" + structures.join(parameter, rel)
                local.append((structures.join(base, old), structures.join(base, new)))
        if local:
            for element in document.get("elements", []):
                for container, key in _element_slots(element):
                    for before, after in local:
                        container[key] = moved_any_index(moved(container[key], before, after), before, after)
    project.types[type_name] = {new if field == old else field: kind for field, kind in fields.items()}
    _apply(project, renames)


# --- history ----------------------------------------------------------------------------------

def former_names(project, path):
    """Names ``path`` had before, newest first, so its archived history is still found."""
    names, current = [], path
    for entry in reversed(project.historian.get("renames", [])):
        if inside(current, entry["new"]):
            current = moved(current, entry["new"], entry["old"])
            if current not in names and current != path:
                names.append(current)
    return names


def validate(project):
    renames = project.historian.get("renames", [])
    if not isinstance(renames, list) or any(not isinstance(e, dict) or set(e) != {"old", "new"}
                                            or not all(isinstance(e[k], str) and e[k] for k in e) for e in renames):
        raise ValueError(tr("historian.renames debe ser una lista de pares old/new"))


# --- data types -------------------------------------------------------------------------------

def renamed_kind(kind, old, new):
    """``Motor[4]`` with ``Motor`` renamed to ``Bomba`` → ``Bomba[4]``; other kinds unchanged."""
    base, length = structures.split_kind(kind)
    if length is not None:
        return renamed_kind(base, old, new) + kind[len(base):]
    return new if kind == old else kind


def type_usages(project, name):
    """Variables, data types and objects that use the data type ``name`` (also in arrays)."""
    found = [tr("Variable {name}", name=v["name"]) for v in project.variables if structures.structure_of(v["type"]) == name]
    found += [tr("Tipo {name}", name=other) for other, fields in project.types.items()
              if other != name and any(structures.structure_of(kind) == name for kind in fields.values())]
    found += [tr("Objeto {name}", name=template) for template, document in project.faceplates.items()
              if any(structures.structure_of(kind) == name for kind in document.get("parameters", {}).values())]
    return found


def rename_type(project, old, new):
    """Rename a data type in types.json, the variables, other types and object parameters.

    Variable paths do not change: a type name is not part of them.
    """
    from .faceplate_libraries import type_owner, owner
    if new == old:
        return
    if type_owner(project, old):
        raise ValueError(tr("{name} pertenece a una librería vinculada y es de solo lectura", name=old))
    if not structures.valid_name(new) or not new.strip() or new != new.strip() or new in structures.PRIMITIVES:
        raise ValueError(tr("Nombre de tipo vacío, reservado, con puntos o con corchetes"))
    if new in project.types:
        raise ValueError(tr("Ya existe un tipo «{name}»", name=new))
    project.types = {new if name == old else name: {field: renamed_kind(kind, old, new) for field, kind in fields.items()}
                     for name, fields in project.types.items()}
    for variable in project.variables:
        variable["type"] = renamed_kind(variable["type"], old, new)
    for template, document in project.faceplates.items():
        if not owner(project, template) and "parameters" in document:
            document["parameters"] = {key: renamed_kind(kind, old, new) for key, kind in document["parameters"].items()}
