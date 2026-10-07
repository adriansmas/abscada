import copy
import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog
from abscada.project import Project
from test_operational_ui import operational_studio, operational_project, pump_until


def configure(w):
    p = w.project
    p.screens['header'] = dict(width=1000,height=100,elements=[
        dict(id='nav',kind='button',x=20,y=20,w=160,h=50,text='Detalle',
             action='screen',screen='detail',target_container='content')])
    p.screens['detail'] = dict(width=800,height=500,elements=[
        dict(id='write',kind='button',x=20,y=20,w=160,h=50,text='Escribir',action='set',tag='Level',value=45),
        dict(id='popup',kind='button',x=200,y=20,w=160,h=50,text='Emergente',action='popup',screen='main')])
    p.screens['layout'] = dict(width=1000,height=700,elements=[
        dict(id='header',kind='screen_container',x=0,y=0,w=1000,h=100,screen='header'),
        dict(id='content',kind='screen_container',x=0,y=100,w=1000,h=600,screen='main')])
    p.manifest['startup_screen']='layout'
    p.validate()
    w.document_name='layout'; w.render_scene()


def test_layout_navigation_preserves_header_and_shares_runtime(operational_studio):
    w=operational_studio; configure(w); w.start_runtime()
    root=w.runtime_window
    assert set(root.containers)=={'header','content'}
    header=root.containers['header']; content=root.containers['content']
    QApplication.processEvents()
    QTest.mouseClick(header.view.viewport(),Qt.MouseButton.LeftButton,
                     pos=header.view.mapFromScene(QPointF(100,45)))
    pump_until(lambda: content.document_name=='detail')
    assert root.document_name=='layout' and root.containers['header'] is header
    assert content.runtime is root.runtime is header.runtime
    content.actuate(dict(action='set',tag='Level',value=45))
    pump_until(lambda: header.samples['Level'].value==45)
    content.actuate(dict(action='popup',screen='main'))
    pump_until(lambda: 'main' in root.popups)
    assert root.popups['main'].runtime is root.runtime
    content.actuate(dict(action='screen',screen='main'))
    pump_until(lambda: content.document_name=='main')
    assert root.containers['header'] is header
    root.navigate_screen('detail','__window__')
    assert root.document_name=='detail' and not root.containers


def test_layout_persistence_editor_and_undo(operational_studio):
    w=operational_studio; configure(w)
    item=next(i for i in w.scene.items() if i.element['id']=='content')
    item.setSelected(True)
    assert w.container_group.isVisible()
    assert w.container_screen_field.findText('layout')==-1
    w.container_screen_field.setCurrentText('detail'); w.apply_fields()
    assert w.document()['elements'][1]['screen']=='detail'
    w.undo(); assert w.document()['elements'][1]['screen']=='main'
    w.redo(); w.save_project()
    assert Project.load(w.project.root).screens['layout']==w.document()
    w.document_name='header'; w.render_scene()
    w.scene.items()[0].setSelected(True)
    assert w.target_container_field.currentData()=='content'
    w.target_container_field.setCurrentIndex(w.target_container_field.findData('__window__'))
    w.apply_fields()
    assert w.document()['elements'][0]['target_container']=='__window__'


@pytest.mark.parametrize('change', ['self','nested','missing','target','faceplate'])
def test_invalid_compositions_rejected(operational_studio,change):
    w=operational_studio; configure(w); p=w.project
    if change in {'self','nested','missing'}:
        p.screens['layout']['elements'][0]['screen']={'self':'layout','nested':'other','missing':'missing'}[change]
        if change=='nested': p.screens['other']=copy.deepcopy(p.screens['layout'])
    elif change=='target': p.screens['header']['elements'][0]['target_container']='unknown'
    else: p.faceplates['invalid']=dict(width=100,height=100,parameters={},elements=[copy.deepcopy(p.screens['layout']['elements'][0])])
    with pytest.raises(ValueError): p.validate()


def test_runtime_rejects_missing_zone_and_embedded_layout(operational_studio):
    w=operational_studio; configure(w); w.start_runtime(); root=w.runtime_window
    with pytest.raises(ValueError): root.navigate_screen('detail','missing')
    with pytest.raises(ValueError): root.navigate_screen('layout','content')
    assert root.containers['content'].document_name=='main'
    root.navigate_screen('detail','content')
    for _ in range(5):
        root.navigate_screen('main','content'); root.navigate_screen('detail','content')
    assert len(root.containers)==2


def test_create_layout_and_add_container_from_palette(operational_studio,monkeypatch):
    w=operational_studio
    def create():
        dialog=QApplication.activeModalWidget()
        dialog.title.setText('shell'); dialog.accept()
    QTimer.singleShot(0,create)
    w.new_document(False)
    assert w.document_name=='shell'
    w.add_element('screen_container')
    # A layout is just a screen with containers.
    from abscada.screen_tree import is_layout
    assert is_layout(w.document())
    assert w.scene.selectedItems()[0].element['screen']=='main'
    assert w.container_group.isVisible()


def test_embedded_viewers_are_disposed_on_navigation(operational_studio):
    import shiboken6
    from abscada.viewers import AlarmViewer, TrendViewer
    w=operational_studio; configure(w)
    p=w.project
    p.screens['detail']['elements']=[
        dict(id='trend',kind='trend',view='process',x=0,y=0,w=800,h=400),
        dict(id='alarms',kind='alarm_view',view='process',x=0,y=400,w=800,h=300)]
    p.validate(); w.start_runtime(); root=w.runtime_window
    root.navigate_screen('detail','content')
    content=root.containers['content']
    viewers=[i.proxy.widget() for i in content.scene.items() if hasattr(i,'proxy')]
    assert any(isinstance(v,TrendViewer) for v in viewers)
    assert any(isinstance(v,AlarmViewer) for v in viewers)
    root.navigate_screen('main','content'); QApplication.processEvents()
    assert all(not shiboken6.isValid(v) for v in viewers)
    assert root.containers['header'].document_name=='header'
