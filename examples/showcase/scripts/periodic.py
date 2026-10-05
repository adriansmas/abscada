from datetime import datetime
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
