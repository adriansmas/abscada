"""Screens in folders, layouts as ordinary screens and viewers that own their configuration."""
import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from abscada import screen_tree
from abscada.project import Project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def hydro(tmp_path):
    shutil.copytree(ROOT / "examples/hydro", tmp_path / "hydro", ignore=shutil.ignore_patterns("runtime"))
    return Project.load(tmp_path / "hydro")


def test_shipped_hydro_is_organised_in_folders(hydro):
    assert screen_tree.folders(hydro) == ["Alarmas", "Emergentes", "Estructura", "Proceso", "Tendencias", "Utilidades"]
    assert hydro.screens["00_layout"]["folder"] == "Estructura" and screen_tree.is_layout(hydro.screens["00_layout"])
    assert all("layout" not in d for d in hydro.screens.values())


def test_folders_create_rename_move_and_delete(hydro):
    screen_tree.add_folder(hydro, "Proceso", "Grupos")
    screen_tree.move_screen(hydro, "30_grupo1", "Proceso/Grupos")
    screen_tree.move_screen(hydro, "31_grupo2", "Proceso/Grupos")
    with pytest.raises(ValueError, match="Ya existe"):
        screen_tree.add_folder(hydro, "", "proceso")
    screen_tree.rename_folder(hydro, "Proceso", "Planta")
    assert hydro.screens["30_grupo1"]["folder"] == "Planta/Grupos" and "Planta/Grupos" in screen_tree.folders(hydro)
    screen_tree.move_folder(hydro, "Planta/Grupos", "")
    assert hydro.screens["31_grupo2"]["folder"] == "Grupos"
    with pytest.raises(ValueError, match="sí misma"):
        screen_tree.move_folder(hydro, "Planta", "Planta")
    screen_tree.delete_folder(hydro, "Grupos")
    assert "folder" not in hydro.screens["30_grupo1"] and "Grupos" not in screen_tree.folders(hydro)
    hydro.validate()


def test_empty_folders_survive_save_and_load(hydro):
    screen_tree.add_folder(hydro, "", "Borradores")
    hydro.save()
    assert "Borradores" in screen_tree.folders(Project.load(hydro.manifest_path))


def test_rename_screen_updates_every_reference(hydro):
    hydro.manifest["display"] = dict(windows=[dict(screen="80_alarmas")])
    pending = screen_tree.rename_screen(hydro, "80_alarmas", "80_alarmas_activas")
    hydro.validate()
    assert "80_alarmas" not in hydro.screens and "80_alarmas_activas" in hydro.screens
    assert hydro.manifest["display"]["windows"][0]["screen"] == "80_alarmas_activas"
    containers = [e for e in hydro.screens["05_ventana_alarmas"]["elements"] if e["kind"] == "screen_container"]
    assert containers[0]["screen"] == "80_alarmas_activas"
    tabs = [e for e in hydro.screens["81_alarmas_historico"]["elements"] if e.get("action") == "screen"]
    assert "80_alarmas_activas" in {e["screen"] for e in tabs}
    assert isinstance(pending, list)
    # Order in the project is preserved.
    names = list(hydro.screens)
    assert names.index("80_alarmas_activas") < names.index("81_alarmas_historico")
    screen_tree.rename_screen(hydro, "00_layout", "00_inicio")
    assert hydro.manifest["startup_screen"] == "00_inicio"
    with pytest.raises(ValueError):
        screen_tree.rename_screen(hydro, "00_inicio", "10_general")
    with pytest.raises(ValueError):
        screen_tree.rename_screen(hydro, "00_inicio", "con espacios")


def test_delete_screen_is_blocked_while_used(hydro):
    with pytest.raises(ValueError, match="se usa en"):
        screen_tree.delete_screen(hydro, "80_alarmas")
    assert "es la pantalla inicial" in screen_tree.screen_references(hydro, "00_layout")
    views = {e["view"] for e in hydro.screens["99_ayuda"]["elements"] if e["kind"] in screen_tree.VIEWERS}
    for name, document in hydro.screens.items():
        for element in document["elements"]:
            if element.get("screen") == "99_ayuda":
                element["screen"] = "10_general"
    screen_tree.delete_screen(hydro, "99_ayuda")
    assert "99_ayuda" not in hydro.screens and not views
    hydro.validate()


def test_duplicate_screen_copies_viewer_configuration(hydro):
    screen_tree.duplicate_screen(hydro, "72_tend_g1", "72_tend_g1_b")
    original = next(e for e in hydro.screens["72_tend_g1"]["elements"] if e["kind"] == "trend")
    duplicate = next(e for e in hydro.screens["72_tend_g1_b"]["elements"] if e["kind"] == "trend")
    assert duplicate["view"] != original["view"]
    assert hydro.trends[duplicate["view"]] == hydro.trends[original["view"]]
    screen_tree.delete_screen(hydro, "72_tend_g1_b")
    assert duplicate["view"] not in hydro.trends and original["view"] in hydro.trends
    hydro.validate()


def test_old_projects_are_migrated(tmp_path):
    """layout flag → «Layouts» folder; a configuration shared by two viewers is split."""
    shutil.copytree(ROOT / "examples/hydro", tmp_path / "old", ignore=shutil.ignore_patterns("runtime"))
    screens = tmp_path / "old" / "screens"
    for name in ("00_layout", "60_control"):
        data = json.loads((screens / f"{name}.json").read_text(encoding="utf-8"))
        data.pop("folder")
        if name == "00_layout":
            data["layout"] = True
        else:
            next(e for e in data["elements"] if e["kind"] == "trend")["view"] = "produccion"
        (screens / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    project = Project.load(tmp_path / "old")
    assert project.screens["00_layout"]["folder"] == "Layouts" and "layout" not in project.screens["00_layout"]
    views = [e["view"] for d in project.screens.values() for e in d["elements"] if e["kind"] == "trend"]
    assert len(views) == len(set(views))


def test_studio_tree_folders_startup_and_actions(hydro, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QInputDialog
    from abscada.ui import Window
    QApplication.instance() or QApplication([])
    window = Window(hydro)
    try:
        items = {item.data(0, Qt.ItemDataRole.UserRole): item for item in window._tree_items()}
        assert ("section", "trends") not in items and ("folder", "Tendencias") in items
        startup = items[("screens", "00_layout")]
        assert startup.text(0).endswith("▶ inicio") and startup.font(0).bold()
        assert startup.parent() is items[("folder", "Estructura")]
        assert "pantalla de inicio" in window.document_label.text()
        # Dropping a screen on a folder moves it; the move can be undone.
        window.tree_drop(("screens", "30_grupo1"), ("folder", "Tendencias"))
        assert window.project.screens["30_grupo1"]["folder"] == "Tendencias"
        window.undo()
        assert window.project.screens["30_grupo1"]["folder"] == "Proceso"
        # Renaming the open screen keeps it open under the new name.
        window.document_kind, window.document_name = "screens", "10_general"
        window.render_scene()
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("10_vista_general", True))
        window.tree_rename(next(i for i in window._tree_items() if i.data(0, Qt.ItemDataRole.UserRole) == ("screens", "10_general")))
        assert window.document_name == "10_vista_general" and "10_general" not in window.project.screens
        container = next(e for e in window.project.screens["00_layout"]["elements"] if e["id"] == "contenido")
        assert container["screen"] == "10_vista_general"
    finally:
        window.dirty = False
        window.close()
