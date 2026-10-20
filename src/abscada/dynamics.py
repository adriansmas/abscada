"""Serializable visual conditions; shared by runtime and isolated preview."""
import copy
import math
import operator
import re
import time
from .i18n import tr
from .project_languages import is_text

OPS={'eq':operator.eq,'ne':operator.ne,'gt':operator.gt,'ge':operator.ge,'lt':operator.lt,'le':operator.le}
COLOR_KEYS={'color','text_color','border_color','stroke_color'}
# Motion and level are painted over the element, which keeps its place and size.
ROTATABLE={'image','rectangle','ellipse','line','polyline','pipe','text','lamp'}
FILLABLE={'image','rectangle','ellipse'}
MOVABLE=ROTATABLE|{'bar','gauge','text_list'}
FORMATTED={'text','input','gauge'}     # unit and decimals may come from variables
ANCHORS=('center','top','bottom','left','right')
MAX_CONDITIONS=16
DIRECTIONS=('up','down','left','right')
FILL_COLOR='#cc3da9bf'
BLINK_HZ=1.0


def style_keys(kind):
    if kind in {'text','input','button','text_list'}:return {'color','text_color','border_color','text'}
    if kind in {'rectangle','ellipse'}:return {'stroke_color','color'}
    if kind in {'pipe','line','polyline'}:return {'stroke_color'}
    if kind=='image':return {'source'}
    if kind in {'lamp','bar','gauge'}:return {'color'}
    return set()


