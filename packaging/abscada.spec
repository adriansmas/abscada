# PyInstaller spec for abSCADA (one-folder build). Run through packaging/build_exe.py.
# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
VERSION_FILE = os.environ.get("ABSCADA_VERSION_FILE")


def example_datas():
    """Ship examples without runtime data (SQLite archives, locks) or caches."""
    pairs = []
    for path in (ROOT / "examples").rglob("*"):
        parts = path.relative_to(ROOT).parts
        if path.is_file() and "runtime" not in parts and "__pycache__" not in parts:
            pairs.append((str(path), str(Path(*parts[:-1]))))
    return pairs


a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=example_datas() + [
        # Standard library: SVG symbols and catalogue, read at run time from the package folder.
        (str(ROOT / "src" / "abscada" / "standard_library"), "abscada/standard_library"),
        (str(ROOT / "packaging" / "abscada.ico"), "packaging"),
        (str(ROOT / "docs" / "BETA.md"), "docs"),
        (str(ROOT / "LICENSE"), "."),
    ],
    # Simulators, protocol adapters and Qt modules are imported lazily by name.
    hiddenimports=collect_submodules("abscada") + collect_submodules("snap7") + collect_submodules("pyModbusTCP")
    + collect_submodules("asyncua") + ["PySide6.QtSvg", "PySide6.QtCharts"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="abscada",
    icon=str(ROOT / "packaging" / "abscada.ico"),
    version=VERSION_FILE,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="abSCADA", upx=False)
