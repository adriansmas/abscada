"""Recording membership, shared cadence, daily partitions and independent controls."""
import time
from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication, QComboBox
from PySide6.QtCore import QDateTime
from abscada import recording
from abscada.runtime import Runtime, Sample
from abscada.storage import ProjectSampleReader, ArchiveReader, Repository, database_path
from abscada.viewers import TrendViewer
from test_operations import operational_project, wait_for
from test_operational_ui import operational_studio, pump_until


def epoch(day):
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()


def configure(project):
    project.historian = dict(retention_days=90, files=[
        dict(id="fast", name="Rápido", interval_ms=50, variables=["Level", "Fault"]),
        dict(id="slow", name="Lento", interval_ms=150, variables=[])])
    project.validate()


def test_membership_is_single_valued_and_can_be_disabled(operational_project):
    configure(operational_project)
    recording.assign(operational_project, "Level", "slow")
    assert recording.assignment(operational_project, "Level") == "slow"
    assert operational_project.historian["files"][0]["variables"] == ["Fault"]
    recording.assign(operational_project, "Level", "")
    assert recording.assignment(operational_project, "Level") == ""
    with pytest.raises(ValueError):
        recording.assign(operational_project, "Level", "missing")


@pytest.mark.parametrize("identifier", ["../escape", "CON", "lpt1", "a.b", "x"*65])
def test_file_ids_are_portable_and_stay_in_project(operational_project, identifier):
    configure(operational_project)
    operational_project.historian["files"][0]["id"] = identifier
    with pytest.raises(ValueError):
        operational_project.validate()


def test_duplicate_membership_and_case_insensitive_file_ids_rejected(operational_project):
    configure(operational_project)
    operational_project.historian["files"][1]["variables"] = ["Level"]
    with pytest.raises(ValueError):
        operational_project.validate()
    operational_project.historian["files"][1].update(variables=[], id="FAST")
    with pytest.raises(ValueError):
        operational_project.validate()


def test_daily_rotation_commits_previous_day_and_cross_day_query(operational_project):
    configure(operational_project)
    before, after = epoch("2026-10-01T23:59:59"), epoch("2026-10-02T00:00:01")
    writer = recording.DailyArchive(operational_project, "fast")
    writer.sample("Level", Sample(12, "good", before), before)
    writer.sample("Level", Sample(34, "good", after), after)
    # Rotation commits and closes the previous file without waiting for shutdown.
    assert ArchiveReader(recording.path(operational_project, "fast", before)).samples("Level", before-1, after)[0]["numeric"] == 12
    writer.close()
    assert recording.path(operational_project, "fast", before).name == "2026-10-01.sqlite3"
    rows = ProjectSampleReader(operational_project).samples("Level", before-1, after+1)
    assert [r["numeric"] for r in rows] == [12, 34]
    assert len(ProjectSampleReader(operational_project).raw_samples("Level", before-1, after+1)) == 2


def test_retention_removes_only_expired_complete_days(operational_project):
    configure(operational_project)
    now = epoch("2026-10-04T12:00:00")
    writer = recording.DailyArchive(operational_project, "fast")
    for day in ("2026-10-01", "2026-10-02", "2026-10-04"):
        timestamp = epoch(day+"T12:00:00")
        writer.sample("Level", Sample(1, "good", timestamp), timestamp)
    writer.prune(now, 2)
    assert not recording.path(operational_project, "fast", epoch("2026-10-01")).exists()
    assert recording.path(operational_project, "fast", epoch("2026-10-02")).exists()
    assert writer.repository.path.exists()
    writer.close()


def test_group_cycle_records_all_members_with_same_timestamp(operational_project):
    configure(operational_project)
    start = time.time()-1
    runtime = Runtime(operational_project)
    runtime.start()
    reader = ProjectSampleReader(operational_project)
    try:
        wait_for(lambda: len(reader.samples("Level", start, time.time()+1)) >= 5)
        runtime.stop()
        levels = reader.samples("Level", start, time.time()+1)
        faults = reader.samples("Fault", start, time.time()+1)
        assert [r["recorded_at"] for r in levels] == [r["recorded_at"] for r in faults]
        assert all(b["recorded_at"]-a["recorded_at"] >= .045 for a,b in zip(levels, levels[1:]))
        assert len(list(recording.path(operational_project, "fast").glob("*.sqlite3"))) == 1
        assert not recording.path(operational_project, "slow").exists()
    finally:
        runtime.stop()


def test_live_chart_does_not_require_recording(operational_project):
    app = QApplication.instance() or QApplication([])
    operational_project.historian = dict(files=[], retention_days=90)
    operational_project.alarms["items"] = []
    runtime = Runtime(operational_project)
    assert runtime.operations is None
    viewer = TrendViewer(operational_project, operational_project.trends["process"], runtime)
    viewer.resize(1000, 500); viewer.show()
    try:
        runtime.write("Level", 42)
        pump_until(lambda: any(r["numeric"] == 42 for r in viewer.data.get("Level", [])))
        assert any(s.name() == "Level" for s in viewer.chart.series())
        assert not database_path(operational_project).exists()
    finally:
        viewer.timer.stop(); viewer.close(); app.processEvents()


