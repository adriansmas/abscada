"""Studio frame after the usability review: menus, section bar, clipboard and clearer lists."""
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from abscada import screen_tree  # noqa: E402
from abscada.project import Project  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def pump_events():
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def window(tmp_path):
    QApplication.instance() or QApplication([])
    from abscada.ui import Window
    shutil.copytree(ROOT / "examples/hydro", tmp_path / "hydro", ignore=shutil.ignore_patterns("runtime"))
    studio = Window(Project.load(tmp_path / "hydro"))
    studio.show()
    QApplication.processEvents()
    yield studio
    studio.dirty = False
    studio.close()
    # The offscreen platform crashes at exit if the clipboard still owns data.
    QApplication.clipboard().clear()


def menu_titles(window):
    return {action.text().replace("&", ""): [a.text() for a in action.menu().actions() if a.text()]
            for action in window.menuBar().actions()}


def test_commands_live_in_menus_and_the_toolbar_is_short(window):
    menus = menu_titles(window)
    assert list(menus) == ["Archivo", "Edición", "Proyecto", "Herramientas", "Ayuda"]
    assert {"Copiar", "Cortar", "Pegar", "Duplicar", "Eliminar", "Deshacer", "Rehacer"} <= set(menus["Edición"])
    assert "Ajustes del proyecto…" in menus["Proyecto"]
    assert "Simuladores de PLC…" in menus["Herramientas"]
    toolbar = window.findChild(type(window.addToolBar("probe")).__mro__[0], "mainToolbar")
    assert [a.text() for a in toolbar.actions() if a.text()] == ["Guardar", "Deshacer", "Rehacer"]


def test_section_bar_replaces_sections_in_the_tree(window):
    rail = window.section_rail
    assert [rail.item(i).text() for i in range(rail.count())] == \
        ["Pantallas", "Variables", "Conexiones", "Alarmas", "Registros", "Scripts", "Diagnóstico"]
    rail.setCurrentRow(1)
    assert window.active_section == "variables" and not window.resources_panel.isVisible()
    window.navigate("types")
    assert window.variables_tabs.currentIndex() == 1 and rail.currentRow() == 1
    rail.setCurrentRow(0)
    assert window.active_section == "screens" and window.resources_panel.isVisible()
    values = {item.data(0, Qt.ItemDataRole.UserRole) for item in window._tree_items()}
    assert not any(value[0] == "section" for value in values)


def test_copy_paste_between_screens_copies_the_trend_configuration(window):
    window.document_kind, window.document_name = "screens", "72_tend_g1"
    window.render_scene()
    trend = next(i for i in window.scene.items() if getattr(i, "element", {}).get("kind") == "trend")
    trend.setSelected(True)
    source_view = trend.element["view"]
    window.copy_elements()
    window.document_name = "73_tend_g2"
    window.render_scene()
    before = len(window.document()["elements"])
    window.paste_elements()
    pasted = window.scene.selectedItems()[0].element
    assert len(window.document()["elements"]) == before + 1
    assert pasted["kind"] == "trend" and pasted["view"] != source_view
    assert window.project.trends[pasted["view"]] == window.project.trends[source_view]
    # Same position on another screen; shifted when pasted on the same one.
    assert (pasted["x"], pasted["y"]) == (trend.element["x"], trend.element["y"])
    window.undo()
    assert len(window.document()["elements"]) == before and pasted["view"] not in window.project.trends


def test_cut_removes_and_paste_restores(window):
    window.document_kind, window.document_name = "screens", "10_general"
    window.render_scene()
    item = window.scene.items()[0]
    element_id = item.element["id"]
    item.setSelected(True)
    window.cut_elements()
    assert element_id not in {e["id"] for e in window.document()["elements"]}
    window.paste_elements()
    assert window.scene.selectedItems()[0].element["kind"] == item.element["kind"]


def test_faceplates_rename_duplicate_and_delete_from_the_tree(window, monkeypatch):
    name = next(n for n in window.project.faceplates if screen_tree.faceplate_references(window.project, n))
    users = screen_tree.faceplate_references(window.project, name)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("equipo_renombrado", True))
    window.rename_faceplate_from_tree(name)
    assert "equipo_renombrado" in window.project.faceplates and name not in window.project.faceplates
    assert len(screen_tree.faceplate_references(window.project, "equipo_renombrado")) == len(users)
    errors = []
    monkeypatch.setattr(window, "error", errors.append)
    window.tree_delete_faceplate("equipo_renombrado")
    assert errors and "equipo_renombrado" in window.project.faceplates
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("copia_libre", True))
    window.tree_duplicate_faceplate("equipo_renombrado")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.tree_delete_faceplate("copia_libre")
    assert "copia_libre" not in window.project.faceplates


def test_variable_filter_is_explicit_and_new_variables_are_shown(window, monkeypatch):
    window.navigate("variables")
    window.filter.setText("zzz")
    assert window.filter_notice.isVisible() and "0 de" in window.filter_notice.text()
    window.add_variable()
    assert window.filter.text() == "" and not window.filter_notice.isVisible()
    window.new_variable_field.setText("NuevaVariable"); window.new_variable_field.editingFinished.emit()
    pump_events()
    assert window.project.variables[-1]["name"] == "NuevaVariable"


def test_unsaved_changes_are_visible_until_saved(window):
    assert not window.unsaved_label.isVisible()
    window.document_kind, window.document_name = "screens", "10_general"
    window.render_scene()
    window.scene.items()[0].setSelected(True)
    window.duplicate_element()
    assert window.unsaved_label.isVisible()
    window.navigate("alarms")
    assert window.unsaved_label.isVisible()
    window.save_project()
    assert not window.unsaved_label.isVisible()


def test_project_settings_keep_the_retention(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialogButtonBox, QSpinBox
    from abscada.project_settings import edit_project_settings
    def fill():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QSpinBox, "historianRetention").setValue(30)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(0, fill)
    edit_project_settings(window)
    assert window.project.historian["retention_days"] == 30
