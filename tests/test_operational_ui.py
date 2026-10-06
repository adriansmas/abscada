import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import csv
import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox, QSpinBox, QDialogButtonBox, QTabWidget
from PySide6.QtTest import QTest
from abscada.ui import Window
from abscada.storage import ArchiveReader, database_path, Repository
from abscada.runtime import Sample
from abscada.viewers import TrendViewer, AlarmViewer
from test_operations import operational_project


def pump_until(predicate, timeout=4):
    deadline = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("GUI condition timed out")
        QApplication.processEvents(); QTest.qWait(20)
        time.sleep(0.005)  # Let the Python SQLite reader threads run during Qt test waits.


@pytest.fixture
def operational_studio(operational_project, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window(operational_project)
    def fail(exc):
        raise AssertionError(str(exc))
    monkeypatch.setattr(window,"error",fail)
    window.show(); app.processEvents()
    yield window
    window.dirty=False; window.stop_runtime(); window.close(); app.processEvents()


def test_engineering_alarm_and_historian_forms_undo_and_save(operational_studio):
    window = operational_studio
    window.navigate("alarms")
    assert window.pages.currentWidget() is window.operational_editor.alarms
    def fill_alarm():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QLineEdit,"field_id").setText("fault")
        dialog.findChild(QLineEdit,"field_message").setText("Fallo general")
        tag = dialog.findChild(QComboBox,"field_tag"); tag.setCurrentIndex(tag.findData("Fault"))
        op = dialog.findChild(QComboBox,"field_condition"); op.setCurrentIndex(op.findData("true"))
        dialog.findChild(QSpinBox,"field_priority").setValue(1000)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(0,fill_alarm)
    window.operational_editor.alarm_definitions.edit(None)
    assert window.project.alarms["items"][-1]["condition"] == "true"
    window.undo(); assert len(window.project.alarms["items"])==1
    window.redo(); assert len(window.project.alarms["items"])==2
    def fill_log():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QSpinBox,"field_interval_ms").setValue(250)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(0,fill_log)
    window.operational_editor.logs.edit(window.project.historian["files"][0])
    assert window.project.historian["files"][0]["interval_ms"]==250
    window.save_project()
    from abscada.project import Project
    assert Project.load(window.project.root).alarms == window.project.alarms


def test_trend_is_configured_from_its_control(operational_studio):
    window = operational_studio
    window.add_element("trend")
    element = window.scene.selectedItems()[0].element
    view = element["view"]
    assert window.project.trends[view]["curves"] == []
    def fill_trend():
        dialog = QApplication.activeModalWidget()
        assert dialog.findChild(QLineEdit, "trendId") is None
        dialog.findChild(QLineEdit,"trendTitle").setText("Nivel del depósito")
        tabs = dialog.findChild(QTabWidget)
        page = tabs.widget(1)
        def fill_curve():
            curve_dialog = QApplication.activeModalWidget()
            curve_dialog.findChild(QLineEdit,"field_id").setText("level")
            curve_dialog.findChild(QLineEdit,"field_color").setText("#123456")
            curve_dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0,fill_curve)
        page.edit(None)
        buttons = dialog.findChildren(QDialogButtonBox, options=Qt.FindChildOption.FindDirectChildrenOnly)[0]
        buttons.button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(0,fill_trend)
    window.configure_viewer()
    trend = window.project.trends[view]
    assert trend["title"] == "Nivel del depósito" and trend["curves"][0]["color"] == "#123456"
    assert "Nivel del depósito" in window.viewer_summary.text()
    # Each control owns its configuration: a copy gets its own one, deleting removes it.
    window.duplicate_element()
    copy_view = window.scene.selectedItems()[0].element["view"]
    assert copy_view != view and window.project.trends[copy_view] == trend
    window.delete_element()
    assert copy_view not in window.project.trends and view in window.project.trends


def test_runtime_alarm_ack_and_embedded_widgets(operational_studio):
    window=operational_studio
    window.add_element("trend")
    window.add_element("alarm_view")
    window.start_runtime(); live=window.runtime_window
    live.runtime.write("Level",90)
    assert not hasattr(live, "tabs")
    viewer=next(item.proxy.widget() for item in live.scene.items() if hasattr(item, "element") and item.element["kind"]=="alarm_view")
    pump_until(lambda: viewer.table.rowCount()==1)
    viewer.table.selectRow(0); viewer.actor.setText("Ana")
    QTest.mouseClick(viewer.ack,Qt.MouseButton.LeftButton)
    reader=ArchiveReader(database_path(window.project))
    pump_until(lambda: reader.alarms()[0]["ack_by"]=="Ana")
    assert reader.alarms()[0]["returned_at"] is None
    live.runtime.write("Level",0)
    viewer.reload()
    pump_until(lambda: viewer.table.rowCount()==0)
    items=[item for item in live.scene.items() if hasattr(item,"element")]
    assert len(items)==2 and all(hasattr(item,"proxy") for item in items)
    assert window.samples=={}


