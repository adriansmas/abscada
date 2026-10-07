"""Arranque del Runtime: marca la sesión."""
from datetime import datetime

ctx.write("Sistema.Inicio", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
print("SCADA La Tolva iniciado")
