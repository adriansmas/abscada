"""Render every example screen without acquisition or edits to the shipped project."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from abscada.project import Project
from abscada.runtime_window import RuntimeWindow


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / 'artifacts' / 'showcase'
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    project = Project.load(root / 'examples/showcase')
    window = RuntimeWindow(project)
    window.resize(1360, 850)
    window.show()
    app.processEvents()
    for name, document in project.screens.items():
        if name in ('01_cabecera', '02_menu'):
            continue
        window.select_screen('00_layout')
        if name.startswith(('1','2','3','4','5','6')):
            window.containers['contenido'].select_screen(name)
        elif name != '00_layout':
            window.select_screen(name)
        app.processEvents()
        window.grab().save(str(out / (name + '.png')))
    window.close()
    print(out)


if __name__ == '__main__':
    main()
