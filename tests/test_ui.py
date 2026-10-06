import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import copy
import pytest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTreeWidget
from PySide6.QtCore import Qt, QPointF, QPoint, QMimeData
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from abscada.project import Project
from abscada.ui import Window, Toolbox
from test_core import DEMO, wait_for


def test_selection_changes_do_not_show_orphan_windows(studio):
    def visible_windows():
        return [widget for widget in QApplication.topLevelWidgets()
                if widget.isVisible() and widget.windowType() == Qt.WindowType.Window]

    assert visible_windows() == [studio]
    for _ in range(3):
        studio.scene.items()[0].setSelected(True)
        QApplication.processEvents()
        studio.scene.clearSelection()
        QApplication.processEvents()
        assert visible_windows() == [studio]
        assert studio.screen_properties.isVisible()


@pytest.fixture
def studio(tmp_path, monkeypatch, plc_project):
    app = QApplication.instance() or QApplication([])
    project = copy.deepcopy(plc_project)
    project.root = tmp_path
    project.save()
    window = Window(project)
    def fail(exc):
        raise AssertionError(f"Unexpected UI error: {exc}")
    monkeypatch.setattr(window, "error", fail)
    window.show()
    app.processEvents()
    yield window
    window.dirty = False
    window.stop_runtime()
    window.close()
    app.processEvents()


def test_toolbox_click_adds_and_selects_element(studio):
    window = studio
    assert window.toolbox.isVisible()
    assert window.samples == {}
    assert len(window.scene.items()) == 6
    header = window.toolbox.item(0)
    assert header.data(Qt.ItemDataRole.UserRole) is None and header.text() == "INDICADORES Y MANDOS"
    QTest.mouseClick(window.toolbox.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.toolbox.visualItemRect(header).center())
    assert len(window.scene.items()) == 6
    item = window.toolbox.item(1)
    QTest.mouseClick(window.toolbox.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.toolbox.visualItemRect(item).center())
    assert len(window.scene.items()) == 7
    assert len(window.scene.selectedItems()) == 1
    assert window.scene.selectedItems()[0].element["kind"] == "text"
    assert window.inspector_fields.isVisible()


def test_properties_persist_and_history_restores(studio):
    window = studio
    item = next(i for i in window.scene.items() if i.element["id"] == "header")
    item.setSelected(True)
    window.property_fields["w"].setValue(900)
    window.text_field.setText("Edited header")
    window.apply_fields()
    assert window.project.screens["overview"]["elements"][0]["w"] == 900
    window.undo()
    assert window.project.screens["overview"]["elements"][0]["w"] == 940
    window.redo()
    assert window.project.screens["overview"]["elements"][0]["text"] == "Edited header"
    window.save_project()
    assert Project.load(window.project.root).screens["overview"]["elements"][0]["w"] == 900


def test_runtime_is_an_independent_snapshot_and_editor_stays_editable(studio):
    window = studio
    window.start_runtime()
    runtime_window = window.runtime_window
    assert runtime_window.isWindow() and runtime_window.isVisible()
    assert window.isVisible()
    assert window.design_mode and not runtime_window.design_mode
    assert window.samples == {}
    assert len(window.scene.items()) == 6
    assert len(runtime_window.scene.items()) == 14
    assert not runtime_window.findChildren(Toolbox)
    assert not runtime_window.findChildren(QTreeWidget)
    assert not runtime_window.findChildren(QPlainTextEdit)
    wait_for(lambda: runtime_window.runtime.snapshot()["Pump1.setpoint"].quality == "good")
    window.refresh()
    assert window.samples == {}
    assert window.mode_label.text() == "MODO DISEÑO"
    original = copy.deepcopy(runtime_window.project.screens)
    window.add_element("lamp")
    assert len(window.scene.items()) == 7
    assert runtime_window.project.screens == original
    window.start_runtime()
    assert window.runtime_window is runtime_window
    model = runtime_window.runtime
    assert runtime_window.close()
    assert window.runtime_window is None
    assert not model._thread.is_alive()
    assert window.isVisible()
    window.start_runtime()
    assert len(window.runtime_window.scene.items()) == 15


