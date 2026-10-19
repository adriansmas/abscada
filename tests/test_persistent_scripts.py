"""Scripts with their own limit or without one: parallel loops, ctx.commit and ctx.sleep."""
import time
import pytest
from abscada import script_tree
from abscada.runtime import Runtime
from abscada.storage import ArchiveReader, database_path
from test_core import wait_for
from test_operations import operational_project  # noqa: F401 (fixture)

LOOP = """
n = ctx.state.get('n', 0)
print('arranca', ctx.event)
while ctx.sleep(0.05):
    n += 1
    ctx.state['n'] = n
    ctx.write('Level', n)
print('parada limpia')
"""


def statuses(runtime, name):
    return [row['status'] for row in runtime.scripts.diagnostics() if row['script'] == name]


def test_unlimited_loop_runs_beside_other_scripts_and_stops_cleanly(operational_project):
    p = operational_project
    p.scripts = {'loop': LOOP, 'slow': "import time\ntime.sleep(0.3)\nprint('lenta')"}
    p.automation = dict(startup=['loop', 'slow'], tasks=[], timeout_seconds=5, limits={'loop': None})
    p.validate()
    r = Runtime(p)
    r.start()
    try:
        wait_for(lambda: r.snapshot()['Level'].value >= 3, 10)
        assert r.scripts.running() == ['loop']
        wait_for(lambda: 'ok' in statuses(r, 'slow'), 10)  # the loop does not block the queue
        r.scripts.submit('loop', 'button')
        wait_for(lambda: any('descartado' in row['message'] for row in r.scripts.diagnostics()))
        wait_for(lambda: any(row['status'] == 'output' and 'arranca startup' in row['message']
                             for row in r.scripts.diagnostics()))
    finally:
        start = time.monotonic()
        r.stop()
        assert time.monotonic() - start < 5
    assert statuses(r, 'loop')[-1] == 'ok'
    assert any('parada limpia' in row['message'] for row in r.scripts.diagnostics())


def test_commit_applies_writes_and_reads_fresh_values(operational_project):
    p = operational_project
    p.scripts = {'live': """
ctx.write('Level', 41)
ctx.commit()
print('leído', ctx.read('Level'))
ctx.write('NoExiste', 1)
try:
    ctx.commit()
except ValueError as exc:
    print('rechazado', exc)
ctx.write('Level', 42)
"""}
    p.automation = dict(startup=[], tasks=[], timeout_seconds=5)
    r = Runtime(p)
    r.start()
    try:
        r.scripts.submit('live')
        wait_for(lambda: 'ok' in statuses(r, 'live'), 10)
        text = '\n'.join(row['message'] for row in r.scripts.diagnostics())
        assert 'leído 41' in text and 'rechazado NoExiste' in text
        assert r.snapshot()['Level'].value == 42
    finally:
        r.stop()


def test_task_restarts_an_unlimited_script_once_it_ends(operational_project):
    p = operational_project
    p.scripts = {'once': "ctx.state['n'] = ctx.state.get('n', 0) + 1\nctx.write('Level', ctx.state['n'])\nctx.sleep(0.2)"}
    p.automation = dict(startup=[], tasks=[dict(id='watch', script='once', interval_ms=100, enabled=True)],
                        timeout_seconds=5, limits={'once': None})
    r = Runtime(p)
    r.start()
    try:
        wait_for(lambda: r.snapshot()['Level'].value >= 3, 15)
        assert 'descartado' not in ' '.join(row['message'] for row in r.scripts.diagnostics())
    finally:
        r.stop()


