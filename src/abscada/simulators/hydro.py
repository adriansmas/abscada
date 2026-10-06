"""External PLCs for examples/hydro: two unit PLCs, a common-services PLC and a
Modbus energy meter, running a simplified model of a two-unit Francis plant.

Never imported by Runtime. Start it in its own terminal:

    abscada --simulador hydro          (or: python -m abscada --simulador hydro)

Timings are compressed so a full start takes about 45 s instead of minutes, and
the reservoir responds ~200x faster than reality so level changes are visible.
"""
import argparse
import math
import random
import socket
import struct
import time
from threading import Event, Thread

from .hydro_map import (COMMON_DB_SIZE, COMMON_FIELDS, METER_FIELDS, PORTS,
                        UNIT_DB_SIZE, UNIT_FIELDS)

DT = 0.1
RESERVOIR_SPEEDUP = 200.0
RATED_MW = 10.0
RATED_KV = 6.3
RATED_RPM = 600.0
Q_DESIGN = 14.5          # m3/s at full gate and design head
H_DESIGN = 82.0          # m
TAILWATER_BASE = 730.0   # m a.s.l.
SPILL_CREST = 808.0      # m a.s.l.
NMN = 815.0              # maximum normal level
AREA_M2 = 1.8e6          # reservoir surface

# Trip thresholds (alarms in the SCADA sit below these)
TRIP_GUIDE, TRIP_THRUST, TRIP_STATOR = 80.0, 85.0, 130.0
TRIP_VIBRATION, TRIP_OIL, TRIP_OVERSPEED = 7.1, 45.0, 115.0


class Block:
    """Typed access to a DB byte array through the shared address map."""

    def __init__(self, fields, size):
        self.memory = bytearray(size)
        self.fields = {name: address for name, _, address, _ in fields}
        self.types = {name: kind for name, kind, _, _ in fields}

    def _locate(self, name):
        address = self.fields[name].upper().replace("%DB1.DB", "")
        if address.startswith("X"):
            byte, bit = address[1:].split(".")
            return int(byte), int(bit)
        return int(address[1:]), None

    def __getitem__(self, name):
        offset, bit = self._locate(name)
        if bit is not None:
            return bool(self.memory[offset] & (1 << bit))
        fmt = ">i" if self.types[name] == "int" else ">f"
        return struct.unpack_from(fmt, self.memory, offset)[0]

    def __setitem__(self, name, value):
        offset, bit = self._locate(name)
        if bit is not None:
            if value:
                self.memory[offset] |= 1 << bit
            else:
                self.memory[offset] &= ~(1 << bit) & 0xFF
            return
        if self.types[name] == "int":
            struct.pack_into(">i", self.memory, offset, int(value))
        else:
            struct.pack_into(">f", self.memory, offset, float(value))


def approach(value, target, rate):
    """Move value towards target by at most rate * DT."""
    step = rate * DT
    return target if abs(target - value) <= step else value + math.copysign(step, target - value)


def lag(value, target, tau):
    return value + (target - value) * min(1.0, DT / tau)


