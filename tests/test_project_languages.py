"""Inline translations across persistence, scripts, editor and operating windows."""
import copy
import csv
import io
from pathlib import Path
import time

import pytest
from PySide6.QtWidgets import QApplication
from abscada import i18n
from abscada.project import Project
from abscada.project_languages import (resolve, default_language, entries, missing,
    export_csv, import_csv, resolved_project)
from abscada.runtime import Runtime, Sample
from abscada.runtime_window import RuntimeWindow
from abscada.script_runner import Context
from abscada.project_text_editor import ProjectTextsDialog
from abscada.text_lists import display_text
from abscada.ui import Window
from abscada.viewers import AlarmViewer, TrendViewer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bilingual(tmp_path):
    text = dict(id='text', kind='text', x=10, y=10, w=180, h=35, text={'es': 'Bomba', 'en': 'Pump'})
    button = dict(id='language', kind='button', x=10, y=60, w=100, h=35,
        text='EN', action='set_language', language='en')
    project = Project(tmp_path, dict(schema_version=1, name='Languages', startup_screen='main',
        languages=['es', 'en'], default_language='es'), {},
        [dict(name='temperature', type='float', initial=80., writable=True)], [],
        {'main': dict(title={'es': 'Sala', 'en': 'Room'}, width=800, height=600, elements=[text, button])}, {})
    project.alarms = dict(categories=[dict(id='process', name={'es': 'Proceso', 'en': 'Process'})],
        items=[dict(id='high', category='process', tag='temperature', condition='high', threshold=70,
                    message={'es': 'Temperatura alta', 'en': 'High temperature'})])
    project.trends = {'trend': dict(title={'es': 'Temperaturas', 'en': 'Temperatures'},
        axes=[dict(id='y', title={'es': 'Temperatura', 'en': 'Temperature'})],
        curves=[dict(id='t', tag='temperature', axis='y', title={'es': 'Tanque', 'en': 'Tank'})])}
    project.validate()
    return project


def test_legacy_fallback_and_roundtrip(bilingual):
    assert resolve('Plain', 'en', 'es') == 'Plain'
    assert resolve({'es': 'Bomba'}, 'en', 'es') == 'Bomba'
    assert resolve({'es': 'Bomba', 'en': ''}, 'en', 'es') == 'Bomba'
    source = copy.deepcopy(bilingual.screens)
    assert resolved_project(bilingual, 'en').screens['main']['elements'][0]['text'] == 'Pump'
    assert bilingual.screens == source
    bilingual.save()
    loaded = Project.load(bilingual.root)
    assert loaded.screens == bilingual.screens
    assert loaded.manifest['languages'] == ['es', 'en']
    bilingual.manifest.pop('languages'); bilingual.manifest.pop('default_language')
    bilingual.screens = {'main': dict(width=800, height=600, elements=[])}
    bilingual.alarms = dict(categories=[], items=[]); bilingual.trends = {}
    bilingual.faceplates = {}
    bilingual.validate()
    assert default_language(bilingual) == 'es'


@pytest.mark.parametrize('codes, default', [([], 'es'), (['es', 'es'], 'es'), (['es', 'en'], 'fr'), ([{}], 'es')])
def test_invalid_languages(bilingual, codes, default):
    bilingual.manifest.update(languages=codes, default_language=default)
    with pytest.raises(ValueError):
        bilingual.validate()


@pytest.mark.parametrize('text', [{'en': 'Pump'}, {'es': 'Bomba', 'fr': 'Pompe'}, {'es': 123}, []])
def test_invalid_translations(bilingual, text):
    bilingual.screens['main']['elements'][0]['text'] = text
    with pytest.raises(ValueError):
        bilingual.validate()


