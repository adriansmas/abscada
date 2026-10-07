"""Publish a new abSCADA version with one command.

    .venv\\Scripts\\python tools/release.py --beta          0.5.0b1 -> 0.5.0b2
    .venv\\Scripts\\python tools/release.py --patch         0.5.0b2 -> 0.5.0  (0.5.0 -> 0.5.1)
    .venv\\Scripts\\python tools/release.py --minor         -> 0.6.0
    .venv\\Scripts\\python tools/release.py 0.6.0rc1        explicit version
    add --dry-run to see everything without changing anything

What it does, stopping at the first problem:
  1. Checks: branch main, no uncommitted changes, not behind origin, tag not used yet,
     and notes under «## [Sin publicar]» in CHANGELOG.md.
  2. Runs the test suite (skip with --skip-tests).
  3. Writes the version in src/abscada/__init__.py and pyproject.toml, and turns
     «## [Sin publicar]» into «## [x.y.z] - date» with a new empty section on top.
  4. Commits «Release vx.y.z», creates the tag, pushes both.
GitHub Actions (release.yml) then builds the .exe, tests it, and publishes the release
with the ZIP, SBOM and checksums, using that CHANGELOG section as release notes.
With --watch it follows the build until the release is online.

    python tools/release.py notes v0.5.0b2     prints the notes of a version (used by CI)
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "abscada" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
UNRELEASED = "## [Sin publicar]"
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")


# -- pure helpers (tested) ----------------------------------------------------
def parse(version):
    match = VERSION.match(version)
    if not match:
        raise ValueError(f"Versión inválida: {version} (formato 1.2.3, 1.2.3b1, 1.2.3rc2)")
    major, minor, patch, stage, number = match.groups()
    return int(major), int(minor), int(patch), stage, int(number) if number else None


def bump(current, part):
    major, minor, patch, stage, number = parse(current)
    if part == "beta":
        if stage == "b":
            return f"{major}.{minor}.{patch}b{number + 1}"
        if stage in (None,):
            return f"{major}.{minor}.{patch + 1}b1"
        return f"{major}.{minor}.{patch}b1"  # alpha -> first beta
    if part == "patch":
        return f"{major}.{minor}.{patch}" if stage else f"{major}.{minor}.{patch + 1}"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "major":
        return f"{major + 1}.0.0"
    raise ValueError(part)


def is_prerelease(version):
    return parse(version)[3] is not None


def unreleased_notes(changelog):
    start = changelog.find(UNRELEASED)
    if start < 0:
        raise ValueError(f"CHANGELOG.md no tiene la sección «{UNRELEASED}»")
    body = changelog[start + len(UNRELEASED):]
    end = re.search(r"^## \[", body, re.M)
    return (body[:end.start()] if end else body).strip()


def rotate_changelog(changelog, version, date):
    notes = unreleased_notes(changelog)
    if not re.search(r"^\s*[-*] ", notes, re.M):
        raise ValueError("No hay cambios anotados en «## [Sin publicar]» de CHANGELOG.md")
    return changelog.replace(UNRELEASED, f"{UNRELEASED}\n\n## [{version}] - {date}", 1)


def version_notes(changelog, version):
    version = version.lstrip("v")
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    if not match:
        raise ValueError(f"CHANGELOG.md no tiene la sección de la versión {version}")
    return match.group(1).strip()


def set_version(text, pattern, version):
    new, count = re.subn(pattern, lambda m: m.group(1) + version + m.group(2), text, count=1, flags=re.M)
    if count != 1:
        raise ValueError("No se encontró la versión que hay que cambiar")
    return new


# -- git / process -------------------------------------------------------------
def git_executable():
    found = shutil.which("git")
    if found:
        return found
    candidate = Path(r"C:\Program Files\Git\cmd\git.exe")
    if candidate.exists():
        return str(candidate)
    raise SystemExit("No encuentro git")


def git(*args, check=True):
    result = subprocess.run([git_executable(), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode:
        raise SystemExit(f"git {' '.join(args)} ha fallado:\n{result.stderr.strip()}")
    return result.stdout.strip()


def current_version():
    return re.search(r'__version__ = "([^"]+)"', INIT.read_text(encoding="utf-8")).group(1)


def preflight(tag):
    problems = []
    if git("branch", "--show-current") != "main":
        problems.append("No estás en la rama main")
    if git("status", "--porcelain"):
        problems.append("Hay cambios sin commit: haz commit (o descártalos) antes de publicar")
    git("fetch", "--quiet", "origin")
    behind = git("rev-list", "--count", "HEAD..origin/main", check=False) or "0"
    if behind != "0":
        problems.append(f"Tu main va {behind} commits por detrás de origin/main: haz git pull")
    if git("tag", "--list", tag) or git("ls-remote", "--tags", "origin", tag, check=False):
        problems.append(f"La etiqueta {tag} ya existe")
    return problems


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "notes":
        notes = version_notes(CHANGELOG.read_text(encoding="utf-8"), sys.argv[2])
        repository = os.environ.get("GITHUB_REPOSITORY")
        if repository:  # relative links do not work on a release page
            base = f"https://github.com/{repository}/blob/{sys.argv[2]}/"
            notes = re.sub(r"\]\((?!https?://|#)([^)]+)\)", lambda m: f"]({base}{m.group(1)})", notes)
        sys.stdout.reconfigure(encoding="utf-8")
        print(notes)
        return
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("version", nargs="?", help="versión explícita, por ejemplo 0.6.0rc1")
    for part in ("beta", "patch", "minor", "major"):
        group.add_argument(f"--{part}", action="store_const", const=part, dest="part")
    parser.add_argument("--dry-run", action="store_true", help="mostrar lo que se haría sin cambiar nada")
    parser.add_argument("--skip-tests", action="store_true", help="no ejecutar las pruebas locales (CI las ejecuta igualmente)")
    parser.add_argument("--yes", action="store_true", help="no pedir confirmación antes de subir")
    parser.add_argument("--watch", action="store_true", help="seguir la compilación en GitHub hasta publicar")
    args = parser.parse_args()

    old = current_version()
    new = args.version or bump(old, args.part)
    parse(new)
    tag = f"v{new}"
    changelog = CHANGELOG.read_text(encoding="utf-8")
    today = datetime.date.today().isoformat()
    rotated = rotate_changelog(changelog, new, today)
    print(f"Versión: {old} -> {new} ({'pre-versión' if is_prerelease(new) else 'versión estable'}), etiqueta {tag}")
    print("\nNotas de la versión (de CHANGELOG.md):\n" + "-" * 60 + f"\n{version_notes(rotated, new)}\n" + "-" * 60)

    problems = preflight(tag)
    if problems:
        print("\nNo se puede publicar:\n  - " + "\n  - ".join(problems))
        raise SystemExit(1)
    if args.dry_run:
        print("\nSimulación: todo correcto. Sin --dry-run se cambiaría la versión, se haría commit, etiqueta y push.")
        return
    if not args.skip_tests:
        print("\nEjecutando las pruebas…")
        if subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT).returncode:
            raise SystemExit("Las pruebas fallan: no se publica")
    if not args.yes and input(f"\n¿Publicar {tag}? Se subirá a GitHub y se compilará el .exe [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
        raise SystemExit("Cancelado")

    INIT.write_text(set_version(INIT.read_text(encoding="utf-8"), r'^(__version__ = ")[^"]+(")', new), encoding="utf-8", newline="\n")
    PYPROJECT.write_text(set_version(PYPROJECT.read_text(encoding="utf-8"), r'^(version = ")[^"]+(")', new), encoding="utf-8", newline="\n")
    CHANGELOG.write_text(rotated, encoding="utf-8", newline="\n")
    git("add", str(INIT), str(PYPROJECT), str(CHANGELOG))
    git("commit", "-m", f"Release {tag}")
    git("tag", "-a", tag, "-m", f"abSCADA {new}")
    git("push", "origin", "main")
    git("push", "origin", tag)
    print(f"\nPublicada la etiqueta {tag}. GitHub Actions compila el .exe y crea la release (unos 10 minutos).")
    gh = shutil.which("gh") or (r"C:\Program Files\GitHub CLI\gh.exe" if Path(r"C:\Program Files\GitHub CLI\gh.exe").exists() else None)
    if args.watch and gh:
        import time
        time.sleep(10)
        run = subprocess.run([gh, "run", "list", "--workflow", "release.yml", "--branch", tag, "--limit", "1",
                              "--json", "databaseId", "-q", ".[0].databaseId"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if run:
            subprocess.run([gh, "run", "watch", run, "--exit-status"], cwd=ROOT)
            subprocess.run([gh, "release", "view", tag, "--web"], cwd=ROOT)
    else:
        remote = git("remote", "get-url", "origin").removesuffix(".git")
        print(f"Progreso: {remote}/actions · Release: {remote}/releases/tag/{tag}")


if __name__ == "__main__":
    main()
