import copy
import pytest
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QDialogButtonBox
from abscada.project import Project
from abscada.operation_windows import popup_key, popup_title
from test_operational_ui import operational_studio, operational_project, pump_until
from test_popups import click


DETAIL = dict(title="Detalle", width=300, height=200, parameters=dict(level="float", fault="bool"), elements=[
    dict(id="value", kind="text", x=10, y=10, w=200, h=40, tag="$level", text="Nivel"),
    dict(id="fault", kind="lamp", x=220, y=10, w=40, h=40, tag="$fault"),
    dict(id="set", kind="button", x=10, y=80, w=120, h=40, text="50 %", action="set", tag="$level", value=50.0),
    dict(id="close", kind="button", x=10, y=140, w=120, h=40, text="Cerrar", action="close_popup")])

# Equipment symbol that opens its own detail window, forwarding its parameters.
ICON = dict(width=100, height=60, parameters=dict(level="float", fault="bool"), elements=[
    dict(id="open", kind="button", x=0, y=0, w=100, h=60, text="Equipo", action="faceplate_popup",
         template="detail", bindings=dict(level="$level", fault="$fault"))])


def configure(project):
    project.variables += [dict(name="Level2", type="float", initial=0.0, writable=True),
                          dict(name="Fault2", type="bool", initial=False, writable=True),
                          dict(name="Reading", type="float", initial=0.0, writable=False)]
    project.faceplates.update(detail=copy.deepcopy(DETAIL), icon=copy.deepcopy(ICON))
    project.screens["main"]["elements"] = [
        dict(id="open1", kind="button", x=20, y=20, w=160, h=40, text="Equipo 1", action="faceplate_popup",
             template="detail", bindings=dict(level="Level", fault="Fault")),
        dict(id="unit2", kind="faceplate", x=20, y=100, w=100, h=60, template="icon",
             bindings=dict(level="Level2", fault="Fault2"))]
    project.screens["alarms"] = dict(title="Alarmas", width=400, height=300, elements=[])
    project.validate()
    return project


@pytest.fixture
def studio(operational_studio):
    configure(operational_studio.project)
    operational_studio.render_scene()
    return operational_studio


def button(project, **changes):
    element = copy.deepcopy(project.screens["main"]["elements"][0]); element.update(changes)
    project.screens["main"]["elements"][0] = element
    return element


@pytest.mark.parametrize("changes", [
    dict(template="missing"),
    dict(bindings=dict(level="Level")),
    dict(bindings=dict(level="Fault", fault="Fault")),
    dict(bindings=dict(level="$level", fault="Fault")),
    dict(bindings=dict(level="Reading", fault="Fault")),
    dict(window=dict(monitor=0)),
    dict(window=dict(monitor=2, frameless=True)),
    dict(window=dict(on_top="yes")),
    dict(window=dict(mode="kiosk")),
    dict(modal="yes"),
    dict(title=3)])
def test_invalid_faceplate_popup_rejected(operational_project, changes):
    project = configure(operational_project)
    button(project, **changes)
    with pytest.raises(ValueError):
        project.validate()


@pytest.mark.parametrize("display", [
    dict(main=dict(monitor=17)), dict(main=dict(mode="kiosk")), dict(windows=[dict(screen="missing")]),
    dict(windows=[dict(screen="alarms", on_top=1)]), dict(extra=True), dict(windows={})])
def test_invalid_display_rejected(operational_project, display):
    project = configure(operational_project)
    project.manifest["display"] = display
    with pytest.raises(ValueError):
        project.validate()


def test_nested_popup_bindings_resolve_to_instance_tags_and_title(operational_project):
    project = configure(operational_project)
    project.manifest["display"] = dict(main=dict(monitor=1, mode="maximized"),
                                       windows=[dict(screen="alarms", monitor=2, mode="fullscreen", on_top=True)])
    button(project, window=dict(monitor=3, on_top=True), title="Bomba de carga")
    project.save()
    project = Project.load(project.root)
    expanded = next(e for e in project.elements("main") if e["id"] == "unit2.open")
    assert expanded["bindings"] == dict(level="Level2", fault="Fault2")
    assert popup_title(project, "detail", dict(level="Pump1.flow", fault="Pump1.fault")) == "Detalle · Pump1"
    assert popup_title(project, "detail", dict(level="Level", fault="Fault")) == "Detalle"
    assert popup_title(project, "detail", {}, "Propio") == "Propio"
    assert popup_key("detail", dict(b=1, a=2)) == popup_key("detail", dict(a=2, b=1))


def test_one_window_per_equipment_shared_runtime_and_close(studio):
    studio.start_runtime()
    root = studio.runtime_window
    click(root, 100, 40)
    first_key = popup_key("detail", dict(level="Level", fault="Fault"))
    pump_until(lambda: first_key in root.popups)
    first = root.popups[first_key]
    assert first.windowTitle() == "Detalle" and first.runtime is root.runtime
    # Button inside the faceplate instance on the screen opens a second window for unit 2.
    click(root, 70, 130)
    second_key = popup_key("detail", dict(level="Level2", fault="Fault2"))
    pump_until(lambda: second_key in root.popups)
    second = root.popups[second_key]
    assert second is not first and second.pos() != first.pos()
    assert root.open_faceplate("detail", dict(fault="Fault", level="Level")) is first
    click(second, 70, 100)
    pump_until(lambda: root.samples["Level2"].value == 50.0)
    assert root.samples["Level"].value == 0.0
    assert any(i.element.get("tag") == "Level2" for i in second.scene.items() if hasattr(i, "element"))
    click(second, 70, 160)
    pump_until(lambda: second_key not in root.popups)
    assert first_key in root.popups and root.running


