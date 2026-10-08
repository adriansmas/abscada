"""Rendering shared by a design-only canvas and an operational canvas."""
from __future__ import annotations
import copy
import math
import shiboken6
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QEvent, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon, QFont, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import QGraphicsObject, QGraphicsItem, QGraphicsView, QGraphicsScene, QGraphicsProxyWidget, QLineEdit

from .text_lists import display_text
from .drawing import PATH_KINDS, SHAPE_KINDS, world_points, set_points
from .vector_graphics import element_path, paint_vector, DrawingInteraction
from .i18n import tr

TOOL_NAMES = {"text": tr("Texto"), "lamp": tr("Piloto"), "button": tr("Botón"),
           "input": tr("Entrada"), "bar": tr("Barra"), "gauge": tr("Indicador"), "image": tr("Imagen"), "faceplate": tr("Objeto de librería"),
           "trend": tr("Tendencia"), "alarm_view": tr("Alarmas"), "line": tr("Línea"), "polyline": tr("Polilínea"),
           "pipe": tr("Tubería"), "rectangle": tr("Rectángulo"), "ellipse": tr("Elipse"), "text_list": tr("Lista de textos"), "screen_container": tr("Contenedor de pantalla")}


def tool_icon(kind):
    pixmap = QPixmap(40, 40)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#387b91"), 2))
    painter.setBrush(QColor("#e1eff4"))
    if kind in PATH_KINDS:
        painter.setPen(QPen(QColor("#387b91"), 6 if kind == "pipe" else 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline([QPointF(5,30),QPointF(20,30),QPointF(20,10),QPointF(35,10)] if kind != "line" else [QPointF(5,30),QPointF(35,10)])
    elif kind == "rectangle":
        painter.drawRect(5,8,30,24)
    elif kind == "ellipse":
        painter.drawEllipse(5,8,30,24)
    elif kind == "lamp":
        painter.drawEllipse(10, 10, 20, 20)
    elif kind == "bar":
        painter.drawRoundedRect(12, 4, 16, 32, 3, 3)
        painter.fillRect(15, 20, 10, 13, QColor("#387b91"))
    elif kind == "gauge":
        painter.drawEllipse(4, 4, 32, 32)
        painter.setPen(QPen(QColor("#c0392b"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(20, 22, 29, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#387b91"))
        painter.drawEllipse(17, 19, 6, 6)
    elif kind == "faceplate":
        painter.drawRoundedRect(4, 7, 32, 26, 3, 3)
        painter.drawEllipse(9, 13, 7, 7)
        painter.drawLine(21, 15, 30, 15)
        painter.drawLine(10, 26, 30, 26)
    elif kind == "image":
        painter.drawRoundedRect(4, 7, 32, 26, 2, 2)
        painter.drawEllipse(9, 12, 5, 5)
        painter.drawLine(8, 28, 19, 19)
        painter.drawLine(19, 19, 31, 28)
    elif kind in {"text", "text_list"}:
        painter.setFont(QFont("Segoe UI", 22, QFont.Weight.DemiBold))
        painter.drawText(QRectF(0, 0, 40, 40), Qt.AlignmentFlag.AlignCenter, "T")
    else:
        painter.drawRoundedRect(3, 10, 34, 20, 4, 4)
        painter.drawLine(10, 20, 28, 20)
        if kind == "input":
            painter.drawLine(27, 14, 27, 26)
    painter.end()
    return QIcon(pixmap)


_SVG = {}


def svg_renderer(path):
    """Cached QSvgRenderer per file and modification time; None if the SVG is invalid."""
    from PySide6.QtSvg import QSvgRenderer
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    if key not in _SVG:
        renderer = QSvgRenderer(str(path))
        if hasattr(renderer, "setAspectRatioMode"):  # Qt 6.7+: symbols keep their proportions
            renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        _SVG[key] = renderer if renderer.isValid() else None
    return _SVG[key]


def draw_element(painter, e, host, rect=None):
    rect = rect or QRectF(0, 0, e["w"], e["h"])
    from .dynamics import effective
    e=effective(e,host.samples,host.design_mode)
    from .project_languages import localized, default_language, resolve
    code = getattr(host, 'editing_language', None) if host.design_mode else getattr(getattr(host, 'runtime', None), 'language', None)
    code = code or default_language(host.project)
    e = localized(e, code, default_language(host.project))
    kind = e["kind"]
    if kind in PATH_KINDS | SHAPE_KINDS:
        paint_vector(painter, e, rect)
        return
    design = host.design_mode
    sample = None if design else host.samples.get(e.get("tag"))
    value = sample.value if sample else None
    good = sample is None or sample.quality == "good"
    border = QColor(e.get("border_color", "#ccd7e3"))
    background = QColor(e.get("color", "#f1f5f9"))
    foreground = QColor(e.get("text_color", "#f8fafc" if background.lightness() < 110 else "#273b53"))
    painter.setPen(QPen(border, 1))
    painter.setBrush(background)
    font = QFont(host.font())
    font.setPixelSize(int(e.get("font_size", 15)))
    font.setBold(e.get("bold",False))
    painter.setFont(font)
    if kind == "screen_container":
        if design:
            document = host.project.screens.get(e.get("screen"))
            painter.fillRect(rect, QColor(document.get("background", "#ffffff") if document else "#ffffff"))
            if document:
                painter.save()
                painter.setClipRect(rect)
                scale = min(rect.width()/document['width'], rect.height()/document['height'])
                painter.translate((rect.width()-document['width']*scale)/2, (rect.height()-document['height']*scale)/2)
                painter.scale(scale, scale)
                for child in host.project.elements(e['screen']):
                    if child['kind'] == 'screen_container':
                        continue
                    painter.save(); painter.translate(child['x'], child['y'])
                    draw_element(painter, child, host); painter.restore()
                painter.restore()
            painter.setPen(QPen(QColor('#387b91'), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawRect(rect)
        return
    if kind == "faceplate":
        template = host.project.faceplates.get(e.get("template"))
        # Symbols without a background (most library objects) are drawn as themselves, without a frame.
        if not template or "background" in template:
            painter.setBrush(QColor(template.get("background", "#f8fafc") if template else "#f8fafc"))
            painter.drawRoundedRect(rect, 8, 8)
        if template:
            painter.save()
            painter.scale(rect.width() / template["width"], rect.height() / template["height"])
            for source in template["elements"]:
                child = copy.deepcopy(source)
                if child.get("tag", "").startswith("$"):
                    child["tag"] = e.get("bindings", {}).get(child["tag"][1:], "")
                painter.save()
                painter.translate(child["x"], child["y"])
                draw_element(painter, child, host)
                painter.restore()
            painter.restore()
        return
    if kind in {"trend", "alarm_view"}:
        painter.setBrush(QColor("#ffffff")); painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QColor("#506176"))
        views = host.project.trends if kind == "trend" else host.project.alarm_views
        title = resolve(views.get(e.get("view"), {}).get("title", TOOL_NAMES[kind]), code, default_language(host.project))
        painter.drawText(rect.adjusted(14, 8, -14, -rect.height()+42), title)
        painter.setPen(QPen(QColor("#dde5ed"), 1))
        for y in range(55, int(rect.height())-15, 35):
            painter.drawLine(15, y, int(rect.width())-15, y)
        if kind == "trend":
            painter.setPen(QPen(QColor("#147d75"), 2))
            points = [QPointF(20+i*(rect.width()-40)/8, rect.height()*fraction) for i, fraction in enumerate((0.7,0.65,0.72,0.48,0.53,0.37,0.43,0.31,0.34))]
            painter.drawPolyline(points)
        return
    if kind == "lamp":
        color = "#97a9ba" if design else e.get("lamp_color", "#e5a339")
        painter.setPen(QPen(QColor(color).darker(115), 1))
        painter.setBrush(QColor(color))
        diameter = min(rect.width(), rect.height()) - 10
        painter.drawEllipse(QRectF((rect.width()-diameter)/2, (rect.height()-diameter)/2, diameter, diameter))
        painter.setBrush(QColor(255, 255, 255, 90))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(rect.width()/2 - diameter/4, rect.height()/2 - diameter/3, diameter/3, diameter/4))
        if not design and not good:
            painter.setPen(QColor('#17273d'));painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,'!')
        return
    if kind == "gauge":
        from .gauges import paint_gauge
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_gauge(painter, e, rect, value, good, design)
        return
    if kind == "bar":
        painter.setBrush(QColor("#f0f4f8"))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
        try:
            ratio = 0.4 if design else max(0, min(1, (float(value) - e.get("min", 0)) / (e.get("max", 100) - e.get("min", 0))))
        except (TypeError, ValueError, ZeroDivisionError):
            ratio = 0
        inner = rect.adjusted(6, 6, -6, -6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#bfccd9" if design else e.get('color',"#3da9bf" if good else "#e5a339")))
        painter.drawRoundedRect(QRectF(inner.left(), inner.bottom()-inner.height()*ratio, inner.width(), inner.height()*ratio), 4, 4)
        return
    if kind == "image":
        pixmap = QPixmap()
        try:
            source = e.get("source", "")
            path = host.project.asset(source) if source else None
            if path is not None and path.suffix.lower() == ".svg":
                renderer = svg_renderer(path)
                if renderer is not None:
                    renderer.render(painter, rect)  # vector: sharp at any size and zoom
                    return
            elif path is not None:
                pixmap = QPixmap(str(path))
        except ValueError:
            pass
        if not pixmap.isNull():
            painter.drawPixmap(rect.toRect(), pixmap)
            return
        painter.setBrush(QColor("#f3f6fa"))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QColor("#8092a7"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("Imagen"))
        return
    if kind == "button":
        painter.setBrush(QColor(e.get("color", "#e6f3f1")))
        painter.setPen(QPen(QColor(e.get("border_color", "#9bc9c4")), 1))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
    elif kind == "input":
        painter.setBrush(QColor(e.get("color", "#ffffff")))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)
    elif "color" in e or e.get("tag"):
        painter.drawRoundedRect(rect, 5, 5)
    text = display_text(e, sample, design=design) if kind == "text_list" and not e.get('_text_override') else e.get("text", TOOL_NAMES[kind])
    if e.get("tag") and kind in ("text", "input"):
        if design:
            display = "—"
        elif sample:
            display = f"{value:.{int(e.get('decimals', 2))}f}" if isinstance(value, float) else str(value)
        else:
            display = "—"
        text = f"{text}  {display} {e.get('unit', '')}".strip()

    painter.setPen(foreground if good or 'text_color' in e else QColor("#b57519"))
    alignment = {"left":Qt.AlignmentFlag.AlignLeft,"center":Qt.AlignmentFlag.AlignHCenter,"right":Qt.AlignmentFlag.AlignRight}[e.get("text_align","center")]
    bounds=rect.adjusted(8,3,-8,-3)
    if not design and not good:
        painter.drawText(QRectF(rect.right()-18,1,16,16),Qt.AlignmentFlag.AlignCenter,'!')
        bounds.adjust(0,0,-14,0)
    # Keep values on one line; scale to fit instead of inserting status words.
    if (e.get('tag') and kind in {'text','input'}) or kind=='button':
        metrics=painter.fontMetrics()
        if metrics.horizontalAdvance(text)>bounds.width() and bounds.width()>0:
            font.setPixelSize(max(5,int(font.pixelSize()*bounds.width()/metrics.horizontalAdvance(text))))
            painter.setFont(font)
        flags=alignment | Qt.AlignmentFlag.AlignVCenter
    else: flags=alignment | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap
    painter.drawText(bounds,flags,text)


class CanvasScene(QGraphicsScene):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.grid = host.design_mode
        self.setBackgroundBrush(QColor("#e9edf3" if host.design_mode else "#ffffff"))

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        bounds = self.sceneRect()
        if self.host.design_mode:
            document = self.host.document()
        elif hasattr(self.host, "screen_document"):
            document = self.host.screen_document()
        else:
            document = self.host.project.screens[self.host.document_name]
        painter.fillRect(bounds, QColor(document.get("background", "#ffffff")))
        if self.grid and document.get("show_grid", True):
            rect = rect.intersected(bounds)
            painter.setPen(QPen(QColor("#e3e9f0"), 1))
            points = []
            step = document.get("grid_size", 10)
            step *= max(1, math.ceil(6/max(.001, step*abs(painter.worldTransform().m11()))))
            for x in range(int(rect.left()) // step * step, int(rect.right()) + step, step):
                for y in range(int(rect.top()) // step * step, int(rect.bottom()) + step, step):
                    points.append(QPointF(x, y))
            painter.drawPoints(points)
            painter.setPen(QPen(QColor("#cbd5e1"), 1))
            painter.drawRect(bounds)


class CanvasView(DrawingInteraction, QGraphicsView):
    def __init__(self, scene, host):
        super().__init__(scene)
        self.host = host
        self.auto_fit = True
        # Runtime only (Ajustes del proyecto → Operación): fit, stretch or none.
        self.scale_mode = "fit"
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(host.design_mode)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag if host.design_mode else QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def contextMenuEvent(self, event):
        # Design only: right click on an element (or on the empty sheet) offers its commands.
        if not self.host.design_mode or self.drawing_tool:
            super().contextMenuEvent(event)
            return
        item = self.itemAt(event.pos())
        while item is not None and not hasattr(item, "element"):
            item = item.parentItem()
        if item is not None and not item.isSelected():
            self.scene().clearSelection()
            item.setSelected(True)
        self.host.canvas_menu(event.globalPos())
        event.accept()

    def fit_canvas(self):
        self.auto_fit = True
        pad = 24 if self.host.design_mode else 0
        mode = "fit" if self.host.design_mode else self.scale_mode
        if mode == "none":
            self.resetTransform()
        else:
            self.fitInView(self.scene().sceneRect().adjusted(-pad, -pad, pad, pad),
                           Qt.AspectRatioMode.IgnoreAspectRatio if mode == "stretch" else Qt.AspectRatioMode.KeepAspectRatio)
        self.update_zoom_label()

    def update_zoom_label(self):
        if not self.host.design_mode or not hasattr(self.host,"zoom_field"):
            return
        field = self.host.zoom_field; field.blockSignals(True)
        percent = f"{round(self.transform().m11()*100)}%"
        if self.auto_fit:
            field.setItemText(0,tr("Encajar ({percent})", percent=percent)); field.setCurrentIndex(0)
        else:
            index = field.findText(percent)
            if index < 0:
                if field.count()>6:
                    field.setItemText(6,percent)
                else:
                    field.addItem(percent)
                index=6
            field.setCurrentIndex(index)
        field.blockSignals(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit and self.scene() and not self.scene().sceneRect().isEmpty():
            self.fit_canvas()

    def wheelEvent(self, event):
        if self.host.design_mode and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.auto_fit = False
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            if 0.15 <= self.transform().m11() * factor <= 4:
                self.scale(factor, factor)
                self.update_zoom_label()
            event.accept()
        else:
            super().wheelEvent(event)

    def accepts(self, mime):
        # Toolbox kinds, and library objects dragged from the «Librerías» tree.
        return self.host.design_mode and (mime.hasFormat("application/x-abscada-element")
                                          or mime.hasFormat("application/x-abscada-template"))

    def dragEnterEvent(self, event):
        if self.accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self.accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if self.host.design_mode and mime.hasFormat("application/x-abscada-template"):
            name = bytes(mime.data("application/x-abscada-template")).decode("utf-8")
            position = self.mapToScene(event.position().toPoint())
            event.setDropAction(Qt.DropAction.CopyAction); event.accept()
            # After the drop has finished: the insertion may open a dialog to link parameters.
            QTimer.singleShot(0, lambda: self.host.insert_library_object(name, position))
        elif self.host.design_mode and mime.hasFormat("application/x-abscada-element"):
            kind = bytes(mime.data("application/x-abscada-element")).decode()
            position = self.mapToScene(event.position().toPoint())
            self.host.add_element(kind, position)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class InlineEntry(QLineEdit):
    """Box shown over an input while its value is typed: Enter writes, Esc or leaving cancels."""
    finished = Signal(object)   # the text, or None when cancelled

    def __init__(self, text, element):
        super().__init__(text)
        self._done = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"QLineEdit {{ background: white; color: #1c3b59; border: 2px solid #147d75; border-radius: 4px;"
                           f" font-size: {int(element.get('font_size', 15))}px; padding: 0 4px; selection-background-color: #147d75; }}")

    def _finish(self, value):
        if not self._done:
            self._done = True
            self.finished.emit(value)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish(self.text())
        elif event.key() == Qt.Key.Key_Escape:
            self._finish(None)
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._finish(None)


class ElementItem(QGraphicsObject):
    def __init__(self, host, element):
        super().__init__()
        self.host, self.element = host, element
        self.resizing = False
        self.node_index = None
        self.selection_only = False
        self.dragged = False
        self.pressed = False
        self.setPos(element["x"], element["y"])
        if host.design_mode:
            self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                          QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
            self.setAcceptHoverEvents(True)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor if element["kind"] in {"button", "input"} else Qt.CursorShape.ArrowCursor)
            if element["kind"] == "screen_container":
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
                from .screen_container import ScreenContainer
                self.proxy = QGraphicsProxyWidget(self)
                widget = ScreenContainer(host, element)
                host.containers[element['id']] = widget
                self.proxy.setWidget(widget)
                self.proxy.resize(element['w'], element['h'])
            if element["kind"] in {"trend", "alarm_view"} and not getattr(host,"preview_mode",False):
                from .viewers import TrendViewer, AlarmViewer
                self.proxy = QGraphicsProxyWidget(self)
                widget = TrendViewer(host.project, host.project.trends[element["view"]], host.runtime) if element["kind"] == "trend" else AlarmViewer(host.project, host.runtime, host.project.alarm_views[element["view"]])
                self.proxy.setWidget(widget)
                widget.setMinimumSize(0, 0)
                # Laid out at its own size: the view scales it uniformly with the rest of the screen.
                self.proxy.resize(element["w"], element["h"])
        self.setToolTip(element.get("tag", element["id"]))
        if host.design_mode:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not element.get('editor_locked',False))
            if element.get('editor_hidden'): self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        else: self.refresh_state()

    def refresh_state(self):
        if self.host.design_mode: return
        from .dynamics import permitted
        visible=permitted(self.element,self.host.samples,'visible')
        enabled=permitted(self.element,self.host.samples,'enabled')
        sample=self.host.samples.get(self.element.get('tag'))
        if self.pressed and (not visible or not enabled or (sample and sample.quality!='good')): self.cancel_press()
        self.setVisible(visible)
        self.setEnabled(enabled)
        self.setOpacity(1 if enabled or self.element.get("dynamics",{}).get("disabled") else .55)
        sample=self.host.samples.get(self.element.get('tag'))
        from .project_languages import resolve, default_language
        code = getattr(getattr(self.host, 'runtime', None), 'language', default_language(self.host.project))
        detail=resolve(self.element.get('tooltip', self.element.get('tag',self.element['id'])), code, default_language(self.host.project))
        if sample and sample.quality!='good': detail+=tr(' · Último valor; calidad ')+{'bad':tr('Mala'),'uncertain':tr('Incierta')}.get(sample.quality,sample.quality)
        if not enabled: detail+=' · '+resolve(self.element.get('dynamics',{}).get('disabled_reason',tr('No se cumple el permiso de operación')), code, default_language(self.host.project))
        self.setToolTip(detail)
        self.update()

    def cancel_press(self):
        if self.pressed and self.element.get('action') in {'momentary','press_release'}:
            self.host.actuate(self.element,phase='release')
        self.pressed=False

    def sceneEvent(self,event):
        if event.type()==QEvent.Type.UngrabMouse and not self.host.design_mode: self.cancel_press()
        return super().sceneEvent(event)

    def boundingRect(self):
        pad = max(8, self.element.get("stroke_width",12 if self.element["kind"] == "pipe" else 2)*2)
        return QRectF(-pad, -pad, self.element["w"]+2*pad, self.element["h"]+2*pad)

    def shape(self):
        if self.element["kind"] in PATH_KINDS:
            stroker = QPainterPathStroker(); stroker.setWidth(max(12,self.element.get("stroke_width",12 if self.element["kind"]=="pipe" else 2)))
            path = stroker.createStroke(element_path(self.element))
            if self.isSelected():
                for x,y in self.element["points"]:
                    path.addEllipse(QPointF(x*self.element["w"],y*self.element["h"]),8,8)
            return path
        path = QPainterPath(); path.setFillRule(Qt.FillRule.WindingFill); rect = QRectF(0,0,self.element["w"],self.element["h"])
        path.addEllipse(rect) if self.element["kind"] == "ellipse" else path.addRect(rect)
        if self.element["kind"] in SHAPE_KINDS and not self.element.get("filled",True):
            stroker = QPainterPathStroker(); stroker.setWidth(max(10,self.element.get("stroke_width",2)))
            path = stroker.createStroke(path)
        if self.isSelected():
            for point in self.resize_handles().values():
                path.addRect(QRectF(point.x()-6,point.y()-6,12,12))
        return path

    def resize_handles(self):
        w,h = self.element["w"],self.element["h"]
        return {"nw":QPointF(0,0),"n":QPointF(w/2,0),"ne":QPointF(w,0),"e":QPointF(w,h/2),
            "se":QPointF(w,h),"s":QPointF(w/2,h),"sw":QPointF(0,h),"w":QPointF(0,h/2)}

    def resize_at(self, position):
        if self.element["kind"] in PATH_KINDS:
            return None
        return next((key for key,point in self.resize_handles().items() if (point-position).manhattanLength() <= 12),None)

    def node_at(self, position):
        if self.element["kind"] not in PATH_KINDS:
            return None
        for i,(x,y) in enumerate(self.element["points"]):
            if (position-QPointF(x*self.element["w"],y*self.element["h"])).manhattanLength() <= 12:
                return i
        return None

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.host.design_mode or not self.element.get("editor_hidden"):
            draw_element(painter, self.element, self.host)
        if self.isSelected():
            rect = QRectF(0, 0, self.element["w"], self.element["h"])
            painter.setPen(QPen(QColor("#218cba"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(QColor("#218cba"))
            points = [QPointF(x*self.element["w"],y*self.element["h"]) for x,y in self.element["points"]] if self.element["kind"] in PATH_KINDS else self.resize_handles().values()
            for point in points:
                painter.drawRect(QRectF(point.x()-3, point.y()-3, 6, 6))

    def hoverMoveEvent(self, event):
        handle = self.resize_at(event.pos()) if self.isSelected() and len(self.scene().selectedItems())==1 else None
        cursor = {"nw":Qt.CursorShape.SizeFDiagCursor,"se":Qt.CursorShape.SizeFDiagCursor,
            "ne":Qt.CursorShape.SizeBDiagCursor,"sw":Qt.CursorShape.SizeBDiagCursor,
            "n":Qt.CursorShape.SizeVerCursor,"s":Qt.CursorShape.SizeVerCursor,
            "e":Qt.CursorShape.SizeHorCursor,"w":Qt.CursorShape.SizeHorCursor}.get(handle,Qt.CursorShape.SizeAllCursor)
        self.setCursor(cursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if not self.host.design_mode:
            if self.element["kind"] in {"button", "input"} and event.button() == Qt.MouseButton.LeftButton:
                self.pressed = True
                if self.element.get('action') in {'momentary','press_release'}: self.host.actuate(self.element,phase='press')
                event.accept()
            else:
                event.ignore()
            return
        if self.host.design_mode:
            if self.element.get('editor_locked'):
                self.setSelected(True); event.accept(); return
            self.host.begin_interaction()
            self.selection_only = not self.isSelected()
            group=self.element.get('group')
            if group and self.isSelected() and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                for item in self.scene().items():
                    if hasattr(item,'element') and item.element.get('group')==group:item.setSelected(True)
            self.dragged = False
            self.node_index = self.node_at(event.pos()) if self.isSelected() and len(self.scene().selectedItems())==1 else None
            if self.node_index is not None:
                self.node_origin = world_points(self.element)
            self.resizing = self.resize_at(event.pos()) if self.isSelected() and len(self.scene().selectedItems())==1 else None
            if self.resizing:
                self.resize_origin = copy.deepcopy(self.element)
                self.resize_start = event.scenePos()
        if self.selection_only:
            if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.scene().clearSelection()
            self.setSelected(True)
            group=self.element.get('group')
            if group:
                for item in self.scene().items():
                    if hasattr(item,'element') and item.element.get('group')==group: item.setSelected(True)
            event.accept()
        elif self.resizing or self.node_index is not None:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.host.design_mode and self.element.get('editor_locked'): event.accept(); return
        if self.selection_only:
            event.accept()
            return
        self.dragged = True
        if self.node_index is not None:
            points = copy.deepcopy(self.node_origin)
            point = self.host.snap_position(event.scenePos()); index = self.node_index
            if self.element["kind"] == "pipe":
                for adjacent in (index-1,index+1):
                    if 0 <= adjacent < len(points):
                        if points[adjacent][0] == points[index][0]:
                            points[adjacent][0] = point.x()
                        elif points[adjacent][1] == points[index][1]:
                            points[adjacent][1] = point.y()
            points[index] = [point.x(),point.y()]
            if any(p != points[0] for p in points):
                self.prepareGeometryChange(); set_points(self.element,points)
                self.setPos(self.element["x"],self.element["y"]); self.update()
            event.accept()
        elif self.resizing:
            self.prepareGeometryChange()
            original = self.resize_origin
            delta = event.scenePos()-self.resize_start
            left,top,right,bottom = original["x"],original["y"],original["x"]+original["w"],original["y"]+original["h"]
            minimum = (400,280) if self.element["kind"] in {"trend","alarm_view"} else (20,20)
            if "w" in self.resizing: left = min(right-minimum[0],left+delta.x())
            if "e" in self.resizing: right = max(left+minimum[0],right+delta.x())
            if "n" in self.resizing: top = min(bottom-minimum[1],top+delta.y())
            if "s" in self.resizing: bottom = max(top+minimum[1],bottom+delta.y())
            self.element.update(x=round(left,1),y=round(top,1),w=round(right-left,1),h=round(bottom-top,1))
            self.setPos(self.element["x"],self.element["y"])
            self.update(); event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.host.design_mode:
            if not self.resizing and self.node_index is None and not self.selection_only:
                super().mouseReleaseEvent(event)
            moved=self.scene().selectedItems() if self.dragged and not self.resizing and self.node_index is None else []
            offset=QPointF()
            if moved and self.host.snap_action.isChecked():
                offset=self.host.snap_position(self.pos())-self.pos()
            for item in moved:
                if item.element.get('editor_locked'): continue
                x, y = item.x()+offset.x(), item.y()+offset.y()
                item.setPos(x, y)
                item.element.update(x=round(x, 1), y=round(y, 1))
            self.resizing = False
            self.node_index = None
            self.selection_only = False
            self.host.end_interaction()
        else:
            pressed, self.pressed = self.pressed, False
            super().mouseReleaseEvent(event)
            if pressed and self.element.get('action') in {'momentary','press_release'}:
                self.host.actuate(self.element,phase='release'); return
            if pressed and self.element["kind"] == "button" and event.button() == Qt.MouseButton.LeftButton and QRectF(0,0,self.element['w'],self.element['h']).contains(event.pos()):
                self.host.actuate(self.element)
            elif pressed and self.element["kind"] == "input" and event.button() == Qt.MouseButton.LeftButton and QRectF(0,0,self.element['w'],self.element['h']).contains(event.pos()):
                self.host.actuate(self.element, entry=True, editor=self.begin_edit)

    def begin_edit(self, text, commit):
        """Type the value of an input right on it (no dialog)."""
        self.end_edit()
        entry = InlineEntry(text, self.element)
        entry.resize(int(self.element["w"]), int(self.element["h"]))
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(entry)
        proxy.setZValue(1000)
        self.entry_proxy = proxy
        def done(typed):
            QTimer.singleShot(0, self.end_edit)
            if typed is not None:
                QTimer.singleShot(0, lambda: commit(typed))
        entry.finished.connect(done)
        entry.selectAll()
        proxy.setFocus()
        entry.setFocus()

    def end_edit(self):
        proxy = getattr(self, "entry_proxy", None)
        self.entry_proxy = None
        if proxy is not None and shiboken6.isValid(proxy):
            proxy.deleteLater()   # the proxy owns the entry box and removes it with itself

    def mouseDoubleClickEvent(self, event):
        if not self.host.design_mode and self.element["kind"] == "input":
            event.accept()   # the first click already opened the entry box
        elif self.host.design_mode:
            if self.element["kind"] == "faceplate":
                host, template = self.host, self.element["template"]
                # Rebuild the scene after this item's mouse event has returned.
                QTimer.singleShot(0, lambda: host.open_faceplate_template(template))
            elif self.element["kind"] in {"trend", "alarm_view"}:
                QTimer.singleShot(0, self.host.configure_viewer)
            elif self.element["kind"] in PATH_KINDS | SHAPE_KINDS:
                self.host.drawing_properties.width.setFocus()
            else:
                self.host.text_field.setFocus()
                self.host.text_field.selectAll()
        else:
            super().mouseDoubleClickEvent(event)
