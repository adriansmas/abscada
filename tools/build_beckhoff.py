"""Build examples/beckhoff: a motor test bench on a Beckhoff PLC over TwinCAT ADS.

    .venv\\Scripts\\python tools/build_beckhoff.py [--output examples/beckhoff] [--force]

Symbols match abscada.ads_simulator.DEMO_SYMBOLS (python -m abscada.ads_simulator).
"""
import argparse
import shutil
from pathlib import Path

from abscada.project import Project

PALETTE = {"Fondo": "#dde1e4", "Panel": "#eceef0", "Borde": "#b4bbc2", "Texto": "#1f2a33", "Suave": "#5b6670",
           "Marcha": "#2e8b57", "Paro": "#9aa3ab", "Alarma": "#d32f2f", "Aviso": "#e89a1c", "Mando": "#2b6cb0"}

FIELDS = [  # (field, type, symbol, PLC type, writable)
    ("Marcha", "bool", "MAIN.bMarcha", "BOOL", True),
    ("Modo", "int", "MAIN.nModo", "INT", True),
    ("Consigna", "float", "MAIN.rConsignaVelocidad", "REAL", True),
    ("Velocidad", "float", "MAIN.rVelocidad", "REAL", False),
    ("Temperatura", "float", "MAIN.rTemperatura", "REAL", False),
    ("Presion", "float", "MAIN.rPresion", "REAL", False),
    ("Ciclos", "int", "MAIN.nCiclos", "DINT", False),
    ("Estado", "string", "MAIN.sEstado", "STRING", False),
    ("AlarmaTemperatura", "bool", "GVL.bAlarmaTemperatura", "BOOL", False),
]


