"""Pop-ups chosen by conditions and array elements chosen by a variable index."""
import copy
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from abscada.project import Project
from abscada.runtime import Sample
from abscada import button_actions, screen_tree, variable_references as references
from abscada.faceplate_libraries import export_library, link
from abscada.graphics import ElementItem
from test_operational_ui import operational_project, operational_studio, pump_until


def configure(project):
    project.types = {"Juego": {"temp": "float", "tiempo": "int"}}
    project.variables += [
        dict(name="Mode", type="int", initial=0, writable=True),
        dict(name="Sel", type="int", initial=1, writable=True),
        dict(name="Sets", type="Juego[1..3]", writable=True,
             initial=[dict(temp=10.0, tiempo=1), dict(temp=20.0, tiempo=2), dict(temp=30.0, tiempo=3)]),
    ]
    show = lambda name: dict(width=200, height=100, parameters={"p": "float"}, title=name,
                             elements=[dict(id="v", kind="text", x=0, y=0, w=100, h=20, tag="$p")])
    project.faceplates = {
        "Normal": show("Normal"), "Manual": show("Manual"),
        "SetPopup": dict(width=200, height=100, parameters={"juegos": "Juego[1..3]", "sel": "int"}, elements=[
            dict(id="temp", kind="input", x=0, y=0, w=100, h=20, tag="$juegos[$sel].temp"),
            dict(id="led", kind="lamp", x=0, y=30, w=20, h=20, tag="Fault",
                 dynamics={"visible": {"tag": "$juegos[$sel].tiempo", "op": "gt", "value": 1}})]),
    }
    project.screens["main"]["elements"] = [
        dict(id="open", kind="button", x=20, y=20, w=160, h=40, text="Abrir", action="faceplate_popup",
             template="Normal", bindings={"p": "Level"},
             variants=[dict(when=[{"tag": "Mode", "op": "eq", "value": 2}, {"tag": "Fault", "op": "eq", "value": False}],
                            template="Manual", bindings={"p": "Level"}, title="Manual")]),
        dict(id="sets", kind="button", x=20, y=80, w=160, h=40, text="Juegos", action="faceplate_popup",
             template="SetPopup", bindings={"juegos": "Sets", "sel": "Sel"}),
        dict(id="actual", kind="text", x=20, y=140, w=160, h=30, tag="Sets[Sel].temp"),
    ]
    project.validate()
    return project


def samples(**values):
    return {name: Sample(value, "good", 0) for name, value in values.items()}


def test_first_alternative_whose_condition_holds_is_opened(operational_project):
    project = configure(operational_project)
    button = project.screens["main"]["elements"][0]
    assert button_actions.choose_popup(button, samples(Mode=2, Fault=False))[0] == "Manual"
    assert button_actions.choose_popup(button, samples(Mode=2, Fault=True))[0] == "Normal"
    assert button_actions.choose_popup(button, samples(Mode=0, Fault=False))[2] == ""


@pytest.mark.parametrize("change, message", [
    (lambda v: v.update(template="Nada"), "inexistente"),
    (lambda v: v.update(when={"tag": "Nada", "op": "eq", "value": 1}), "Condición"),
    (lambda v: v.update(bindings={}), "incompletos"),
    (lambda v: v.update(extra=1), "condición y objeto"),
])
def test_alternatives_are_validated(operational_project, change, message):
    project = configure(operational_project)
    change(project.screens["main"]["elements"][0]["variants"][0])
    with pytest.raises(ValueError, match=message):
        project.validate()


def test_alternatives_follow_renames_and_travel_with_libraries(operational_project, tmp_path):
    project = configure(operational_project)
    assert any("open" in where for where, _ in references.usages(project, "Level"))
    screen_tree.rename_faceplate(project, "Manual", "Mantenimiento")
    assert project.screens["main"]["elements"][0]["variants"][0]["template"] == "Mantenimiento"
    assert screen_tree.faceplate_references(project, "Mantenimiento")
    project.faceplates["Panel"] = dict(width=200, height=60, parameters={"p": "float", "mode": "int"}, elements=[
        dict(id="b", kind="button", x=0, y=0, w=50, h=20, action="faceplate_popup", template="Normal", bindings={"p": "$p"},
             variants=[dict(when={"tag": "$mode", "op": "eq", "value": 2}, template="Mantenimiento", bindings={"p": "$p"})])])
    project.validate()
    package = export_library(project, ["Panel"], tmp_path / "lib.json", "Paneles", "1.0.0")
    assert set(package["faceplates"]) == {"Panel", "Normal", "Mantenimiento"}
    consumer = Project(tmp_path / "c", dict(schema_version=1, name="c", startup_screen="main"), {},
                       [dict(name="L", type="float", initial=0.0), dict(name="M", type="int", initial=0)], [],
                       {"main": dict(width=100, height=100, elements=[
                           dict(id="panel", kind="faceplate", template="lib__Panel", x=0, y=0, w=200, h=60, bindings={"p": "L", "mode": "M"})])}, {})
    link(consumer, tmp_path / "lib.json", "lib")
    button = next(e for e in consumer.elements("main") if e["id"] == "panel.b")
    assert button["variants"][0] == dict(when={"tag": "M", "op": "eq", "value": 2}, template="lib__Mantenimiento", bindings={"p": "L"})