def test_runtime_button_writes_and_closes_cleanly(studio):
    window = studio
    window.start_runtime()
    live = window.runtime_window
    wait_for(lambda: live.runtime.snapshot()["Pump1.running"].quality == "good")
    live.refresh()
    QApplication.processEvents()
    command = next(i for i in live.scene.items() if i.element["id"] == "pump1.command")
    old = live.runtime.snapshot()["Pump1.running"].value
    point = live.view.mapFromScene(command.mapToScene(QPointF(command.element["w"]/2, command.element["h"]/2)))
    QTest.mouseClick(live.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    wait_for(lambda: live.runtime.snapshot()["Pump1.running"].value is not old)
    assert not live.scene.selectedItems()
    assert window.stop_runtime()
    assert window.runtime is None


def test_duplicate_delete_and_undo(studio):
    studio.add_element("button")
    studio.duplicate_element()
    assert len(studio.scene.items()) == 8
    ids = [e["id"] for e in studio.document()["elements"]]
    assert len(set(ids)) == len(ids)
    studio.delete_element()
    assert len(studio.scene.items()) == 7
    studio.undo()
    assert len(studio.scene.items()) == 8


def test_resize_handle_and_move_are_undoable(studio):
    studio.add_element("text", QPointF(100, 100))
    studio.snap_action.setChecked(False)
    item = studio.scene.selectedItems()[0]
    identity = item.element["id"]
    corner = studio.view.mapFromScene(item.mapToScene(QPointF(item.element["w"]-2, item.element["h"]-2)))
    QTest.mousePress(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(studio.view.viewport(), corner+QPoint(30, 20), delay=30)
    QTest.mouseRelease(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=corner+QPoint(30, 20))
    changed = next(e for e in studio.document()["elements"] if e["id"] == identity)
    assert changed["w"] > 180 and changed["h"] > 48
    studio.undo()
    restored = next(e for e in studio.document()["elements"] if e["id"] == identity)
    assert restored["w"] == 180 and restored["h"] == 48


def test_drop_adds_at_canvas_position(studio):
    mime = QMimeData()
    mime.setData("application/x-abscada-element", b"lamp")
    point = studio.view.mapFromScene(QPointF(200, 200))
    enter = QDragEnterEvent(point, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(studio.view.viewport(), enter)
    drop = QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(studio.view.viewport(), drop)
    assert drop.isAccepted()
    item = studio.scene.selectedItems()[0]
    assert item.element["kind"] == "lamp"
    assert abs(item.element["x"]-200) <= 2


def test_navigation_and_filtering(studio):
    studio.navigate("variables")
    assert studio.pages.currentIndex() == 1
    studio.filter.setText("Pump1")
    assert studio.table.topLevelItemCount() == 1
    assert studio.table.topLevelItem(0).childCount() == 3
    assert studio.table.topLevelItem(0).isExpanded()
    studio.navigate("connections")
    assert studio.connections_table.rowCount() == 1
    studio.navigate("types")
    assert studio.types_table.rowCount() == 1
    studio.navigate("faceplates")
    assert studio.document_kind == "faceplates"
    studio.start_runtime()
    assert studio.document_kind == "faceplates"
    assert studio.runtime_window.document_name == "overview"


def test_reloading_updates_catalogs_and_clears_history(studio):
    studio.add_element("text")
    assert studio.undo_action.isEnabled()
    studio.replace_project(studio.project.root)
    assert len(studio.scene.items()) == 6
    assert not studio.undo_stack
    assert not studio.dirty


def test_editor_canvas_is_unchanged_by_acquisition(studio):
    before = studio.view.viewport().grab().toImage()
    studio.start_runtime()
    wait_for(lambda: studio.runtime.snapshot()["Pump1.flow"].quality == "good")
    studio.refresh()
    QApplication.processEvents()
    after = studio.view.viewport().grab().toImage()
    assert before == after


def test_button_set_action_has_an_editable_typed_value(studio):
    studio.add_element("button")
    studio.tag_field.setCurrentText("Pump1.setpoint")
    studio.apply_fields()
    studio.action_field.setCurrentIndex(1)
    studio.apply_fields()
    assert studio.value_field.isEnabled()
    assert studio.scene.selectedItems()[0].element["value"] == 0.0
    studio.value_field.setText("34.5")
    studio.apply_fields()
    assert studio.scene.selectedItems()[0].element["value"] == 34.5


def test_regular_connection_form_creates_a_connection(studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLineEdit, QComboBox
    def fill():
        dialog = QApplication.activeModalWidget()
        fields = dialog.findChildren(QLineEdit)
        fields[0].setText("plc_test")
        dialog.findChildren(QComboBox)[0].setCurrentIndex(0)
        dialog.accept()
    QTimer.singleShot(0, fill)
    studio.connection_form(None)
    assert studio.project.connections[-1]["id"] == "plc_test"
    assert studio.project.connections[-1]["protocol"] == "s7"


def test_regular_variable_form_creates_a_variable(studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLineEdit
    def fill():
        dialog = QApplication.activeModalWidget()
        fields = dialog.findChildren(QLineEdit)
        fields[0].setText("NewTemperature")
        fields[1].setText("23.5")
        dialog.accept()
    QTimer.singleShot(0, fill)
    studio.variable_form(None)
    assert studio.project.tags()["NewTemperature"]["initial"] == 23.5


def test_screen_settings_without_json(studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSpinBox
    def fill():
        dialog = QApplication.activeModalWidget()
        dialog.findChildren(QSpinBox)[0].setValue(1200)
        dialog.accept()
    QTimer.singleShot(0, fill)
    studio.edit_graphic_document()
    assert studio.document()["width"] == 1200


def test_opening_a_faceplate_template_preserves_runtime(studio):
    studio.start_runtime()
    current = studio.runtime_window
    item = next(i for i in studio.scene.items() if i.element["id"] == "pump1")
    point = studio.view.mapFromScene(item.mapToScene(QPointF(150, 100)))
    QTest.mouseDClick(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QApplication.processEvents()
    assert studio.document_kind == "faceplates"
    assert studio.document_name == "pump"
    assert studio.runtime_window is current
    assert studio.page_title.text() == "Faceplates"


def test_structures_are_collapsed_groups_and_filter_shows_matching_fields(studio):
    tree = studio.table
    assert tree.topLevelItemCount() == 4
    pump = tree.topLevelItem(0)
    assert pump.text(0) == "Pump1"
    assert pump.childCount() == 3
    assert not pump.isExpanded()
    pump.setExpanded(True)
    studio.refresh_variables()
    assert tree.topLevelItem(0).isExpanded()
    studio.filter.setText("Pump1.flow")
    assert tree.topLevelItemCount() == 1
    assert tree.topLevelItem(0).childCount() == 1
    assert tree.topLevelItem(0).child(0).text(0) == "flow"
    assert tree.topLevelItem(0).isExpanded()


def test_structure_field_can_select_plc_and_db_without_json(studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLineEdit, QComboBox, QSpinBox
    studio.project.connections.append(dict(id="PLC_Main", protocol="s7", host="127.0.0.1"))
    def fill():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QComboBox, "tagConnection").setCurrentIndex(2)
        dialog.findChild(QSpinBox, "protocol_db").setValue(3)
        dialog.findChild(QSpinBox, "protocol_offset").setValue(8)
        dialog.accept()
    QTimer.singleShot(0, fill)
    studio.tag_form("Pump1.flow")
    binding = studio.project.tags()["Pump1.flow"]["binding"]
    assert binding == dict(connection="PLC_Main", version=1, address=dict(db=3, offset=8, encoding="float32"))
    assert studio.project.tags()["Pump1.running"]["binding"]["connection"] == "plant"


def test_all_tools_fit_and_inspector_always_shows_context(studio):
    assert studio.inspector_panel.isVisible()
    assert studio.screen_properties.isVisible()
    viewport = studio.toolbox.viewport().rect()
    for index in range(studio.toolbox.count()):
        item=studio.toolbox.item(index)
        if item.data(Qt.ItemDataRole.UserRole) is None:
            continue  # group title, hidden while searching
        studio.tool_search.setText(item.text())
        QApplication.processEvents()
        assert not item.isHidden()
        assert studio.toolbox.viewport().rect().contains(studio.toolbox.visualItemRect(item))
    studio.tool_search.clear()
    studio.add_element("text")
    assert studio.inspector_panel.isVisible()
    studio.scene.clearSelection()
    assert studio.inspector_panel.isVisible()
    assert studio.screen_properties.isVisible()


def test_nested_structures_keep_their_hierarchy(studio):
    studio.project.types["Station"] = {"pump": "Pump"}
    studio.project.variables.append(dict(name="Station1", type="Station", initial={"pump": {"running": False, "flow": 0.0, "setpoint": 0.0}}, writable=False))
    studio.refresh_variables()
    root = studio.table.topLevelItem(4)
    assert root.text(0) == "Station1"
    assert root.child(0).text(0) == "pump"
    assert root.child(0).childCount() == 3
    studio.project.configure_tag("Station1.pump.flow", "27.5", False, None)
    studio.project.validate()
    assert studio.project.tags()["Station1.pump.flow"]["initial"] == 27.5


def test_variable_dialog_has_no_explanatory_banner(studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLabel
    contents = []
    def inspect():
        dialog = QApplication.activeModalWidget()
        contents.extend(w.text() for w in dialog.findChildren(QLabel))
        dialog.reject()
    QTimer.singleShot(0, inspect)
    studio.tag_form("Operator")
    assert not any("No se lee" in text or "variable interna" in text.casefold() for text in contents)
    assert {'Valor inicial','Acceso','Conexión'} <= set(contents)
    assert not any(text for text in contents if text not in {'Valor inicial','Acceso','Conexión'})


def test_first_click_selects_without_moving_or_snapping(studio):
    studio.add_element("text", QPointF(103, 107))
    item = studio.scene.selectedItems()[0]
    original = item.pos()
    identity = item.element["id"]
    studio.scene.clearSelection()
    QApplication.processEvents()
    point = studio.view.mapFromScene(item.mapToScene(QPointF(70, 20)))
    history = len(studio.undo_stack)
    QTest.mousePress(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(studio.view.viewport(), point+QPoint(40, 15), delay=20)
    QTest.mouseRelease(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=point+QPoint(40, 15))
    QApplication.processEvents()
    assert item.isSelected()
    assert item.pos() == original
    assert len(studio.undo_stack) == history
    # A second ordinary click still must not move a non-grid-aligned item.
    point = studio.view.mapFromScene(item.mapToScene(QPointF(60, 20)))
    QTest.mouseClick(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert item.pos() == original
    studio.snap_action.setChecked(False)
    QTest.mousePress(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(studio.view.viewport(), point+QPoint(35, 20), delay=20)
    QTest.mouseRelease(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=point+QPoint(35, 20))
    assert item.x() > original.x() and item.y() > original.y()
    studio.undo()
    restored = next(e for e in studio.document()["elements"] if e["id"] == identity)
    assert restored["x"] == original.x() and restored["y"] == original.y()


def test_modbus_connection_and_binding_forms(studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLineEdit, QComboBox, QSpinBox
    def create():
        dialog = QApplication.activeModalWidget()
        dialog.findChildren(QLineEdit)[0].setText("Meter")
        protocol = dialog.findChildren(QComboBox)[0]
        protocol.setCurrentIndex(protocol.findData("modbus_tcp"))
        assert dialog.findChild(QSpinBox, "protocol_port").value() == 502
        assert dialog.findChild(QSpinBox, "protocol_rack") is None
        dialog.findChild(QSpinBox, "protocol_unit_id").setValue(7)
        dialog.findChild(QSpinBox, "connectionCycle").setValue(100)
        dialog.accept()
    QTimer.singleShot(0, create)
    studio.connection_form(None)
    config = studio.project.connections[-1]
    assert config["protocol"] == "modbus_tcp" and config["unit_id"] == 7 and config["poll_ms"] == 100
    def bind():
        dialog = QApplication.activeModalWidget()
        connection = dialog.findChild(QComboBox, "tagConnection")
        connection.setCurrentIndex(connection.findData("Meter"))
        assert dialog.findChild(QSpinBox, "protocol_db") is None
        dialog.findChild(QSpinBox, "protocol_offset").setValue(20)
        area = dialog.findChild(QComboBox, "protocol_area")
        area.setCurrentIndex(area.findData("input_registers"))
        # Switching away and back preserves the draft of each connection.
        connection.setCurrentIndex(connection.findData("plant"))
        assert dialog.findChild(QSpinBox, "protocol_db") is not None
        connection.setCurrentIndex(connection.findData("Meter"))
        assert dialog.findChild(QSpinBox, "protocol_offset").value() == 20
        dialog.accept()
    QTimer.singleShot(0, bind)
    studio.tag_form("Pump1.flow")
    binding = studio.project.tags()["Pump1.flow"]["binding"]
    assert binding["connection"] == "Meter"
    assert binding["address"] == dict(area="input_registers", offset=20, encoding="float32", byte_order="big", word_order="big")