def test_configured_files_have_independent_recording_frequencies(operational_project):
    configure(operational_project)
    recording.assign(operational_project, "Fault", "slow")
    runtime = Runtime(operational_project)
    reader = ProjectSampleReader(operational_project)
    start = time.time()-1
    runtime.start()
    try:
        wait_for(lambda: len(reader.samples("Fault", start, time.time()+1)) >= 5)
    finally:
        runtime.stop()
    fast = reader.samples("Level", start, time.time()+1)
    slow = reader.samples("Fault", start, time.time()+1)
    # Cadences are targets; disk commits and scheduler load can delay a cycle.
    # Compare observed intervals instead of assuming an exact wall-clock ratio.
    from statistics import median
    assert len(fast) > len(slow)
    assert median(b["recorded_at"]-a["recorded_at"] for a,b in zip(fast,fast[1:])) < median(b["recorded_at"]-a["recorded_at"] for a,b in zip(slow,slow[1:]))
    assert all(b["recorded_at"]-a["recorded_at"] >= .14 for a,b in zip(slow, slow[1:]))


def test_chart_queries_previous_days_across_daily_files(operational_project):
    app = QApplication.instance() or QApplication([])
    configure(operational_project)
    first, last = epoch("2026-09-01T12:00:00"), epoch("2026-09-03T12:00:00")
    writer = recording.DailyArchive(operational_project, "fast")
    for timestamp, val in [(first,12), (last,34)]:
        writer.sample("Level", Sample(val,"good",timestamp), timestamp)
    writer.close()
    viewer = TrendViewer(operational_project, operational_project.trends["process"])
    viewer.start.setDateTime(QDateTime.fromMSecsSinceEpoch(int((first-1)*1000)))
    viewer.end.setDateTime(QDateTime.fromMSecsSinceEpoch(int((last+1)*1000)))
    viewer.live.setChecked(False)
    viewer.resize(1000,500); viewer.show()
    try:
        pump_until(lambda: len(viewer.data.get("Level",[])) == 2)
        assert [r["numeric"] for r in viewer.data["Level"]] == [12,34]
        assert sum(s.count() for s in viewer.chart.series()) == 2
    finally:
        viewer.timer.stop(); viewer.close(); app.processEvents()


def test_variable_table_assigns_moves_and_unsets_recording_with_undo(operational_studio):
    window = operational_studio
    window.navigate("variables")
    item = next(window.table.topLevelItem(i) for i in range(window.table.topLevelItemCount()) if window.table.topLevelItem(i).text(0) == "Level")
    combo = window.table.itemWidget(item, 7)
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData(""))
    assert recording.assignment(window.project, "Level") == ""
    window.undo()
    assert recording.assignment(window.project, "Level") != ""


def test_control_addition_needs_no_predefined_views_and_runtime_has_only_screen(operational_studio):
    window = operational_studio
    window.project.trends.clear(); window.project.alarm_views.clear()
    window.add_element("trend")
    assert window.project.trends[window.scene.selectedItems()[0].element["view"]]["curves"] == []
    window.add_element("alarm_view")
    window.start_runtime()
    live = window.runtime_window
    assert live.centralWidget() is live.view
    assert not hasattr(live, "tabs")
    assert len([i for i in live.scene.items() if hasattr(i, "proxy")]) == 2


def test_history_survives_assignment_move_and_legacy_migration(operational_project):
    now = time.time()
    legacy = Repository(database_path(operational_project))
    legacy.sample("Level", Sample(1, "good", now-2), now-2)
    legacy.connection.commit(); legacy.close()
    recording.migrate(operational_project)
    assert "tags" not in operational_project.historian
    configure(operational_project)
    writer = recording.DailyArchive(operational_project, "fast")
    writer.sample("Level", Sample(2, "good", now-1), now-1); writer.close()
    recording.assign(operational_project, "Level", "slow")
    writer = recording.DailyArchive(operational_project, "slow")
    writer.sample("Level", Sample(3, "good", now), now); writer.close()
    rows = ProjectSampleReader(operational_project).samples("Level", now-3, now+1)
    assert [r["numeric"] for r in rows] == [1,2,3]


def test_project_navigation_button_changes_screen_without_plc_write(operational_studio):
    window = operational_studio
    window.project.screens["second"] = dict(width=1000, height=600, elements=[])
    window.project.screens["main"]["elements"] = [dict(id="nav", kind="button", x=0,y=0,w=150,h=40,text="Otra",action="screen",screen="second")]
    window.start_runtime()
    live = window.runtime_window
    live.actuate(live.project.screens["main"]["elements"][0])
    pump_until(lambda: live.document_name == "second")
    assert not live.scene.items()


def test_historical_query_skips_known_unrelated_recording_files(operational_project, monkeypatch):
    configure(operational_project)
    recording.assign(operational_project, "Fault", "slow")
    runtime = Runtime(operational_project); runtime.start()
    reader = ProjectSampleReader(operational_project)
    now = time.time()
    try:
        wait_for(lambda: len(reader.samples("Fault", now-1, time.time()+1)) >= 2)
    finally:
        runtime.stop()
    opened = []
    original = ArchiveReader.samples
    def capture(self, *args, **kwargs):
        opened.append(self.path)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(ArchiveReader, "samples", capture)
    assert reader.samples("Level", now-1, time.time()+1)
    assert not any(p.parent.name == "slow" for p in opened)
