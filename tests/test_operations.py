import copy
import time
import pytest
from abscada.alarms import AlarmEngine, condition, state
from abscada.project import Project
from abscada.runtime import Runtime, Sample
from abscada.storage import Repository, ArchiveReader, RuntimeLease, database_path, ProjectSampleReader
from test_core import DEMO, wait_for


@pytest.fixture
def operational_project(tmp_path):
    project = Project.load(DEMO)
    project.root = tmp_path
    project.connections = []
    project.types = {}; project.faceplates = {}
    project.variables = [dict(name="Level", type="float", initial=0.0, writable=True),
                         dict(name="Fault", type="bool", initial=False, writable=True)]
    project.screens = {"main": dict(width=1000, height=650, elements=[])}
    project.manifest["startup_screen"] = "main"
    project.alarms = dict(retention_days=30, categories=[dict(id="process", name="Proceso", color="#d74c4c")],
        items=[dict(id="high", message="Nivel alto", tag="Level", category="process", condition="high", threshold=80,
            hysteresis=5, priority=800, ack_required=True, enabled=True, on_delay_ms=0, off_delay_ms=0)])
    project.historian = dict(retention_days=7, tags=[dict(tag="Level", interval_ms=50, mode="cyclic", deadband=0),
                                                  dict(tag="Fault", interval_ms=50, mode="change", deadband=0)])
    project.trends = dict(process=dict(title="Proceso", window_seconds=60,
        axes=[dict(id="level", title="Nivel (%)", side="left", auto=False, min=0, max=100, visible=True),
              dict(id="digital", title="Estado", side="right", auto=False, min=0, max=1, visible=False)],
        curves=[dict(id="level", tag="Level", axis="level", color="#147d75", width=3, visible=True),
                dict(id="fault", tag="Fault", axis="digital", color="#d74c4c", width=1, visible=True)]))
    project.alarm_views = dict(process=dict(title="Alarmas de proceso", categories=["process"], min_priority=1, mode="pending", allow_ack=True))
    project.save()
    return Project.load(tmp_path)


@pytest.fixture
def repository(tmp_path):
    repo = Repository(tmp_path/"archive.sqlite3")
    yield repo
    repo.close()


@pytest.mark.parametrize("operator,threshold,entry,hold,clear", [("high",80,85,76,74), ("low",20,15,24,26)])
def test_hysteresis(operator, threshold, entry, hold, clear):
    alarm = dict(condition=operator, threshold=threshold, hysteresis=5)
    assert condition(alarm, entry)
    assert condition(alarm, hold, True)
    assert not condition(alarm, clear, True)
    assert not condition(alarm, hold, False)


def test_alarm_occurrence_ack_return_and_reactivation(repository, operational_project):
    engine = AlarmEngine(operational_project.alarms["items"], repository)
    engine.observe("Level", Sample(90,"good",100), 1, 100)
    first = engine.active["high"]
    assert state(repository.active()[0]) == "Activa · pendiente ACK"
    assert repository.acknowledge([first],101,"Ana","Revisado") == 1
    assert repository.acknowledge([first],102,"Ana") == 0
    assert state(repository.active()[0]) == "Activa"
    engine.observe("Level", Sample(0,"good",103), 2, 103)
    engine.observe("Level", Sample(95,"good",104), 3, 104)
    second = engine.active["high"]
    assert second != first
    repository.connection.commit()
    reader = ArchiveReader(repository.path)
    events = reader.alarms("events")
    assert [e["event"] for e in reversed(events)] == ["incoming","ack","outgoing","incoming"]
    assert events[-2]["ack_by"] == "Ana"
    history = reader.alarms("history")
    assert next(r for r in history if r["id"] == first)["returned_at"] == 103
    assert len(reader.alarms("pending")) == 1


