"""Graphical state preview: no Runtime, adapters, scripts or database writers."""
import copy
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QFormLayout,QComboBox,QPushButton,QLabel,QSplitter
from .graphics import CanvasScene,CanvasView,ElementItem
from .runtime import Sample
from .value_editor import ValueEditor


class VisualPreview(QMainWindow):
    design_mode=False
    preview_mode=True

    def __init__(self,studio):
        super().__init__(studio,Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
        self.project=copy.deepcopy(studio.project);self.setFont(studio.font());self.setStyleSheet(studio.styleSheet())
        self.containers={};self.running=False
        self.setWindowTitle('PRUEBA VISUAL · '+self.project.manifest['name']);self.resize(1200,760)
        self.document_name=studio.document_name if studio.document_kind=='screens' else self.project.manifest['startup_screen']
        tags=self.project.tags();self.samples={name:Sample(t['initial'],'good',time.time()) for name,t in tags.items()}
        root=QWidget();row=QHBoxLayout(root);self.setCentralWidget(root)
        panel=QWidget();panel.setMaximumWidth(280);form=QFormLayout(panel)
        badge=QLabel('PRUEBA VISUAL');badge.setObjectName('designBadge');form.addRow(badge)
        self.screen=QComboBox();self.screen.addItems(self.project.screens);self.screen.setCurrentText(self.document_name);form.addRow('Pantalla',self.screen)
        self.tag=QComboBox();self.tag.setEditable(True);self.tag.addItems(tags);form.addRow('Variable',self.tag)
        self.value=ValueEditor();form.addRow('Valor de prueba',self.value)
        self.quality=QComboBox()
        for key,title in [('good','Buena'),('bad','Mala'),('uncertain','Incierta')]:self.quality.addItem(title,key)
        form.addRow('Calidad',self.quality)
        apply=QPushButton('Aplicar estado');form.addRow(apply)
        self.feedback=QLabel('Solo previsualización gráfica. Sin comunicaciones ni ejecución de acciones.');self.feedback.setWordWrap(True);form.addRow(self.feedback)
        row.addWidget(panel);self.scene=CanvasScene(self);self.view=CanvasView(self.scene,self);row.addWidget(self.view,1)
        def select():
            name=self.tag.currentText()
            if name in tags:
                self.value.set_kind(tags[name]['type'],self.samples[name].value)
                self.quality.setCurrentIndex(self.quality.findData(self.samples[name].quality))
        self.tag.currentTextChanged.connect(select);select()
        def change():
            try:
                name=self.tag.currentText()
                if name not in tags:raise ValueError('Variable inexistente')
                self.samples[name]=Sample(self.value.value(),self.quality.currentData(),time.time())
                for scene in [self.scene]+[c.scene for c in self.containers.values()]:
                    for item in scene.items():
                        if isinstance(item,ElementItem):item.refresh_state()
                self.feedback.setText('Estado aplicado a la previsualización')
            except ValueError as exc:self.feedback.setText(str(exc))
        apply.clicked.connect(change);self.apply_state=change
        self.screen.currentTextChanged.connect(self.render_scene);self.render_scene()

    def render_scene(self):
        self.document_name=self.screen.currentText();self.containers.clear();self.scene.clear();doc=self.project.screens[self.document_name]
        self.scene.setSceneRect(0,0,doc['width'],doc['height'])
        for e in self.project.elements(self.document_name):self.scene.addItem(ElementItem(self,e))
        self.view.fit_canvas()

    def actuate(self,*args,**kwargs):pass

    def release_momentaries(self):pass
