"""Project file operations and advanced document editing for Studio."""
from pathlib import Path
import json
from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QDialogButtonBox, QMessageBox
from .project import Project
from .dialogs import EditorDialog as QDialog
from .i18n import tr


class ProjectActions:
    def new_document(self, faceplate, folder=""):
        if not self.editable():
            return
        from .project_dialogs import NewDocumentDialog
        dialog = NewDocumentDialog(self, faceplate)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name.text().strip()
        kind = 'faceplates' if faceplate else 'screens'
        document = dialog.document()
        if folder:
            document['folder'] = folder
        if self.tree_mutate(lambda: getattr(self.project, kind).__setitem__(name, document), (kind, name)):
            self.navigate(kind)

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
            data = self.json_dialog(tr("Documento gráfico / parámetros"), self.document())
            if data is not None:
                self.mutate(lambda: getattr(self.project, self.document_kind).__setitem__(self.document_name, data))
        except Exception as exc:
            self.error(exc)

    def edit_variables(self):
        if not self.editable():
            return
        try:
            data = self.json_dialog(tr("Definiciones de variables"), self.project.variables)
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
            self.statusBar().showMessage(tr("Proyecto guardado"), 5000)
            from .versioning import ProjectGit
            try:
                revision = ProjectGit(self.project).commit()
                if revision: self.statusBar().showMessage(tr("Proyecto guardado · versión ") + revision, 5000)
            except Exception as exc:
                self.error(tr("El proyecto está guardado, pero no se pudo crear la versión Git: ") + str(exc))
                return False
            return True
        except Exception as exc:
            self.error(exc)

    def maybe_save(self):
        if not self.dirty:
            return True
        choice = QMessageBox.question(self, tr("Cambios pendientes"), tr("¿Guardar los cambios del proyecto?"),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            self.save_project()
            return not self.dirty
        return True

    def replace_project(self, path):
        try:
            project = Project.load(path)
            if not self.stop_runtime():
                return
            from .start_dialog import remember_project
            remember_project(project.manifest_path)
            self.project = project
            from .project_languages import languages, default_language
            self.editing_language = default_language(project)
            self.editing_language_field.blockSignals(True)
            self.editing_language_field.clear()
            self.editing_language_field.addItems(languages(project))
            self.editing_language_field.setCurrentText(self.editing_language)
            self.editing_language_field.blockSignals(False)
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

    def open_project(self, path=None):
        if not self.maybe_save():
            return
        from .start_dialog import ask_open_project
        path = path or ask_open_project(self)
        if path:
            self.replace_project(path)

    def new_project(self):
        if not self.maybe_save():
            return
        from .start_dialog import ask_new_project
        try:
            path = ask_new_project(self)
        except Exception as exc:
            self.error(exc)
            return
        if path:
            self.replace_project(path)

    def reload_project(self):
        if self.maybe_save():
            self.replace_project(self.project.manifest_path)

    def fill_recent_menu(self, menu):
        from .start_dialog import recent_projects
        menu.clear()
        for path in recent_projects():
            menu.addAction(f"{Path(path).stem}  —  {Path(path).parent}", lambda p=path: self.open_project(p))
        if menu.isEmpty():
            menu.addAction(tr("Sin proyectos recientes")).setEnabled(False)
