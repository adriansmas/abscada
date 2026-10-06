"""Build the Windows beta: dist/abSCADA/abscada.exe and dist/abSCADA-<version>-windows.zip.

    .venv\\Scripts\\python -m pip install -e ".[s7,modbus]" pyinstaller
    .venv\\Scripts\\python packaging/build_exe.py
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_INFO = ROOT / "src" / "abscada" / "_build_info.py"


def version():
    text = (ROOT / "src" / "abscada" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def git_revision():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "sin git"


def windows_version_file(ver, folder):
    """VS_VERSIONINFO so Explorer shows product name and version."""
    numbers = [int(n) for n in re.findall(r"\d+", ver)[:3]] + [0]
    numbers = (numbers + [0, 0, 0, 0])[:4]
    tuple_text = ", ".join(map(str, numbers))
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tuple_text}), prodvers=({tuple_text}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040A04B0', [
      StringStruct('CompanyName', 'abSCADA'),
      StringStruct('FileDescription', 'abSCADA · SCADA de escritorio libre'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'abscada'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', 'abscada.exe'),
      StringStruct('ProductName', 'abSCADA'),
      StringStruct('ProductVersion', '{ver}')])]),
        VarFileInfo([VarStruct('Translation', [0x040A, 1200])])]
)"""
    path = Path(folder) / "version_info.txt"
    path.write_text(content, encoding="utf-8")
    return path


def main():
    ver = version()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    BUILD_INFO.write_text(f'BUILD = "{ver} · {stamp} · {git_revision()}"\n', encoding="utf-8")
    if not (ROOT / "packaging" / "abscada.ico").exists():
        subprocess.run([sys.executable, str(ROOT / "packaging" / "make_icon.py")], check=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, ABSCADA_VERSION_FILE=str(windows_version_file(ver, tmp)))
            subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                            "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"),
                            str(ROOT / "packaging" / "abscada.spec")], check=True, cwd=ROOT, env=env)
    finally:
        BUILD_INFO.unlink(missing_ok=True)
    folder = ROOT / "dist" / "abSCADA"
    shutil.copyfile(ROOT / "docs" / "BETA.md", folder / "LEEME-BETA.md")
    archive = shutil.make_archive(str(ROOT / "dist" / f"abSCADA-{ver}-windows"), "zip", folder.parent, folder.name)
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6
    print(f"Ejecutable: {folder / 'abscada.exe'} ({size:.0f} MB en la carpeta)\nZIP: {archive}")


if __name__ == "__main__":
    main()
