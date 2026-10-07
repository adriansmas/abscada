"""Application language: catalogs complete and consistent, tr() behaviour and the setting."""
import importlib.util
import json
import string
from pathlib import Path

import pytest
from abscada import i18n

ROOT = Path(__file__).resolve().parents[1]


def check_tool():
    spec = importlib.util.spec_from_file_location("i18n_check", ROOT / "tools" / "i18n_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fields(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name is not None)


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("es")


@pytest.mark.parametrize("code", [c for c in i18n.LANGUAGES if c != i18n.SOURCE])
def test_every_text_is_translated_with_the_same_placeholders(code):
    texts = check_tool().texts()
    catalog = i18n.load_catalog(code)
    missing = [t for t in texts if not catalog.get(t)]
    assert not missing, f"{len(missing)} textos sin traducir a {code}, p. ej. {missing[:5]}"
    broken = [t for t in texts if fields(t) != fields(catalog[t])]
    assert not broken, f"marcadores distintos en {code}: {broken[:5]}"


def test_tr_translates_formats_and_falls_back_to_spanish(english):
    assert i18n.tr("Guardar") == "Save"
    assert i18n.tr("¿Eliminar la cuenta {name}?", name="ana") == "Delete the account ana?"
    assert i18n.tr("Un texto que nadie ha traducido") == "Un texto que nadie ha traducido"
    i18n._catalog["Hola {name}"] = "Hello {nombre}"  # a broken translation never hides the message
    assert i18n.tr("Hola {name}", name="x") == "Hola x"


def test_the_language_is_an_application_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "settings_path", lambda: tmp_path / "settings.json")
    assert i18n.configured_language() == "es"
    i18n.save_language("en")
    assert i18n.configured_language() == "en"
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8")) == {"language": "en"}
    with pytest.raises(ValueError):
        i18n.save_language("xx")


def test_studio_builds_in_english(english, qtbot_free_project):
    from abscada.ui import Window
    window = Window(qtbot_free_project)
    titles = [action.text() for action in window.menuBar().actions()]
    assert "&File" in titles and "&Help" in titles
    window.close()


@pytest.fixture
def qtbot_free_project(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from abscada.project import Project
    import shutil
    shutil.copytree(ROOT / "examples" / "plant", tmp_path / "plant", ignore=shutil.ignore_patterns("runtime"))
    return Project.load(tmp_path / "plant")