def test_own_limit_overrides_the_general_one_and_ignored_stop_is_killed(operational_project):
    p = operational_project
    p.scripts = {'short': 'while True: pass', 'deaf': 'while True: pass'}
    p.automation = dict(startup=['deaf'], tasks=[], timeout_seconds=60, limits={'short': 0.5, 'deaf': None})
    r = Runtime(p)
    r.start()
    try:
        r.scripts.submit('short')
        wait_for(lambda: 'error' in statuses(r, 'short'), 10)
        assert 'excedido' in r.scripts.diagnostics()[-1]['message'] or any(
            'excedido' in row['message'] for row in r.scripts.diagnostics() if row['script'] == 'short')
        assert r.scripts.running() == ['deaf']
    finally:
        start = time.monotonic()
        r.stop(timeout=10)
        assert time.monotonic() - start < 8
    assert statuses(r, 'deaf')[-1] == 'error'


def test_limits_are_validated_and_follow_renames(operational_project):
    p = operational_project
    p.scripts = {'a': 'pass', 'b': 'pass'}
    p.automation = dict(startup=[], tasks=[], timeout_seconds=10, limits={'a': None, 'b': 3})
    p.validate()
    script_tree.rename_script(p, 'a', 'lector')
    assert p.automation['limits'] == {'lector': None, 'b': 3}
    script_tree.delete_script(p, 'b')
    assert p.automation['limits'] == {'lector': None}
    for bad in ({'nada': None}, {'lector': 0}, {'lector': 'mucho'}, ['lector']):
        p.automation['limits'] = bad
        with pytest.raises(ValueError):
            p.validate()


def test_ctx_sleep_outside_the_runtime_is_explained():
    from abscada.script_runner import Context
    ctx = Context(dict(event='test', samples={}))
    with pytest.raises(RuntimeError, match='Runtime'):
        ctx.sleep(1)
    with pytest.raises(ValueError):
        ctx.sleep(-1)


def test_scripts_set_the_quality_of_internal_variables(operational_project):
    p = operational_project
    p.alarms["items"].append(dict(p.alarms["items"][0], id="sin_datos", condition="bad_quality", on_delay_ms=0, off_delay_ms=0))
    p.scripts = {'calidad': """
ctx.write('Level', 5)
ctx.set_quality('Level', 'bad', 'báscula sin tramas')
ctx.commit()
print('calidad', ctx.quality('Level'))
try:
    ctx.read('Level')
except ValueError:
    print('lectura rechazada')
try:
    ctx.set_quality('Level', 'mala')
except ValueError:
    print('calidad desconocida')
""", 'vuelve': "ctx.write('Level', 6)", 'dudosa': "ctx.set_quality('Level', 'uncertain')"}
    p.automation = dict(startup=[], tasks=[], timeout_seconds=5)
    p.validate()
    r = Runtime(p)
    r.start()
    try:
        r.scripts.submit('calidad')
        wait_for(lambda: 'ok' in statuses(r, 'calidad'), 10)
        text = '\n'.join(row['message'] for row in r.scripts.diagnostics())
        assert 'calidad bad' in text and 'lectura rechazada' in text and 'calidad desconocida' in text
        sample = r.snapshot()['Level']
        assert (sample.value, sample.quality, sample.error) == (5, 'bad', 'báscula sin tramas')
        reader = ArchiveReader(database_path(p))
        wait_for(lambda: any(row["alarm_id"] == "sin_datos" for row in reader.alarms()))
        r.scripts.submit('vuelve')
        wait_for(lambda: r.snapshot()['Level'].quality == 'good' and r.snapshot()['Level'].value == 6, 10)
        r.scripts.submit('dudosa')
        wait_for(lambda: r.snapshot()['Level'].quality == 'uncertain', 10)
        assert r.snapshot()['Level'].value == 6
    finally:
        r.stop()


def test_quality_of_bound_variables_belongs_to_their_connection(operational_project):
    from abscada.scripting import ScriptService
    p = operational_project
    r = Runtime(p)
    r.tags['Level'] = dict(r.tags['Level'], binding=dict(connection='plc', address={}))
    with pytest.raises(ValueError, match='internas'):
        ScriptService(r).apply('x', [['Level', None, 'bad', '']], None, {})
    with pytest.raises(ValueError, match='internas'):
        r.set_quality('Level', 'bad')
