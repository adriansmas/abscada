"""Write SYNTHETIC history for examples/hydro: the 7 days before today, one sample per minute.

Gives the trend viewers something to show in «Histórico» mode on a fresh copy.
The data follows a plausible daily dispatch (two peaks, a rain episode) but is
generated, never read from a PLC; every file records that in its audit table.
Run it with Runtime closed:

    .venv\\Scripts\\python tools/seed_hydro_history.py [examples/hydro]
"""
import argparse
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from abscada.project import Project
from abscada.recording import path
from abscada.runtime import Sample
from abscada.storage import Repository, RuntimeLease

STEP_S = 60
DAYS = 7


def dispatch(hour):
    """Scheduled MW per unit for a given hour of the day (peaks morning and evening)."""
    g1 = 0.0
    if 6.5 <= hour < 23.5:
        g1 = 9.2 if hour < 14 else (6.0 if hour < 18 else 9.6)
    g2 = 8.5 if (8 <= hour < 14 or 18.5 <= hour < 23) else 0.0
    return g1, g2


class Model:
    """Very small plant model integrated minute by minute."""

    def __init__(self, rng):
        self.rng = rng
        self.level = 812.2
        self.temps = {u: dict(GuiaSup=24.0, Empuje=25.0, GuiaTurbina=23.0, Estator=22.0, Aceite=22.0) for u in ("G1", "G2")}
        self.sump = 40.0
        self.air = 7.5

    def step(self, when):
        rng = self.rng
        hour = when.hour + when.minute / 60.0
        day = when.timetuple().tm_yday
        rain = 4.0 if day % 7 in (2, 3) and 3 <= hour <= 17 else 0.0
        inflow = 17.0 + 4.0 * math.sin((hour - 6) / 24 * 2 * math.pi) + 2.5 * rain + rng.uniform(-0.5, 0.5)
        ambient = 15.0 + 6.0 * math.sin((hour - 9) / 24 * 2 * math.pi)
        head = self.level - 730.3
        values = {}
        flow_total = power_total = 0.0
        for unit, mw in zip(("G1", "G2"), dispatch(hour)):
            on = mw > 0
            p = mw + rng.uniform(-0.05, 0.05) if on else 0.0
            gate = (12.0 + 7.9 * p) if on else 0.0
            flow = 14.5 * gate / 100.0 * math.sqrt(head / 82.0) if on else 0.0
            load, spin = p / 10.0, 1.0 if on else 0.0
            targets = dict(GuiaSup=ambient + 4 + spin * 18 + load * 10, Empuje=ambient + 5 + spin * 20 + load * 14,
                           GuiaTurbina=ambient + 3 + spin * 16 + load * 9, Estator=ambient + 2 + spin * 15 + load * 48,
                           Aceite=ambient + 2 + spin * 14 + load * 8)
            for name, target in targets.items():  # 15-minute thermal time constant
                self.temps[unit][name] += (target - self.temps[unit][name]) * (STEP_S / 900.0)
            flow_total += flow
            power_total += p
            values.update({
                f"{unit}.Potencia": p, f"{unit}.Reactiva": (1.0 + rng.uniform(-0.05, 0.05)) if on else 0.0,
                f"{unit}.Tension": (6.3 + rng.uniform(-0.03, 0.03)) if on else 0.0,
                f"{unit}.Frecuencia": (50.0 + rng.uniform(-0.03, 0.03)) if on else 0.0,
                f"{unit}.Velocidad": (100.0 + rng.uniform(-0.05, 0.05)) if on else 0.0,
                f"{unit}.Distribuidor": gate, f"{unit}.Caudal": flow,
                f"{unit}.Vibracion": (0.6 + 0.9 + 0.5 * load + rng.uniform(-0.1, 0.1)) if on else 0.0,
                f"{unit}.PresionOleo": 59.5 + 3.0 * math.sin(when.timestamp() / 400.0),
                f"{unit}.Paso": 6 if on else 0, f"{unit}.Acoplado": on,
                **{f"{unit}.Temp{k}": v for k, v in self.temps[unit].items()},
            })
        outflow = flow_total + 0.6
        self.level += (inflow - outflow) * STEP_S / 1.8e6 * 6.0  # gentle drift over the week
        self.level = max(809.5, min(814.3, self.level))
        self.sump = self.sump + 12.0 if self.sump < 60 else 22.0
        self.air = self.air - 0.25 if self.air > 7.05 else 8.0
        values.update({
            "Contador.Potencia": power_total - 0.12, "SSCC.FrecuenciaRed": 50.0 + rng.uniform(-0.03, 0.03),
            "SSCC.NivelEmbalse": self.level, "SSCC.CaudalEntrada": inflow, "SSCC.CaudalSalida": outflow,
            "SSCC.CaudalAliviadero": 0.0, "SSCC.PosCompuerta1": 0.0, "SSCC.PosCompuerta2": 0.0,
            "SSCC.SaltoBruto": head, "SSCC.Lluvia": rain, "Sistema.CaudalTurbinado": flow_total,
            "SSCC.Interruptor52L": True, "SSCC.TensionBaterias": 125.4 + rng.uniform(-0.2, 0.2),
            "SSCC.NivelPozo": self.sump, "SSCC.PresionAire": self.air, "Sistema.PotenciaTotal": power_total,
        })
        return values


def seed(project, now=None, seed_value=7):
    now = now or datetime.now(timezone.utc)
    if project.manifest["name"] != "CH Valdearenas":
        raise ValueError("Esta herramienta solo admite el ejemplo CH Valdearenas")
    files = {f["id"]: set(f["variables"]) for f in project.historian["files"]}
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today - timedelta(days=n) for n in range(DAYS, 0, -1)]
    targets = [path(project, file_id, day.timestamp()) for day in days for file_id in files]
    lease = RuntimeLease(project.root / "runtime" / "runtime.lock")
    lease.acquire()
    try:
        if any(t.exists() for t in targets):
            raise ValueError("Ya hay histórico en esos días; no se sobrescribe ni se mezcla")
        model = Model(random.Random(seed_value))
        for day in days:
            repositories = {file_id: Repository(path(project, file_id, day.timestamp())) for file_id in files}
            try:
                for minute in range(24 * 60):
                    when = day + timedelta(minutes=minute)
                    stamp = when.timestamp()
                    for tag, value in model.step(when).items():
                        for file_id, tags in files.items():
                            if tag in tags:
                                repositories[file_id].sample(tag, Sample(value, "good", stamp), stamp)
                for file_id, repository in repositories.items():
                    repository.connection.execute(
                        "INSERT INTO audit(timestamp,action,target,actor,detail) VALUES(?,?,?,?,?)",
                        (now.timestamp(), "demo_seed", file_id, "seed_hydro_history", "Datos sintéticos de demostración, 1 muestra/min"))
                    repository.connection.commit()
            finally:
                for repository in repositories.values():
                    repository.close()
        return days
    finally:
        lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default="examples/hydro")
    args = parser.parse_args()
    seeded = seed(Project.load(Path(args.project)))
    print(f"Histórico sintético: {seeded[0]:%d/%m} – {seeded[-1]:%d/%m} (UTC), 1 muestra por minuto.")
