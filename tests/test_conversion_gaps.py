"""Gaps found converting an InduSoft project: type renames, library pop-ups, formats and motion."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import pytest
from abscada.project import Project
from abscada.runtime import Sample
from abscada import dynamics, variable_references as references
from abscada.faceplate_libraries import export_library, link
from test_structures import build
import validate_library


def samples(**values):
    return {name: Sample(value, "good", 0) for name, value in values.items()}


def test_renaming_a_data_type_changes_variables_types_and_parameters(tmp_path):
    project = build(tmp_path / "p")
    project.types["Planta"] = {"bombas": "Bomba[2]", "principal": "Bomba"}
    project.variables.append(dict(name="P", type="Planta", initial={"bombas": project.variables[1]["initial"], "principal": project.variables[0]["initial"]}))
    project.validate()
    assert set(references.type_usages(project, "Bomba")) == {"Variable B1", "Variable Grupo", "Tipo Planta", "Objeto outer"}
    references.rename_type(project, "Bomba", "Valvula")
    project.validate()
    assert "Bomba" not in project.types and list(project.types)[0] == "Valvula"
    assert project.variables[0]["type"] == "Valvula" and project.variables[1]["type"] == "Valvula[2]"
    assert project.types["Planta"] == {"bombas": "Valvula[2]", "principal": "Valvula"}
    assert project.faceplates["outer"]["parameters"] == {"motor": "Valvula"}
    assert "B1.marcha" in project.tags()   # paths do not change
    for bad in ("", "float", "Planta", "a.b"):
        with pytest.raises(ValueError):
            references.rename_type(project, "Valvula", bad)


def library_with_popups(tmp_path):
    popup = dict(width=200, height=100, parameters={"open": "bool"},
                 elements=[dict(id="b", kind="button", x=0, y=0, w=50, h=20, action="toggle", tag="$open")])
    symbol = dict(width=50, height=50, parameters={"open": "bool", "unit": "string", "decimals": "int"}, elements=[
        dict(id="p", kind="button", x=0, y=0, w=50, h=50, action="faceplate_popup", template="Scr_Cmd_Valve", bindings={"open": "$open"}),
        dict(id="s", kind="button", x=0, y=0, w=50, h=50, action="sequence", actions=[
            dict(action="set", tag="$open", value=True),
            dict(action="faceplate_popup", template="Scr_Cmd_Valve", bindings={"open": "$open"})]),
        dict(id="t", kind="text", x=0, y=0, w=50, h=20, tag="$open",
             dynamics={"unit": {"tag": "$unit"}, "decimals": {"tag": "$decimals"}})])
    variables = [dict(name="V", type="bool", initial=False, writable=True), dict(name="U", type="string", initial="bar"),
                 dict(name="D", type="int", initial=1)]
    author = Project(tmp_path / "a", dict(schema_version=1, name="a", startup_screen="main"), {}, variables, [],
                     {"main": dict(width=100, height=100, elements=[])}, {"Scr_Cmd_Valve": popup, "Valve": symbol})
    author.validate()
    package = export_library(author, ["Valve"], tmp_path / "lib.json", "Cidaut", "1.0.0")
    return package, variables


def test_library_pop_ups_point_to_the_aliased_object(tmp_path):
    package, variables = library_with_popups(tmp_path)
    assert set(package["faceplates"]) == {"Valve", "Scr_Cmd_Valve"}   # the pop-up travels with the symbol
    validate_library.validate(package)                                # lists of actions are accepted
    consumer = Project(tmp_path / "c", dict(schema_version=1, name="c", startup_screen="main"), {}, variables, [],
                       {"main": dict(width=100, height=100, elements=[
                           dict(id="v", kind="faceplate", template="cidaut__Valve", x=0, y=0, w=50, h=50,
                                bindings={"open": "V", "unit": "U", "decimals": "D"})])}, {})
    link(consumer, tmp_path / "lib.json", "cidaut")
    elements = {e["id"]: e for e in consumer.elements("main")}
    assert elements["v.p"]["template"] == "cidaut__Scr_Cmd_Valve"
    assert elements["v.s"]["actions"][1]["template"] == "cidaut__Scr_Cmd_Valve"
    assert elements["v.t"]["dynamics"]["unit"] == {"tag": "U"}


def test_unit_and_decimals_come_from_variables():
    element = dict(id="t", kind="text", x=0, y=0, w=10, h=10, tag="L", unit="m", decimals=2,
                   dynamics={"unit": {"tag": "U"}, "decimals": {"tag": "D"}})
    result = dynamics.effective(element, samples(L=1.5, U="bar", D=3))
    assert (result["unit"], result["decimals"]) == ("bar", 3)
    assert dynamics.effective(element, samples(L=1.5, D=99))["decimals"] == 10
    bad = {"U": Sample("bar", "bad", 0)}
    assert dynamics.effective(element, bad)["unit"] == "m"
    tags = {"L": dict(type="float"), "U": dict(type="string"), "D": dict(type="int")}
    dynamics.validate(element, tags, {})
    with pytest.raises(ValueError, match="unidad"):
        dynamics.validate(dict(element, dynamics={"unit": {"tag": "D"}}), tags, {})
    with pytest.raises(ValueError, match="Solo textos"):
        dynamics.validate(dict(element, kind="lamp"), tags, {})


def test_conditions_combine_with_and():
    both = [{"tag": "A", "op": "eq", "value": True}, {"tag": "L", "op": "gt", "value": 5}]
    element = dict(id="e", kind="rectangle", x=0, y=0, w=10, h=10, color="#000000",
                   dynamics={"visible": both, "states": [{"when": both, "style": {"color": "#ff0000"}}]})
    assert dynamics.permitted(element, samples(A=True, L=6), "visible")
    assert not dynamics.permitted(element, samples(A=True, L=4), "visible")
    assert dynamics.effective(element, samples(A=True, L=6))["color"] == "#ff0000"
    assert dynamics.effective(element, samples(A=False, L=6))["color"] == "#000000"
    tags = {"A": dict(type="bool"), "L": dict(type="float")}
    dynamics.validate(element, tags, {})
    with pytest.raises(ValueError):
        dynamics.validate(dict(element, dynamics={"visible": []}), tags, {})


def test_conditions_with_and_follow_object_parameters_and_renames(tmp_path):
    project = build(tmp_path / "p")
    fan = project.faceplates["outer"]["elements"][1]
    fan["dynamics"]["visible"] = [{"tag": "$motor.marcha", "op": "eq", "value": True},
                                  {"tag": "$motor.velocidad", "op": "gt", "value": 1.0}]
    project.validate()
    expanded = {e["id"]: e for e in project.elements("main")}
    assert [c["tag"] for c in expanded["p1.fan"]["dynamics"]["visible"]] == ["B1.marcha", "B1.velocidad"]
    references.rename_field(project, "Bomba", "velocidad", "rpm")
    assert fan["dynamics"]["visible"][1]["tag"] == "$motor.rpm"


def test_move_and_scale_follow_their_variables():
    element = dict(id="e", kind="image", x=0, y=0, w=10, h=10, dynamics={
        "move": {"tag": "P", "min": 0, "max": 100, "x": 200, "y": -50},
        "scale": {"tag": "S", "min": 0, "max": 10, "from": 1, "to": 3, "axis": "y", "anchor": "bottom"}})
    result = dynamics.effective(element, samples(P=50, S=5))
    assert result["_offset"] == (100, -25) and result["_scale"] == (1.0, 2.0, "bottom")
    assert "_offset" not in dynamics.effective(element, samples(P=0, S=0))
    tags = {"P": dict(type="float"), "S": dict(type="int")}
    dynamics.validate(element, tags, {})
    for change, message in [({"scale": {"tag": "S", "to": 50}}, "0 a 20"), ({"scale": {"tag": "S", "anchor": "corner"}}, "fijo"),
                            ({"move": {"tag": "P", "x": "a"}}, "número")]:
        with pytest.raises(ValueError, match=message):
            dynamics.validate(dict(element, dynamics=change), tags, {})
    with pytest.raises(ValueError, match="desplazamiento"):
        dynamics.validate(dict(element, kind="button", dynamics={"move": {"tag": "P"}}), tags, {})


def test_move_and_scale_are_painted():
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import Qt
    from abscada.graphics import draw_element
    app = QApplication.instance() or QApplication([])
    host = QWidget(); host.design_mode = False; host.project = build(Path("unused"))
    element = dict(id="e", kind="rectangle", x=0, y=0, w=10, h=10, color="#ff0000", stroke_color="#ff0000", filled=True,
                   dynamics={"move": {"tag": "P", "min": 0, "max": 100, "x": 40, "y": 0},
                             "scale": {"tag": "S", "min": 0, "max": 1, "from": 1, "to": 2, "axis": "y", "anchor": "top"}})
    host.samples = samples(P=100, S=1)
    image = QImage(80, 40, QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.white)
    painter = QPainter(image); draw_element(painter, element, host); painter.end()
    red = lambda x, y: QColor(image.pixel(x, y)).green() < 60
    assert not red(5, 5) and red(45, 5) and red(45, 17)   # moved 40 px right and twice as tall


def test_dialog_edits_and_conditions_unit_and_motion(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from abscada.ui import Window
    from abscada.dynamic_editor import DynamicDialog
    app = QApplication.instance() or QApplication([])
    project = build(tmp_path / "studio")
    project.variables += [dict(name="U", type="string", initial="bar"), dict(name="D", type="int", initial=1)]
    project.screens["main"]["elements"].append(dict(id="txt", kind="text", x=0, y=250, w=80, h=20, tag="B1.velocidad"))
    project.root.mkdir(parents=True); project.save()
    window = Window(Project.load(project.root))
    monkeypatch.setattr(window, "error", lambda exc: (_ for _ in ()).throw(AssertionError(str(exc))))
    try:
        window.show(); app.processEvents()
        text = window.project.screens["main"]["elements"][-1]
        dialog = DynamicDialog(window, text)
        dialog.format["unit"].setCurrentText("U"); dialog.format["decimals"].setCurrentText("D")
        dialog.visible.active.setChecked(True)
        dialog.visible.rows[0][1].tag.setCurrentText("B1.marcha")
        dialog.visible.add(None)
        dialog.visible.rows[1][1].tag.setCurrentText("Niveles[0]")
        dialog.motion.move[0].setChecked(True)
        dialog.motion.move[1]["tag"].setCurrentText("B1.velocidad"); dialog.motion.move[1]["x"].setValue(30)
        data = dialog.data()["dynamics"]
        assert data["unit"] == {"tag": "U"} and data["decimals"] == {"tag": "D"}
        assert [c["tag"] for c in data["visible"]] == ["B1.marcha", "Niveles[0]"]
        assert data["move"]["x"] == 30
        dialog.validate()
        dialog.visible.remove(dialog.visible.rows[1])
        assert dialog.data()["dynamics"]["visible"]["tag"] == "B1.marcha"
        dialog.close()
    finally:
        window.dirty = False; window.close(); app.processEvents()


def test_studio_renames_a_data_type(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QInputDialog
    from abscada.ui import Window
    app = QApplication.instance() or QApplication([])
    project = build(tmp_path / "studio"); project.root.mkdir(parents=True); project.save()
    window = Window(Project.load(project.root))
    monkeypatch.setattr(window, "error", lambda exc: (_ for _ in ()).throw(AssertionError(str(exc))))
    try:
        window.show(); app.processEvents()
        window.navigate("types"); window.refresh_catalogs()
        window.types_table.selectRow(list(window.project.types).index("Bomba"))
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Valvula", True))
        window.rename_type_dialog()
        assert window.project.variables[1]["type"] == "Valvula[2]"
        window.undo()
        assert window.project.variables[1]["type"] == "Bomba[2]"
    finally:
        window.dirty = False; window.close(); app.processEvents()
