"""Studio usability round: empty containers, one-name screens, inline lists, context menus, scripts."""
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402

from abscada.project import Project  # noqa: E402
from abscada.project_dialogs import NewDocumentDialog, file_name_from_title  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def pump():
    for _ in range(4):
        QApplication.processEvents()


@pytest.fixture
def studio(tmp_path):
    QApplication.instance() or QApplication([])
    from abscada.ui import Window
    shutil.copytree(ROOT / "examples/hydro", tmp_path / "hydro", ignore=shutil.ignore_patterns("runtime"))
    window = Window(Project.load(tmp_path / "hydro"))
    window.show(); pump()
    yield window
    window.dirty = False
    window.close()
    QApplication.clipboard().clear()


def test_a_container_can_exist_without_a_screen(studio):
    studio.project.screens = {k: v for k, v in list(studio.project.screens.items())[:1]}
    studio.project.manifest["startup_screen"] = next(iter(studio.project.screens))
    studio.document_kind, studio.document_name = "screens", studio.project.manifest["startup_screen"]
    studio.project.screens[studio.document_name]["elements"] = []
    studio.render_scene()
    studio.add_element("screen_container")
    element = studio.document()["elements"][0]
    assert element["kind"] == "screen_container" and element["screen"] == ""
    studio.project.validate()
    assert studio.container_screen_field.currentData() == ""


def test_file_name_comes_from_the_title(studio):
    assert file_name_from_title("Depósito nº 1 – Cocción") == "Deposito_no_1_Coccion"
    assert file_name_from_title("Inicio", taken=["inicio"]) == "Inicio_2"
    assert file_name_from_title("¿¿??") == ""
    dialog = NewDocumentDialog(studio)
    dialog.title.setText("Sala de bombas")
    assert dialog.name.text() == "Sala_de_bombas" and not dialog.name.isVisibleTo(dialog)
    assert dialog.document()["title"] == "Sala de bombas"


def test_right_click_menu_offers_delete(studio, monkeypatch):
    studio.add_element("text")
    assert len(studio.scene.selectedItems()) == 1
    titles = [a.text() for a in studio.build_canvas_menu().actions() if a.text()]
    assert "Suprimir" in titles and "Duplicar" in titles
    before = len(studio.document()["elements"])
    studio.delete_element()
    assert len(studio.document()["elements"]) == before - 1


def test_variables_are_typed_in_the_last_row_numbered_and_inserted_in_the_middle(studio):
    studio.navigate("variables")
    count = len(studio.project.variables)
    last = studio.table.topLevelItem(studio.table.topLevelItemCount() - 1)
    assert last.data(0, Qt.ItemDataRole.UserRole) == "\0new-variable"
    studio.new_variable_field.setText("Alfa"); studio.new_variable_field.editingFinished.emit(); pump()
    assert [v["name"] for v in studio.project.variables][-1] == "Alfa"
    assert studio.project.variables[-1]["type"] == "float"
    assert len(studio.project.variables) == count + 1
    first = studio.table.topLevelItem(0)
    from abscada.numbered_rows import NUMBER_ROLE
    assert first.data(0, NUMBER_ROLE) == 1 and studio.table.topLevelItem(1).data(0, NUMBER_ROLE) == 2
    studio.insert_variable_at(1); pump()
    studio.new_variable_field.setText("Medio"); studio.new_variable_field.editingFinished.emit(); pump()
    assert studio.project.variables[1]["name"] == "Medio"
    studio.change_variable_type("Medio", "int")
    assert studio.project.variables[1]["type"] == "int" and studio.project.variables[1]["initial"] == 0
    monkeypatch_yes = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        studio.delete_variable("Medio")
    finally:
        QMessageBox.question = monkeypatch_yes
    assert all(v["name"] != "Medio" for v in studio.project.variables)
    studio.undo()
    assert any(v["name"] == "Medio" for v in studio.project.variables)


def test_data_types_have_an_inline_row(studio):
    studio.navigate("types")
    studio.new_type_field.setText("Valvula"); studio.new_type_field.returnPressed.emit(); pump()
    assert studio.project.types["Valvula"] == {"valor": "float"}


def test_bool_conditions_do_not_ask_for_an_operator(studio):
    from abscada.dynamic_editor import ConditionForm
    studio.project.variables.append(dict(name="Marcha", type="bool", initial=False, writable=True))
    form = ConditionForm(studio, dict(tag="Marcha", op="ne", value=True), False)
    assert not form.op.isVisibleTo(form)
    assert form.data() == dict(tag="Marcha", op="eq", value=False, bad=False)


def test_scripts_page_explains_itself_and_creates_inline(studio):
    studio.project.scripts.clear(); studio.project.automation = {}
    for document in studio.project.screens.values():
        document.pop("on_open", None)
    studio.navigate("automation")
    editor = studio.automation_editor
    editor.refresh()
    assert "Todavía no hay scripts" in editor.code.placeholderText()
    editor.new_name.setText("arranque"); editor.new_name.returnPressed.emit(); pump()
    assert "arranque" in studio.project.scripts and editor.current == "arranque" and editor.code.isEnabled()


def test_screen_open_scripts_without_scripts_points_to_the_scripts_section(studio, monkeypatch):
    studio.project.scripts.clear()
    opened = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: opened.append(self.text()) or 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    studio.screen_properties.edit_events()
    assert opened and "Scripts" in opened[0]
