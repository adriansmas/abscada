"""Arrays in types, structure parameters, nested objects, libraries with types and motion dynamics."""
import copy
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import pytest
from abscada.project import Project
from abscada.runtime import Sample
from abscada import dynamics, structures
from abscada.faceplate_libraries import export_library, link, unlink, type_owner
from abscada.project_storage import documents


def pump(**fields):
    value = dict(marcha=False, velocidad=0.0, temps=[0.0, 0.0, 0.0])
    value.update(fields)
    return value


def build(root):
    types = {"Bomba": {"marcha": "bool", "velocidad": "float", "temps": "float[3]"}}
    variables = [
        dict(name="B1", type="Bomba", initial=pump(temps=[1.0, 2.0, 3.0]), writable=True),
        dict(name="Grupo", type="Bomba[2]", initial=[pump(marcha=True), pump()], writable=False),
        dict(name="Niveles", type="float[4]", initial=[0.0, 1.0, 2.0, 3.0], writable=True),
    ]
    inner = dict(width=50, height=50, parameters={"run": "bool", "level": "float"}, elements=[
        dict(id="led", kind="lamp", x=0, y=0, w=50, h=50, tag="$run"),
        dict(id="tank", kind="rectangle", x=0, y=0, w=50, h=50, dynamics={"fill": {"tag": "$level", "min": 0, "max": 10}}),
    ])
    outer = dict(width=100, height=100, parameters={"motor": "Bomba"}, elements=[
        dict(id="sub", kind="faceplate", template="inner", x=0, y=0, w=50, h=50,
             bindings={"run": "$motor.marcha", "level": "$motor.temps[1]"}),
        dict(id="fan", kind="ellipse", x=50, y=50, w=50, h=50, dynamics={
            "spin": {"when": {"tag": "$motor.marcha", "op": "eq", "value": True}, "seconds": 2},
            "states": [{"when": {"tag": "$motor.marcha", "op": "eq", "value": True}, "style": {"color": "#ff0000"}, "blink": True}]}),
        dict(id="go", kind="button", x=0, y=60, w=40, h=20, action="toggle", tag="$motor.marcha"),
        dict(id="more", kind="button", x=50, y=0, w=40, h=20, action="faceplate_popup", template="inner",
             bindings={"run": "$motor.marcha", "level": "$motor.velocidad"}),
    ])
    screen = dict(width=400, height=300, elements=[
        dict(id="p1", kind="faceplate", template="outer", x=10, y=10, w=200, h=200, bindings={"motor": "B1"}),
    ])
    return Project(root, dict(schema_version=1, name="t", startup_screen="main"), types, variables, [],
                   {"main": screen}, {"inner": inner, "outer": outer})


@pytest.fixture
def project(tmp_path):
    result = build(tmp_path / "project")
    result.validate()
    return result


def test_arrays_expand_into_indexed_tags_and_keep_their_settings(project):
    tags = project.tags()
    assert tags["Niveles[3]"]["initial"] == 3.0 and tags["Niveles[0]"]["type"] == "float"
    assert tags["Grupo[1].temps[2]"]["type"] == "float" and tags["Grupo[0].marcha"]["initial"] is True
    project.configure_tag("Grupo[1].temps[2]", 7.5, True, None)
    tags = project.tags()
    assert tags["Grupo[1].temps[2]"]["initial"] == 7.5 and tags["Grupo[1].temps[2]"]["writable"]
    assert tags["Grupo[0].temps[2]"]["initial"] == 0.0 and not tags["Grupo[0].temps[2]"]["writable"]
    project.configure_tag("Niveles[1]", 9, False, None)
    assert project.variables[2]["initial"] == [0.0, 9.0, 2.0, 3.0]
    assert project.variables[2]["overrides"]["[1]"] == {"writable": False}


@pytest.mark.parametrize("change, message", [
    (lambda p: p.variables[2].update(initial=[0.0]), "lista de 4"),
    (lambda p: p.types["Bomba"].update(temps="float[0]"), "Campo inválido"),
    (lambda p: p.types["Bomba"].update(temps="Nada[2]"), "Campo inválido"),
    (lambda p: p.types.update(Ciclo={"yo": "Ciclo[2]"}), "recursivo"),
    (lambda p: p.variables.append(dict(name="X[1]", type="int", initial=0)), "corchetes|puntos"),
])
def test_invalid_arrays_are_rejected(project, change, message):
    change(project)
    with pytest.raises(ValueError, match=message):
        project.validate()


