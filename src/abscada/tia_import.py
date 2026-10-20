"""Import a Siemens DB from the source text TIA Portal generates. No Qt.

In TIA Portal, «Generate source from blocks» (with the blocks it depends on) writes the
UDTs (``TYPE … END_TYPE``) and the DB (``DATA_BLOCK … END_DATA_BLOCK``) as text. That
text is pasted here and becomes:

- one data type per UDT and per anonymous ``Struct``;
- one structured variable per DB, named after it, so paths stay as in TIA
  (``DB_Valvulas.V101.Abierta``; ``Array[1..10]`` keeps its indices);
- initial values from the declarations and the ``BEGIN`` section;
- S7 addresses for every field, computed with the layout of a standard
  (non-optimized) DB: bools packed bit by bit, bytes on the next byte, anything
  larger, every structure and every array on an even byte, and structures and
  arrays taking an even number of bytes.

Optimized DBs have no absolute addresses: their structure is imported without links.
Data types abSCADA cannot read yet (LReal, String…) still take their room in the
layout, so the following fields keep their right address, but they are left out.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from .i18n import tr
from . import structures

# PLC type → (size in bytes, 0 for a bit; abSCADA type or None; S7 access or None)
ELEMENTARY = {
    "bool": (0, "bool", "X"),
    "byte": (1, "int", "B"), "usint": (1, "int", "B"),
    "sint": (1, None, None), "char": (1, None, None),
    "int": (2, "int", "W"), "word": (2, "int", "W"), "uint": (2, "int", "W"),
    "dint": (4, "int", "D"), "dword": (4, "int", "D"), "udint": (4, "int", "D"), "time": (4, "int", "D"),
    "real": (4, "float", "D"),
    "wchar": (2, None, None), "date": (2, None, None), "s5time": (2, None, None),
    "time_of_day": (4, None, None), "tod": (4, None, None),
    "lreal": (8, None, None), "lint": (8, None, None), "ulint": (8, None, None), "lword": (8, None, None),
    "ltime": (8, None, None), "ltod": (8, None, None), "ldt": (8, None, None),
    "date_and_time": (8, None, None), "dt": (8, None, None), "dtl": (12, None, None),
}
# Read through a signed S7 access: values above the signed range come out negative.
SIGNED_READ = {"word", "uint", "dword", "udint"}
HEADER = {"title", "author", "family", "name", "version"}


@dataclass
class Type:
    kind: str                      # "elementary", "string", "struct", "udt", "array"
    plc: str = ""                  # elementary or UDT name as written in TIA
    length: int = 0                # characters of a String / WString
    members: list = field(default_factory=list)   # [(name, Type, init)] of a struct
    dims: list = field(default_factory=list)      # [(low, high)] of an array
    of: "Type | None" = None       # element of an array


@dataclass
class Plan:
    """What an import will create; ``rows`` feed the preview."""
    types: dict = field(default_factory=dict)
    variable: dict | None = None
    rows: list = field(default_factory=list)      # (path, PLC type, abSCADA type, address, initial)
    warnings: list = field(default_factory=list)
    db_name: str = ""
    optimized: bool = False


# --- source text ----------------------------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<space>[ \t\r\f\v]+) | (?P<newline>\n) |
    (?P<comment>//[^\n]* | \(\*.*?\*\)) |
    (?P<attr>\{.*?\}) |
    (?P<name>"[^"]*") | (?P<text>'[^']*') |
    (?P<typed>[A-Za-z_]\w*\#[^\s;,\]\)]+ | \d+\#[0-9A-Fa-f_]+) |
    (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?) |
    (?P<assign>:=) | (?P<range>\.\.) |
    (?P<ident>[A-Za-z_]\w*) |
    (?P<symbol>[:;\[\],()=.+\-*/<>])
""", re.VERBOSE | re.DOTALL)


@dataclass
class Token:
    kind: str
    text: str
    line: int


