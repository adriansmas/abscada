"""The shipped laboratory exercises actual project files and TCP transports."""
import importlib.util
import socket
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest
from abscada.project import Project, KINDS
from abscada.runtime import Runtime
from abscada.storage import ProjectSampleReader, ArchiveReader, database_path
from test_core import wait_for

ROOT = Path(__file__).resolve().parents[1]


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_showcase_covers_controls_actions_and_roundtrip(tmp_path):
    project = Project.load(ROOT / 'examples/showcase')
    project.validate()
    elements = [e for doc in [*project.screens.values(), *project.faceplates.values()] for e in doc['elements']]
    assert {e['kind'] for e in elements} == KINDS
    assert {e.get('action') for e in elements if e['kind'] == 'button'} == {'toggle','set','momentary','press_release','screen','popup','close_popup','script'}
    generated = tool('build_showcase').build_project(tmp_path / 'generated')
    assert generated.tags() == project.tags()
    assert generated.screens == project.screens
    with pytest.raises(ValueError, match='ya existe'):
        tool('build_showcase').build_project(generated.root)


def test_showcase_tcp_scripts_and_independent_quality(tmp_path):
    plc = tool('showcase_plcs').LaboratoryPLCs(s7_port=free_port(), modbus_port=free_port()).start()
    project = tool('build_showcase').build_project(tmp_path / 'project')
    project.connections[0]['port'] = plc.s7_port
    project.connections[1]['port'] = plc.modbus_port
    runtime = Runtime(project)
    try:
        runtime.start()
        wait_for(lambda: all(s.quality == 'good' for s in runtime.snapshot().values()), timeout=8)
        runtime.write('Siemens.Bomba1.Consigna', 71.0).result(3)
        runtime.write('Siemens.Bomba1.Marcha', True).result(3)
        runtime.write('Modbus.Consigna', 72.0).result(3)
        runtime.write('Modbus.Habilitar', True).result(3)
        runtime.write('Modbus.Modo', 2).result(3)
        wait_for(lambda: runtime.snapshot()['Siemens.Bomba1.Caudal'].value == 71.0)
        wait_for(lambda: runtime.snapshot()['Modbus.Listo'].value and runtime.snapshot()['Modbus.Temperatura'].value > 69)
        wait_for(lambda: runtime.snapshot()['Sistema.Ciclos'].value >= 1)
        assert runtime.snapshot()['Sistema.Inicio'].value
        reader = ArchiveReader(database_path(project))
        runtime.write('Local.Nivel', 90.0).result(3)
        wait_for(lambda: any(a['alarm_id'] == 'local_high' for a in reader.alarms()), timeout=4)
        alarm = next(a for a in reader.alarms() if a['alarm_id'] == 'local_high')
        assert runtime.operations.acknowledge([alarm['id']], 'Prueba laboratorio', 'Verificado') == 1
        runtime.write('Local.Nivel', 50.0).result(3)
        wait_for(lambda: next(a for a in reader.alarms('history') if a['id'] == alarm['id'])['returned_at'] is not None)
        record = next(a for a in reader.alarms('history') if a['id'] == alarm['id'])
        assert record['ack_by'] == 'Prueba laboratorio'
        assert record['entered_at'] <= record['ack_at'] <= record['returned_at']
        wait_for(lambda: bool(ProjectSampleReader(project).samples('Local.Nivel', 0, time.time()+1)))
        runtime.scripts.submit('screen_open','screen_open','20_internas')
        wait_for(lambda: runtime.snapshot()['Sistema.Aperturas'].value == 1)
        runtime.scripts.submit('button_event','button','60_scripts')
        wait_for(lambda: 'ejecución 1' in runtime.snapshot()['Sistema.UltimoEvento'].value)
        runtime.write('Local.Generador', True).result(3)
        wait_for(lambda: runtime.snapshot()['Local.SinRegistro'].value != 0, timeout=5)
        # Stop just the Modbus listener; S7 and the internal task keep working.
        plc.modbus.stop()
        wait_for(lambda: runtime.snapshot()['Modbus.Temperatura'].quality == 'bad', timeout=6)
        assert runtime.snapshot()['Siemens.Nivel'].quality == 'good'
        assert runtime.snapshot()['Local.Nivel'].quality == 'good'
        assert not [d for d in runtime.scripts.diagnostics() if d['status'] == 'error']
    finally:
        runtime.stop()
        plc.stop()


def test_showcase_history_spans_days_without_plc_or_overwrites(tmp_path):
    project = tool('build_showcase').build_project(tmp_path / 'project')
    now = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
    seed = tool('seed_showcase_history').seed
    targets = seed(project, now)
    assert [p.stem for p in targets] == ['2026-10-03', '2026-10-04']
    reader = ProjectSampleReader(project)
    rows = reader.raw_samples('Local.Nivel', (now-timedelta(days=3)).timestamp(), now.timestamp())
    assert len(rows) == 7200
    assert not reader.samples('Siemens.Nivel', 0, now.timestamp())
    assert not reader.samples('Local.SinRegistro', 0, now.timestamp())
    with pytest.raises(ValueError, match='Ya existe'):
        seed(project, now)
