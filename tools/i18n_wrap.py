"""Wrap user-facing Spanish literals in tr() (one-off codemod, kept for new modules).

    .venv\\Scripts\\python tools/i18n_wrap.py src/abscada/ui.py [...] [--dry-run]

Wraps string literals and f-strings passed to Qt text APIs, to the project's own UI
helpers and to raised exceptions. An f-string becomes a template with named fields:
f"Usuario {name}" -> tr("Usuario {name}", name=name). Everything else (object names,
keys, data) is left alone; review the diff and translate leftovers by hand.
"""
from __future__ import annotations

import argparse
import ast
import keyword
import re
import sys
from pathlib import Path

# name -> positional argument indexes holding text ("*" = every positional literal)
CALLS = {
    "QLabel": [0], "QPushButton": [0], "QCheckBox": [0], "QRadioButton": [0], "QGroupBox": [0],
    "QAction": "first", "QTableWidgetItem": [0], "QListWidgetItem": [0], "QToolButton": [],
    "setText": [0], "setWindowTitle": [0], "setToolTip": [0], "setPlaceholderText": [0], "setStatusTip": [0],
    "setTitle": [0], "setSuffix": [0], "setPrefix": [0], "setSpecialValueText": [0], "showMessage": [0],
    "addAction": "first", "addMenu": "first", "addTab": [1], "insertTab": [2], "setTabText": [1],
    "addRow": [0], "addItem": [0], "insertItem": [1], "setHeaderLabel": [0], "setItemText": [1],
    "information": [1, 2], "warning": [1, 2], "critical": [1, 2], "question": [1, 2], "about": [1, 2],
    "getText": [1, 2], "getItem": [1, 2], "getInt": [1, 2], "getDouble": [1, 2],
    "getOpenFileName": [1, 3], "getSaveFileName": [1, 3], "getExistingDirectory": [1],
    "setInformativeText": [0], "setDetailedText": [0], "setLabelText": [0], "addSection": [0],
    # abSCADA helpers
    "button": [0], "label": [0], "error": [0], "Field": [1], "action": [1], "section_label": [0], "heading": [0],
}
LIST_CALLS = {"setHorizontalHeaderLabels", "setVerticalHeaderLabels", "setHeaderLabels", "addItems", "QTreeWidgetItem"}
EXCEPTIONS = {"ValueError", "PermissionError", "RuntimeError", "ConnectionError", "TypeError", "OSError",
              "FileNotFoundError", "KeyError", "TimeoutError", "AuthenticationError", "ProjectError"}
TEXT_KEYWORDS = {"text", "title", "tooltip", "label", "message", "caption", "reason", "disabled_reason"}
SPANISH = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]")


def call_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def is_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip()
        return bool(value) and bool(SPANISH.search(value)) and not value.startswith(("#", "%", "@", "$", "*."))
    return isinstance(node, ast.JoinedStr) and any(
        isinstance(v, ast.Constant) and SPANISH.search(v.value) for v in node.values)


class Collector(ast.NodeVisitor):
    def __init__(self):
        self.targets = []

    def add(self, node):
        if is_text(node):
            self.targets.append(node)

    def visit_Call(self, node):
        name = call_name(node)
        if name == "tr":
            return  # already translated
        spec = CALLS.get(name)
        if spec == "first":
            literal = next((a for a in node.args if isinstance(a, (ast.Constant, ast.JoinedStr))), None)
            if literal is not None:
                self.add(literal)
        elif spec:
            for index in spec:
                if index < len(node.args):
                    self.add(node.args[index])
        if name in LIST_CALLS:
            for arg in node.args:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    for element in arg.elts:
                        self.add(element)
        if spec is not None or name in LIST_CALLS:
            for kw in node.keywords:
                if kw.arg in TEXT_KEYWORDS:
                    self.add(kw.value)
        self.generic_visit(node)

    def visit_Raise(self, node):
        exc = node.exc
        if isinstance(exc, ast.Call) and call_name(exc) in EXCEPTIONS and exc.args:
            self.add(exc.args[0])
        self.generic_visit(node)


def field_name(expr, source, used):
    text = ast.get_source_segment(source, expr) or "v"
    if isinstance(expr, ast.Name):
        base = expr.id
    elif isinstance(expr, ast.Attribute):
        base = expr.attr
    elif isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, str):
        base = expr.slice.value
    elif isinstance(expr, ast.Call) and call_name(expr):
        base = call_name(expr)
    else:
        base = re.sub(r"\W+", "_", text).strip("_").lower()[:20] or "v"
    base = re.sub(r"\W", "_", base)
    if not base or base[0].isdigit() or keyword.iskeyword(base):
        base = "v_" + base
    name, n = base, 2
    while name in used and used[name] != text:
        name, n = f"{base}{n}", n + 1
    used[name] = text
    return name, text


def wrap_fstring(node, source):
    template, args, used = [], {}, {}
    for part in node.values:
        if isinstance(part, ast.Constant):
            template.append(part.value.replace("{", "{{").replace("}", "}}"))
            continue
        name, expr = field_name(part.value, source, used)
        conversion = {-1: "", 115: "!s", 114: "!r", 97: "!a"}[part.conversion]
        spec = ""
        if part.format_spec is not None:
            if not all(isinstance(v, ast.Constant) for v in part.format_spec.values):
                return None  # nested replacement fields in a format spec: leave it
            spec = ":" + "".join(v.value for v in part.format_spec.values)
        template.append("{" + name + conversion + spec + "}")
        args[name] = expr
    literal = '"' + "".join(template).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return "tr(" + literal + "".join(f", {k}={v}" for k, v in args.items()) + ")"


def offsets(source):
    starts, total = [0], 0
    for line in source.splitlines(keepends=True):
        total += len(line)
        starts.append(total)
    return starts


def process(path, dry_run=False):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    collector = Collector()
    collector.visit(tree)
    starts = offsets(source)
    edits = []
    for node in collector.targets:
        begin = starts[node.lineno - 1] + len(source[starts[node.lineno - 1]:].encode("utf-8")[:node.col_offset].decode("utf-8"))
        end = starts[node.end_lineno - 1] + len(source[starts[node.end_lineno - 1]:].encode("utf-8")[:node.end_col_offset].decode("utf-8"))
        if isinstance(node, ast.Constant):
            replacement = "tr(" + source[begin:end] + ")"
        else:
            replacement = wrap_fstring(node, source)
            if replacement is None:
                continue
        edits.append((begin, end, replacement))
    if not edits:
        return 0
    for begin, end, replacement in sorted(set(edits), reverse=True):
        source = source[:begin] + replacement + source[end:]
    if "from .i18n import tr" not in source and "from abscada.i18n import tr" not in source:
        source = add_import(source, path)
    ast.parse(source)  # never write a file that no longer parses
    if not dry_run:
        path.write_text(source, encoding="utf-8", newline="\n")
    return len(edits)


def add_import(source, path):
    relative = path.parent.name == "abscada"
    line = "from .i18n import tr\n" if relative else "from abscada.i18n import tr\n"
    tree = ast.parse(source)
    last = None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node
        elif last is not None or not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            break
    lines = source.splitlines(keepends=True)
    if last is None:
        # after the module docstring
        first = tree.body[0]
        index = first.end_lineno if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) else 0
    else:
        index = last.end_lineno
    lines.insert(index, line)
    return "".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    for file in args.files:
        print(f"{process(file, args.dry_run):4d}  {file}")
    sys.exit(0)