def test_csv_is_atomic_and_reports_missing(bilingual):
    element = bilingual.screens['main']['elements'][0]
    element['text'] = {'es': 'Bomba, "principal"\nA'}
    assert 'screens/main/elements/@text/text: falta traducción en' in list(missing(bilingual))
    content = export_csv(bilingual)
    rows = list(csv.reader(io.StringIO(content)))
    row = next(r for r in rows if r[0] == 'screens/main/elements/@text/text')
    row[2] = 'Main pump\nA'
    output = io.StringIO(); csv.writer(output).writerows(rows)
    bilingual.screens['main']['elements'].reverse()
    import_csv(bilingual, output.getvalue())
    assert element['text']['en'] == 'Main pump\nA'
    before = copy.deepcopy(bilingual.screens)
    with pytest.raises(ValueError):
        import_csv(bilingual, output.getvalue() + 'unknown,Hola,Hello\n')
    assert bilingual.screens == before
    assert not any('elements/@text/text' in message for message in missing(bilingual))


def test_text_lists_translate_values_but_keep_process_data():
    element = dict(texts=[dict(value='1', text={'es': 'Marcha', 'en': 'Running'})],
                   default_text={'es': 'Otro', 'en': 'Other'})
    assert display_text(element, Sample(1, 'good', 0), language='en') == 'Running'
    assert display_text(element, Sample(2, 'good', 0), language='en') == 'Other'
    assert display_text(element, Sample(1, 'bad', 0), language='en') == '—'


def test_runtime_action_script_context_and_shared_windows(bilingual):
    app = QApplication.instance() or QApplication([])
    window = RuntimeWindow(bilingual)
    other = RuntimeWindow(bilingual, owner=window)
    try:
        window.actuate(bilingual.screens['main']['elements'][1])
        window.refresh(); other.refresh()
        assert window.runtime.language == other.runtime.language == 'en'
        assert window.windowTitle().endswith('Room')
        assert other.windowTitle() == 'Room'
        assert i18n.language() == 'es'
        window.runtime.set_language('es')
        with pytest.raises(ValueError):
            window.runtime.set_language('fr')
        context = Context(dict(event='button', samples={}, language='es', languages=['es', 'en']))
        context.set_language('en')
        assert context.language == context.language_change == 'en'
        bilingual.scripts['lang'] = "assert ctx.language == 'es'\nctx.set_language('en')"
        window.runtime.project.scripts = bilingual.scripts
        window.runtime.scripts.execute('lang', 'button', '')
        assert window.runtime.language == 'en'
    finally:
        other.close(); window.close(); app.processEvents()


