"""Runtime scaling: the page fills the window and full screen gives it the whole monitor."""
import os

import pytest
from PySide6.QtCore import Qt
from abscada.project import Project


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def runtime_window(tmp_path, scale="fit", width=1600, height=900):
    from abscada.runtime_window import RuntimeWindow
    manifest = dict(schema_version=1, name="S", startup_screen="main", display=dict(main=dict(scale=scale)))
    project = Project(tmp_path / "s", manifest, {}, [], [], {}, {})
    project.screens["main"] = dict(width=width, height=height, background="#e9edf3", elements=[
        dict(id="title", kind="text", x=0, y=0, w=width, h=60, text="Planta")])
    return RuntimeWindow(project)


def page_on_viewport(window):
    view = window.view
    return view.mapFromScene(view.sceneRect()).boundingRect()


@pytest.mark.parametrize("size", [(1200, 675), (1000, 800), (1500, 600)])
def test_fit_touches_two_edges_without_margin_or_scroll_bars(app, tmp_path, size):
    window = runtime_window(tmp_path)
    window.resize(*size); window.show(); app.processEvents()
    viewport = window.view.viewport().rect()
    page = page_on_viewport(window)
    t = window.view.transform()
    assert t.m11() == pytest.approx(t.m22())
    # No 2 px frame: the page reaches the window edges along the limiting direction.
    assert abs(page.width() - viewport.width()) <= 1 or abs(page.height() - viewport.height()) <= 1
    assert abs(page.center().x() - viewport.center().x()) <= 1 and abs(page.center().y() - viewport.center().y()) <= 1
    assert not window.view.horizontalScrollBar().isVisible() and not window.view.verticalScrollBar().isVisible()
    window.close()


def test_stretch_fills_the_whole_viewport(app, tmp_path):
    window = runtime_window(tmp_path, "stretch")
    window.resize(1000, 800); window.show(); app.processEvents()
    viewport = window.view.viewport().rect()
    page = page_on_viewport(window)
    assert abs(page.width() - viewport.width()) <= 1 and abs(page.height() - viewport.height()) <= 1
    window.close()


def test_actual_size_keeps_scroll_bars(app, tmp_path):
    window = runtime_window(tmp_path, "none")
    window.resize(800, 600); window.show(); app.processEvents()
    assert window.view.transform().isIdentity()
    assert window.view.horizontalScrollBar().isVisible()
    window.close()


def test_letterbox_is_dark_not_white(app, tmp_path):
    from abscada.runtime_window import LETTERBOX
    window = runtime_window(tmp_path)
    window.resize(1400, 600); window.show(); app.processEvents()
    image = window.view.viewport().grab().toImage()
    assert image.pixelColor(2, image.height() // 2).name() == LETTERBOX
    assert image.pixelColor(image.width() // 2, image.height() - 2).name() == "#e9edf3"
    window.close()


def test_full_screen_hides_status_bar_and_floats_messages(app, tmp_path):
    window = runtime_window(tmp_path)
    window.show(); app.processEvents()
    assert not window.statusBar().isHidden()
    window.setWindowState(Qt.WindowState.WindowFullScreen); app.processEvents()
    assert window.statusBar().isHidden()
    window.statusBar().showMessage("Conexión perdida", 5000); app.processEvents()
    assert window.notice.isVisible() and window.notice.text() == "Conexión perdida"
    assert window.notice.geometry().bottom() < window.view.height()
    window.statusBar().clearMessage(); app.processEvents()
    assert not window.notice.isVisible()
    window.statusBar().showMessage("Otra", 5000)
    window.setWindowState(Qt.WindowState.WindowNoState); app.processEvents()
    assert not window.statusBar().isHidden() and not window.notice.isVisible()
    window.close()


def test_full_screen_keeps_session_controls(app, tmp_path):
    window = runtime_window(tmp_path)
    window.session_label = object()  # a project with users shows its login controls here
    window.setWindowState(Qt.WindowState.WindowFullScreen); window.show(); app.processEvents()
    assert not window.statusBar().isHidden()
    window.session_label = None
    window.close()
