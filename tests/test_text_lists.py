from types import SimpleNamespace
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog
from abscada.project import Project
from abscada.text_lists import display_text, validate_text_list
from abscada.text_list_editor import TextListDialog
from test_operational_ui import operational_project, operational_studio, pump_until


def element():
    return dict(texts=[dict(value='0', text='Parado'), dict(value='1', text='En marcha'),
                       dict(value='2', text='Avería')], default_text='Desconocido')


@pytest.mark.parametrize('value,expected', [(0,'Parado'), (1,'En marcha'), (2,'Avería'), (9,'Desconocido'), (1.0,'En marcha')])
def test_discrete_values_and_fallback(value, expected):
    assert display_text(element(), SimpleNamespace(value=value, quality='good')) == expected


def test_boolean_string_quality_and_design():
    e = dict(texts=[dict(value='false', text='Parado'), dict(value='1', text='Marcha')])
    validate_text_list(e, 'bool')
    assert display_text(e, SimpleNamespace(value=True, quality='good')) == 'Marcha'
    assert display_text(e, SimpleNamespace(value=False, quality='good')) == 'Parado'
    e = dict(texts=[dict(value='AUTO', text='Automático')])
    assert display_text(e, SimpleNamespace(value='AUTO', quality='good')) == 'Automático'
    assert display_text(e, SimpleNamespace(value='AUTO', quality='bad')) == '—'
    assert display_text(e) == '—'
    assert display_text(e, SimpleNamespace(value='AUTO', quality='good'), design=True) == 'Lista de textos'


@pytest.mark.parametrize('kind,values', [('int',['1','1.0']), ('bool',['1','true']), ('float',['nan']), ('int',['1.5']), ('bool',['2'])])
def test_invalid_and_duplicate_values(kind, values):
    with pytest.raises(ValueError):
        validate_text_list(dict(texts=[dict(value=v,text='Estado') for v in values]), kind)


def test_editor_configures_list_atomically_and_roundtrips(operational_studio):
    w = operational_studio
    w.add_element('text_list')
    w.tag_field.setCurrentText('Level'); w.apply_fields()
    assert w.text_list_button.isVisible() and not w.unit_field.isVisible()
    def edit():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, TextListDialog)
        dialog.add_row('0','Parado'); dialog.add_row('1','En marcha')
        dialog.default.setText('Desconocido'); dialog.accept()
    QTimer.singleShot(0, edit)
    w.text_list_button.click()
    e = w.scene.selectedItems()[0].element
    assert len(e['texts']) == 2
    w.undo(); assert w.document()['elements'][0]['texts'] == []
    w.redo(); w.save_project()
    assert Project.load(w.project.root).screens['main']['elements'][0]['texts'] == e['texts']
    w.start_runtime(); live = w.runtime_window
    runtime_element = next(i.element for i in live.scene.items() if i.element['kind'] == 'text_list')
    live.runtime.write('Level',1)
    pump_until(lambda: live.samples['Level'].value == 1)
    assert display_text(runtime_element, live.samples['Level']) == 'En marcha'
    live.runtime.write('Level',9)
    pump_until(lambda: live.samples['Level'].value == 9)
    assert display_text(runtime_element, live.samples['Level']) == 'Desconocido'


def test_dialog_rejects_duplicates_cancel_and_remove(operational_studio):
    d = TextListDialog(element(), 'int', operational_studio)
    d.add_row('01', 'Duplicado'); d.accept()
    assert d.result() != QDialog.DialogCode.Accepted and d.error.text()
    d.remove_rows(); assert d.table.rowCount() == 3
    d.reject(); assert d.result() == QDialog.DialogCode.Rejected


def test_faceplate_parameter_mapping_and_project_validation(operational_studio):
    p = operational_studio.project
    e = dict(id='state',kind='text_list',x=0,y=0,w=200,h=40,tag='$state',
             texts=[dict(value='0',text='Correcto'),dict(value='1',text='Fallo')])
    p.faceplates['status'] = dict(width=200,height=40,parameters={'state':'bool'},elements=[e])
    p.screens['main']['elements'] = [dict(id='device',kind='faceplate',x=0,y=0,w=200,h=40,
                                        template='status',bindings={'state':'Fault'})]
    p.validate()
    expanded = next(item for item in p.elements('main') if item['kind'] == 'text_list')
    assert expanded['tag'] == 'Fault'
    assert display_text(expanded, SimpleNamespace(value=True,quality='good')) == 'Fallo'
    e['texts'].append(dict(value='true',text='Duplicado'))
    with pytest.raises(ValueError): p.validate()
