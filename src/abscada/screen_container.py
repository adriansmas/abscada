"""Embedded screen surface. Acquisition and refresh belong to its runtime window."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLayout
from PySide6.QtCore import Qt
from .graphics import CanvasScene, CanvasView, ElementItem
from .screen_layouts import containers


class EmbeddedCanvasView(CanvasView):
    def fit_canvas(self):
        self.auto_fit = True
        bounds = self.scene().sceneRect()
        if bounds.isEmpty():
            return
        self.resetTransform()
        factor = min(self.viewport().width()/bounds.width(), self.viewport().height()/bounds.height())
        self.scale(factor, factor)
        self.centerOn(bounds.center())


class ScreenContainer(QWidget):
    design_mode = False

    def __init__(self, window, element):
        super().__init__()
        self.window = window
        self.project = window.project
        self.runtime = getattr(window,'runtime',None)
        self.preview_mode = getattr(window,'preview_mode',False)
        self.document_name = element['screen']
        self.setFont(window.font())
        self.scene = CanvasScene(self)
        self.view = EmbeddedCanvasView(self.scene, self)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setMinimumSize(0, 0)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.addWidget(self.view)
        self.initializing = True
        self.select_screen(self.document_name)
        self.initializing = False

    @property
    def samples(self):
        return self.window.samples

    def select_screen(self, screen):
        document = self.project.screens[screen]
        if containers(document):
            raise ValueError('No se puede abrir un layout dentro de un contenedor')
        self.document_name = screen
        self.window.release_momentaries()
        self.scene.clear()
        self.scene.setSceneRect(0, 0, document['width'], document['height'])
        for element in self.project.elements(screen):
            self.scene.addItem(ElementItem(self, element))
        self.view.fit_canvas()
        if not self.initializing and self.window.running:
            self.window.screen_opened(screen)

    def actuate(self, element, entry=False, phase=None):
        self.window.actuate(element, entry, source=self, phase=phase)