def test_return_before_ack_keeps_occurrence_pending(repository, operational_project):
    engine = AlarmEngine(operational_project.alarms["items"], repository)
    engine.observe("Level", Sample(90,"good",100), 1, 100)
    first = engine.active["high"]
    engine.observe("Level", Sample(0,"good",101), 2, 101)
    engine.observe("Level", Sample(90,"good",102), 3, 102)
    repository.connection.commit()
    reader = ArchiveReader(repository.path)
    assert len(reader.alarms()) == 2
    assert state(next(r for r in reader.alarms() if r["id"] == first)) == "Retornada · pendiente ACK"
    repository.acknowledge([first],103,"Luis")
    repository.connection.commit()
    assert len(reader.alarms()) == 1


def test_delay_quality_and_restart_recovery(repository, operational_project):
    alarm = dict(operational_project.alarms["items"][0], on_delay_ms=1000, off_delay_ms=1000)
    engine = AlarmEngine([alarm],repository)
    engine.observe("Level", Sample(90,"good",100), 0,100)
    engine.tick(0.9,100.9); assert not engine.active
    engine.observe("Level", Sample(90,"bad",101),0.95,101)
    engine.tick(2,102); assert not engine.active
    engine.observe("Level", Sample(90,"good",103),3,103)
    engine.tick(4,104); assert "high" in engine.active
    repository.connection.commit()
    restored = AlarmEngine([alarm],repository)
    assert restored.active == engine.active
    restored.observe("Level", Sample(0,"bad",105),5,105)
    restored.tick(7,107); assert "high" in restored.active
    restored.observe("Level", Sample(0,"good",108),8,108)
    restored.tick(8.9,108.9); assert "high" in restored.active
    restored.tick(9,109); assert not restored.active


def test_retention_preserves_pending_and_active_alarms(repository, operational_project):
    alarm = operational_project.alarms["items"][0]
    active = repository.enter(alarm,90,1)
    pending = repository.enter(alarm,90,2); repository.returned(pending,3)
    closed = repository.enter(alarm,90,4); repository.returned(closed,5); repository.acknowledge([closed],6,"Op")
    repository.sample("Level",Sample(3,"good",1),1)
    repository.prune(864000,1,1); repository.connection.commit()
    reader = ArchiveReader(repository.path)
    assert {r["id"] for r in reader.alarms("history")} == {active,pending}
    assert reader.samples("Level",0,100) == []


def test_runtime_archive_ack_and_restart(operational_project):
    runtime = Runtime(operational_project); runtime.start()
    reader = ArchiveReader(database_path(operational_project))
    try:
        runtime.write("Level",90)
        wait_for(lambda: bool(reader.alarms()))
        first = reader.alarms()[0]
        wait_for(lambda: len(ProjectSampleReader(operational_project).samples("Level",0,time.time()+1))>=3)
        runtime.write("Level",0)
        wait_for(lambda: reader.alarms()[0]["returned_at"] is not None)
        assert runtime.operations.acknowledge([first["id"]],"Operador 1","Corregida") == 1
        assert reader.alarms() == []
        assert reader.alarms("history")[0]["ack_by"] == "Operador 1"
        runtime.write("Level",90)
        wait_for(lambda: len(reader.alarms())==1)
    finally:
        runtime.stop()
    # Restart preserves the open occurrence and returns it on the first valid local value.
    runtime = Runtime(operational_project); runtime.start()
    try:
        wait_for(lambda: reader.alarms()[0]["returned_at"] is not None)
        assert len(reader.alarms()) == 1
        assert runtime.operations.acknowledge([reader.alarms()[0]["id"]],"Operador 2") == 1
    finally:
        runtime.stop()
    assert not runtime.operations.thread.is_alive()


def test_legacy_change_logging_deadband_and_quality_gaps(operational_project):
    operational_project.historian = dict(retention_days=7, tags=[dict(tag="Level", mode="change", interval_ms=50, deadband=2)])
    runtime = Runtime(operational_project); runtime.start()
    reader = ArchiveReader(database_path(operational_project))
    try:
        wait_for(lambda: len(reader.samples("Level",0,time.time()+1))==1)
        runtime.write("Level",1)
        time.sleep(0.3)
        assert len(reader.samples("Level",0,time.time()+1)) == 1
        runtime.write("Level",3)
        wait_for(lambda: len(reader.samples("Level",0,time.time()+1))==2)
        runtime._set("Level",3,"bad","offline")
        runtime._set("Level",3,"good")
        wait_for(lambda: len(reader.samples("Level",0,time.time()+1))==4)
        assert [r["quality"] for r in reader.samples("Level",0,time.time()+1)] == ["good","good","bad","good"]
    finally:
        runtime.stop()


