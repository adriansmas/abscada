"""Render product-review fixes without touching the user's project or a PLC."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QSettings
from abscada.project import Project
from abscada.ui import Window
from abscada.dynamic_editor import DynamicDialog
from abscada.visual_preview import VisualPreview
from abscada.runtime import Sample

root=Path(__file__).resolve().parents[1];out=root/'docs/review-fixes';out.mkdir(exist_ok=True)
app=QApplication([])
with tempfile.TemporaryDirectory(prefix='abscada-review-fixes-') as temporary:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,temporary)
    project=Project.load(root/'examples/plant');project.root=Path(temporary)
    project.manifest['startup_screen']='process_design';project.manifest['palette']={'Marcha':'#147d75','Paro':'#b44141'}
    condition=lambda value:dict(tag='Pump1.running',op='eq',value=value,bad=False)
    for name,value in [('MARCHA',True),('PARO',False)]:
        project.screens['process_design']['elements'].append(dict(id=name,kind='button',x=800,y=430,w=180,h=48,text=name,tag='Pump1.running',action='set',value=value,color='@Marcha' if value else '@Paro',text_color='#ffffff',dynamics={'visible':condition(not value)}))
    w=Window(project);w.resize(1366,768);w.show();app.processEvents()
    w.render_scene(['MARCHA']);app.processEvents();w.grab().save(str(out/'studio-1366.png'))
    dynamic=DynamicDialog(w,w.scene.selectedItems()[0].element);dynamic.show();app.processEvents();dynamic.grab().save(str(out/'conditions.png'));dynamic.close()
    def structure():
        from PySide6.QtWidgets import QComboBox,QLineEdit
        d=app.activeModalWidget();d.findChild(QLineEdit,'variableName').setText('Pump3');d.findChildren(QComboBox)[0].setCurrentText('Pump')
        app.processEvents();d.grab().save(str(out/'structure.png'));d.reject()
    QTimer.singleShot(0,structure);w.variable_form(None)
    preview=VisualPreview(w);preview.show();app.processEvents();preview.grab().save(str(out/'preview-stopped.png'))
    preview.tag.setCurrentText('Pump1.running');preview.value.boolean.setCurrentIndex(1);preview.apply_state();app.processEvents();preview.grab().save(str(out/'preview-running.png'))
    for name,sample in list(preview.samples.items()):preview.samples[name]=Sample(sample.value,'bad',sample.timestamp)
    preview.quality.setCurrentIndex(preview.quality.findData('bad'))
    for item in preview.scene.items():
        if hasattr(item,'refresh_state'):item.refresh_state()
    app.processEvents();preview.grab().save(str(out/'preview-bad-quality.png'));preview.close()
    w.resize(980,650);app.processEvents();w.grab().save(str(out/'studio-980.png'))
    w.dirty=False;w.close()
