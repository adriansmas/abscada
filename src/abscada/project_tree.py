"""Studio project tree: screens in folders, faceplates and libraries (sections are in the side bar).

Right click for document and folder actions; drag screens and folders onto a folder to move them.
The rules themselves live in screen_tree (no Qt).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QInputDialog, QMenu, QMessageBox, QStyle, QTreeWidget, QTreeWidgetItem

from . import screen_tree
from .graphics import tool_icon
from .i18n import tr

ROLE = Qt.ItemDataRole.UserRole


class ProjectTree(QTreeWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.setHeaderHidden(True)
        self.setIndentation(12)
        self.setMinimumHeight(150)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda position: host.tree_menu(self.itemAt(position), self.viewport().mapToGlobal(position)))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F2:
            self.host.tree_rename(self.currentItem())
        else:
            super().keyPressEvent(event)

    def startDrag(self, actions):
        # A library object can also be dropped on the canvas: it carries its template name.
        item = self.currentItem()
        value = item.data(0, ROLE) if item else None
        if value and value[0] == "faceplates":
            from PySide6.QtCore import QMimeData
            from PySide6.QtGui import QDrag
            from .library_browser import TEMPLATE_MIME
            mime = QMimeData()
            mime.setData(TEMPLATE_MIME, value[1].encode("utf-8"))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(item.icon(0).pixmap(40, 40))
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)
            return
        super().startDrag(actions)

    def dragMoveEvent(self, event):
        from .library_browser import TEMPLATE_MIME
        if event.mimeData().hasFormat(TEMPLATE_MIME):
            event.acceptProposedAction()  # moving an object between library folders
        else:
            super().dragMoveEvent(event)

    def dragEnterEvent(self, event):
        from .library_browser import TEMPLATE_MIME
        if event.mimeData().hasFormat(TEMPLATE_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        # The project is rebuilt from data after the move, Qt must not move the items itself.
        source, target = self.currentItem(), self.itemAt(event.position().toPoint())
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if source is not None:
            self.host.tree_drop(source.data(0, ROLE), target.data(0, ROLE) if target else None)


def library_folder_of_target(project, value):
    """Library folder that receives a drop on ``value``; None outside the project's library."""
    if not value:
        return None
    if value[0] == "lfolder":
        return value[1]
    if value == ("group", "faceplates"):
        return ""
    if value[0] == "faceplates" and value[1] in project.faceplates:
        from .faceplate_libraries import owner
        return None if owner(project, value[1]) else project.faceplates[value[1]].get("folder", "")
    return None


def folder_of_target(project, value):
    """Folder that receives a drop on ``value`` (a folder, a screen or the «Pantallas» group)."""
    if not value:
        return None
    if value[0] == "folder":
        return value[1]
    if value == ("group", "screens"):
        return ""
    if value[0] == "screens":
        return project.screens[value[1]].get("folder", "")
    return None


