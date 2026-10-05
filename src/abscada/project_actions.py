"""Project file operations and advanced document editing for Studio."""
from pathlib import Path
import json
from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QDialogButtonBox, QInputDialog, QMessageBox, QFileDialog
from .project import Project
from .dialogs import EditorDialog as QDialog


class ProjectActions:
    def new_document(self, faceplate, layout=False):
        if not self.editable():
            return
        from .project_dialogs import NewDocumentDialog
        dialog = NewDocumentDialog(self, faceplate, layout)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name.text().strip()
        kind = 'faceplates' if faceplate else 'screens'
        document = dialog.document()
        if self.mutate(lambda: getattr(self.project, kind).__setitem__(name, document)):
            self.document_kind, self.document_name = kind, name
            self.navigate(kind)
            self.populate_navigation()
            self.render_scene()

    def json_dialog(self, title, data):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(json.dumps(data, indent=2, ensure_ascii=False))
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return json.loads(editor.toPlainText())
        return None

    def edit_graphic_document(self):
        if not self.editable():
            return
        try:
            data = self.json_dialog("Documento gráfico / parámetros", self.document())
            if data is not None:
                self.mutate(lambda: getattr(self.project, self.document_kind).__setitem__(self.document_name, data))
        except Exception as exc:
            self.error(exc)

    def edit_variables(self):
        if not self.editable():
            return
        try:
            data = self.json_dialog("Definiciones de variables", self.project.variables)
            if data is not None:
                self.mutate(lambda: setattr(self.project, "variables", data))
        except Exception as exc:
            self.error(exc)

    def save_project(self):
        try:
            if hasattr(self, 'automation_editor'): self.automation_editor.end_edit_group()
            focus = self.focusWidget()
            if focus: focus.clearFocus()
            self.project.save()
            self.dirty = False
            self.setWindowTitle("abSCADA Studio · " + self.project.manifest["name"])
            self.statusBar().showMessage("Proyecto guardado", 5000)
            from .versioning import ProjectGit
            try:
                revision = ProjectGit(self.project).commit()
                if revision: self.statusBar().showMessage("Proyecto guardado · versión " + revision, 5000)
            except Exception as exc:
                self.error("El proyecto está guardado, pero no se pudo crear la versión Git: " + str(exc))
                return False
            return True
        except Exception as exc:
            self.error(exc)

    def maybe_save(self):
        if not self.dirty:
            return True
        choice = QMessageBox.question(self, "Cambios pendientes", "¿Guardar los cambios del proyecto?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            self.save_project()
            return not self.dirty
        return True

    def replace_project(self, root):
        try:
            project = Project.load(root)
            if not self.stop_runtime():
                return
            self.project = project
            self.document_kind, self.document_name = "screens", project.manifest["startup_screen"]
            self.dirty = False
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.update_history_actions()
            self.refresh_catalogs()
            self.project_label.setText(project.manifest["name"])
            self.populate_navigation()
            self.refresh_variables()
            self.render_scene()
            self.setWindowTitle("abSCADA Studio · " + project.manifest["name"])
        except Exception as exc:
            self.error(exc)

    def open_project(self):
        if not self.maybe_save():
            return
        root = QFileDialog.getExistingDirectory(self, "Carpeta del proyecto")
        if root:
            self.replace_project(root)

    def new_project(self):
        if not self.maybe_save():
            return
        root = QFileDialog.getExistingDirectory(self, "Elige una carpeta vacía para el nuevo proyecto")
        if not root:
            return
        if any(Path(root).iterdir()):
            self.error("Elige una carpeta vacía para evitar sobrescribir archivos")
            return
        name, ok = QInputDialog.getText(self, "Nuevo proyecto", "Nombre", text="Mi SCADA")
        if not ok or not name.strip():
            return
        project = Project(Path(root), dict(schema_version=1, name=name.strip(), startup_screen="main"),
                          {}, [], [], {"main": dict(width=1000, height=650, elements=[])}, {})
        try:
            project.save()
            self.replace_project(root)
        except Exception as exc:
            self.error(exc)

    def reload_project(self):
        if self.maybe_save():
            self.replace_project(self.project.root)