def test_popup_navigated_away_returns_to_faceplate(studio):
    studio.start_runtime()
    root = studio.runtime_window
    popup = root.open_faceplate("detail", dict(level="Level", fault="Fault"))
    popup.select_screen("alarms")
    assert popup.faceplate is None and popup.windowTitle() == "Alarmas"
    assert root.open_faceplate("detail", dict(level="Level", fault="Fault")) is popup
    assert popup.faceplate and popup.windowTitle() == "Detalle"


def test_positions_remembered_per_window(studio):
    studio.start_runtime()
    root = studio.runtime_window
    bindings = dict(level="Level", fault="Fault")
    popup = root.open_faceplate("detail", bindings)
    popup.move(popup.pos() + QPoint(37, 23)); QApplication.processEvents()
    moved = popup.pos()
    popup.close(); QApplication.processEvents()
    reopened = root.open_faceplate("detail", bindings)
    assert reopened is not popup and reopened.pos() == moved


def test_startup_windows_and_missing_monitor(studio):
    studio.project.manifest["display"] = dict(main=dict(mode="normal"),
                                              windows=[dict(screen="alarms", monitor=9, on_top=True)])
    studio.start_runtime()
    root = studio.runtime_window
    assert "display_0" in root.popups
    window = root.popups["display_0"]
    assert window.document_name == "alarms" and window.isVisible()
    assert "Monitor 9 no disponible" in studio.log.toPlainText()
    root.close(); QApplication.processEvents()
    assert not root.popups


def test_inspector_configures_faceplate_popup_and_saves(studio):
    studio.scene.clearSelection()
    item = next(i for i in studio.scene.items() if getattr(i, "element", {}).get("id") == "open1")
    item.setSelected(True)
    assert studio.action_field.currentData() == "faceplate_popup"
    assert studio.popup_template_field.currentText() == "detail"
    assert set(studio.popup_binding_fields) == {"level", "fault"}
    studio.popup_binding_fields["level"].setCurrentText("Level2")
    studio.popup_monitor.setCurrentIndex(studio.popup_monitor.findData(2))
    studio.popup_on_top.setChecked(True)
    studio.popup_mode.setCurrentIndex(studio.popup_mode.findData("maximized"))
    studio.popup_title_field.setText("Bomba 2")
    studio.apply_fields()
    element = studio.project.screens["main"]["elements"][0]
    assert element["bindings"] == dict(level="Level2", fault="Fault")
    assert element["window"] == dict(monitor=2, mode="maximized", on_top=True) and element["title"] == "Bomba 2"
    studio.save_project()
    assert Project.load(studio.project.root).screens["main"]["elements"][0]["window"]["monitor"] == 2
    item = next(i for i in studio.scene.items() if getattr(i, "element", {}).get("id") == "open1")
    item.setSelected(True)
    studio.action_field.setCurrentIndex(studio.action_field.findData("toggle"))
    studio.apply_fields()
    element = studio.project.screens["main"]["elements"][0]
    assert not {"template", "bindings", "title", "window", "modal"} & set(element)


def test_inspector_inside_faceplate_offers_own_parameters(studio):
    studio.open_faceplate_template("icon")
    item = next(i for i in studio.scene.items() if getattr(i, "element", {}).get("id") == "open")
    item.setSelected(True)
    options = [studio.popup_binding_fields["level"].itemText(i) for i in range(studio.popup_binding_fields["level"].count())]
    assert options[0] == "$level" and "Level2" in options


def test_project_settings_edit_operation_windows_with_undo(studio):
    from PySide6.QtWidgets import QComboBox, QSpinBox
    from abscada.project_settings import edit_project_settings
    def fill():
        dialog = QApplication.activeModalWidget()
        add = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Añadir ventana")
        add.click()
        table = dialog.findChild(QTableWidget)
        table.cellWidget(0, 0).setCurrentText("alarms")
        table.cellWidget(0, 1).setCurrentIndex(table.cellWidget(0, 1).findData(2))
        table.cellWidget(0, 2).setCurrentIndex(table.cellWidget(0, 2).findData("fullscreen"))
        scale = dialog.findChild(QComboBox, "runtimeScale")
        scale.setCurrentIndex(scale.findData("stretch"))
        dialog.findChild(QSpinBox, "screenWidth").setValue(1920)
        dialog.findChild(QSpinBox, "screenHeight").setValue(1080)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(0, fill)
    edit_project_settings(studio)
    assert studio.project.manifest["display"] == dict(main=dict(scale="stretch"),
                                                      windows=[dict(screen="alarms", monitor=2, mode="fullscreen")])
    assert studio.project.manifest["screen_defaults"] == dict(width=1920, height=1080)
    studio.undo()
    assert "display" not in studio.project.manifest and "screen_defaults" not in studio.project.manifest