def test_structure_parameters_and_nested_objects_expand_to_real_tags(project):
    elements = {e["id"]: e for e in project.elements("main")}
    assert elements["p1.sub.led"]["tag"] == "B1.marcha"
    assert elements["p1.sub.tank"]["dynamics"]["fill"]["tag"] == "B1.temps[1]"
    assert elements["p1.fan"]["dynamics"]["spin"]["when"]["tag"] == "B1.marcha"
    assert elements["p1.go"]["tag"] == "B1.marcha"
    assert elements["p1.more"]["bindings"] == {"run": "B1.marcha", "level": "B1.velocidad"}
    # The nested object sits inside its container, scaled with it.
    assert (elements["p1.sub.led"]["x"], elements["p1.sub.led"]["w"]) == (10, 100)
    assert len(elements["p1.sub.led"]["_guards"]) == 2


def test_an_element_of_an_array_of_structures_fills_a_structure_parameter(project):
    project.variables[1]["writable"] = True
    project.screens["main"]["elements"][0]["bindings"]["motor"] = "Grupo[1]"
    project.validate()
    assert {e["id"]: e for e in project.elements("main")}["p1.go"]["tag"] == "Grupo[1].marcha"


def test_structure_parameters_match_by_shape(project):
    project.types["Otra"] = {"marcha": "bool", "velocidad": "float", "temps": "float[3]", "extra": "int"}
    project.variables.append(dict(name="O", type="Otra", initial=dict(pump(), extra=1), writable=True))
    project.screens["main"]["elements"][0]["bindings"]["motor"] = "O"
    project.validate()
    project.types["Otra"]["temps"] = "float[2]"
    project.variables[-1]["initial"]["temps"] = [0.0, 0.0]
    with pytest.raises(ValueError, match="Tipo incorrecto en parámetro motor"):
        project.validate()


@pytest.mark.parametrize("binding, message", [
    ("B1.temps", "Tipo incorrecto"),
    ("Niveles", "Tipo incorrecto"),
    ("Grupo[0]", "solo lectura"),
])
def test_wrong_or_read_only_structure_bindings_are_rejected(project, binding, message):
    project.screens["main"]["elements"][0]["bindings"]["motor"] = binding
    with pytest.raises(ValueError, match=message):
        project.validate()


def test_unassigned_structure_parameter_is_allowed_until_linked(project):
    project.screens["main"]["elements"][0]["bindings"]["motor"] = ""
    project.validate()
    elements = {e["id"]: e for e in project.elements("main")}
    assert elements["p1.sub.led"]["tag"] == ""


def test_nesting_cycles_are_rejected(project):
    project.faceplates["inner"]["elements"].append(dict(id="loop", kind="faceplate", template="outer", x=0, y=0, w=5, h=5,
                                                        bindings={"motor": ""}))
    with pytest.raises(ValueError, match="ciclo"):
        project.validate()


def test_nested_binding_types_are_checked(project):
    project.faceplates["outer"]["elements"][0]["bindings"]["run"] = "$motor.velocidad"
    with pytest.raises(ValueError, match="Tipo incorrecto en parámetro run"):
        project.validate()


def test_library_v2_carries_types_nested_objects_and_links_read_only(project, tmp_path):
    project.root.mkdir(parents=True)
    project.save()
    package = export_library(project, ["outer"], tmp_path / "lib.json", "Bombas", "1.0.0")
    assert package["schema_version"] == 2 and set(package["faceplates"]) == {"outer", "inner"}
    assert package["types"] == {"Bomba": project.types["Bomba"]}
    consumer = Project(tmp_path / "consumer", dict(schema_version=1, name="c", startup_screen="main"),
                       {"Mia": dict(project.types["Bomba"], extra="int")},
                       [dict(name="M", type="Mia", initial=dict(pump(), extra=0), writable=True)], [],
                       {"main": dict(width=400, height=300, elements=[])}, {})
    link(consumer, tmp_path / "lib.json", "v")
    assert consumer.types["v__Bomba"] == project.types["Bomba"] and type_owner(consumer, "v__Bomba") == "v"
    assert consumer.faceplates["v__outer"]["parameters"] == {"motor": "v__Bomba"}
    assert consumer.faceplates["v__outer"]["elements"][0]["template"] == "v__inner"
    consumer.screens["main"]["elements"].append(dict(id="i", kind="faceplate", template="v__outer", x=0, y=0, w=100, h=100,
                                                    bindings={"motor": "M"}))
    consumer.variables.append(dict(name="L", type="v__Bomba", initial=pump(), writable=True))
    consumer.root.mkdir(parents=True)
    consumer.save()
    assert json.loads(documents(consumer)["types.json"]) == {"Mia": consumer.types["Mia"]}
    loaded = Project.load(consumer.root)
    assert {e["id"]: e for e in loaded.elements("main")}["i.sub.led"]["tag"] == "M.marcha"
    assert loaded.tags()["L.temps[2]"]["type"] == "float"
    loaded.types["v__Bomba"]["marcha"] = "int"
    with pytest.raises(ValueError, match="solo lectura"):
        loaded.validate()
    with pytest.raises(ValueError, match="en uso"):
        unlink(Project.load(consumer.root), "v")