def tokenize(text):
    tokens, line, position = [], 1, 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            raise ValueError(tr("Línea {line}: carácter inesperado «{char}»", line=line, char=text[position]))
        kind, value = match.lastgroup, match[0]
        if kind == "name":
            value = value[1:-1]
        if kind not in {"space", "newline", "comment"}:
            tokens.append(Token(kind, value, line))
        line += match[0].count("\n")
        position = match.end()
    return tokens


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.index = 0
        self.udts = {}       # name → struct Type
        self.blocks = []     # (name, Type, assignments, optimized)

    # tokens
    def peek(self, offset=0):
        index = self.index + offset
        return self.tokens[index] if index < len(self.tokens) else Token("end", "", self.tokens[-1].line if self.tokens else 1)

    def take(self):
        token = self.peek()
        self.index += 1
        return token

    def word(self, offset=0):
        token = self.peek(offset)
        return token.text.casefold() if token.kind == "ident" else None

    def expect(self, text):
        token = self.take()
        if token.text.casefold() != text.casefold():
            raise ValueError(tr("Línea {line}: se esperaba «{expected}» y hay «{found}»", line=token.line, expected=text, found=token.text or tr("fin del texto")))
        return token

    def skip(self, text):
        if self.peek().text.casefold() == text.casefold():
            self.index += 1
            return True
        return False

    def identifier(self):
        token = self.take()
        if token.kind not in {"ident", "name"}:
            raise ValueError(tr("Línea {line}: se esperaba un nombre y hay «{found}»", line=token.line, found=token.text or tr("fin del texto")))
        return token.text

    # blocks
    def parse(self):
        while self.peek().kind != "end":
            word = self.word()
            if word == "type":
                self.take(); self.parse_type()
            elif word == "data_block":
                self.take(); self.parse_block()
            elif word in {"function_block", "function", "organization_block"}:
                raise ValueError(tr("Línea {line}: solo se importan tipos (TYPE) y bloques de datos (DATA_BLOCK)", line=self.peek().line))
            else:
                token = self.peek()
                raise ValueError(tr("Línea {line}: se esperaba TYPE o DATA_BLOCK y hay «{found}»", line=token.line, found=token.text))
        return self

    def header(self):
        """Skip block attributes and TITLE/VERSION/… lines; True if the DB is optimized."""
        optimized = False
        while True:
            token = self.peek()
            if token.kind == "attr":
                optimized |= bool(re.search(r"S7_Optimized_Access\s*:=\s*'TRUE'", token.text, re.IGNORECASE))
                self.take()
            elif token.kind == "ident" and token.text.casefold() in HEADER:
                line = token.line
                while self.peek().kind != "end" and self.peek().line == line:
                    self.take()
            elif token.kind == "ident" and token.text.casefold() in {"non_retain", "retain", "unlinked", "read_only", "know_how_protect"}:
                self.take()
            else:
                return optimized

    def parse_type(self):
        name = self.identifier()
        self.header()
        self.expect("STRUCT")
        self.udts[name] = self.struct_body()
        self.skip(";")
        self.expect("END_TYPE")

    def parse_block(self):
        name = self.identifier()
        optimized = self.header()
        if self.word() == "struct":
            self.take()
            body = self.struct_body()
            self.skip(";")
        else:
            body = Type("udt", plc=self.identifier())
            self.skip(";")
        assignments = []
        if self.skip("BEGIN"):
            while self.word() != "end_data_block":
                if self.peek().kind == "end":
                    self.expect("END_DATA_BLOCK")
                assignments.append(self.assignment())
        self.expect("END_DATA_BLOCK")
        self.blocks.append((name, body, assignments, optimized))

    def struct_body(self):
        members = []
        while self.word() != "end_struct":
            if self.peek().kind == "end":
                self.expect("END_STRUCT")
            name = self.identifier()
            while self.peek().kind == "attr":
                self.take()
            self.expect(":")
            kind = self.datatype()
            init = self.initial() if self.skip(":=") else None
            self.expect(";")
            members.append((name, kind, init))
        self.take()
        return Type("struct", members=members)

    def datatype(self):
        token = self.take()
        if token.kind == "name":
            return Type("udt", plc=token.text)
        word = token.text.casefold() if token.kind == "ident" else None
        if word == "struct":
            result = self.struct_body()
            return result
        if word == "array":
            self.expect("[")
            dims = []
            while True:
                low = self.integer(); self.expect(".."); high = self.integer()
                if high < low:
                    raise ValueError(tr("Línea {line}: rango de array inválido", line=token.line))
                dims.append((low, high))
                if not self.skip(","):
                    break
            self.expect("]"); self.expect("of")
            return Type("array", dims=dims, of=self.datatype())
        if word in {"string", "wstring"}:
            length = 254
            if self.skip("["):
                length = self.integer(); self.expect("]")
            return Type("string", plc=token.text, length=length)
        if word in ELEMENTARY:
            return Type("elementary", plc=token.text)
        raise ValueError(tr("Línea {line}: tipo de dato desconocido «{kind}»", line=token.line, kind=token.text))

    def integer(self):
        sign = -1 if self.skip("-") else 1
        token = self.take()
        if token.kind != "number" or not token.text.isdigit():
            raise ValueError(tr("Línea {line}: se esperaba un número entero", line=token.line))
        return sign * int(token.text)

    def literal(self):
        """One value as text: ``TRUE``, ``-3``, ``1.5E3``, ``16#FF``, ``T#5s``…"""
        sign = "-" if self.skip("-") else ""
        token = self.take()
        if token.kind not in {"number", "typed", "ident", "text"}:
            raise ValueError(tr("Línea {line}: valor inicial no reconocido", line=token.line))
        return sign + token.text

    def initial(self):
        """A value, or the list of an array: ``[1, 2, 3(0)]`` (3(0) repeats 0 three times)."""
        if not self.skip("["):
            return self.literal()
        values = []
        while not self.skip("]"):
            if self.peek().kind == "number" and self.peek(1).text == "(":
                count = int(self.take().text); self.take()
                value = self.literal(); self.expect(")")
                values.extend([value] * count)
            else:
                values.append(self.literal())
            self.skip(",")
        return values

    def assignment(self):
        parts = []
        while not self.skip(":="):
            token = self.take()
            if token.kind == "end" or token.text == ";":
                raise ValueError(tr("Línea {line}: asignación inválida en BEGIN", line=token.line))
            parts.append(token)
        path = ""
        for token in parts:
            if token.text == ",":
                path += "]["
            else:
                path += token.text
        value = self.initial()
        self.expect(";")
        return path, value


