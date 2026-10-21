"""Embedded screen surface. Acquisition and refresh belong to its runtime window.

The screen shown in a container is drawn in the same scene as the window, as children of
the container element, scaled to fit and clipped to it. An embedded view (a proxy widget)
repainted the whole inner screen and its frame for every changed value.
"""
import shiboken6
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPen, QBrush
from PySide6.QtWidgets import QGraphicsRectItem
from .graphics import ElementItem, index_items
from .screen_layouts import containers
from .i18n import tr


class ContainerItems:
    """``container.scene.items()``: the items of the screen shown in the container."""
    def __init__(self, container):
        self.container = container

    def items(self):
        result = []
        stack = list(self.container.items_shown)
        while stack:
            item = stack.pop()
            result.append(item)
            stack.extend(item.childItems())
        return result


class ScreenContainer:
    design_mode = False

    def __init__(self, window, element, parent_item):
        self.window = window
        self.project = window.project
        self.runtime = getattr(window, 'runtime', None)
        self.preview_mode = getattr(window, 'preview_mode', False)
        self.document_name = element.get('screen', '')
        self.element = element
        # White behind the screen where its proportions leave room, as an embedded view did.
        self.frame = QGraphicsRectItem(0, 0, element['w'], element['h'], parent_item)
        self.frame.setBrush(QBrush(QColor('#ffffff'))); self.frame.setPen(QPen(QColor(0, 0, 0, 0)))
        self.root = QGraphicsRectItem(self.frame)
        self.root.setPen(QPen(QColor(0, 0, 0, 0)))
        self.scene = ContainerItems(self)
        self.dependents, self.animated, self.items_shown = {}, [], []
        self.initializing = True
        if self.document_name:
            self.select_screen(self.document_name)
        self.initializing = False

    @property
    def samples(self):
        return self.window.samples

    def font(self):
        return self.window.font()

    def map_to_scene(self, point):
        """A point of the shown screen in the coordinates of the window's scene."""
        return self.root.mapToScene(QPointF(point))

    def clear(self):
        old, self.items_shown = self.items_shown, []
        self.dependents, self.animated = {}, []
        for item in old:
            if shiboken6.isValid(item):
                item.setParentItem(None)
                if item.scene() is not None:
                    item.scene().removeItem(item)
                shiboken6.delete(item)   # its embedded viewers go with it

    def select_screen(self, screen, opened=True):
        document = self.project.screens[screen]
        if containers(document):
            raise ValueError(tr('No se puede abrir un layout dentro de un contenedor'))
        self.document_name = screen
        self.window.release_momentaries()
        self.clear()
        width, height = document['width'], document['height']
        scale = min(self.element['w'] / width, self.element['h'] / height)
        self.root.setRect(0, 0, width, height)
        self.root.setBrush(QBrush(QColor(document.get('background', '#ffffff'))))
        self.root.setScale(scale)
        self.root.setPos((self.element['w'] - width * scale) / 2, (self.element['h'] - height * scale) / 2)
        from .dynamics import resolve_indices
        elements, self.index_state = resolve_indices(self.project.elements(screen), self.samples)
        items = [ElementItem(self, element) for element in elements]
        for item in items:
            item.setParentItem(self.root)
        index_items(self, items)
        if not self.initializing and self.window.running and opened:
            self.window.screen_opened(screen)

    def actuate(self, element, entry=False, phase=None, editor=None, text=None):
        self.window.actuate(element, entry, source=self, phase=phase, editor=editor, text=text)
