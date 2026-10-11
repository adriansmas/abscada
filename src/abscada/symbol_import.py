"""Import variables from the symbols a PLC offers (adapters with ``browse()``). No Qt.

``browse()`` returns ``[(address, logical type)]``. Each selected symbol becomes a variable
bound to the connection by name; nothing reads offsets. Importing again only adds what is
new: a symbol already bound in the connection keeps its variable, its name and its uses.
"""
import re
from .connectors import create, definition

INITIAL = {"bool": False, "int": 0, "float": 0.0, "string": ""}


def explore(config, project_root):
    """Connect, browse and close. Runs outside the Qt thread."""
    adapter = create(config, project_root)
    try:
        adapter.connect()
        return adapter.browse()
    finally:
        try:
            adapter.close()
        except Exception:
            pass


def can_explore(config):
    from .connectors import REGISTRY
    return hasattr(REGISTRY.get(config.get("protocol")), "browse")


def variable_name(text):
    """``DB_Horno.Zona[2].Temperatura`` -> ``DB_Horno_Zona_2_Temperatura`` (variable names have no dots)."""
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", text)).strip("_") or "Variable"


def candidates(project, config, found):
    """Rows for the import list: (address, kind, label, existing variable or None)."""
    spec = definition(config["protocol"])
    bound = {}
    for variable in project.variables:
        binding = variable.get("binding") or {}
        if binding.get("connection") == config["id"]:
            try:
                bound[spec.describe(binding["address"], variable["type"])] = variable["name"]
            except (KeyError, TypeError, ValueError):
                pass
    rows = []
    for address, kind in found:
        label = spec.describe(address, kind)
        rows.append((address, kind, label, bound.get(label)))
    return rows


def import_symbols(project, config, rows, writable=False):
    """Add a variable per row not imported yet. Returns the names created."""
    spec = definition(config["protocol"])
    taken = {v["name"].casefold() for v in project.variables}
    created = []
    for address, kind, label, existing in rows:
        if existing:
            continue
        address = spec.validate_binding(address, kind, writable)
        base = variable_name(address.get("symbol") or label)
        name, number = base, 2
        while name.casefold() in taken:
            name, number = f"{base}_{number}", number + 1
        taken.add(name.casefold())
        project.variables.append(dict(name=name, type=kind, initial=INITIAL[kind], writable=writable,
                                      binding=dict(connection=config["id"], address=address)))
        created.append(name)
    return created