class Unit:
    """Unit control PLC: sequences, governor, protections and machine physics."""

    def __init__(self, name):
        self.name = name
        self.db = Block(UNIT_FIELDS, UNIT_DB_SIZE)
        self.timer = 0.0
        self.cooling_fault_time = 0.0
        db = self.db
        db["ConsignaP"] = 8.0
        db["ConsignaQ"] = 1.0
        db["PresionOleo"] = 60.0
        db["ValvulaCerrada"] = True
        db["Frenos"] = True
        db["Energia"] = random.uniform(51000, 64000)
        db["HorasMarcha"] = random.uniform(41000, 47000)
        db["Arranques"] = random.randint(3100, 3900)
        for field in ("TempGuiaSup", "TempEmpuje", "TempGuiaTurbina", "TempEstator", "TempAceite"):
            db[field] = 24.0
        db["CosPhi"] = 1.0

    # -- helpers -------------------------------------------------------------
    def goto(self, step):
        self.db["Paso"] = step
        self.timer = 0.0

    def trip(self, cause):
        db = self.db
        if db["Paso"] in (0, 10):
            return
        db["CausaDisparo"] = cause
        db["Disparo"] = True
        db["Interruptor52G"] = False
        db["InterruptorCampo"] = False
        self.goto(10)

    # -- one PLC scan --------------------------------------------------------
    def scan(self, plant):
        db = self.db
        step = db["Paso"]
        self.timer += DT
        db["Remoto"] = not db["SimLocal"]
        grid = plant.common["RedPresente"] and plant.common["Interruptor52L"]
        oil_ok = db["PresionOleo"] > 55.0
        db["ListoArranque"] = (step == 0 and db["Remoto"] and not db["Disparo"] and oil_ok and grid
                               and plant.common["CompuertaTomaAbierta"] and plant.common["NivelEmbalse"] > 800.5)

        # Commands are pulses: always cleared after the scan reads them.
        start, stop, estop, reset = (db["OrdenArranque"], db["OrdenParada"],
                                     db["OrdenEmergencia"], db["OrdenRearme"])
        for field in ("OrdenArranque", "OrdenParada", "OrdenEmergencia", "OrdenRearme"):
            db[field] = False
        if estop:
            self.trip(1)
        elif db["Remoto"]:
            if start and db["ListoArranque"]:
                self.goto(1)
            elif stop and 1 <= step <= 6:
                self.goto(7 if db["Acoplado"] else 9)
            elif reset and step == 10 and db["Velocidad"] < 1.0:
                db["Disparo"] = False
                db["CausaDisparo"] = 0
                self.goto(0)
        step = db["Paso"]

        self._sequence(step, plant, grid)
        self._hydraulics(plant)
        self._electrical(plant)
        self._thermal(plant)
        self._protections(grid)
        db["AlarmaGrupo"] = (db["Disparo"] or db["TempGuiaSup"] > 70 or db["TempEmpuje"] > 75
                             or db["TempEstator"] > 110 or db["Vibracion"] > 4.5
                             or db["PresionOleo"] < 52 or db["FalloRefrigeracion"])

    def _sequence(self, step, plant, grid):
        db = self.db
        if step == 0:
            db["Refrigeracion"] = False
            db["Frenos"] = True
        elif step == 1:  # auxiliaries: cooling water, oil pumps, release brakes
            db["Refrigeracion"] = True
            db["Frenos"] = False
            if self.timer > 4.0:
                self.goto(2)
        elif step == 2:  # main inlet valve: bypass, equalise, open
            if self.timer > 2.0:
                db["PosValvula"] = approach(db["PosValvula"], 100.0, 14.0)
            if db["PosValvula"] >= 99.9:
                self.goto(3)
        elif step == 3:  # acceleration to rated speed on speed control
            target = 15.0 if db["Velocidad"] < 95.0 else 11.0
            db["Distribuidor"] = approach(db["Distribuidor"], target, 3.0)
            if db["Velocidad"] >= 99.0 and self.timer > 3.0:
                self.goto(4)
        elif step == 4:  # field breaker and voltage build-up
            db["InterruptorCampo"] = True
            if db["Tension"] >= RATED_KV * 0.98:
                self.goto(5)
        elif step == 5:  # synchroniser matches frequency and phase, closes 52G
            if self.timer > 3.0 and grid:
                db["Interruptor52G"] = True
                db["Arranques"] = db["Arranques"] + 1
                self.goto(6)
        elif step == 7:  # unload to zero before opening the breaker
            if db["Potencia"] < 0.3:
                self.goto(8)
        elif step == 8:  # open 52G and field breaker
            db["Interruptor52G"] = False
            if self.timer > 1.0:
                db["InterruptorCampo"] = False
            if self.timer > 2.0:
                self.goto(9)
        elif step == 9:  # close gates and valve, brake below 20 % speed
            db["Distribuidor"] = approach(db["Distribuidor"], 0.0, 4.0)
            db["PosValvula"] = approach(db["PosValvula"], 0.0, 12.0)
            db["Frenos"] = db["Velocidad"] < 20.0
            if db["Velocidad"] < 0.5 and db["PosValvula"] <= 0.0:
                self.goto(0)
        elif step == 10:  # trip: fast closure, lockout until reset
            db["Distribuidor"] = approach(db["Distribuidor"], 0.0, 20.0)
            db["PosValvula"] = approach(db["PosValvula"], 0.0, 15.0)
            db["Frenos"] = db["Velocidad"] < 20.0
            db["Refrigeracion"] = db["Velocidad"] > 0.5
        db["Acoplado"] = db["Interruptor52G"]
        db["ValvulaAbierta"] = db["PosValvula"] >= 99.9
        db["ValvulaCerrada"] = db["PosValvula"] <= 0.1

    def _hydraulics(self, plant):
        db = self.db
        step = db["Paso"]
        head = plant.net_head
        gate = db["Distribuidor"]
        valve = db["PosValvula"] / 100.0
        flow = Q_DESIGN * gate / 100.0 * math.sqrt(max(head, 0.0) / H_DESIGN) * min(1.0, valve * 1.2)
        efficiency = max(0.0, 0.93 - 0.9 * (gate / 100.0 - 0.8) ** 2) if gate > 6 else 0.0
        hydraulic_mw = 9.81 * flow * head * efficiency / 1000.0
        db["Caudal"] = flow

        if db["Acoplado"]:
            # Governor in power control: gate follows the setpoint, rate limited.
            setpoint = 0.0 if step == 7 else max(0.0, min(RATED_MW, db["ConsignaP"]))
            error = setpoint - db["Potencia"]
            db["Distribuidor"] = max(0.0, min(100.0, db["Distribuidor"] + max(-4.0, min(4.0, error * 6.0)) * DT))
            db["Potencia"] = lag(db["Potencia"], hydraulic_mw, 1.5)
            db["Velocidad"] = 100.0 * plant.common["FrecuenciaRed"] / 50.0
        else:
            db["Potencia"] = lag(db["Potencia"], 0.0, 0.5)
            no_load_gate = 11.0
            target = 0.0 if gate < 2 or valve < 0.05 else min(135.0, 100.0 * math.sqrt(gate / no_load_gate))
            if step == 3 and db["Velocidad"] >= 95.0:
                target = 100.0 + random.uniform(-0.15, 0.15)
            tau = 4.0 if target > db["Velocidad"] else 9.0
            db["Velocidad"] = max(0.0, lag(db["Velocidad"], target, tau) - (0.6 * DT if db["Frenos"] else 0.0))
        db["VelocidadRpm"] = db["Velocidad"] / 100.0 * RATED_RPM
        db["ZonaRugosa"] = db["Acoplado"] and 25.0 < db["Distribuidor"] < 45.0
        db["PresionEspiral"] = (0.0981 * plant.gross_head * valve - 0.004 * flow ** 2) if valve > 0.01 else 0.4

        # Oil pressure unit: consumption grows with gate movement, pump hysteresis 56/63 bar.
        consumption = 0.10 + (0.25 if 1 <= step <= 10 and step != 6 else 0.05)
        if db["PresionOleo"] < 56.0:
            db["BombaOleo"] = True
        elif db["PresionOleo"] > 63.0:
            db["BombaOleo"] = False
        db["PresionOleo"] += (1.1 if db["BombaOleo"] else 0.0) * DT - consumption * DT
        db["FalloBombaOleo"] = db["BombaOleo"] and db["PresionOleo"] < 52.0

    def _electrical(self, plant):
        db = self.db
        excited = db["InterruptorCampo"]
        speed_ratio = db["Velocidad"] / 100.0
        target_kv = RATED_KV * speed_ratio + 0.05 * db["Reactiva"] if excited else 0.0
        db["Tension"] = lag(db["Tension"], target_kv, 1.2)
        db["Frecuencia"] = 50.0 * speed_ratio
        if db["Acoplado"]:
            db["Reactiva"] = approach(db["Reactiva"], max(-3.0, min(5.0, db["ConsignaQ"])), 0.5)
        else:
            db["Reactiva"] = lag(db["Reactiva"], 0.0, 0.5)
        p, q, v = db["Potencia"], db["Reactiva"], max(db["Tension"], 0.01)
        apparent = math.hypot(p, q)
        db["CosPhi"] = p / apparent if apparent > 0.05 else 1.0
        db["Intensidad"] = apparent * 1e6 / (math.sqrt(3) * v * 1e3) if db["Acoplado"] else 0.0
        db["CorrienteExcitacion"] = (180.0 * speed_ratio + 28.0 * p + 55.0 * q) if excited else 0.0
        if db["Acoplado"]:
            db["Energia"] = db["Energia"] + p * DT / 3600.0
            db["HorasMarcha"] = db["HorasMarcha"] + DT / 3600.0

    def _thermal(self, plant):
        db = self.db
        load = db["Potencia"] / RATED_MW
        spinning = db["Velocidad"] / 100.0
        ambient = plant.common["TempAmbiente"]
        cooling = db["Refrigeracion"] and not db["SimRefrigeracion"]
        db["CaudalRefrigeracion"] = lag(db["CaudalRefrigeracion"],
                                        (31.0 + random.uniform(-0.6, 0.6)) if cooling else (7.0 if db["Refrigeracion"] else 0.0), 2.0)
        if db["Refrigeracion"] and db["CaudalRefrigeracion"] < 15.0:
            self.cooling_fault_time += DT
        else:
            self.cooling_fault_time = 0.0
        db["FalloRefrigeracion"] = self.cooling_fault_time > 5.0
        extra = 38.0 if db["FalloRefrigeracion"] else 0.0
        targets = {
            "TempGuiaSup": ambient + 4 + spinning * 18 + load * 10 + extra * 0.8,
            "TempEmpuje": ambient + 5 + spinning * 20 + load * 14 + extra + (32.0 if db["SimCojinete"] else 0.0),
            "TempGuiaTurbina": ambient + 3 + spinning * 16 + load * 9 + extra * 0.7,
            "TempEstator": ambient + 2 + spinning * 15 + load * 48 + extra * 1.6,
            "TempAceite": ambient + 2 + spinning * 14 + load * 8 + extra * 0.6,
        }
        for field, target in targets.items():
            db[field] = lag(db[field], target, 25.0 if field != "TempEstator" else 35.0)
        rough = 2.6 if db["ZonaRugosa"] else 0.0
        vibration = (0.6 + 0.9 * spinning + 0.5 * load + rough + (6.5 if db["SimVibracion"] and spinning > 0.2 else 0.0)) if spinning > 0.02 else 0.0
        db["Vibracion"] = max(0.0, lag(db["Vibracion"], vibration, 1.5) + random.uniform(-0.05, 0.05) * spinning)

    def _protections(self, grid):
        db = self.db
        if db["Paso"] in (0, 10):
            return
        if db["Acoplado"] and not grid:
            db["Velocidad"] = min(128.0, db["Velocidad"] + 18.0)  # load rejection
            self.trip(7)
        elif max(db["TempGuiaSup"], db["TempGuiaTurbina"]) > TRIP_GUIDE or db["TempEmpuje"] > TRIP_THRUST:
            self.trip(2)
        elif db["Velocidad"] > TRIP_OVERSPEED:
            self.trip(3)
        elif db["Vibracion"] > TRIP_VIBRATION:
            self.trip(4)
        elif db["PresionOleo"] < TRIP_OIL:
            self.trip(5)
        elif db["TempEstator"] > TRIP_STATOR:
            self.trip(6)


