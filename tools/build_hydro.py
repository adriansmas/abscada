"""Build examples/hydro: a complete SCADA for a two-unit hydroelectric plant.

    .venv\\Scripts\\python tools/build_hydro.py [--output examples/hydro] [--force]

Bindings come from plc_simulators/hydro_map.py, the same map served by plc_simulators/hydro.py.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from abscada.drawing import set_points  # noqa: E402
from abscada.example_languages import bilingual
from abscada.project import Project  # noqa: E402
from abscada.project_files import is_project  # noqa: E402
from abscada.screen_tree import own_viewers  # noqa: E402
from plc_simulators.hydro_map import COMMON_FIELDS, METER_FIELDS, PORTS, STEPS, TRIP_CAUSES, UNIT_FIELDS  # noqa: E402

SCREEN_W, SCREEN_H = 1400, 830
UNITS = [("G1", "PLC_G1", "Grupo 1"), ("G2", "PLC_G2", "Grupo 2")]


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
class Doc:
    """Screen/faceplate builder that keeps element ids unique."""

    text_color = "#1f2a33"
    muted_color = "#5b6670"
    panel_color = "#eceef0"
    border_color = "#b4bbc2"
    value_color = "#f8f9fa"
    off_color = "#9aa3ab"

    def __init__(self, data):
        self.data = data
        self.ids = set()

    def add(self, kind, identifier, x, y, w, h, **props):
        base, n = identifier, 2
        while identifier in self.ids:
            identifier, n = f"{base}_{n}", n + 1
        self.ids.add(identifier)
        element = dict(id=identifier, kind=kind, x=x, y=y, w=w, h=h, **props)
        self.data["elements"].append(element)
        return element

    def path(self, kind, identifier, points, **props):
        if kind == "line" and len(points) > 2:
            kind = "polyline"
        element = self.add(kind, identifier, 0, 0, 1, 1, **props)
        set_points(element, points)
        return element

    # -- typography ----------------------------------------------------------
    def label(self, identifier, text, x, y, w, h=22, size=13, bold=False, color=None, align="left"):
        return self.add("text", identifier, x, y, w, h, text=text, font_size=size, bold=bold,
                        text_color=color or self.muted_color, text_align=align)

    def title(self, text, subtitle=""):
        self.label("titulo", text, 14, 8, 900, 30, size=20, bold=True, color=self.text_color)
        if subtitle:
            self.label("subtitulo", subtitle, 14, 36, 900, 18, size=12)

    def panel(self, identifier, x, y, w, h, caption=None):
        self.add("rectangle", identifier, x, y, w, h, color=self.panel_color, stroke_color=self.border_color,
                 stroke_width=1, filled=True, editor_locked=True)
        if caption:
            self.label(identifier + "_titulo", caption.upper(), x + 12, y + 6, w - 24, 20, size=11, bold=True)

    def value(self, identifier, tag, x, y, w=110, h=26, unit="", decimals=1, alarms=(), size=14, align="right"):
        """Numeric display. alarms: [(op, threshold, color)] first match wins."""
        states = [dict(when=dict(tag=tag, op=op, value=float(limit), bad=False),
                       style=dict(color=color, text_color="#ffffff", border_color=color)) for op, limit, color in alarms]
        dynamics = {"bad": {"color": "#fdf1dc", "border_color": "#e89a1c"}}
        if states:
            dynamics["states"] = states
        return self.add("text", identifier, x, y, w, h, text="", tag=tag, unit=unit, decimals=decimals,
                        font_size=size, text_align=align, color=self.value_color, border_color=self.border_color,
                        text_color=self.text_color, dynamics=dynamics)

    def field(self, identifier, caption, tag, x, y, unit="", w=300, value_w=120, decimals=1, alarms=()):
        self.label(identifier + "_t", caption, x, y + 3, w - value_w - 6, 22, size=13, color=self.text_color)
        return self.value(identifier, tag, x + w - value_w, y, value_w, 26, unit, decimals, alarms)

    def setpoint(self, identifier, caption, tag, x, y, unit="", w=300, value_w=120, enabled=None, reason=""):
        self.label(identifier + "_t", caption, x, y + 3, w - value_w - 6, 22, size=13, color=self.text_color)
        dynamics = {}
        if enabled:
            dynamics = dict(enabled=enabled, disabled=dict(color="#e3e6e9", text_color="#8a949d"), disabled_reason=reason)
        return self.add("input", identifier, x + w - value_w, y, value_w, 26, text="", tag=tag, unit=unit,
                        decimals=1, font_size=14, text_align="right", color="#ffffff", border_color="#2b6cb0",
                        text_color="#2b6cb0", bold=True, dynamics=dynamics)

    def lamp(self, identifier, tag, x, y, size=20, on="#2e8b57", off=None):
        return self.add("lamp", identifier, x, y, size, size, tag=tag, lamp_colors=dict(on=on, off=off or self.off_color, bad="#e89a1c"))

    def status(self, identifier, caption, tag, x, y, w=240, on="#2e8b57", off=None):
        self.lamp(identifier, tag, x, y + 2, 20, on, off)
        return self.label(identifier + "_t", caption, x + 28, y + 1, w - 28, 22, size=13, color=self.text_color)

    def state_text(self, identifier, tag, x, y, w, h, true_text, false_text, true_color, false_color, size=13):
        return self.add("text_list", identifier, x, y, w, h, tag=tag, font_size=size, bold=True,
                        texts=[dict(value="true", text=true_text), dict(value="false", text=false_text)],
                        default_text="—", color=false_color, text_color="#ffffff", border_color=false_color,
                        dynamics=dict(states=[dict(when=dict(tag=tag, op="eq", value=True), style=dict(color=true_color, border_color=true_color))],
                                      bad=dict(color="#e89a1c", border_color="#e89a1c")))

    def button(self, identifier, text, x, y, w=150, h=34, **props):
        style = dict(font_size=13, bold=True, color="#ffffff", border_color=self.border_color, text_color=self.text_color)
        style.update(props)
        return self.add("button", identifier, x, y, w, h, text=text, **style)

    def command(self, identifier, text, tag, x, y, w=150, h=38, color="#2b6cb0", enabled=None, reason="", value=True):
        dynamics = {}
        if enabled:
            dynamics = dict(enabled=enabled, disabled=dict(color="#d7dce0", text_color="#8a949d", border_color="#c3c9ce"),
                            disabled_reason=reason)
        return self.add("button", identifier, x, y, w, h, text=text, tag=tag, action="set", value=value,
                        font_size=13, bold=True, color=color, border_color=color, text_color="#ffffff", dynamics=dynamics)

    def bar(self, identifier, tag, x, y, w, h, low, high, color="#4f86b8", alarms=()):
        states = [dict(when=dict(tag=tag, op=op, value=float(limit), bad=False), style=dict(color=c)) for op, limit, c in alarms]
        return self.add("bar", identifier, x, y, w, h, tag=tag, min=low, max=high, color=color,
                        dynamics=dict(states=states) if states else {})

    def energized(self, kind, identifier, points, tag, threshold=None, width=4, op="gt"):
        """Electrical conductor coloured by a bool tag or by a voltage threshold."""
        condition = dict(tag=tag, op="eq", value=True, bad=False) if threshold is None else dict(tag=tag, op=op, value=float(threshold), bad=False)
        return self.path(kind, identifier, points, stroke_color="#a9b1b8", stroke_width=width,
                         dynamics=dict(states=[dict(when=condition, style=dict(stroke_color="#1f5f99"))]))


def condition(tag, op, value):
    return dict(tag=tag, op=op, value=value, bad=False)


# ---------------------------------------------------------------------------
# Project model
# ---------------------------------------------------------------------------
def build_variables():
    types = {
        "GrupoHidro": {name: kind for name, kind, _, _ in UNIT_FIELDS},
        "ServiciosComunes": {name: kind for name, kind, _, _ in COMMON_FIELDS},
        "Contador": {name: kind for name, kind, *_ in METER_FIELDS},
        "Sistema": {"Fecha": "string", "Hora": "string", "Inicio": "string", "Operador": "string", "Pantalla": "string",
                    "ComG1": "bool", "ComG2": "bool", "ComSSCC": "bool", "ComContador": "bool", "ComTodas": "bool",
                    "PotenciaTotal": "float", "CaudalTurbinado": "float", "EnergiaHoy": "float"},
        "ControlPlanta": {"ControlConjunto": "bool", "ConsignaPlanta": "float", "ControlNivel": "bool",
                          "ConsignaNivel": "float", "Estado": "string"},
    }
    defaults = {"bool": False, "int": 0, "float": 0.0, "string": ""}

    def plc_variable(name, kind, fields, connection):
        initial = {field: defaults[t] for field, t, *_ in fields}
        bindings = {f"{name}.{field}": dict(connection=connection, address=address) for field, _, address, _ in fields}
        overrides = {field: {"writable": False} for field, _, _, writable in fields if not writable}
        return dict(name=name, type=kind, initial=initial, writable=True, overrides=overrides, bindings=bindings)

    variables = [plc_variable(unit, "GrupoHidro", UNIT_FIELDS, connection) for unit, connection, _ in UNITS]
    variables.append(plc_variable("SSCC", "ServiciosComunes", COMMON_FIELDS, "PLC_SSCC"))
    meter_bindings = {}
    for field, _, area, offset, encoding, _ in METER_FIELDS:
        address = dict(area=area, offset=offset, encoding=encoding)
        if encoding != "bool":
            address.update(byte_order="big", word_order="big")
        meter_bindings[f"Contador.{field}"] = dict(connection="Contador_66kV", version=1, address=address)
    variables.append(dict(name="Contador", type="Contador", writable=False, bindings=meter_bindings,
                          initial={field: defaults[t] for field, t, *_ in METER_FIELDS}))
    variables.append(dict(name="Sistema", type="Sistema", writable=True, initial=dict(
        Fecha="", Hora="", Inicio="", Operador="Operador de turno", Pantalla="", ComG1=True, ComG2=True, ComSSCC=True,
        ComContador=True, ComTodas=True, PotenciaTotal=0.0, CaudalTurbinado=0.0, EnergiaHoy=0.0)))
    variables.append(dict(name="Planta", type="ControlPlanta", writable=True, initial=dict(
        ControlConjunto=False, ConsignaPlanta=16.0, ControlNivel=False, ConsignaNivel=812.5, Estado="Control conjunto desactivado")))
    return types, variables


def build_connections():
    from abscada.connectors import REGISTRY
    modbus = next(k for k, v in REGISTRY.items() if v.definition.label == "Modbus TCP")
    connections = [dict(id=name, protocol="s7", host="127.0.0.1", port=PORTS[name], rack=0, slot=1, poll_ms=250)
                   for name in ("PLC_G1", "PLC_G2")]
    connections.append(dict(id="PLC_SSCC", protocol="s7", host="127.0.0.1", port=PORTS["PLC_SSCC"], rack=0, slot=1, poll_ms=500))
    connections.append(dict(id="Contador_66kV", protocol=modbus, host="127.0.0.1", port=PORTS["Contador_66kV"],
                            unit_id=1, timeout_ms=800, poll_ms=1000))
    return connections


# ---------------------------------------------------------------------------
# Faceplates
# ---------------------------------------------------------------------------
def build_faceplates():
    faceplates = {}

    # Circuit breaker: red = closed, green = open (power utility convention).
    fp = Doc(dict(title="Interruptor", width=44, height=44, background="#dde1e4",
                  parameters={"cerrado": "bool"}, elements=[]))
    fp.add("rectangle", "cuerpo", 2, 2, 40, 40, color="#2e7d32", stroke_color="#1f2a33", stroke_width=2,
           dynamics=dict(states=[dict(when=condition("$cerrado", "eq", True), style=dict(color="#c62828"))],
                         bad=dict(color="#e89a1c")))
    fp.add("text_list", "estado", 2, 2, 40, 40, tag="$cerrado", font_size=16, bold=True, text_color="#ffffff",
           color="#00000000", border_color="#00000000",
           texts=[dict(value="true", text="I"), dict(value="false", text="O")], default_text="?")
    faceplates["interruptor"] = fp.data

    # Pump: green running, red fault, grey stopped.
    fp = Doc(dict(title="Bomba", width=50, height=50, background="#eceef0",
                  parameters={"marcha": "bool", "fallo": "bool"}, elements=[]))
    fp.add("ellipse", "cuerpo", 3, 3, 44, 44, color="#9aa3ab", stroke_color="#1f2a33", stroke_width=2,
           dynamics=dict(states=[dict(when=condition("$fallo", "eq", True), style=dict(color="#d32f2f")),
                                 dict(when=condition("$marcha", "eq", True), style=dict(color="#2e8b57"))],
                         bad=dict(color="#e89a1c")))
    fp.path("polyline", "rodete", [[16, 13], [38, 25], [16, 37], [16, 13]], stroke_color="#ffffff", stroke_width=3)
    faceplates["bomba"] = fp.data

    # Radial spillway gate: position, setpoint and manual/automatic mode.
    fp = Doc(dict(title="Compuerta de aliviadero", width=250, height=190, background="#eceef0",
                  parameters={"posicion": "float", "consigna": "float", "automatico": "bool"}, elements=[]))
    fp.add("rectangle", "marco", 14, 14, 52, 162, color="#ffffff", stroke_color="#6c7882", stroke_width=2)
    fp.bar("apertura", "$posicion", 18, 18, 44, 154, 0, 100, color="#4f86b8")
    fp.label("pos_t", "Apertura", 80, 12, 160, 24)
    fp.value("pos", "$posicion", 80, 38, 150, 30, "%", 1, size=16)
    fp.label("sp_t", "Consigna", 80, 74, 160, 24)
    fp.add("input", "sp", 80, 100, 150, 30, text="", tag="$consigna", unit="%", decimals=1, font_size=15,
           text_align="right", color="#ffffff", border_color="#2b6cb0", text_color="#2b6cb0", bold=True,
           dynamics=dict(enabled=condition("$automatico", "eq", False),
                         disabled=dict(color="#e3e6e9", text_color="#8a949d", border_color="#b4bbc2"),
                         disabled_reason="Aliviadero en automático: la consigna la calcula el PLC"))
    fp.add("text_list", "modo", 80, 142, 150, 28, tag="$automatico", font_size=12, bold=True, text_color="#ffffff",
           color="#6c7882", border_color="#6c7882", texts=[dict(value="true", text="AUTOMÁTICO"), dict(value="false", text="MANUAL")],
           default_text="—", dynamics=dict(states=[dict(when=condition("$automatico", "eq", False), style=dict(color="#2b6cb0", border_color="#2b6cb0"))]))
    faceplates["compuerta"] = fp.data

    # Unit summary tile used on the overview. Its «Mando…» button forwards the
    # tile's parameters, so each tile opens the command window of its own unit.
    unit_parameters = {"paso": "int", "potencia": "float", "consigna": "float", "remoto": "bool", "listo": "bool",
                       "disparo": "bool", "causa": "int", "arranque": "bool", "parada": "bool", "rearme": "bool"}
    fp = Doc(dict(title="Resumen de grupo", width=290, height=214, background="#eceef0",
                  parameters={**unit_parameters, "velocidad": "float", "caudal": "float", "acoplado": "bool",
                              "alarma": "bool"}, elements=[]))
    fp.button("mando", "Mando…", 206, 10, 74, 32, action="faceplate_popup", template="mando_grupo",
              bindings={name: "$" + name for name in unit_parameters}, color="#2b6cb0", border_color="#2b6cb0",
              text_color="#ffffff", font_size=12)
    fp.add("text_list", "estado", 10, 10, 190, 32, tag="$paso", font_size=12, bold=True, text_color="#ffffff",
           color="#9aa3ab", border_color="#9aa3ab", texts=[dict(value=str(i), text=t.upper()) for i, t in enumerate(STEPS)],
           default_text="—", dynamics=dict(states=[
               dict(when=condition("$paso", "eq", 10), style=dict(color="#d32f2f", border_color="#d32f2f")),
               dict(when=condition("$paso", "eq", 6), style=dict(color="#2e8b57", border_color="#2e8b57")),
               dict(when=condition("$paso", "gt", 0), style=dict(color="#e89a1c", border_color="#e89a1c"))],
               bad=dict(color="#e89a1c", border_color="#e89a1c")))
    for i, (caption, tag, unit, decimals) in enumerate([("Potencia", "$potencia", "MW", 2), ("Consigna P", "$consigna", "MW", 1),
                                                         ("Velocidad", "$velocidad", "%", 1), ("Caudal", "$caudal", "m³/s", 2)]):
        fp.field(f"v{i}", caption, tag, 10, 52 + i * 31, unit, 270, 130, decimals)
    fp.lamp("l52g", "$acoplado", 12, 182, 16, "#c62828", "#2e7d32")
    fp.label("l52g_t", "52G", 32, 179, 50, 22, size=12, color="#1f2a33")
    fp.add("text_list", "remoto", 90, 179, 90, 24, tag="$remoto", font_size=11, bold=True, text_color="#1f2a33",
           texts=[dict(value="true", text="REMOTO"), dict(value="false", text="LOCAL")], default_text="—",
           dynamics=dict(states=[dict(when=condition("$remoto", "eq", False), style=dict(text_color="#e89a1c"))]))
    fp.add("text_list", "alarma", 190, 179, 90, 24, tag="$alarma", font_size=11, bold=True, text_color="#ffffff",
           color="#9aa3ab", border_color="#9aa3ab", texts=[dict(value="true", text="ALARMA"), dict(value="false", text="SIN ALARMA")],
           default_text="—", dynamics=dict(states=[dict(when=condition("$alarma", "eq", True), style=dict(color="#d32f2f", border_color="#d32f2f"))]))
    faceplates["grupo"] = fp.data

    # Pop-up windows: never placed on a screen, opened from buttons.
    fp = Doc(dict(title="Mando de grupo", width=480, height=330, background="#eceef0",
                  parameters=unit_parameters, elements=[]))
    fp.add("text_list", "estado", 12, 12, 456, 36, tag="$paso", font_size=15, bold=True, text_color="#ffffff",
           color="#9aa3ab", border_color="#9aa3ab", texts=[dict(value=str(i), text=t.upper()) for i, t in enumerate(STEPS)],
           default_text="SIN COMUNICACIÓN", dynamics=dict(states=[
               dict(when=condition("$paso", "eq", 10), style=dict(color="#d32f2f", border_color="#d32f2f")),
               dict(when=condition("$paso", "eq", 6), style=dict(color="#2e8b57", border_color="#2e8b57")),
               dict(when=condition("$paso", "gt", 0), style=dict(color="#e89a1c", border_color="#e89a1c"))],
               bad=dict(color="#e89a1c", border_color="#e89a1c")))
    fp.state_text("modo", "$remoto", 12, 60, 130, 30, "REMOTO", "LOCAL", "#6c7882", "#e89a1c")
    fp.status("listo", "Listo para arrancar", "$listo", 160, 64, 300)
    fp.field("potencia", "Potencia activa", "$potencia", 12, 104, "MW", 456, 140, 2)
    fp.setpoint("consigna", "Consigna de potencia activa", "$consigna", 12, 138, "MW", 456, 140,
                condition("$remoto", "eq", True), "Grupo en local")
    fp.command("arrancar", "ARRANCAR", "$arranque", 12, 180, 144, 40, "#2e8b57",
               enabled=condition("$listo", "eq", True), reason="Condiciones de arranque no cumplidas")
    fp.command("parar", "PARAR", "$parada", 168, 180, 144, 40, "#6c7882",
               enabled=condition("$paso", "ne", 0), reason="El grupo ya está parado")
    fp.command("rearmar", "REARME 86", "$rearme", 324, 180, 144, 40, "#2b6cb0",
               enabled=condition("$disparo", "eq", True), reason="No hay disparo que rearmar")
    fp.label("causa_t", "Causa de disparo", 12, 234, 200, 18, size=10, bold=True)
    fp.add("text_list", "causa", 12, 254, 300, 28, tag="$causa", font_size=12, bold=True,
           texts=[dict(value=str(i), text=t) for i, t in enumerate(TRIP_CAUSES)], default_text="—",
           color="#f8f9fa", border_color="#b4bbc2", text_color="#1f2a33",
           dynamics=dict(states=[dict(when=condition("$causa", "gt", 0), style=dict(color="#d32f2f", text_color="#ffffff", border_color="#d32f2f"))]))
    fp.button("cerrar", "Cerrar", 348, 280, 120, 38, action="close_popup")
    faceplates["mando_grupo"] = fp.data

    fp = Doc(dict(title="Bomba", width=360, height=230, background="#eceef0",
                  parameters={"marcha": "bool", "fallo": "bool"}, elements=[]))
    fp.add("ellipse", "cuerpo", 16, 16, 80, 80, color="#9aa3ab", stroke_color="#1f2a33", stroke_width=3,
           dynamics=faceplates["bomba"]["elements"][0]["dynamics"])
    fp.path("polyline", "rodete", [[38, 34], [80, 56], [38, 78], [38, 34]], stroke_color="#ffffff", stroke_width=4)
    fp.state_text("marcha", "$marcha", 112, 20, 232, 32, "EN MARCHA", "PARADA", "#2e8b57", "#9aa3ab")
    fp.state_text("fallo", "$fallo", 112, 62, 232, 32, "FALLO", "SIN FALLO", "#d32f2f", "#9aa3ab")
    fp.label("nota", "Arranque y parada automáticos por el PLC (nivel o presión). Sin mando desde el SCADA.",
             16, 112, 328, 48, size=12, color="#1f2a33")
    fp.button("cerrar", "Cerrar", 224, 176, 120, 38, action="close_popup")
    faceplates["bomba_detalle"] = fp.data
    return faceplates


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------
NAV = [
    ("10_general", "Vista general"),
    ("20_embalse", "Embalse y presa"),
    ("30_grupo1", "Grupo 1"),
    ("31_grupo2", "Grupo 2"),
    ("40_unifilar", "Unifilar 66 kV"),
    ("50_auxiliares", "Servicios auxiliares"),
    ("60_control", "Control de planta"),
    ("70_tend_produccion", "Tendencias"),
    ("80_alarmas", "Alarmas"),
    ("90_instructor", "Simulación (instructor)"),
]


def screen(project, key, title, subtitle="", width=SCREEN_W, height=SCREEN_H, background="#dde1e4", **extra):
    data = dict(title=title, width=width, height=height, background=background, grid_size=10, show_grid=False,
                snap_to_grid=True, elements=[], **extra)
    project.screens[key] = data
    doc = Doc(data)
    if subtitle is not None and width == SCREEN_W:
        doc.title(title.upper(), subtitle)
    return doc


def build_layout(project):
    project.screens["00_layout"] = dict(title="CH Valdearenas · SCADA", width=1600, height=900,
                                        background="#dde1e4", elements=[
        dict(id="cabecera", kind="screen_container", x=0, y=0, w=1600, h=70, screen="01_cabecera"),
        dict(id="menu", kind="screen_container", x=0, y=70, w=200, h=830, screen="02_menu"),
        dict(id="contenido", kind="screen_container", x=200, y=70, w=1400, h=830, screen="10_general")])

    h = screen(project, "01_cabecera", "Cabecera", None, 1600, 70, "#22303a")
    h.label("marca", "CH VALDEARENAS", 18, 8, 210, 28, size=19, bold=True, color="#ffffff")
    h.label("marca2", "SCADA · 2 × 10 MW · 66 kV", 18, 38, 220, 20, size=11, color="#9fb0bd")
    for i, (caption, tag, unit, decimals) in enumerate([("POTENCIA PLANTA", "Sistema.PotenciaTotal", "MW", 2),
                                                         ("NIVEL EMBALSE", "SSCC.NivelEmbalse", "msnm", 2),
                                                         ("FRECUENCIA RED", "SSCC.FrecuenciaRed", "Hz", 3),
                                                         ("ENERGÍA HOY", "Sistema.EnergiaHoy", "MWh", 1)]):
        x = 250 + i * 175
        h.label(f"k{i}_t", caption, x, 6, 165, 18, size=10, bold=True, color="#9fb0bd")
        h.add("text", f"k{i}", x, 26, 165, 34, text="", tag=tag, unit=unit, decimals=decimals, font_size=19, bold=True,
              text_align="left", color="#22303a", border_color="#22303a", text_color="#ffffff")
    h.label("areas_t", "ALARMAS DE ÁREA", 960, 6, 300, 18, size=10, bold=True, color="#9fb0bd")
    for i, (caption, tag) in enumerate([("G1", "G1.AlarmaGrupo"), ("G2", "G2.AlarmaGrupo"), ("PRESA", "SSCC.AlarmaPresa"),
                                        ("SUBEST.", "SSCC.AlarmaSubestacion"), ("SSAA", "SSCC.AlarmaAuxiliares")]):
        x = 960 + i * 66
        h.add("text_list", f"area{i}", x, 28, 60, 30, tag=tag, font_size=11, bold=True, text_color="#ffffff",
              color="#3a4a56", border_color="#3a4a56", texts=[dict(value="true", text=caption), dict(value="false", text=caption)],
              dynamics=dict(states=[dict(when=condition(tag, "eq", True), style=dict(color="#d32f2f", border_color="#d32f2f"))],
                            bad=dict(color="#e89a1c", border_color="#e89a1c")))
    h.add("text_list", "coms", 1296, 28, 60, 30, tag="Sistema.ComTodas", font_size=11, bold=True, text_color="#ffffff",
          color="#3a4a56", border_color="#3a4a56", texts=[dict(value="true", text="COM"), dict(value="false", text="COM")],
          dynamics=dict(states=[dict(when=condition("Sistema.ComTodas", "eq", False), style=dict(color="#d32f2f", border_color="#d32f2f"))]))
    h.add("text", "fecha", 1380, 8, 205, 24, text="", tag="Sistema.Fecha", font_size=13, text_align="right",
          color="#22303a", border_color="#22303a", text_color="#9fb0bd")
    h.add("text", "hora", 1380, 30, 205, 32, text="", tag="Sistema.Hora", font_size=21, bold=True, text_align="right",
          color="#22303a", border_color="#22303a", text_color="#ffffff")

    m = screen(project, "02_menu", "Menú", None, 200, 830, "#2c3a45")
    for i, (key, caption) in enumerate(NAV):
        special = key == "90_instructor"
        m.button("nav_" + key, caption, 10, 14 + i * 48, 180, 40, action="screen", screen=key, target_container="contenido",
                 color="#6b4b16" if special else "#3b4b57", border_color="#8a6420" if special else "#4b5c69",
                 text_color="#ffffff", text_align="left")
    m.label("com_t", "COMUNICACIONES", 14, 520, 172, 18, size=10, bold=True, color="#9fb0bd")
    for i, (caption, tag) in enumerate([("PLC Grupo 1", "Sistema.ComG1"), ("PLC Grupo 2", "Sistema.ComG2"),
                                        ("PLC Serv. comunes", "Sistema.ComSSCC"), ("Contador 66 kV", "Sistema.ComContador")]):
        m.lamp(f"com{i}", tag, 14, 546 + i * 30, 18, "#2e8b57", "#d32f2f")
        m.label(f"com{i}_t", caption, 40, 544 + i * 30, 150, 22, size=12, color="#d5dde3")
    m.label("op_t", "OPERADOR", 14, 680, 172, 18, size=10, bold=True, color="#9fb0bd")
    m.add("input", "operador", 10, 700, 180, 30, text="", tag="Sistema.Operador", font_size=12, text_align="left",
          color="#3b4b57", border_color="#4b5c69", text_color="#ffffff")
    m.label("pant_t", "PANTALLA", 14, 742, 172, 18, size=10, bold=True, color="#9fb0bd")
    m.add("text", "pantalla", 10, 762, 180, 26, text="", tag="Sistema.Pantalla", font_size=11, text_align="left",
          color="#2c3a45", border_color="#2c3a45", text_color="#d5dde3")
    m.button("ayuda", "Ayuda", 10, 792, 180, 30, action="popup", screen="99_ayuda", color="#3b4b57",
             border_color="#4b5c69", text_color="#ffffff")


def build_overview(project):
    d = screen(project, "10_general", "Vista general de la central",
               "Embalse → toma → tubería forzada → 2 grupos Francis → transformadores → línea de 66 kV")
    d.panel("sinoptico", 10, 60, 1380, 410)
    # Reservoir and dam
    d.add("rectangle", "vaso", 30, 120, 330, 300, color="#ffffff", stroke_color="#b4bbc2", stroke_width=1)
    d.bar("agua", "SSCC.NivelEmbalse", 32, 122, 326, 296, 795, 818, color="#4f86b8",
          alarms=[("ge", 815.0, "#d32f2f"), ("ge", 814.5, "#e89a1c")])
    d.add("image", "presa", 300, 96, 150, 330, source="assets/presa.svg")
    d.label("embalse_t", "EMBALSE", 40, 70, 200, 22, size=13, bold=True, color="#1f2a33")
    d.value("nivel", "SSCC.NivelEmbalse", 40, 92, 160, 26, "msnm", 2, size=15, align="left")
    d.value("volumen", "SSCC.Volumen", 206, 92, 110, 26, "hm³", 2, align="left")
    # Intake, penstock and spillway
    d.lamp("toma", "SSCC.CompuertaTomaAbierta", 438, 352, 18, "#2e8b57", "#d32f2f")
    d.label("toma_t", "Toma", 430, 372, 60, 18, size=11)
    d.path("pipe", "tuberia", [[450, 390], [600, 390], [700, 440], [1240, 440]], stroke_color="#4f86b8", stroke_width=12)
    d.label("tuberia_t", "Tubería forzada Ø2,2 m", 460, 400, 200, 20, size=11)
    d.value("p_tub", "SSCC.PresionTuberia", 560, 448, 110, 24, "bar", 2, size=12)
    # Spill flows over the crest and down the downstream face; amber while discharging.
    d.path("polyline", "aliviadero", [[372, 104], [410, 140], [440, 260], [470, 330]], stroke_color="#a9b1b8", stroke_width=6,
           stroke_style="dash", arrows="end",
           dynamics=dict(states=[dict(when=condition("SSCC.CaudalAliviadero", "gt", 1.0), style=dict(stroke_color="#4f86b8"))]))
    d.label("aliv_t", "Aliviadero", 470, 120, 120, 20, size=11)
    d.value("aliv", "SSCC.CaudalAliviadero", 470, 142, 110, 24, "m³/s", 1, size=12, alarms=[("gt", 1.0, "#e89a1c")])
    # Units
    for i, (unit, _, name) in enumerate(UNITS):
        x = 740 + i * 330
        d.path("pipe", f"ramal{i}", [[x + 70, 440], [x + 70, 400]], stroke_color="#4f86b8", stroke_width=10)
        d.label(f"{unit}_t", name.upper(), x, 72, 290, 22, size=13, bold=True, color="#1f2a33")
        d.add("faceplate", f"tile_{unit}", x, 96, 290, 214, template="grupo", bindings=dict(
            paso=f"{unit}.Paso", potencia=f"{unit}.Potencia", consigna=f"{unit}.ConsignaP", velocidad=f"{unit}.Velocidad",
            caudal=f"{unit}.Caudal", acoplado=f"{unit}.Acoplado", remoto=f"{unit}.Remoto", alarma=f"{unit}.AlarmaGrupo",
            listo=f"{unit}.ListoArranque", disparo=f"{unit}.Disparo", causa=f"{unit}.CausaDisparo",
            arranque=f"{unit}.OrdenArranque", parada=f"{unit}.OrdenParada", rearme=f"{unit}.OrdenRearme"))
        d.add("image", f"maquina_{unit}", x + 30, 318, 80, 84, source="assets/grupo_parado.svg",
              dynamics=dict(states=[dict(when=condition(f"{unit}.Paso", "eq", 10), style=dict(source="assets/grupo_disparo.svg")),
                                    dict(when=condition(f"{unit}.Velocidad", "gt", 5.0), style=dict(source="assets/grupo_marcha.svg"))]))
        d.button(f"ir_{unit}", f"Detalle {unit} →", x + 140, 344, 150, 34, action="screen", screen=f"3{i}_grupo{i + 1}",
                 target_container="contenido", color="#2b6cb0", border_color="#2b6cb0", text_color="#ffffff")
    d.path("line", "desague", [[1240, 440], [1370, 440]], stroke_color="#4f86b8", stroke_width=6, arrows="end")
    d.label("desague_t", "Río / canal de desagüe", 1220, 410, 160, 20, size=11)
    # KPI strip
    kpis = [("Potencia planta", "Sistema.PotenciaTotal", "MW", 2), ("Energía hoy", "Sistema.EnergiaHoy", "MWh", 1),
            ("Caudal turbinado", "Sistema.CaudalTurbinado", "m³/s", 2), ("Caudal de entrada", "SSCC.CaudalEntrada", "m³/s", 1),
            ("Salto bruto", "SSCC.SaltoBruto", "m", 2), ("Frecuencia red", "SSCC.FrecuenciaRed", "Hz", 3)]
    for i, (caption, tag, unit, decimals) in enumerate(kpis):
        x = 10 + i * 231
        d.panel(f"kpi{i}", x, 476, 223, 64)
        d.label(f"kpi{i}_t", caption.upper(), x + 12, 481, 200, 18, size=10, bold=True)
        d.add("text", f"kpi{i}_v", x + 8, 500, 207, 34, text="", tag=tag, unit=unit, decimals=decimals, font_size=20,
              bold=True, text_align="left", color="#eceef0", border_color="#eceef0", text_color="#1f2a33")
    d.add("alarm_view", "alarmas", 10, 548, 1380, 280, view="activas")


def build_reservoir(project):
    d = screen(project, "20_embalse", "Embalse, presa y aliviadero",
               "Presa de gravedad · coronación 817,00 · NMN 815,00 · umbral aliviadero 808,00 · mínimo de explotación 800,00 msnm")
    d.panel("seccion", 10, 60, 820, 462, "Sección por la presa")
    low, high, top, bottom = 795.0, 818.0, 100, 500
    d.add("rectangle", "vaso", 30, top, 420, bottom - top, color="#ffffff", stroke_color="#b4bbc2", stroke_width=1)
    d.bar("agua", "SSCC.NivelEmbalse", 32, top + 2, 416, bottom - top - 4, low, high, color="#4f86b8",
          alarms=[("ge", 815.0, "#d32f2f"), ("ge", 814.5, "#e89a1c"), ("le", 802.0, "#e89a1c")])
    for i, (cota, caption) in enumerate([(817.0, "Coronación 817,00"), (815.0, "NMN 815,00"), (808.0, "Umbral aliviadero 808,00"),
                                         (800.0, "Mínimo explotación 800,00")]):
        y = bottom - (cota - low) / (high - low) * (bottom - top)
        d.path("line", f"cota{i}", [[32, y], [400, y]], stroke_color="#6c7882", stroke_width=1, stroke_style="dash")
        d.label(f"cota{i}_t", caption, 40, y - 20, 250, 20, size=11, color="#1f2a33")
    d.add("image", "presa", 380, 86, 200, 422, source="assets/presa.svg")
    d.path("pipe", "salida", [[560, 470], [810, 470]], stroke_color="#4f86b8", stroke_width=8, arrows="end")
    for i, (caption, tag, unit_, decimals) in enumerate([("Nivel de embalse", "SSCC.NivelEmbalse", "msnm", 2),
                                                         ("Volumen embalsado", "SSCC.Volumen", "hm³", 2),
                                                         ("Pluviómetro", "SSCC.Lluvia", "mm/h", 1),
                                                         ("Temperatura ambiente", "SSCC.TempAmbiente", "°C", 1)]):
        d.label(f"r{i}_t", caption, 610, 100 + i * 64, 200, 22, size=12, color="#1f2a33")
        d.value(f"r{i}", tag, 610, 124 + i * 64, 160, 28 if i else 32, unit_, decimals, size=16 if i == 0 else 14,
                alarms=[("ge", 815.0, "#d32f2f"), ("ge", 814.5, "#e89a1c")] if i == 0 else ())
    d.label("abajo_t", "Nivel de desagüe", 610, 408, 200, 22, size=12, color="#1f2a33")
    d.value("desague", "SSCC.NivelDesague", 610, 432, 160, 26, "msnm", 2)

    d.panel("caudales", 840, 60, 550, 250, "Balance de caudales")
    rows = [("Caudal de entrada", "SSCC.CaudalEntrada", [("gt", 60.0, "#e89a1c")]),
            ("Caudal turbinado (G1 + G2)", "Sistema.CaudalTurbinado", []),
            ("Caudal por aliviadero", "SSCC.CaudalAliviadero", [("gt", 1.0, "#e89a1c")]),
            ("Caudal ecológico", "SSCC.CaudalEcologico", []),
            ("Caudal total de salida", "SSCC.CaudalSalida", []),
            ("Salto bruto", "SSCC.SaltoBruto", [])]
    for i, (caption, tag, alarms) in enumerate(rows):
        d.field(f"q{i}", caption, tag, 856, 92 + i * 34, "m" if "Salto" in caption else "m³/s", 518, 150, 2, alarms)

    d.panel("aliv", 840, 318, 550, 204, "Aliviadero · 2 compuertas Taintor 8 × 6 m")
    for i in (1, 2):
        x = 852 + (i - 1) * 262
        d.label(f"c{i}_t", f"Compuerta {i}", x, 340, 120, 20, size=12, bold=True, color="#1f2a33")
        d.add("faceplate", f"compuerta{i}", x, 360, 250, 156, template="compuerta", bindings=dict(
            posicion=f"SSCC.PosCompuerta{i}", consigna=f"SSCC.ConsignaCompuerta{i}", automatico="SSCC.AliviaderoAuto"))
    d.add("button", "modo_aliv", 1236, 330, 144, 28, text="Auto / manual", tag="SSCC.AliviaderoAuto", action="toggle",
          font_size=12, bold=True, color="#ffffff", border_color="#2b6cb0", text_color="#2b6cb0")

    d.add("trend", "tendencia", 10, 530, 860, 300, view="embalse")
    d.panel("toma", 880, 530, 510, 300, "Toma y tubería forzada")
    d.add("rectangle", "toma_marco", 900, 566, 60, 200, color="#ffffff", stroke_color="#6c7882", stroke_width=2)
    d.bar("toma_pos", "SSCC.PosCompuertaToma", 904, 570, 52, 192, 0, 100, color="#6c7882")
    d.label("toma_pos_t", "Compuerta de toma", 980, 566, 200, 20, size=12, color="#1f2a33")
    d.value("toma_pos_v", "SSCC.PosCompuertaToma", 980, 590, 120, 28, "%", 1)
    d.status("toma_ab", "Abierta", "SSCC.CompuertaTomaAbierta", 1120, 566, 120)
    d.status("toma_ce", "Cerrada", "SSCC.CompuertaTomaCerrada", 1120, 594, 120, "#d32f2f", "#9aa3ab")
    d.command("abrir_toma", "ABRIR TOMA", "SSCC.OrdenAbrirToma", 980, 640, 180)
    d.command("cerrar_toma", "CERRAR TOMA", "SSCC.OrdenCerrarToma", 1180, 640, 190, color="#6c7882",
              enabled=condition("SSCC.CompuertaTomaCerrada", "eq", False), reason="La compuerta ya está cerrada")
    d.label("toma_nota", "El PLC solo cierra la toma con ambos grupos parados.", 980, 686, 395, 36, size=12)
    d.field("p_tub", "Presión en tubería forzada", "SSCC.PresionTuberia", 980, 740, "bar", 395, 120, 2)
    d.field("caudal_tub", "Caudal turbinado total", "Sistema.CaudalTurbinado", 980, 776, "m³/s", 395, 120, 2)


def build_unit(project, index, unit, name):
    key = f"3{index}_grupo{index + 1}"
    d = screen(project, key, f"{name} · turbina Francis",
               "10 MW · 6,3 kV · 600 rpm · salto de diseño 82 m · caudal nominal 14,5 m³/s")
    d.add("text_list", "estado", 930, 10, 460, 40, tag=f"{unit}.Paso", font_size=17, bold=True, text_color="#ffffff",
          color="#9aa3ab", border_color="#9aa3ab", texts=[dict(value=str(i), text=t.upper()) for i, t in enumerate(STEPS)],
          default_text="SIN COMUNICACIÓN", dynamics=dict(states=[
              dict(when=condition(f"{unit}.Paso", "eq", 10), style=dict(color="#d32f2f", border_color="#d32f2f")),
              dict(when=condition(f"{unit}.Paso", "eq", 6), style=dict(color="#2e8b57", border_color="#2e8b57")),
              dict(when=condition(f"{unit}.Paso", "gt", 0), style=dict(color="#e89a1c", border_color="#e89a1c"))],
              bad=dict(color="#e89a1c", border_color="#e89a1c")))

    # Hydraulic / machine schematic
    d.panel("esquema", 10, 60, 560, 462, "Esquema hidráulico y máquina")
    d.path("pipe", "tuberia", [[24, 180], [150, 180]], stroke_color="#4f86b8", stroke_width=14)
    d.path("pipe", "espiral", [[190, 180], [250, 180]], stroke_color="#4f86b8", stroke_width=14,
           dynamics=dict(states=[dict(when=condition(f"{unit}.ValvulaCerrada", "eq", True), style=dict(stroke_color="#a9b1b8"))]))
    # Main inlet (butterfly) valve symbol
    d.add("ellipse", "valvula", 146, 158, 46, 46, color="#9aa3ab", stroke_color="#1f2a33", stroke_width=2,
          dynamics=dict(states=[dict(when=condition(f"{unit}.ValvulaAbierta", "eq", True), style=dict(color="#2e8b57")),
                                dict(when=condition(f"{unit}.ValvulaCerrada", "eq", False), style=dict(color="#e89a1c"))],
                        bad=dict(color="#e89a1c")))
    d.path("line", "valvula_disco", [[156, 170], [182, 192]], stroke_color="#ffffff", stroke_width=4)
    d.label("valvula_t", "Válvula de entrada", 110, 210, 130, 18, size=11, align="center")
    d.add("image", "maquina", 250, 92, 180, 290, source="assets/grupo_parado_alto.svg",
          dynamics=dict(states=[dict(when=condition(f"{unit}.Paso", "eq", 10), style=dict(source="assets/grupo_disparo_alto.svg")),
                                dict(when=condition(f"{unit}.Velocidad", "gt", 5.0), style=dict(source="assets/grupo_marcha_alto.svg"))]))
    d.add("gauge", "tacometro", 440, 168, 124, 124, tag=f"{unit}.VelocidadRpm", min=0, max=800, unit="rpm", decimals=0,
          text="Velocidad", gauge_style="dial", warning=660, alarm=690)
    d.path("pipe", "aspiracion", [[340, 382], [340, 410], [540, 410]], stroke_color="#4f86b8", stroke_width=12, arrows="end")
    d.label("aspiracion_t", "Tubo de aspiración", 380, 386, 160, 18, size=11)
    # Generator connection to 52G
    d.energized("line", "cable_gen", [[430, 140], [470, 140], [470, 120]], f"{unit}.Tension", 1.0)
    d.add("faceplate", "52g", 448, 76, 44, 44, template="interruptor", bindings=dict(cerrado=f"{unit}.Interruptor52G"))
    d.energized("line", "cable_trafo", [[470, 76], [470, 66], [540, 66]], f"{unit}.Interruptor52G")
    d.label("52g_t", "52G", 500, 86, 50, 20, size=12, bold=True, color="#1f2a33")
    d.label("trafo_t", "→ TP 6,3/66 kV", 440, 44, 120, 18, size=11)
    for i, (caption, tag, unit_, decimals) in enumerate([("Válvula", f"{unit}.PosValvula", "%", 1), ("Distribuidor", f"{unit}.Distribuidor", "%", 1),
                                                         ("Caudal", f"{unit}.Caudal", "m³/s", 2), ("P. espiral", f"{unit}.PresionEspiral", "bar", 2)]):
        d.field(f"h{i}", caption, tag, 24, 236 + i * 34, unit_, 220, 110, decimals)
    d.field("rpm", "Velocidad", f"{unit}.VelocidadRpm", 24, 440, "rpm", 260, 120, 0,
            alarms=[("gt", 660.0, "#d32f2f")])
    d.field("vel", "", f"{unit}.Velocidad", 290, 440, "%", 130, 110, 1)
    d.label("aux_t", "AUXILIARES", 24, 476, 120, 18, size=10, bold=True)
    for i, (caption, tag) in enumerate([("Refrigeración", f"{unit}.Refrigeracion"), ("Bomba oleo.", f"{unit}.BombaOleo"),
                                        ("Frenos", f"{unit}.Frenos"), ("Int. campo", f"{unit}.InterruptorCampo")]):
        d.status(f"aux{i}", caption, tag, 24 + i * 134, 494, 130, "#2e8b57" if i != 2 else "#e89a1c")

    # Electrical
    d.panel("electrico", 580, 60, 340, 250, "Generador")
    rows = [("Potencia activa", f"{unit}.Potencia", "MW", 2), ("Potencia reactiva", f"{unit}.Reactiva", "Mvar", 2),
            ("Tensión", f"{unit}.Tension", "kV", 2), ("Intensidad", f"{unit}.Intensidad", "A", 0),
            ("Frecuencia", f"{unit}.Frecuencia", "Hz", 2), ("Factor de potencia", f"{unit}.CosPhi", "", 3),
            ("Corriente de excitación", f"{unit}.CorrienteExcitacion", "A", 0)]
    for i, (caption, tag, unit_, decimals) in enumerate(rows):
        d.field(f"e{i}", caption, tag, 594, 90 + i * 30, unit_, 312, 120, decimals)

    # Sequence
    d.panel("secuencia", 580, 318, 340, 204, "Secuencia de arranque / parada")
    for i in range(1, 10):
        column, row = (0, i - 1) if i <= 6 else (1, i - 7)
        x, y = 594 + column * 0, 346 + (i - 1) * 19
        done_limit = 6 if i <= 6 else 9
        active = "#2e8b57" if i == 6 else "#e89a1c"  # «En carga» is the steady state, not a transition
        d.add("rectangle", f"paso{i}", x, y + 3, 12, 12, color="#ffffff", stroke_color="#6c7882", stroke_width=1,
              dynamics=dict(states=[dict(when=condition(f"{unit}.Paso", "eq", i), style=dict(color=active, stroke_color=active)),
                                    dict(when=condition(f"{unit}.Paso", "gt", done_limit), style=dict(color="#ffffff")),
                                    dict(when=condition(f"{unit}.Paso", "gt", i), style=dict(color="#2e8b57", stroke_color="#2e8b57"))]))
        d.label(f"paso{i}_t", f"{i}. {STEPS[i]}", x + 20, y, 300, 18, size=12, color="#1f2a33")
    d.label("paso_div", "— parada —", 790, 346 + 6 * 19 - 2, 120, 16, size=10, align="right")

    # Command panel
    d.panel("mando", 930, 60, 460, 250, "Mando")
    d.state_text("modo", f"{unit}.Remoto", 944, 88, 140, 30, "REMOTO", "LOCAL", "#6c7882", "#e89a1c")
    d.status("listo", "Listo para arrancar", f"{unit}.ListoArranque", 1100, 92, 280)
    remote = condition(f"{unit}.Remoto", "eq", True)
    d.command("arrancar", "ARRANCAR", f"{unit}.OrdenArranque", 944, 130, 140, 40, "#2e8b57",
              enabled=condition(f"{unit}.ListoArranque", "eq", True), reason="Condiciones de arranque no cumplidas")
    d.command("parar", "PARAR", f"{unit}.OrdenParada", 1094, 130, 140, 40, "#6c7882",
              enabled=condition(f"{unit}.Paso", "ne", 0), reason="El grupo ya está parado")
    d.command("rearmar", "REARME 86", f"{unit}.OrdenRearme", 1244, 130, 132, 40, "#2b6cb0",
              enabled=condition(f"{unit}.Disparo", "eq", True), reason="No hay disparo que rearmar")
    d.setpoint("sp_p", "Consigna de potencia activa", f"{unit}.ConsignaP", 944, 184, "MW", 432, 120, remote, "Grupo en local")
    d.setpoint("sp_q", "Consigna de potencia reactiva", f"{unit}.ConsignaQ", 944, 216, "Mvar", 432, 120, remote, "Grupo en local")
    d.button("emergencia", "PARADA DE EMERGENCIA", 944, 256, 250, 42, action="popup", screen=f"9{5 + index}_emergencia_{unit.lower()}",
             modal=True, color="#d32f2f", border_color="#8e1c1c", text_color="#ffffff", font_size=14)
    d.label("causa_t", "Causa de disparo", 1206, 254, 170, 16, size=10, bold=True)
    d.add("text_list", "causa", 1206, 272, 170, 26, tag=f"{unit}.CausaDisparo", font_size=11, bold=True,
          texts=[dict(value=str(i), text=t) for i, t in enumerate(TRIP_CAUSES)], default_text="—",
          color="#f8f9fa", border_color="#b4bbc2", text_color="#1f2a33",
          dynamics=dict(states=[dict(when=condition(f"{unit}.CausaDisparo", "gt", 0), style=dict(color="#d32f2f", text_color="#ffffff", border_color="#d32f2f"))]))

    # Temperatures and vibration
    d.panel("temps", 930, 318, 460, 204, "Temperaturas y vibración")
    sensors = [("Guía sup.", f"{unit}.TempGuiaSup", 70, 80, 120), ("Empuje", f"{unit}.TempEmpuje", 75, 85, 120),
               ("Guía turb.", f"{unit}.TempGuiaTurbina", 70, 80, 120), ("Estator", f"{unit}.TempEstator", 110, 130, 150),
               ("Aceite", f"{unit}.TempAceite", 65, 75, 120)]
    for i, (caption, tag, alarm, trip, scale) in enumerate(sensors):
        x = 944 + i * 74
        d.label(f"t{i}_t", caption, x - 4, 340, 74, 20, size=11, align="center")
        d.bar(f"t{i}", tag, x + 14, 362, 36, 110, 0, scale, color="#6c7882",
              alarms=[("ge", trip, "#d32f2f"), ("ge", alarm, "#e89a1c")])
        d.value(f"t{i}_v", tag, x - 2, 478, 68, 24, "°C", 1, alarms=[("ge", trip, "#d32f2f"), ("ge", alarm, "#e89a1c")], size=12, align="center")
    d.label("vib_t", "Vibración", 1312, 340, 78, 20, size=11, align="center")
    d.bar("vib", f"{unit}.Vibracion", 1330, 362, 36, 110, 0, 10, color="#6c7882", alarms=[("ge", 7.1, "#d32f2f"), ("ge", 4.5, "#e89a1c")])
    d.value("vib_v", f"{unit}.Vibracion", 1312, 478, 72, 24, "mm/s", 1, alarms=[("ge", 7.1, "#d32f2f"), ("ge", 4.5, "#e89a1c")], size=12, align="center")

    # Bottom: unit alarms and machine data
    d.add("alarm_view", "alarmas", 10, 530, 900, 300, view=f"activas_{unit.lower()}")
    d.panel("datos", 920, 530, 470, 300, "Datos de máquina")
    rows = [("Presión grupo oleohidráulico", f"{unit}.PresionOleo", "bar", 1, [("lt", 52.0, "#e89a1c")]),
            ("Caudal agua de refrigeración", f"{unit}.CaudalRefrigeracion", "l/s", 1, []),
            ("Energía generada (contador)", f"{unit}.Energia", "MWh", 1, []),
            ("Horas de funcionamiento", f"{unit}.HorasMarcha", "h", 0, []),
            ("Número de arranques", f"{unit}.Arranques", "", 0, [])]
    for i, (caption, tag, unit_, decimals, alarms) in enumerate(rows):
        d.field(f"d{i}", caption, tag, 936, 562 + i * 34, unit_, 440, 140, decimals, alarms)
    d.status("rugosa", "Zona de funcionamiento rugoso (distribuidor 25–45 %)", f"{unit}.ZonaRugosa", 936, 740, 440, "#e89a1c", "#9aa3ab")
    d.status("fallo_ref", "Fallo de agua de refrigeración", f"{unit}.FalloRefrigeracion", 936, 768, 440, "#d32f2f", "#9aa3ab")
    d.button("tendencia", "Ver tendencias térmicas →", 936, 794, 250, 30, action="screen",
             screen=f"7{2 + index}_tend_{unit.lower()}", target_container="contenido")

    # Emergency stop confirmation (modal)
    c = screen(project, f"9{5 + index}_emergencia_{unit.lower()}", f"Confirmar parada de emergencia · {name}", None, 520, 260, "#fbeaea")
    c.label("icono", "⚠", 20, 20, 60, 60, size=40, bold=True, color="#d32f2f")
    c.label("texto", f"¿Disparar el {name} con PARADA DE EMERGENCIA?", 90, 22, 410, 50, size=17, bold=True, color="#1f2a33")
    c.label("detalle", "Abre el 52G, cierra el distribuidor y la válvula de entrada de forma rápida. El grupo queda bloqueado (86) hasta el rearme.",
            90, 76, 410, 70, size=13, color="#1f2a33")
    c.command("confirmar", "CONFIRMAR DISPARO", f"{unit}.OrdenEmergencia", 90, 170, 220, 46, "#d32f2f")
    c.button("cancelar", "Cerrar", 330, 170, 170, 46, action="close_popup")


def build_single_line(project):
    d = screen(project, "40_unifilar", "Esquema unifilar · subestación 66 kV",
               "Rojo = interruptor cerrado · verde = abierto · azul = conductor en tensión")
    d.panel("fondo", 10, 60, 1010, 770)
    d.label("linea_t", "LÍNEA L-6601 → SE COMARCAL 66 kV", 360, 70, 400, 22, size=13, bold=True, color="#1f2a33")
    d.energized("line", "linea", [[520, 96], [520, 140]], "SSCC.RedPresente", width=5)
    d.add("faceplate", "52l", 498, 140, 44, 44, template="interruptor", bindings=dict(cerrado="SSCC.Interruptor52L"))
    d.label("52l_t", "52L", 552, 150, 50, 22, size=13, bold=True, color="#1f2a33")
    d.command("abrir_52l", "ABRIR 52L", "SSCC.OrdenAbrir52L", 620, 140, 130, 34, "#2e7d32",
              enabled=condition("SSCC.Interruptor52L", "eq", True), reason="El interruptor ya está abierto")
    d.command("cerrar_52l", "CERRAR 52L", "SSCC.OrdenCerrar52L", 760, 140, 130, 34, "#c62828",
              enabled=condition("SSCC.RedPresente", "eq", True), reason="Sin tensión de red en la línea")
    d.energized("line", "bajada", [[520, 184], [520, 230]], "SSCC.TensionBarras66", 10.0, 5)
    d.energized("line", "barras", [[120, 230], [920, 230]], "SSCC.TensionBarras66", 10.0, 8)
    d.label("barras_t", "BARRAS 66 kV", 130, 204, 140, 20, size=12, bold=True, color="#1f2a33")
    d.value("barras_v", "SSCC.TensionBarras66", 790, 196, 120, 26, "kV", 1)

    for i, (unit, _, name) in enumerate(UNITS):
        x = 260 + i * 300
        d.energized("line", f"f{i}a", [[x, 230], [x, 280]], "SSCC.TensionBarras66", 10.0)
        d.add("ellipse", f"tp{i}a", x - 26, 280, 52, 52, filled=False, stroke_color="#1f2a33", stroke_width=2)
        d.add("ellipse", f"tp{i}b", x - 26, 314, 52, 52, filled=False, stroke_color="#1f2a33", stroke_width=2)
        d.label(f"tp{i}_t", f"TP{i + 1}  66/6,3 kV  12,5 MVA", x + 34, 312, 200, 20, size=12, color="#1f2a33")
        # The transformer LV side is live from the 66 kV busbar whatever the 52G state.
        d.energized("line", f"f{i}b", [[x, 366], [x, 410]], "SSCC.TensionBarras66", 10.0)
        d.add("faceplate", f"52g{i}", x - 22, 410, 44, 44, template="interruptor", bindings=dict(cerrado=f"{unit}.Interruptor52G"))
        d.label(f"52g{i}_t", f"52{unit}", x + 30, 420, 60, 20, size=13, bold=True, color="#1f2a33")
        d.energized("line", f"f{i}c", [[x, 454], [x, 510]], f"{unit}.Tension", 1.0)
        d.add("ellipse", f"gen{i}", x - 36, 510, 72, 72, color="#ffffff", stroke_color="#1f2a33", stroke_width=3,
              dynamics=dict(states=[dict(when=condition(f"{unit}.Paso", "eq", 10), style=dict(stroke_color="#d32f2f")),
                                    dict(when=condition(f"{unit}.Acoplado", "eq", True), style=dict(stroke_color="#1f5f99"))]))
        d.label(f"gen{i}_t", unit, x - 36, 534, 72, 26, size=18, bold=True, color="#1f2a33", align="center")
        d.label(f"gen{i}_d", f"{name} · 6,3 kV", x - 80, 590, 160, 20, size=12, align="center")
        for j, (caption, tag, unit_, decimals) in enumerate([("P", f"{unit}.Potencia", "MW", 2), ("Q", f"{unit}.Reactiva", "Mvar", 2),
                                                             ("U", f"{unit}.Tension", "kV", 2), ("I", f"{unit}.Intensidad", "A", 0)]):
            d.field(f"m{i}{j}", caption, tag, x + 50, 474 + j * 30, unit_, 150, 118, decimals)

    # Auxiliary services feeder
    x = 860
    d.energized("line", "aux_a", [[x, 230], [x, 300]], "SSCC.TensionBarras66", 10.0)
    d.add("ellipse", "tsa_a", x - 20, 300, 40, 40, filled=False, stroke_color="#1f2a33", stroke_width=2)
    d.add("ellipse", "tsa_b", x - 20, 326, 40, 40, filled=False, stroke_color="#1f2a33", stroke_width=2)
    d.label("tsa_t", "TSA 66/0,4 kV", x - 150, 322, 120, 20, size=12, color="#1f2a33", align="right")
    d.energized("line", "aux_b", [[x, 366], [x, 650]], "SSCC.TrafoAuxOk")
    d.energized("line", "barras_400", [[620, 650], [960, 650]], "SSCC.Tension400V", 300.0, 6)
    d.label("b400_t", "SERVICIOS AUXILIARES 400 V", 630, 660, 260, 20, size=12, bold=True, color="#1f2a33")
    d.value("b400_v", "SSCC.Tension400V", 860, 680, 100, 26, "V", 0)
    d.energized("line", "diesel_l", [[700, 650], [700, 720]], "SSCC.GrupoDiesel")
    d.add("ellipse", "diesel", 676, 720, 48, 48, color="#ffffff", stroke_color="#1f2a33", stroke_width=2,
          dynamics=dict(states=[dict(when=condition("SSCC.GrupoDiesel", "eq", True), style=dict(color="#2e8b57"))]))
    d.label("diesel_t", "GE", 676, 732, 48, 24, size=14, bold=True, color="#1f2a33", align="center")
    d.label("diesel_d", "Grupo diésel de emergencia 250 kVA", 734, 734, 270, 20, size=12)

    # Fiscal meter
    d.panel("contador", 1030, 60, 360, 330, "Contador fiscal 66 kV (Modbus)")
    rows = [("Potencia activa", "Contador.Potencia", "MW", 2), ("Potencia reactiva", "Contador.Reactiva", "Mvar", 2),
            ("Tensión", "Contador.Tension", "kV", 2), ("Frecuencia", "Contador.Frecuencia", "Hz", 3),
            ("Factor de potencia", "Contador.CosPhi", "", 3), ("Energía exportada", "Contador.EnergiaExportada", "kWh", 0),
            ("Energía importada", "Contador.EnergiaImportada", "kWh", 0)]
    for i, (caption, tag, unit_, decimals) in enumerate(rows):
        d.field(f"c{i}", caption, tag, 1046, 92 + i * 34, unit_, 330, 160, decimals)
    d.status("c_com", "Comunicación con contador", "Contador.Comunicacion", 1046, 342, 330)
    d.panel("red", 1030, 400, 360, 160, "Red")
    d.status("red_ok", "Tensión de red presente", "SSCC.RedPresente", 1046, 432, 330, "#2e8b57", "#d32f2f")
    d.field("red_f", "Frecuencia de red", "SSCC.FrecuenciaRed", 1046, 466, "Hz", 330, 140, 3,
            alarms=[("lt", 49.8, "#e89a1c"), ("gt", 50.2, "#e89a1c")])
    d.field("red_v", "Tensión de barras", "SSCC.TensionBarras66", 1046, 502, "kV", 330, 140, 2)
    d.panel("leyenda", 1030, 570, 360, 260, "Leyenda")
    for i, (color, caption) in enumerate([("#c62828", "Interruptor cerrado (I)"), ("#2e7d32", "Interruptor abierto (O)"),
                                          ("#1f5f99", "Conductor en tensión"), ("#a9b1b8", "Conductor sin tensión"),
                                          ("#e89a1c", "Calidad de dato dudosa / sin comunicación")]):
        d.add("rectangle", f"ley{i}", 1048, 606 + i * 40, 26, 26, color=color, stroke_color="#1f2a33", stroke_width=1)
        d.label(f"ley{i}_t", caption, 1086, 608 + i * 40, 290, 22, size=13, color="#1f2a33")


def build_auxiliaries(project):
    d = screen(project, "50_auxiliares", "Servicios auxiliares",
               "Grupos oleohidráulicos, refrigeración, drenaje, aire comprimido, corriente continua y 400 V")
    for i, (unit, _, name) in enumerate(UNITS):
        x = 10 + i * 345
        d.panel(f"oleo{i}", x, 60, 335, 370, f"Oleohidráulico y refrigeración {unit}")
        # Accumulator manometer; the needle turns red through the dynamic style below 52 bar.
        d.add("gauge", f"oleo{i}_m", x + 14, 92, 170, 170, tag=f"{unit}.PresionOleo", min=0, max=80, unit="bar", decimals=1,
              text="Acumulador", gauge_style="dial", warning=66, alarm=72, color="#34495e",
              dynamics=dict(states=[dict(when=condition(f"{unit}.PresionOleo", "lt", 52.0), style=dict(color="#d32f2f"))]))
        d.value(f"oleo{i}_v", f"{unit}.PresionOleo", x + 200, 100, 120, 30, "bar", 1, alarms=[("lt", 45.0, "#d32f2f"), ("lt", 52.0, "#e89a1c")], size=16)
        d.add("faceplate", f"oleo{i}_p", x + 200, 146, 50, 50, template="bomba", bindings=dict(marcha=f"{unit}.BombaOleo", fallo=f"{unit}.FalloBombaOleo"))
        d.label(f"oleo{i}_pt", "Bomba de aceite\n56 / 63 bar", x + 256, 146, 76, 50, size=11, color="#1f2a33")
        d.label(f"oleo{i}_lim", "Alarma 52 bar\nDisparo 45 bar", x + 200, 210, 130, 40, size=11)
        d.field(f"ref{i}", "Caudal refrigeración", f"{unit}.CaudalRefrigeracion", x + 20, 334, "l/s", 300, 110, 1)
        d.status(f"ref{i}_s", "Fallo de refrigeración", f"{unit}.FalloRefrigeracion", x + 20, 372, 300, "#d32f2f", "#9aa3ab")
        d.status(f"ref{i}_on", "Bombas de refrigeración", f"{unit}.Refrigeracion", x + 20, 398, 300)

    d.panel("drenaje", 700, 60, 340, 370, "Pozo de drenaje de la central")
    d.add("rectangle", "pozo_m", 720, 96, 90, 260, color="#ffffff", stroke_color="#6c7882", stroke_width=2)
    d.bar("pozo", "SSCC.NivelPozo", 724, 100, 82, 252, 0, 100, color="#4f86b8", alarms=[("ge", 80.0, "#d32f2f")])
    d.value("pozo_v", "SSCC.NivelPozo", 720, 366, 90, 28, "%", 0, alarms=[("ge", 80.0, "#d32f2f")])
    for i, (caption, tag, limits) in enumerate([("Bomba 1 (principal)", "SSCC.BombaDrenaje1", "60 / 20 %"),
                                                ("Bomba 2 (reserva)", "SSCC.BombaDrenaje2", "78 / 30 %")]):
        y = 110 + i * 120
        d.add("faceplate", f"bd{i}", 830, y, 50, 50, template="bomba", bindings=dict(marcha=tag, fallo="SSCC.FalloDrenaje"))
        d.label(f"bd{i}_t", caption, 890, y + 2, 140, 20, size=13, bold=True, color="#1f2a33")
        d.label(f"bd{i}_l", f"Arranque / parada {limits}", 890, y + 24, 140, 36, size=11)
    d.label("pozo_nota", "Alarma de nivel alto: 80 %", 830, 366, 200, 22, size=12)

    d.panel("aire", 1050, 60, 340, 180, "Aire comprimido (frenos)")
    d.add("faceplate", "compresor", 1068, 96, 50, 50, template="bomba", bindings=dict(marcha="SSCC.Compresor", fallo="SSCC.FalloCompresor"))
    d.label("compresor_t", "Compresor\narranca 7 · para 8 bar", 1128, 98, 250, 44, size=12, color="#1f2a33")
    d.field("aire_v", "Presión calderín", "SSCC.PresionAire", 1068, 166, "bar", 300, 110, 2, alarms=[("lt", 6.0, "#e89a1c")])
    d.label("aire_n", "Alarma de presión baja: 6 bar", 1068, 202, 300, 20, size=11)

    d.panel("cc", 1050, 250, 340, 180, "Corriente continua 125 V")
    d.status("cargador", "Rectificador-cargador", "SSCC.CargadorOk", 1068, 284, 300, "#2e8b57", "#d32f2f")
    d.field("bat", "Tensión de baterías", "SSCC.TensionBaterias", 1068, 318, "V", 300, 110, 1,
            alarms=[("lt", 105.0, "#d32f2f"), ("lt", 110.0, "#e89a1c")])
    d.label("bat_n", "Batería de plomo 60 elementos · alarma 110 V · crítica 105 V", 1068, 354, 300, 40, size=11)

    d.panel("ca", 10, 440, 690, 170, "Servicios auxiliares de corriente alterna 400 V")
    d.status("tsa", "Transformador de servicios auxiliares", "SSCC.TrafoAuxOk", 30, 476, 340, "#2e8b57", "#d32f2f")
    d.status("diesel", "Grupo diésel de emergencia", "SSCC.GrupoDiesel", 30, 506, 340, "#e89a1c", "#9aa3ab")
    d.field("v400", "Tensión barras 400 V", "SSCC.Tension400V", 30, 540, "V", 340, 120, 0, alarms=[("lt", 360.0, "#d32f2f")])
    d.label("ca_n", "Ante pérdida de red, el diésel arranca a los 3 s y recupera la barra de 400 V para los auxiliares esenciales.",
            400, 474, 280, 110, size=12)
    d.panel("resumen", 10, 620, 690, 210, "Alarmas por área (calculadas en los PLC)")
    for i, (caption, tag) in enumerate([("Grupo 1", "G1.AlarmaGrupo"), ("Grupo 2", "G2.AlarmaGrupo"),
                                        ("Presa y embalse", "SSCC.AlarmaPresa"), ("Subestación 66 kV", "SSCC.AlarmaSubestacion"),
                                        ("Servicios auxiliares", "SSCC.AlarmaAuxiliares")]):
        d.status(f"area{i}", caption, tag, 30 + (i % 2) * 330, 656 + (i // 2) * 34, 300, "#d32f2f", "#9aa3ab")
    d.label("res_n", "La cabecera muestra este mismo resumen en todas las pantallas.", 30, 770, 640, 40, size=12)
    d.add("alarm_view", "alarmas", 710, 440, 680, 390, view="activas_sscc")

    # Clicking a pump symbol opens its own detail window (one per pump).
    pumps = [(f"oleo{i}_p", f"Bomba de aceite {unit}", f"{unit}.BombaOleo", f"{unit}.FalloBombaOleo")
             for i, (unit, _, _) in enumerate(UNITS)]
    pumps += [("bd0", "Bomba de drenaje 1", "SSCC.BombaDrenaje1", "SSCC.FalloDrenaje"),
              ("bd1", "Bomba de drenaje 2", "SSCC.BombaDrenaje2", "SSCC.FalloDrenaje"),
              ("compresor", "Compresor de aire", "SSCC.Compresor", "SSCC.FalloCompresor")]
    symbols = {e["id"]: e for e in d.data["elements"]}
    for identifier, title, running, fault in pumps:
        s = symbols[identifier]
        d.add("button", identifier + "_abrir", s["x"], s["y"], s["w"], s["h"], text="", action="faceplate_popup",
              template="bomba_detalle", bindings=dict(marcha=running, fallo=fault), title=title,
              color="#00000000", border_color="#00000000")


def build_control(project):
    d = screen(project, "60_control", "Control conjunto de planta",
               "Reparto automático de potencia entre grupos y regulación de nivel del embalse (script control_planta.py cada 2 s)")
    d.panel("conjunto", 10, 60, 680, 330, "Control conjunto de potencia")
    d.state_text("cc_estado", "Planta.ControlConjunto", 30, 94, 200, 34, "ACTIVO", "INACTIVO", "#2e8b57", "#9aa3ab", 14)
    d.add("button", "cc_toggle", 250, 94, 220, 34, text="Activar / desactivar", tag="Planta.ControlConjunto",
          action="toggle", font_size=13, bold=True, color="#ffffff", border_color="#2b6cb0", text_color="#2b6cb0")
    d.setpoint("cc_sp", "Consigna de potencia de planta", "Planta.ConsignaPlanta", 30, 146, "MW", 640, 140,
               condition("Planta.ControlNivel", "eq", False), "La calcula el control de nivel")
    d.field("cc_pv", "Potencia total generada", "Sistema.PotenciaTotal", 30, 182, "MW", 640, 140, 2)
    d.field("cc_g1", "Consigna aplicada Grupo 1", "G1.ConsignaP", 30, 218, "MW", 640, 140, 2)
    d.field("cc_g2", "Consigna aplicada Grupo 2", "G2.ConsignaP", 30, 254, "MW", 640, 140, 2)
    d.label("cc_estado_t", "Estado del controlador", 30, 294, 300, 20, size=12, bold=True)
    d.add("text", "cc_msg", 30, 316, 640, 30, text="", tag="Planta.Estado", font_size=13, text_align="left",
          color="#f8f9fa", border_color="#b4bbc2", text_color="#1f2a33")
    d.label("cc_n", "Reparte la consigna a partes iguales entre los grupos acoplados en remoto, entre 2 y 10 MW por grupo.",
            30, 352, 640, 30, size=12)

    d.panel("nivel", 700, 60, 690, 330, "Regulación de nivel del embalse")
    d.state_text("cn_estado", "Planta.ControlNivel", 720, 94, 200, 34, "ACTIVO", "INACTIVO", "#2e8b57", "#9aa3ab", 14)
    d.add("button", "cn_toggle", 940, 94, 220, 34, text="Activar / desactivar", tag="Planta.ControlNivel",
          action="toggle", font_size=13, bold=True, color="#ffffff", border_color="#2b6cb0", text_color="#2b6cb0")
    d.setpoint("cn_sp", "Consigna de nivel", "Planta.ConsignaNivel", 720, 146, "msnm", 650, 140)
    d.field("cn_pv", "Nivel actual", "SSCC.NivelEmbalse", 720, 182, "msnm", 650, 140, 2)
    d.field("cn_q", "Caudal de entrada", "SSCC.CaudalEntrada", 720, 218, "m³/s", 650, 140, 1)
    d.field("cn_t", "Caudal turbinado", "Sistema.CaudalTurbinado", 720, 254, "m³/s", 650, 140, 2)
    d.label("cn_n", "Con el control de nivel activo, la consigna de planta se ajusta para mantener el embalse en la cota deseada "
            "(acción integral: +1,5 MW por cada metro por encima de la consigna, cada 2 s). Requiere el control conjunto activo.",
            720, 294, 650, 80, size=12)
    d.add("trend", "tend", 10, 400, 1380, 430, view="produccion")


def build_trends(project):
    tabs = [("70_tend_produccion", "Producción", "produccion"), ("71_tend_embalse", "Embalse", "embalse"),
            ("72_tend_g1", "Térmico G1", "termico_g1"), ("73_tend_g2", "Térmico G2", "termico_g2"),
            ("74_tend_electrico", "Eléctrico", "electrico")]
    for key, caption, view in tabs:
        d = screen(project, key, f"Tendencias · {caption}", "Tiempo real e histórico · zoom, cursor y exportación CSV")
        for i, (other, other_caption, _) in enumerate(tabs):
            active = other == key
            d.button(f"tab{i}", other_caption, 930 + i * 92 - 40 * 0, 14, 88, 32, action="screen", screen=other,
                     target_container="contenido", color="#2b6cb0" if active else "#ffffff",
                     border_color="#2b6cb0", text_color="#ffffff" if active else "#2b6cb0", font_size=12)
        d.add("trend", "tendencia", 10, 60, 1380, 770, view=view)


def build_alarm_screens(project):
    tabs = [("80_alarmas", "Activas", "activas"), ("81_alarmas_historico", "Histórico", "historico"), ("82_alarmas_eventos", "Eventos", "eventos")]
    for key, caption, view in tabs:
        d = screen(project, key, f"Alarmas · {caption}", "ACK individual o múltiple · filtros por categoría, prioridad y fecha · exportación CSV")
        for i, (other, other_caption, _) in enumerate(tabs):
            active = other == key
            d.button(f"tab{i}", other_caption, 1110 + i * 94, 14, 90, 32, action="screen", screen=other, target_container="contenido",
                     color="#2b6cb0" if active else "#ffffff", border_color="#2b6cb0", text_color="#ffffff" if active else "#2b6cb0", font_size=12)
        # Alarms on a second monitor: a window with its own «contenido» zone, so the tabs keep working there.
        d.button("ventana", "⧉ Monitor 2", 946, 14, 150, 32, action="popup", screen="05_ventana_alarmas",
                 window=dict(monitor=2, mode="maximized"), font_size=12)
        d.add("alarm_view", "visor", 10, 60, 1380, 770, view=view)
    project.screens["05_ventana_alarmas"] = dict(title="CH Valdearenas · Alarmas", width=1400, height=830,
                                                 background="#dde1e4", elements=[
        dict(id="contenido", kind="screen_container", x=0, y=0, w=1400, h=830, screen="80_alarmas")])


def build_instructor(project):
    d = screen(project, "90_instructor", "Panel del instructor · simulación",
               "Solo para formación: inyecta fallos en el PLC simulado (abscada --simulador hydro). No existe en una planta real.")
    d.add("rectangle", "banda", 10, 60, 1380, 40, color="#fff4dc", stroke_color="#e89a1c", stroke_width=2)
    d.label("banda_t", "MODO FORMACIÓN · las órdenes de esta pantalla activan averías simuladas. Desactívalas para recuperar la normalidad.",
            24, 68, 1350, 24, size=14, bold=True, color="#7a4b00")
    faults = [
        ("SimCojinete", "Calentamiento de cojinete de empuje", "Sube la temperatura del cojinete: alarma a 75 °C y disparo por temperatura a 85 °C."),
        ("SimRefrigeracion", "Fallo del agua de refrigeración", "Cae el caudal de refrigeración: fallo a los 5 s, suben todas las temperaturas y acaba en disparo."),
        ("SimVibracion", "Desequilibrio / vibración", "Vibración por encima de 7,1 mm/s: alarma y disparo por vibración muy alta."),
        ("SimLocal", "Selector en LOCAL", "El grupo pasa a mando local: el SCADA no puede arrancar, parar ni cambiar consignas."),
    ]
    for i, (unit, _, name) in enumerate(UNITS):
        x = 10 + i * 465
        d.panel(f"u{i}", x, 110, 455, 470, name)
        for j, (field, caption, detail) in enumerate(faults):
            y = 146 + j * 106
            d.state_text(f"u{i}f{j}", f"{unit}.{field}", x + 16, y, 110, 30, "ACTIVO", "NORMAL", "#d32f2f", "#9aa3ab", 12)
            d.add("button", f"u{i}b{j}", x + 136, y, 300, 30, text=caption, tag=f"{unit}.{field}", action="toggle",
                  font_size=13, bold=True, color="#ffffff", border_color="#e89a1c", text_color="#7a4b00")
            d.label(f"u{i}d{j}", detail, x + 136, y + 36, 300, 56, size=11)
    common = [
        ("SSCC.SimAvenida", "Avenida en el río", "Entrada de 135 m³/s: sube el embalse, abre el aliviadero en automático y salta la alarma de avenida."),
        ("SSCC.SimFalloRed", "Pérdida de red 66 kV", "Abre el 52L: rechazo de carga, sobrevelocidad y disparo de los grupos. Arranca el diésel."),
        ("SSCC.SimFalloCargador", "Fallo del rectificador-cargador", "Las baterías se descargan lentamente: alarma a 110 V y crítica a 105 V."),
    ]
    d.panel("comun", 940, 110, 450, 470, "Servicios comunes")
    for j, (tag, caption, detail) in enumerate(common):
        y = 146 + j * 140
        d.state_text(f"c{j}", tag, 956, y, 110, 30, "ACTIVO", "NORMAL", "#d32f2f", "#9aa3ab", 12)
        d.add("button", f"cb{j}", 1076, y, 300, 30, text=caption, tag=tag, action="toggle", font_size=13, bold=True,
              color="#ffffff", border_color="#e89a1c", text_color="#7a4b00")
        d.label(f"cd{j}", detail, 1076, y + 36, 300, 80, size=11)
    d.panel("guia", 10, 590, 1380, 240, "Ejercicio recomendado")
    steps = ["1. Comprueba en «Grupo 1» que está LISTO PARA ARRANCAR y pulsa ARRANCAR: sigue los 6 pasos de la secuencia hasta EN CARGA.",
             "2. Cambia la consigna de potencia a 3,5 MW y observa la alarma de zona rugosa (distribuidor entre 25 y 45 %). Vuelve a 8 MW.",
             "3. Activa «Calentamiento de cojinete» del Grupo 1: reconoce la alarma de temperatura y espera al disparo por protección.",
             "4. Desactiva la avería, espera a que el grupo se pare y pulsa REARME 86. Vuelve a arrancar.",
             "5. Provoca una «Pérdida de red 66 kV» con ambos grupos en carga. Restablece, cierra el 52L desde el unifilar y rearma los grupos."]
    for i, line in enumerate(steps):
        d.label(f"g{i}", line, 30, 626 + i * 38, 1340, 34, size=13, color="#1f2a33")


def build_help(project):
    d = screen(project, "99_ayuda", "Ayuda de operación", None, 760, 520, "#ffffff")
    d.label("t", "CH VALDEARENAS · AYUDA RÁPIDA", 24, 18, 700, 30, size=18, bold=True, color="#1f2a33")
    lines = [
        "• Cabecera: potencia, nivel, frecuencia, energía del día y alarmas por área en rojo.",
        "• Grupo 1 / 2: estado de la secuencia, mando (arrancar, parar, rearme 86), consignas P y Q.",
        "• Las órdenes son pulsos: el PLC las borra al aceptarlas. Sin comunicación, el dato se marca «!».",
        "• Parada de emergencia: pide confirmación y bloquea el grupo hasta el rearme.",
        "• Unifilar: rojo = interruptor cerrado, verde = abierto; azul = en tensión.",
        "• Control de planta: reparto de potencia y regulación del nivel del embalse.",
        "• Alarmas: reconocer (ACK) con operador y comentario; filtros e histórico CSV.",
        "• Ventanas: «Mando…» en la ficha de un grupo o un clic en una bomba abre su ventana; arrástrala a otro monitor.",
        "• Simulación: el PLC simulado se arranca con  abscada --simulador hydro.",
    ]
    for i, line in enumerate(lines):
        d.label(f"l{i}", line, 24, 62 + i * 42, 712, 40, size=14, color="#1f2a33")
    d.button("cerrar", "Cerrar", 560, 456, 176, 40, action="close_popup")


# ---------------------------------------------------------------------------
# Operations: alarms, logging, trends, scripts
# ---------------------------------------------------------------------------
def build_operations(project):
    categories = [("g1", "Grupo 1", "#2b6cb0"), ("g2", "Grupo 2", "#6b46c1"), ("presa", "Presa y embalse", "#2c7a7b"),
                  ("subestacion", "Subestación 66 kV", "#c05621"), ("sscc", "Servicios auxiliares", "#718096"),
                  ("sistema", "Sistema SCADA", "#4a5568")]
    items = []

    def alarm(identifier, tag, category, cond, threshold, message, priority, ack=True, hysteresis=0.0, on=1000, off=500):
        items.append(dict(id=identifier, tag=tag, category=category, condition=cond, threshold=threshold, message=message,
                          priority=priority, ack_required=ack, enabled=True, hysteresis=hysteresis,
                          on_delay_ms=on, off_delay_ms=off))

    for unit, _, name in UNITS:
        u, cat = unit, unit.lower()
        alarm(f"{cat}_disparo", f"{u}.Disparo", cat, "true", 0, f"{unit} · Disparo del grupo · bloqueo 86", 1000, on=0)
        alarm(f"{cat}_guia_sup", f"{u}.TempGuiaSup", cat, "high", 70, f"{unit} · Temperatura alta cojinete guía superior", 700, hysteresis=2)
        alarm(f"{cat}_empuje", f"{u}.TempEmpuje", cat, "high", 75, f"{unit} · Temperatura alta cojinete de empuje", 700, hysteresis=2)
        alarm(f"{cat}_guia_turb", f"{u}.TempGuiaTurbina", cat, "high", 70, f"{unit} · Temperatura alta cojinete guía turbina", 700, hysteresis=2)
        alarm(f"{cat}_estator", f"{u}.TempEstator", cat, "high", 110, f"{unit} · Temperatura alta devanado estator", 700, hysteresis=3)
        alarm(f"{cat}_vibracion", f"{u}.Vibracion", cat, "high", 4.5, f"{unit} · Vibración alta en cojinete guía", 600, hysteresis=0.3, on=2000)
        alarm(f"{cat}_oleo", f"{u}.PresionOleo", cat, "low", 52, f"{unit} · Presión baja grupo oleohidráulico", 800, hysteresis=2)
        alarm(f"{cat}_refrigeracion", f"{u}.FalloRefrigeracion", cat, "true", 0, f"{unit} · Fallo de agua de refrigeración", 750)
        alarm(f"{cat}_bomba_oleo", f"{u}.FalloBombaOleo", cat, "true", 0, f"{unit} · Bomba de aceite en marcha sin recuperar presión", 700, on=3000)
        alarm(f"{cat}_rugosa", f"{u}.ZonaRugosa", cat, "true", 0, f"{unit} · Funcionamiento en zona rugosa", 250, ack=False, on=5000)
        alarm(f"{cat}_local", f"{u}.Remoto", cat, "false", 0, f"{unit} · Grupo en mando local", 200, ack=False)
        alarm(f"{cat}_com", f"Sistema.Com{unit}", "sistema", "false", 0, f"Fallo de comunicación con PLC {name}", 900, on=3000)
    alarm("nivel_alto", "SSCC.NivelEmbalse", "presa", "high", 814.5, "Nivel de embalse alto (814,50)", 700, hysteresis=0.1)
    alarm("nivel_nmn", "SSCC.NivelEmbalse", "presa", "high", 815.0, "Nivel máximo normal superado (815,00)", 900, hysteresis=0.1)
    alarm("nivel_bajo", "SSCC.NivelEmbalse", "presa", "low", 802.0, "Nivel de embalse bajo (802,00)", 600, hysteresis=0.2)
    alarm("avenida", "SSCC.CaudalEntrada", "presa", "high", 60.0, "Caudal de entrada de avenida > 60 m³/s", 800, hysteresis=5)
    alarm("vertido", "SSCC.CaudalAliviadero", "presa", "high", 1.0, "Aliviadero vertiendo", 300, ack=False, hysteresis=0.5)
    alarm("toma_cerrada", "SSCC.CompuertaTomaCerrada", "presa", "true", 0, "Compuerta de toma cerrada", 400)
    alarm("red", "SSCC.RedPresente", "subestacion", "false", 0, "Pérdida de tensión en red 66 kV", 1000, on=0)
    alarm("52l", "SSCC.Interruptor52L", "subestacion", "false", 0, "Interruptor de línea 52L abierto", 900, on=0)
    alarm("frecuencia", "SSCC.FrecuenciaRed", "subestacion", "low", 49.8, "Frecuencia de red baja", 700, hysteresis=0.05)
    alarm("cargador", "SSCC.CargadorOk", "sscc", "false", 0, "Fallo de rectificador-cargador 125 Vcc", 700)
    alarm("baterias", "SSCC.TensionBaterias", "sscc", "low", 110, "Tensión de baterías baja", 800, hysteresis=1)
    alarm("pozo", "SSCC.NivelPozo", "sscc", "high", 80, "Nivel alto en pozo de drenaje", 600, hysteresis=5)
    alarm("drenaje", "SSCC.FalloDrenaje", "sscc", "true", 0, "Fallo de drenaje: riesgo de inundación de la central", 900)
    alarm("aire", "SSCC.PresionAire", "sscc", "low", 6.0, "Presión baja de aire comprimido", 500, hysteresis=0.2)
    alarm("compresor", "SSCC.FalloCompresor", "sscc", "true", 0, "Compresor en marcha sin recuperar presión", 500, on=5000)
    alarm("diesel", "SSCC.GrupoDiesel", "sscc", "true", 0, "Grupo diésel de emergencia en servicio", 600)
    alarm("400v", "SSCC.Tension400V", "sscc", "low", 360, "Tensión baja en servicios auxiliares 400 V", 800, hysteresis=5)
    alarm("sscc_com", "Sistema.ComSSCC", "sistema", "false", 0, "Fallo de comunicación con PLC de servicios comunes", 900, on=3000)
    alarm("contador_com", "Sistema.ComContador", "sistema", "false", 0, "Fallo de comunicación con contador fiscal", 500, on=3000)
    project.alarms = dict(retention_days=365, categories=[dict(id=i, name=n, color=c) for i, n, c in categories], items=items)

    columns = ["priority", "category", "message", "state", "entered_at", "returned_at", "ack_at", "actor"]
    views = {
        "activas": dict(title="Alarmas activas y pendientes de reconocer", mode="pending"),
        "historico": dict(title="Histórico de alarmas", mode="history"),
        "eventos": dict(title="Registro de eventos", mode="events"),
        "activas_g1": dict(title="Alarmas del Grupo 1", mode="pending", categories=["g1"]),
        "activas_g2": dict(title="Alarmas del Grupo 2", mode="pending", categories=["g2"]),
        "activas_sscc": dict(title="Alarmas de servicios auxiliares y subestación", mode="pending", categories=["sscc", "subestacion"]),
    }
    project.alarm_views = {k: dict(dict(categories=[], min_priority=1, allow_ack=True, columns=columns), **v) for k, v in views.items()}

    electrical = [f"{u}.{f}" for u, _, _ in UNITS for f in ("Potencia", "Reactiva", "Tension", "Frecuencia", "Velocidad", "Distribuidor", "Caudal")]
    thermal = [f"{u}.{f}" for u, _, _ in UNITS for f in ("TempGuiaSup", "TempEmpuje", "TempGuiaTurbina", "TempEstator", "TempAceite", "Vibracion", "PresionOleo")]
    project.historian = dict(retention_days=365, files=[
        dict(id="electrico", name="Eléctrico y regulación · 2 s", interval_ms=2000, variables=electrical + ["Contador.Potencia", "SSCC.FrecuenciaRed"]),
        dict(id="termico", name="Temperaturas y vibraciones · 5 s", interval_ms=5000, variables=thermal),
        dict(id="embalse", name="Embalse y caudales · 10 s", interval_ms=10000, variables=[
            "SSCC.NivelEmbalse", "SSCC.CaudalEntrada", "SSCC.CaudalSalida", "SSCC.CaudalAliviadero",
            "SSCC.PosCompuerta1", "SSCC.PosCompuerta2", "SSCC.SaltoBruto", "SSCC.Lluvia", "Sistema.CaudalTurbinado"]),
        dict(id="estados", name="Estados y auxiliares · 5 s", interval_ms=5000, variables=[
            "G1.Paso", "G2.Paso", "G1.Acoplado", "G2.Acoplado", "SSCC.Interruptor52L", "SSCC.TensionBaterias",
            "SSCC.NivelPozo", "SSCC.PresionAire", "Sistema.PotenciaTotal"]),
    ])

    def axis(identifier, title, side="left", auto=True, low=0, high=100, visible=True):
        return dict(id=identifier, title=title, side=side, auto=auto, min=low, max=high, visible=visible)

    def curve(identifier, tag, axis_id, color, width=2, visible=True):
        return dict(id=identifier, tag=tag, axis=axis_id, color=color, width=width, visible=visible)

    project.trends = {
        "produccion": dict(title="Producción y nivel", window_seconds=1800,
                           axes=[axis("mw", "Potencia (MW)", auto=False, low=0, high=22), axis("nivel", "Nivel (msnm)", "right")],
                           curves=[curve("g1", "G1.Potencia", "mw", "#2b6cb0", 2), curve("g2", "G2.Potencia", "mw", "#6b46c1", 2),
                                   curve("total", "Contador.Potencia", "mw", "#2e8b57", 3), curve("nivel", "SSCC.NivelEmbalse", "nivel", "#4f86b8", 2)]),
        "embalse": dict(title="Embalse: nivel y caudales", window_seconds=3600,
                        axes=[axis("nivel", "Nivel (msnm)"), axis("q", "Caudal (m³/s)", "right")],
                        curves=[curve("nivel", "SSCC.NivelEmbalse", "nivel", "#1f5f99", 3), curve("entrada", "SSCC.CaudalEntrada", "q", "#2c7a7b"),
                                curve("salida", "SSCC.CaudalSalida", "q", "#c05621"), curve("aliv", "SSCC.CaudalAliviadero", "q", "#e89a1c")]),
        "electrico": dict(title="Tensión y frecuencia de los generadores", window_seconds=900,
                          axes=[axis("kv", "Tensión (kV)", auto=False, low=0, high=7.5), axis("hz", "Frecuencia (Hz)", "right", auto=False, low=48, high=52)],
                          curves=[curve("v1", "G1.Tension", "kv", "#2b6cb0"), curve("v2", "G2.Tension", "kv", "#6b46c1"),
                                  curve("f1", "G1.Frecuencia", "hz", "#c05621"), curve("f2", "G2.Frecuencia", "hz", "#e89a1c"),
                                  curve("fred", "SSCC.FrecuenciaRed", "hz", "#4a5568", 1)]),
    }
    for unit, _, name in UNITS:
        project.trends[f"termico_{unit.lower()}"] = dict(
            title=f"{name}: temperaturas y vibración", window_seconds=900,
            axes=[axis("c", "Temperatura (°C)", auto=False, low=0, high=140), axis("v", "Vibración (mm/s)", "right", auto=False, low=0, high=10)],
            curves=[curve("gs", f"{unit}.TempGuiaSup", "c", "#2b6cb0"), curve("em", f"{unit}.TempEmpuje", "c", "#c53030", 3),
                    curve("gt", f"{unit}.TempGuiaTurbina", "c", "#2c7a7b"), curve("es", f"{unit}.TempEstator", "c", "#d69e2e"),
                    curve("ac", f"{unit}.TempAceite", "c", "#718096", 1), curve("vi", f"{unit}.Vibracion", "v", "#6b46c1", 2)])

    project.scripts = {
        "inicio": '''"""Arranque del Runtime: marca la sesión."""
from datetime import datetime

ctx.write("Sistema.Inicio", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
print("SCADA CH Valdearenas iniciado")
''',
        "ciclo_1s": '''"""Cada segundo: reloj, estado de comunicaciones y totales de planta."""
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
''',
        "control_planta": '''"""Cada 2 s: control conjunto de potencia y regulación de nivel del embalse."""
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
''',
        "apertura": '''"""Al abrir una pantalla: la muestra en el menú."""
ctx.write("Sistema.Pantalla", ctx.screen)
''',
    }
    project.automation = dict(startup=["inicio"], timeout_seconds=5, tasks=[
        dict(id="ciclo_1s", script="ciclo_1s", interval_ms=1000, enabled=True),
        dict(id="control_planta", script="control_planta", interval_ms=2000, enabled=True)])


# ---------------------------------------------------------------------------
# SVG assets
# ---------------------------------------------------------------------------
DAM_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 330" width="150" height="330">
<defs><pattern id="h" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
<line x1="0" y1="0" x2="0" y2="8" stroke="#9ea6ad" stroke-width="1.5"/></pattern></defs>
<path d="M40 10 H70 L140 325 H20 Z" fill="#c8cdd1" stroke="#4b555e" stroke-width="3"/>
<path d="M40 10 H70 L140 325 H20 Z" fill="url(#h)" opacity="0.6"/>
<rect x="34" y="4" width="42" height="10" fill="#8f99a2" stroke="#4b555e" stroke-width="2"/>
<path d="M70 28 Q120 60 135 150" fill="none" stroke="#4b555e" stroke-width="3"/>
<rect x="22" y="250" width="22" height="26" fill="#6c7882" stroke="#4b555e" stroke-width="2"/>
</svg>"""


