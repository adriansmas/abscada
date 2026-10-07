"""Development PLC simulators, runnable without Python as `abscada --simulador <id>`.

They serve the shipped examples over real TCP (S7, Modbus, ADS, OPC UA). Runtime never
imports them: they always run as a separate process.
"""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class Simulator:
    id: str
    title: str
    example: str
    endpoints: str
    module: str

    def run(self, argv=None):
        return import_module(self.module).main(argv)


SIMULATORS = {
    s.id: s for s in (
        Simulator("hydro", "Central hidroeléctrica (CH Valdearenas)", "hydro",
                  "S7 :1102, :1103, :1104 · Modbus :1502", "abscada.simulators.hydro"),
        Simulator("cerveceria", "Microcervecería por lotes (La Tolva)", "brewery",
                  "OPC UA :4841 (cifrado)", "abscada.simulators.brewery"),
        Simulator("ads", "Banco de ensayo Beckhoff (TwinCAT ADS)", "beckhoff",
                  "ADS :48898 · puerto 851", "abscada.ads_simulator"),
        Simulator("laboratorio", "Laboratorio SCADA (S7 + Modbus)", "showcase",
                  "S7 :1102 · Modbus :1502", "abscada.simulators.laboratory"),
        Simulator("s7", "PLC S7 básico (demo, s7)", "s7",
                  "S7 :1102", "abscada.s7_simulator"),
    )
}


def for_example(example):
    """Simulator that brings a shipped example to life, if any."""
    return next((s for s in SIMULATORS.values() if s.example == example), None)
