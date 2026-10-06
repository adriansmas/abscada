"""Beta packaging: .abscada project files, start screen helpers and .exe helper modes."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from abscada import app_paths, project_files
from abscada.project import Project
from abscada.project_storage import disk_state

ROOT = Path(__file__).resolve().parents[1]


def blank(root, manifest_file="Planta.abscada"):
    return Project(root, dict(schema_version=1, name="Planta", startup_screen="main"), {}, [], [],
                   {"main": dict(width=100, height=100, elements=[])}, {}, manifest_file=manifest_file)


def test_save_and_open_by_abscada_file_or_folder(tmp_path):
    project = blank(tmp_path / "Planta")
    project.save()
    assert (tmp_path / "Planta" / "Planta.abscada").is_file()
    assert not (tmp_path / "Planta" / "project.json").exists()
    for path in (tmp_path / "Planta" / "Planta.abscada", tmp_path / "Planta"):
        loaded = Project.load(path)
        assert loaded.manifest_file == "Planta.abscada" and loaded.manifest["name"] == "Planta"
    assert "Planta.abscada" in disk_state(tmp_path / "Planta")


def test_legacy_project_json_still_opens(tmp_path):
    blank(tmp_path / "old", "project.json").save()
    loaded = Project.load(tmp_path / "old")
    assert loaded.manifest_file == "project.json"
    loaded.save()
    assert (tmp_path / "old" / "project.json").exists() and not list((tmp_path / "old").glob("*.abscada"))


def test_external_edit_of_abscada_file_is_detected(tmp_path):
    blank(tmp_path / "p").save()
    loaded = Project.load(tmp_path / "p")
    manifest = tmp_path / "p" / "Planta.abscada"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("Planta", "Otra", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="fuera de Studio"):
        loaded.save()


def test_locate_errors(tmp_path):
    with pytest.raises(ValueError, match="ningún proyecto"):
        project_files.locate(tmp_path)
    (tmp_path / "a.abscada").write_text("{}")
    (tmp_path / "b.abscada").write_text("{}")
    with pytest.raises(ValueError, match="varios proyectos"):
        project_files.locate(tmp_path)
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(ValueError, match="no es un proyecto"):
        project_files.locate(tmp_path / "notes.txt")


def test_new_project_location(tmp_path):
    assert project_files.new_project_location(tmp_path / "Depuradora.abscada") == (tmp_path / "Depuradora", "Depuradora.abscada")
    assert project_files.new_project_location(tmp_path / "Sin extension")[1] == "Sin extension.abscada"
    (tmp_path / "Ocupada").mkdir()
    (tmp_path / "Ocupada" / "x.txt").write_text("x")
    with pytest.raises(ValueError, match="no está vacía"):
        project_files.new_project_location(tmp_path / "Ocupada.abscada")
    with pytest.raises(ValueError):
        project_files.safe_stem("CON")
    assert project_files.safe_stem('a:b*c') == "a_b_c"


@pytest.mark.parametrize("example", ["hydro", "beckhoff", "showcase", "plant", "library_author", "demo", "s7"])
def test_every_shipped_example_has_an_abscada_file(example):
    root, manifest = project_files.locate(ROOT / "examples" / example)
    assert manifest.endswith(".abscada")


def test_child_commands_for_source_and_frozen(monkeypatch):
    assert app_paths.script_runner_command()[-1].endswith("script_runner.py")
    assert app_paths.simulator_command("hydro")[1:] == ["-m", "abscada", "--simulador", "hydro"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\abSCADA\abscada.exe")
    assert app_paths.script_runner_command() == [r"C:\abSCADA\abscada.exe", "--script-runner"]
    assert app_paths.simulator_command("ads") == [r"C:\abSCADA\abscada.exe", "--simulador", "ads"]


def test_script_runner_mode_of_the_entry_point():
    request = dict(source="ctx.write('A', ctx.read('B') + 1)\nprint('hola')", filename="scripts/t.py", event="startup",
                   samples={"B": dict(value=41, quality="good")})
    result = subprocess.run([sys.executable, "-m", "abscada", "--script-runner"], input=json.dumps(request),
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    answer = json.loads(result.stdout)
    assert answer["ok"] and answer["actions"] == [["A", 42]] and "hola" in answer["output"]


def test_simulator_mode_serves_s7():
    snap7 = pytest.importorskip("snap7")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "abscada", "--simulador", "s7", "--port", str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        client = snap7.Client()
        for _ in range(50):
            try:
                client.connect("127.0.0.1", 0, 1, port)
                break
            except Exception:
                time.sleep(0.1)
        assert client.get_connected()
        assert len(client.db_read(1, 0, 4)) == 4
        client.disconnect()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_simulator_output_to_a_file_accepts_non_cp1252_text(tmp_path):
    # In the .exe the simulator log is a file with the Windows codepage; «→» crashed the hydro simulator.
    code = ("import types, abscada.simulators as s, abscada.__main__ as m\n"
            "s.SIMULATORS['hydro'] = types.SimpleNamespace(run=lambda argv: print('127.0.0.1 → 502', flush=True))\n"
            "m.main(['--simulador', 'hydro'])\n")
    log = tmp_path / "simulador.log"
    with log.open("wb") as output:
        result = subprocess.run([sys.executable, "-c", code], stdout=output, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}, timeout=30)
    assert result.returncode == 0, log.read_text(errors="replace")
    assert "→ 502" in log.read_text(encoding="utf-8")


def test_unknown_simulator_is_rejected():
    from abscada import simulator_manager
    with pytest.raises(ValueError, match="desconocido"):
        simulator_manager.start("nope")
    result = subprocess.run([sys.executable, "-m", "abscada", "--simulador", "nope"], capture_output=True, text=True)
    assert result.returncode != 0 and "Uso" in result.stderr


def test_examples_are_copied_to_documents_once(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from abscada import start_dialog
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(start_dialog, "documents_root", lambda: tmp_path / "Docs")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(start_dialog, "_settings", lambda: settings)
    path = start_dialog.example_copy("beckhoff")
    assert path == tmp_path / "Docs" / "Ejemplos" / "beckhoff" / "banco_beckhoff.abscada"
    assert not (path.parent / "runtime").exists()
    path.with_name("marca.txt").write_text("cambio del usuario")
    assert start_dialog.example_copy("beckhoff") == path and path.with_name("marca.txt").exists()
    start_dialog.remember_project(path)
    start_dialog.remember_project(tmp_path / "missing.abscada")
    assert start_dialog.recent_projects() == [str(path.resolve())]
