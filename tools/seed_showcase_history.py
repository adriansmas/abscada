"""Create explicitly synthetic LOCAL history for the laboratory, never PLC readings."""
import argparse
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from abscada.project import Project
from abscada.runtime import Sample
from abscada.storage import Repository, RuntimeLease
from abscada.recording import path


def seed(project, now=None):
    now = now or datetime.now(timezone.utc)
    if project.manifest['name'] != 'Laboratorio SCADA':
        raise ValueError('Esta herramienta solo admite el proyecto Laboratorio SCADA')
    days = [(now - timedelta(days=n)).replace(hour=12, minute=0, second=0, microsecond=0) for n in (2, 1)]
    targets = [path(project, 'internas', day.timestamp()) for day in days]
    lease = RuntimeLease(project.root / 'runtime' / 'runtime.lock')
    lease.acquire()
    try:
        if any(target.exists() for target in targets):
            raise ValueError('Ya existe un archivo de esos días; no se sobrescribe ni mezcla con datos existentes')
        for day, target in zip(days, targets):
            repository = Repository(target)
            try:
                # One hour at the configured one-second cadence, on each UTC day.
                for second in range(3600):
                    timestamp = day.timestamp() + second
                    values = {'Local.Nivel': 50 + 40 * math.sin(second / 60),
                              'Local.Consigna': 55.0, 'Local.Temperatura': 30 + 10 * math.sin(second / 100),
                              'Local.Marcha': second % 600 < 400}
                    for tag, value in values.items():
                        repository.sample(tag, Sample(value, 'good', timestamp), timestamp)
                repository.connection.execute("INSERT INTO audit(timestamp,action,target,actor,detail) VALUES(?,?,?,?,?)",
                    (now.timestamp(), 'demo_seed', 'internas', 'seed_showcase_history', 'Datos sintéticos locales: 12:00–13:00 UTC'))
                repository.connection.commit()
            finally:
                repository.close()
        return targets
    finally:
        lease.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', nargs='?', default='examples/showcase')
    args = parser.parse_args()
    for target in seed(Project.load(Path(args.project))):
        print(target)
    print('Datos sintéticos locales: ayer y anteayer, de 12:00 a 13:00 UTC. Selecciona ese intervalo en Histórico.')
