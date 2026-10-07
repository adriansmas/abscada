"""Cada 2 s: anota en «Último evento» los hitos de cada lote (inicio, llegada a bodega, listo)."""
from datetime import datetime

FASES = ["vacío", "llenando", "fermentando", "en reposo de diacetilo", "en cold crash", "en guarda", "listo para envasar"]


def good(*tags):
    return all(ctx.quality(t) == "good" for t in tags)


def event(text):
    ctx.write("Sistema.UltimoEvento", datetime.now().strftime("%H:%M") + " · " + text)


if good("Cocina.Lote", "Cocina.RecetaLote", "Cocina.FVLote"):
    lote = ctx.read("Cocina.Lote")
    if ctx.state.get("lote") is not None and lote != ctx.state["lote"]:
        ctx.write("Sistema.LotesCocinados", ctx.read("Sistema.LotesCocinados") + 1)
        event(f"Lote {lote} {ctx.read('Cocina.RecetaLote')} → FV{ctx.read('Cocina.FVLote')}")
    ctx.state["lote"] = lote

for fv in ("FV1", "FV2", "FV3"):
    if not good(fv + ".Fase", fv + ".Lote"):
        continue
    fase = ctx.read(fv + ".Fase")
    previous = ctx.state.get(fv)
    if previous is not None and fase != previous and 0 <= fase < len(FASES):
        event(f"{fv} {FASES[fase]}" + (f" · lote {ctx.read(fv + '.Lote')}" if fase else ""))
    ctx.state[fv] = fase
