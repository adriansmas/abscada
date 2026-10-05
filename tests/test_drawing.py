import copy
import pytest
from PySide6.QtCore import Qt, QPointF, QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from abscada.drawing import world_points
from abscada.project import Project
from test_ui import studio


def click_canvas(window,x,y):
    QTest.mouseClick(window.view.viewport(),Qt.MouseButton.LeftButton,pos=window.view.mapFromScene(QPointF(x,y)))


def test_screen_properties_persist_and_runtime_uses_background(studio):
    panel = studio.screen_properties
    assert panel.isVisible()
    panel.title.setText("Bombeo"); panel.width.setValue(1280); panel.height.setValue(720)
    panel.background.setText("#e4edf5"); panel.grid_size.setValue(25)
    panel.show_grid.setChecked(False); panel.apply()
    assert studio.document()["background"] == "#e4edf5"
    assert studio.scene.sceneRect().width() == 1280
    assert studio.snap_position(QPointF(38,64)) == QPointF(50,75)
    studio.undo(); assert studio.document().get("background") != "#e4edf5"
    studio.redo(); studio.save_project()
    assert Project.load(studio.project.root).screens["overview"]["grid_size"] == 25
    studio.start_runtime()
    assert studio.runtime_window.project.screens["overview"]["background"] == "#e4edf5"
    assert "Bombeo" in studio.runtime_window.windowTitle()


def test_draw_pipe_orthogonal_cancel_and_single_undo(studio):
    count = len(studio.document()["elements"])
    history = len(studio.undo_stack)
    studio.add_element("pipe")
    click_canvas(studio,100,400); click_canvas(studio,300,410); click_canvas(studio,310,550)
    QTest.keyClick(studio.view,Qt.Key.Key_Return)
    element = studio.scene.selectedItems()[0].element
    assert element["kind"] == "pipe"
    points = world_points(element)
    assert points[0][1] == points[1][1] and points[1][0] == points[2][0]
    assert len(studio.undo_stack) == history+1
    studio.undo(); assert len(studio.document()["elements"]) == count
    studio.redo(); assert len(studio.document()["elements"]) == count+1
    studio.add_element("polyline"); click_canvas(studio,50,50)
    QTest.keyClick(studio.view,Qt.Key.Key_Escape)
    assert len(studio.document()["elements"]) == count+1
    assert studio.screen_properties.isVisible()


def test_line_draw_and_node_drag_preserve_selection_first_click(studio):
    studio.add_element("line")
    click_canvas(studio,100,400); click_canvas(studio,300,400)
    item = studio.scene.selectedItems()[0]; identity = item.element["id"]
    assert len(item.element["points"]) == 2
    studio.scene.clearSelection()
    start = studio.view.mapFromScene(QPointF(*world_points(item.element)[0]))
    original = copy.deepcopy(item.element)
    QTest.mousePress(studio.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(studio.view.viewport(),start+QPoint(30,30),delay=20)
    QTest.mouseRelease(studio.view.viewport(),Qt.MouseButton.LeftButton,pos=start+QPoint(30,30))
    assert item.element == original
    QTest.mousePress(studio.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(studio.view.viewport(),start+QPoint(30,30),delay=20)
    QTest.mouseRelease(studio.view.viewport(),Qt.MouseButton.LeftButton,pos=start+QPoint(30,30))
    assert world_points(item.element)[0] != world_points(original)[0]
    studio.undo()
    restored = next(e for e in studio.document()["elements"] if e["id"]==identity)
    assert restored == original


def test_pipe_empty_bounding_area_is_not_selectable(studio):
    studio.insert_path("pipe",[[100,100],[300,100],[300,300]])
    item = studio.scene.selectedItems()[0]
    assert item.shape().contains(QPointF(100,0))
    assert not item.shape().contains(QPointF(50,150))


def test_vector_styling_points_and_layers_survive_save(studio):
    studio.insert_path("polyline",[[100,400],[250,400],[300,550]])
    identity = studio.scene.selectedItems()[0].element["id"]
    panel = studio.drawing_properties
    panel.color.setText("#dd6633"); panel.width.setValue(8)
    panel.arrows.setCurrentIndex(panel.arrows.findData("end")); panel.apply()
    panel.add_point()
    element = studio.scene.selectedItems()[0].element
    assert len(element["points"]) == 4 and element["stroke_width"] == 8
    studio.order_elements("back")
    assert studio.document()["elements"][0]["id"] == identity
    studio.save_project()
    assert Project.load(studio.project.root).screens["overview"]["elements"][0]["arrows"] == "end"
    assert studio.layers.item(studio.layers.count()-1).data(Qt.ItemDataRole.UserRole) == identity


def test_alignment_and_northwest_resize_are_undoable(studio):
    studio.add_element("rectangle",QPointF(100,400)); first=studio.scene.selectedItems()[0].element["id"]
    studio.add_element("ellipse",QPointF(350,450))
    for item in studio.scene.items():
        if item.element["id"] == first:
            item.setSelected(True)
    studio.align_elements("top")
    assert {item.element["y"] for item in studio.scene.selectedItems()} == {400}
    studio.undo()
    item = next(i for i in studio.scene.items() if i.element["id"]==first)
    item.setSelected(True); original=copy.deepcopy(item.element)
    start=studio.view.mapFromScene(item.mapToScene(QPointF(0,0)))
    QTest.mousePress(studio.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(studio.view.viewport(),start-QPoint(25,20),delay=20)
    QTest.mouseRelease(studio.view.viewport(),Qt.MouseButton.LeftButton,pos=start-QPoint(25,20))
    assert item.element["x"] < original["x"] and item.element["w"] > original["w"]
    assert abs(item.element["x"]+item.element["w"]-original["x"]-original["w"]) < .2


@pytest.mark.parametrize("points", [[],[[0,0]],[[0,0],[0,0]],[[0,0],[float("nan"),1]],[[0,0],[2,1]]])
def test_invalid_vector_geometry_is_rejected(studio, points):
    project = copy.deepcopy(studio.project)
    project.screens["overview"]["elements"].append(dict(id="invalid",kind="pipe",x=0,y=0,w=100,h=100,points=points))
    with pytest.raises(ValueError):
        project.validate()


def test_delete_in_property_field_does_not_delete_element(studio):
    studio.add_element("rectangle",QPointF(100,400))
    count=len(studio.document()["elements"])
    studio.id_field.setFocus(); studio.id_field.setCursorPosition(0)
    original=studio.id_field.text()
    QTest.keyClick(studio.id_field,Qt.Key.Key_Delete)
    assert studio.id_field.text() == original[1:]
    assert len(studio.document()["elements"]) == count
    studio.id_field.clearFocus(); QApplication.processEvents()


def test_faceplate_background_is_preserved_in_runtime_expansion(studio):
    studio.project.faceplates["pump"]["background"]="#e4edf5"
    expanded=list(studio.project.elements("overview"))
    backgrounds=[e for e in expanded if e["id"].endswith(".$background")]
    assert len(backgrounds)==2
    assert all(e["color"]=="#e4edf5" for e in backgrounds)
