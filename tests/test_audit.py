"""Regressions from the cross-module audit of 2026-10-04."""
import copy
import os
import time
from concurrent.futures import Future
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from abscada.project import coerce, Project
from abscada.runtime import Runtime, Sample
from abscada.storage import Repository, ProjectSampleReader, database_path, ArchiveReader
from abscada.alarms import AlarmEngine
from abscada.script_runner import TailOutput
from abscada.versioning import ProjectGit
from test_operations import operational_project
from test_operational_ui import operational_studio, pump_until
from test_core import wait_for


def test_failed_start_releases_all_services_and_lease(operational_project,monkeypatch):
    r=Runtime(operational_project)
    def fail(): raise RuntimeError('script worker could not start')
    monkeypatch.setattr(r.scripts,'start',fail)
    with pytest.raises(RuntimeError,match='script worker'):r.start()
    assert not r._thread.is_alive() and not r.operations.thread.is_alive()
    other=Runtime(operational_project);other.start();other.stop()


def test_project_exclusivity_without_historian(operational_project):
    p=operational_project;p.alarms['items']=[];p.historian['files']=[]
    first=Runtime(p);second=Runtime(p);first.start()
    try:
        with pytest.raises(RuntimeError,match='runtime'):second.start()
    finally:first.stop();second.stop()


def test_stop_invalidates_plc_quality_and_status(plc_project):
    r=Runtime(plc_project);r.start()
    try:wait_for(lambda:r.snapshot()['Pump1.setpoint'].quality=='good')
    finally:r.stop()
    assert r.snapshot()['Pump1.setpoint'].quality=='uncertain'
    assert all(s=='Detenido' for s in r.status().values())


def test_startup_is_a_barrier_before_tasks_and_screen_events(operational_project,monkeypatch):
    p=operational_project;p.scripts={n:'' for n in ['first','second','third','periodic','screen']}
    p.automation=dict(startup=['first','second','third'],tasks=[dict(id='t',script='periodic',interval_ms=100)])
    r=Runtime(p);calls=[]
    def execute(name,event,screen):
        calls.append(name)
        if event=='startup':time.sleep(.08)
    monkeypatch.setattr(r.scripts,'execute',execute)
    r.scripts.start();r.scripts.submit('screen','screen_open','main')
    try:wait_for(lambda:len(calls)>=5)
    finally:r.scripts.stop()
    assert calls[:4]==['first','second','third','screen']


def test_script_output_is_bounded_while_writing():
    output=TailOutput(16)
    for _ in range(100):output.write('x'*10000)
    output.write('end')
    assert output.getvalue()=='x'*13+'end'


def test_removed_alarm_retired_without_losing_pending_ack(operational_project,tmp_path):
    repo=Repository(tmp_path/'retired.sqlite3')
    try:
        identifier=repo.enter(operational_project.alarms['items'][0],90,time.time())
        AlarmEngine([],repo);repo.connection.commit()
        assert repo.active()==[]
        row=ArchiveReader(repo.path).alarms()[0]
        assert row['ack_at'] is None and row['returned_at'] is not None
        assert repo.connection.execute('SELECT event FROM alarm_events ORDER BY id DESC').fetchone()[0]=='disabled'
        assert repo.acknowledge([identifier],time.time(),'Ana')==1
    finally:repo.close()


def test_limited_history_merges_old_and_current_archives(operational_project):
    p=operational_project;now=time.time()
    for path,offsets in [(database_path(p),[0,1]),(p.root/'runtime/records/legacy.sqlite3',[-20,-10])]:
        repo=Repository(path)
        for offset in offsets:repo.sample('Level',Sample(offset,'good',now+offset),now+offset)
        repo.connection.commit();repo.close()
    rows=ProjectSampleReader(p).raw_samples('Level',now-30,now+5,limit=2)
    assert [r['recorded_at'] for r in rows]==[now-20,now-10]


@pytest.mark.parametrize('value',[9007199254740993,'9223372036854775807','-9223372036854775808'])
def test_integer_conversion_does_not_round_through_float(value):
    assert coerce(value,'int')==int(value)


@pytest.mark.parametrize('name',['CON','name.','bad:name','Main'])
def test_nonportable_document_names_are_rejected(operational_project,name):
    p=operational_project;p.screens[name]=copy.deepcopy(p.screens['main'])
    with pytest.raises(ValueError):p.validate()


def test_git_literal_asset_names(operational_project):
    p=operational_project;(p.root/'assets').mkdir()
    (p.root/'assets/[a].txt').write_text('literal')
    p.save();git=ProjectGit(p);git.initialize()
    assert 'assets/[a].txt' in git.run('ls-tree','-r','--name-only','HEAD')


