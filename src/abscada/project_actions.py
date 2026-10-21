"""Project file operations and advanced document editing for Studio."""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout, QPlainTextEdit, QDialogButtonBox, QMessageBox
from .project import Project
from .dialogs import EditorDialog
from .i18n import tr

# Git versions are created one after another, outside the interface thread.
VERSIONS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="abscada-git")


class ProjectActions:
    def new_document(self, faceplate, folder=""):
        if not self.editable():
            return
        from .project_dialogs import NewDocumentDialog
        dialog = NewDocumentDialog(self, faceplate)
        if dialog.exec() != EditorDialog.DialogCode.Accepted:
            return
        name = dialog.name.text().strip()
        kind = 'faceplates' if faceplate else 'screens'
        document = dialog.document()
        if folder:
            document['folder'] = folder
        if self.tree_mutate(lambda: getattr(self.project, kind).__setitem__(name, document), (kind, name)):
            self.navigate(kind)

    def json_dialog(self, title, data):
        dialog = EditorDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(json.dumps(data, indent=2, ensure_ascii=False))
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == EditorDialog.DialogCode.Accepted:
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
            if hasattr(self, 'flush_nudge'): self.flush_nudge()
            focus = self.focusWidget()
            if focus: focus.clearFocus()
            self.project.save()
            self.mark_saved()
            self.statusBar().showMessage(tr("Proyecto guardado"), 5000)
            self.commit_version()
            return True
        except Exception as exc:
            self.error(exc)

    def commit_version(self):
        """The Git version of the saved files, in the background: git takes most of a second."""
        from .versioning import ProjectGit
        git = ProjectGit(self.project)
        if not git.enabled():
            return
        self.wait_for_version()
        git.paths = git.project_paths()   # read now, on this thread, from the project just saved
        self._version_future = VERSIONS.submit(git.commit)
        self._version_timer = QTimer(self)
        self._version_timer.timeout.connect(self.check_version)
        self._version_timer.start(100)

    def check_version(self, wait=False):
        future = getattr(self, "_version_future", None)
        if future is None or (not wait and not future.done()):
            return
        self._version_future = None
        self._version_timer.stop()
        try:
            revision = future.result(timeout=60)
            if revision: self.statusBar().showMessage(tr("Proyecto guardado · versión ") + revision, 5000)
        except Exception as exc:
            self.error(tr("El proyecto está guardado, pero no se pudo crear la versión Git: ") + str(exc))

    def wait_for_version(self):
        """Before closing or saving again: an interrupted git commit leaves the repository locked."""
        self.check_version(wait=True)

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
            from .project_languages import default_language
            self.editing_language = default_language(project)
            self.fill_language_field()
            self.document_kind, self.document_name = "screens", project.manifest["startup_screen"]
            self.dirty = False
            self.saved_project = copy.deepcopy(project)
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
