"""Renaming variables and fields of data types: every reference follows."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import pytest
from abscada.project import Project
from abscada.runtime import Sample
from abscada.storage import Repository, ProjectSampleReader, database_path
from abscada import variable_references as references
from test_structures import build


@pytest.fixture
def project(tmp_path):
    result = build(tmp_path / "project")
    result.connections = [dict(id="plc", protocol="s7", host="127.0.0.1")]
    result.variables[0]["bindings"] = {"B1.marcha": dict(connection="plc", address="%DB1.DBX0.0"),
                                      "B1.temps[2]": dict(connection="plc", address="%DB1.DBD8")}
    result.variables[1]["overrides"] = {"[1].marcha": {"writable": True}}
    screen = result.screens["main"]["elements"]
    screen.append(dict(id="led", kind="lamp", x=0, y=250, w=20, h=20, tag="B1.marcha",
                       dynamics={"visible": {"tag": "Grupo[1].marcha", "op": "eq", "value": True}}))
    screen.append(dict(id="go", kind="button", x=40, y=250, w=40, h=20, action="sequence",
                       actions=[dict(action="set", tag="Niveles[2]", value=1.0),
                                dict(action="faceplate_popup", template="outer", bindings={"motor": "B1"})]))
    result.alarms = dict(categories=[dict(id="c", name="C", color="#d74c4c")], retention_days=30,
                         items=[dict(id="a1", message="Marcha", tag="B1.marcha", category="c", condition="true")])
    result.historian = dict(files=[dict(id="f1", name="Fichero", interval_ms=1000, variables=["B1.velocidad", "Niveles[0]"])],
                            retention_days=7)
    result.trends = {"t": dict(title="Tendencia", window_seconds=600, axes=[dict(id="y")],
                               curves=[dict(id="c1", tag="B1.temps[0]", axis="y")])}
    result.scripts = {"control": 'v = ctx.read("B1.marcha")\nw = ctx.read(\'B1\')\nx = "B10"\n'}
    result.validate()
    return result


def test_renaming_a_variable_moves_every_reference(project):
    assert {where.split(" ")[0] for where, _ in references.usages(project, "B1")} >= {"Pantalla", "Alarma", "Registro", "Tendencia"}
    references.rename_variable(project, "B1", "Bomba1")
    project.validate()
    screen = {e["id"]: e for e in project.screens["main"]["elements"]}
    assert screen["p1"]["bindings"] == {"motor": "Bomba1"}
    assert screen["led"]["tag"] == "Bomba1.marcha"
    assert screen["go"]["actions"][1]["bindings"] == {"motor": "Bomba1"}
    assert project.alarms["items"][0]["tag"] == "Bomba1.marcha"
    assert project.historian["files"][0]["variables"] == ["Bomba1.velocidad", "Niveles[0]"]
    assert project.trends["t"]["curves"][0]["tag"] == "Bomba1.temps[0]"
    assert set(project.variables[0]["bindings"]) == {"Bomba1.marcha", "Bomba1.temps[2]"}
    assert project.tags()["Bomba1.temps[2]"]["binding"]["address"] == "%DB1.DBD8"
    assert references.usages(project, "B1") == []
    assert [dict(old=e["old"], new=e["new"]) for e in project.historian["renames"]] == [dict(old="B1", new="Bomba1")]
    assert isinstance(project.historian["renames"][0]["at"], float)
    assert references.former_names(project, "Bomba1.velocidad") == ["B1.velocidad"]


def test_rename_rejects_bad_or_taken_names(project):
    for name in ("", "a.b", "a[1]", "Grupo"):
        with pytest.raises(ValueError):
            references.rename_variable(project, "B1", name)


def test_renaming_a_field_changes_every_variable_of_the_type(project):
    references.rename_field(project, "Bomba", "marcha", "run")
    project.validate()
    assert list(project.types["Bomba"]) == ["run", "velocidad", "temps"]
    assert project.variables[0]["initial"]["run"] is False and "marcha" not in project.variables[0]["initial"]
    assert project.variables[1]["initial"][0]["run"] is True
    assert project.variables[1]["overrides"] == {"[1].run": {"writable": True}}
    assert set(project.variables[0]["bindings"]) == {"B1.run", "B1.temps[2]"}
    screen = {e["id"]: e for e in project.screens["main"]["elements"]}
    assert screen["led"]["tag"] == "B1.run" and screen["led"]["dynamics"]["visible"]["tag"] == "Grupo[1].run"
    assert project.alarms["items"][0]["tag"] == "B1.run"
    # Inside the object whose parameter is a Bomba.
    outer = project.faceplates["outer"]["elements"]
    assert outer[0]["bindings"]["run"] == "$motor.run"
    assert outer[1]["dynamics"]["spin"]["when"]["tag"] == "$motor.run"
    assert outer[2]["tag"] == "$motor.run"
    assert {e["id"]: e for e in project.elements("main")}["p1.go"]["tag"] == "B1.run"
    with pytest.raises(ValueError, match="ya tiene"):
        references.rename_field(project, "Bomba", "run", "velocidad")


def test_scripts_are_only_changed_where_the_name_is_quoted(project):
    assert references.scripts_mentioning(project, "B1") == ["control"]
    references.replace_in_scripts(project, "B1", "Bomba1")
    assert project.scripts["control"] == 'v = ctx.read("Bomba1.marcha")\nw = ctx.read(\'Bomba1\')\nx = "B10"\n'


def test_history_recorded_before_a_rename_is_still_read(project):
    project.root.mkdir(parents=True)
    repository = Repository(database_path(project))
    now = time.time()
    repository.sample("B1.velocidad", Sample(3.5, "good", now), now)
    repository.connection.commit(); repository.close()
    references.rename_variable(project, "B1", "Bomba1")
    rows = ProjectSampleReader(project).raw_samples("Bomba1.velocidad", now - 10, now + 10)
    assert [row["tag"] for row in rows] == ["Bomba1.velocidad"]


def test_renames_survive_save_and_load(project):
    references.rename_variable(project, "B1", "Bomba1")
    project.root.mkdir(parents=True)
    project.save()
    loaded = Project.load(project.root)
    assert [(e["old"], e["new"]) for e in loaded.historian["renames"]] == [("B1", "Bomba1")]
    loaded.historian["renames"] = [dict(old="X")]
    with pytest.raises(ValueError, match="renames"):
        loaded.validate()


def test_reimporting_a_db_warns_about_used_fields_that_disappear(tmp_path):
    from abscada import tia_import
    from test_tia_import import SOURCE, empty
    project = empty(tmp_path)
    tia_import.apply(project, tia_import.plan(project, SOURCE, db=10, connection="plc"))
    project.screens["main"]["elements"].append(dict(id="l", kind="lamp", x=0, y=0, w=20, h=20, tag="DB_Valvulas.V101.Abierta"))
    project.validate()
    renamed = SOURCE.replace("Abierta : Bool;", "Abierto : Bool;")
    result = tia_import.plan(project, renamed, db=10, connection="plc", replace=True)
    assert "DB_Valvulas.V101.Abierta" in result.warnings[0] and "Renombrar" in result.warnings[0]
    # Renaming the field first keeps the screen working with the new import.
    references.rename_field(project, "MD012_VALVE", "Abierta", "Abierto")
    tia_import.apply(project, tia_import.plan(project, renamed, db=10, connection="plc", replace=True))
    project.validate()
    assert project.screens["main"]["elements"][0]["tag"] == "DB_Valvulas.V101.Abierto"


def test_studio_renames_after_confirmation_and_refuses_deleting_used_variables(project, monkeypatch):
    from PySide6.QtWidgets import QApplication, QInputDialog
    from abscada.ui import Window
    from abscada.dialogs import EditorDialog
    app = QApplication.instance() or QApplication([])
    project.root.mkdir(parents=True)
    project.save()
    window = Window(Project.load(project.root))
    errors = []
    monkeypatch.setattr(window, "error", lambda exc: errors.append(str(exc)))
    try:
        window.show(); app.processEvents()
        window.delete_variable("B1")
        assert errors and "se usa en" in errors[0] and any(v["name"] == "B1" for v in window.project.variables)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Bomba1", True))
        monkeypatch.setattr(EditorDialog, "exec", lambda self: EditorDialog.DialogCode.Accepted)
        window.rename_variable_dialog("B1")
        assert window.project.alarms["items"][0]["tag"] == "Bomba1.marcha"
        assert '"Bomba1.marcha"' in window.project.scripts["control"]
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("run", True))
        window.rename_field_dialog("Bomba1.marcha")
        assert window.project.alarms["items"][0]["tag"] == "Bomba1.run"
        window.undo()
        assert window.project.alarms["items"][0]["tag"] == "Bomba1.marcha"
    finally:
        window.dirty = False; window.close(); app.processEvents()
