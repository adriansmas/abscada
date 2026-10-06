import os
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from abscada.project import Project
from abscada.versioning import ProjectGit
from test_operational_ui import operational_studio, operational_project


def test_new_screen_dialog_dimensions_and_single_save(operational_studio):
    w=operational_studio
    def create():
        d=QApplication.activeModalWidget();d.name.setText('sensors');d.title.setText('Sensores')
        d.width.setValue(900);d.height.setValue(450);d.accept()
    QTimer.singleShot(0,create);w.new_document(False)
    assert w.document()['width']==900 and w.document()['title']=='Sensores'
    assert w.save_project()
    assert Project.load(w.project.root).screens['sensors']['height']==450


def test_save_rolls_back_io_failure_and_removes_deleted_sources(operational_project,monkeypatch):
    p=operational_project;p.scripts={'old':'print(1)'};p.save()
    original=p.manifest_path.read_bytes()
    p.manifest['name']='Changed';p.scripts={'new':'print(2)'}
    replace=os.replace
    def fail(source,target):
        if str(target).endswith('new.py'):raise OSError('disk error')
        return replace(source,target)
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError):p.save()
    assert p.manifest_path.read_bytes()==original
    assert Project.load(p.root).scripts=={'old':'print(1)'}
    monkeypatch.setattr(os,'replace',replace);p.save()
    assert Project.load(p.root).scripts=={'new':'print(2)'}


def test_git_versions_exclude_runtime_and_unrelated_staged_files(operational_project):
    p=operational_project;p.save();g=ProjectGit(p);g.initialize()
    (p.root/'runtime').mkdir(exist_ok=True);(p.root/'runtime/test.sqlite3').write_text('data')
    (p.root/'private.txt').write_text('unrelated');g.run('add','private.txt')
    p.scripts={'boot':'print(1)'};p.save();revision=g.commit()
    assert revision and 'Guardar proyecto' in g.history()
    files=g.run('ls-tree','-r','--name-only','HEAD')
    assert 'scripts/boot.py' in files and 'private.txt' not in files and 'runtime/' not in files
    assert 'private.txt' in g.run('diff','--cached','--name-only')
    assert g.commit() is None
    p.scripts={};p.save();assert g.commit()
    assert 'scripts/boot.py' not in g.run('ls-tree','-r','--name-only','HEAD')


def test_external_edits_are_not_overwritten(operational_project):
    p=operational_project;p.save()
    path=p.root/'screens/main.json'
    original=path.read_text(encoding='utf-8')
    path.write_text(original+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='fuera de Studio'):p.save()
    assert path.read_text(encoding='utf-8')==original+'\n'
    Project.load(p.root).save()
