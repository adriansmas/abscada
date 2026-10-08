"""«Librerías»: the standard library, folders for the project's objects and their use in Studio."""
import copy
import pytest
from PySide6.QtCore import QMimeData, QPointF
from PySide6.QtWidgets import QInputDialog
from abscada import screen_tree
from abscada.dynamics import effective
from abscada.faceplate_libraries import owner
from abscada.project import Project
from abscada.project_storage import documents
from abscada.runtime import Sample
from abscada.system_library import FOLDER, PREFIX, SYSTEM, is_system, templates, title
from test_operational_ui import operational_studio, operational_project


def test_standard_library_is_available_read_only_and_never_saved(operational_project):
    project = operational_project
    names = [n for n in project.faceplates if n.startswith(PREFIX)]
    assert len(names) == len(templates()) >= 40
    assert owner(project, "estandar__valvula_manual") == SYSTEM and is_system("estandar__deposito_vertical")
    assert title("estandar__deposito_vertical") == "Depósito vertical"
    assert not any(PREFIX in key for key in documents(project))
    project.faceplates["estandar__silo"]["width"] = 1
    with pytest.raises(ValueError, match="solo lectura"):
        project.validate()
    project.faceplates["estandar__silo"] = templates()["estandar__silo"]
    project.faceplates["estandar__mio"] = copy.deepcopy(project.faceplates["estandar__silo"])
    with pytest.raises(ValueError, match="reservado"):
        project.validate()


def test_projects_built_in_code_also_see_it(tmp_path):
    project = Project(tmp_path, dict(schema_version=1, name="P", startup_screen="main"), {}, [], [],
                      {"main": dict(width=800, height=600, elements=[
                          dict(id="v", kind="faceplate", x=0, y=0, w=100, h=64, template="estandar__valvula_manual", bindings={})])}, {})
    project.validate()
    assert project.asset("library://estandar/graficos/valvula_manual.svg") == FOLDER / "graficos" / "valvula_manual.svg"
    with pytest.raises(ValueError):
        project.asset("library://estandar/../library.json")


def test_every_symbol_is_a_valid_svg():
    from PySide6.QtSvg import QSvgRenderer
    files = list(FOLDER.rglob("*.svg"))
    assert len(files) >= 55
    for path in files:
        assert QSvgRenderer(str(path)).isValid(), path.name


def test_animated_object_switches_symbol_with_its_variables(operational_project):
    project = operational_project
    project.screens["main"]["elements"] = [dict(id="b1", kind="faceplate", x=10, y=10, w=100, h=100,
                                                template="estandar__bomba_estado", bindings=dict(marcha="Fault", fallo="Fault"))]
    project.validate()
    image = next(e for e in project.elements("main") if e["id"] == "b1.simbolo")
    def source(value, quality="good"):
        return effective(image, {"Fault": Sample(value, quality, 0)})["source"]
    assert source(False).endswith("bomba_paro.svg")
    assert source(True).endswith("bomba_fallo.svg")       # fallo wins over marcha
    assert source(True, "bad").endswith("bomba_dudoso.svg")


def test_library_folders(operational_project):
    project = operational_project
    project.faceplates["valvula_propia"] = dict(width=80, height=60, parameters={}, elements=[])
    screen_tree.add_folder(project, "", "Válvulas", "faceplates")
    screen_tree.add_folder(project, "Válvulas", "Agua", "faceplates")
    screen_tree.move_faceplate(project, "valvula_propia", "Válvulas/Agua")
    assert project.faceplates["valvula_propia"]["folder"] == "Válvulas/Agua"
    assert screen_tree.folders(project, "faceplates") == ["Válvulas", "Válvulas/Agua"]
    assert screen_tree.folders(project) == []  # screens keep their own folders
    screen_tree.rename_folder(project, "Válvulas", "Valvulería", "faceplates")
    assert project.faceplates["valvula_propia"]["folder"] == "Valvulería/Agua"
    screen_tree.delete_folder(project, "Valvulería", "faceplates")
    assert project.faceplates["valvula_propia"]["folder"] == "Agua"
    with pytest.raises(ValueError, match="no se pueden mover"):
        screen_tree.move_faceplate(project, "estandar__silo", "Agua")
    project.validate(); project.save()
    reloaded = Project.load(project.root)
    assert reloaded.faceplates["valvula_propia"]["folder"] == "Agua" and reloaded.manifest["library_folders"] == ["Agua"]
    screen_tree.duplicate_faceplate(reloaded, "estandar__silo", "mi_silo")
    assert "folder" not in reloaded.faceplates["mi_silo"] and not owner(reloaded, "mi_silo")
    reloaded.validate()


def test_studio_tree_insert_and_picker(operational_studio, monkeypatch):
    window = operational_studio
    tree = window.navigation
    titles = {tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())}
    assert "Librerías" in titles
    libraries = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0) == "Librerías")
    assert [libraries.child(i).text(0) for i in range(libraries.childCount())][:2] == ["Proyecto", "Estándar (sistema)"]
    standard = libraries.child(1)
    assert {standard.child(i).text(0) for i in range(standard.childCount())} == {"Gráficos", "Objetos"}
    # A static symbol has no parameters: it goes straight onto the screen.
    assert window.insert_library_object("estandar__deposito_vertical", QPointF(300, 200))
    element = window.project.screens["main"]["elements"][-1]
    assert element["template"] == "estandar__deposito_vertical" and (element["w"], element["h"]) == (100, 140)
    assert (element["x"], element["y"]) == (250, 130)  # dropped by its centre
    # An animated object is placed without variables; they are assigned afterwards.
    assert window.insert_library_object("estandar__valvula_estado")
    assert window.project.screens["main"]["elements"][-1]["bindings"] == {"abierta": ""}  # variables are assigned afterwards
    window.save_project()
    assert not (window.project.root / "faceplates" / "estandar__valvula_estado.json").exists()
    window.undo()
    assert window.project.screens["main"]["elements"][-1]["template"] == "estandar__deposito_vertical"
    mime = QMimeData(); mime.setData("application/x-abscada-template", b"estandar__silo")
    assert window.view.accepts(mime)


def test_picker_filters_and_returns_a_template(operational_studio):
    from abscada.library_browser import LibraryPicker
    picker = LibraryPicker(operational_studio, operational_studio.project)
    picker.filter.setText("mariposa")
    visible = []
    def walk(item):
        if not item.isHidden():
            value = item.data(0, 256)
            if value and value[0] == "faceplates":
                visible.append(value[1])
            for i in range(item.childCount()):
                walk(item.child(i))
    for i in range(picker.tree.topLevelItemCount()):
        walk(picker.tree.topLevelItem(i))
    assert visible == ["estandar__valvula_mariposa"]
    picker.close()