# --- layout ---------------------------------------------------------------------------------

class Cursor:
    def __init__(self):
        self.byte, self.bit = 0, 0

    def to_byte(self):
        if self.bit:
            self.byte, self.bit = self.byte + 1, 0

    def to_word(self):
        self.to_byte()
        self.byte += self.byte % 2


def elements(dims):
    """Every index of a (multi-dimensional) array in memory order, as paths ``[i][j]``."""
    result = [""]
    for low, high in dims:
        result = [prefix + f"[{i}]" for prefix in result for i in range(low, high + 1)]
    return result


def place(kind, cursor, path, udts, out):
    """Lay out ``kind`` at ``cursor``; ``out`` gets (path, PLC type, byte, bit) per elementary value."""
    if kind.kind == "elementary":
        size = ELEMENTARY[kind.plc.casefold()][0]
        if size == 0:
            out.append((path, kind.plc, cursor.byte, cursor.bit))
            cursor.bit += 1
            if cursor.bit == 8:
                cursor.byte, cursor.bit = cursor.byte + 1, 0
            return
        cursor.to_byte() if size == 1 else cursor.to_word()
        out.append((path, kind.plc, cursor.byte, 0))
        cursor.byte += size
    elif kind.kind == "string":
        cursor.to_word()
        out.append((path, f"{kind.plc}[{kind.length}]", cursor.byte, 0))
        cursor.byte += kind.length + 2 if kind.plc.casefold() == "string" else 2 * kind.length + 4
    elif kind.kind in {"struct", "udt"}:
        body = resolve(kind, udts)
        cursor.to_word()
        for name, member, _ in body.members:
            place(member, cursor, structures.join(path, clean_name(name)), udts, out)
        cursor.to_word()
    else:
        cursor.to_word()
        for index in elements(kind.dims):
            place(kind.of, cursor, path + index, udts, out)
        cursor.to_word()