def validate_color(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?',value):
        raise ValueError(tr('Usa un color HEX #RRGGBB o #AARRGGBB'))


def conditions(condition):
    """The single conditions of a condition: a list means all of them (AND)."""
    if not condition: return []
    return list(condition) if isinstance(condition,list) else [condition]


def test(condition,samples):
    if not condition: return True
    if isinstance(condition,list): return all(test(c,samples) for c in condition)
    sample=samples.get(condition['tag'])
    if sample is None or sample.quality!='good': return condition.get('bad',False)
    try: return OPS[condition['op']](sample.value,condition['value'])
    except (TypeError,ValueError): return False


def permitted(element,samples,key):
    if key=='visible' and not element.get('visible',True): return False
    conditions=[element.get('dynamics',{}).get(key)]
    conditions.extend(g.get(key) for g in element.get('_guards',[]))
    return all(test(c,samples) for c in conditions)


def blink_on(now=None):
    """Phase shared by every blinking state, so they all blink in step."""
    now=time.monotonic() if now is None else now
    return int(now*2*BLINK_HZ)%2==0


def ratio(spec,samples):
    """Position of a variable between min and max (0..1); the last value if its quality is bad."""
    sample=samples.get(spec['tag'])
    try: value=float(sample.value)
    except (AttributeError,TypeError,ValueError): return 0.0
    if not math.isfinite(value): return 0.0
    return max(0.0,min(1.0,(value-spec.get('min',0))/(spec.get('max',100)-spec.get('min',0))))


def motion_tags(dynamics):
    specs=[dynamics.get(key) for key in ('rotation','fill','move','scale')]
    return [spec['tag'] for spec in specs if spec]+([c['tag'] for c in conditions(dynamics['spin']['when'])] if dynamics.get('spin') else [])


def animated(element):
    """Needs repainting as time passes: blinking states or continuous rotation."""
    dynamics=element.get('dynamics',{})
    return bool(dynamics.get('spin')) or any(state.get('blink') for state in dynamics.get('states',[]))


def effective(element,samples,design=False,now=None):
    result=dict(element); dynamics=element.get('dynamics',{})
    if not design:
        appearance={}
        now=time.monotonic() if now is None else now
        result.update(dynamics.get('default',{}))
        appearance.update(dynamics.get('default',{}))
        for state in dynamics.get('states',[]):
            if test(state['when'],samples):
                # A blinking state alternates its appearance with the normal one.
                if not state.get('blink') or blink_on(now):
                    result.update(state['style']); appearance.update(state['style'])
                break
        angle=0.0
        if dynamics.get('rotation'):
            spec=dynamics['rotation']; angle+=spec.get('from',0)+ratio(spec,samples)*(spec.get('to',360)-spec.get('from',0))
        if dynamics.get('spin') and test(dynamics['spin']['when'],samples):
            angle+=(now/dynamics['spin'].get('seconds',2)*360)%360
        if angle: result['_angle']=angle
        if dynamics.get('fill'):
            spec=dynamics['fill']; result['_fill']=(ratio(spec,samples),spec.get('color',FILL_COLOR),spec.get('direction','up'))
        if dynamics.get('move'):
            spec=dynamics['move']; position=ratio(spec,samples)
            offset=(spec.get('x',0)*position,spec.get('y',0)*position)
            if any(offset): result['_offset']=offset
        if dynamics.get('scale'):
            spec=dynamics['scale']; factor=spec.get('from',1)+ratio(spec,samples)*(spec.get('to',2)-spec.get('from',1))
            axis=spec.get('axis','both')
            result['_scale']=(factor if axis!='y' else 1.0, factor if axis!='x' else 1.0, spec.get('anchor','center'))
        for key,kind in (('unit',str),('decimals',int)):
            source=samples.get(dynamics.get(key,{}).get('tag'))
            if source is not None and source.quality=='good':
                result[key]=str(source.value) if kind is str else max(0,min(10,int(source.value)))
        referenced=[element.get('tag')]+[c['tag'] for s in dynamics.get('states',[]) for c in conditions(s['when'])]+motion_tags(dynamics)
        if any(name and (name not in samples or samples[name].quality!='good') for name in referenced):
            result.update(dynamics.get('bad',{}))
            appearance.update(dynamics.get('bad',{}))
        if not permitted(element,samples,'enabled'):
            result.update(dynamics.get('disabled',{}));appearance.update(dynamics.get('disabled',{}))
        if 'text' in appearance:result['_text_override']=True
        if element['kind']=='lamp':
            sample=samples.get(element.get('tag'))
            state='bad' if sample is None or sample.quality!='good' else 'on' if sample.value else 'off'
            result['lamp_color']=element.get('lamp_colors',{}).get(state,{'bad':'#e5a339','on':'#14b889','off':'#d7e0e9'}[state])
            if 'color' in appearance: result['lamp_color']=appearance['color']
    return result


def resolve_bindings(element,bindings):
    from .structures import substitute
    result=copy.deepcopy(element)
    def replace(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='tag' and isinstance(item,str) and '$' in item: value[key]=substitute(item,bindings)
                else: replace(item)
        elif isinstance(value,list):
            for item in value: replace(item)
    replace(result); return result


def validate(element,tags,parameters):
    from .project import coerce
    kinds={name:t['type'] for name,t in tags.items()}|{'$'+key:value for key,value in parameters.items()}
    def condition(c):
        if isinstance(c,list):
            # Several conditions that must all hold (AND).
            if not 1<=len(c)<=MAX_CONDITIONS: raise ValueError(tr('Entre 1 y {count} condiciones a la vez', count=MAX_CONDITIONS))
            for item in c: condition(item)
            return
        if not isinstance(c,dict) or set(c)-{'tag','op','value','bad'} or c.get('tag') not in kinds or c.get('op') not in OPS:
            raise ValueError(tr('Condición inválida: revisa variable y operador'))
        kind=kinds[c['tag']]
        if kind not in {'int','float'} and c['op'] not in {'eq','ne'}: raise ValueError(tr('Ese tipo solo admite igual o distinto'))
        if 'value' not in c or coerce(c['value'],kind)!=c['value']: raise ValueError(tr('Valor de condición incompatible'))
        if not isinstance(c.get('bad',False),bool): raise ValueError(tr('Comportamiento de mala calidad inválido'))
    def style(s):
        if not isinstance(s,dict) or set(s)-style_keys(element['kind']): raise ValueError(tr('Propiedad de apariencia no aplicable a este objeto'))
        for key,value in s.items():
            if not (is_text(value) if key == 'text' else isinstance(value, str)): raise ValueError(tr('La apariencia necesita textos o colores'))
            if key in COLOR_KEYS: validate_color(value)
    def number(value,message):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError(message)
    def analog(spec,keys):
        if not isinstance(spec,dict) or set(spec)-keys or spec.get('tag') not in kinds: raise ValueError(tr('Indica una variable numérica'))
        if kinds[spec['tag']] not in {'int','float'}: raise ValueError(tr('El giro, el llenado, el desplazamiento y la escala necesitan una variable numérica'))
        for key in keys-{'tag','color','direction','axis','anchor'}:
            if key in spec: number(spec[key],tr('{key}: se esperaba un número', key=key))
        if not spec.get('min',0)<spec.get('max',100): raise ValueError(tr('El máximo debe ser mayor que el mínimo'))
    d=element.get('dynamics',{})
    if not isinstance(d,dict) or set(d)-{'visible','enabled','states','default','bad','disabled','disabled_reason','rotation','spin','fill','move','scale','unit','decimals'}: raise ValueError(tr('Dinámica visual desconocida'))
    if ('move' in d or 'scale' in d) and element['kind'] not in MOVABLE: raise ValueError(tr('Este objeto no admite desplazamiento ni escala'))
    if 'move' in d: analog(d['move'],{'tag','min','max','x','y'})
    if 'scale' in d:
        analog(d['scale'],{'tag','min','max','from','to','axis','anchor'})
        if not all(0<=d['scale'].get(key,default)<=20 for key,default in (('from',1),('to',2))): raise ValueError(tr('La escala va de 0 a 20'))
        if d['scale'].get('axis','both') not in ('both','x','y') or d['scale'].get('anchor','center') not in ANCHORS: raise ValueError(tr('Eje o punto fijo de escala desconocido'))
    for key,kind in (('unit','string'),('decimals','int')):
        if key in d:
            if element['kind'] not in FORMATTED: raise ValueError(tr('Solo textos, entradas e indicadores toman unidad y decimales de una variable'))
            if not isinstance(d[key],dict) or set(d[key])!={'tag'} or kinds.get(d[key]['tag'])!=kind:
                raise ValueError(tr('La unidad necesita una variable de texto y los decimales una entera'))
    if ('rotation' in d or 'spin' in d) and element['kind'] not in ROTATABLE: raise ValueError(tr('Este objeto no admite giro'))
    if 'fill' in d and element['kind'] not in FILLABLE: raise ValueError(tr('Solo imágenes, rectángulos y elipses admiten nivel de llenado'))
    if 'rotation' in d: analog(d['rotation'],{'tag','min','max','from','to'})
    if 'spin' in d:
        if not isinstance(d['spin'],dict) or set(d['spin'])-{'when','seconds'} or 'when' not in d['spin']: raise ValueError(tr('Giro continuo inválido'))
        condition(d['spin']['when']); number(d['spin'].get('seconds',2),tr('Duración de vuelta inválida'))
        if not 0.2<=d['spin'].get('seconds',2)<=3600: raise ValueError(tr('Una vuelta debe durar entre 0,2 y 3600 segundos'))
    if 'fill' in d:
        analog(d['fill'],{'tag','min','max','color','direction'})
        validate_color(d['fill'].get('color',FILL_COLOR))
        if d['fill'].get('direction','up') not in DIRECTIONS: raise ValueError(tr('Dirección de llenado desconocida'))
    for key in ('visible','enabled'):
        if key in d: condition(d[key])
    if not is_text(d.get('disabled_reason','')): raise ValueError(tr('Motivo de bloqueo inválido'))
    for key in ('default','bad','disabled'):
        if key in d: style(d[key])
    states=d.get('states',[])
    if not isinstance(states,list) or len(states)>128: raise ValueError(tr('Máximo 128 estados por objeto'))
    for state in states:
        if not isinstance(state,dict) or not {'when','style'}<=set(state)<={'when','style','blink'} or not isinstance(state.get('blink',False),bool): raise ValueError(tr('Estado inválido'))
        condition(state['when']); style(state['style'])
    for color in element.get('lamp_colors',{}).values(): validate_color(color)
    if set(element.get('lamp_colors',{}))-{'on','off','bad'}: raise ValueError(tr('Estado de piloto desconocido'))
    for key in COLOR_KEYS:
        if key in element: validate_color(element[key])
    for key in ('visible','editor_locked','editor_hidden'):
        if key in element and not isinstance(element[key],bool): raise ValueError(tr("{key} debe ser booleano", key=key))
    for key in ('group','description'):
        if key in element and not (is_text(element[key]) if key == 'description' else isinstance(element[key], str)): raise ValueError(tr("{key} debe ser texto", key=key))


def writable_control(element):
    return element['kind']=='input' or (element['kind']=='button' and element.get('action','toggle') in {'toggle','set','momentary','press_release'})


def compatible(element,tag):
    if element['kind']=='lamp' and tag['type']!='bool': return False
    if element['kind'] in {'bar','gauge'} and tag['type'] not in {'float','int'}: return False
    if element.get('action')=='momentary' and tag['type']!='bool': return False
    return not writable_control(element) or tag.get('writable',False)


# Every property an element may store; anything else is reported (Studio) or refused (validate_library).
KNOWN_PROPERTIES={'id','kind','x','y','w','h','text','tag','font_size','bold','text_align','text_color','border_color','color','unit','decimals','min','max','action','value','screen','modal','target_container','script','source','view','template','bindings','points','stroke_color','stroke_width','stroke_style','arrows','filled','texts','default_text','dynamics','lamp_colors','visible','editor_locked','editor_hidden','group','description','press_value','release_value','gauge_style','warning','alarm','title','window','permission','language','tooltip','actions','variants'}


def issues(project):
    known=KNOWN_PROPERTIES
    from .button_actions import as_button, steps
    result=[]
    for collection in (project.screens,project.faceplates):
        for name,document in collection.items():
            for e in document['elements']:
                if e['kind']=='button' and e.get('action')=='sequence' and not e.get('actions'): result.append(tr("{name} / {id}: botón sin acciones", name=name, id=e["id"]))
                for c in [e]+[as_button(e,s) for s in steps(e)]:
                    if writable_control(c) and not c.get('tag'): result.append(tr("{name} / {id}: mando sin variable", name=name, id=e["id"]))
                    loose=[p for p,v in c.get('bindings',{}).items() if v=='']
                    if loose: result.append(tr("{name} / {id}: parámetros sin variable asignada: {parameters}", name=name, id=e["id"], parameters=', '.join(loose)))
                for key in sorted(set(e)-known): result.append(tr("{name} / {id}: propiedad no reconocida «{key}»", name=name, id=e["id"], key=key))
    return result


def written_references(template):
    """``$`` references (without the $) written by the template's controls."""
    from .button_actions import as_button, steps
    controls=[c for e in template["elements"] for c in [e]+[as_button(e,s) for s in steps(e)]]
    return {c["tag"][1:] for c in controls if isinstance(c.get("tag"),str) and c["tag"].startswith("$") and writable_control(c)}


def parameter_writable(template,parameter):
    """Some control writes the parameter or, for a structure or array, one of its parts."""
    from .structures import root
    return any(root(reference)==parameter for reference in written_references(template))


def index_values(names,samples):
    """Current value of each variable used as an index; None if it has no valid integer."""
    result={}
    for name in names:
        sample=samples.get(name)
        try: result[name]=int(sample.value) if sample is not None and sample.quality=='good' and not isinstance(sample.value,str) else None
        except (TypeError,ValueError): result[name]=None
    return result


def resolve_indices(elements,samples):
    """Elements with each variable index (``Juegos[Sel].Temp``) set to its current value.

    Returns the elements and the index values used, so the screen is drawn again when one
    changes. Pop-up bindings keep their index: the window they open follows it on its own.
    """
    from .structures import index_tags, resolve_indices as resolve
    elements=[copy.deepcopy(e) for e in elements]
    names=set()
    def collect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='tag' and isinstance(item,str): names.update(index_tags(item))
                elif key!='bindings': collect(item)
        elif isinstance(value,list):
            for item in value: collect(item)
    for element in elements: collect(element)
    if not names: return elements,{}
    values=index_values(names,samples)
    def apply(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='tag' and isinstance(item,str) and index_tags(item): value[key]=resolve(item,values) or ''
                elif key!='bindings': apply(item)
        elif isinstance(value,list):
            for item in value: apply(item)
    for element in elements: apply(element)
    return elements,values