class Plant:
    def __init__(self):
        self.units = [Unit("G1"), Unit("G2")]
        self.common = Block(COMMON_FIELDS, COMMON_DB_SIZE)
        self.elapsed = 0.0
        self.rain_timer = 0.0
        self.grid_restore = 0.0
        self.diesel_timer = 0.0
        self.export_kwh = random.uniform(182e6, 186e6)
        self.import_kwh = random.uniform(410_000, 450_000)
        c = self.common
        c["NivelEmbalse"] = 812.4
        c["CompuertaTomaAbierta"] = True
        c["PosCompuertaToma"] = 100.0
        c["Interruptor52L"] = True
        c["RedPresente"] = True
        c["CargadorOk"] = True
        c["TrafoAuxOk"] = True
        c["AliviaderoAuto"] = True
        c["TensionBaterias"] = 125.4
        c["Tension400V"] = 400.0       # start energised: no spurious alarms on the first scans
        c["TensionBarras66"] = 66.0
        c["PresionAire"] = 7.6
        c["NivelPozo"] = 35.0
        c["FrecuenciaRed"] = 50.0
        c["TempAmbiente"] = 18.0
        c["CaudalEcologico"] = 0.6
        self.gross_head = H_DESIGN
        self.net_head = H_DESIGN

    def scan(self):
        self.elapsed += DT
        self._common()
        for unit in self.units:
            unit.scan(self)

    def _common(self):
        c = self.common
        t = self.elapsed
        # Weather and inflow: daily wave, rain showers, optional flood.
        self.rain_timer -= DT
        if self.rain_timer <= 0:
            self.rain_timer = random.uniform(60, 240)
            c["Lluvia"] = random.choice([0.0, 0.0, 0.0, 0.8, 2.5, 6.0])
        base_inflow = 17.0 + 4.0 * math.sin(t / 300.0) + 1.6 * c["Lluvia"]
        if c["SimAvenida"]:
            base_inflow = 135.0
        c["CaudalEntrada"] = lag(c["CaudalEntrada"], base_inflow + random.uniform(-0.4, 0.4), 20.0)
        c["TempAmbiente"] = 17.0 + 5.0 * math.sin(t / 900.0)

        # Spillway: two radial gates, automatic level control above 814.6 m.
        level = c["NivelEmbalse"]
        if c["AliviaderoAuto"]:
            demand = max(0.0, min(100.0, (level - 814.6) * 160.0))
            c["ConsignaCompuerta1"] = demand
            c["ConsignaCompuerta2"] = max(0.0, demand - 40.0) * 100.0 / 60.0
        for gate in ("1", "2"):
            setpoint = max(0.0, min(100.0, c["ConsignaCompuerta" + gate]))
            c["PosCompuerta" + gate] = approach(c["PosCompuerta" + gate], setpoint, 2.0)
        over_crest = max(0.0, level - SPILL_CREST)
        spill = sum(0.6 * 8.0 * (c["PosCompuerta" + g] / 100.0 * 6.0) * math.sqrt(2 * 9.81 * over_crest) for g in ("1", "2"))
        c["CaudalAliviadero"] = spill

        # Intake gate commands (closing only with both units stopped).
        stopped = all(u.db["Paso"] == 0 for u in self.units)
        if c["OrdenAbrirToma"]:
            self.intake_target = 100.0
        if c["OrdenCerrarToma"] and stopped:
            self.intake_target = 0.0
        c["OrdenAbrirToma"] = c["OrdenCerrarToma"] = False
        c["PosCompuertaToma"] = approach(c["PosCompuertaToma"], getattr(self, "intake_target", 100.0), 2.5)
        c["CompuertaTomaAbierta"] = c["PosCompuertaToma"] >= 99.9
        c["CompuertaTomaCerrada"] = c["PosCompuertaToma"] <= 0.1

        turbine_flow = sum(u.db["Caudal"] for u in self.units)
        eco = 0.6 if level > 800.0 else 0.0
        c["CaudalEcologico"] = eco
        outflow = turbine_flow + spill + eco
        c["CaudalSalida"] = outflow
        level += (c["CaudalEntrada"] - outflow) * DT * RESERVOIR_SPEEDUP / AREA_M2
        c["NivelEmbalse"] = max(798.0, min(817.0, level))
        c["Volumen"] = 5.0 + AREA_M2 * (c["NivelEmbalse"] - 800.0) / 1e6
        c["NivelDesague"] = TAILWATER_BASE + 0.045 * outflow ** 0.75
        self.gross_head = c["NivelEmbalse"] - c["NivelDesague"]
        self.net_head = max(0.0, self.gross_head - 0.009 * turbine_flow ** 2)
        c["SaltoBruto"] = self.gross_head
        c["PresionTuberia"] = (0.0981 * self.gross_head - 0.0009 * turbine_flow ** 2) * c["PosCompuertaToma"] / 100.0

        # Grid and 66 kV substation.
        if c["SimFalloRed"]:
            c["RedPresente"] = False
            self.grid_restore = 5.0
        elif not c["RedPresente"]:
            self.grid_restore -= DT
            c["RedPresente"] = self.grid_restore <= 0
        if not c["RedPresente"]:
            c["Interruptor52L"] = False
        if c["OrdenAbrir52L"]:
            c["Interruptor52L"] = False
        if c["OrdenCerrar52L"] and c["RedPresente"]:
            c["Interruptor52L"] = True
        c["OrdenAbrir52L"] = c["OrdenCerrar52L"] = False
        live = c["RedPresente"] and c["Interruptor52L"]
        c["TensionBarras66"] = lag(c["TensionBarras66"], (66.0 + random.uniform(-0.3, 0.3)) if live else 0.0, 0.5)
        c["FrecuenciaRed"] = (max(49.9, min(50.1, c["FrecuenciaRed"] + random.uniform(-0.004, 0.004)))
                              if c["RedPresente"] else 50.0)

        # Auxiliary services: 400 V, diesel back-up, DC battery, air, drainage.
        c["TrafoAuxOk"] = live
        if not live:
            self.diesel_timer += DT
        else:
            self.diesel_timer = 0.0
        c["GrupoDiesel"] = not live and self.diesel_timer > 3.0
        c["Tension400V"] = lag(c["Tension400V"], (400.0 + random.uniform(-2, 2)) if (live or self.diesel_timer > 8.0) else 0.0, 0.8)
        charger = not c["SimFalloCargador"] and c["Tension400V"] > 360
        c["CargadorOk"] = charger
        c["TensionBaterias"] = lag(c["TensionBaterias"], 125.4 if charger else 98.0, 4.0 if charger else 60.0)
        if c["PresionAire"] < 7.0:
            c["Compresor"] = True
        elif c["PresionAire"] > 8.0:
            c["Compresor"] = False
        c["PresionAire"] += (0.06 if c["Compresor"] else 0.0) * DT - 0.008 * DT
        inflow_sump = 0.35 + (0.15 if c["SimAvenida"] else 0.0)
        if c["NivelPozo"] > 60:
            c["BombaDrenaje1"] = True
        elif c["NivelPozo"] < 20:
            c["BombaDrenaje1"] = False
        if c["NivelPozo"] > 78:
            c["BombaDrenaje2"] = True
        elif c["NivelPozo"] < 30:
            c["BombaDrenaje2"] = False
        c["NivelPozo"] = max(0.0, c["NivelPozo"] + (inflow_sump - 1.1 * c["BombaDrenaje1"] - 1.1 * c["BombaDrenaje2"]) * DT)
        c["FalloDrenaje"] = c["NivelPozo"] > 85.0
        c["FalloCompresor"] = c["Compresor"] and c["PresionAire"] < 6.0

        c["AlarmaPresa"] = (c["NivelEmbalse"] > 814.5 or c["NivelEmbalse"] < 802.0
                            or c["CaudalEntrada"] > 60.0)
        c["AlarmaSubestacion"] = not c["RedPresente"] or not c["Interruptor52L"]
        c["AlarmaAuxiliares"] = (not c["CargadorOk"] or c["TensionBaterias"] < 110.0
                                 or c["NivelPozo"] > 80.0 or c["PresionAire"] < 6.0 or c["GrupoDiesel"])

    def meter(self):
        p = sum(u.db["Potencia"] for u in self.units) - 0.12
        q = sum(u.db["Reactiva"] for u in self.units) + 0.05
        if p > 0:
            self.export_kwh += p * 1000.0 * DT / 3600.0
        else:
            self.import_kwh += -p * 1000.0 * DT / 3600.0
        live = self.common["TensionBarras66"] > 10.0
        return dict(Potencia=p if live else 0.0, Reactiva=q if live else 0.0,
                    Tension=self.common["TensionBarras66"], Frecuencia=self.common["FrecuenciaRed"],
                    CosPhi=(p / math.hypot(p, q)) if live and abs(p) > 0.05 else 1.0,
                    EnergiaExportada=int(self.export_kwh), EnergiaImportada=int(self.import_kwh))