def test_library_types_need_schema_2(project, tmp_path):
    project.root.mkdir(parents=True)
    package = export_library(project, ["outer"], tmp_path / "lib.json", "Bombas", "1.0.0")
    package["schema_version"] = 1
    (tmp_path / "old.json").write_text(json.dumps(package), encoding="utf-8")
    consumer = build(tmp_path / "c")
    with pytest.raises(ValueError, match="formato 2"):
        link(consumer, tmp_path / "old.json", "v")


def test_libraries_without_types_stay_in_schema_1(project, tmp_path):
    package = export_library(project, ["inner"], tmp_path / "lib.json", "Pilotos", "1.0.0")
    assert package["schema_version"] == 1 and "types" not in package


def samples(**values):
    return {name: Sample(value, "good", 0) for name, value in values.items()}


def test_blinking_state_alternates_with_the_normal_appearance():
    element = dict(id="e", kind="rectangle", x=0, y=0, w=10, h=10, color="#000000", dynamics={
        "states": [{"when": {"tag": "A", "op": "eq", "value": True}, "style": {"color": "#ff0000"}, "blink": True}]})
    on, off = 0.1, 0.6  # first and second half of a 1 Hz period
    assert dynamics.effective(element, samples(A=True), now=on)["color"] == "#ff0000"
    assert dynamics.effective(element, samples(A=True), now=off)["color"] == "#000000"
    assert dynamics.effective(element, samples(A=False), now=on)["color"] == "#000000"
    assert dynamics.animated(element)


def test_rotation_spin_and_fill_follow_their_variables():
    element = dict(id="e", kind="image", x=0, y=0, w=10, h=10, dynamics={
        "rotation": {"tag": "P", "min": 0, "max": 100, "from": 0, "to": 90},
        "spin": {"when": {"tag": "Run", "op": "eq", "value": True}, "seconds": 4},
        "fill": {"tag": "L", "min": 0, "max": 10, "color": "#ff00ff00", "direction": "right"}})
    result = dynamics.effective(element, samples(P=50, Run=False, L=2.5), now=1)
    assert result["_angle"] == 45 and result["_fill"] == (0.25, "#ff00ff00", "right")
    assert dynamics.effective(element, samples(P=50, Run=True, L=99), now=1)["_angle"] == 45 + 90
    assert dynamics.effective(element, samples(P=-10, Run=False, L=-1), now=1)["_fill"][0] == 0
    assert "_angle" not in dynamics.effective(element, {}, design=True)


@pytest.mark.parametrize("change, message", [
    (lambda d: d["fill"].update(tag="Text"), "numérica"),
    (lambda d: d["fill"].update(min=5, max=5), "mayor"),
    (lambda d: d["fill"].update(direction="diagonal"), "Dirección"),
    (lambda d: d["spin"].update(seconds=0), "0,2"),
    (lambda d: d["states"][0].update(blink="yes"), "Estado"),
])
def test_motion_dynamics_are_validated(change, message):
    tags = {"L": dict(type="float"), "Run": dict(type="bool"), "Text": dict(type="string")}
    element = dict(id="e", kind="image", x=0, y=0, w=10, h=10, dynamics={
        "fill": {"tag": "L", "min": 0, "max": 10},
        "spin": {"when": {"tag": "Run", "op": "eq", "value": True}, "seconds": 2},
        "states": [{"when": {"tag": "Run", "op": "eq", "value": True}, "style": {}, "blink": True}]})
    dynamics.validate(element, tags, {})
    change(element["dynamics"])
    with pytest.raises(ValueError, match=message):
        dynamics.validate(element, tags, {})