def test_variable_indices_are_validated_and_renamed(operational_project):
    project = configure(operational_project)
    for path, message in [("Sets[Level].temp", "entera"), ("Sets[Sel].nada", "inválida"), ("Level[Sel]", "inválida")]:
        broken = copy.deepcopy(project)
        broken.screens["main"]["elements"][2]["tag"] = path
        with pytest.raises(ValueError, match=message):
            broken.validate()
    references.rename_variable(project, "Sel", "Indice")
    assert project.screens["main"]["elements"][2]["tag"] == "Sets[Indice].temp"
    assert project.screens["main"]["elements"][1]["bindings"]["sel"] == "Indice"
    references.rename_field(project, "Juego", "temp", "temperatura")
    assert project.screens["main"]["elements"][2]["tag"] == "Sets[Indice].temperatura"
    assert project.faceplates["SetPopup"]["elements"][0]["tag"] == "$juegos[$sel].temperatura"
    project.validate()


def tags_on_screen(window):
    return {item.element["id"]: item.element.get("tag") for item in window.scene.items() if isinstance(item, ElementItem)}


def test_runtime_opens_the_alternative_and_follows_the_index(operational_studio):
    window = operational_studio
    configure(window.project)
    window.render_scene()
    window.start_runtime()
    root = window.runtime_window
    assert tags_on_screen(root)["actual"] == "Sets[1].temp"
    root.actuate(dict(kind="button", id="x", action="set", tag="Mode", value=2))
    pump_until(lambda: root.samples["Mode"].value == 2)
    button = root.project.screens["main"]["elements"][0]
    root.click_action(button, None)()
    pump_until(lambda: any(isinstance(key, tuple) and key[1] == "Manual" for key in root.popups))
    # The index changes: the screen shows another element of the array, and so does the pop-up.
    root.click_action(root.project.screens["main"]["elements"][1], None)()
    pump_until(lambda: any(isinstance(key, tuple) and key[1] == "SetPopup" for key in root.popups))
    popup = next(p for key, p in root.popups.items() if isinstance(key, tuple) and key[1] == "SetPopup")
    assert tags_on_screen(popup)["faceplate.temp"] == "Sets[1].temp"
    root.actuate(dict(kind="button", id="x", action="set", tag="Sel", value=3))
    pump_until(lambda: tags_on_screen(root).get("actual") == "Sets[3].temp")
    pump_until(lambda: tags_on_screen(popup).get("faceplate.temp") == "Sets[3].temp")
    assert tags_on_screen(popup)["faceplate.led"] == "Fault"
    # Writing through the indexed input reaches the selected element.
    popup.actuate(dict(kind="input", id="faceplate.temp", tag="Sets[3].temp"), entry=True, text="42")
    pump_until(lambda: root.samples["Sets[3].temp"].value == 42.0)
    assert root.samples["Sets[1].temp"].value == 10.0


def test_studio_edits_alternatives_and_accepts_typed_indexed_bindings(operational_studio, monkeypatch):
    from abscada.popup_variants_editor import VariantsDialog, VariantDialog, binding_combo, combo_value, edit_variants
    from abscada.dialogs import EditorDialog
    window = operational_studio
    configure(window.project)
    window.render_scene()
    button = window.project.screens["main"]["elements"][0]
    dialog = VariantDialog(window, button, {})
    dialog.condition.rows[0][1].tag.setCurrentText("Fault")
    dialog.template.setCurrentText("Manual")
    assert combo_value(dialog.fields["p"]) == "Level"       # same parameter as the button's object
    dialog.validate()
    variant = dialog.variant()
    assert variant["template"] == "Manual" and variant["when"]["tag"] == "Fault"
    dialog.close()
    combo = binding_combo(window, "SetPopup", "juegos", "Juego[1..3]", "")
    combo.setCurrentText("Sets")
    assert combo_value(combo) == "Sets"
    combo.setCurrentText("Sets[Sel]")      # typed by hand: not in the list
    assert combo_value(combo) == "Sets[Sel]"
    monkeypatch.setattr(VariantsDialog, "exec", lambda self: (self.variants.append(variant), EditorDialog.DialogCode.Accepted)[1])
    edit_variants(window, button)
    assert window.project.screens["main"]["elements"][0]["variants"][-1]["template"] == "Manual"
    assert len(window.project.screens["main"]["elements"][0]["variants"]) == 2
