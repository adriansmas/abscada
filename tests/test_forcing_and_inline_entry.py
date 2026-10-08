"""«Forzado» tab of the variables section and typing an input value in place in the runtime."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit

from abscada.forcing_editor import FORCE, NAME, STATE, parse_value
from abscada.graphics import ElementItem
from test_operational_ui import operational_studio, operational_project, pump_until  # noqa: F401


def test_values_are_parsed_by_the_type_of_the_variable():
    assert parse_value("Verdadero", "bool") is True and parse_value("0", "bool") is False
    assert parse_value("12,5", "float") == 12.5 and parse_value("7", "int") == 7
    for text, kind in (("quizá", "bool"), ("abc", "float")):
        try:
            parse_value(text, kind)
        except ValueError:
            continue
        raise AssertionError(text)


def forcing_row(page, name):
    return next(row for row in range(page.table.rowCount()) if page.table.item(row, NAME).text() == name)


def test_forcing_tab_writes_values_while_the_runtime_runs(operational_studio):
    studio = operational_studio
    studio.navigate("variables")
    studio.variables_tabs.setCurrentWidget(studio.forcing_page)
    page = studio.forcing_page
    pump_until(lambda: page.isVisible())
    page.rebuild()
    row = forcing_row(page, "Level")
    assert not page.table.item(row, FORCE).flags() & Qt.ItemFlag.ItemIsEditable      # no runtime yet
    studio.start_runtime()
    pump_until(lambda: page.live)
    row = forcing_row(page, "Level")
    assert page.table.item(row, FORCE).flags() & Qt.ItemFlag.ItemIsEditable
    page.table.item(row, FORCE).setText("42,5")
    assert studio.runtime.snapshot()["Level"].value == 42.5
    assert page.table.item(row, STATE).text() == "Escrito"
    pump_until(lambda: page.table.item(row, 3).text() == "42.5")
    page.table.item(forcing_row(page, "Fault"), FORCE).setText("quizá")
    assert page.table.item(forcing_row(page, "Fault"), STATE).text() == "Escribe verdadero o falso (1 / 0)"
    assert studio.runtime.snapshot()["Fault"].value is False


def test_an_input_is_typed_in_place_without_a_dialog(operational_studio, monkeypatch):
    studio = operational_studio
    studio.project.screens["main"]["elements"] = [dict(id="level_in", kind="input", x=20, y=20, w=200, h=50, tag="Level", unit="%", decimals=1)]
    studio.project.validate()
    studio.document_name = "main"; studio.render_scene()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dialog opened")))
    studio.start_runtime()
    window = studio.runtime_window
    QApplication.processEvents()
    item = next(i for i in window.scene.items() if isinstance(i, ElementItem) and i.element["id"] == "level_in")
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=window.view.mapFromScene(QPointF(120, 45)))
    pump_until(lambda: getattr(item, "entry_proxy", None) is not None)
    entry = item.entry_proxy.widget()
    assert isinstance(entry, QLineEdit)
    entry.setText("37,5")
    QTest.keyClick(entry, Qt.Key.Key_Return)
    pump_until(lambda: window.runtime.snapshot()["Level"].value == 37.5)
    pump_until(lambda: item.entry_proxy is None)