def resolve(kind, udts):
    if kind.kind == "udt":
        if kind.plc not in udts:
            raise ValueError(tr("Falta el tipo «{name}» en el texto pegado: genera la fuente incluyendo los bloques dependientes", name=kind.plc))
        return udts[kind.plc]
    return kind


# --- conversion -----------------------------------------------------------------------------

def clean_name(name):
    """A TIA name as an abSCADA name: no dots, brackets or spaces at the ends."""
    result = re.sub(r"[.\[\]]", "_", name.strip())
    return result or "_"


def value(literal, kind, plc):
    """A TIA literal as an abSCADA value of ``kind``; None if it cannot be read."""
    text = literal.strip()
    upper = text.upper()
    if "#" in upper and not re.match(r"-?\d+#", upper):
        prefix, _, rest = upper.partition("#")
        prefix = prefix.lstrip("-")
        if prefix in {"T", "TIME"}:
            return _milliseconds(rest, upper.startswith("-")) if kind == "int" else None
        text = ("-" if upper.startswith("-") else "") + rest     # INT#5, REAL#1.5, BOOL#TRUE
        upper = text.upper()
    try:
        if kind == "bool":
            if upper in {"TRUE", "1"}:
                return True
            if upper in {"FALSE", "0"}:
                return False
            return None
        if kind == "int":
            radix = re.fullmatch(r"(-?)(\d+)#([0-9A-F_]+)", upper)
            if radix:
                return int(radix[1] + radix[3].replace("_", ""), int(radix[2]))
            if upper in {"TRUE", "FALSE"}:
                return int(upper == "TRUE")
            return int(text)
        if kind == "float":
            return float(text)
    except ValueError:
        return None
    return None


def _milliseconds(text, negative):
    parts = re.findall(r"(\d+(?:\.\d+)?)(MS|D|H|M|S)", text.replace("_", ""))
    if not parts or "".join(a + b for a, b in parts) != text.replace("_", ""):
        return None
    scale = {"D": 86400000, "H": 3600000, "M": 60000, "S": 1000, "MS": 1}
    total = round(sum(float(amount) * scale[unit] for amount, unit in parts))
    return -total if negative else total


class Converter:
    def __init__(self, project, parser, replace):
        self.project, self.parser, self.replace = project, parser, replace
        self.types = {}                # new types for the project
        self.udts = {}                 # UDT name → abSCADA kind (None if nothing readable)
        self.omitted = []              # paths left out
        self.warnings = []

    def existing(self, name):
        return self.types.get(name, self.project.types.get(name))

    def add_type(self, name, fields):
        current = self.existing(name)
        if current is not None and current != fields and not self.replace:
            raise ValueError(tr("Ya existe el tipo «{name}» con otros campos; marca «Sustituir» para actualizarlo", name=name))
        self.types[name] = fields
        return name

    def kind_of(self, kind, owner, path):
        """abSCADA kind of a TIA type, creating the data types it needs; None if not readable."""
        if kind.kind == "elementary":
            scada = ELEMENTARY[kind.plc.casefold()][1]
            if scada is None:
                self.omitted.append((path, kind.plc))
            return scada
        if kind.kind == "string":
            self.omitted.append((path, f"{kind.plc}[{kind.length}]"))
            return None
        if kind.kind == "array":
            base = self.kind_of(kind.of, owner, path + "[]")
            if base is None:
                return None
            for low, high in reversed(kind.dims):
                base += f"[{high + 1}]" if low == 0 else f"[{low}..{high}]"
                if not structures.known(base, {**self.project.types, **self.types}):
                    raise ValueError(tr("{path}: array demasiado grande (máximo {count} elementos)", path=path, count=structures.MAX_LENGTH))
            return base
        # Every instance of a UDT shares one data type, named after it.
        if kind.kind == "udt" and kind.plc in self.udts:
            return self.udts[kind.plc]
        name = clean_name(kind.plc) if kind.kind == "udt" else clean_name(owner)
        body = resolve(kind, self.parser.udts)
        fields = {}
        for member, member_kind, _ in body.members:
            child = self.kind_of(member_kind, f"{name}_{clean_name(member)}", structures.join(path, clean_name(member)))
            if child is not None:
                fields[clean_name(member)] = child
        result = self.add_type(name, fields) if fields else None
        if kind.kind == "udt":
            self.udts[kind.plc] = result
        return result


