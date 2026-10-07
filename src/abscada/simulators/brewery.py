"""External PLC for examples/brewery: a 10 hl craft brewery behind an OPC UA server.

Never imported by Runtime. Start it in its own terminal:

    abscada --simulador cerveceria        (or: python -m abscada --simulador cerveceria)

The server only offers encrypted endpoints (Basic256Sha256, sign and encrypt). Its
certificate is created once per user under the abSCADA state folder, so the SCADA has to
trust it a single time. Like a PLC in commissioning, it accepts every client certificate.

Time is compressed: one recipe minute lasts one second in the brewhouse (a full brew takes
about seven minutes) and one fermentation day lasts one minute in the cellar.
"""
import argparse
import asyncio
import math
import random
import socket
import threading
from collections import deque

from .brewery_map import (DAYS_PER_SECOND, DEFAULT_RECIPES, FERMENTERS, MINUTES_PER_SECOND,
                          NAMESPACE, OBJECTS, PORT, RECIPE_COUNT, RECIPE_FIELDS, RECIPE_PARAMETERS)

DT = 0.1                       # real seconds per PLC scan
MINUTES = DT * MINUTES_PER_SECOND
DAYS = DT * DAYS_PER_SECOND
CELLAR_C = 22.0                # the cellar is warm: diacetyl rests rise freely
MAINS_WATER_C = 12.0
HLT_CAPACITY = 30.0            # hl
FV_CAPACITY = 12.0             # hl
BATCH_HL = 10.0                # hl of wort into the fermenter
EVAPORATION = 0.025            # hl per boiling minute
FILTER_FLOW = 0.5              # hl/min through a clean bed
TRANSFER_FLOW = 1.0            # hl/min through the wort cooler
RELIEF_BAR, SPUNDING_BAR = 2.5, 1.0


def clamp(value, low, high):
    return max(low, min(high, value))


def lag(value, target, tau):
    return value + (target - value) * min(1.0, DT / tau)


