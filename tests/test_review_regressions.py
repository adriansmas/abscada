"""Acceptance regressions for findings F01–F16 of the product review."""
import copy
import pytest
from PySide6.QtCore import QTimer,QPointF,QPoint,Qt,QEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox, QMessageBox
from PySide6.QtTest import QTest
from abscada import dynamics
from abscada.runtime import Sample
from abscada.project import Project
from abscada.value_editor import ValueEditor,StructureEditor,engineering_value
from abscada.dynamic_editor import DynamicDialog
from abscada.visual_preview import VisualPreview
from test_core import wait_for
from test_operations import operational_project
from test_operational_ui import operational_studio
from test_ui import studio


def condition(value,tag='Fault'):
    return dict(tag=tag,op='eq',value=value,bad=False)


def command(identifier,**extra):
    return dict(id=identifier,kind='button',x=40,y=40,w=170,h=50,tag='Fault',action='set',value=True,**extra)


def find(window,identifier):
    return next(i for i in window.scene.items() if hasattr(i,'element') and i.element['id']==identifier)


@pytest.mark.parametrize('text,kind,expected',[('23,5','float',23.5),('23.5','float',23.5),('-1,25e2','float',-125.),('9223372036854775807','int',9223372036854775807)])
def test_localized_engineering_numbers(text,kind,expected):
    assert engineering_value(text,kind)==expected


@pytest.mark.parametrize('text',['1.234,56','1,234.56','1 234','nan','infinity'])
def test_ambiguous_numbers_rejected(text):
    with pytest.raises(ValueError):engineering_value(text,'float')


def test_invalid_variable_preserves_draft_then_accepts_comma(operational_studio):
    w=operational_studio;seen=[]
    def fill():
        d=QApplication.activeModalWidget();name=d.findChild(QLineEdit,'variableName');name.setText('Temperature')
        value=d.findChild(ValueEditor);value.edit.setText('incorrecto');d.accept()
        seen.append(d.isVisible() and name.text()=='Temperature' and hasattr(d,'validation_error'))
        value.edit.setText('23,5');d.accept()
    QTimer.singleShot(0,fill);w.variable_form(None)
    assert seen==[True] and w.project.tags()['Temperature']['initial']==23.5


def test_new_boolean_has_valid_default(operational_studio):
    w=operational_studio
    def fill():
        d=QApplication.activeModalWidget();d.findChild(QLineEdit,'variableName').setText('Ready')
        d.findChildren(QComboBox)[0].setCurrentText('bool')
        assert d.findChild(ValueEditor).boolean.isVisible()
        d.accept()
    QTimer.singleShot(0,fill);w.variable_form(None)
    assert w.project.tags()['Ready']['initial'] is False


def test_nested_structure_and_access_without_json(operational_studio):
    w=operational_studio;w.project.types={'Motor':{'run':'bool','speed':'float'},'Station':{'motor':'Motor','count':'int'}}
    def fill():
        d=QApplication.activeModalWidget();d.findChild(QLineEdit,'variableName').setText('S1')
        d.findChildren(QComboBox)[0].setCurrentText('Station');tree=d.findChild(StructureEditor)
        tree.fields['motor.speed'][0].edit.setText('34,2');tree.fields['motor.run'][1].setChecked(True);d.accept()
    QTimer.singleShot(0,fill);w.variable_form(None)
    assert w.project.tags()['S1.motor.speed']['initial']==34.2
    assert w.project.tags()['S1.motor.run']['writable'] is True
    assert w.project.tags()['S1.count']['initial']==0


def test_visibility_switches_overlapping_buttons_and_hit_targets(operational_studio):
    w=operational_studio;a=command('start',dynamics={'visible':condition(False)});b=command('stop',dynamics={'visible':condition(True)});b['value']=False
    w.project.screens['main']['elements']=[a,b];w.start_runtime();r=w.runtime_window;r.refresh()
    assert find(r,'start').isVisible() and not find(r,'stop').isVisible()
    point=r.view.mapFromScene(QPointF(90,65));QTest.mouseClick(r.view.viewport(),Qt.MouseButton.LeftButton,pos=point);r.refresh()
    assert r.runtime.snapshot()['Fault'].value is True
    assert not find(r,'start').isVisible() and find(r,'stop').isVisible()
    QTest.mouseClick(r.view.viewport(),Qt.MouseButton.LeftButton,pos=point);r.refresh()
    assert r.runtime.snapshot()['Fault'].value is False


