"""Serializable visual conditions; shared by runtime and isolated preview."""
import copy
import operator
import re
from .i18n import tr

OPS={'eq':operator.eq,'ne':operator.ne,'gt':operator.gt,'ge':operator.ge,'lt':operator.lt,'le':operator.le}
COLOR_KEYS={'color','text_color','border_color','stroke_color'}
STYLE_KEYS=COLOR_KEYS|{'text','source'}


def style_keys(kind):
    if kind in {'text','input','button','text_list'}:return {'color','text_color','border_color','text'}
    if kind in {'rectangle','ellipse'}:return {'stroke_color','color'}
    if kind in {'pipe','line','polyline'}:return {'stroke_color'}
    if kind=='image':return {'source'}
    if kind in {'lamp','bar','gauge'}:return {'color'}
    return set()


def resolve_color(value, palette):
    if isinstance(value,str) and value.startswith('@'):
        if value[1:] not in palette: raise ValueError(tr("Color de paleta inexistente: {value}", value=value))
        return palette[value[1:]]
    return value


def validate_color(value,palette):
    value=resolve_color(value,palette)
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?',value):
        raise ValueError(tr('Usa un color HEX #RRGGBB, #AARRGGBB o una referencia @paleta'))


def test(condition,samples):
    if not condition: return True
    sample=samples.get(condition['tag'])
    if sample is None or sample.quality!='good': return condition.get('bad',False)
    try: return OPS[condition['op']](sample.value,condition['value'])
    except (TypeError,ValueError): return False


def permitted(element,samples,key):
    if key=='visible' and not element.get('visible',True): return False
    conditions=[element.get('dynamics',{}).get(key)]
    conditions.extend(g.get(key) for g in element.get('_guards',[]))
    return all(test(c,samples) for c in conditions)


def effective(element,samples,palette,design=False):
    result=dict(element); dynamics=element.get('dynamics',{})
    if not design:
        appearance={}
        result.update(dynamics.get('default',{}))
        appearance.update(dynamics.get('default',{}))
        for state in dynamics.get('states',[]):
            if test(state['when'],samples):
                result.update(state['style']); appearance.update(state['style']); break
        referenced=[element.get('tag')]+[s['when']['tag'] for s in dynamics.get('states',[])]
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
    for key in COLOR_KEYS|{'lamp_color'}:
        if key in result: result[key]=resolve_color(result[key],palette)
    return result


def resolve_bindings(element,bindings):
    result=copy.deepcopy(element)
    def replace(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='tag' and isinstance(item,str) and item.startswith('$'): value[key]=bindings[item[1:]]
                else: replace(item)
        elif isinstance(value,list):
            for item in value: replace(item)
    replace(result); return result


def validate(element,tags,parameters,palette):
    from .project import coerce
    kinds={name:t['type'] for name,t in tags.items()}|{'$'+key:value for key,value in parameters.items()}
    def condition(c):
        if not isinstance(c,dict) or set(c)-{'tag','op','value','bad'} or c.get('tag') not in kinds or c.get('op') not in OPS:
            raise ValueError(tr('Condición inválida: revisa variable y operador'))
        kind=kinds[c['tag']]
        if kind not in {'int','float'} and c['op'] not in {'eq','ne'}: raise ValueError(tr('Ese tipo solo admite igual o distinto'))
        if 'value' not in c or coerce(c['value'],kind)!=c['value']: raise ValueError(tr('Valor de condición incompatible'))
        if not isinstance(c.get('bad',False),bool): raise ValueError(tr('Comportamiento de mala calidad inválido'))
    def style(s):
        if not isinstance(s,dict) or set(s)-style_keys(element['kind']): raise ValueError(tr('Propiedad de apariencia no aplicable a este objeto'))
        for key,value in s.items():
            if not isinstance(value,str): raise ValueError(tr('La apariencia necesita textos o colores'))
            if key in COLOR_KEYS: validate_color(value,palette)
    d=element.get('dynamics',{})
    if not isinstance(d,dict) or set(d)-{'visible','enabled','states','default','bad','disabled','disabled_reason'}: raise ValueError(tr('Dinámica visual desconocida'))
    for key in ('visible','enabled'):
        if key in d: condition(d[key])
    if not isinstance(d.get('disabled_reason',''),str): raise ValueError(tr('Motivo de bloqueo inválido'))
    for key in ('default','bad','disabled'):
        if key in d: style(d[key])
    states=d.get('states',[])
    if not isinstance(states,list) or len(states)>128: raise ValueError(tr('Máximo 128 estados por objeto'))
    for state in states:
        if not isinstance(state,dict) or set(state)!={'when','style'}: raise ValueError(tr('Estado inválido'))
        condition(state['when']); style(state['style'])
    for color in element.get('lamp_colors',{}).values(): validate_color(color,palette)
    if set(element.get('lamp_colors',{}))-{'on','off','bad'}: raise ValueError(tr('Estado de piloto desconocido'))
    for key in COLOR_KEYS:
        if key in element and element[key].startswith('@'): validate_color(element[key],palette)
    for key in ('visible','editor_locked','editor_hidden'):
        if key in element and not isinstance(element[key],bool): raise ValueError(tr("{key} debe ser booleano", key=key))
    for key in ('group','description'):
        if key in element and not isinstance(element[key],str): raise ValueError(tr("{key} debe ser texto", key=key))


def writable_control(element):
    return element['kind']=='input' or (element['kind']=='button' and element.get('action','toggle') in {'toggle','set','momentary','press_release'})


def compatible(element,tag):
    if element['kind']=='lamp' and tag['type']!='bool': return False
    if element['kind'] in {'bar','gauge'} and tag['type'] not in {'float','int'}: return False
    if element.get('action')=='momentary' and tag['type']!='bool': return False
    return not writable_control(element) or tag.get('writable',False)


def issues(project):
    known={'id','kind','x','y','w','h','text','tag','font_size','bold','text_align','text_color','border_color','color','unit','decimals','min','max','action','value','screen','modal','target_container','script','source','view','template','bindings','points','stroke_color','stroke_width','stroke_style','arrows','filled','texts','default_text','dynamics','lamp_colors','visible','editor_locked','editor_hidden','group','description','press_value','release_value','gauge_style','warning','alarm','title','window','permission'}
    result=[]
    for collection in (project.screens,project.faceplates):
        for name,document in collection.items():
            for e in document['elements']:
                if writable_control(e) and not e.get('tag'): result.append(tr("{name} / {id}: mando sin variable", name=name, id=e["id"]))
                for key in sorted(set(e)-known): result.append(tr("{name} / {id}: propiedad no reconocida «{key}»", name=name, id=e["id"], key=key))
    return result


def parameter_writable(template,parameter):
    return any(e.get("tag")=="$"+parameter and writable_control(e) for e in template["elements"])