def test_failed_rollback_keeps_recovery_copy(operational_project,monkeypatch):
    p=operational_project;before=p.manifest_path.read_bytes()
    p.manifest['name']='changed';p.scripts={'new':'print(1)'}
    replace=os.replace
    def fail(source,target):
        if str(target).endswith('new.py') or 'backup' in str(source):raise OSError('injected failure')
        return replace(source,target)
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError,match='Copias recuperables'):p.save()
    recovery=list(p.root.glob('.abscada-recovery-*'))
    assert len(recovery)==1
    assert (recovery[0]/'backup'/p.manifest_file).read_bytes()==before


def test_releasing_outside_runtime_button_cancels_command(operational_studio):
    w=operational_studio;w.project.screens['main']['elements']=[dict(id='write',kind='button',x=20,y=20,w=120,h=40,action='set',tag='Level',value=50)]
    w.start_runtime();root=w.runtime_window;QApplication.processEvents()
    inside=root.view.mapFromScene(QPointF(60,40));outside=root.view.mapFromScene(QPointF(300,200))
    QTest.mousePress(root.view.viewport(),Qt.MouseButton.LeftButton,pos=inside)
    QTest.mouseMove(root.view.viewport(),outside)
    QTest.mouseRelease(root.view.viewport(),Qt.MouseButton.LeftButton,pos=outside)
    assert root.runtime.snapshot()['Level'].value==0
    QTest.mouseClick(root.view.viewport(),Qt.MouseButton.LeftButton,pos=inside)
    assert root.runtime.snapshot()['Level'].value==50


def test_ack_does_not_wait_on_the_gui_thread(operational_studio,monkeypatch):
    import abscada.viewers as viewers
    w=operational_studio;w.add_element('alarm_view');w.start_runtime()
    viewer=next(i.proxy.widget() for i in w.runtime_window.scene.items() if hasattr(i,'proxy'))
    pending=Future();submitted=[]
    def submit(*args):submitted.append(args);return pending
    monkeypatch.setattr(viewers.COMMANDS,'submit',submit)
    viewer.acknowledge([1]);assert submitted and viewer.ack_future is pending
    assert not viewer.ack.isEnabled()
    pending.set_result(1);viewer.poll();assert viewer.ack_future is None


def test_python_typing_coalesces_project_snapshots(operational_studio):
    w=operational_studio;w.project.scripts={'sample':''};w.automation_editor.refresh()
    before=len(w.undo_stack)
    for part in ['p','r','i','n','t','(','1',')']:
        w.automation_editor.code.insertPlainText(part)
    assert len(w.undo_stack)==before+1
    w.undo();assert w.project.scripts['sample']==''


def test_modal_dialog_fields_readable_then_released(operational_studio):
    import shiboken6
    from PySide6.QtCore import QTimer,QCoreApplication,QEvent
    from abscada.project_dialogs import NewDocumentDialog
    dialog=NewDocumentDialog(operational_studio)
    dialog.name.setText('new_screen')
    QTimer.singleShot(0,dialog.accept)
    dialog.exec()
    assert dialog.document()['title']=='new_screen'
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(dialog)


def test_failed_runtime_window_is_destroyed(operational_studio,monkeypatch):
    import shiboken6
    from PySide6.QtCore import QCoreApplication,QEvent
    from abscada.runtime_window import RuntimeWindow
    created=[];errors=[]
    def fail(window):created.append(window);raise RuntimeError('startup failure')
    monkeypatch.setattr(RuntimeWindow,'start',fail)
    monkeypatch.setattr(operational_studio,'error',errors.append)
    operational_studio.start_runtime()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert errors and not shiboken6.isValid(created[0])


def test_archive_close_failure_releases_lease(operational_project,monkeypatch):
    from abscada.operations import Operations
    from abscada.storage import RuntimeLease
    close=Repository.close
    def fail(repository):
        close(repository)
        raise OSError('close failed')
    service=Operations(operational_project);service.start()
    monkeypatch.setattr(Repository,'close',fail)
    service.stop()
    assert 'close failed' in service.error
    lease=RuntimeLease(service.path.with_suffix('.lock'))
    lease.acquire();lease.close()


def test_archive_rejects_commands_during_shutdown(operational_project):
    from abscada.operations import Operations
    service=Operations(operational_project);service.start()
    try:
        service.stopping.set()
        with pytest.raises(RuntimeError):service.acknowledge([1],'operator')
    finally:service.stop()