class ProjectTreeActions:
    """Mixin for Studio's Window."""

    def populate_navigation(self):
        from .library_browser import fill
        tree = self.navigation
        collapsed = {item.data(0, ROLE) for item in self._tree_items() if not item.isExpanded()}
        # Read-only libraries are long: closed until the user opens them.
        opened = {item.data(0, ROLE) for item in self._tree_items() if item.isExpanded()}
        tree.blockSignals(True)
        tree.clear()
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        startup = self.project.manifest.get("startup_screen")

        def node(parent, text, value, icon=None, tip=""):
            item = QTreeWidgetItem([text])
            item.setData(0, ROLE, value)
            if icon is not None:
                item.setIcon(0, icon)
            if tip:
                item.setToolTip(0, tip)
            (parent.addChild if isinstance(parent, QTreeWidgetItem) else tree.addTopLevelItem)(item)
            if value == (self.document_kind, self.document_name):
                tree.setCurrentItem(item)
            return item

        screens = node(tree, tr("Pantallas"), ("group", "screens"))
        folders = {"": screens}
        for path in screen_tree.folders(self.project):
            folders[path] = node(folders[screen_tree.parent_folder(path)], path.rpartition("/")[2], ("folder", path), folder_icon)
        for name, document in self.project.screens.items():
            layout = screen_tree.is_layout(document)
            tip = tr("Pantalla con zonas para otras pantallas (layout)") if layout else ""
            if name == startup:
                tip = (tr("Pantalla de inicio del runtime. ") + tip).strip()
            item = node(folders[document.get("folder", "")], tr("{name}  ▶ inicio", name=name) if name == startup else name, ("screens", name),
                        tool_icon("screen_container" if layout else "image"), tip)
            if name == startup:
                font = QFont(item.font(0)); font.setBold(True); item.setFont(0, font)
        libraries = node(tree, tr("Librerías"), ("group", "libraries"),
                         tip=tr("Objetos reutilizables (símbolos y plantillas de equipo). Arrástralos al lienzo."))
        fill(self.project, libraries, node, folder_icon)
        for item in self._tree_items():
            value = item.data(0, ROLE)
            if value and value[0] in {"library", "libfolder"}:
                item.setExpanded(value in opened)
            else:
                item.setExpanded(value not in collapsed)
        tree.blockSignals(False)

    def _tree_items(self):
        stack = [self.navigation.topLevelItem(i) for i in range(self.navigation.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    # --- actions --------------------------------------------------------------------------------

    def tree_mutate(self, callback, document=None):
        """Change the project from the tree; ``document`` is the document to show afterwards."""
        previous = (self.document_kind, self.document_name)

        def run():
            callback()
            self.project.validate()
            if document:
                self.document_kind, self.document_name = document
            elif self.document_name not in getattr(self.project, self.document_kind):
                self.document_kind, self.document_name = "screens", self.project.manifest["startup_screen"]
        if self.mutate(run, selected_ids=[]):
            return True
        self.document_kind, self.document_name = previous
        return False

    def ask_text(self, title, label, text=""):
        value, ok = QInputDialog.getText(self, title, label, text=text)
        return value.strip() if ok and value.strip() else None

    def tree_menu(self, item, position):
        if not self.editable():
            return
        value = item.data(0, ROLE) if item else None
        menu = QMenu(self)
        kind = value[0] if value else None
        if value in (None, ("group", "screens")) or kind == "folder":
            folder = value[1] if kind == "folder" else ""
            menu.addAction(tr("Nueva pantalla…"), lambda: self.new_document(False, folder=folder))
            menu.addAction(tr("Nueva carpeta…"), lambda: self.tree_new_folder(folder))
            if kind == "folder":
                menu.addSeparator()
                menu.addAction(tr("Renombrar carpeta…"), lambda: self.tree_rename(item))
                menu.addAction(tr("Eliminar carpeta (su contenido sube un nivel)"), lambda: self.tree_mutate(lambda: screen_tree.delete_folder(self.project, folder)))
        elif value == ("group", "libraries"):
            from .library_editor import LibraryDialog
            menu.addAction(tr("Importar librería externa…"), lambda: LibraryDialog(self).exec())
            menu.addAction(tr("Nuevo objeto de librería…"), lambda: self.new_document(True))
        elif kind == "screens":
            name = value[1]
            menu.addAction(tr("Renombrar…"), lambda: self.tree_rename(item))
            menu.addAction(tr("Duplicar…"), lambda: self.tree_duplicate(name))
            move = menu.addMenu(tr("Mover a carpeta"))
            current = self.project.screens[name].get("folder", "")
            for path in [""] + screen_tree.folders(self.project):
                action = move.addAction(tr("(raíz de Pantallas)") if not path else "    " * path.count("/") + path.rpartition("/")[2],
                                        lambda p=path: self.tree_mutate(lambda: screen_tree.move_screen(self.project, name, p)))
                action.setEnabled(path != current)
            start = menu.addAction(tr("Usar como pantalla de inicio"), lambda: self.tree_mutate(lambda: self.project.manifest.__setitem__("startup_screen", name)))
            start.setEnabled(self.project.manifest.get("startup_screen") != name)
            menu.addSeparator()
            menu.addAction(tr("Eliminar…"), lambda: self.tree_delete_screen(name))
        elif value == ("group", "faceplates") or kind == "lfolder":
            folder = value[1] if kind == "lfolder" else ""
            menu.addAction(tr("Nuevo objeto de librería…"), lambda: self.new_document(True, folder=folder))
            menu.addAction(tr("Nueva carpeta…"), lambda: self.tree_new_folder(folder, "faceplates"))
            if kind == "lfolder":
                menu.addSeparator()
                menu.addAction(tr("Renombrar carpeta…"), lambda: self.tree_rename(item))
                menu.addAction(tr("Eliminar carpeta (su contenido sube un nivel)"),
                               lambda: self.tree_mutate(lambda: screen_tree.delete_folder(self.project, folder, "faceplates")))
        elif kind == "faceplates" and value[1] in self.project.faceplates:
            name = value[1]
            if self.document_kind == "screens":
                menu.addAction(tr("Insertar en la pantalla"), lambda: self.insert_library_object(name))
            if self.faceplate_is_linked(name):
                menu.addAction(tr("Copiar al proyecto para modificarlo…"), lambda: self.tree_duplicate_faceplate(name))
            else:
                menu.addAction(tr("Renombrar…"), lambda: self.tree_rename(item))
                menu.addAction(tr("Duplicar…"), lambda: self.tree_duplicate_faceplate(name))
                move = menu.addMenu(tr("Mover a carpeta"))
                current = self.project.faceplates[name].get("folder", "")
                for path in [""] + screen_tree.folders(self.project, "faceplates"):
                    action = move.addAction(tr("(raíz de Proyecto)") if not path else "    " * path.count("/") + path.rpartition("/")[2],
                                            lambda p=path: self.tree_mutate(lambda: screen_tree.move_faceplate(self.project, name, p)))
                    action.setEnabled(path != current)
                menu.addSeparator()
                menu.addAction(tr("Nuevo objeto de librería…"), lambda: self.new_document(True, folder=current))
                menu.addAction(tr("Eliminar…"), lambda: self.tree_delete_faceplate(name))
        if not menu.isEmpty():
            menu.exec(position)

    def tree_new_folder(self, parent, kind="screens"):
        name = self.ask_text(tr("Nueva carpeta"), tr("Nombre de la carpeta") + (tr(" dentro de «{parent}»", parent=parent) if parent else ""))
        if name:
            self.tree_mutate(lambda: screen_tree.add_folder(self.project, parent, name, kind))

    def tree_rename(self, item):
        value = item.data(0, ROLE) if item else None
        if not value or not self.editable():
            return
        if value[0] == "faceplates" and value[1] in self.project.faceplates and not self.faceplate_is_linked(value[1]):
            self.rename_faceplate_from_tree(value[1])
        elif value[0] in {"folder", "lfolder"}:
            kind = "screens" if value[0] == "folder" else "faceplates"
            name = self.ask_text(tr("Renombrar carpeta"), tr("Nuevo nombre"), value[1].rpartition("/")[2])
            if name:
                self.tree_mutate(lambda: screen_tree.rename_folder(self.project, value[1], name, kind))
        elif value[0] == "screens":
            old = value[1]
            new = self.ask_text(tr("Renombrar pantalla"), tr("Nuevo nombre de archivo (letras sin acentos, números, _ y -)"), old)
            if not new or new == old:
                return
            pending = []
            showing = self.document_name if self.document_kind == "screens" and self.document_name != old else new
            if self.tree_mutate(lambda: pending.extend(screen_tree.rename_screen(self.project, old, new)),
                                ("screens", showing) if self.document_kind == "screens" else None):
                if pending:
                    QMessageBox.information(self, tr("Pantalla renombrada"),
                                            tr("Los botones, contenedores y la configuración se han actualizado. Revisa estos scripts, que mencionan «{old}» como texto: {join}", old=old, join=', '.join(pending)))

    def faceplate_is_linked(self, name):
        from .faceplate_libraries import owner
        return bool(owner(self.project, name))

    def rename_faceplate_from_tree(self, old):
        new = self.ask_text(tr("Renombrar objeto de librería"), tr("Nuevo nombre (letras sin acentos, números, _ y -)"), old)
        if new and new != old:
            showing = ("faceplates", new) if (self.document_kind, self.document_name) == ("faceplates", old) else None
            self.tree_mutate(lambda: screen_tree.rename_faceplate(self.project, old, new), showing)

    def tree_duplicate_faceplate(self, name):
        linked = self.faceplate_is_linked(name)
        base = name.split("__", 1)[-1] if linked else name + "_copia"
        new = self.ask_text(tr("Copiar al proyecto") if linked else tr("Duplicar objeto de librería"), tr("Nombre de la copia"), base)
        if new:
            self.tree_mutate(lambda: screen_tree.duplicate_faceplate(self.project, name, new), ("faceplates", new))

    def tree_delete_faceplate(self, name):
        used = screen_tree.faceplate_references(self.project, name)
        if used:
            self.error(tr("No se puede eliminar «{name}» porque se usa en:\n· ", name=name) + "\n· ".join(used))
            return
        if QMessageBox.question(self, tr("Eliminar objeto de librería"), tr("¿Eliminar el objeto «{name}»? Se puede deshacer con Ctrl+Z.", name=name)) \
                == QMessageBox.StandardButton.Yes:
            self.tree_mutate(lambda: screen_tree.delete_faceplate(self.project, name))

    def tree_duplicate(self, name):
        new = self.ask_text(tr("Duplicar pantalla"), tr("Nombre de la copia"), name + "_copia")
        if new:
            self.tree_mutate(lambda: screen_tree.duplicate_screen(self.project, name, new), ("screens", new))

    def tree_delete_screen(self, name):
        used = screen_tree.screen_references(self.project, name)
        if used:
            self.error(tr("No se puede eliminar «{name}» porque se usa en:\n· ", name=name) + "\n· ".join(used))
            return
        mentioned = screen_tree.scripts_mentioning(self.project, name)
        extra = tr("\n\nAtención: estos scripts la mencionan: {join}", join=', '.join(mentioned)) if mentioned else ""
        if QMessageBox.question(self, tr("Eliminar pantalla"), tr("¿Eliminar la pantalla «{name}»? Se puede deshacer con Ctrl+Z.{extra}", name=name, extra=extra)) \
                == QMessageBox.StandardButton.Yes:
            self.tree_mutate(lambda: screen_tree.delete_screen(self.project, name))

    def tree_drop(self, source, target):
        if not self.editable() or not source:
            return
        if source[0] in {"lfolder", "faceplates"}:
            folder = library_folder_of_target(self.project, target)
            if folder is None:
                return
            if source[0] == "faceplates" and not self.faceplate_is_linked(source[1]) \
                    and self.project.faceplates[source[1]].get("folder", "") != folder:
                self.tree_mutate(lambda: screen_tree.move_faceplate(self.project, source[1], folder))
            elif source[0] == "lfolder" and screen_tree.parent_folder(source[1]) != folder:
                self.tree_mutate(lambda: screen_tree.move_folder(self.project, source[1], folder, "faceplates"))
            return
        folder = folder_of_target(self.project, target)
        if folder is None:
            return
        if source[0] == "screens" and self.project.screens[source[1]].get("folder", "") != folder:
            self.tree_mutate(lambda: screen_tree.move_screen(self.project, source[1], folder))
        elif source[0] == "folder" and screen_tree.parent_folder(source[1]) != folder:
            self.tree_mutate(lambda: screen_tree.move_folder(self.project, source[1], folder))
