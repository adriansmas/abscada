# PyInstaller spec for abSCADA (one-folder build). Run through packaging/build_exe.py.
# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
VERSION_FILE = os.environ.get("ABSCADA_VERSION_FILE")
# The PLC simulators live in tools/ but travel inside the .exe (abscada --simulador).
sys.path.insert(0, str(ROOT / "tools"))


def example_datas():
    """Ship examples without runtime data (SQLite archives, locks), certificates or caches."""
    pairs = []
    for path in (ROOT / "examples").rglob("*"):
        parts = path.relative_to(ROOT).parts
        if path.is_file() and not {"runtime", "pki", "__pycache__"} & set(parts):
            pairs.append((str(path), str(Path(*parts[:-1]))))
    return pairs


a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src"), str(ROOT / "tools")],
    datas=example_datas() + [
        # Standard library: SVG symbols and catalogue, read at run time from the package folder.
        (str(ROOT / "src" / "abscada" / "standard_library"), "abscada/standard_library"),
        # Application translations (Ayuda → Idioma), read at run time from the package folder.
        (str(ROOT / "src" / "abscada" / "locales"), "abscada/locales"),
        (str(ROOT / "packaging" / "abscada.ico"), "packaging"),
        (str(ROOT / "docs" / "BETA.md"), "docs"),
        (str(ROOT / "LICENSE"), "."),
    ],
    # Simulators, protocol adapters and Qt modules are imported lazily by name.
    hiddenimports=collect_submodules("abscada") + collect_submodules("plc_simulators") + collect_submodules("snap7") + collect_submodules("pyModbusTCP")
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
