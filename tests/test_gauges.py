"""Analog indicator (gauge): geometry, validation, faceplate use and rendering."""
import os

import pytest
from abscada import gauges
from abscada.project import Project


def make_project(tmp_path, element, faceplate=False):
    variables = [dict(name="P", type="float", initial=42.0, writable=False),
                 dict(name="Txt", type="string", initial="", writable=False)]
    project = Project(tmp_path / "g", dict(schema_version=1, name="G", startup_screen="main"), {}, variables, [], {}, {})
    if faceplate:
        project.faceplates["fp"] = dict(width=200, height=200, parameters={"v": "float"}, elements=[dict(element, tag="$v")])
        element = dict(id="inst", kind="faceplate", x=0, y=0, w=200, h=200, template="fp", bindings={"v": "P"})
    project.screens["main"] = dict(width=400, height=400, elements=[element])
    return project


def gauge(**extra):
    return dict(dict(id="g", kind="gauge", x=10, y=10, w=200, h=200, tag="P", min=0, max=100), **extra)


def test_nice_ticks():
    assert gauges.ticks(0, 100) == ([0, 20, 40, 60, 80, 100], 20)
    assert gauges.ticks(0, 800)[1] == 200
    assert gauges.ticks(-20, 20)[0] == [-20, -10, 0, 10, 20]
    assert gauges.nice_step(1) == 0.2


def test_angles_and_fraction():
    assert gauges.angle("dial", 0) == 210 and gauges.angle("dial", 1) == -30
    assert gauges.angle("semi", 0) == 180 and gauges.angle("semi", 1) == 0
    assert gauges.fraction(150, 0, 100) == 1 and gauges.fraction(None, 0, 100) == 0


@pytest.mark.parametrize("extra, message", [
    (dict(gauge_style="speedometer"), "Estilo"),
    (dict(min=10, max=10), "máximo"),
    (dict(warning=80, alarm=70), "alarma"),
    (dict(warning="80"), "número"),
    (dict(decimals=12), "decimals"),
])
def test_invalid_gauges_are_rejected(tmp_path, extra, message):
    with pytest.raises(ValueError, match=message):
        make_project(tmp_path, gauge(**extra)).validate()


def test_gauge_needs_a_numeric_tag(tmp_path):
    with pytest.raises(ValueError, match="numérica"):
        make_project(tmp_path, gauge(tag="Txt")).validate()


@pytest.mark.parametrize("style", sorted(gauges.STYLES))
def test_valid_gauge_round_trips_and_works_in_faceplates(tmp_path, style):
    element = gauge(gauge_style=style, unit="bar", decimals=1, text="Presión", warning=70, alarm=85,
                    dynamics=dict(states=[dict(when=dict(tag="P", op="gt", value=90.0), style=dict(color="#ff0000"))]))
    project = make_project(tmp_path, element)
    project.validate()
    project.save()
    assert Project.load(project.root).screens["main"]["elements"][0]["gauge_style"] == style
    make_project(tmp_path / "fp", gauge(gauge_style=style), faceplate=True).validate()


def test_gauges_render_in_runtime(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from abscada.runtime_window import RuntimeWindow
    app = QApplication.instance() or QApplication([])
    project = make_project(tmp_path, gauge())
    for i, style in enumerate(sorted(gauges.STYLES)):
        project.screens["main"]["elements"].append(gauge(id=f"s{i}", x=10 + i * 120, gauge_style=style, warning=60, alarm=80))
    project.validate()
    project.save()
    window = RuntimeWindow(Project.load(project.root))
    window.resize(500, 450)
    window.show()
    app.processEvents()
    image = window.grab().toImage()
    window.close()
    assert not image.isNull() and image.width() > 0
