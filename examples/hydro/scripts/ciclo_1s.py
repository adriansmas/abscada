"""Cada segundo: reloj, estado de comunicaciones y totales de planta."""
from datetime import datetime

now = datetime.now()
ctx.write("Sistema.Fecha", now.strftime("%d/%m/%Y"))
ctx.write("Sistema.Hora", now.strftime("%H:%M:%S"))

links = {"ComG1": "G1.Paso", "ComG2": "G2.Paso", "ComSSCC": "SSCC.NivelEmbalse", "ComContador": "Contador.Potencia"}
ok = {}
for flag, probe in links.items():
    ok[flag] = ctx.quality(probe) == "good"
    ctx.write("Sistema." + flag, ok[flag])
ctx.write("Sistema.ComTodas", all(ok.values()))

power = flow = 0.0
for unit in ("G1", "G2"):
    if ctx.quality(unit + ".Potencia") == "good":
        power += ctx.read(unit + ".Potencia")
        flow += ctx.read(unit + ".Caudal")
ctx.write("Sistema.PotenciaTotal", power)
ctx.write("Sistema.CaudalTurbinado", flow)

# Energía del día a partir del contador fiscal (kWh exportados).
if ok["ComContador"]:
    exported = ctx.read("Contador.EnergiaExportada")
    today = now.strftime("%Y-%m-%d")
    if ctx.state.get("day") != today:
        ctx.state["day"] = today
        ctx.state["start_kwh"] = exported
    ctx.write("Sistema.EnergiaHoy", (exported - ctx.state["start_kwh"]) / 1000.0)
