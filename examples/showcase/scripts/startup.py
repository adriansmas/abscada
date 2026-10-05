from datetime import datetime
ctx.write('Sistema.Inicio', datetime.now().strftime('%d/%m/%Y %H:%M:%S'))
ctx.write('Sistema.UltimoEvento', 'Script de inicio completado')
print('Inicio del laboratorio; no se escriben variables PLC')