def initial_values(kind, path, init, udts, out):
    """Declared initial values as (path, literal) in memory order, UDT defaults included."""
    if kind.kind in {"elementary", "string"}:
        if init is not None and not isinstance(init, list):
            out.append((path, init, kind))
    elif kind.kind in {"struct", "udt"}:
        for name, member, member_init in resolve(kind, udts).members:
            initial_values(member, structures.join(path, clean_name(name)), member_init, udts, out)
    else:
        for position, index in enumerate(elements(kind.dims)):
            element_init = init[position] if isinstance(init, list) and position < len(init) else None
            initial_values(kind.of, path + index, element_init, udts, out)


def plan(project, text, *, db=None, connection="", writable=False, replace=False):
    """Read the pasted source and say what would be created (``apply`` creates it)."""
    if not text.strip():
        raise ValueError(tr("Pega la fuente del DB generada en TIA Portal"))
    parser = Parser(text).parse()
    if len(parser.blocks) > 1:
        raise ValueError(tr("Pega un solo DATA_BLOCK cada vez (con los TYPE que use)"))
    converter = Converter(project, parser, replace)
    result = Plan()
    if not parser.blocks:
        for name, body in parser.udts.items():
            converter.kind_of(Type("udt", plc=name), name, clean_name(name))
        result.types = converter.types
        result.warnings = [tr("No hay DATA_BLOCK: solo se importan los tipos")] + _omitted(converter)
        result.rows = [(name, "UDT", name, "", "") for name in converter.types]
        return result
    name, body, assignments, optimized = parser.blocks[0]
    variable_name = clean_name(name)
    result.db_name, result.optimized = variable_name, optimized
    existing = next((v for v in project.variables if v["name"] == variable_name), None)
    if existing is not None and not replace:
        raise ValueError(tr("Ya existe la variable «{name}»; marca «Sustituir» para actualizarla", name=variable_name))
    kind = converter.kind_of(body, variable_name, "")
    if kind is None:
        raise ValueError(tr("El DB no tiene ningún dato que abSCADA pueda leer"))
    all_types = {**project.types, **converter.types}
    initial = structures.default_value(all_types, kind)
    declared = []
    initial_values(body, "", None, parser.udts, declared)
    begin = [(path, literal, None) for path, literal in assignments]
    leaves = structures.leaves(all_types, kind)
    for path, literal, _ in declared + begin:
        relative = path.replace('"', "")
        if relative not in leaves:
            if not any(relative == p for p, _ in converter.omitted):
                result.warnings.append(tr("Valor inicial de «{path}» ignorado: no existe en el DB", path=relative))
            continue
        if isinstance(literal, list):
            result.warnings.append(tr("Valor inicial de «{path}» ignorado: no se esperaba una lista", path=relative))
            continue
        parsed = value(literal, leaves[relative], "")
        if parsed is None:
            result.warnings.append(tr("Valor inicial de «{path}» no reconocido: {value}", path=relative, value=literal))
            continue
        structures.set_at(all_types, kind, initial, structures.relative_steps(relative), parsed)
    layout = []
    place(body, Cursor(), "", parser.udts, layout)
    addresses = {}
    if connection and not optimized:
        if not isinstance(db, int) or not 1 <= db <= 65535:
            raise ValueError(tr("Indica el número del DB (1 a 65535)"))
        for path, plc, byte, bit in layout:
            access = ELEMENTARY.get(plc.casefold(), (0, None, None))[2]
            if path in leaves and access:
                addresses[path] = (f"%DB{db}.DBX{byte}.{bit}" if access == "X" else f"%DB{db}.DB{access}{byte}")
    elif optimized:
        result.warnings.append(tr("DB con acceso optimizado: no tiene direcciones absolutas. Se importa la estructura sin enlaces; "
                                  "desactiva «Acceso optimizado al bloque» en TIA Portal o enlázalo por OPC UA"))
    signed = sorted({plc for path, plc, _, _ in layout if plc.casefold() in SIGNED_READ and path in addresses})
    if signed:
        result.warnings.append(tr("{types} se leen con signo: los valores por encima del rango con signo se verán negativos", types=", ".join(signed)))
    variable = dict(name=variable_name, type=kind, initial=initial, writable=bool(writable))
    if existing is not None:
        for key in ("folder", "description"):
            if key in existing:
                variable[key] = existing[key]
    bindings = {structures.join(variable_name, path): dict(connection=connection, address=address) for path, address in addresses.items()}
    if bindings:
        variable["bindings"] = bindings
    plc_types = {path: plc for path, plc, _, _ in layout}
    for path, scada in leaves.items():
        current = structures.kind_at(all_types, kind, structures.relative_steps(path))
        shown = _get(all_types, kind, initial, path)
        result.rows.append((structures.join(variable_name, path), plc_types.get(path, ""), current, addresses.get(path, ""), shown))
    result.types = converter.types
    result.variable = variable
    result.warnings = _omitted(converter) + result.warnings
    if existing is not None:
        # Replacing: fields that disappear but are still used make the import fail validation.
        from .variable_references import usages
        kept = {row[0] for row in result.rows}
        gone = sorted(name for name in project.tags() if structures.root(name) == variable_name and name not in kept)
        used = [name for name in gone if usages(project, name)]
        if used:
            result.warnings.insert(0, tr("Desaparecen campos que se usan: {fields}. Si solo han cambiado de nombre, renómbralos antes en "
                                         "abSCADA (clic derecho → Renombrar…) y vuelve a importar", fields=", ".join(used[:8])))
    return result


