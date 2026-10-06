"""Studio frame: menu bar, short tool bar and the section bar on the left."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QListWidget, QListWidgetItem

# key, title shown under the icon. «faceplates» and «types» live inside «screens» and «variables».
SECTIONS = (("screens", "Pantallas"), ("variables", "Variables"), ("connections", "Conexiones"), ("alarms", "Alarmas"),
            ("historian", "Registros"), ("automation", "Scripts"), ("diagnostics", "Diagnóstico"))
RAIL_OF = {"faceplates": "screens", "types": "variables"}


def section_icon(key, color="#387b91"):
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    if key == "screens":
        p.drawRoundedRect(QRectF(7, 9, 34, 23), 3, 3)
        p.drawLine(24, 32, 24, 38); p.drawLine(16, 39, 32, 39)
    elif key == "variables":
        for y in (13, 24, 35):
            p.drawEllipse(QPointF(11, y), 2, 2); p.drawLine(18, y, 40, y)
    elif key == "connections":
        p.drawRoundedRect(QRectF(5, 15, 13, 18), 2, 2); p.drawRoundedRect(QRectF(30, 15, 13, 18), 2, 2)
        p.drawLine(18, 24, 30, 24)
    elif key == "alarms":
        p.drawPolygon(QPolygonF([QPointF(24, 7), QPointF(42, 39), QPointF(6, 39)]))
        p.drawLine(24, 18, 24, 29); p.drawPoint(24, 34)
    elif key == "historian":
        p.drawEllipse(QRectF(9, 7, 30, 10))
        p.drawLine(9, 12, 9, 36); p.drawLine(39, 12, 39, 36)
        p.drawArc(QRectF(9, 31, 30, 10), 180 * 16, 180 * 16)
        p.drawArc(QRectF(9, 21, 30, 10), 180 * 16, 180 * 16)
    elif key == "automation":
        font = QFont(); font.setPixelSize(20); font.setBold(True); p.setFont(font)
        p.drawText(QRectF(0, 0, 48, 48), Qt.AlignmentFlag.AlignCenter, "</>")
    elif key == "diagnostics":
        p.drawPolyline(QPolygonF([QPointF(4, 26), QPointF(14, 26), QPointF(19, 12), QPointF(27, 38), QPointF(32, 22),
                                  QPointF(36, 26), QPointF(44, 26)]))
    p.end()
    return QIcon(pixmap)


class SectionRail(QListWidget):
    def __init__(self, host):
        super().__init__()
        self.setObjectName("sectionRail")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setMovement(QListWidget.Movement.Static)
        self.setWrapping(False)
        self.setIconSize(QSize(26, 26))
        self.setGridSize(QSize(84, 62))
        self.setFixedWidth(88)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for key, title in SECTIONS:
            item = QListWidgetItem(section_icon(key), title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setSizeHint(QSize(84, 62))
            self.addItem(item)
        self.currentItemChanged.connect(lambda item, previous: item and host.active_rail() != item.data(Qt.ItemDataRole.UserRole)
                                        and host.navigate(item.data(Qt.ItemDataRole.UserRole)))

    def show_section(self, key):
        key = RAIL_OF.get(key, key)
        self.blockSignals(True)
        for row in range(self.count()):
            if self.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.setCurrentRow(row)
        self.blockSignals(False)


def build_menus(studio):
    """Every command lives in a menu; the tool bar keeps only what is used all the time."""
    from .help_dialogs import SimulatorsDialog, about, open_log_folder
    from .library_editor import LibraryDialog
    from .palette_editor import edit_palette
    from .project_dialogs import VersionDialog
    from .project_settings import edit_project_settings

    def action(menu, title, callback, shortcut=None):
        item = QAction(title, studio)
        item.triggered.connect(lambda checked=False: callback())
        if shortcut:
            item.setShortcut(shortcut)
        menu.addAction(item)
        return item

    bar = studio.menuBar()
    file = bar.addMenu("&Archivo")
    studio.new_action = action(file, "Nuevo proyecto…", studio.new_project, "Ctrl+N")
    studio.open_action = action(file, "Abrir proyecto…", lambda: studio.open_project(), "Ctrl+O")
    recent = file.addMenu("Proyectos recientes")
    recent.aboutToShow.connect(lambda: studio.fill_recent_menu(recent))
    file.addSeparator()
    studio.save_action = action(file, "Guardar", studio.save_project, "Ctrl+S")
    action(file, "Recargar desde disco", studio.reload_project)
    action(file, "Versiones del proyecto…", lambda: VersionDialog(studio).exec())
    file.addSeparator()
    action(file, "Salir", studio.close)

    edit = bar.addMenu("&Edición")
    studio.undo_action = action(edit, "Deshacer", studio.undo)
    studio.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
    studio.redo_action = action(edit, "Rehacer", studio.redo)
    studio.redo_action.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
    edit.addSeparator()
    # Canvas actions keep their canvas-only shortcuts, so Ctrl+C still copies text in the fields.
    for canvas_action in studio.canvas_actions:
        edit.addAction(canvas_action)

    project = bar.addMenu("&Proyecto")
    action(project, "Ajustes del proyecto…", lambda: edit_project_settings(studio))
    action(project, "Paleta de colores…", lambda: edit_palette(studio))
    action(project, "Bibliotecas de faceplates…", lambda: LibraryDialog(studio).exec())
    project.addSeparator()
    action(project, "Revisar el proyecto", studio.review_project)

    tools = bar.addMenu("&Herramientas")
    action(tools, "Prueba visual…", studio.open_visual_preview)
    action(tools, "Simuladores de PLC…", lambda: SimulatorsDialog(studio).exec())
    action(tools, "Copia de seguridad de los registros (SQLite)…", lambda: studio.operational_editor.backup())

    help_menu = bar.addMenu("A&yuda")
    action(help_menu, "Acerca de abSCADA", lambda: about(studio))
    action(help_menu, "Abrir carpeta de registros de la aplicación", open_log_folder)

    toolbar = studio.addToolBar("Proyecto")
    toolbar.setObjectName("mainToolbar")
    toolbar.setMovable(False)
    for item in (studio.save_action, None, studio.undo_action, studio.redo_action):
        toolbar.addSeparator() if item is None else toolbar.addAction(item)
    studio.update_history_actions()
