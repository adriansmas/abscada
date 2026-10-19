"""The variable dialog shows one binding form, not the one it replaced while being prepared."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shutil
from pathlib import Path
from PySide6.QtWidgets import QApplication, QDialog, QLabel
from abscada import dialogs
from abscada.project import Project

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo"


def test_variable_dialog_shows_each_binding_field_once(tmp_path, monkeypatch):
    from abscada.ui import Window
    app = QApplication.instance() or QApplication([])
    shutil.copytree(DEMO, tmp_path / "demo", ignore=shutil.ignore_patterns("runtime"))
    window = Window(Project.load(tmp_path / "demo"))
    seen = []

    def inspect(dialog):
        dialog.show()
        app.processEvents()
        seen.extend(label.text() for label in dialog.findChildren(QLabel) if label.isVisible())
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(dialogs.EditorDialog, "exec", inspect)
    try:
        window.variable_form(next(i for i, v in enumerate(window.project.variables) if v.get("binding")))
    finally:
        window.dirty = False
        window.close()
    assert "DB" in seen
    assert [text for text in seen if seen.count(text) > 1] == []