def test_conditions_roundtrip_faceplate_parameters_and_colors(operational_project):
    p=operational_project
    child=command('child',dynamics={'visible':condition(False,'$run'),'states':[dict(when=condition(True,'$run'),style={'color':'#123456'})]});child['tag']='$run'
    p.faceplates['motor']=dict(width=250,height=100,parameters={'run':'bool'},elements=[child])
    p.screens['main']['elements']=[dict(id='motor1',kind='faceplate',template='motor',bindings={'run':'Fault'},x=0,y=0,w=250,h=100)]
    p.save();p=Project.load(p.root);expanded=list(p.elements('main'))[0]
    assert expanded['dynamics']['visible']['tag']=='Fault'
    assert dynamics.effective(expanded,{'Fault':Sample(True,'good',0)})['color']=='#123456'


def test_pilot_exact_colors_and_bad_quality(operational_project):
    e=dict(id='pilot',kind='lamp',tag='Fault',lamp_colors={'on':'#234567','off':'#123456','bad':'#654321'})
    for value,quality,expected in [(True,'good','#234567'),(False,'good','#123456'),(True,'bad','#654321')]:
        assert dynamics.effective(e,{'Fault':Sample(value,quality,0)})['lamp_color']==expected
    e['lamp_colors']['on']='#998877';assert dynamics.effective(e,{'Fault':Sample(True,'good',0)})['lamp_color']=='#998877'


def test_state_dialog_keeps_both_conditions_and_colors(operational_studio):
    w=operational_studio;e=command('command',dynamics={'visible':condition(False),'enabled':condition(True),'bad':{'color':'#987654'}})
    d=DynamicDialog(w,e);assert d.data()['dynamics']==e['dynamics'];d.validate();d.close()


def test_missing_or_bad_condition_quality_fails_closed():
    e=command('c',dynamics={'visible':condition(False),'enabled':condition(True)})
    assert not dynamics.permitted(e,{},'visible')
    assert not dynamics.permitted(e,{'Fault':Sample(True,'bad',0)},'enabled')


def test_readonly_control_rejected_with_object_location(operational_project):
    p=operational_project;p.variables[1]['writable']=False;p.screens['main']['elements']=[command('readonly')]
    with pytest.raises(ValueError,match='main / readonly.*solo lectura'):p.validate()


def test_inspector_filters_types_and_hides_unused_properties(operational_studio):
    w=operational_studio;w.add_element('lamp')
    choices=[w.tag_field.itemText(i) for i in range(w.tag_field.count())]
    assert 'Fault' in choices and 'Level' not in choices
    assert not w.text_field.isVisible() and not w.unit_field.isVisible() and not w.decimals_field.isVisible()
    w.add_element('button');assert w.text_field.isVisible() and not w.unit_field.isVisible()
    w.resize(1366,768);QApplication.processEvents()
    assert w.inspector_panel.horizontalScrollBar().maximum()==0


def test_multi_edit_is_one_undo_and_preserves_bindings(operational_studio):
    w=operational_studio;w.project.screens['main']['elements']=[command('one'),command('two')];w.render_scene(['one','two'])
    assert w.common_properties.isVisible();before=len(w.undo_stack)
    w.common_properties.fields['h'].setValue(75);w.common_properties.apply('h')
    assert len(w.undo_stack)==before+1
    assert all(e['h']==75 and e['tag']=='Fault' for e in w.document()['elements'])
    w.undo();assert all(e['h']==50 for e in w.document()['elements'])


def test_copy_style_does_not_copy_command_or_tag(operational_studio):
    from abscada.selection_editor import copy_style,paste_style
    w=operational_studio;a=command('a',color='#112233');b=command('b');b.update(tag='Level',value=20)
    w.project.screens['main']['elements']=[a,b];w.render_scene(['a']);copy_style(w);w.render_scene(['b']);paste_style(w)
    target=next(e for e in w.document()['elements'] if e['id']=='b')
    assert target['color']=='#112233' and target['tag']=='Level' and target['value']==20


def test_layer_flags_do_not_hide_runtime_and_group_duplicate_is_independent(operational_studio):
    w=operational_studio;w.project.screens['main']['elements']=[command('one'),command('two')];w.render_scene(['one','two'])
    w.group_elements();group=w.document()['elements'][0]['group'];w.duplicate_element()
    assert all(e['group']!=group for e in w.document()['elements'][2:])
    w.toggle_layer_flag('editor_hidden');w.toggle_layer_flag('editor_locked')
    w.start_runtime();assert all(find(w.runtime_window,e['id']).isVisible() for e in w.document()['elements'])


