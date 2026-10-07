"""Versioned, editable project documents. No GUI dependencies."""
from __future__ import annotations

import copy
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from dataclasses import dataclass, field
from .i18n import tr

PRIMITIVES = {"bool", "int", "float", "string"}
from .text_lists import validate_text_list
from .drawing import PATH_KINDS, SHAPE_KINDS, validate_drawing
from .security import default_security
from .opcua_server import default_server

KINDS = PATH_KINDS | SHAPE_KINDS | {"screen_container", "text", "text_list", "lamp", "button", "input", "bar", "gauge", "image", "faceplate", "trend", "alarm_view"}


def coerce(value, kind):
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if value in (0, 1, "true", "false", "True", "False"):
            return value in (1, "true", "True")
        raise ValueError(tr("Se esperaba un booleano"))
    if kind == "int":
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValueError(tr("Se esperaba un entero")) from None
        if isinstance(value, bool) or not number.is_finite() or number != number.to_integral_value():
            raise ValueError(tr("Se esperaba un entero"))
        return int(number)
    if kind == "float":
        try:
            result = float(value)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(tr("Se esperaba un número real")) from None
        if not math.isfinite(result):
            raise ValueError(tr("Valor numérico no finito"))
        return result
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError(tr("Se esperaba un texto"))
        return value
    raise ValueError(tr("Tipo desconocido: {kind}", kind=kind))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Project:
    root: Path
    manifest: dict
    types: dict
    variables: list
    connections: list
    screens: dict
    faceplates: dict
    alarms: dict = field(default_factory=lambda: dict(categories=[], items=[], retention_days=365))
    historian: dict = field(default_factory=lambda: dict(files=[], retention_days=90))
    trends: dict = field(default_factory=dict)
    alarm_views: dict = field(default_factory=dict)

    scripts: dict = field(default_factory=dict)
    automation: dict = field(default_factory=lambda: dict(startup=[], tasks=[], timeout_seconds=10))
    libraries: dict = field(default_factory=dict)
    security: dict = field(default_factory=default_security)
    opcua_server: dict = field(default_factory=default_server)
    # Main project file inside root: "<Name>.abscada", or "project.json" for older projects.
    manifest_file: str = "project.json"

    @property
    def manifest_path(self):
        return Path(self.root) / self.manifest_file

    @classmethod
    def load(cls, path):
        """Open a project from its .abscada file, its legacy project.json, or its folder."""
        from .project_files import locate
        root, manifest_file = locate(path)
        manifest = read_json(root / manifest_file)
        if manifest.get("schema_version") != 1:
            raise ValueError(tr("Versión de proyecto no soportada (se requiere 1)"))
        project = cls(root, manifest, read_json(root / "types.json"),
                      read_json(root / "variables.json"), read_json(root / "connections.json"),
                      {p.stem: read_json(p) for p in sorted((root / "screens").glob("*.json"))},
                      {p.stem: read_json(p) for p in sorted((root / "faceplates").glob("*.json"))},
                      manifest_file=manifest_file)
        for key in ("alarms", "historian", "trends", "alarm_views", "automation", "libraries", "security", "opcua_server"):
            if (root / f"{key}.json").exists():
                setattr(project, key, read_json(root / f"{key}.json"))
        project.scripts = {p.stem: p.read_text(encoding="utf-8") for p in (root / "scripts").glob("*.py")}
        from .legacy_colors import migrate as migrate_colors
        migrate_colors(project)
        from .recording import migrate
        migrate(project)
        from .screen_tree import migrate as organise
        organise(project)
        from .faceplate_libraries import hydrate
        hydrate(project)
        project.validate()
        from .project_storage import remember_disk
        remember_disk(project)
        return project

    def tags(self):
        """Expand structured variables into typed leaf tags."""
        result = {}

        def expand(name, kind, value, source, stack=()):
            if kind in PRIMITIVES:
                tag = copy.deepcopy(source)
                relative_name = name.partition(".")[2]
                overrides = source.get("overrides", {}).get(relative_name, {})
                if set(overrides) - {"writable"}:
                    raise ValueError(tr("{name}: override solo admite writable", name=name))
                tag.update(overrides)
                tag.update(name=name, type=kind, initial=coerce(value, kind))
                binding = source.get("bindings", {}).get(name)
                if binding:
                    tag["binding"] = binding
                result[name] = tag
                return
            if kind in stack or kind not in self.types:
                raise ValueError(tr("Tipo inválido o recursivo: {kind}", kind=kind))
            if not isinstance(value, dict):
                raise ValueError(tr("{name}: el valor de una estructura debe ser un objeto", name=name))
            fields = self.types[kind]
            if set(value) != set(fields):
                raise ValueError(tr("{name}: los campos no coinciden con el tipo {kind}", name=name, kind=kind))
            for field, field_type in fields.items():
                expand(f"{name}.{field}", field_type, value[field], source, stack + (kind,))

        for variable in self.variables:
            expand(variable["name"], variable["type"], variable["initial"], variable)
        return result

    def validate(self):
        from .project_languages import validate, resolved_project, default_language
        validate(self)
        from .faceplate_libraries import validate_links
        validate_links(self)
        validate(self)
        resolved_project(self, default_language(self))._validate()

    def _validate(self):
        from .validation import filenames
        for collection in (self.screens, self.faceplates, self.scripts):
            filenames(collection)
        if not isinstance(self.manifest.get("name"), str) or not self.manifest["name"]:
            raise ValueError(tr("El proyecto necesita un nombre"))
        names = [v["name"] for v in self.variables]
        if len(names) != len(set(names)) or any(not n or "." in n for n in names):
            raise ValueError(tr("Nombres de variables vacíos, duplicados o con puntos"))
        for name, fields in self.types.items():
            if not name or name in PRIMITIVES or not isinstance(fields, dict) or not fields:
                raise ValueError(tr("Definición de tipo inválida: {name}", name=name))
            for field, kind in fields.items():
                if not field or "." in field or kind not in PRIMITIVES | self.types.keys():
                    raise ValueError(tr("Campo inválido: {name}.{field}", name=name, field=field))
            def check_type(kind, stack):
                if kind in stack:
                    raise ValueError(tr("Tipo recursivo: {kind}", kind=kind))
                if kind in self.types:
                    for child in self.types[kind].values():
                        check_type(child, stack + (kind,))
            check_type(name, ())
        tags = self.tags()
        from . import dynamics
        from .operation_windows import validate_popup_button, validate_popup_writes, validate_window, validate_display
        from .security import validate_element_permission
        from .operational_config import validate_operations
        try:
            validate_operations(self, tags)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(tr("Definición de operaciones inválida: {exc}", exc=exc)) from exc
        connections = {c["id"]: c for c in self.connections}
        if len(connections) != len(self.connections):
            raise ValueError(tr("Conexiones duplicadas"))
        from .connectors import REGISTRY, definition
        for connection in self.connections:
            if not isinstance(connection["id"], str) or not connection["id"].strip():
                raise ValueError(tr("Las conexiones necesitan un nombre"))
            if connection.get("protocol") not in REGISTRY:
                raise ValueError(tr("Protocolo desconocido: {get}", get=connection.get('protocol')))
            cycle = connection.get("poll_ms", 250)
            if isinstance(cycle, bool) or not isinstance(cycle, int) or not 50 <= cycle <= 60000:
                raise ValueError(tr("poll_ms debe estar entre 50 y 60000"))
            definition(connection["protocol"]).validate_connection(connection)
        for name, tag in tags.items():
            if not isinstance(tag.get("writable", False), bool):
                raise ValueError(tr("{name}: writable debe ser booleano", name=name))
            binding = tag.get("binding")
            if binding:
                if binding["connection"] not in connections:
                    raise ValueError(tr("{name}: conexión inexistente", name=name))
                if binding.get("version", 1) != definition(connections[binding["connection"]]["protocol"]).version:
                    raise ValueError(tr("{name}: versión de enlace no soportada", name=name))
                definition(connections[binding["connection"]]["protocol"]).validate_binding(
                    binding["address"], tag["type"], tag.get("writable", False))
        if not self.screens or self.manifest.get("startup_screen") not in self.screens:
            raise ValueError(tr("Pantalla inicial inexistente"))
        for name, document in {**self.screens, **{f'faceplate:{k}': v for k, v in self.faceplates.items()}}.items():
            for dimension in ("width", "height"):
                value = document.get(dimension)
                if isinstance(value,bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 10000:
                    raise ValueError(tr("{name}: dimensiones inválidas", name=name))
            from .operational_config import color, number
            dynamics.validate_color(document.get("background", "#ffffff"))
            number(document.get("grid_size", 10), 1, 200)
            if not isinstance(document.get("grid_size", 10), int):
                raise ValueError(tr("La cuadrícula necesita un tamaño entero"))
            for option in ("show_grid", "snap_to_grid"):
                if not isinstance(document.get(option, True), bool):
                    raise ValueError(tr("Opción de cuadrícula inválida"))
            if not isinstance(document.get("title", ""), str):
                raise ValueError(tr("Título de pantalla inválido"))
            ids = set()
            parameters = document.get("parameters", {}) if name.startswith("faceplate:") else {}
            if not isinstance(parameters,dict) or any(not isinstance(key,str) or not key.strip() or kind not in PRIMITIVES for key,kind in parameters.items()):
                raise ValueError(tr('Parámetros de objeto de librería inválidos'))
            for element in document["elements"]:
                if not isinstance(element["id"], str) or not element["id"].strip():
                    raise ValueError(tr("Los elementos necesitan un nombre"))
                if element["id"] in ids or element["kind"] not in KINDS:
                    raise ValueError(tr("{name}: elemento duplicado o desconocido", name=name))
                ids.add(element["id"])
                for key in ("x", "y", "w", "h"):
                    if isinstance(element[key],bool) or not isinstance(element[key], (float, int)) or not math.isfinite(element[key]) or abs(element[key]) > 10000:
                        raise ValueError(tr("{name}: geometría inválida", name=name))
                if element["w"] <= 0 or element["h"] <= 0:
                    raise ValueError(tr("{name}: tamaño inválido", name=name))
                if element.get("text_align", "center") not in {"left", "center", "right"} or not isinstance(element.get("bold",False),bool):
                    raise ValueError(tr("Formato de texto inválido"))
                try: dynamics.validate(element,tags,parameters)
                except (ValueError,TypeError,KeyError) as exc: raise ValueError(f'{name} / {element["id"]}: {exc}') from exc
                visual=element.get('dynamics',{})
                for style in [visual.get(key,{}) for key in ('default','bad','disabled')]+[state['style'] for state in visual.get('states',[])]:
                    if 'source' in style:self.asset(style['source'])
                validate_drawing(element)
                for key in ('text','unit','color','text_color','border_color'):
                    if key in element and not isinstance(element[key],str):
                        raise ValueError(tr("{key}: se esperaba texto", key=key))
                for color_key in ("stroke_color",):
                    if color_key in element:
                        dynamics.validate_color(element[color_key])
                tag = element.get("tag", "")
                if not isinstance(tag,str):raise ValueError(tr("{name} / {id}: la referencia de variable debe ser texto", name=name, id=element["id"]))
                if tag and tag not in tags and not (tag.startswith("$") and tag[1:] in parameters):
                    raise ValueError(tr("{name}: variable inexistente {tag}", name=name, tag=tag))
                tag_type = tags[tag]["type"] if tag in tags else parameters.get(tag.lstrip("$"))
                try: validate_element_permission(element)
                except ValueError as exc: raise ValueError(f'{name} / {element["id"]}: {exc}') from exc
                if element['kind'] == 'button':
                    action = element.get('action','toggle')
                    if action not in {'toggle','set','momentary','press_release','screen','popup','faceplate_popup','close_popup','script','set_language'}:
                        raise ValueError(tr('Acción de botón desconocida'))
                    if action == 'set_language' and element.get('language') not in self.manifest.get('languages', ['es']):
                        raise ValueError('Idioma de destino no declarado')
                    if action == 'faceplate_popup':
                        try: validate_popup_button(element, self, tags, parameters)
                        except (ValueError, TypeError) as exc: raise ValueError(f'{name} / {element["id"]}: {exc}') from exc
                    if action in {'popup','faceplate_popup'}:
                        validate_window(element.get('window', {}))
                        if not isinstance(element.get('modal', False), bool):
                            raise ValueError(tr("El modo modal debe ser booleano"))
                    if action in {'toggle','momentary'} and tag and tag_type != 'bool':
                        raise ValueError(tr('Alternar o pulsador momentáneo requiere una variable bool'))
                    if action=='press_release':
                        for key in ('press_value','release_value'):
                            if key not in element:raise ValueError(tr('Falta el valor al pulsar o soltar'))
                            if tag:coerce(element[key],tag_type)
                    if action == 'set':
                        if 'value' not in element:
                            raise ValueError(tr('El botón necesita un valor de escritura'))
                        if tag: coerce(element['value'],tag_type)
                if dynamics.writable_control(element) and tag in tags and not tags[tag].get('writable',False):
                    raise ValueError(tr("{name} / {id}: variable de solo lectura: {tag}", name=name, id=element["id"], tag=tag))
                if element["kind"] == "text_list":
                    validate_text_list(element, tag_type)
                if tag and element["kind"] == "lamp" and tag_type != "bool":
                    raise ValueError(tr("Un piloto requiere una variable bool"))
                if tag and element["kind"] == "bar" and tag_type not in {"int", "float"}:
                    raise ValueError(tr("Una barra requiere una variable numérica"))
                if element["kind"] == "bar" and element.get("max", 100) <= element.get("min", 0):
                    raise ValueError(tr("El máximo de una barra debe ser mayor que el mínimo"))
                if element["kind"] == "gauge":
                    if tag and tag_type not in {"int", "float"}:
                        raise ValueError(tr("Un indicador requiere una variable numérica"))
                    from .gauges import validate as validate_gauge
                    validate_gauge(element)
                if element["kind"] == "button" and element.get("action") in {"screen", "popup"} and element.get("screen") not in self.screens:
                    raise ValueError(tr("Pantalla de destino inexistente"))
                if element["kind"] == "button" and element.get("action") == "popup" and not isinstance(element.get("modal", False), bool):
                    raise ValueError(tr("El modo modal debe ser booleano"))
                if element["kind"] == "image":
                    self.asset(element.get("source", ""))
                if element["kind"] in {"trend", "alarm_view"}:
                    views = self.trends if element["kind"] == "trend" else self.alarm_views
                    if element.get("view") not in views:
                        raise ValueError(tr("Configuración del visor inexistente"))
                    if name.startswith("faceplate:"):
                        raise ValueError(tr("Los visores deben colocarse directamente en una pantalla"))
                    if element["w"] < 400 or element["h"] < 280:
                        raise ValueError(tr("El visor necesita al menos 400 × 280"))
                if not isinstance(element.get("font_size", 15), int) or not 8 <= element.get("font_size", 15) <= 72:
                    raise ValueError(tr("font_size debe ser un entero entre 8 y 72"))
                if element["kind"] in {"text", "input"} and (not isinstance(element.get("decimals", 2), int) or not 0 <= element.get("decimals", 2) <= 10):
                    raise ValueError(tr("decimals debe estar entre 0 y 10"))
                if element["kind"] == "faceplate":
                    template = self.faceplates.get(element.get("template"))
                    if template is None or name.startswith("faceplate:"):
                        raise ValueError(tr("Objeto de librería inexistente o anidado (no soportado en v1)"))
                    bindings = element.get("bindings", {})
                    if set(bindings) != set(template.get("parameters", {})):
                        raise ValueError(tr("Parámetros del objeto de librería incompletos"))
                    for parameter, kind in template["parameters"].items():
                        if bindings[parameter] not in tags or tags[bindings[parameter]]["type"] != kind:
                            raise ValueError(tr("Tipo incorrecto en parámetro {parameter}", parameter=parameter))

        for screen in self.screens:
            for element in self.elements(screen):
                tag=element.get('tag')
                if dynamics.writable_control(element) and tag in tags and not tags[tag].get('writable',False):
                    raise ValueError(tr("{screen} / {id}: variable de solo lectura: {tag}", screen=screen, id=element["id"], tag=tag))
                if element['kind'] == 'button' and element.get('action') == 'faceplate_popup':
                    try: validate_popup_writes(element, self, tags)
                    except ValueError as exc: raise ValueError(f'{screen} / {element["id"]}: {exc}') from exc
        validate_display(self)
        from .security import validate_security
        validate_security(self.security)
        from .opcua_server import validate_server
        validate_server(self.opcua_server)
        from .screen_layouts import validate_layouts
        validate_layouts(self)
        from .screen_tree import validate_folders
        validate_folders(self)
        from .project_settings import validate_settings
        validate_settings(self)
        from .scripting import validate_scripts
        validate_scripts(self)

    def set_binding(self, name, binding):
        """Configure one primitive leaf, including a field within a structure."""
        if name not in self.tags():
            raise ValueError(tr("Variable inexistente: {name}", name=name))
        root_name, separator, relative = name.partition(".")
        source = next(v for v in self.variables if v["name"] == root_name)
        if separator:
            bindings = source.setdefault("bindings", {})
            if binding:
                bindings[name] = copy.deepcopy(binding)
            else:
                bindings.pop(name, None)
                if not bindings:
                    source.pop("bindings", None)
        elif binding:
            source["binding"] = copy.deepcopy(binding)
        else:
            source.pop("binding", None)

    def configure_tag(self, name, initial, writable, binding):
        tag = self.tags()[name]
        initial = coerce(initial, tag["type"])
        root_name, separator, relative = name.partition(".")
        source = next(v for v in self.variables if v["name"] == root_name)
        if separator:
            parts = relative.split(".")
            target = source["initial"]
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = initial
            source.setdefault("overrides", {})[relative] = {"writable": writable}
        else:
            source.update(initial=initial, writable=writable)
        self.set_binding(name, binding)

    def save(self):
        self.validate()
        from .project_storage import save_project
        save_project(self)

    def asset(self, relative):
        if relative.startswith('library://'):
            from .faceplate_libraries import asset
            return asset(self, relative)
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(tr("La imagen debe estar dentro del proyecto"))
        return path

    def elements(self, screen):
        """Resolve faceplate parameter references into ordinary graphical elements."""
        return self.expand(self.screens[screen]["elements"])

    def expand(self, elements):
        """Expand a list of document elements; also used for faceplate pop-up windows."""
        from .operation_windows import resolve_popup_bindings
        for element in elements:
            if element["kind"] != "faceplate":
                yield copy.deepcopy(element)
                continue
            template = self.faceplates[element["template"]]
            sx, sy = element["w"] / template["width"], element["h"] / template["height"]
            if "background" in template:
                yield dict(id=element["id"]+".$background",kind="rectangle",x=element["x"],y=element["y"],
                    w=element["w"],h=element["h"],color=template["background"],stroke_color=template["background"],stroke_width=1,filled=True,dynamics=copy.deepcopy(element.get("dynamics",{})),visible=element.get("visible",True))
            for child in template["elements"]:
                from .dynamics import resolve_bindings
                child = resolve_bindings(child,element['bindings'])
                child['_guards']=[element.get('dynamics',{})]
                if element.get('visible') is False: child['visible']=False
                child["id"] = element["id"] + "." + child["id"]
                child["x"] = element["x"] + child["x"] * sx
                child["y"] = element["y"] + child["y"] * sy
                child["w"] *= sx
                child["h"] *= sy
                if child.get("tag", "").startswith("$"):
                    child["tag"] = element["bindings"][child["tag"][1:]]
                yield resolve_popup_bindings(child, element["bindings"])
