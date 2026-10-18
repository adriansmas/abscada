"""Script folders (logical, stored in automation.json) and script renaming."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from abscada import script_tree
from abscada.project import Project


@pytest.fixture
def project(tmp_path):
    button = dict(id="go", kind="button", x=0, y=0, w=100, h=30, action="script", script="arranque")
    listed = dict(id="list", kind="button", x=0, y=50, w=100, h=30, action="sequence",
                  actions=[dict(action="set", tag="Modo", value=1), dict(action="script", script="arranque")])
    project = Project(tmp_path, dict(schema_version=1, name="Carpetas", startup_screen="main", languages=["es", "en"],
                                     default_language="es"), {},
                      [dict(name="Modo", type="int", initial=0, writable=True)], [],
                      {"main": dict(width=800, height=600, elements=[button, listed], on_open=["arranque", "abrir"])}, {})
    project.scripts = {"arranque": "ctx.write('Modo', 2)\n", "abrir": "print('arranque')\n", "reloj": "print(1)\n"}
    project.automation = dict(startup=["arranque"], tasks=[dict(id="t", script="arranque", interval_ms=1000, enabled=True)],
                              timeout_seconds=10)
    project.validate()
    return project


def test_old_projects_have_every_script_at_the_root(project):
    assert script_tree.folders(project) == []
    assert [script_tree.folder_of(project, n) for n in project.scripts] == ["", "", ""]
    assert script_tree.choices(project) == [("abrir", "abrir"), ("arranque", "arranque"), ("reloj", "reloj")]


def test_folders_are_logical_and_survive_save_and_reopen(project):
    script_tree.add_folder(project, "", "Proceso")
    script_tree.add_folder(project, "Proceso", "Bombas")
    script_tree.add_folder(project, "", "Vacía")
    script_tree.move_script(project, "arranque", "Proceso/Bombas")
    project.validate()
    project.save()
    assert (project.root / "scripts" / "arranque.py").exists()  # the source does not move
    reopened = Project.load(project.root)
    assert script_tree.folders(reopened) == ["Proceso", "Proceso/Bombas", "Vacía"]
    assert script_tree.folder_of(reopened, "arranque") == "Proceso/Bombas"
    assert script_tree.label(reopened, "arranque") == "Proceso/Bombas/arranque"
    # References keep using the bare name.
    assert reopened.automation["startup"] == ["arranque"]
    assert ("arranque", "Proceso/Bombas/arranque") in script_tree.choices(reopened)


def test_folder_rename_move_and_delete_keep_every_script(project):
    script_tree.add_folder(project, "", "A")
    script_tree.add_folder(project, "A", "B")
    script_tree.move_script(project, "reloj", "A/B")
    script_tree.rename_folder(project, "A", "Proceso")
    assert script_tree.folder_of(project, "reloj") == "Proceso/B"
    with pytest.raises(ValueError, match="Ya existe"):
        script_tree.add_folder(project, "", "proceso")
    script_tree.add_folder(project, "", "Otra")
    script_tree.move_folder(project, "Proceso/B", "Otra")
    assert script_tree.folder_of(project, "reloj") == "Otra/B"
    with pytest.raises(ValueError, match="sí misma"):
        script_tree.move_folder(project, "Otra", "Otra/B")
    script_tree.delete_folder(project, "Otra")
    assert script_tree.folder_of(project, "reloj") == "B"
    assert set(project.scripts) == {"arranque", "abrir", "reloj"}
    script_tree.delete_folder(project, "B")
    assert script_tree.folder_of(project, "reloj") == ""
    assert "script_folders" not in project.automation
    with pytest.raises(ValueError, match="inexistente"):
        script_tree.move_script(project, "reloj", "No/Existe")
    project.validate()


@pytest.mark.parametrize("automation, message", [
    (dict(folders="Proceso"), "folders"),
    (dict(folders=["/Proceso"]), "folders"),
    (dict(script_folders={"reloj": ""}), "script_folders"),
    (dict(script_folders={"falta": "A"}), "inexistente"),
])
def test_invalid_folder_data_is_rejected(project, automation, message):
    project.automation.update(automation)
    with pytest.raises(ValueError, match=message):
        project.validate()


def test_rename_updates_structured_references_and_reports_code_mentions(project):
    script_tree.add_folder(project, "", "Proceso")
    script_tree.move_script(project, "arranque", "Proceso")
    pending = script_tree.rename_script(project, "arranque", "inicio")
    project.validate()
    assert list(project.scripts) == ["inicio", "abrir", "reloj"]
    assert project.automation["startup"] == ["inicio"]
    assert project.automation["tasks"][0]["script"] == "inicio"
    screen = project.screens["main"]
    assert screen["on_open"] == ["inicio", "abrir"]
    assert screen["elements"][0]["script"] == "inicio"
    assert screen["elements"][1]["actions"][1]["script"] == "inicio"
    assert script_tree.folder_of(project, "inicio") == "Proceso"
    assert pending == ["abrir"]  # print('arranque') is only text: reviewed by hand
    with pytest.raises(ValueError, match="ya existe"):
        script_tree.rename_script(project, "inicio", "RELOJ")
    with pytest.raises(ValueError, match="letras"):
        script_tree.rename_script(project, "inicio", "con espacio")
    script_tree.rename_script(project, "inicio", "Inicio")  # only the case changes
    project.validate()


def test_used_scripts_report_their_references(project):
    used = script_tree.references(project, "arranque")
    assert used == ["eventos de inicio", "tarea t", "main · al abrir", "main · go", "main · list"]
    assert script_tree.references(project, "reloj") == []
    script_tree.add_folder(project, "", "Reloj")
    script_tree.move_script(project, "reloj", "Reloj")
    script_tree.delete_script(project, "reloj")
    project.validate()
    assert "script_folders" not in project.automation and script_tree.folders(project) == ["Reloj"]


# --- Studio ---------------------------------------------------------------------------------

@pytest.fixture
def studio(project, monkeypatch):
    from abscada.ui import Window
    app = QApplication.instance() or QApplication([])
    project.save()
    window = Window(Project.load(project.root))
    errors = []
    monkeypatch.setattr(window, "error", lambda exc: errors.append(str(exc)))
    window.errors = errors
    window.notices = []
    monkeypatch.setattr("abscada.automation_editor.QMessageBox.information",
                        lambda parent, title, text: window.notices.append(text))
    window.show(); window.navigate("automation"); app.processEvents()
    yield window
    window.dirty = False
    window.close(); app.processEvents()


def tree_items(editor):
    from abscada.automation_editor import ROLE
    found, stack = [], [editor.tree.topLevelItem(i) for i in range(editor.tree.topLevelItemCount())]
    while stack:
        item = stack.pop(0)
        found.append(item.data(0, ROLE))
        stack[:0] = [item.child(i) for i in range(item.childCount())]
    return found


def test_scripts_tree_creates_moves_renames_and_undoes(studio):
    editor, project = studio.automation_editor, lambda: studio.project
    studio.mutate(lambda: script_tree.add_folder(project(), "", "Proceso"))
    assert tree_items(editor)[0] == ("folder", "Proceso")
    # A new script goes into the selected folder.
    folder_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(folder_item)
    editor.new_name.setText("bombas"); editor.new_name.returnPressed.emit()
    assert script_tree.folder_of(project(), "bombas") == "Proceso" and editor.current == "bombas"
    assert tree_items(editor)[:2] == [("folder", "Proceso"), ("script", "bombas")]
    # Drag a script from the root onto the folder.
    editor.drop(("script", "reloj"), ("folder", "Proceso"))
    assert script_tree.folder_of(project(), "reloj") == "Proceso"
    editor.drop(("script", "reloj"), None)
    assert script_tree.folder_of(project(), "reloj") == ""
    studio.undo()
    assert script_tree.folder_of(project(), "reloj") == "Proceso"
    studio.redo()
    assert script_tree.folder_of(project(), "reloj") == ""
    # Rename keeps references; deleting a used script is refused with its uses.
    editor.rename_script("arranque", "inicio")
    assert project().automation["startup"] == ["inicio"] and editor.current == "inicio"
    assert studio.notices and "abrir" in studio.notices[0]
    editor.remove()
    assert studio.errors and "eventos de inicio" in studio.errors[-1] and "inicio" in project().scripts
    editor.current = "bombas"; editor.remove()
    assert "bombas" not in project().scripts
    assert studio.errors[:-1] == []


def test_selectors_show_folders_and_keep_the_execution_order(studio):
    studio.mutate(lambda: (script_tree.add_folder(studio.project, "", "Zeta"),
                           script_tree.move_script(studio.project, "abrir", "Zeta")))
    assert script_tree.choices(studio.project, ["abrir", "arranque"])[:2] == [("abrir", "Zeta/abrir"), ("arranque", "arranque")]
    studio.navigate("screens")
    studio.render_scene(["go"]); studio.show_properties()
    assert studio.script_field.currentData() == "arranque"
    assert [studio.script_field.itemText(i) for i in range(studio.script_field.count())] == ["arranque", "reloj", "Zeta/abrir"]
    studio.script_field.setCurrentIndex(studio.script_field.findData("abrir"))
    studio.apply_fields()
    assert studio.document()["elements"][0]["script"] == "abrir"


def test_script_limit_dialog_stores_own_limit_or_none(studio, monkeypatch):
    from abscada import automation_editor
    editor, project = studio.automation_editor, lambda: studio.project
    answers = iter([dict(mode="none", seconds=10.0), dict(mode="custom", seconds=2.5), dict(mode="default", seconds=1.0)])

    class Accepted:
        def __init__(self, *args, **kwargs):
            self.answer = next(answers)
        def exec(self):
            return automation_editor.QDialog.DialogCode.Accepted
        def data(self):
            return self.answer
    monkeypatch.setattr(automation_editor, "RecordDialog", Accepted)
    editor.edit_limit("reloj")
    assert project().automation["limits"] == {"reloj": None}
    assert any(editor.tree.topLevelItem(i).text(0) == "reloj  ·  sin límite" for i in range(editor.tree.topLevelItemCount()))
    editor.edit_limit("reloj")
    assert project().automation["limits"] == {"reloj": 2.5}
    editor.edit_limit("reloj")
    assert "limits" not in project().automation
    assert studio.errors == []
