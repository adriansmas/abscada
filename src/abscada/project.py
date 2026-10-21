"""Versioned, editable project documents. No GUI dependencies."""
from __future__ import annotations

import copy
import functools
import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from dataclasses import dataclass, field
from .i18n import tr
from . import button_actions
from . import structures

PRIMITIVES = {"bool", "int", "float", "string"}
from .text_lists import validate_text_list
from .drawing import PATH_KINDS, SHAPE_KINDS, validate_drawing
from .security import default_security
from .opcua_server import default_server

MAX_NESTING = 8
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


_INDEXED_TEXT = re.compile(r"[\w$\]]\[")


@functools.lru_cache(maxsize=4096)
def _inside(root, relative):
    """Resolved path of an image of the project (asked at every validation and repaint)."""
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root)):
        raise ValueError(tr("La imagen debe estar dentro del proyecto"))
    return path


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
        """Expand structured variables into typed leaf tags.

        Linear in the number of leaves: each leaf copies only the variable's own settings,
        never its whole ``initial`` value, ``bindings`` or ``overrides``."""
        result = {}
        for variable in self.variables:
            base = {key: value for key, value in variable.items() if key not in ("initial", "bindings", "overrides")}
            overrides = variable.get("overrides", {})
            bindings = variable.get("bindings", {})
            self._expand(result, variable["name"], variable["type"], variable["initial"], base, overrides, bindings, ())
        return result

    def _expand(self, result, name, kind, value, base, overrides, bindings, stack):
        if kind in PRIMITIVES:
            tag = dict(base)
            override = overrides.get(structures.relative(name), {})
            if set(override) - {"writable"}:
                raise ValueError(tr("{name}: override solo admite writable", name=name))
            tag.update(override)
            tag.update(name=name, type=kind, initial=coerce(value, kind))
            binding = bindings.get(name) or base.get("binding")
            if binding:
                tag["binding"] = copy.deepcopy(binding)
            result[name] = tag
            return
        item, length = structures.split_kind(kind)
        if length is not None:
            if not structures.known(kind, self.types):
                raise ValueError(tr("Tipo inválido o recursivo: {kind}", kind=kind))
            if not isinstance(value, list) or len(value) != length:
                raise ValueError(tr("{name}: el valor de un array debe ser una lista de {length} elementos", name=name, length=length))
            for index, element in zip(structures.indices(kind), value):
                self._expand(result, f"{name}[{index}]", item, element, base, overrides, bindings, stack)
            return
        if kind in stack or kind not in self.types:
            raise ValueError(tr("Tipo inválido o recursivo: {kind}", kind=kind))
        if not isinstance(value, dict):
            raise ValueError(tr("{name}: el valor de una estructura debe ser un objeto", name=name))
        fields = self.types[kind]
        if set(value) != set(fields):
            raise ValueError(tr("{name}: los campos no coinciden con el tipo {kind}", name=name, kind=kind))
        for field, field_type in fields.items():
            self._expand(result, f"{name}.{field}", field_type, value[field], base, overrides, bindings, stack + (kind,))

    def validate(self):
        from .project_languages import validate, validate_codes, resolved_project, default_language
        from .faceplate_libraries import validate_links
        validate_codes(self)   # linked libraries are translated into these languages
        validate_links(self)
        validate(self)
        resolved_project(self, default_language(self))._validate()

    def validate_screen(self, screen):
        """Quick check after a change inside one screen and nowhere else (Studio, while
        drawing): the same checks as ``validate`` for that screen and for what depends on
        screens. ``validate`` still runs in full before saving and before operating."""
        from .project_languages import validate, resolved_project, default_language
        validate(self, only=("screens", screen))
        resolved_project(self, default_language(self), only=screen)._validate(only=screen)

    def _validate(self, only=None):
        from .validation import filenames
        for collection in (self.screens, self.faceplates, self.scripts):
            filenames(collection)
        if not isinstance(self.manifest.get("name"), str) or not self.manifest["name"]:
            raise ValueError(tr("El proyecto necesita un nombre"))
        names = [v["name"] for v in self.variables]
        if len(names) != len(set(names)) or any(not structures.valid_name(n) for n in names):
            raise ValueError(tr("Nombres de variables vacíos, duplicados o con puntos"))
        structures.check_definitions(self.types)
        tags = self.tags()
        for variable in ([] if only else self.variables):
            name = variable["name"]
            if variable["type"] not in PRIMITIVES and variable.get("binding"):
                raise ValueError(tr("{name}: una variable estructurada se enlaza campo a campo, no entera", name=name))
            # Links and overrides of fields that no longer exist would come back with an old
            # address if a field with that name were created again.
            orphans = [key for key in variable.get("bindings", {}) if key not in tags or structures.root(key) != name]
            orphans += [key for key in variable.get("overrides", {}) if structures.join(name, key) not in tags]
            if orphans:
                raise ValueError(tr("{name}: enlaces o ajustes de campos inexistentes: {fields}", name=name, fields=", ".join(orphans)))
        roots = {v["name"]: v["type"] for v in self.variables}
        from . import dynamics
        from .operation_windows import validate_popup_button, validate_popup_writes, validate_window, validate_display
        from .security import validate_element_permission
        from .operational_config import validate_operations
        try:
            if not only:
                validate_operations(self, tags)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(tr("Definición de operaciones inválida: {exc}", exc=exc)) from exc
        connections = {c["id"]: c for c in self.connections}
        if len(connections) != len(self.connections):
            raise ValueError(tr("Conexiones duplicadas"))
        from .connectors import REGISTRY, definition
        for connection in ([] if only else self.connections):
            if not isinstance(connection["id"], str) or not connection["id"].strip():
                raise ValueError(tr("Las conexiones necesitan un nombre"))
            if connection.get("protocol") not in REGISTRY:
                raise ValueError(tr("Protocolo desconocido: {get}", get=connection.get('protocol')))
            cycle = connection.get("poll_ms", 250)
            if isinstance(cycle, bool) or not isinstance(cycle, int) or not 50 <= cycle <= 60000:
                raise ValueError(tr("poll_ms debe estar entre 50 y 60000"))
            definition(connection["protocol"]).validate_connection(connection)
        for name, tag in ({} if only else tags).items():
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
        documents = {only: self.screens[only]} if only else {**self.screens, **{f'faceplate:{k}': v for k, v in self.faceplates.items()}}
        for name, document in documents.items():
            for dimension in ("width", "height"):
                value = document.get(dimension)
                if isinstance(value,bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 10000:
                    raise ValueError(tr("{name}: dimensiones inválidas", name=name))
            from .operational_config import number
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
            if not isinstance(parameters,dict) or any(not structures.valid_name(key) or not key.strip() or not isinstance(kind,str) or not structures.known(kind,self.types) for key,kind in parameters.items()):
                raise ValueError(tr('Parámetros de objeto de librería inválidos'))
            # $name, $name.field and $name[i]: primitive ones can feed elements, any one a nested object.
            references = structures.parameter_references(parameters, self.types)
            values = {key: kind for key, kind in references.items() if kind in PRIMITIVES}
            for element in document["elements"]:
                element = self._concrete(name, element, tags, roots, parameters, values)
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
                try: dynamics.validate(element,tags,values)
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
                if tag and tag not in tags and not (tag.startswith("$") and tag[1:] in values):
                    raise ValueError(tr("{name}: variable inexistente {tag}", name=name, tag=tag))
                tag_type = tags[tag]["type"] if tag in tags else values.get(tag.lstrip("$"))
                try: validate_element_permission(element)
                except ValueError as exc: raise ValueError(f'{name} / {element["id"]}: {exc}') from exc
                if element['kind'] == 'button' and element.get('action') == button_actions.SEQUENCE:
                    try: button_actions.validate_structure(element)
                    except ValueError as exc: raise ValueError(f'{name} / {element["id"]}: {exc}') from exc
                    for number, step in enumerate(element['actions'], 1):
                        try: self._validate_button_action(name, button_actions.as_button(element, step), tags, references)
                        except ValueError as exc:
                            raise ValueError(tr("{name} / {id}, acción {number}: {exc}", name=name, id=element["id"], number=number, exc=exc)) from exc
                elif element['kind'] == 'button':
                    self._validate_button_action(name, element, tags, references)
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
                    if template is None:
                        raise ValueError(tr("Objeto de librería inexistente: {template}", template=element.get("template")))
                    bindings = element.get("bindings", {})
                    if not isinstance(bindings, dict) or set(bindings) != set(template.get("parameters", {})):
                        raise ValueError(tr("Parámetros del objeto de librería incompletos"))
                    for parameter, kind in template["parameters"].items():
                        if not self.binding_fits(bindings[parameter], kind, roots, references):
                            raise ValueError(tr("Tipo incorrecto en parámetro {parameter}", parameter=parameter))
        if not only:
            self._check_nesting()

        for screen in [only] if only else self.screens:
            for expanded in self.elements(screen):
                expanded = self._concrete(screen, expanded, tags, roots, {}, {})
                for element in [expanded] + [button_actions.as_button(expanded, step) for step in button_actions.steps(expanded)]:
                    tag=element.get('tag')
                    if dynamics.writable_control(element) and tag in tags and not tags[tag].get('writable',False):
                        raise ValueError(tr("{screen} / {id}: variable de solo lectura: {tag}", screen=screen, id=element["id"], tag=tag))
                    if element['kind'] == 'button' and element.get('action') == 'faceplate_popup':
                        for variant in [element] + element.get('variants', []):
                            try: validate_popup_writes(dict(element, template=variant['template'], bindings=variant.get('bindings', {})), self, tags)
                            except ValueError as exc: raise ValueError(f'{screen} / {element["id"]}: {exc}') from exc
        validate_display(self)
        if not only:
            from .security import validate_security
            validate_security(self.security)
            from .opcua_server import validate_server
            validate_server(self.opcua_server)
        from .screen_layouts import validate_layouts
        validate_layouts(self)
        from .screen_tree import validate_folders
        validate_folders(self)
        if not only:
            from .project_settings import validate_settings
            validate_settings(self)
        from .scripting import validate_scripts
        validate_scripts(self)

    def binding_fits(self, source, kind, roots, references=None):
        """A faceplate parameter of ``kind`` can take ``source``.

        ``source`` is a variable path (a leaf, a whole structure or array, or a part of
        one), ``$parameter...`` of the faceplate that contains the instance, or "" for a
        parameter not assigned yet: the object can be placed first and linked later.
        """
        if not isinstance(source, str):
            return False
        if source == "":
            return True
        if source.startswith("$"):
            actual = (references or {}).get(source[1:])
        else:
            actual = structures.path_kind(self.types, roots, source)
        return structures.compatible(self.types, actual, kind)

    def _concrete(self, name, element, tags, roots, parameters, values):
        """The element with each variable index replaced by the first index (``A[Sel]`` → ``A[0]``).

        The index must be an integer variable or, inside an object, an integer ``$parameter``;
        every other check then runs on the sample path.
        """
        from .variable_references import _element_slots
        # Most elements hold no indexed path at all: a name followed by «[» can only appear
        # inside a string, so the serialised element tells it without walking it.
        try:
            if not _INDEXED_TEXT.search(json.dumps(element, ensure_ascii=False)):
                return element
        except (TypeError, ValueError):
            pass
        slots = [(container, key) for container, key in _element_slots(element)
                 if structures.index_tags(container[key])]
        if not slots:
            return element
        element = copy.deepcopy(element)
        everything = {**roots, **{"$" + key: kind for key, kind in parameters.items()}}
        for container, key in _element_slots(element):
            path = container[key]
            indices = structures.index_tags(path)
            if not indices:
                continue
            for index in indices:
                kind = values.get(index[1:]) if index.startswith("$") else tags.get(index, {}).get("type")
                if kind != "int":
                    raise ValueError(tr("{name} / {id}: el índice «{index}» de {path} debe ser una variable entera",
                                        name=name, id=element.get("id", ""), index=index, path=path))
            sample = structures.sample_path(self.types, everything, path)
            if sample is None:
                raise ValueError(tr("{name} / {id}: ruta con índice variable inválida: {path}", name=name, id=element.get("id", ""), path=path))
            container[key] = sample
        return element

    def _check_nesting(self):
        """Objects may contain other objects, without cycles and at most MAX_NESTING levels deep."""
        def visit(name, stack):
            if name in stack:
                raise ValueError(tr("Objetos de librería anidados en ciclo: {path}", path=" → ".join(stack + (name,))))
            if len(stack) >= MAX_NESTING:
                raise ValueError(tr("Demasiados niveles de objetos anidados (máximo {count})", count=MAX_NESTING))
            for element in self.faceplates.get(name, {}).get("elements", []):
                if element.get("kind") == "faceplate":
                    visit(element.get("template"), stack + (name,))
        for name in self.faceplates:
            visit(name, ())

    def _validate_button_action(self, name, element, tags, parameters):
        """One action: a single-action button or one step of a list (seen as a button).

        ``parameters`` are the references of the containing faceplate (see
        ``structures.parameter_references``).
        """
        from . import dynamics
        from .operation_windows import validate_popup_button, validate_window
        references, parameters = parameters, {key: kind for key, kind in parameters.items() if kind in PRIMITIVES}
        tag = element.get("tag", "")
        if not isinstance(tag, str):
            raise ValueError(tr("{name} / {id}: la referencia de variable debe ser texto", name=name, id=element["id"]))
        if tag and tag not in tags and not (tag.startswith("$") and tag[1:] in parameters):
            raise ValueError(tr("{name}: variable inexistente {tag}", name=name, tag=tag))
        tag_type = tags[tag]["type"] if tag in tags else parameters.get(tag.lstrip("$"))
        action = element.get('action','toggle')
        if action not in {'toggle','set','momentary','press_release','screen','popup','faceplate_popup','close_popup','script','set_language'}:
            raise ValueError(tr('Acción de botón desconocida'))
        if action == 'set_language' and element.get('language') not in self.manifest.get('languages', ['es']):
            raise ValueError('Idioma de destino no declarado')
        if action == 'faceplate_popup':
            try: validate_popup_button(element, self, tags, references)
            except (ValueError, TypeError) as exc: raise ValueError(f'{name} / {element["id"]}: {exc}') from exc
            self._validate_variants(name, element, tags, references)
        elif 'variants' in element:
            raise ValueError(tr("{name} / {id}: solo «Abrir objeto en ventana» admite alternativas", name=name, id=element["id"]))
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
        if action in {"screen", "popup"} and element.get("screen") not in self.screens:
            raise ValueError(tr("Pantalla de destino inexistente"))
        if dynamics.writable_control(element) and tag in tags and not tags[tag].get('writable',False):
            raise ValueError(tr("{name} / {id}: variable de solo lectura: {tag}", name=name, id=element["id"], tag=tag))

    def _validate_variants(self, name, element, tags, references):
        """Alternatives of a faceplate pop-up: the first whose condition holds is opened."""
        from . import dynamics
        from .operation_windows import validate_popup_button
        variants = element.get("variants", [])
        if not isinstance(variants, list) or len(variants) > button_actions.MAX_VARIANTS:
            raise ValueError(tr("{name} / {id}: como máximo {count} alternativas", name=name, id=element["id"], count=button_actions.MAX_VARIANTS))
        values = {key: kind for key, kind in references.items() if kind in PRIMITIVES}
        for number, variant in enumerate(variants, 1):
            try:
                if not isinstance(variant, dict) or not {"when", "template"} <= set(variant) <= button_actions.VARIANT_KEYS:
                    raise ValueError(tr("necesita condición y objeto"))
                dynamics.validate(dict(id=element["id"], kind="rectangle", dynamics={"visible": variant["when"]}), tags, values)
                validate_popup_button(dict(element, template=variant["template"], bindings=variant.get("bindings", {}),
                                           title=variant.get("title", "")), self, tags, references)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(tr("{name} / {id}, alternativa {number}: {exc}", name=name, id=element["id"], number=number, exc=exc)) from exc

    def set_binding(self, name, binding):
        """Configure one primitive leaf, including a field within a structure."""
        if name not in self.tags():
            raise ValueError(tr("Variable inexistente: {name}", name=name))
        source = next(v for v in self.variables if v["name"] == structures.root(name))
        if structures.relative(name):
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
        source = next(v for v in self.variables if v["name"] == structures.root(name))
        relative = structures.relative(name)
        if relative:
            structures.set_at(self.types, source["type"], source["initial"], structures.steps(name), initial)
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
        return _inside(str(self.root), relative)

    def elements(self, screen):
        """Resolve faceplate parameter references into ordinary graphical elements."""
        return self.expand(self.screens[screen]["elements"])

    def expand(self, elements):
        """Expand a list of document elements; also used for faceplate pop-up windows.

        Objects placed inside an object are expanded in turn: their bindings may
        forward the outer object's parameters (``$motor``, ``$motor.marcha``).
        """
        from .operation_windows import resolve_popup_bindings
        from .dynamics import resolve_bindings
        for element in elements:
            if element["kind"] != "faceplate":
                yield copy.deepcopy(element)
                continue
            template = self.faceplates[element["template"]]
            sx, sy = element["w"] / template["width"], element["h"] / template["height"]
            outer = copy.deepcopy(element.get("_guards", []))
            if "background" in template:
                background = dict(id=element["id"]+".$background",kind="rectangle",x=element["x"],y=element["y"],
                    w=element["w"],h=element["h"],color=template["background"],stroke_color=template["background"],stroke_width=1,filled=True,dynamics=copy.deepcopy(element.get("dynamics",{})),visible=element.get("visible",True))
                if outer:
                    background["_guards"] = outer
                yield background
            for child in template["elements"]:
                child = resolve_bindings(child,element['bindings'])
                child['_guards']=outer+[element.get('dynamics',{})]
                if element.get('visible') is False: child['visible']=False
                child["id"] = element["id"] + "." + child["id"]
                child["x"] = element["x"] + child["x"] * sx
                child["y"] = element["y"] + child["y"] * sy
                child["w"] *= sx
                child["h"] *= sy
                if child["kind"] == "faceplate":
                    child["bindings"] = {key: structures.substitute(value, element["bindings"])
                                         for key, value in child.get("bindings", {}).items()}
                    yield from self.expand([child])
                    continue
                yield resolve_popup_bindings(child, element["bindings"])
