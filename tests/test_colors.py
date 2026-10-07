"""Explicit colors and lossless migration of legacy project palettes."""
import json
import pytest
from abscada.project import Project
from abscada.dynamics import validate_color
from test_operations import operational_project


def test_open_legacy_colors_preserves_appearance_and_literal_text(operational_project):
    p = operational_project
    p.screens['main']['background'] = '#123456'
    p.screens['main']['elements'] = [dict(id='lamp', kind='lamp', tag='Fault', x=0, y=0, w=40, h=40,
        color='#123456', lamp_colors={'on':'#123456','off':'#abcdef','bad':'#80123456'},
        dynamics={'states':[{'when':dict(tag='Fault',op='eq',value=True), 'style':{'color':'#123456'}}]}),
        dict(id='label',kind='text',x=50,y=0,w=200,h=40,text='@brand',text_color='#123456')]
    p.faceplates['sample'] = dict(width=100,height=100,parameters={},background='#123456',elements=[])
    p.save()
    manifest = json.loads(p.manifest_path.read_text(encoding='utf-8'))
    manifest['palette'] = {'brand':'#123456'}
    p.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    for path in (p.root/'screens/main.json', p.root/'faceplates/sample.json'):
        source = path.read_text(encoding='utf-8').replace('#123456','@brand')
        path.write_text(source, encoding='utf-8')
    loaded = Project.load(p.root)
    assert 'palette' not in loaded.manifest
    assert loaded.screens == p.screens
    assert loaded.faceplates['sample'] == p.faceplates['sample']
    loaded.save()
    assert 'palette' not in json.loads(loaded.manifest_path.read_text(encoding='utf-8'))
    assert Project.load(p.root).screens == loaded.screens


@pytest.mark.parametrize('value', ['@brand', 'red', '#12345', '#GGGGGG', 123])
def test_colors_reject_references_and_invalid_hex(value):
    with pytest.raises(ValueError):
        validate_color(value)


@pytest.mark.parametrize('value', ['#123456', '#80123456'])
def test_colors_accept_rgb_and_argb(value):
    validate_color(value)


def test_legacy_missing_color_reports_error(operational_project):
    p = operational_project
    p.save()
    manifest = json.loads(p.manifest_path.read_text(encoding='utf-8'))
    manifest['palette'] = {}
    p.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    path = p.root/'screens/main.json'
    screen = json.loads(path.read_text(encoding='utf-8'))
    screen['background'] = '@missing'
    path.write_text(json.dumps(screen), encoding='utf-8')
    with pytest.raises(ValueError, match='@missing'):
        Project.load(p.root)