def test_motion_only_on_supported_elements():
    tags = {"L": dict(type="float")}
    with pytest.raises(ValueError, match="llenado"):
        dynamics.validate(dict(id="b", kind="button", dynamics={"fill": {"tag": "L"}}), tags, {})
    with pytest.raises(ValueError, match="giro"):
        dynamics.validate(dict(id="b", kind="input", dynamics={"rotation": {"tag": "L"}}), tags, {})


def test_fill_paints_only_over_the_drawing():
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import Qt
    from abscada.graphics import draw_element
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.design_mode = False
    host.samples = samples(L=5.0)
    host.project = build(Path("unused"))
    element = dict(id="e", kind="ellipse", x=0, y=0, w=40, h=40, color="#ffffff", stroke_color="#ffffff", filled=True,
                   dynamics={"fill": {"tag": "L", "min": 0, "max": 10, "color": "#ff0000"}})
    image = QImage(40, 40, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    draw_element(painter, element, host)
    painter.end()
    assert QColor(image.pixel(20, 35)).red() == 255 and QColor(image.pixel(20, 35)).green() < 50  # lower half, inside
    assert QColor(image.pixel(20, 5)).green() > 200  # upper half keeps the white figure
    assert QColor.fromRgba(image.pixel(1, 38)).alpha() == 0  # outside the ellipse stays transparent


def test_structure_helpers():
    types = {"T": {"a": "int", "b": "float[2]"}}
    assert structures.leaves(types, "T[2]") == {"[0].a": "int", "[0].b[0]": "float", "[0].b[1]": "float",
                                                "[1].a": "int", "[1].b[0]": "float", "[1].b[1]": "float"}
    assert structures.path_kind(types, {"V": "T[2]"}, "V[1].b") == "float[2]"
    assert structures.path_kind(types, {"V": "T[2]"}, "V[2]") is None
    assert structures.substitute("$m.b[1]", {"m": "V[0]"}) == "V[0].b[1]"
    assert structures.substitute("$m", {"m": ""}) == ""
    assert structures.segments("V[1].b") == [("V", "V"), ("[1]", "V[1]"), ("b", "V[1].b")]
    assert structures.default_value(types, "T[1]") == [{"a": 0, "b": [0.0, 0.0]}]


def test_studio_offers_structures_nests_objects_and_edits_motion(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from abscada.ui import Window
    from abscada.dynamic_editor import DynamicDialog
    app = QApplication.instance() or QApplication([])
    source = build(tmp_path / "studio")
    source.root.mkdir(parents=True)
    source.save()
    window = Window(Project.load(source.root))
    monkeypatch.setattr(window, "error", lambda exc: (_ for _ in ()).throw(AssertionError(str(exc))))
    try:
        window.show(); app.processEvents()
        assert window.popup_binding_options("outer", "motor", "Bomba") == ["B1", "Grupo[0]", "Grupo[1]"]
        window.open_faceplate_template("outer")
        assert window.document_references()["motor.temps[2]"] == "float"
        assert window.popup_binding_options("inner", "run", "bool")[:1] == ["$motor.marcha"]
        assert window.insert_library_object("inner")
        nested = window.project.faceplates["outer"]["elements"][-1]
        assert nested["kind"] == "faceplate" and nested["bindings"] == {"run": "", "level": ""}
        fan = next(e for e in window.project.faceplates["outer"]["elements"] if e["id"] == "fan")
        dialog = DynamicDialog(window, fan)
        motion = dialog.motion
        motion.rotation[0].setChecked(True)
        motion.rotation[1]["tag"].setCurrentText("$motor.velocidad")
        motion.rotation[1]["to"].setValue(180)
        motion.fill[0].setChecked(True)
        motion.fill[1]["tag"].setCurrentText("$motor.temps[0]")
        data = dialog.data()["dynamics"]
        assert data["rotation"] == {"tag": "$motor.velocidad", "min": 0, "max": 100, "from": 0, "to": 180}
        assert data["fill"]["tag"] == "$motor.temps[0]" and data["spin"]["seconds"] == 2
        assert data["states"][0]["blink"] is True
        dialog.validate()
        dialog.close()
    finally:
        window.dirty = False; window.close(); app.processEvents()