class Brewery:
    """The PLC program and the process it controls. Values live in ``self.v[object][field]``."""

    def __init__(self):
        self.v = {obj: {name: {"bool": False, "int": 0, "float": 0.0, "string": ""}[kind]
                        for name, kind, *_ in fields} for obj, fields in OBJECTS}
        self.recipes = [dict(r) for r in DEFAULT_RECIPES]
        self.batch = None          # recipe copied when the brew starts
        self.reached = False       # mash rest temperature reached at least once
        self.held = 0.0            # minutes counted in the current timed step
        self.sparge_left = 0.0
        self.preboil = 0.0
        self.aroma_asked = False
        self.integral = {fv: 0.0 for fv in FERMENTERS}
        self.fv_recipe = {fv: None for fv in FERMENTERS}
        self.phase_start = {fv: 0.0 for fv in FERMENTERS}
        self.history = {fv: deque(maxlen=12) for fv in FERMENTERS}
        self.refill = False
        self.time = 0.0
        c, s, r = self.v["Cocina"], self.v["Servicios"], self.v["Recetas"]
        c.update(RecetaSeleccionada=2, FVDestino=3, Lote=1041, TempMT=20.0, TempBK=20.0, TempMostoSalida=18.0)
        s.update(ConsignaHLT=80.0, ConsignaGlicol=-4.0, TempHLT=80.0, NivelHLT=26.0, PresionVapor=6.0, Caldera=True,
                 TempGlicol=-4.0, NivelGlicol=75.0, TempAguaFria=2.0)
        r["Numero"] = 1
        self.load_editor()
        for fv in FERMENTERS:
            self.v[fv].update(Automatico=True, ConsignaManual=18.0, Temperatura=CELLAR_C - 4)
        # The plant is already working: an IPA fermenting and a lager-style blonde in the cold.
        self.fill(FERMENTERS[0], self.recipes[2], 1041, 15.5, day=2.5)
        self.fill(FERMENTERS[1], self.recipes[0], 1040, 12.0, day=9.0, phase=5)

    # ------------------------------------------------------------------ helpers
    def fill(self, fv, recipe, batch, original, day=0.0, phase=2):
        f = self.v[fv]
        self.fv_recipe[fv] = recipe
        k = self.rate_constant(recipe)
        density = recipe["DensidadFinal"] + (original - recipe["DensidadFinal"]) * math.exp(-k * max(0.0, day - 0.7))
        f.update(Fase=phase, Lote=batch, NombreReceta=recipe["Nombre"], Dia=day, Densidad=density,
                 DensidadOriginal=original, DensidadObjetivo=recipe["DensidadFinal"], Nivel=BATCH_HL,
                 Presion=SPUNDING_BAR if day > 0.5 else 0.1, Temperatura=self.phase_setpoint(fv, phase))
        self.phase_start[fv] = day
        self.history[fv].clear()

    @staticmethod
    def rate_constant(recipe):
        # 90 % of the attenuation within 60 % of the planned fermentation days.
        return 2.3 / (0.6 * recipe["DiasFermentacion"])

    def phase_setpoint(self, fv, phase=None):
        recipe = self.fv_recipe[fv]
        phase = self.v[fv]["Fase"] if phase is None else phase
        if recipe is None or phase <= 1:
            return recipe["TempFermentacion"] if recipe else 18.0
        return {2: recipe["TempFermentacion"], 3: recipe["TempDiacetilo"]}.get(phase, recipe["TempGuarda"])

    def load_editor(self):
        r = self.v["Recetas"]
        r["Numero"] = clamp(int(r["Numero"]), 1, RECIPE_COUNT)
        r.update(self.recipes[r["Numero"] - 1])
        self.editing = r["Numero"]

    def pulse(self, obj, field):
        value = self.v[obj][field]
        self.v[obj][field] = False
        return value

    # ------------------------------------------------------------------ scan
    def scan(self):
        self.time += DT
        self.services()
        self.recipe_manager()
        self.brewhouse()
        for fv in FERMENTERS:
            self.fermenter(fv)

    def services(self):
        s = self.v["Servicios"]
        s["FalloCaldera"] = s["SimFalloCaldera"]
        s["Caldera"] = not s["FalloCaldera"]
        s["PresionVapor"] = clamp(s["PresionVapor"] + (0.4 if s["Caldera"] else -0.15) * DT, 0.0, 6.0)
        steam = s["PresionVapor"] / 6.0
        heating = s["TempHLT"] < s["ConsignaHLT"] - 0.5
        s["TempHLT"] += ((1.5 * steam if heating else 0.0) - 0.003 * (s["TempHLT"] - 20.0)) * MINUTES
        if s["NivelHLT"] < 15.0:
            self.refill = True
        if self.refill:
            added = min(1.0 * MINUTES, HLT_CAPACITY - s["NivelHLT"])
            s["TempHLT"] = (s["TempHLT"] * s["NivelHLT"] + MAINS_WATER_C * added) / max(s["NivelHLT"] + added, 0.1)
            s["NivelHLT"] += added
            self.refill = s["NivelHLT"] < HLT_CAPACITY - 0.01

        if s["SimFugaGlicol"]:
            s["NivelGlicol"] = max(0.0, s["NivelGlicol"] - 0.5 * DT)
        elif s["NivelGlicol"] < 75.0:
            s["NivelGlicol"] = min(75.0, s["NivelGlicol"] + 0.3 * DT)
        s["FalloEnfriadora"] = s["SimFalloEnfriadora"] or s["NivelGlicol"] < 20.0
        if s["FalloEnfriadora"]:
            s["Enfriadora"] = False
        elif s["TempGlicol"] > s["ConsignaGlicol"] + 0.5:
            s["Enfriadora"] = True
        elif s["TempGlicol"] < s["ConsignaGlicol"] - 0.5:
            s["Enfriadora"] = False
        load = sum(self.v[fv]["ValvulaGlicol"] for fv in FERMENTERS) / 100.0
        load += 2.0 if self.v["Cocina"]["Paso"] == 11 else 0.0
        s["TempGlicol"] += (0.03 * load - 0.25 * s["Enfriadora"] + 0.004 * (20.0 - s["TempGlicol"])) * DT
        s["TempAguaFria"] = lag(s["TempAguaFria"], max(1.0, s["TempGlicol"] + 6.0), 20.0)
        s["AlarmaServicios"] = (s["PresionVapor"] < 4.0 or s["FalloCaldera"] or s["FalloEnfriadora"]
                                or s["TempGlicol"] > 0.0 or s["NivelGlicol"] < 40.0 or s["NivelHLT"] < 10.0)

    def recipe_manager(self):
        r = self.v["Recetas"]
        if int(r["Numero"]) != self.editing:
            self.load_editor()
        if self.pulse("Recetas", "OrdenDescartar"):
            self.load_editor()
        if self.pulse("Recetas", "OrdenGuardar"):
            limits = {name: (low, high) for name, _, _, _, low, high in RECIPE_PARAMETERS}
            recipe = {}
            for name, kind in RECIPE_FIELDS:
                value = r[name]
                if kind == "float":
                    value = clamp(float(value), *limits[name])  # the PLC never stores an impossible recipe
                recipe[name] = value if name != "Nombre" else (str(value).strip()[:20] or f"Receta {self.editing}")
            self.recipes[self.editing - 1] = recipe
            r.update(recipe)
        stored = self.recipes[self.editing - 1]
        r["Modificada"] = any(r[name] != stored[name] for name, _ in RECIPE_FIELDS)
        c = self.v["Cocina"]
        r["EnUso"] = c["Paso"] > 0 and self.batch is not None and self.batch.get("_numero") == self.editing
        for i, recipe in enumerate(self.recipes, 1):
            r[f"Nombre{i}"] = recipe["Nombre"]

    # ------------------------------------------------------------------ brewhouse
    def goto(self, step):
        c = self.v["Cocina"]
        c["Paso"], c["TiempoPaso"] = step, 0.0
        self.held, self.reached = 0.0, False
        c["FueraTemperaturaMT"] = False

    def ask(self, prompt):
        c = self.v["Cocina"]
        c["EsperaOperador"], c["Aviso"] = True, prompt

    def heat_mash(self, target, steam):
        c = self.v["Cocina"]
        c["ConsignaActual"] = target
        c["VaporMT"] = clamp((target - c["TempMT"]) * 60.0, 0.0, 100.0) * (steam > 0.05)
        c["TempMT"] += (1.2 * steam * c["VaporMT"] / 100.0 - 0.004 * (c["TempMT"] - 20.0)) * MINUTES

    def brewhouse(self):
        c, s = self.v["Cocina"], self.v["Servicios"]
        start, hold, resume, abort, confirm = (self.pulse("Cocina", f) for f in (
            "OrdenIniciar", "OrdenRetener", "OrdenReanudar", "OrdenAbortar", "OrdenConfirmar"))
        c["RecetaSeleccionada"] = clamp(int(c["RecetaSeleccionada"]), 1, RECIPE_COUNT)
        c["FVDestino"] = clamp(int(c["FVDestino"]), 1, len(FERMENTERS))
        c["NombreReceta"] = self.recipes[c["RecetaSeleccionada"] - 1]["Nombre"]
        destination = FERMENTERS[c["FVDestino"] - 1]
        steam = s["PresionVapor"] / 6.0
        step = c["Paso"]
        c["ListoIniciar"] = (step == 0 and self.v[destination]["Fase"] == 0 and s["PresionVapor"] > 4.0
                             and s["TempHLT"] >= 70.0 and s["NivelHLT"] >= 10.0)

        if abort and step > 0:
            if step == 11:  # the half-filled fermenter goes to drain with the rest of the brew
                self.v[FERMENTERS[c["FVLote"] - 1]].update(Fase=0, Nivel=0.0, Lote=0, NombreReceta="")
            c.update(NivelMT=0.0, NivelLT=0.0, NivelBK=0.0, Retenido=False, EsperaOperador=False, Aviso=0,
                     TiempoRestante=0.0, ConsignaActual=0.0)
            self.goto(0)
            step = 0
        elif start and c["ListoIniciar"]:
            self.batch = dict(self.recipes[c["RecetaSeleccionada"] - 1], _numero=c["RecetaSeleccionada"])
            c["Lote"] += 1
            c.update(RecetaLote=self.batch["Nombre"], FVLote=c["FVDestino"], Retenido=False, DensidadMosto=0.0)
            self.aroma_asked = False
            self.goto(1)
            step = 1
        if hold and step > 0:
            c["Retenido"] = True
        if resume:
            c["Retenido"] = False
        if confirm and c["EsperaOperador"]:
            c["EsperaOperador"] = False
            if c["Aviso"] == 1 and step == 2:
                c["TempMT"] -= 3.0
                c["NivelMT"] += 0.3 * self.batch["VolumenAgua"]
                self.goto(3 if self.batch["TiempoE1"] > 0 else 4)
                step = c["Paso"]
            c["Aviso"] = 0

        # Defaults every scan; each step switches on what it uses.
        c.update(AgitadorMT=False, Rastrillos=False, CaudalFiltrado=0.0, CaudalTrasiego=0.0,
                 VaporBK=0.0, Ebullicion=False, SiembraCaliente=False)
        c["VaporMT"] = 0.0
        if step not in (8, 9):
            c["NivelEspuma"] = lag(c["NivelEspuma"], 0.0, 3.0)
        if step == 0 or c["Retenido"]:
            for vessel in ("TempMT", "TempBK"):
                c[vessel] += -0.004 * (c[vessel] - 20.0) * MINUTES
            if step == 0:
                c.update(TiempoRestante=0.0, ConsignaActual=0.0, FueraTemperaturaMT=False)
            self.summary()
            return

        b = self.batch
        c["TiempoPaso"] += MINUTES
        strike = (b["TempE1"] if b["TiempoE1"] > 0 else b["TempE2"]) + 3.0
        if step == 1:  # hot liquor blended with mains water to the strike temperature
            c["AgitadorMT"] = True
            flow = min(1.0 * MINUTES, b["VolumenAgua"] - c["NivelMT"])
            incoming = min(strike, s["TempHLT"])
            hot = clamp((incoming - MAINS_WATER_C) / max(s["TempHLT"] - MAINS_WATER_C, 1.0), 0.0, 1.0)
            s["NivelHLT"] = max(0.0, s["NivelHLT"] - flow * hot)
            if flow > 0:
                c["TempMT"] = (c["TempMT"] * c["NivelMT"] + incoming * flow) / (c["NivelMT"] + flow)
                c["NivelMT"] += flow
            self.heat_mash(strike, steam)
            c["TiempoRestante"] = max(0.0, b["VolumenAgua"] - c["NivelMT"]) / 1.0
            if c["NivelMT"] >= b["VolumenAgua"] - 1e-6 and abs(c["TempMT"] - strike) < 1.0:
                self.goto(2)
                self.ask(1)
        elif step == 2:
            c["AgitadorMT"] = True
            self.heat_mash(strike, steam)
            c["TiempoRestante"] = 0.0
            if not c["EsperaOperador"]:
                self.ask(1)
        elif step in (3, 4, 5):
            target, minutes = {3: (b["TempE1"], b["TiempoE1"]), 4: (b["TempE2"], b["TiempoE2"]),
                               5: (b["TempE3"], b["TiempoE3"])}[step]
            c["AgitadorMT"] = True
            self.heat_mash(target, steam)
            if abs(c["TempMT"] - target) < 0.5:
                self.reached = True
            if self.reached:
                self.held += MINUTES
            c["FueraTemperaturaMT"] = self.reached and abs(c["TempMT"] - target) > 1.5
            c["TiempoRestante"] = max(0.0, minutes - self.held)
            if self.held >= minutes:
                self.goto(step + 1)
        elif step == 6:  # transfer to the lauter tun, then recirculate until the wort runs clear
            c["ConsignaActual"] = 0.0
            moved = min(1.5 * MINUTES, c["NivelMT"])
            c["NivelMT"] -= moved
            c["NivelLT"] += moved
            c["AgitadorMT"] = c["NivelMT"] > 0
            if c["NivelMT"] <= 0:
                self.held += MINUTES
            c["TiempoRestante"] = c["NivelMT"] / 1.5 + max(0.0, 5.0 - self.held)
            if self.held >= 5.0:
                self.preboil = BATCH_HL + EVAPORATION * b["TiempoHervido"] + 0.5
                self.sparge_left = self.preboil - 0.9 * b["VolumenAgua"]
                c["PresionLecho"] = 60.0
                self.goto(7)
        elif step == 7:
            # The rakes cut the bed above 120 mbar; a stuck bed beats them.
            c["Rastrillos"] = c["PresionLecho"] > 120.0
            rate = (15.0 if c["SimLechoColmatado"] else 2.0) - (12.0 if c["Rastrillos"] else 0.0)
            c["PresionLecho"] = clamp(c["PresionLecho"] + rate * MINUTES, 40.0, 320.0)
            factor = clamp(1.0 - (c["PresionLecho"] - 100.0) / 200.0, 0.15, 1.0)
            c["CaudalFiltrado"] = FILTER_FLOW * factor * 60.0          # hl/h on the screen
            flow = FILTER_FLOW * factor * MINUTES
            sparge = min(flow, self.sparge_left)
            self.sparge_left -= sparge
            s["NivelHLT"] = max(0.0, s["NivelHLT"] - sparge)
            c["NivelLT"] = max(0.0, c["NivelLT"] + sparge - flow)
            c["NivelBK"] += flow
            c["TempBK"] = lag(c["TempBK"], 74.0, 5.0 / MINUTES_PER_SECOND)
            done = clamp(c["NivelBK"] / self.preboil, 0.0, 1.0)
            c["DensidadMosto"] = self.original_preboil() * (1.3 - 0.3 * done)
            c["TiempoRestante"] = max(0.0, self.preboil - c["NivelBK"]) / (FILTER_FLOW * factor)
            if c["NivelBK"] >= self.preboil:
                c.update(NivelLT=0.0, PresionLecho=0.0)  # spent grain out
                self.goto(8)
        elif step == 8:
            c["ConsignaActual"] = 100.0
            c["VaporBK"] = 100.0 * (steam > 0.05)
            c["TempBK"] = min(100.0, c["TempBK"] + (1.5 * steam - 0.004 * (c["TempBK"] - 20.0)) * MINUTES)
            c["TiempoRestante"] = max(0.0, 100.0 - c["TempBK"]) / 1.5
            c["NivelEspuma"] = lag(c["NivelEspuma"], 15.0, 2.0)
            if c["TempBK"] >= 99.5:
                self.goto(9)
                self.ask(2)
        elif step == 9:
            c["ConsignaActual"] = 100.0
            foam = c["NivelEspuma"] > 80.0
            c["VaporBK"] = (40.0 if foam else 70.0) * (steam > 0.05)
            c["Ebullicion"] = steam > 0.4
            if c["Ebullicion"]:
                c["TempBK"] = 100.0
                self.held += MINUTES
                c["NivelBK"] = max(0.0, c["NivelBK"] - EVAPORATION * MINUTES)
            else:
                c["TempBK"] += -0.004 * (c["TempBK"] - 20.0) * MINUTES
            target = (98.0 if not foam else 88.0) if c["SimEspuma"] else 25.0 + 8.0 * math.sin(self.time / 3.0)
            c["NivelEspuma"] = lag(c["NivelEspuma"], target if c["Ebullicion"] else 5.0, 4.0)
            c["DensidadMosto"] = self.original_preboil() * self.preboil / max(c["NivelBK"], 0.1)
            c["TiempoRestante"] = max(0.0, b["TiempoHervido"] - self.held)
            if b["LupuloAroma"] > 0 and not self.aroma_asked and c["TiempoRestante"] <= b["LupuloAroma"]:
                self.aroma_asked = True
                self.ask(3)
            if self.held >= b["TiempoHervido"]:
                self.goto(10)
        elif step == 10:
            c["ConsignaActual"] = 0.0
            c["TempBK"] = lag(c["TempBK"], 95.0, 5.0)
            c["TiempoRestante"] = max(0.0, 15.0 - c["TiempoPaso"])
            if c["TiempoPaso"] >= 15.0:
                fv = self.v[FERMENTERS[c["FVLote"] - 1]]
                fv.update(Fase=1, Lote=c["Lote"], NombreReceta=b["Nombre"], Nivel=0.0, Dia=0.0)
                self.fv_recipe[FERMENTERS[c["FVLote"] - 1]] = b
                self.goto(11)
        elif step == 11:
            name = FERMENTERS[c["FVLote"] - 1]
            fv = self.v[name]
            moved = min(TRANSFER_FLOW * MINUTES, c["NivelBK"])
            c["CaudalTrasiego"] = TRANSFER_FLOW * 60.0
            c["NivelBK"] -= moved
            outlet = max(s["TempAguaFria"] + 3.0, b["TempFermentacion"])
            c["TempMostoSalida"] = lag(c["TempMostoSalida"], outlet, 3.0)
            c["SiembraCaliente"] = c["TempMostoSalida"] > b["TempFermentacion"] + 2.0
            if moved > 0:
                fv["Temperatura"] = (fv["Temperatura"] * fv["Nivel"] + c["TempMostoSalida"] * moved) / (fv["Nivel"] + moved)
                fv["Nivel"] = min(FV_CAPACITY, fv["Nivel"] + moved)
            c["TiempoRestante"] = c["NivelBK"] / TRANSFER_FLOW
            if c["NivelBK"] <= 0.5:
                c["NivelBK"] = 0.0  # trub stays in the whirlpool
                original = round(c["DensidadMosto"], 1)
                self.fill(name, b, c["Lote"], original, phase=2)
                fv["Temperatura"] = c["TempMostoSalida"]
                fv["Nivel"] = BATCH_HL
                self.goto(12)
        elif step == 12:
            c["TempMostoSalida"] = lag(c["TempMostoSalida"], 18.0, 5.0)
            c["TiempoRestante"] = max(0.0, 10.0 - c["TiempoPaso"])
            if c["TiempoPaso"] >= 10.0:
                c.update(EsperaOperador=False, Aviso=0)
                self.goto(0)
        self.summary()

    def original_preboil(self):
        """Gravity before the boil: the boil concentrates it to the recipe's original gravity."""
        return self.batch["DensidadOriginal"] * (BATCH_HL + 0.5) / self.preboil

    def summary(self):
        c = self.v["Cocina"]
        c["AlarmaCocina"] = (c["FueraTemperaturaMT"] or c["NivelEspuma"] > 80.0 or c["PresionLecho"] > 200.0
                             or c["SiembraCaliente"])

    # ------------------------------------------------------------------ cellar
    def fermenter(self, fv):
        f, s = self.v[fv], self.v["Servicios"]
        drain = self.pulse(fv, "OrdenVaciar")
        phase = f["Fase"]
        if phase == 6 and drain:
            f["Fase"] = phase = 7  # internal: draining to the bottling line
        if phase == 7:
            f["Nivel"] = max(0.0, f["Nivel"] - 1.0 * DT)
            if f["Nivel"] <= 0:
                f.update(Fase=0, Lote=0, NombreReceta="", Dia=0.0, Densidad=0.0, DensidadOriginal=0.0,
                         DensidadObjetivo=0.0, Atenuacion=0.0, Presion=0.0)
                self.fv_recipe[fv] = None
                phase = 0
        if phase == 0:
            f.update(Desviacion=0.0, ValvulaGlicol=0.0, FermentacionParada=False, ConsignaTemp=0.0, Presion=0.0)
            f["Temperatura"] = lag(f["Temperatura"], CELLAR_C - 4.0, 30.0)
            self.integral[fv] = 0.0
            f["Alarma"] = False
            return

        recipe = self.fv_recipe[fv]
        setpoint = self.phase_setpoint(fv, min(phase, 6)) if f["Automatico"] else f["ConsignaManual"]
        f["ConsignaTemp"] = setpoint

        # Yeast: lag phase, then first-order attenuation towards the final gravity.
        rate = 0.0
        if phase in (2, 3) and recipe is not None:
            activity = 0.0 if f["SimFermentacionParada"] and phase == 2 else min(1.0, f["Dia"] / 0.7)
            warmth = clamp(1.0 + 0.08 * (f["Temperatura"] - recipe["TempFermentacion"]), 0.2, 1.6)
            if f["Temperatura"] < 8.0:
                warmth *= 0.2
            rate = self.rate_constant(recipe) * warmth * activity * max(0.0, f["Densidad"] - recipe["DensidadFinal"])
            f["Densidad"] -= rate * DAYS

        # Glycol jacket: PI on the temperature, stuck closed in the training fault.
        error = f["Temperatura"] - setpoint
        if phase == 1:
            error = max(error, 0.0)
        self.integral[fv] = clamp(self.integral[fv] + 300.0 * error * DAYS, 0.0, 100.0)
        valve = clamp(60.0 * error + self.integral[fv], 0.0, 100.0)
        if f["SimValvulaAtascada"] or (phase == 3 and error < 0):
            valve = 0.0  # diacetyl rest: free rise, never chilled below the setpoint
        f["ValvulaGlicol"] = valve
        heat = 2.5 * rate + 0.5 * (CELLAR_C - f["Temperatura"])
        cooling = 3.0 * max(0.0, f["Temperatura"] - s["TempGlicol"]) * valve / 100.0
        f["Temperatura"] += (heat - cooling) * DAYS

        # CO2: the spunding valve holds 1 bar; jammed, the pressure climbs to the relief valve.
        if f["SimSobrepresion"]:
            f["Presion"] = min(RELIEF_BAR, f["Presion"] + 0.25 * rate * DAYS + 0.3 * DAYS)
        else:
            # Cold crash: part of the CO2 dissolves back into the beer.
            f["Presion"] = clamp(f["Presion"] + 0.4 * rate * DAYS - (0.3 * DAYS if phase == 4 else 0.0), 0.0, SPUNDING_BAR)

        if phase >= 2:
            f["Dia"] += DAYS
        f["Atenuacion"] = (f["DensidadOriginal"] - f["Densidad"]) / f["DensidadOriginal"] * 100.0 if f["DensidadOriginal"] else 0.0

        # A stuck fermentation: the gravity no longer falls although the target is far.
        history = self.history[fv]
        if not history or f["Dia"] - history[-1][0] >= 0.25:
            history.append((f["Dia"], f["Densidad"]))
        day_ago = next((d for t, d in history if 0.75 <= f["Dia"] - t <= 1.25), None)
        f["FermentacionParada"] = (phase == 2 and recipe is not None and f["Dia"] > 1.5 and day_ago is not None
                                   and f["Densidad"] > recipe["DensidadFinal"] + 1.0 and day_ago - f["Densidad"] < 0.2)

        # Deviation alarms only where the PLC actually holds a temperature.
        if phase in (2, 5, 6) and f["Dia"] > 0.3:
            f["Desviacion"] = error
        elif phase == 3:
            f["Desviacion"] = max(0.0, error)
        else:
            f["Desviacion"] = 0.0

        if recipe is not None:
            elapsed = f["Dia"] - self.phase_start[fv]
            if phase == 2 and f["Dia"] >= recipe["DiasFermentacion"] and f["Densidad"] <= recipe["DensidadFinal"] + 0.3:
                self.next_phase(fv, 3 if recipe["DiasDiacetilo"] > 0 else 4)
            elif phase == 3 and elapsed >= recipe["DiasDiacetilo"]:
                self.next_phase(fv, 4)
            elif phase == 4 and f["Temperatura"] <= recipe["TempGuarda"] + 0.5:
                self.next_phase(fv, 5)
            elif phase == 5 and elapsed >= recipe["DiasGuarda"]:
                self.next_phase(fv, 6)
        f["Alarma"] = abs(f["Desviacion"]) > 1.5 or f["Presion"] > 1.6 or f["FermentacionParada"]

    def next_phase(self, fv, phase):
        self.v[fv]["Fase"] = phase
        self.phase_start[fv] = self.v[fv]["Dia"]

    # ------------------------------------------------------------------ published values
    def published(self):
        """Values as the PLC publishes them: measurements carry a little sensor noise."""
        noisy = {"TempMT", "TempBK", "TempMostoSalida", "Temperatura", "TempHLT", "TempGlicol", "TempAguaFria"}
        result = {}
        for obj, fields in self.v.items():
            for name, value in fields.items():
                if obj in FERMENTERS and name == "Fase" and value == 7:
                    value = 6
                elif name in noisy and isinstance(value, float):
                    value = round(value + random.gauss(0.0, 0.03), 2)
                result[f"{obj}.{name}"] = value
        return result


