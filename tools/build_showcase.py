"""Build the documented SCADA feature laboratory in a new project directory."""
from pathlib import Path
import argparse
from abscada.project import Project
from abscada.drawing import set_points


def build_project(root):
    root=Path(root).resolve()
    if (root/'project.json').exists():raise ValueError('El proyecto ya existe; usa otra carpeta para no sobrescribir cambios')
    palette={'Fondo':'#f4f7fa','Panel':'#ffffff','Texto':'#243c50','Marcha':'#147d75','Paro':'#c64b51','Aviso':'#da982f','S7':'#3678c8','Modbus':'#8152b4','Linea':'#7c94a5'}
    p=Project(root,dict(schema_version=1,name='Laboratorio SCADA',startup_screen='00_layout',palette=palette),{},[],[],{}, {})
    p.types={
        'Bomba':{'Marcha':'bool','Caudal':'float','Consigna':'float'},
        'PlantaS7':{'Bomba1':'Bomba','Bomba2':'Bomba','Nivel':'float'},
        'EquipoModbus':{'Habilitar':'bool','Listo':'bool','Consigna':'float','Temperatura':'float','Contador':'int','Modo':'int'},
        'BancoLocal':{'Marcha':'bool','Permiso':'bool','Generador':'bool','Fallo':'bool','Pulsador':'bool','Orden':'int','Modo':'int','Consigna':'float','Nivel':'float','Temperatura':'float','SinRegistro':'float','Texto':'string'},
        'Sesion':{'Operador':'string','Ciclos':'int','Aperturas':'int','UltimoEvento':'string','Inicio':'string','Hora':'string','S7':'string','Modbus':'string'}}
    p.connections=[dict(id='S7_Laboratorio',protocol='s7',host='127.0.0.1',port=1102,rack=0,slot=1,poll_ms=250),
                   dict(id='Modbus_Laboratorio',protocol='modbus_tcp',host='127.0.0.1',port=1502,unit_id=1,timeout_ms=800,poll_ms=500)]
    # Protocol key is looked up from the installed registry rather than assumed.
    from abscada.connectors import REGISTRY
    p.connections[1]['protocol']=next(k for k,v in REGISTRY.items() if v.definition.label=='Modbus TCP')
    s7bindings={}
    for motor,offset in [('Bomba1',0),('Bomba2',16)]:
        for field,address in [('Marcha',f'%DB1.DBX{offset}.0'),('Caudal',f'%DB1.DBD{offset+4}'),('Consigna',f'%DB1.DBD{offset+8}')]:
            s7bindings[f'Siemens.{motor}.{field}']=dict(connection='S7_Laboratorio',address=address)
    s7bindings['Siemens.Nivel']=dict(connection='S7_Laboratorio',address='%DB1.DBD12')
    mb={}
    for field,area,offset,encoding in [('Habilitar','coils',0,'bool'),('Listo','discrete_inputs',0,'bool'),('Consigna','holding_registers',0,'float32'),('Temperatura','input_registers',0,'float32'),('Contador','input_registers',2,'uint32'),('Modo','holding_registers',2,'uint16')]:
        address=dict(area=area,offset=offset,encoding=encoding)
        if encoding!='bool':address.update(byte_order='big',word_order='big')
        mb['Modbus.'+field]=dict(connection='Modbus_Laboratorio',version=1,address=address)
    p.variables=[
        dict(name='Local',type='BancoLocal',initial=dict(Marcha=False,Permiso=True,Generador=False,Fallo=False,Pulsador=False,Orden=0,Modo=0,Consigna=55.,Nivel=35.,Temperatura=24.,SinRegistro=0.,Texto='Lote de demostración'),writable=True),
        dict(name='Sistema',type='Sesion',initial=dict(Operador='Operador demo',Ciclos=0,Aperturas=0,UltimoEvento='Sin eventos',Inicio='',Hora='',S7='Sin lectura',Modbus='Sin lectura'),writable=True),
        dict(name='Siemens',type='PlantaS7',initial=dict(Bomba1=dict(Marcha=False,Caudal=0.,Consigna=60.),Bomba2=dict(Marcha=False,Caudal=0.,Consigna=45.),Nivel=0.),writable=True,
             overrides={'Bomba1.Caudal':{'writable':False},'Bomba2.Caudal':{'writable':False},'Nivel':{'writable':False}},bindings=s7bindings),
        dict(name='Modbus',type='EquipoModbus',initial=dict(Habilitar=False,Listo=False,Consigna=40.,Temperatura=0.,Contador=0,Modo=0),writable=True,
             overrides={name:{'writable':False} for name in ['Listo','Temperatura','Contador']},bindings=mb)]

    def elem(doc,kind,identifier,x,y,w,h,**data):
        result=dict(id=identifier,kind=kind,x=x,y=y,w=w,h=h,**data);doc['elements'].append(result);return result
    def text(doc,identifier,title,x,y,w=500,h=32,**data):return elem(doc,'text',identifier,x,y,w,h,text=title,font_size=16,text_align='left',text_color='@Texto',**data)
    def title(doc,name,subtitle):
        e=text(doc,'title',name,30,22,1090,44);e.update(font_size=28,bold=True)
        e=text(doc,'subtitle',subtitle,30,72,1090,48);e.update(font_size=14,text_color='#63768b')
    def page(key,name,subtitle):
        doc=dict(title=name,width=1160,height=770,background='@Fondo',grid_size=10,show_grid=True,snap_to_grid=True,elements=[],on_open=['screen_open'])
        p.screens[key]=doc;title(doc,name,subtitle);return doc
    def button(doc,identifier,label,x,y,tag=None,action='toggle',w=210,**data):
        result=elem(doc,'button',identifier,x,y,w,42,text=label,action=action,font_size=15,**data)
        if tag:result['tag']=tag
        return result
    def value(doc,identifier,label,tag,x,y,w=260,unit='',kind='text',**data):
        return elem(doc,kind,identifier,x,y,w,44,text=label,tag=tag,unit=unit,decimals=1,text_align='left',color='#ffffff',text_color='@Texto',**data)
    def lamp(doc,identifier,tag,x,y):return elem(doc,'lamp',identifier,x,y,44,44,tag=tag,lamp_colors=dict(on='@Marcha',off='#d7e0e9',bad='@Aviso'))
    def condition(tag,value,op='eq'):return dict(tag=tag,op=op,value=value,bad=False)
    def nav(doc,key,label,x,y,w=240):return button(doc,'nav_'+key,label,x,y,action='screen',screen=key,target_container='contenido',w=w)
    def card(doc,identifier,x,y,w,h):return elem(doc,'rectangle',identifier,x,y,w,h,color='@Panel',stroke_color='#dce5ed',stroke_width=1,filled=True,editor_locked=True)
    def path(doc,kind,identifier,points,**data):
        e=dict(id=identifier,kind=kind,stroke_color='@Linea',stroke_width=12 if kind=='pipe' else 3);e.update(data);set_points(e,points);doc['elements'].append(e);return e

    navigation=[('10_inicio','01 · Recorrido'),('20_internas','02 · Proceso interno'),('21_estados','03 · Estados y mandos'),('22_dibujo','04 · Dibujo e imágenes'),('23_faceplates','05 · Faceplates y ventanas'),('30_siemens','06 · Siemens S7'),('31_modbus','07 · Modbus TCP'),('40_graficas','08 · Gráficas en vivo'),('41_historicos','09 · Histórico diario'),('50_alarmas','10 · Alarmas y ACK'),('51_eventos','11 · Eventos y retorno'),('60_scripts','12 · Scripts y tareas')]
    p.screens['00_layout']=dict(title='Laboratorio SCADA',width=1360,height=850,layout=True,background='@Fondo',elements=[
        dict(id='cabecera',kind='screen_container',x=0,y=0,w=1360,h=80,screen='01_cabecera'),
        dict(id='menu',kind='screen_container',x=0,y=80,w=200,h=770,screen='02_menu'),
        dict(id='contenido',kind='screen_container',x=200,y=80,w=1160,h=770,screen='10_inicio')])
    header=dict(title='Cabecera compartida',width=1360,height=80,background='#183445',elements=[]);p.screens['01_cabecera']=header
    e=text(header,'brand','abSCADA / LABORATORIO',24,20,535,40);e.update(font_size=25,bold=True,text_color='#ffffff')
    e=text(header,'operator','',600,21,350,38,tag='Sistema.Operador');e.update(text_color='#ffffff',color='#183445')
    e=text(header,'clock','',1000,21,335,38,tag='Sistema.Hora');e.update(text_color='#ffffff',color='#183445')
    menu=dict(title='Navegación compartida',width=200,height=770,background='#ffffff',elements=[]);p.screens['02_menu']=menu
    for i,(key,label) in enumerate(navigation):nav(menu,key,label,10,15+i*45,180)
    e=text(menu,'status_title','COMUNICACIONES',14,562,172,26);e['font_size']=12
    for i,(label,tag) in enumerate([('S7','Sistema.S7'),('Modbus','Sistema.Modbus')]):
        e=text(menu,'status_'+str(i),label,12,592+i*59,176,50,tag=tag);e['font_size']=12
    button(menu,'help','Mapa y ayuda',10,716,action='popup',screen='91_ayuda',w=180)

    d=page('10_inicio','Laboratorio SCADA','Un proyecto completo, dividido por función. Las pantallas de equipos usan conexiones TCP independientes.')
    for i,(name,desc,keys) in enumerate([
        ('SIN EQUIPOS','Variables internas, estados visuales, alarmas y scripts.',navigation[1:5]),
        ('COMUNICACIONES','S7: DB1 · Modbus: coils y registros. Calidad real de lectura.',navigation[5:7]),
        ('DATOS Y OPERACIÓN','Curvas, archivos diarios, reconocimiento y eventos.',navigation[7:11])]):
        x=30+i*375;card(d,'card'+str(i),x,140,345,415);e=text(d,'head'+str(i),name,x+20,158,305,40);e['bold']=True
        text(d,'desc'+str(i),desc,x+20,210,305,66)
        for j,(key,label) in enumerate(keys):nav(d,key,label,x+20,300+j*56,305)
    text(d,'start','Empieza en «Proceso interno». Activa la señal local para generar curvas; las variables PLC nunca se sustituyen por valores locales.',30,588,1090,62)
    nav(d,'60_scripts','Ver scripts y tareas',30,682,280)
    button(d,'popup','Configuración modal',335,682,action='popup',screen='90_ajustes',modal=True,w=280)
    button(d,'window','Pantalla completa',640,682,action='screen',screen='92_completa',target_container='__window__',w=280)

    d=page('20_internas','Proceso con variables internas','Los mandos y valores son locales. «Señal local» activa una tarea de ejemplo; no interviene en S7 ni Modbus.')
    card(d,'process',30,140,640,505);card(d,'controls',695,140,435,505)
    path(d,'pipe','inlet',[[75,330],[190,330],[190,240],[335,240]],arrows='end')
    path(d,'pipe','outlet',[[465,460],[565,460],[565,545],[630,545]],arrows='end')
    elem(d,'ellipse','pump',115,290,80,80,color='#ffffff',stroke_color='@S7',stroke_width=3,filled=True,group='bomba_local')
    path(d,'line','pump_line',[[128,302],[180,356]],group='bomba_local')
    elem(d,'rectangle','tank',340,230,130,305,color='#edf3f7',stroke_color='@Linea',stroke_width=3,filled=True)
    elem(d,'ellipse','tank_top',340,215,130,30,color='#edf3f7',stroke_color='@Linea',stroke_width=3,filled=True)
    elem(d,'bar','level',360,260,90,248,tag='Local.Nivel',min=0,max=100,dynamics={'states':[dict(when=condition('Local.Nivel',80.,'ge'),style={'color':'@Paro'})],'default':{'color':'@Marcha'},'bad':{'color':'@Aviso'}})
    elem(d,'gauge','temp_gauge',505,150,150,150,tag='Local.Temperatura',min=0,max=60,unit='°C',decimals=1,text='Temperatura',gauge_style='dial',warning=40,alarm=50)
    lamp(d,'running','Local.Marcha',207,305);value(d,'pv','Nivel','Local.Nivel',335,556,280,'%')
    text(d,'tank_label','TK-01',340,166,190,36);value(d,'temp','Temperatura','Local.Temperatura',65,580,250,'°C')
    button(d,'run','Marcha / paro',720,165,'Local.Marcha',w=385)
    button(d,'generator','Señal local: activar / parar',720,222,'Local.Generador',w=385)
    value(d,'sp','Consigna','Local.Consigna',720,292,385,'%',kind='input')
    value(d,'manual_level','Nivel manual','Local.Nivel',720,354,385,'%',kind='input',dynamics={'enabled':condition('Local.Generador',False),'disabled_reason':'Detén la señal local para introducir un nivel manual'})
    value(d,'batch','Lote','Local.Texto',720,416,385,kind='input')
    elem(d,'text_list','run_text',720,482,385,44,tag='Local.Marcha',texts=[{'value':'false','text':'Equipo parado'},{'value':'true','text':'Equipo en marcha'}],default_text='Estado desconocido',color='#ffffff')
    text(d,'use','Doble clic en una entrada para escribir. El nivel > 80 activa una alarma con retardo; los valores se registran cada segundo.',30,675,1090,60)

    d=page('21_estados','Estados, permisos y gestos','Visibilidad, habilitación, colores de paleta, lista de textos y escrituras al pulsar/soltar.')
    for i,name in enumerate(['VISIBILIDAD','PERMISO','PULSACIÓN']):
        card(d,'card'+str(i),30+i*375,145,345,375);e=text(d,'head'+str(i),name,50+i*375,163,300,30);e['bold']=True
    for name,desired in [('MARCHA',True),('PARO',False)]:
        button(d,name,name,60,230,'Local.Marcha',action='set',value=desired,w=285,color='@Marcha' if desired else '@Paro',text_color='#ffffff',dynamics={'visible':condition('Local.Marcha',not desired)})
    lamp(d,'run_status','Local.Marcha',165,303);text(d,'overlap','Dos botones superpuestos. Solo recibe clic el que corresponde al estado.',55,380,285,95)
    button(d,'permit','Habilitar / bloquear permiso',430,230,'Local.Permiso',w=285)
    button(d,'guarded','Orden con permiso',430,298,'Local.Marcha',w=285,dynamics={'enabled':condition('Local.Permiso',True),'disabled_reason':'El permiso local está desactivado','disabled':{'color':'#d4dce4','text_color':'#63768b'}})
    lamp(d,'permit_lamp','Local.Permiso',550,375)
    button(d,'momentary','Mantener pulsado',805,230,'Local.Pulsador',action='momentary',w=285)
    lamp(d,'momentary_status','Local.Pulsador',815,292)
    button(d,'phases','Pulsar: 10 / soltar: 0',805,355,'Local.Orden',action='press_release',press_value=10,release_value=0,w=285)
    value(d,'command','Orden','Local.Orden',805,422,285)
    for i,(label,mode) in enumerate([('Parado',0),('Manual',1),('Automático',2),('Desconocido',9)]):button(d,'mode'+str(i),label,30+i*280,560,'Local.Modo',action='set',value=mode,w=260)
    elem(d,'text_list','mode_text',30,630,535,62,tag='Local.Modo',texts=[dict(value=str(i),text=t) for i,t in enumerate(['Modo parado','Modo manual','Modo automático'])],default_text='Modo no definido',dynamics={'states':[dict(when=condition('Local.Modo',1),style={'color':'@Aviso','text_color':'#ffffff'}),dict(when=condition('Local.Modo',2),style={'color':'@Marcha','text_color':'#ffffff'})],'default':{'color':'#ffffff'}})
    text(d,'palette_note','Colores compartidos: @Marcha, @Paro y @Aviso. Cambia la paleta desde Studio y reinicia Runtime para aplicar.',590,625,525,90)

    d=page('22_dibujo','Dibujo, imágenes y capas','Todos los elementos geométricos. En Studio: Objetos → bloqueo, ocultación, grupos y nombre descriptivo.')
    path(d,'line','line',[[70,200],[470,200]],arrows='both',stroke_color='@S7',stroke_width=4)
    path(d,'polyline','polyline',[[70,290],[210,240],[350,310],[490,250]],stroke_color='@Modbus',stroke_width=4,stroke_style='dash')
    path(d,'pipe','pipe',[[75,420],[230,420],[230,350],[480,350]],arrows='end',dynamics={'states':[dict(when=condition('Local.Marcha',True),style={'stroke_color':'@Marcha'})]})
    elem(d,'rectangle','rect',70,515,170,90,color='@S7',stroke_color='#1c4568',stroke_width=3,filled=True,group='formas')
    elem(d,'ellipse','ellipse',290,515,170,90,color='@Modbus',stroke_color='#59327f',stroke_width=3,filled=True,group='formas')
    card(d,'image_panel',575,140,550,470)
    elem(d,'image','valve',675,200,350,210,source='assets/valve-off.svg',dynamics={'states':[dict(when=condition('Local.Marcha',True),style={'source':'assets/valve-on.svg'})]})
    button(d,'image_state','Cambiar estado de válvula',690,470,'Local.Marcha',w=320)
    text(d,'image_label','Imagen SVG que cambia por condición',655,550,410,38)
    elem(d,'text','hidden_example',75,655,1000,42,text='Este texto está oculto solo en diseño; sí aparece en Runtime.',font_size=16,editor_hidden=True,description='Ejemplo de ocultación exclusiva de Studio')

    template=dict(title='Unidad reutilizable',width=500,height=260,background='#ffffff',parameters={'run':'bool','pv':'float','sp':'float'},elements=[])
    text(template,'heading','UNIDAD PARAMETRIZADA',18,12,465,32)
    lamp(template,'lamp','$run',22,57);value(template,'pv','PV','$pv',88,59,390,'u')
    value(template,'sp','SP','$sp',25,121,450,'u',kind='input')
    button(template,'command','Marcha / paro',25,190,'$run',w=280)
    elem(template,'text_list','status',315,190,160,42,tag='$run',texts=[dict(value='true',text='MARCHA'),dict(value='false',text='PARADO')],default_text='—')
    p.faceplates['unidad']=template
    d=page('23_faceplates','Faceplates, contenedores y emergentes','La misma plantilla con parámetros diferentes: una unidad interna y otra conectada a Siemens.')
    for i,(name,bindings) in enumerate([('INTERNA',dict(run='Local.Marcha',pv='Local.Nivel',sp='Local.Consigna')),('SIEMENS',dict(run='Siemens.Bomba1.Marcha',pv='Siemens.Bomba1.Caudal',sp='Siemens.Bomba1.Consigna'))]):
        x=30+i*565;text(d,'name'+str(i),name,x,147,520,30);elem(d,'faceplate','unit'+str(i),x,195,530,280,template='unidad',bindings=bindings)
    button(d,'nonmodal','Abrir ajustes no modales',30,540,action='popup',screen='90_ajustes',w=350)
    button(d,'modal','Abrir ayuda modal',405,540,action='popup',screen='91_ayuda',modal=True,w=350)
    text(d,'layout_note','La cabecera y el menú permanecen en sus contenedores. Los botones del menú navegan solo en «contenido». Las emergentes comparten adquisición y variables.',30,620,1090,96)

    d=page('30_siemens','Siemens S7 · DB1','S7_Laboratorio · 127.0.0.1:1102 · rack 0 / slot 1 · adquisición cada 250 ms.')
    for i,motor in enumerate(['Bomba1','Bomba2']):
        x=30+i*565;text(d,'label'+str(i),motor,x,145,500,32)
        elem(d,'faceplate','s7unit'+str(i),x,195,530,280,template='unidad',bindings=dict(run=f'Siemens.{motor}.Marcha',pv=f'Siemens.{motor}.Caudal',sp=f'Siemens.{motor}.Consigna'))
        offset=0 if i==0 else 16;text(d,'map'+str(i),f'Marcha: %DB1.DBX{offset}.0\nCaudal: %DB1.DBD{offset+4} · Consigna: %DB1.DBD{offset+8}',x,510,525,95)
    value(d,'level','Nivel DB1.DBD12','Siemens.Nivel',30,640,420,'%')
    value(d,'quality','S7','Sistema.S7',485,640,615)

    d=page('31_modbus','Modbus TCP · cuatro áreas','Modbus_Laboratorio · 127.0.0.1:1502 · Unit ID 1 · adquisición cada 500 ms · offsets base 0.')
    fields=[('Coil 0','Habilitar','bool','coils[0]',True),('Discrete input 0','Listo','bool','discrete_inputs[0]',False),('Consigna REAL','Consigna','float','holding_registers[0..1] · float32 ABCD',True),('Temperatura REAL','Temperatura','float','input_registers[0..1] · float32 ABCD',False),('Contador DINT','Contador','int','input_registers[2..3] · uint32 ABCD',False),('Modo UINT','Modo','int','holding_registers[2] · uint16',True)]
    for i,(label,field,kind,address,writable) in enumerate(fields):
        x=30+(i%2)*565;y=145+(i//2)*170;card(d,'card'+str(i),x,y,530,145)
        text(d,'label'+str(i),label,x+18,y+10,490,30)
        if kind=='bool':
            lamp(d,'lamp'+str(i),'Modbus.'+field,x+20,y+54)
            if writable:button(d,'write'+str(i),'Habilitar / deshabilitar',x+90,y+56,'Modbus.'+field,w=400)
        else:value(d,'value'+str(i),'','Modbus.'+field,x+20,y+52,490,kind='input' if writable else 'text')
        e=text(d,'address'+str(i),address,x+18,y+106,495,29);e['font_size']=13
    value(d,'quality','Modbus','Sistema.Modbus',30,685,1090)

    p.trends={}
    axes=[dict(id='percent',title='Nivel / consigna (%)',side='left',auto=False,min=0,max=100,visible=True),dict(id='temperature',title='Temperatura (°C)',side='right',auto=True,min=0,max=100,visible=True),dict(id='digital',title='Marcha',side='right',auto=False,min=0,max=1,visible=False)]
    def curve(identifier,tag,axis,color,width=2,visible=True):return dict(id=identifier,tag=tag,axis=axis,color=color,width=width,visible=visible)
    p.trends['local']=dict(title='Variables internas registradas',window_seconds=600,axes=axes,curves=[curve('level','Local.Nivel','percent','#147d75',3),curve('sp','Local.Consigna','percent','#3678c8'),curve('temp','Local.Temperatura','temperature','#da982f'),curve('run','Local.Marcha','digital','#8152b4',1,False)])
    p.trends['online_only']=dict(title='Señal en vivo sin registro',window_seconds=120,axes=[dict(id='y',title='Señal local',side='left',auto=True,min=-1,max=1,visible=True)],curves=[curve('live','Local.SinRegistro','y','#8152b4',3)])
    p.trends['equipment']=dict(title='S7 y Modbus en el mismo visor',window_seconds=600,axes=[dict(id='flow',title='Caudal S7',side='left',auto=True,min=0,max=100,visible=True),dict(id='temp',title='Temperatura Modbus',side='right',auto=True,min=0,max=100,visible=True)],curves=[curve('s7','Siemens.Bomba1.Caudal','flow','#3678c8',3),curve('mb','Modbus.Temperatura','temp','#8152b4',3)])
    d=page('40_graficas','Gráficas en vivo','Curvas registradas y no registradas. Activa la señal local o arranca los servidores externos para observar cambios.')
    elem(d,'trend','graph',30,148,1100,535,view='local')
    button(d,'generator','Activar / parar señal local',30,704,'Local.Generador',w=300)
    button(d,'unrecorded','Abrir curva sin registro',360,704,action='popup',screen='93_sin_registro',w=320)
    button(d,'equipment','Abrir curva S7 + Modbus',710,704,action='popup',screen='94_equipos',w=390)
    d=page('41_historicos','Histórico y archivos diarios','Registro interno: 1 s · equipos: 2 s · modos: 5 s. Selecciona un intervalo en el visor para consultar días anteriores.')
    elem(d,'trend','history',30,148,1100,535,view='local')
    text(d,'files','Cada variable pertenece a un solo registro. «Local.SinRegistro» no se archiva. Los datos de ayer y anteayer se preparan con seed_showcase_history.py.',30,697,1090,56)
    for name,title_,view in [('93_sin_registro','Variable local no registrada','online_only'),('94_equipos','Adquisición multiprotocolo','equipment')]:
        d=page(name,title_,'Visor independiente del registro de variables.');elem(d,'trend','plot',30,140,1100,530,view=view);button(d,'close','Cerrar ventana',850,700,action='close_popup',w=280)

    p.historian=dict(retention_days=90,files=[dict(id='internas',name='Variables internas · 1 s',interval_ms=1000,variables=['Local.Nivel','Local.Consigna','Local.Temperatura','Local.Marcha']),dict(id='equipos',name='Equipos TCP · 2 s',interval_ms=2000,variables=['Siemens.Bomba1.Caudal','Siemens.Bomba2.Caudal','Siemens.Nivel','Modbus.Temperatura','Modbus.Contador']),dict(id='estados',name='Estados y mandos · 5 s',interval_ms=5000,variables=['Local.Modo','Local.Permiso','Local.Fallo'])])
    p.alarms=dict(retention_days=365,categories=[dict(id='local',name='Proceso interno',color='#147d75'),dict(id='equipment',name='Equipos TCP',color='#3678c8'),dict(id='events',name='Avisos',color='#da982f')],items=[])
    for identifier,tag,category,condition_,threshold,message,priority,ack in [('local_high','Local.Nivel','local','high',80,'Nivel local alto',800,True),('local_low','Local.Nivel','local','low',15,'Nivel local bajo',600,True),('fault','Local.Fallo','local','true',0,'Fallo digital de ejemplo',900,True),('s7_high','Siemens.Nivel','equipment','high',80,'Nivel alto en depósito S7',700,True),('modbus_hot','Modbus.Temperatura','equipment','high',65,'Temperatura Modbus alta',750,True),('manual','Local.Modo','events','equal',1,'Modo manual seleccionado',200,False)]:
        p.alarms['items'].append(dict(id=identifier,tag=tag,category=category,condition=condition_,threshold=threshold,message=message,priority=priority,ack_required=ack,enabled=True,hysteresis=3 if condition_ in {'high','low'} else 0,on_delay_ms=500,off_delay_ms=300))
    p.alarm_views={mode:dict(title=label,categories=[],min_priority=1,mode=mode,allow_ack=True,columns=['priority','category','message','state','entered_at','returned_at','ack_at','actor']) for mode,label in [('pending','Alarmas pendientes'),('history','Histórico de alarmas'),('events','Eventos de alarma')]}
    for key,name,mode in [('50_alarmas','Alarmas, reconocimiento y retorno','pending'),('51_eventos','Histórico de alarmas y eventos','events')]:
        d=page(key,name,'Prueba el ciclo: activar → reconocer (ACK) → retornar. Las fechas y el operador quedan registrados en SQLite.')
        elem(d,'alarm_view','alarms',30,210,1100,485,view=mode)
        button(d,'high','Nivel alto (90 %)',30,140,'Local.Nivel',action='set',value=90.,w=260)
        button(d,'normal','Nivel normal (50 %)',310,140,'Local.Nivel',action='set',value=50.,w=260)
        button(d,'fault','Activar / quitar fallo',590,140,'Local.Fallo',w=260)
        button(d,'history','Ver ocurrencias',870,140,action='popup',screen='95_ocurrencias',w=260)
        text(d,'alarm_hint','Detén la señal local para mantener el nivel manual. El visor permite cambiar filtros, periodo, columnas y exportar CSV.',30,707,1090,44)
    d=page('95_ocurrencias','Ocurrencias de alarmas','Cada activación conserva entrada, retorno y reconocimiento.');elem(d,'alarm_view','history',30,140,1100,530,view='history');button(d,'close','Cerrar ventana',850,700,action='close_popup',w=280)

    d=page('60_scripts','Python: inicio, apertura, tarea y botón','Fuentes editables en scripts/. Las tareas de demostración escriben exclusivamente variables internas.')
    for i,(label,tag) in enumerate([('Inicio de sesión','Sistema.Inicio'),('Hora actual','Sistema.Hora'),('Ciclos de tarea','Sistema.Ciclos'),('Pantallas abiertas','Sistema.Aperturas'),('Último evento','Sistema.UltimoEvento')]):value(d,'event'+str(i),label,tag,30,145+i*73,1090)
    button(d,'script','Ejecutar script de botón',30,550,action='script',script='button_event',w=350)
    button(d,'reset','Restablecer banco local',405,550,action='script',script='reset_local',w=350)
    value(d,'operator','Operador','Sistema.Operador',30,626,725,kind='input')
    text(d,'jobs','Tarea cada 1 s: reloj, contador, señal local opcional y estado de calidad de S7/Modbus. Ver ejecuciones en Studio → Scripts y tareas.',30,688,1090,57)

    d=page('90_ajustes','Configuración local','La misma variable se actualiza en la pantalla principal y en esta ventana.')
    for i,(label,tag) in enumerate([('Operador','Sistema.Operador'),('Lote','Local.Texto'),('Consigna','Local.Consigna'),('Temperatura','Local.Temperatura')]):value(d,'setting'+str(i),label,tag,50,150+i*100,1040,kind='input')
    button(d,'close','Cerrar ajustes',760,650,action='close_popup',w=330)
    d=page('91_ayuda','Mapa del laboratorio','El README del proyecto contiene el recorrido completo y los mapas de direcciones.')
    for i,line in enumerate(['01–05: banco interno, dinámica visual, dibujos y componentes.','06–07: equipos externos S7 y Modbus, sin sustitución de lecturas.','08–09: tiempo real, variable sin registro e históricos entre días.','10–11: alarmas, reconocimiento, retorno y exportación.','12: scripts de inicio, apertura, botón y tarea periódica.','Guardar proyecto conserva todo; Versiones permite activar Git local.']):text(d,'help'+str(i),line,40,150+i*74,1080,53)
    button(d,'close','Cerrar ayuda',760,650,action='close_popup',w=330)
    d=page('92_completa','Navegación de ventana completa','Esta acción sustituye el layout completo. El botón inferior restaura cabecera, menú y contenido.')
    elem(d,'image','logo',390,210,380,250,source='assets/valve-on.svg')
    button(d,'back','Volver al laboratorio',380,570,action='screen',screen='00_layout',target_container='__window__',w=400)

    p.scripts={
        'startup':"from datetime import datetime\nctx.write('Sistema.Inicio', datetime.now().strftime('%d/%m/%Y %H:%M:%S'))\nctx.write('Sistema.UltimoEvento', 'Script de inicio completado')\nprint('Inicio del laboratorio; no se escriben variables PLC')\n",
        'screen_open':"ctx.write('Sistema.Aperturas', ctx.read('Sistema.Aperturas') + 1)\nctx.write('Sistema.UltimoEvento', 'Apertura: ' + ctx.screen)\n",
        'periodic':"""from datetime import datetime
import math
ctx.state['ticks'] = ctx.state.get('ticks', 0) + 1
n = ctx.state['ticks']
ctx.write('Sistema.Ciclos', n)
ctx.write('Sistema.Hora', datetime.now().strftime('%d/%m/%Y %H:%M:%S'))
ctx.write('Sistema.S7', {'good':'Conectado','bad':'Sin conexión','uncertain':'Esperando lectura'}[ctx.quality('Siemens.Nivel')])
ctx.write('Sistema.Modbus', {'good':'Conectado','bad':'Sin conexión','uncertain':'Esperando lectura'}[ctx.quality('Modbus.Temperatura')])
if ctx.read('Local.Generador'):
    ctx.write('Local.Nivel', 50.0 + 40.0 * math.sin(n / 10.0))
    ctx.write('Local.Temperatura', 30.0 + 10.0 * math.sin(n / 17.0))
    ctx.write('Local.SinRegistro', math.sin(n / 4.0))
""",
        'button_event':"ctx.state['clicks'] = ctx.state.get('clicks', 0) + 1\nctx.write('Sistema.UltimoEvento', 'Script de botón: ejecución ' + str(ctx.state['clicks']))\nprint('Botón en pantalla', ctx.screen)\n",
        'reset_local':"""for name, value in {'Generador':False,'Marcha':False,'Permiso':True,'Fallo':False,'Pulsador':False,'Orden':0,'Modo':0,'Consigna':55.0,'Nivel':35.0,'Temperatura':24.0,'SinRegistro':0.0}.items():
    ctx.write('Local.'+name, value)
ctx.write('Sistema.UltimoEvento', 'Banco interno restablecido')
"""}
    p.automation=dict(startup=['startup'],tasks=[dict(id='cada_segundo',script='periodic',interval_ms=1000,enabled=True)],timeout_seconds=10)
    assets=root/'assets';assets.mkdir(parents=True,exist_ok=True)
    for state,color in [('off','#8394a5'),('on','#147d75')]:
        (assets/f'valve-{state}.svg').write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="500" height="300" viewBox="0 0 500 300"><rect width="500" height="300" rx="24" fill="#edf3f7"/><path d="M40 150H460" stroke="#b5c4d1" stroke-width="32"/><path d="M160 75L340 225V75L160 225Z" fill="{color}" stroke="#243c50" stroke-width="5"/><path d="M250 150V35M210 35H290" stroke="#243c50" stroke-width="8"/><text x="250" y="278" text-anchor="middle" font-family="sans-serif" font-size="22" fill="#243c50">VÁLVULA · {'ABIERTA' if state=='on' else 'CERRADA'}</text></svg>''',encoding='utf-8',newline='\n')
    from abscada.faceplate_libraries import link
    library=Path(__file__).resolve().parents[1]/'examples/libraries/equipos-1.0.0.abscada-library.json'
    link(p,library,'equipos')
    # Keep the internal instance local and use the published template for Siemens.
    for element in p.screens['23_faceplates']['elements']:
        if element.get('id')=='unit1':element['template']='equipos__unidad'
    p.save();return p


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='examples/showcase');args=parser.parse_args()
    project=build_project(args.output)
    print(f'{project.root}: {len(project.screens)} pantallas, {len(project.tags())} variables, {len(project.connections)} conexiones')
