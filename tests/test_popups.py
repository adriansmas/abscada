import copy
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from abscada.project import Project
from test_operational_ui import operational_studio, operational_project, pump_until
from test_ui import studio


def configure(window):
    window.project.screens['settings'] = {
        'title': 'Ajustes', 'width': 480, 'height': 320,
        'elements': [dict(id='close', kind='button', x=20, y=240, w=120, h=40,
                          text='Cerrar', action='close_popup')]}
    window.project.screens['second'] = copy.deepcopy(window.project.screens['settings'])
    window.project.screens['main']['elements'] = [
        dict(id='open', kind='button', x=20, y=20, w=160, h=40,
             text='Ajustes', action='popup', screen='settings')]
    window.project.validate()
    window.render_scene()


def click(window, x, y):
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.view.mapFromScene(QPointF(x, y)))


def test_button_opens_shared_runtime_and_close_only_closes_popup(operational_studio):
    window = operational_studio
    configure(window)
    window.start_runtime()
    root = window.runtime_window
    click(root, 100, 40)
    pump_until(lambda: 'settings' in root.popups)
    popup = root.popups['settings']
    assert popup.isVisible() and popup.windowTitle() == 'Ajustes'
    assert popup.runtime is root.runtime and popup.project is root.project
    assert root.document_name == 'main'
    popup.actuate(dict(action='set', tag='Level', value=42))
    pump_until(lambda: root.samples['Level'].value == 42 and popup.samples['Level'].value == 42)
    assert root.open_popup('settings') is popup
    click(popup, 80, 260)
    pump_until(lambda: not root.popups)
    assert root.running and root.timer.isActive()


def test_multiple_popups_modality_navigation_and_shutdown(operational_studio):
    window = operational_studio
    configure(window); window.start_runtime()
    root = window.runtime_window
    first = root.open_popup('settings', modal=True)
    assert first.windowModality() == Qt.WindowModality.WindowModal
    assert root.open_popup('settings') is first
    assert first.windowModality() == Qt.WindowModality.NonModal
    second = first.open_popup('second')
    assert second.owner is root and second.runtime is first.runtime
    assert len(root.popups) == 2
    first.actuate(dict(action='screen', screen='main'))
    pump_until(lambda: first.document_name == 'main')
    assert root.document_name == 'main'
    assert root.open_popup('settings') is first and first.document_name == 'settings'
    events = []
    first.closed.connect(lambda: events.append('first'))
    second.closed.connect(lambda: events.append('second'))
    root.close()
    assert set(events) == {'first', 'second'}
    assert not root.running and not root.popups
    QApplication.processEvents()


def test_popup_action_editor_save_and_undo(operational_studio):
    window = operational_studio
    configure(window)
    window.scene.items()[0].setSelected(True)
    assert window.action_field.currentData() == 'popup'
    assert window.popup_modal.isVisible()
    window.popup_modal.setChecked(True)
    window.screen_field.setCurrentText('second'); window.apply_fields()
    element = window.project.screens['main']['elements'][0]
    assert element['screen'] == 'second' and element['modal'] is True
    window.undo()
    assert window.project.screens['main']['elements'][0]['screen'] == 'settings'
    window.redo(); window.save_project()
    assert Project.load(window.project.root).screens['main']['elements'][0]['modal'] is True
    window.scene.items()[0].setSelected(True)
    window.action_field.setCurrentIndex(window.action_field.findData('close_popup'))
    window.apply_fields()
    element = window.project.screens['main']['elements'][0]
    assert element['action'] == 'close_popup'
    assert 'screen' not in element and 'modal' not in element and 'tag' not in element


@pytest.mark.parametrize('changes', [{'screen': 'missing'}, {'modal': 'yes'}])
def test_invalid_popup_configuration_rejected(operational_studio, changes):
    configure(operational_studio)
    operational_studio.project.screens['main']['elements'][0].update(changes)
    with pytest.raises(ValueError):
        operational_studio.project.validate()


def test_close_action_on_main_is_harmless_and_pending_open_cancelled(operational_studio):
    configure(operational_studio); operational_studio.start_runtime()
    root = operational_studio.runtime_window
    root.actuate({'action': 'close_popup'})
    assert root.running
    root.actuate({'action': 'popup', 'screen': 'settings'})
    opened = []
    root.open_popup = lambda *args: opened.append(args)
    root.close(); QApplication.processEvents()
    assert not opened


def test_popup_writes_through_existing_s7_connection(studio):
    studio.project.screens['settings'] = {
        'width': 480, 'height': 320, 'elements': []}
    studio.start_runtime()
    root = studio.runtime_window
    pump_until(lambda: root.samples['Pump1.setpoint'].quality == 'good')
    popup = root.open_popup('settings')
    popup.actuate(dict(action='set', tag='Pump1.setpoint', value=37.5))
    pump_until(lambda: root.samples['Pump1.setpoint'].value == 37.5
               and popup.samples['Pump1.setpoint'].value == 37.5)
    popup.close()
    root.actuate(dict(action='set', tag='Pump1.setpoint', value=41.5))
    pump_until(lambda: root.samples['Pump1.setpoint'].value == 41.5)
