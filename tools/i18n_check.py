"""Translation catalog maintenance for the application's own texts (not projects).

    .venv\\Scripts\\python tools/i18n_check.py              # missing / unused entries per language
    .venv\\Scripts\\python tools/i18n_check.py --leftovers  # Spanish literals not wrapped in tr()
    .venv\\Scripts\\python tools/i18n_check.py --export en  # write missing entries (empty) to review

Texts are collected from every tr("…") and N_("…") call in src/abscada (the first argument must be a
literal). tests/test_i18n.py fails when a catalog misses one of them.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "abscada"
LOCALES = PACKAGE / "locales"
SKIP = {"script_runner.py"}
SPANISH_HINT = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]|\b(el|la|los|las|de|del|un|una|sin|con|para|por|que|no|se|en|y|o)\b")
# A label: starts with a capital letter and reads like words, not like code or a key.
CAPS = re.compile(r"^[A-ZÁÉÍÓÚÑ]{4,}(?: [A-ZÁÉÍÓÚÑ]{2,})*$")
LABEL = re.compile(r"^[+¿¡«(]?\s?[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:[ ,.:·…/-]+[\wáéíóúñü%()«»…]+)*[.…:?!»)]*$")


def sources():
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name not in SKIP and "simulators" not in path.parts:
            yield path


def texts():
    """{source text: [locations]} for every tr() literal."""
    found = {}
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "N_") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.setdefault(first.value, []).append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def leftovers():
    """Spanish-looking literals outside tr(), docstrings and comments."""
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        inside, docstrings = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "N_"):
                inside.update(id(n) for n in ast.walk(node))
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if id(node) in inside or id(node) in docstrings:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and (
                    SPANISH_HINT.search(node.value) or LABEL.match(node.value.strip()) or CAPS.match(node.value.strip())):
                yield f"{path.relative_to(ROOT)}:{node.lineno}: {node.value[:90]!r}"


def catalog(code):
    path = LOCALES / f"{code}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leftovers", action="store_true")
    parser.add_argument("--export", metavar="LANG")
    args = parser.parse_args()
    if args.leftovers:
        for line in leftovers():
            print(line)
        return 0
    found = texts()
    for code in sorted(p.stem for p in LOCALES.glob("*.json")):
        entries = catalog(code)
        missing = [t for t in found if not entries.get(t)]
        unused = [t for t in entries if t not in found]
        print(f"{code}: {len(found) - len(missing)}/{len(found)} traducidos · {len(unused)} sin uso")
        for text in missing[:50]:
            print("  falta:", repr(text[:100]), found[text][0])
    if args.export:
        entries = catalog(args.export)
        merged = {text: entries.get(text, "") for text in found}
        LOCALES.mkdir(exist_ok=True)
        (LOCALES / f"{args.export}.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