def test_multi_axis_curve_style_visibility_and_bad_quality_gap(operational_project):
    app=QApplication.instance() or QApplication([])
    repo=Repository(database_path(operational_project))
    now=time.time()
    for i,quality in enumerate(["good","good","bad","good","good"]):
        repo.sample("Level",Sample(i*10,quality,now-5+i),now-5+i)
        repo.sample("Fault",Sample(bool(i%2),"good",now-5+i),now-5+i)
    repo.connection.commit(); repo.close()
    viewer=TrendViewer(operational_project,operational_project.trends["process"])
    assert viewer.x_axis.min().isValid() and viewer.x_axis.min()<viewer.x_axis.max()
    viewer.resize(1000,500); viewer.show()
    try:
        pump_until(lambda: len(viewer.chart.series())==3)
        level_series=[s for s in viewer.chart.series() if s.name()=="Level"]
        assert len(level_series)==2
        assert all(s.pen().widthF()==3 and s.pen().color().name()=="#147d75" for s in level_series)
        assert all(viewer.axes["level"] in s.attachedAxes() for s in level_series)
        assert not viewer.axes["digital"].isVisible()
        viewer.axes["digital"].setVisible(True)
        viewer.curve_visible["fault"].setChecked(False)
        assert len(viewer.chart.series())==2
        viewer.cursor(now-3)
        assert "bad" in viewer.readout.text()
    finally:
        viewer.close(); app.processEvents()


def test_alarm_history_filter_and_csv(operational_project, monkeypatch, tmp_path):
    app=QApplication.instance() or QApplication([])
    repo=Repository(database_path(operational_project))
    key=repo.enter(operational_project.alarms["items"][0],90,time.time()-2)
    repo.acknowledge([key],time.time()-1,"Ana","Revisado"); repo.connection.commit(); repo.close()
    viewer=AlarmViewer(operational_project)
    viewer.resize(1100,500); viewer.show()
    target=tmp_path/"alarms.csv"
    monkeypatch.setattr("abscada.viewers.QFileDialog.getSaveFileName",lambda *a: (str(target),"CSV"))
    try:
        viewer.mode.setCurrentIndex(viewer.mode.findData("events")); viewer.end.setDateTime(viewer.end.dateTime().addSecs(5))
        pump_until(lambda: viewer.table.rowCount()==2)
        viewer.search.setText("Missing"); assert viewer.table.rowCount()==0
        viewer.search.setText("alto"); assert viewer.table.rowCount()==2
        viewer.export_csv()
        rows=list(csv.DictReader(target.open(encoding="utf-8-sig")))
        assert len(rows)==2 and rows[0]["actor"]=="Ana" and rows[0]["comment"]=="Revisado"
    finally:
        viewer.close(); app.processEvents()


def test_trend_export_uses_raw_samples_not_decimated_data(operational_project, monkeypatch, tmp_path):
    app=QApplication.instance() or QApplication([])
    repo=Repository(database_path(operational_project)); now=time.time()
    for i in range(6000):
        repo.sample("Level",Sample(i,"good",now-60+i/100),now-60+i/100)
    repo.connection.commit(); repo.close()
    viewer=TrendViewer(operational_project,operational_project.trends["process"])
    viewer.resize(1000,500); viewer.show()
    target=tmp_path/"trend.csv"
    monkeypatch.setattr("abscada.viewers.QFileDialog.getSaveFileName",lambda *a: (str(target),"CSV"))
    try:
        viewer.live.setChecked(False)
        from PySide6.QtCore import QDateTime
        viewer.start.setDateTime(QDateTime.fromMSecsSinceEpoch(int((now-61)*1000)))
        viewer.end.setDateTime(QDateTime.fromMSecsSinceEpoch(int((now+1)*1000))); viewer.reload()
        pump_until(lambda: bool(viewer.data))
        assert len(viewer.data["Level"])<6000
        viewer.export_csv()
        pump_until(lambda: target.exists() and viewer.export_future is None)
        assert len(list(csv.DictReader(target.open(encoding="utf-8-sig"))))==6000
    finally:
        viewer.close(); app.processEvents()
