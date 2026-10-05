import copy
import json
from pathlib import Path
import pytest
from abscada.project import Project
from abscada.faceplate_libraries import export_library, link, unlink, owner
from abscada.project_storage import documents

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def library_case(tmp_path):
    author = Project.load(ROOT/'examples/showcase')
    author.faceplates['unidad']['elements'].append(dict(id='picture',kind='image',x=0,y=0,w=20,h=20,
        source='assets/valve-off.svg',dynamics={'states':[dict(when=dict(tag='$run',op='eq',value=True,bad=False),style={'source':'assets/valve-on.svg'})]}))
    source = tmp_path/'process.json'
    export_library(author,['unidad'],source,'Process','1.0.0')
    consumer = Project.load(ROOT/'examples/showcase')
    for document in consumer.screens.values():
        for element in document['elements']:
            if element.get('template') == 'equipos__unidad':
                element['template'] = 'unidad'
    unlink(consumer, 'equipos')
    consumer.root = tmp_path/'consumer'
    return author, source, consumer


def instance(project):
    return next(e for e in project.screens['23_faceplates']['elements'] if e['kind']=='faceplate')


def test_link_save_assets_offline_and_frozen_snapshot(library_case):
    author, source, project = library_case
    link(project,source,'vendor')
    instance(project)['template']='vendor__unidad'
    project.save()
    frozen=copy.deepcopy(project)
    source.unlink()
    loaded=Project.load(project.root)
    assert owner(loaded,'vendor__unidad')=='vendor'
    assert 'faceplates/vendor__unidad.json' not in documents(loaded)
    image=loaded.faceplates['vendor__unidad']['elements'][-1]
    assert loaded.asset(image['source']).read_bytes()==author.asset('assets/valve-off.svg').read_bytes()
    assert loaded.asset(image['dynamics']['states'][0]['style']['source']).read_bytes()==author.asset('assets/valve-on.svg').read_bytes()
    assert list(loaded.elements('23_faceplates'))
    loaded.faceplates['vendor__unidad']['width']=99
    with pytest.raises(ValueError,match='solo lectura'): loaded.validate()
    assert frozen.faceplates['vendor__unidad']['width']==500


def test_updates_validate_consumers_and_are_atomic(library_case,tmp_path):
    author, source, project=library_case
    link(project,source,'vendor')
    instance(project)['template']='vendor__unidad'
    before=copy.deepcopy(project)
    author.faceplates['unidad']['parameters']['extra']='float'
    bad=tmp_path/'bad.json'
    export_library(author,['unidad'],bad,'Process','2.0.0')
    with pytest.raises(ValueError,match='incompletos'):link(project,bad,'vendor',update=True)
    assert project==before
    del author.faceplates['unidad']['parameters']['extra']
    author.faceplates['unidad']['title']='Updated unit'
    good=tmp_path/'good.json'
    export_library(author,['unidad'],good,'Process','1.1.0')
    link(project,good,'vendor',update=True)
    assert project.faceplates['vendor__unidad']['title']=='Updated unit'
    assert before.faceplates['vendor__unidad']['title']!='Updated unit'
    with pytest.raises(ValueError,match='en uso'):unlink(project,'vendor')
    instance(project)['template']='unidad'
    project.save()
    unlink(project,'vendor'); project.save()
    assert not (project.root/'libraries.json').exists()
    assert not Project.load(project.root).libraries


def test_package_rejects_dependencies_collision_and_version_rewrite(library_case,tmp_path):
    author,source,project=library_case
    link(project,source,'vendor')
    with pytest.raises(ValueError,match='ya existe'):link(project,source,'vendor')
    author.faceplates['unidad']['title']='Changed'
    changed=tmp_path/'changed.json'
    export_library(author,['unidad'],changed,'Process','1.0.0')
    with pytest.raises(ValueError,match='inmutable'):link(project,changed,'vendor',update=True)
    with pytest.raises(FileExistsError):export_library(author,['unidad'],source,'Process','1.1.0')
    author.faceplates['unidad']['elements'][0]['tag']='Local.Nivel'
    with pytest.raises(ValueError,match='inexistente'):export_library(author,['unidad'],tmp_path/'invalid.json','Process','2')
    assert not (tmp_path/'invalid.json').exists()
    project.faceplates['other__unidad']=copy.deepcopy(project.faceplates['unidad'])
    with pytest.raises(ValueError,match='Colisión'):link(project,source,'other')


def test_library_resource_paths_and_integrity(library_case,tmp_path):
    _,source,project=library_case
    package=json.loads(source.read_text(encoding='utf-8'))
    package['assets']['../escape.svg']='eA=='
    bad=tmp_path/'unsafe.json';bad.write_text(json.dumps(package),encoding='utf-8')
    with pytest.raises(ValueError,match='Ruta'):link(project,bad,'unsafe')
    link(project,source,'vendor');project.save()
    path=project.root/'libraries.json'
    data=json.loads(path.read_text(encoding='utf-8'));data['vendor']['package']['version']='tampered'
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='huella'):Project.load(project.root)


def test_library_manager_and_navigation(library_case):
    from PySide6.QtWidgets import QApplication
    from abscada.ui import Window
    from abscada.library_editor import LibraryDialog, PublishDialog
    _,source,project=library_case
    link(project,source,'vendor')
    app=QApplication.instance() or QApplication([])
    window=Window(project)
    dialog=LibraryDialog(window)
    assert dialog.table.rowCount()==1
    assert 'vendor__unidad' in dialog.details.toPlainText()
    publisher=PublishDialog(window)
    assert all(not publisher.faces.item(i).text().startswith('vendor__') for i in range(publisher.faces.count()))
    window.navigate('faceplates')
    assert not owner(project,window.document_name)
    publisher.close();dialog.close();window.close();app.processEvents()
