import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "tools" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

CHANGELOG = """# Registro de cambios

## [Sin publicar]

### Añadido
- Algo nuevo.

## [0.5.0b1] - 2026-10-01

### Añadido
- Primera beta.
"""


@pytest.mark.parametrize("current, part, expected", [
    ("0.5.0b1", "beta", "0.5.0b2"), ("0.5.0", "beta", "0.5.1b1"), ("0.5.0a3", "beta", "0.5.0b1"),
    ("0.5.0b2", "patch", "0.5.0"), ("0.5.0", "patch", "0.5.1"), ("0.5.0rc1", "patch", "0.5.0"),
    ("0.5.3", "minor", "0.6.0"), ("0.5.0b1", "major", "1.0.0")])
def test_bump(current, part, expected):
    assert release.bump(current, part) == expected


@pytest.mark.parametrize("bad", ["1.0", "v1.0.0", "1.0.0-beta", "1.0.0b"])
def test_invalid_versions(bad):
    with pytest.raises(ValueError):
        release.parse(bad)


def test_prerelease_detection():
    assert release.is_prerelease("0.5.0b2") and release.is_prerelease("1.0.0rc1") and not release.is_prerelease("1.0.0")


def test_changelog_rotation_and_notes():
    rotated = release.rotate_changelog(CHANGELOG, "0.5.0b2", "2026-10-07")
    assert rotated.index("## [Sin publicar]") < rotated.index("## [0.5.0b2] - 2026-10-07") < rotated.index("## [0.5.0b1]")
    assert release.unreleased_notes(rotated) == ""
    assert release.version_notes(rotated, "v0.5.0b2") == "### Añadido\n- Algo nuevo."
    assert release.version_notes(rotated, "0.5.0b1") == "### Añadido\n- Primera beta."
    with pytest.raises(ValueError, match="No hay cambios"):
        release.rotate_changelog(rotated, "0.5.0b3", "2026-10-08")
    with pytest.raises(ValueError):
        release.version_notes(rotated, "9.9.9")


def test_version_is_replaced_once():
    text = '__version__ = "0.5.0b1"\n'
    assert release.set_version(text, r'^(__version__ = ")[^"]+(")', "0.5.0b2") == '__version__ = "0.5.0b2"\n'
    toml = '[project]\nname = "abscada"\nversion = "0.5.0b1"\n[tool.x]\nversion = "9"\n'
    assert 'version = "0.5.0b2"' in release.set_version(toml, r'^(version = ")[^"]+(")', "0.5.0b2")
    assert 'version = "9"' in release.set_version(toml, r'^(version = ")[^"]+(")', "0.5.0b2")


def test_repository_versions_agree():
    assert release.current_version() in release.PYPROJECT.read_text(encoding="utf-8")
