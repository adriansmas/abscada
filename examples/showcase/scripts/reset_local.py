for name, value in {'Generador':False,'Marcha':False,'Permiso':True,'Fallo':False,'Pulsador':False,'Orden':0,'Modo':0,'Consigna':55.0,'Nivel':35.0,'Temperatura':24.0,'SinRegistro':0.0}.items():
    ctx.write('Local.'+name, value)
ctx.write('Sistema.UltimoEvento', 'Banco interno restablecido')