def test_studio_preserves_other_translations_and_undo(bilingual, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window(bilingual)
    monkeypatch.setattr(window, 'maybe_save', lambda: True)
    try:
        window.editing_language_field.setCurrentText('en')
        window.render_scene(['text'])
        window.show_properties()
        assert window.text_field.text() == 'Pump'
        window.text_field.setText('Feed pump')
        window.apply_fields()
        assert window.project.screens['main']['elements'][0]['text'] == {'es': 'Bomba', 'en': 'Feed pump'}
        window.undo()
        assert window.project.screens['main']['elements'][0]['text']['en'] == 'Pump'
        dialog = ProjectTextsDialog(window)
        row = next(i for i, e in enumerate(dialog.rows) if e.path == 'screens/main/elements/@text/text')
        dialog.table.item(row, 2).setText('Water pump')
        assert window.project.screens['main']['elements'][0]['text']['en'] == 'Water pump'
        dialog.close()
    finally:
        window.close(); app.processEvents()


def test_historic_messages_and_trends_follow_language(bilingual):
    app = QApplication.instance() or QApplication([])
    runtime = Runtime(bilingual)
    alarm = AlarmViewer(bilingual, runtime)
    trend = TrendViewer(bilingual, bilingual.trends['trend'], runtime)
    try:
        alarm.rows = [dict(alarm_id='high', message='Old saved Spanish text')]
        runtime.set_language('en')
        assert alarm.translated_rows()[0]['message'] == 'High temperature'
        alarm.rows = [dict(alarm_id='removed', message='{"es":"Retirada","en":"Removed"}')]
        assert alarm.translated_rows()[0]['message'] == 'Removed'
        trend.poll()
        assert trend.chart.title() == 'Temperatures'
        assert trend.axes['y'].titleText() == 'Temperature'
        assert trend.curve_visible['t'].text() == 'Tank'
        assert trend.source.itemText(0) == 'Real time'
        assert i18n.tr('Guardar') == 'Guardar'
    finally:
        alarm.close(); trend.close(); runtime.stop(); app.processEvents()


def test_every_shipped_project_has_complete_translations():
    for path in (ROOT / 'examples').glob('*/*.abscada'):
        project = Project.load(path)
        assert project.manifest['languages'] == ['es', 'en'], path
        assert not list(missing(project)), path
        for entry in entries(project):
            assert isinstance(entry.value, dict), entry.path


def test_station_and_user_preference_do_not_change_studio(bilingual, monkeypatch, tmp_path):
    from abscada.security import Session
    path = tmp_path / 'settings.json'
    monkeypatch.setattr(i18n, 'settings_path', lambda: path)
    bilingual.manifest['initial_language'] = 'station'
    runtime = Runtime(bilingual)
    runtime.set_language('en')
    assert Runtime(bilingual).language == 'en'
    bilingual.manifest['initial_language'] = 'user'
    user_runtime = Runtime(bilingual)
    monkeypatch.setattr(user_runtime.security, 'login', lambda name, password: Session(name, '', (), frozenset()))
    monkeypatch.setattr(user_runtime.security.store, 'find', lambda name: {'language': 'es'})
    user_runtime.login('operator', 'password')
    assert user_runtime.language == 'es'
    assert Runtime(bilingual).language == 'en'  # The user preference did not overwrite the station.
    assert i18n.language() == 'es'
    bilingual.manifest['initial_language'] = 'project'
    assert Runtime(bilingual).language == 'es'


def test_dynamic_and_list_editors_preserve_spanish(bilingual):
    from abscada.dynamic_editor import DynamicDialog
    from abscada.text_list_editor import TextListDialog
    app = QApplication.instance() or QApplication([])
    studio = Window(bilingual)
    studio.editing_language_field.setCurrentText('en')
    try:
        element = bilingual.screens['main']['elements'][0]
        element['dynamics'] = {'default': {'text': {'es': 'Marcha', 'en': 'Running'}},
                               'disabled_reason': {'es': 'Bloqueada', 'en': 'Locked'}}
        dialog = DynamicDialog(studio, element)
        dialog.styles['default'].fields['text'].setText('On')
        dialog.reason.setText('')
        dialog.validate()
        assert dialog.data()['dynamics']['default']['text'] == {'es': 'Marcha', 'en': 'On'}
        assert dialog.data()['dynamics']['disabled_reason'] == {'es': 'Bloqueada', 'en': ''}
        dialog.close()
        mapping = {'texts': [{'value': '1', 'text': {'es': 'Marcha', 'en': 'Running'}}],
                   'default_text': {'es': 'Otro', 'en': 'Other'}}
        dialog = TextListDialog(mapping, 'int', studio)
        dialog.table.item(0, 1).setText('On')
        assert dialog.mapping()['texts'][0]['text'] == {'es': 'Marcha', 'en': 'On'}
        dialog.close()
    finally:
        studio.close(); app.processEvents()


def test_declaring_languages_in_legacy_project_and_adding_a_third_language(bilingual):
    legacy = resolved_project(bilingual, 'es')
    legacy.manifest.pop('languages'); legacy.manifest.pop('default_language')
    legacy.screens['main']['elements'].pop()
    legacy.faceplates = {}
    legacy.validate()
    legacy.manifest.update(languages=['es', 'en'], default_language='es')
    legacy.validate()
    assert isinstance(legacy.faceplates['estandar__deposito_vertical']['title'], dict)
    bilingual.manifest['languages'].append('fr')
    bilingual.validate()
    assert any('falta traducción fr' in text for text in missing(bilingual))
