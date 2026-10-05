import time
import pytest
from abscada.runtime import Runtime
from abscada.project import Project
from test_operations import operational_project
from test_core import wait_for
from test_operational_ui import operational_studio, pump_until


def test_startup_task_state_error_and_timeout(operational_project):
    p=operational_project
    p.scripts={'boot':"ctx.write('Level', 3)", 'cycle':"ctx.state['n']=ctx.state.get('n',0)+1\nctx.write('Level',ctx.state['n']+10)",
               'bad':"ctx.write('Level',99)\nraise ValueError('fallo deliberado')", 'hang':'while True: pass'}
    # Include interpreter startup on loaded Windows CI hosts in the execution budget.
    p.automation=dict(startup=['boot'],tasks=[],timeout_seconds=2)
    r=Runtime(p); r.start()
    try:
        wait_for(lambda:r.snapshot()['Level'].value==3)
        r.scripts.submit('cycle'); wait_for(lambda:r.snapshot()['Level'].value==11)
        r.scripts.submit('cycle'); wait_for(lambda:r.snapshot()['Level'].value==12)
        r.scripts.submit('bad'); wait_for(lambda:any(row['script']=='bad' for row in r.scripts.diagnostics()))
        assert r.snapshot()['Level'].value==12
        r.scripts.submit('hang'); wait_for(lambda:any(row['script']=='hang' for row in r.scripts.diagnostics()),5)
        assert r.scripts.diagnostics()[-1]['status']=='error'
        r.scripts.submit('boot'); wait_for(lambda:r.snapshot()['Level'].value==3)
    finally: r.stop()


def test_periodic_tasks_disable_stop_and_no_overlap(operational_project):
    p=operational_project
    p.scripts={'tick':"import time\ntime.sleep(.12)\nctx.state['n']=ctx.state.get('n',0)+1\nctx.write('Level',ctx.state['n'])",'off':"raise Exception('disabled')"}
    p.automation=dict(startup=[],tasks=[dict(id='tick',script='tick',interval_ms=100,enabled=True),dict(id='off',script='off',interval_ms=100,enabled=False)])
    r=Runtime(p);r.start()
    wait_for(lambda:r.snapshot()['Level'].value>=2,5)
    r.stop(); current=r.snapshot()['Level'].value; time.sleep(.2)
    assert r.snapshot()['Level'].value==current
    assert not r.scripts.thread.is_alive()
    assert not any(row['script']=='off' for row in r.scripts.diagnostics())


def test_stop_kills_running_script(operational_project):
    p=operational_project;p.scripts={'loop':'while True: pass'};p.automation['startup']=['loop']
    r=Runtime(p);r.start();time.sleep(.2)
    start=time.monotonic();r.stop();assert time.monotonic()-start<2


@pytest.mark.parametrize('source', ['if:', 'def x('])
def test_invalid_python_rejected_before_save(operational_project,source):
    operational_project.scripts={'bad':source}
    with pytest.raises(ValueError):operational_project.save()


def test_screen_open_once_per_open_shared_with_popup(operational_studio):
    w=operational_studio;p=w.project
    p.scripts={'opened':"ctx.state['n']=ctx.state.get('n',0)+1\nctx.write('Level',ctx.state['n'])\nprint(ctx.screen)"}
    p.screens['main']['on_open']=['opened'];w.start_runtime();r=w.runtime_window
    pump_until(lambda:r.samples['Level'].value==1)
    popup=r.open_popup('main');pump_until(lambda:r.samples['Level'].value==2)
    assert r.open_popup('main') is popup
    r.select_screen('main');pump_until(lambda:r.samples['Level'].value==3)
    assert all(row['script']=='opened' for row in r.runtime.scripts.diagnostics())


def test_editor_source_save_and_undo(operational_studio):
    w=operational_studio;w.project.scripts={'sample':'print(1)'};w.automation_editor.refresh()
    w.navigate('automation');w.automation_editor.code.setPlainText('print(2)')
    assert w.dirty and w.project.scripts['sample']=='print(2)'
    w.undo();assert w.project.scripts['sample']=='print(1)'
    w.redo();assert w.save_project()
    assert Project.load(w.project.root).scripts['sample']=='print(2)'
    w.undo(); assert w.save_project()
    assert Project.load(w.project.root).scripts['sample']=='print(1)'


def test_button_executes_script_in_container_context(operational_studio):
    from test_layouts import configure
    w=operational_studio;configure(w)
    w.project.scripts={'button':"ctx.write('Level',64)\nprint(ctx.screen)"}
    w.start_runtime();root=w.runtime_window
    root.containers['content'].actuate(dict(action='script',script='button'))
    pump_until(lambda:root.samples['Level'].value==64)
    assert 'main' in root.runtime.scripts.diagnostics()[-1]['message']


def test_runtime_exposes_script_errors_without_editor_page(operational_studio):
    w=operational_studio;w.project.scripts={'fail':"raise ValueError('Error de prueba')"}
    w.project.automation['startup']=['fail'];w.start_runtime();root=w.runtime_window
    pump_until(lambda:'Error de prueba' in root.statusBar().currentMessage())
    assert root.running


def test_task_and_screen_event_forms(operational_studio):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QDialogButtonBox
    w=operational_studio;w.project.scripts={'check':'print(ctx.event)'}
    def task():
        d=QApplication.activeModalWidget()
        d.fields['id'].setText('health');d.fields['interval_ms'].setValue(2500)
        d.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(0,task);w.automation_editor.tasks.edit(None)
    assert w.project.automation['tasks'][0]['script']=='check'
    def event():
        from PySide6.QtCore import Qt
        d=QApplication.activeModalWidget();d.fields['on_open'].item(0).setCheckState(Qt.CheckState.Checked);d.accept()
    QTimer.singleShot(0,event);w.screen_properties.edit_events()
    assert w.document()['on_open']==['check']


def test_script_write_reaches_s7_and_checks_readonly(plc_project):
    p=plc_project;p.scripts={'write':"ctx.write('Pump1.setpoint',42.5)",
                             'invalid':"ctx.write('Pump1.setpoint',90)\nctx.write('TankLevel',10)"}
    r=Runtime(p);r.start()
    try:
        wait_for(lambda:r.snapshot()['Pump1.setpoint'].quality=='good')
        r.scripts.submit('write');wait_for(lambda:r.snapshot()['Pump1.setpoint'].value==42.5)
        r.scripts.submit('invalid');wait_for(lambda:any(row['script']=='invalid' for row in r.scripts.diagnostics()))
        assert r.snapshot()['Pump1.setpoint'].value==42.5
        assert r.scripts.diagnostics()[-1]['status']=='error'
    finally:r.stop()