def test_momentary_release_outside_and_on_focus_loss(operational_studio):
    w=operational_studio;e=command('hold');e['action']='momentary';w.project.screens['main']['elements']=[e];w.start_runtime();r=w.runtime_window
    point=r.view.mapFromScene(QPointF(90,65));outside=r.view.mapFromScene(QPointF(400,400))
    QTest.mousePress(r.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
    r.refresh()
    assert r.runtime.snapshot()['Fault'].value is True
    assert find(r,'hold').pressed
    QTest.mouseRelease(r.view.viewport(),Qt.MouseButton.LeftButton,pos=outside)
    assert r.runtime.snapshot()['Fault'].value is False
    QTest.mousePress(r.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
    QApplication.sendEvent(r,QEvent(QEvent.Type.WindowDeactivate))
    assert r.runtime.snapshot()['Fault'].value is False and not r.momentary


def test_closing_runtime_sends_s7_release_before_stopping(studio):
    from abscada.connectors import S7
    w=studio;e=command('hold');e.update(tag='Pump1.running',action='momentary')
    w.project.screens['overview']['elements']=[e];w.start_runtime();r=w.runtime_window
    wait_for(lambda:r.runtime.snapshot()['Pump1.running'].quality=='good')
    r.actuate(find(r,'hold').element,phase='press')
    wait_for(lambda:r.runtime.snapshot()['Pump1.running'].value is True)
    config=copy.deepcopy(r.project.connections[0]);binding=r.runtime.tags['Pump1.running']['binding']
    w.stop_runtime()
    adapter=S7(config)
    try:
        adapter.connect();assert adapter.read(binding['address'],'bool') is False
    finally:adapter.close()


def test_lost_quality_cancels_gesture_without_replaying_release(operational_studio,monkeypatch):
    w=operational_studio;e=command('hold');e['action']='momentary';w.project.screens['main']['elements']=[e];w.start_runtime();r=w.runtime_window
    item=find(r,'hold');r.actuate(item.element,phase='press');item.pressed=True
    r.runtime.tags['Fault']['binding']={'connection':'offline'}
    r.runtime._set('Fault',True,'bad');messages=[];r.diagnostic.connect(messages.append)
    r.refresh()
    assert not item.pressed and not r.momentary and any('liberación' in m for m in messages)
    r.runtime.tags['Fault'].pop('binding')
    r.runtime._set('Fault',True,'good');r.refresh()
    assert r.runtime.snapshot()['Fault'].value is True


def test_connection_validation_keeps_fields(operational_studio):
    w=operational_studio;observed=[]
    def fill():
        d=QApplication.activeModalWidget();d.accept();observed.append(d.isVisible() and hasattr(d,'validation_error'))
        d.findChildren(QLineEdit)[0].setText('PLC1');d.accept()
    QTimer.singleShot(0,fill);w.connection_form(None)
    assert observed==[True] and w.project.connections[0]['id']=='PLC1'


def test_structure_duplication_clears_plc_bindings(studio):
    w=studio;source=copy.deepcopy(w.project.variables[0])
    assert source.get('bindings')
    def fill():
        d=QApplication.activeModalWidget();d.findChild(QLineEdit,'variableName').setText('PumpCopy');d.accept()
    QTimer.singleShot(0,fill);w.variable_form(None,duplicate=source)
    assert all(not tag.get('binding') for name,tag in w.project.tags().items() if name.startswith('PumpCopy.'))


def test_local_color_change_undo_preserves_other_objects(operational_studio):
    w=operational_studio
    w.project.screens['main']['elements']=[command('a',color='#112233'),command('b',color='#112233'),command('local',color='#abcdef')]
    w.render_scene();w.mutate(lambda:w.document()['elements'][0].__setitem__('color','#445566'))
    colors=lambda:[dynamics.effective(e,{},True)['color'] for e in w.document()['elements']]
    assert colors()==['#445566','#112233','#abcdef']
    w.undo();assert colors()==['#112233','#112233','#abcdef']


def test_momentary_released_when_permission_changes(operational_studio):
    w=operational_studio;e=command('hold',dynamics={'enabled':dict(tag='Level',op='eq',value=0.,bad=False)});e['action']='momentary'
    w.project.screens['main']['elements']=[e];w.start_runtime();r=w.runtime_window;item=find(r,'hold')
    r.actuate(item.element,phase='press');item.pressed=True;r.runtime.write('Level',1);r.refresh()
    assert r.runtime.snapshot()['Fault'].value is False and not item.isEnabled()


def test_press_release_numeric_values_and_navigation_cleanup(operational_studio):
    w=operational_studio;e=command('hold');e.update(action='press_release',tag='Level',press_value=7.,release_value=2.)
    w.project.screens['main']['elements']=[e];w.start_runtime();r=w.runtime_window;item=find(r,'hold')
    r.actuate(item.element,phase='press');assert r.runtime.snapshot()['Level'].value==7.
    r.select_screen('main');assert r.runtime.snapshot()['Level'].value==2.


def test_visual_preview_has_no_runtime_or_writes(operational_studio,monkeypatch):
    from abscada.runtime import Runtime
    def fail(*a,**k):raise AssertionError('Preview must not construct a Runtime')
    monkeypatch.setattr(Runtime,'__init__',fail)
    w=operational_studio;w.project.screens['main']['elements']=[command('c',dynamics={'visible':condition(True)})]
    preview=VisualPreview(w);preview.show();assert not find(preview,'c').isVisible()
    preview.tag.setCurrentText('Fault');preview.value.boolean.setCurrentIndex(1);preview.apply_state()
    assert find(preview,'c').isVisible() and not hasattr(preview,'runtime')
    preview.close()


def test_preview_layout_uses_real_containers_and_updates_conditions(operational_studio):
    w=operational_studio;w.project.screens['main']['elements']=[command('child',dynamics={'visible':condition(True)})]
    w.project.screens['layout']=dict(width=1200,height=800,layout=True,elements=[dict(id='content',kind='screen_container',screen='main',x=10,y=50,w=1000,h=650)])
    w.document_name='layout';preview=VisualPreview(w);preview.show()
    child=find(preview.containers['content'],'child');assert not child.isVisible()
    preview.tag.setCurrentText('Fault');preview.value.boolean.setCurrentIndex(1);preview.apply_state()
    assert child.isVisible() and preview.containers['content'].runtime is None
    preview.close()


def test_group_drag_preserves_relative_positions_with_grid(operational_studio):
    w=operational_studio;a=command('a');b=command('b');b.update(x=303,y=43)
    w.project.screens['main']['elements']=[a,b];w.render_scene(['a','b']);w.group_elements();w.scene.clearSelection()
    point=w.view.mapFromScene(QPointF(90,65))
    QTest.mouseClick(w.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
    assert len(w.scene.selectedItems())==2
    QTest.mousePress(w.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
    QTest.mouseMove(w.view.viewport(),point+QPoint(37,21),delay=20)
    QTest.mouseRelease(w.view.viewport(),Qt.MouseButton.LeftButton,pos=point+QPoint(37,21))
    a,b=w.document()['elements'];assert a['x']!=40
    assert b['x']-a['x']==263 and b['y']-a['y']==3


def test_runtime_difference_clears_after_restart(operational_studio,monkeypatch):
    w=operational_studio;w.start_runtime();w.add_element('text');assert w.restart_button.isVisible()
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    w.restart_runtime();assert not w.restart_button.isVisible()
    assert len(w.runtime_window.project.screens['main']['elements'])==1


def test_unknown_property_and_missing_tag_reported(operational_project):
    p=operational_project;e=command('unfinished');e.pop('tag');e['typo']=True;p.screens['main']['elements']=[e]
    warnings=dynamics.issues(p)
    assert any('sin variable' in s for s in warnings) and any('typo' in s for s in warnings)


def test_probe_is_read_only_and_reports_address_failure(monkeypatch):
    from abscada.connection_diagnostics import probe,REGISTRY
    calls=[]
    class Adapter:
        def __init__(self,*a):pass
        def connect(self):calls.append('connect')
        def read(self,*a):raise ValueError('DB inexistente')
        def close(self):calls.append('close')
    monkeypatch.setitem(REGISTRY,'s7',Adapter)
    # Keep metadata validation independent of the substituted adapter.
    import abscada.connection_diagnostics as module
    class Definition:
        def validate_connection(self,*a):pass
        def validate_binding(self,*a):pass
    monkeypatch.setattr(module,'definition',lambda *_:Definition())
    result=probe(dict(protocol='s7',host='localhost'),dict(address={}), 'float',False)
    assert 'no se pudo leer la dirección' in result and calls==['connect','close']
