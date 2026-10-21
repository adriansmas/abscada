"""Performance regressions found in the October 2026 review, with generous limits.

Where possible the check counts work (rebuilt views, repainted items) instead of
measuring time, so a slow CI machine does not make it fail.
"""
import copy
import os
import shutil
import time
from pathlib import Path
import pytest
from abscada.project import Project

ROOT = Path(__file__).resolve().parents[1]


def big_project(n):
    project = Project.load(ROOT / "examples" / "hydro")
    project.types["BigT"] = {f"f{i}": "float" for i in range(10)}
    project.variables.append(dict(name="Big", type=f"BigT[{n}]", writable=True,
                                  initial=[{f"f{i}": 0.0 for i in range(10)} for _ in range(n)]))
    return project


def test_tags_and_validation_stay_linear_with_big_arrays():
    project = big_project(1000)
    started = time.perf_counter()
    assert len(project.tags()) > 10000
    project.validate()
    # 37 s before the review; well under a second now.
    assert time.perf_counter() - started < 5


@pytest.fixture
def studio(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from abscada.ui import Window
    shutil.copytree(ROOT / "examples/hydro", tmp_path / "hydro", ignore=shutil.ignore_patterns("runtime"))
    window = Window(Project.load(tmp_path / "hydro"))
    yield window
    window.dirty = False
    window.close()


def test_moving_an_element_rebuilds_only_the_canvas(studio, monkeypatch):
    studio.document_kind, studio.document_name = "screens", "30_grupo1"
    studio.render_scene()
    rebuilt = []
    for view in ("refresh_variables", "refresh_catalogs", "populate_navigation"):
        monkeypatch.setattr(studio, view, lambda *a, view=view, **k: rebuilt.append(view))
    validated = []
    monkeypatch.setattr(studio.project, "validate", lambda: validated.append("full"))
    element = studio.document()["elements"][0]
    studio.mutate(lambda: element.update(x=element["x"] + 1))
    assert rebuilt == [] and validated == []   # the open screen alone is checked


def test_variable_list_creates_widgets_only_for_the_current_row(studio):
    from PySide6.QtWidgets import QComboBox, QPushButton
    studio.navigate("variables")
    studio.refresh_variables()
    widgets = studio.table.viewport().findChildren(QComboBox) + studio.table.viewport().findChildren(QPushButton)
    # The widgets of one row at most, not three for each of the 173 variables.
    assert len(widgets) <= 3 < len(studio.project.tags())
