"""Test-only PLC server. Application transport is always real S7 TCP."""
import os
import socket
from pathlib import Path
import pytest

# Messages are asserted in Spanish, the source language, whatever the developer's own setting.
os.environ["ABSCADA_LANG"] = "es"
from abscada.project import Project
from plc_simulators.s7 import create_server


@pytest.fixture(scope='session',autouse=True)
def isolated_studio_preferences(tmp_path_factory):
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path_factory.mktemp('qt-preferences')))


@pytest.fixture
def plc_project():
    pytest.importorskip("snap7")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server, memory = create_server(port)
    project = Project.load(Path(__file__).resolve().parents[1] / "examples/demo")
    project.connections[0]["port"] = port
    try:
        yield project
    finally:
        server.stop()
        server.destroy()