def test_repository_queries_bounded_extrema_and_gaps(repository):
    for i in range(12000):
        repository.sample("Level", Sample(900 if i==6000 else 1,"bad" if i==8000 else "good",i),i)
    repository.connection.commit()
    rows = ArchiveReader(repository.path).samples("Level",0,11999,limit=500)
    assert len(rows)<=500
    assert rows[0]["recorded_at"] == 0 and rows[-1]["recorded_at"] == 11999
    assert max(row["numeric"] for row in rows) == 900
    assert any(row["quality"]=="bad" for row in rows)


def test_single_writer_lease_and_database_version(tmp_path):
    first, second = RuntimeLease(tmp_path/"runtime.lock"), RuntimeLease(tmp_path/"runtime.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="Ya existe"):
            second.acquire()
    finally:
        first.close()
    second.acquire(); second.close()
    repository = Repository(tmp_path/"archive.sqlite3")
    repository.connection.execute("PRAGMA user_version=99"); repository.close()
    with pytest.raises(ValueError, match="Versión"):
        Repository(tmp_path/"archive.sqlite3")


def test_online_backup_includes_committed_wal_records(repository, operational_project, tmp_path):
    instance = repository.enter(operational_project.alarms["items"][0],90,time.time())
    repository.sample("Level",Sample(90,"good",time.time()),time.time())
    repository.connection.commit()
    backup = tmp_path/"backup.sqlite3"
    ArchiveReader(repository.path).backup(backup)
    assert ArchiveReader(backup).alarms()[0]["id"] == instance
    assert len(ArchiveReader(backup).samples("Level",0,time.time()+1)) == 1
    with pytest.raises(ValueError):
        ArchiveReader(repository.path).backup(repository.path)


def test_s7_alarm_and_historian_use_acquired_values(plc_project, tmp_path):
    project = copy.deepcopy(plc_project); project.root=tmp_path
    project.alarms=dict(categories=[dict(id="equipment",name="Equipo",color="#d74c4c")],
        items=[dict(id="setpoint_high",message="Consigna alta",tag="Pump1.setpoint",category="equipment",condition="high",threshold=55,priority=700,ack_required=True)])
    project.historian=dict(tags=[dict(tag="Pump1.setpoint",interval_ms=50,mode="cyclic",deadband=0)],retention_days=7)
    project.connections[0]["poll_ms"]=50
    runtime=Runtime(project); reader=ArchiveReader(database_path(project)); runtime.start()
    try:
        wait_for(lambda: bool(reader.alarms()))
        row=reader.alarms()[0]; assert row["value"]=="60.0"
        runtime.write("Pump1.setpoint",20)
        wait_for(lambda: reader.alarms()[0]["returned_at"] is not None)
        wait_for(lambda: any(r["value"]=="20.0" for r in reader.samples("Pump1.setpoint",0,time.time()+1)))
        runtime.operations.acknowledge([row["id"]],"Ana")
        assert reader.alarms()==[]
    finally:
        runtime.stop()


@pytest.mark.parametrize("change", [
    lambda p: p.alarms["items"][0].update(tag="Missing"),
    lambda p: p.alarms["items"][0].update(condition="true"),
    lambda p: p.alarms["items"][0].update(hysteresis=-1),
    lambda p: p.alarms["items"][0].update(category="missing"),
    lambda p: p.historian["files"][0].update(interval_ms=0),
    lambda p: p.trends["process"]["curves"][0].update(axis="missing"),
    lambda p: p.trends["process"]["axes"][0].update(min=200,max=100),
    lambda p: p.trends["process"]["curves"][0].update(color="wrong"),
    lambda p: p.alarm_views["process"].update(categories=["missing"]),
])
def test_operational_configuration_rejects_invalid_references(operational_project, change):
    change(operational_project)
    with pytest.raises(ValueError):
        operational_project.validate()