def build_project(root, force=False):
    root = Path(root).resolve()
    readme = None
    if (root / "project.json").exists():
        if not force:
            raise ValueError("El proyecto ya existe; usa --force para regenerarlo (se pierden sus cambios)")
        readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").exists() else None
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")

    p = Project(root, dict(schema_version=1, name="Banco de ensayo Beckhoff", startup_screen="banco", palette=PALETTE),
                {}, [], [], {}, {})
    p.types = {"BancoEnsayo": {field: kind for field, kind, *_ in FIELDS}}
    bindings = {}
    for field, kind, symbol, plc_type, _ in FIELDS:
        address = {"symbol": symbol, "encoding": plc_type}
        if plc_type == "STRING":
            address["length"] = 40
        bindings[f"Banco.{field}"] = dict(connection="CX_Banco", version=1, address=address)
    p.variables = [dict(name="Banco", type="BancoEnsayo", writable=True, bindings=bindings,
                        overrides={field: {"writable": False} for field, *_, writable in FIELDS if not writable},
                        initial=dict(Marcha=False, Modo=1, Consigna=1500.0, Velocidad=0.0, Temperatura=0.0, Presion=0.0,
                                     Ciclos=0, Estado="", AlarmaTemperatura=False))]
    p.connections = [dict(id="CX_Banco", protocol="ads", host="127.0.0.1", port=48898, ams_net_id="127.0.0.1.1.1",
                          ams_port=851, local_ams_net_id="auto", timeout_ms=1000, poll_ms=200)]

    elements = []

    def add(kind, identifier, x, y, w, h, **props):
        elements.append(dict(id=identifier, kind=kind, x=x, y=y, w=w, h=h, **props))

    def label(identifier, text, x, y, w, h=24, size=13, bold=False, color="@Suave"):
        add("text", identifier, x, y, w, h, text=text, font_size=size, bold=bold, text_color=color, text_align="left")

    def panel(identifier, x, y, w, h, caption):
        add("rectangle", identifier, x, y, w, h, color="@Panel", stroke_color="@Borde", stroke_width=1, filled=True, editor_locked=True)
        label(identifier + "_t", caption.upper(), x + 14, y + 8, w - 28, 20, size=11, bold=True)

    def command(identifier, text, tag, value, x, y, w, color, enabled=None, reason=""):
        dynamics = {}
        if enabled:
            dynamics = dict(enabled=enabled, disabled=dict(color="#d7dce0", text_color="#8a949d", border_color="#c3c9ce"), disabled_reason=reason)
        add("button", identifier, x, y, w, 42, text=text, tag=tag, action="set", value=value, font_size=14, bold=True,
            color=color, border_color=color, text_color="#ffffff", dynamics=dynamics)

    label("titulo", "BANCO DE ENSAYO DE MOTOR", 20, 12, 700, 32, size=22, bold=True, color="@Texto")
    label("subtitulo", "Beckhoff CX · TwinCAT 3 · ADS sobre TCP 48898 · puerto 851 · símbolos MAIN.* y GVL.*", 20, 44, 900, 20, size=12)

    panel("instrumentos", 20, 76, 770, 300, "Instrumentos")
    add("gauge", "velocidad", 36, 110, 360, 250, tag="Banco.Velocidad", min=0, max=3000, unit="rpm", decimals=0,
        text="Velocidad del eje", gauge_style="semi", warning=2500, alarm=2800)
    add("gauge", "presion", 414, 112, 240, 240, tag="Banco.Presion", min=0, max=8, unit="bar", decimals=2,
        text="Presión de aceite", gauge_style="dial", warning=6, alarm=7)
    add("gauge", "temperatura", 670, 104, 104, 262, tag="Banco.Temperatura", min=0, max=120, unit="°C", decimals=1,
        text="Devanado", gauge_style="thermometer", warning=75, alarm=85, color="#c0392b")

    panel("mando", 806, 76, 454, 300, "Mando")
    add("text", "estado", 822, 110, 422, 40, text="", tag="Banco.Estado", font_size=18, bold=True, text_align="center",
        color="@Paro", border_color="@Paro", text_color="#ffffff",
        dynamics=dict(states=[dict(when=dict(tag="Banco.Estado", op="eq", value="EN MARCHA", bad=False), style=dict(color="@Marcha", border_color="@Marcha")),
                              dict(when=dict(tag="Banco.Estado", op="ne", value="PARADO", bad=False), style=dict(color="@Aviso", border_color="@Aviso"))],
                      bad=dict(color="@Aviso", border_color="@Aviso")))
    command("marcha", "MARCHA", "Banco.Marcha", True, 822, 164, 205, "@Marcha",
            enabled=dict(tag="Banco.Marcha", op="eq", value=False, bad=False), reason="El motor ya está en marcha")
    command("paro", "PARO", "Banco.Marcha", False, 1039, 164, 205, "@Alarma",
            enabled=dict(tag="Banco.Marcha", op="eq", value=True, bad=False), reason="El motor ya está parado")
    label("sp_t", "Consigna de velocidad", 822, 222, 230, 26, size=13, color="@Texto")
    add("input", "consigna", 1064, 218, 180, 32, text="", tag="Banco.Consigna", unit="rpm", decimals=0, font_size=15, bold=True,
        text_align="right", color="#ffffff", border_color="@Mando", text_color="@Mando")
    label("modo_t", "Modo", 822, 266, 100, 26, size=13, color="@Texto")
    add("text_list", "modo", 1064, 262, 180, 32, tag="Banco.Modo", font_size=13, bold=True, color="#ffffff", border_color="@Borde",
        text_color="@Texto", texts=[dict(value="0", text="Manual"), dict(value="1", text="Automático"), dict(value="2", text="Mantenimiento")],
        default_text="—")
    for i, (text, value) in enumerate([("Manual", 0), ("Auto", 1), ("Mant.", 2)]):
        add("button", f"modo{i}", 822 + i * 76, 304, 70, 30, text=text, tag="Banco.Modo", action="set", value=value, font_size=12,
            color="#ffffff", border_color="@Mando", text_color="@Mando")
    label("ciclos_t", "Ciclos", 1064, 304, 70, 30, size=13, color="@Texto")
    add("text", "ciclos", 1130, 304, 114, 30, text="", tag="Banco.Ciclos", font_size=14, text_align="right",
        color="#f8f9fa", border_color="@Borde", text_color="@Texto")
    add("lamp", "alarma", 822, 342, 26, 26, tag="Banco.AlarmaTemperatura", lamp_colors=dict(on="@Alarma", off="@Paro", bad="@Aviso"))
    label("alarma_t", "Alarma de temperatura (calculada en el PLC)", 856, 342, 390, 26, size=13, color="@Texto")

    add("trend", "tendencia", 20, 390, 770, 360, view="banco")
    add("alarm_view", "alarmas", 806, 390, 454, 360, view="activas")
    p.screens["banco"] = dict(title="Banco de ensayo", width=1280, height=770, background="@Fondo", elements=elements)

    p.trends = {"banco": dict(title="Velocidad, temperatura y presión", window_seconds=600, axes=[
        dict(id="rpm", title="Velocidad (rpm)", side="left", auto=False, min=0, max=3000, visible=True),
        dict(id="t", title="Temperatura (°C) / presión (bar)", side="right", auto=False, min=0, max=120, visible=True)],
        curves=[dict(id="v", tag="Banco.Velocidad", axis="rpm", color="#2b6cb0", width=3, visible=True),
                dict(id="sp", tag="Banco.Consigna", axis="rpm", color="#7f9bb3", width=1, visible=True),
                dict(id="t", tag="Banco.Temperatura", axis="t", color="#c0392b", width=2, visible=True),
                dict(id="p", tag="Banco.Presion", axis="t", color="#2e8b57", width=2, visible=True)])}
    p.historian = dict(retention_days=90, files=[dict(id="banco", name="Banco · 1 s", interval_ms=1000,
                                                      variables=["Banco.Velocidad", "Banco.Consigna", "Banco.Temperatura", "Banco.Presion"])])
    p.alarms = dict(retention_days=365, categories=[dict(id="banco", name="Banco de ensayo", color="#2b6cb0")], items=[
        dict(id="temp_alta", tag="Banco.Temperatura", category="banco", condition="high", threshold=75, message="Temperatura de devanado alta",
             priority=700, ack_required=True, enabled=True, hysteresis=2, on_delay_ms=1000, off_delay_ms=500),
        dict(id="temp_muy_alta", tag="Banco.AlarmaTemperatura", category="banco", condition="true", threshold=0,
             message="Temperatura de devanado muy alta (PLC)", priority=900, ack_required=True, enabled=True, hysteresis=0,
             on_delay_ms=0, off_delay_ms=500),
        dict(id="sobrevelocidad", tag="Banco.Velocidad", category="banco", condition="high", threshold=2800, message="Velocidad excesiva",
             priority=800, ack_required=True, enabled=True, hysteresis=50, on_delay_ms=500, off_delay_ms=500)])
    p.alarm_views = {"activas": dict(title="Alarmas del banco", categories=[], min_priority=1, mode="pending", allow_ack=True,
                                     columns=["priority", "message", "state", "entered_at", "ack_at"])}
    p.validate()
    p.save()
    return p


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="examples/beckhoff")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    built = build_project(args.output, args.force)
    print(f"{built.root}: {len(built.tags())} variables · conexión ADS {built.connections[0]['host']}:{built.connections[0]['port']}")
