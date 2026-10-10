"""Buttons with a list of actions: format, references, permissions, runtime and Studio editor."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import copy
import pytest
from PySide6.QtWidgets import QApplication
from abscada.project import Project
from abscada.dynamics import issues, parameter_writable
from abscada.security import required_permission
from abscada.screen_tree import faceplate_references, rename_faceplate, rename_screen, screen_references
from abscada.runtime import Sample


def button(actions, **extra):
    return dict(id="go", kind="button", x=10, y=10, w=120, h=40, text="Arrancar", action="sequence",
                actions=actions, **extra)


@pytest.fixture
def project(tmp_path):
    variables = [dict(name="Run", type="bool", initial=False, writable=True),
                 dict(name="Speed", type="float", initial=0.0, writable=True),
                 dict(name="Mode", type="int", initial=0, writable=True),
                 dict(name="Level", type="float", initial=1.0, writable=False)]
    steps = [dict(action="set", tag="Speed", value=42.5), dict(action="toggle", tag="Run"),
             dict(action="script", script="log"), dict(action="set", tag="Mode", value=3),
             dict(action="screen", screen="detail")]
    face = dict(width=200, height=100, parameters={"running": "bool"},
                elements=[button([dict(action="set", tag="$running", value=True),
                                  dict(action="faceplate_popup", template="unit", bindings={"running": "$running"})])])
    project = Project(tmp_path, dict(schema_version=1, name="Lists", startup_screen="main", languages=["es", "en"],
                                     default_language="es"), {}, variables, [],
                      {"main": dict(width=800, height=600, elements=[button(steps)]),
                       "detail": dict(width=800, height=600, elements=[])}, {"unit": face})
    project.scripts = {"log": "ctx.write('Mode', 7)\n"}
    project.validate()
    return project


def first(project, screen="main"):
    return project.screens[screen]["elements"][0]


def test_single_action_buttons_are_unchanged_and_lists_validate(project):
    assert first(project)["actions"][0] == dict(action="set", tag="Speed", value=42.5)
    project.screens["main"]["elements"].append(dict(id="old", kind="button", x=0, y=100, w=80, h=30,
                                                    action="set", tag="Mode", value=1))
    project.validate()


@pytest.mark.parametrize("steps, message", [
    ([dict(action="momentary", tag="Run")], "no admitido"),
    ([dict(action="press_release", tag="Mode", press_value=1, release_value=0)], "no admitido"),
    ([dict(action="screen", screen="detail"), dict(action="toggle", tag="Run")], "última acción"),
    ([dict(action="close_popup"), dict(action="toggle", tag="Run")], "última acción"),
    ([dict(action="set", tag="Level", value=2.0)], "solo lectura"),
    ([dict(action="toggle", tag="Speed")], "bool"),
    ([dict(action="set", tag="Mode", value="abc")], "acción 1"),
    ([dict(action="set", tag="Mode")], "valor"),
    ([dict(action="script", script="missing")], "inexistente"),
    ([dict(action="screen", screen="missing")], "inexistente"),
    ([dict(action="set_language", language="fr")], "acción 1"),
    ([dict(action="set", tag="Mode", value=1, press_value=2)], "desconocida"),
    ("not a list", "no es válida"),
])
def test_invalid_lists_are_rejected(project, steps, message):
    first(project)["actions"] = steps
    with pytest.raises(ValueError, match=message):
        project.validate()


def test_list_button_names_variables_in_each_action(project):
    first(project)["tag"] = "Run"
    with pytest.raises(ValueError, match="cada acción"):
        project.validate()


def test_empty_list_is_valid_while_editing_but_reported(project):
    first(project)["actions"] = []
    project.validate()
    assert any("sin acciones" in issue for issue in issues(project))
    first(project)["actions"] = [dict(action="set", tag="", value=1)]
    project.validate()
    assert any("mando sin variable" in issue for issue in issues(project))


def test_references_and_renames_reach_every_action(project):
    assert screen_references(project, "detail") == ["main · go"]
    assert faceplate_references(project, "unit") == ["objeto unit · go"]
    rename_screen(project, "detail", "detalle")
    assert first(project)["actions"][-1]["screen"] == "detalle"
    rename_faceplate(project, "unit", "grupo")
    assert project.faceplates["grupo"]["elements"][0]["actions"][1]["template"] == "grupo"
    project.validate()


def test_permission_and_writable_parameters_follow_the_actions(project):
    assert required_permission(first(project)) == "operate"
    assert required_permission(button([dict(action="screen", screen="detail")])) is None
    assert required_permission(button([dict(action="screen", screen="detail")], permission="recipes")) == "recipes"
    assert parameter_writable(project.faceplates["unit"], "running")


def test_faceplate_instances_resolve_parameters_inside_actions(project):
    project.screens["main"]["elements"].append(dict(id="u1", kind="faceplate", x=0, y=200, w=200, h=100,
                                                    template="unit", bindings={"running": "Run"}))
    project.validate()
    expanded = next(e for e in project.elements("main") if e["id"] == "u1.go")
    assert expanded["actions"][0]["tag"] == "Run"
    assert expanded["actions"][1]["bindings"] == {"running": "Run"}
    # The parameter is written by the list: a read-only variable cannot be bound to it.
    project.screens["main"]["elements"][-1]["bindings"]["running"] = "Level"
    with pytest.raises(ValueError):
        project.validate()


# --- runtime --------------------------------------------------------------------------------

@pytest.fixture
def live(project, monkeypatch):
    from abscada.runtime_window import RuntimeWindow
    app = QApplication.instance() or QApplication([])
    window = RuntimeWindow(project)
    window.running = True
    warnings = []
    monkeypatch.setattr("abscada.runtime_window.QMessageBox.warning", lambda parent, title, text: warnings.append(text))
    window.warnings = warnings
    yield window
    window.running = False
    window.close()
    app.processEvents()


def queued_scripts(window):
    return list(window.runtime.scripts.queue.queue)


def test_click_sends_every_action_in_order_and_navigates_last(live):
    sent = []
    command = live.runtime.command
    live.runtime.command = lambda name, value, session, **kw: sent.append((name, value)) or command(name, value, session, **kw)
    navigated = []
    live.navigate_screen = lambda target, container, source: navigated.append(target)
    live.actuate(first(live.project))
    assert live.warnings == []
    assert sent == [("Speed", 42.5), ("Run", True), ("Mode", 3)]
    assert queued_scripts(live) == [("log", "button", "main")]
    snapshot = live.runtime.snapshot()
    assert (snapshot["Speed"].value, snapshot["Run"].value, snapshot["Mode"].value) == (42.5, True, 3)
    assert navigated == []  # deferred until the click event has finished
    QApplication.processEvents()
    assert navigated == ["detail"]


def test_a_failing_check_sends_nothing(live):
    live.runtime.tags["Run"]["binding"] = dict(connection="plc", address="%DB1.DBX0.0")
    live.runtime._samples["Run"] = Sample(False, "bad", 0)
    live.actuate(first(live.project))
    assert live.warnings and "Acción 2" in live.warnings[0] and "ninguna" in live.warnings[0]
    assert live.runtime.snapshot()["Speed"].value == 0.0
    assert queued_scripts(live) == []


def test_a_failure_while_sending_stops_the_rest_without_undoing(live):
    command = live.runtime.command
    def refuse_mode(name, value, session, **kw):
        if name == "Mode":
            raise ValueError("cola llena")
        return command(name, value, session, **kw)
    live.runtime.command = refuse_mode
    navigated = []
    live.navigate_screen = lambda target, container, source: navigated.append(target)
    live.actuate(first(live.project))
    assert "Acción 4" in live.warnings[0] and "no se deshacen" in live.warnings[0]
    assert live.runtime.snapshot()["Speed"].value == 42.5  # already sent
    assert queued_scripts(live) == [("log", "button", "main")]
    QApplication.processEvents()
    assert navigated == []


def test_permission_is_checked_once_for_the_whole_list(live, monkeypatch):
    asked = []
    monkeypatch.setattr(live, "authorize", lambda element: asked.append(element["id"]) or False)
    live.actuate(first(live.project))
    assert asked == ["go"]
    assert live.runtime.snapshot()["Speed"].value == 0.0


# --- Studio ---------------------------------------------------------------------------------

@pytest.fixture
def studio(project, monkeypatch):
    from abscada.ui import Window
    app = QApplication.instance() or QApplication([])
    project.save()
    window = Window(Project.load(project.root))
    monkeypatch.setattr(window, "error", lambda exc: (_ for _ in ()).throw(AssertionError(f"Unexpected UI error: {exc}")))
    window.show(); app.processEvents()
    yield window
    window.dirty = False
    window.close(); app.processEvents()


def select(studio, element_id):
    studio.render_scene([element_id])
    studio.show_properties()


def test_switching_to_a_list_keeps_the_single_action_as_first_step(studio):
    studio.mutate(lambda: studio.document()["elements"].append(
        dict(id="b2", kind="button", x=0, y=200, w=80, h=30, text="B", action="set", tag="Mode", value=5)))
    select(studio, "b2")
    studio.action_field.setCurrentIndex(studio.action_field.findData("sequence"))
    studio.apply_fields()
    element = next(e for e in studio.document()["elements"] if e["id"] == "b2")
    assert element["action"] == "sequence" and "tag" not in element and "value" not in element
    assert element["actions"] == [dict(action="set", tag="Mode", value=5)]
    assert studio.sequence_button.isVisible()
    studio.action_field.setCurrentIndex(studio.action_field.findData("toggle"))
    studio.tag_field.setCurrentText("Run")
    studio.apply_fields()
    element = next(e for e in studio.document()["elements"] if e["id"] == "b2")
    assert element["action"] == "toggle" and "actions" not in element


def test_actions_dialog_adds_reorders_and_validates(studio):
    from abscada.button_actions_editor import ButtonActionsDialog
    select(studio, "go")
    element = next(e for e in studio.document()["elements"] if e["id"] == "go")
    dialog = ButtonActionsDialog(studio, element)
    assert dialog.list.count() == 5
    dialog.list.setCurrentRow(4)
    dialog.remove()  # the screen change
    dialog.add()
    dialog.type_field.setCurrentIndex(dialog.type_field.findData("set_language"))
    dialog.change_type()
    dialog.language_field.setCurrentText("en")
    dialog.changed()
    dialog.move(-1)
    assert [s["action"] for s in dialog.steps] == ["set", "toggle", "script", "set_language", "set"]
    dialog.check()
    # A navigation that is not the last action is refused and the dialog stays open.
    dialog.list.setCurrentRow(0)
    dialog.type_field.setCurrentIndex(dialog.type_field.findData("close_popup"))
    dialog.change_type()
    with pytest.raises(ValueError, match="última"):
        dialog.check()
    dialog.type_field.setCurrentIndex(dialog.type_field.findData("set"))
    dialog.change_type()
    dialog.tag_field.setCurrentText("Speed")
    dialog.value_field.setText("12,5")
    dialog.changed()
    dialog.check()
    assert dialog.result_steps()[0] == dict(action="set", tag="Speed", value=12.5)