def _get(types, kind, value, path):
    for step in structures.relative_steps(path):
        if isinstance(step, int):
            value = value[step - structures.lower(kind)]; kind = structures.split_kind(kind)[0]
        else:
            value = value[step]; kind = types[kind][step]
    return value


def _omitted(converter):
    if not converter.omitted:
        return []
    shown = ", ".join(f"{path} ({plc})" for path, plc in converter.omitted[:8])
    more = len(converter.omitted) - 8
    return [tr("Sin soporte todavía, se omiten (su espacio sí se respeta en las direcciones): {fields}", fields=shown)
            + (tr(" y {count} más", count=more) if more > 0 else "")]


def apply(project, result, folder=""):
    """Add the planned types and variable to ``project`` (replacing ones with the same name)."""
    project.types.update(copy.deepcopy(result.types))
    if result.variable is None:
        return
    variable = copy.deepcopy(result.variable)
    folder = structures_folder(folder)
    if folder:
        from .screen_tree import folders, add_folder, parent_folder
        if folder not in folders(project, "variables"):
            parent, _, leaf = folder.rpartition("/")
            if parent and parent not in folders(project, "variables"):
                _make_folders(project, parent)
            add_folder(project, parent, leaf, "variables")
        variable["folder"] = folder
    index = next((i for i, v in enumerate(project.variables) if v["name"] == variable["name"]), None)
    if index is None:
        project.variables.append(variable)
    else:
        project.variables[index] = variable


def structures_folder(folder):
    from .screen_tree import clean_folder
    return clean_folder(folder or "")


def _make_folders(project, path):
    from .screen_tree import folders, add_folder
    built = ""
    for part in path.split("/"):
        parent, built = built, f"{built}/{part}" if built else part
        if built not in folders(project, "variables"):
            add_folder(project, parent, part, "variables")
