"""Files written by abSCADA and its generators use LF, as .gitattributes stores them, also on Windows."""
from pathlib import Path
from abscada.project import Project
from abscada.faceplate_libraries import export_library
from test_hydro import tool

ROOT = Path(__file__).resolve().parents[1]


def crlf_files(root):
    return [p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and b"\r\n" in p.read_bytes()]


def test_saved_projects_generated_examples_and_libraries_use_lf(tmp_path):
    project = Project.load(ROOT / "examples/showcase")
    project.root = tmp_path / "saved"
    project.save()
    export_library(project, ["unidad"], tmp_path / "library.json", "Equipos", "1.0.0")
    tool("build_hydro").build_project(tmp_path / "hydro")
    assert crlf_files(tmp_path) == []