def port_in_use(host, port):
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex((host, port)) == 0


def words(encoding, value):
    data = struct.pack(">f" if encoding == "float32" else ">I", value)
    return list(struct.unpack(">HH", data))


class HydroPLCs:
    """TCP endpoints: three S7 servers and one Modbus server, plus the model thread."""

    def __init__(self, host="127.0.0.1", ports=None):
        self.host = host
        self.ports = dict(PORTS, **(ports or {}))
        self.plant = Plant()
        self.servers = []
        self.modbus = None
        self.thread = None
        self.stop_event = Event()

    def start(self):
        from snap7.server import Server
        from snap7.type import SrvArea
        from pyModbusTCP.server import ModbusServer
        # snap7 may share a busy port silently on Windows: refuse instead of mixing two plants.
        busy = [f"{name} :{port}" for name, port in self.ports.items() if port_in_use(self.host, port)]
        if busy:
            raise RuntimeError("Puertos ya en uso (¿hay otro simulador abierto?): " + ", ".join(busy))
        try:
            blocks = [("PLC_G1", self.plant.units[0].db), ("PLC_G2", self.plant.units[1].db), ("PLC_SSCC", self.plant.common)]
            for name, block in blocks:
                server = Server(log=False)
                server.host = self.host
                server.register_area(SrvArea.DB, 1, block.memory)
                server.start(tcp_port=self.ports[name])
                self.servers.append(server)
            self.modbus = ModbusServer(host=self.host, port=self.ports["Contador_66kV"], no_block=True)
            self.modbus.start()
            if not self.modbus.is_run:
                raise RuntimeError("No se pudo abrir el puerto Modbus del contador")
            self.thread = Thread(target=self._run, name="hydro-plant", daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.stop()
            raise

    def _run(self):
        next_tick = time.monotonic()
        while not self.stop_event.is_set():
            self.plant.scan()
            values = self.plant.meter()
            bank = self.modbus.data_bank
            bank.set_discrete_inputs(0, [True])
            registers = []
            for name, _, area, offset, encoding, _ in METER_FIELDS:
                if area == "input_registers":
                    registers[offset:offset + 2] = words(encoding, values[name])
            bank.set_input_registers(0, registers)
            next_tick += DT
            self.stop_event.wait(max(0.0, next_tick - time.monotonic()))

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            self.thread = None
        if self.modbus:
            self.modbus.stop()
            self.modbus = None
        for server in self.servers:
            server.stop()
            server.destroy()
        self.servers = []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    try:
        plcs = HydroPLCs().start()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    ports = ", ".join(f"{name} :{port}" for name, port in plcs.ports.items())
    print(f"Central hidroeléctrica simulada en 127.0.0.1 → {ports}. Ctrl+C para detener.", flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        plcs.stop()


if __name__ == "__main__":
    main()
