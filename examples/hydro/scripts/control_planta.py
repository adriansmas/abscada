"""Cada 2 s: control conjunto de potencia y regulación de nivel del embalse."""
MIN_MW, MAX_MW = 2.0, 10.0


def good(*tags):
    return all(ctx.quality(t) == "good" for t in tags)


if not ctx.read("Planta.ControlConjunto"):
    ctx.write("Planta.Estado", "Control conjunto desactivado: cada grupo sigue su propia consigna")
else:
    target = ctx.read("Planta.ConsignaPlanta")
    if ctx.read("Planta.ControlNivel") and good("SSCC.NivelEmbalse"):
        error = ctx.read("SSCC.NivelEmbalse") - ctx.read("Planta.ConsignaNivel")
        target = max(0.0, min(2 * MAX_MW, target + 1.5 * error))
        ctx.write("Planta.ConsignaPlanta", round(target, 2))

    units = [u for u in ("G1", "G2")
             if good(u + ".Paso", u + ".Remoto") and ctx.read(u + ".Paso") == 6 and ctx.read(u + ".Remoto")]
    if not units:
        ctx.write("Planta.Estado", "Sin grupos acoplados en remoto: nada que repartir")
    else:
        share = max(MIN_MW, min(MAX_MW, target / len(units)))
        for unit in units:
            if abs(ctx.read(unit + ".ConsignaP") - share) > 0.05:
                ctx.write(unit + ".ConsignaP", round(share, 2))
        ctx.write("Planta.Estado", f"Reparto {target:.2f} MW entre {', '.join(units)}: {share:.2f} MW por grupo")
