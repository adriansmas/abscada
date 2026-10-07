"""Cada segundo: reloj y estado de la comunicación con el PLC."""
from datetime import datetime

now = datetime.now()
ctx.write("Sistema.Fecha", now.strftime("%d/%m/%Y"))
ctx.write("Sistema.Hora", now.strftime("%H:%M:%S"))
ctx.write("Sistema.ComPLC", ctx.quality("Cocina.Paso") == "good")