# ---------------------------------------------------------------------- OPC UA server
def certificate_folder():
    from ..app_paths import state_root
    return state_root() / "simuladores" / "cerveceria"


class BreweryServer:
    """asyncua server on its own thread; the PLC scan runs on the same event loop."""

    def __init__(self, host="127.0.0.1", port=PORT, folder=None, plant=None):
        self.host, self.port = host, port
        self.folder = folder or certificate_folder()
        self.plant = plant or Brewery()
        self.lock = threading.Lock()
        self.thread = self.loop = self.stopping = None
        self.ready = threading.Event()
        self.error = ""

    @property
    def endpoint(self):
        return f"opc.tcp://{self.host}:{self.port}/latolva"

    def start(self, timeout=20):
        with socket.socket() as probe:
            probe.settimeout(0.3)
            if probe.connect_ex((self.host, self.port)) == 0:
                raise RuntimeError(f"Puerto {self.port} ya en uso (¿hay otro simulador abierto?)")
        self.thread = threading.Thread(target=self._thread, name="brewery-plc", daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout) or self.error:
            self.stop()
            raise RuntimeError(self.error or "El servidor OPC UA del simulador no arranca")
        return self

    def stop(self, timeout=5):
        if self.loop and self.stopping and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.stopping.set)
        if self.thread:
            self.thread.join(timeout)
            self.thread = None

    def _thread(self):
        self.loop = asyncio.new_event_loop()
        try:
            self.loop.run_until_complete(self._main())
        except Exception as exc:
            self.error = f"Simulador de cervecería: {exc}"
        finally:
            self.ready.set()
            self.loop.close()

    async def _main(self):
        from asyncua import Server, ua
        from .. import pki

        self.stopping = asyncio.Event()
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("La Tolva · PLC de cervecería (simulado)")
        uri = f"urn:{socket.gethostname().lower()}:latolva:plc"
        await server.set_application_uri(uri)
        certificate, key = pki.ensure_own_certificate(self.folder, uri, "La Tolva PLC (simulado)")
        await server.load_certificate(str(certificate))
        await server.load_private_key(str(key))
        server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                                    ua.SecurityPolicyType.Basic256Sha256_Sign])
        index = await server.register_namespace(NAMESPACE)
        variant = {"bool": ua.VariantType.Boolean, "int": ua.VariantType.Int32,
                   "float": ua.VariantType.Float, "string": ua.VariantType.String}
        nodes, writable = {}, {}
        top = await server.nodes.objects.add_folder(ua.NodeId("LaTolva", index), "LaTolva")
        values = self.plant.published()
        for obj, fields in OBJECTS:
            parent = await top.add_object(ua.NodeId(obj, index), obj)
            for name, kind, *rest in fields:
                key = f"{obj}.{name}"
                node = await parent.add_variable(ua.NodeId(key, index), name, ua.Variant(values[key], variant[kind]))
                if rest and rest[0]:
                    await node.set_writable()
                    writable[key] = values[key]
                nodes[key] = (node.nodeid, variant[kind])
        published = dict(values)
        async with server:
            self.ready.set()
            while not self.stopping.is_set():
                # Client writes land in the address space; the PLC copies them in before scanning.
                for key in writable:
                    node_id, _ = nodes[key]
                    value = server.read_attribute_value(node_id).Value.Value
                    if value != published[key]:
                        obj, name = key.split(".", 1)
                        self.plant.v[obj][name] = value
                        published[key] = value
                with self.lock:
                    self.plant.scan()
                    values = self.plant.published()
                for key, value in values.items():
                    if value != published[key]:
                        node_id, kind = nodes[key]
                        if kind == ua.VariantType.Int32:
                            value = int(value)
                        elif kind == ua.VariantType.Float:
                            value = float(value)
                        await server.write_attribute_value(node_id, ua.DataValue(ua.Variant(value, kind)))
                        published[key] = value
                try:
                    await asyncio.wait_for(self.stopping.wait(), DT)
                except asyncio.TimeoutError:
                    pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    try:
        server = BreweryServer(port=args.port).start()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    from .. import pki
    der = (pki.pki_root(server.folder) / "own" / "plc.der").read_bytes()
    print(f"PLC de la cervecería simulado en {server.endpoint}\n"
          f"Certificado del servidor: huella {pki.fingerprint(der)}. Ctrl+C para detener.", flush=True)
    try:
        while server.thread and server.thread.is_alive():
            server.thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
