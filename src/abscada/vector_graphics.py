"""Qt rendering and canvas drawing gestures for SCADA vector objects."""
import math
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF
from .drawing import PATH_KINDS, SHAPE_KINDS


def element_path(element):
    path = QPainterPath()
    for index, (x,y) in enumerate(element["points"]):
        point = QPointF(x*element["w"],y*element["h"])
        path.moveTo(point) if index == 0 else path.lineTo(point)
    return path


def paint_vector(painter, element, rect):
    kind = element["kind"]
    color = QColor(element.get("stroke_color", "#75879a" if kind == "pipe" else "#334155"))
    width = element.get("stroke_width",12 if kind == "pipe" else 2)
    style = {"solid":Qt.PenStyle.SolidLine,"dash":Qt.PenStyle.DashLine,"dot":Qt.PenStyle.DotLine}[element.get("stroke_style","solid")]
    pen = QPen(color,width,style,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind in SHAPE_KINDS:
        if element.get("filled", True):
            painter.setBrush(QColor(element.get("color", "#e9eef3")))
        if kind == "ellipse":
            painter.drawEllipse(rect)
        else:
            painter.drawRect(rect)
        return
    path = element_path(element)
    if kind == "pipe":
        pen.setColor(color.darker(155)); painter.setPen(pen); painter.drawPath(path)
        pen.setWidthF(max(1,width-3)); pen.setColor(color); painter.setPen(pen); painter.drawPath(path)
        pen.setWidthF(max(1,width*.23)); pen.setColor(color.lighter(135)); painter.setPen(pen); painter.drawPath(path)
    else:
        painter.drawPath(path)
    arrows = element.get("arrows","none")
    points = [QPointF(x*element["w"], y*element["h"]) for x,y in element["points"]]
    for end, adjacent, enabled in ((points[0],points[1],arrows in {"start","both"}), (points[-1],points[-2],arrows in {"end","both"})):
        if enabled:
            angle = math.atan2(end.y()-adjacent.y(),end.x()-adjacent.x())
            length = max(10,width*2)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(color)
            painter.drawPolygon(QPolygonF([end, end-QPointF(math.cos(angle-.45)*length, math.sin(angle-.45)*length),
                end-QPointF(math.cos(angle+.45)*length, math.sin(angle+.45)*length)]))


class DrawingInteraction:
    drawing_tool = None
    pan_start = None

    def set_drawing_tool(self, kind):
        self.drawing_tool = kind; self.drawing_points = []; self.hover_point = None
        self.setCursor(Qt.CursorShape.CrossCursor if kind else Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(bool(kind)); self.setFocus()
        if kind:
            self.scene().clearSelection()
        self.viewport().update()
        self.host.statusBar().showMessage({"pipe":"Tubería", "line":"Línea", "polyline":"Polilínea"}.get(kind,"Selección"))
        if hasattr(self.host, "select_tool_button"):
            self.host.select_tool_button.setVisible(bool(kind))

    def drawing_position(self, event):
        point = self.host.snap_position(self.mapToScene(event.position().toPoint()))
        if self.drawing_points:
            last = self.drawing_points[-1]
            if self.drawing_tool == "pipe" or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                point = QPointF(point.x(),last.y()) if abs(point.x()-last.x())>=abs(point.y()-last.y()) else QPointF(last.x(),point.y())
        return point

    def finish_drawing(self):
        points, kind = getattr(self,"drawing_points",[]), self.drawing_tool
        self.set_drawing_tool(None)
        if kind and len(points)>=2:
            self.host.insert_path(kind, [[p.x(),p.y()] for p in points])

    def mousePressEvent(self, event):
        if self.host.design_mode and event.button() == Qt.MouseButton.MiddleButton:
            self.pan_start = event.position(); self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept(); return
        if self.drawing_tool:
            if event.button() == Qt.MouseButton.RightButton:
                self.finish_drawing()
            elif event.button() == Qt.MouseButton.LeftButton:
                point = self.drawing_position(event)
                if not self.drawing_points or point != self.drawing_points[-1]:
                    self.drawing_points.append(point)
                if self.drawing_tool == "line" and len(self.drawing_points)==2:
                    self.finish_drawing()
                self.viewport().update()
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.pan_start is not None:
            delta=event.position()-self.pan_start; self.pan_start=event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-round(delta.y()))
            event.accept(); return
        if self.drawing_tool:
            self.hover_point = self.drawing_position(event); self.viewport().update()
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.pan_start is not None and event.button()==Qt.MouseButton.MiddleButton:
            self.pan_start=None; self.setCursor(Qt.CursorShape.CrossCursor if self.drawing_tool else Qt.CursorShape.ArrowCursor)
            event.accept(); return
        if self.drawing_tool:
            event.accept(); return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        if self.drawing_tool:
            self.finish_drawing(); event.accept(); return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self,event):
        if event.key() == Qt.Key.Key_Escape and self.host.design_mode:
            self.set_drawing_tool(None); self.scene().clearSelection(); event.accept(); return
        if self.drawing_tool:
            if event.key() in {Qt.Key.Key_Return,Qt.Key.Key_Enter}:
                self.finish_drawing()
            elif event.key() == Qt.Key.Key_Backspace and self.drawing_points:
                self.drawing_points.pop(); self.viewport().update()
            event.accept(); return
        arrows = {Qt.Key.Key_Left:(-1,0),Qt.Key.Key_Right:(1,0),Qt.Key.Key_Up:(0,-1),Qt.Key.Key_Down:(0,1)}
        if self.host.design_mode and event.key() in arrows and self.scene().selectedItems():
            dx,dy=arrows[event.key()]
            step = self.host.document().get("grid_size",10) if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            selected=[item.element for item in self.scene().selectedItems()]
            def move():
                for element in selected:
                    element.update(x=element["x"]+dx*step,y=element["y"]+dy*step)
            self.host.mutate(move); event.accept(); return
        super().keyPressEvent(event)

    def drawForeground(self,painter,rect):
        super().drawForeground(painter,rect)
        if self.drawing_tool and self.drawing_points:
            points = self.drawing_points + ([self.hover_point] if self.hover_point else [])
            painter.setPen(QPen(QColor("#147d75"),2,Qt.PenStyle.DashLine))
            painter.drawPolyline(points)
            painter.setBrush(QColor("#ffffff"))
            for point in self.drawing_points:
                painter.drawEllipse(point,4,4)
