"""«Librerías» in Studio: the project's objects (editable, in folders), the standard library and
linked libraries (read-only). Shared by the project tree and the object picker.

Internally a library object is still a faceplate template (``faceplates/<name>.json``, element
kind ``faceplate``): only the user-facing name changed, so existing projects keep working.
"""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QStyle, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)
from .i18n import tr

ROLE = Qt.ItemDataRole.UserRole
TEMPLATE_MIME = "application/x-abscada-template"
_ICONS = {}


def sections(project):
    """[(title, value, tooltip, [(folder, name, label), …]), …] — pure data, sorted for display."""
    from . import screen_tree
    from .faceplate_libraries import owner
    from .system_library import SYSTEM, _templates
    local = [(doc.get("folder", ""), name, name) for name, doc in project.faceplates.items() if not owner(project, name)]
    result = [(tr("Proyecto"), ("group", "faceplates"),
               tr("Objetos de este proyecto: se editan y se ordenan en carpetas (clic derecho)"), local)]
    standard = [(doc.get("folder", ""), name, doc.get("title", name)) for name, doc in _templates().items()]
    result.append((tr("Estándar (sistema)"), ("library", SYSTEM),
                   tr("Librería del sistema, de solo lectura. Arrastra un objeto al lienzo para usarlo; "
                   "«Copiar al proyecto» para modificarlo."), standard))
    for alias, entry in project.libraries.items():
        from .faceplate_libraries import expected_faces
        items = [("", name, name.removeprefix(alias + "__")) for name in expected_faces(alias, entry["package"])]
        result.append((f"{alias} · {entry['package']['version']}", ("library", alias), tr("Librería vinculada · solo lectura"), items))
    for _, _, _, items in result:
        items.sort(key=lambda item: (item[0].casefold(), item[2].casefold()))
    return result


def template_icon(project, name):
    """Preview of an object: its SVG symbol when it has one."""
    from .graphics import svg_renderer, tool_icon
    document = project.faceplates.get(name) or {}
    image = next((e for e in document.get("elements", []) if e.get("kind") == "image" and e.get("source")), None)
    if image is None:
        return tool_icon("faceplate")
    try:
        path = project.asset(image["source"])
    except ValueError:
        return tool_icon("faceplate")
    if path not in _ICONS:
        renderer = svg_renderer(path) if path.suffix.lower() == ".svg" else None
        pixmap = QPixmap(40, 40); pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if renderer is not None:
            size = renderer.defaultSize()
            scale = min(36 / max(1, size.width()), 36 / max(1, size.height()))
            w, h = size.width() * scale, size.height() * scale
            renderer.render(painter, QRectF((40 - w) / 2, (40 - h) / 2, w, h))
        else:
            source = QPixmap(str(path))
            if not source.isNull():
                painter.drawPixmap(2, 2, source.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
        painter.end()
        _ICONS[path] = QIcon(pixmap)
    return _ICONS[path]


def fill(project, parent, add, folder_icon, include_empty_folders=True):
    """Add the library tree under ``parent`` with ``add(parent, text, value, icon, tooltip)``."""
    from . import screen_tree
    nodes = []
    for title, value, tip, items in sections(project):
        section = add(parent, title, value, None, tip)
        nodes.append(section)
        folders = {"": section}
        paths = screen_tree.folders(project, "faceplates") if value == ("group", "faceplates") and include_empty_folders else []
        paths = sorted(set(paths) | {"/".join(f.split("/")[:i]) for f, _, _ in items if f for i in range(1, len(f.split("/")) + 1)},
                       key=str.casefold)
        for path in paths:
            folder_value = ("lfolder", path) if value == ("group", "faceplates") else ("libfolder", value[1], path)
            folders[path] = add(folders[screen_tree.parent_folder(path)], path.rpartition("/")[2], folder_value, folder_icon, "")
        for folder, name, label in items:
            tip = tr("Arrastra al lienzo para añadirlo a la pantalla") + ("" if value == ("group", "faceplates") else " · solo lectura")
            add(folders.get(folder, section), label, ("faceplates", name), template_icon(project, name), tip)
    return nodes


class LibraryPicker(QDialog):
    """Choose a library object to insert (toolbox «Objeto de librería»)."""

    def __init__(self, parent, project):
        super().__init__(parent)
        self.setWindowTitle(tr("Insertar objeto de librería"))
        self.resize(460, 560)
        layout = QVBoxLayout(self)
        self.filter = QLineEdit(); self.filter.setPlaceholderText(tr("Buscar: válvula, depósito, motor…"))
        self.filter.setObjectName("library_filter")
        layout.addWidget(self.filter)
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.setIconSize(QSize(28, 28))
        self.tree.setObjectName("library_picker")
        layout.addWidget(self.tree, 1)
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

        def add(parent_item, text, value, icon, tip):
            item = QTreeWidgetItem([text]); item.setData(0, ROLE, value)
            if icon is not None:
                item.setIcon(0, icon)
            if tip:
                item.setToolTip(0, tip)
            (parent_item.addChild if isinstance(parent_item, QTreeWidgetItem) else self.tree.addTopLevelItem)(item)
            return item
        fill(project, self.tree, add, folder_icon, include_empty_folders=False)
        self.tree.expandToDepth(1)
        self.tree.itemDoubleClicked.connect(lambda item, _: self.accept() if self.selected() else None)
        self.filter.textChanged.connect(self.apply_filter)
        layout.addWidget(QLabel(tr("Doble clic para insertar. También puedes arrastrar objetos desde el árbol del proyecto.")))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Insertar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancelar"))
        buttons.accepted.connect(lambda: self.accept() if self.selected() else None)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self):
        item = self.tree.currentItem()
        value = item.data(0, ROLE) if item else None
        return value[1] if value and value[0] == "faceplates" else None

    def apply_filter(self, text):
        needle = text.casefold().strip()

        def visit(item):
            value = item.data(0, ROLE)
            if value and value[0] == "faceplates":
                shown = not needle or needle in item.text(0).casefold() or needle in value[1].casefold()
            else:
                shown = any([visit(item.child(i)) for i in range(item.childCount())])
            item.setHidden(not shown)
            if shown and needle:
                item.setExpanded(True)
            return shown
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))