def unit_svg(state, tall=False):
    body, accent, water = {"parado": ("#d5dade", "#8f99a3", "#a9c3da"), "marcha": ("#d7ece0", "#2e8b57", "#4f86b8"),
                           "disparo": ("#f6d6d6", "#d32f2f", "#a9c3da")}[state]
    rotor = '<animateTransform attributeName="transform" type="rotate" from="0 90 120" to="360 90 120" dur="1s" repeatCount="indefinite"/>' if state == "marcha" else ""
    height = 290 if tall else 200
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 {height}" width="180" height="{height}">
<rect x="20" y="10" width="140" height="70" rx="8" fill="{body}" stroke="#2c3a45" stroke-width="3"/>
<rect x="34" y="20" width="112" height="50" rx="4" fill="none" stroke="{accent}" stroke-width="3"/>
<text x="90" y="52" text-anchor="middle" font-family="Arial" font-weight="bold" font-size="22" fill="#2c3a45">G</text>
<rect x="84" y="80" width="12" height="40" fill="#6c7882"/>
<ellipse cx="90" cy="135" rx="78" ry="26" fill="{water}" stroke="#2c3a45" stroke-width="3"/>
<g>{rotor}<path d="M90 120 L112 142 M90 120 L68 142 M90 120 L90 152" stroke="{accent}" stroke-width="5" stroke-linecap="round"/></g>
<path d="M70 158 L60 {height - 10} H120 L110 158 Z" fill="{water}" stroke="#2c3a45" stroke-width="3"/>
</svg>"""


def write_assets(root):
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    # newline="\n": the repository stores text as LF (.gitattributes), also on Windows.
    (assets / "presa.svg").write_text(DAM_SVG, encoding="utf-8", newline="\n")
    for state in ("parado", "marcha", "disparo"):
        (assets / f"grupo_{state}.svg").write_text(unit_svg(state), encoding="utf-8", newline="\n")
        (assets / f"grupo_{state}_alto.svg").write_text(unit_svg(state, tall=True), encoding="utf-8", newline="\n")


# Studio tree: folders by function (runtime ignores them).
FOLDERS = [("Estructura", ("00_", "01_", "02_", "05_")), ("Proceso", ("10_", "20_", "30_", "31_", "40_", "50_", "60_")),
           ("Tendencias", ("7",)), ("Alarmas", ("8",)), ("Emergentes", ("95_", "96_")), ("Utilidades", ("90_", "99_"))]


def organise(project):
    for key, document in project.screens.items():
        document["folder"] = next(folder for folder, prefixes in FOLDERS if key.startswith(prefixes))
    # A trend shown on two screens needs a configuration per control.
    own_viewers(project)


# ---------------------------------------------------------------------------
def build_project(root, force=False):
    root = Path(root).resolve()
    readme = None
    if is_project(root):
        if not force:
            raise ValueError("El proyecto ya existe; usa --force para regenerarlo (se pierden sus cambios)")
        # The README is hand-written documentation, not generated: keep it.
        readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").exists() else None
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    # Only the main window is placed: extra windows are opened by the operator, so the
    # example also works on a single-monitor laptop. See README for a 3-monitor layout.
    project = Project(root, dict(schema_version=1, name="CH Valdearenas", startup_screen="00_layout",
                                 display=dict(main=dict(mode="maximized"))),
                      {}, [], [], {}, {}, manifest_file="valdearenas.abscada")
    project.types, project.variables = build_variables()
    project.connections = build_connections()
    project.faceplates = build_faceplates()
    write_assets(root)
    build_layout(project)
    build_overview(project)
    build_reservoir(project)
    for index, (unit, _, name) in enumerate(UNITS):
        build_unit(project, index, unit, name)
    build_single_line(project)
    build_auxiliaries(project)
    build_control(project)
    build_trends(project)
    build_alarm_screens(project)
    build_instructor(project)
    build_help(project)
    for key, data in project.screens.items():
        if key not in ("00_layout", "01_cabecera", "02_menu", "05_ventana_alarmas") and not data.get("width") < SCREEN_W:
            data["on_open"] = ["apertura"]
    build_operations(project)
    organise(project)
    bilingual(project)
    project.validate()
    project.save()
    return project


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="examples/hydro")
    parser.add_argument("--force", action="store_true", help="Regenerar aunque exista (borra la carpeta)")
    args = parser.parse_args()
    built = build_project(args.output, args.force)
    print(f"{built.root}: {len(built.screens)} pantallas, {len(built.tags())} variables, "
          f"{len(built.connections)} conexiones, {len(built.alarms['items'])} alarmas")
