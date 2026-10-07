"""Build examples/brewery: SCADA of a 10 hl craft brewery over encrypted OPC UA.

    .venv\\Scripts\\python tools/build_brewery.py [--output examples/brewery] [--force]

Bindings come from abscada.simulators.brewery_map, the same address space the
simulator publishes (abscada --simulador cerveceria).
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from abscada.project import Project  # noqa: E402
from abscada.project_files import is_project  # noqa: E402
from abscada.screen_tree import own_viewers  # noqa: E402
from abscada.security import UserStore, default_security, users_path  # noqa: E402
from abscada.simulators.brewery_map import (BREWHOUSE_FIELDS, ENDPOINT, FERMENTER_FIELDS, FERMENTERS, PHASES,  # noqa: E402
                                            PROMPTS, RECIPE_COUNT, RECIPE_EDITOR_FIELDS, RECIPE_PARAMETERS,
                                            SERVICES_FIELDS, STEPS, node)
from build_hydro import SCREEN_W, Doc, condition, screen  # noqa: E402

PALETTE = {
    "Fondo": "#dfe1e2", "Panel": "#eeefef", "Borde": "#b8bdc1", "Texto": "#24292e",
    "TextoSuave": "#5f676e", "Valor": "#f9f9f9", "Linea": "#6f777e", "Agua": "#4f86b8",
    "Marcha": "#2e8b57", "Paro": "#9ba2a8", "Disparo": "#d32f2f", "Aviso": "#e89a1c",
    "Mosto": "#c2872b", "Cerveza": "#d8a23e", "Glicol": "#3c8fa6", "Vapor": "#9a6fb0", "Muerto": "#b3b9be",
    "Cabecera": "#2b2620", "Menu": "#38312a", "Mando": "#2b6cb0", "Apagado": "#4a4038",
}
PLC = "PLC_Cerveceria"
RECIPES_PERMISSION = "recipes"
# Demonstration accounts, documented in the README. A real plant creates its own.
DEMO_ACCOUNTS = [("admin", "Administrador de la planta", "administrador", "Tolva-Admin-2026"),
                 ("maestro", "Maestro cervecero", "maestro", "Tolva-Maestro-2026"),
                 ("operador", "Operador de cocción", "operador", "Tolva-Operador-2026"),
                 ("mes", "Cliente MES", "mes", "Tolva-MES-cliente")]


def ranges(field):
    return next((low, high) for name, _, _, _, low, high in RECIPE_PARAMETERS if name == field)


# ---------------------------------------------------------------------------
# Project model
# ---------------------------------------------------------------------------
def build_variables():
    types = {
        "Cocina": {name: kind for name, kind, _ in BREWHOUSE_FIELDS},
        "Fermentador": {name: kind for name, kind, _ in FERMENTER_FIELDS},
        "Servicios": {name: kind for name, kind, _ in SERVICES_FIELDS},
        "EditorRecetas": {name: kind for name, kind, _ in RECIPE_EDITOR_FIELDS},
        "Sistema": {"Fecha": "string", "Hora": "string", "Inicio": "string", "Pantalla": "string",
                    "ComPLC": "bool", "UltimoEvento": "string", "LotesCocinados": "int"},
    }
    defaults = {"bool": False, "int": 0, "float": 0.0, "string": ""}

    def plc_variable(name, kind, fields):
        bindings = {f"{name}.{field}": dict(connection=PLC, address=dict(node=node(name, field)))
                    for field, _, _ in fields}
        overrides = {field: {"writable": False} for field, _, writable in fields if not writable}
        return dict(name=name, type=kind, writable=True, overrides=overrides, bindings=bindings,
                    initial={field: defaults[t] for field, t, _ in fields})

    variables = [plc_variable("Cocina", "Cocina", BREWHOUSE_FIELDS)]
    variables += [plc_variable(fv, "Fermentador", FERMENTER_FIELDS) for fv in FERMENTERS]
    variables.append(plc_variable("Servicios", "Servicios", SERVICES_FIELDS))
    variables.append(plc_variable("Recetas", "EditorRecetas", RECIPE_EDITOR_FIELDS))
    variables.append(dict(name="Sistema", type="Sistema", writable=True, initial=dict(
        Fecha="", Hora="", Inicio="", Pantalla="", ComPLC=False, UltimoEvento="", LotesCocinados=0)))
    return types, variables


def build_connections():
    return [dict(id=PLC, protocol="opcua", endpoint=ENDPOINT, security="Basic256Sha256_SignAndEncrypt",
                 username="", timeout_ms=4000, poll_ms=1000)]


def build_security():
    roles = [
        dict(id="observador", name="Observador", permissions=[]),
        dict(id="operador", name="Operador de cocción", permissions=["operate", "acknowledge"]),
        dict(id="maestro", name="Maestro cervecero", permissions=["operate", "acknowledge", RECIPES_PERMISSION]),
        dict(id="administrador", name="Administrador", permissions=["operate", "acknowledge", RECIPES_PERMISSION,
                                                                   "manage_users", "opcua"]),
        dict(id="mes", name="Cliente MES (OPC UA)", permissions=["opcua"]),
    ]
    return dict(default_security(), enabled=True, session_timeout_minutes=30, roles=roles)


def build_accounts(project):
    """Create the demo accounts once; regenerating keeps users.json (salted hashes change every time)."""
    store = UserStore(users_path(project.root))
    for name, full_name, role, password in DEMO_ACCOUNTS:
        if store.find(name) is None:
            store.create(name, password, [role], project.security, full_name=full_name, must_change=False)


# ---------------------------------------------------------------------------
# Drawing helpers specific to the brewery
# ---------------------------------------------------------------------------
def phase_list(doc, identifier, tag, x, y, w, h, size=12):
    return doc.add("text_list", identifier, x, y, w, h, tag=tag, font_size=size, bold=True, text_color="#ffffff",
                   color="@Paro", border_color="@Paro", default_text="SIN COMUNICACIÓN",
                   texts=[dict(value=str(i), text=t.upper()) for i, t in enumerate(PHASES)],
                   dynamics=dict(states=[
                       dict(when=condition(tag, "eq", 6), style=dict(color="@Mando", border_color="@Mando")),
                       dict(when=condition(tag, "eq", 1), style=dict(color="@Aviso", border_color="@Aviso")),
                       dict(when=condition(tag, "gt", 1), style=dict(color="@Marcha", border_color="@Marcha"))],
                       bad=dict(color="@Aviso", border_color="@Aviso")))


def step_list(doc, identifier, tag, x, y, w, h, size=15):
    return doc.add("text_list", identifier, x, y, w, h, tag=tag, font_size=size, bold=True, text_color="#ffffff",
                   color="@Paro", border_color="@Paro", default_text="SIN COMUNICACIÓN",
                   texts=[dict(value=str(i), text=t.upper()) for i, t in enumerate(STEPS)],
                   dynamics=dict(states=[
                       dict(when=condition("Cocina.Retenido", "eq", True), style=dict(color="@Aviso", border_color="@Aviso")),
                       dict(when=condition(tag, "gt", 0), style=dict(color="@Marcha", border_color="@Marcha"))],
                       bad=dict(color="@Aviso", border_color="@Aviso")))


def vessel(doc, key, x, y, w, h, level, capacity, caption, color="@Mosto", temperature=None):
    """Tank outline with a level bar, its name above and level / temperature below."""
    doc.label(key + "_t", caption, x - 20, y - 24, w + 40, 20, size=12, bold=True, color="@Texto", align="center")
    doc.add("rectangle", key + "_marco", x, y, w, h, color="#ffffff", stroke_color="@Linea", stroke_width=2)
    doc.bar(key + "_nivel", level, x + 3, y + 3, w - 6, h - 6, 0, capacity, color=color)
    doc.value(key + "_v", level, x, y + h + 4, w, 24, "hl", 1, size=12, align="center")
    if temperature:
        doc.value(key + "_temp", temperature, x, y + h + 30, w, 26, "°C", 1, size=14, align="center")


def pipe(doc, identifier, points, *active, color="@Mosto", width=7, arrows="end"):
    """Process line: grey at rest, coloured while any of the (tag, op, value) conditions holds."""
    states = [dict(when=condition(tag, op, value), style=dict(stroke_color=color)) for tag, op, value in active]
    return doc.path("polyline", identifier, points, stroke_color="@Muerto", stroke_width=width, arrows=arrows,
                    dynamics=dict(states=states) if states else {})


def step(n):
    return ("Cocina.Paso", "eq", n)


# ---------------------------------------------------------------------------
# Faceplates
# ---------------------------------------------------------------------------
FV_PARAMETERS = {"fase": "int", "temperatura": "float", "consigna": "float", "densidad": "float",
                 "objetivo": "float", "presion": "float", "nivel": "float", "dia": "float", "lote": "int",
                 "receta": "string", "alarma": "bool", "valvula": "float", "automatico": "bool",
                 "consigna_manual": "float", "vaciar": "bool", "atenuacion": "float", "original": "float"}


def fv_bindings(fv):
    fields = {"fase": "Fase", "temperatura": "Temperatura", "consigna": "ConsignaTemp", "densidad": "Densidad",
              "objetivo": "DensidadObjetivo", "presion": "Presion", "nivel": "Nivel", "dia": "Dia", "lote": "Lote",
              "receta": "NombreReceta", "alarma": "Alarma", "valvula": "ValvulaGlicol", "automatico": "Automatico",
              "consigna_manual": "ConsignaManual", "vaciar": "OrdenVaciar", "atenuacion": "Atenuacion",
              "original": "DensidadOriginal"}
    return {parameter: f"{fv}.{field}" for parameter, field in fields.items()}


def cylinder(doc, key, x, y, w, h, level_tag, capacity):
    """Cylindro-conical fermenter: shell, level and cone."""
    doc.add("rectangle", key + "_casco", x, y, w, h, color="#ffffff", stroke_color="@Linea", stroke_width=2)
    doc.bar(key + "_nivel", level_tag, x + 3, y + 3, w - 6, h - 6, 0, capacity, color="@Cerveza")
    doc.path("polyline", key + "_cono", [[x, y + h], [x + w / 2, y + h + w * 0.45], [x + w, y + h]],
             stroke_color="@Linea", stroke_width=2)


def build_faceplates():
    faceplates = {}
    tile = Doc(dict(title="Fermentador", width=318, height=236, background="@Panel", parameters=FV_PARAMETERS,
                    elements=[]))
    tile.add("text", "receta", 10, 8, 150, 28, text="", tag="$receta", font_size=15, bold=True, text_align="left",
             color="@Panel", border_color="@Panel", text_color="@Texto")
    tile.label("lote_t", "Lote", 160, 12, 40, 20, size=11)
    tile.value("lote", "$lote", 196, 9, 52, 24, "", 0, size=12, align="center")
    tile.button("detalle", "Mando…", 254, 8, 56, 26, action="faceplate_popup", template="fermentador_mando",
                bindings={name: "$" + name for name in FV_PARAMETERS}, color="@Mando", border_color="@Mando",
                text_color="#ffffff", font_size=11)
    phase_list(tile, "fase", "$fase", 10, 42, 298, 28)
    cylinder(tile, "fv", 14, 80, 62, 110, "$nivel", 12)
    tile.add("rectangle", "alarma", 14, 214, 62, 16, color="@Paro", stroke_color="@Paro", stroke_width=1,
             dynamics=dict(states=[dict(when=condition("$alarma", "eq", True), style=dict(color="@Disparo", stroke_color="@Disparo"))],
                           bad=dict(color="@Aviso")))
    rows = [("Temperatura", "$temperatura", "°C", 1), ("Consigna", "$consigna", "°C", 1),
            ("Densidad", "$densidad", "°P", 2), ("Presión", "$presion", "bar", 2), ("Día", "$dia", "d", 1)]
    for i, (caption, tag, unit, decimals) in enumerate(rows):
        tile.field(f"v{i}", caption, tag, 92, 80 + i * 30, unit, 216, 104, decimals)
    faceplates["fermentador"] = tile.data

    pop = Doc(dict(title="Mando del fermentador", width=520, height=470, background="@Panel",
                   parameters=FV_PARAMETERS, elements=[]))
    phase_list(pop, "fase", "$fase", 12, 12, 496, 34, 15)
    pop.add("text", "receta", 12, 56, 300, 28, text="", tag="$receta", font_size=16, bold=True, text_align="left",
            color="@Panel", border_color="@Panel", text_color="@Texto")
    pop.label("lote_t", "Lote", 330, 60, 60, 22, size=12)
    pop.value("lote", "$lote", 388, 56, 120, 28, "", 0, align="center")
    rows = [("Temperatura", "$temperatura", "°C", 2), ("Consigna activa", "$consigna", "°C", 1),
            ("Densidad actual", "$densidad", "°P", 2), ("Densidad original", "$original", "°P", 1),
            ("Densidad objetivo", "$objetivo", "°P", 1), ("Atenuación aparente", "$atenuacion", "%", 0),
            ("Presión de CO₂", "$presion", "bar", 2), ("Válvula de glicol", "$valvula", "%", 0),
            ("Día de proceso", "$dia", "d", 1)]
    for i, (caption, tag, unit, decimals) in enumerate(rows):
        pop.field(f"v{i}", caption, tag, 12, 96 + i * 30, unit, 300, 110, decimals)
    pop.label("modo_t", "REGULACIÓN DE TEMPERATURA", 330, 96, 180, 18, size=10, bold=True)
    pop.state_text("modo", "$automatico", 330, 118, 178, 30, "SEGÚN RECETA", "MANUAL", "@Linea", "@Aviso")
    pop.add("button", "modo_b", 330, 154, 178, 30, text="Receta / manual", tag="$automatico", action="toggle",
            font_size=12, bold=True, color="#ffffff", border_color="@Mando", text_color="@Mando")
    pop.label("sp_t", "Consigna manual", 330, 194, 178, 20, size=12, color="@Texto")
    pop.add("input", "sp", 330, 216, 178, 30, text="", tag="$consigna_manual", unit="°C", decimals=1, font_size=15,
            text_align="right", color="#ffffff", border_color="@Mando", text_color="@Mando", bold=True,
            dynamics=dict(enabled=condition("$automatico", "eq", False),
                          disabled=dict(color="#e3e6e9", text_color="#8a949d", border_color="@Borde"),
                          disabled_reason="En modo receta la consigna la marca la fase"))
    pop.label("valv_t", "Válvula de glicol", 330, 258, 178, 20, size=12, color="@Texto")
    pop.bar("valv", "$valvula", 330, 280, 178, 22, 0, 100, color="@Glicol")
    pop.command("vaciar", "TRASEGAR A ENVASADO", "$vaciar", 330, 330, 178, 40, "@Mando",
                enabled=condition("$fase", "eq", 6), reason="La cerveza aún no está lista para envasar")
    pop.label("nota", "Las fases avanzan solas según la receta: fermentación → diacetilo → cold crash → guarda.",
              12, 376, 300, 40, size=11)
    pop.button("cerrar", "Cerrar", 388, 420, 120, 38, action="close_popup")
    faceplates["fermentador_mando"] = pop.data
    return faceplates


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------
NAV = [("10_general", "Vista general"), ("20_cocina", "Sala de cocción"), ("30_bodega", "Bodega"),
       ("40_recetas", "Recetas"), ("50_servicios", "Servicios"), ("70_tend_coccion", "Tendencias"),
       ("80_alarmas", "Alarmas"), ("90_instructor", "Simulación (instructor)")]


def build_layout(project):
    project.screens["00_layout"] = dict(title="La Tolva · SCADA", width=1600, height=900, background="@Fondo", elements=[
        dict(id="cabecera", kind="screen_container", x=0, y=0, w=1600, h=70, screen="01_cabecera"),
        dict(id="menu", kind="screen_container", x=0, y=70, w=200, h=830, screen="02_menu"),
        dict(id="contenido", kind="screen_container", x=200, y=70, w=1400, h=830, screen="10_general")])

    h = screen(project, "01_cabecera", "Cabecera", None, 1600, 70, "@Cabecera")
    h.label("marca", "LA TOLVA", 18, 8, 210, 28, size=20, bold=True, color="#ffffff")
    h.label("marca2", "Microcervecería · cocción 10 hl", 18, 38, 220, 20, size=11, color="#c9b9a6")
    h.label("paso_t", "SALA DE COCCIÓN", 250, 6, 300, 18, size=10, bold=True, color="#c9b9a6")
    step_list(h, "paso", "Cocina.Paso", 250, 26, 300, 34, 13)
    for i, (caption, tag, unit, decimals, w) in enumerate([("LOTE", "Cocina.Lote", "", 0, 90),
                                                            ("RECETA", "Cocina.RecetaLote", "", 0, 150),
                                                            ("RESTANTE", "Cocina.TiempoRestante", "min", 0, 120),
                                                            ("GLICOL", "Servicios.TempGlicol", "°C", 1, 110)]):
        x = 570 + sum((90, 150, 120, 110)[:i]) + i * 10
        h.label(f"k{i}_t", caption, x, 6, w, 18, size=10, bold=True, color="#c9b9a6")
        h.add("text", f"k{i}", x, 26, w, 34, text="", tag=tag, unit=unit, decimals=decimals, font_size=18, bold=True,
              text_align="left", color="@Cabecera", border_color="@Cabecera", text_color="#ffffff")
    h.label("areas_t", "ALARMAS DE ÁREA", 1080, 6, 300, 18, size=10, bold=True, color="#c9b9a6")
    areas = [("COC.", "Cocina.AlarmaCocina")] + [(fv, f"{fv}.Alarma") for fv in FERMENTERS] + \
            [("SERV.", "Servicios.AlarmaServicios"), ("COM", "Sistema.ComPLC")]
    for i, (caption, tag) in enumerate(areas):
        bad_when = condition(tag, "eq", False) if caption == "COM" else condition(tag, "eq", True)
        h.add("text_list", f"area{i}", 1080 + i * 52, 28, 48, 30, tag=tag, font_size=11, bold=True, text_color="#ffffff",
              color="@Apagado", border_color="@Apagado", texts=[dict(value="true", text=caption), dict(value="false", text=caption)],
              dynamics=dict(states=[dict(when=bad_when, style=dict(color="@Disparo", border_color="@Disparo"))],
                            bad=dict(color="@Aviso", border_color="@Aviso")))
        h.data["elements"][-1]["description"] = "En rojo si el área tiene alguna alarma (COM: sin comunicación con el PLC)"
    h.add("text", "fecha", 1400, 8, 185, 24, text="", tag="Sistema.Fecha", font_size=13, text_align="right",
          color="@Cabecera", border_color="@Cabecera", text_color="#c9b9a6")
    h.add("text", "hora", 1400, 30, 185, 32, text="", tag="Sistema.Hora", font_size=21, bold=True, text_align="right",
          color="@Cabecera", border_color="@Cabecera", text_color="#ffffff")

    m = screen(project, "02_menu", "Menú", None, 200, 830, "@Menu")
    for i, (key, caption) in enumerate(NAV):
        special = key == "90_instructor"
        m.button("nav_" + key, caption, 10, 14 + i * 48, 180, 40, action="screen", screen=key, target_container="contenido",
                 color="#6b4b16" if special else "#4a4037", border_color="#8a6420" if special else "#5d5146",
                 text_color="#ffffff", text_align="left")
    m.label("com_t", "COMUNICACIONES", 14, 420, 172, 18, size=10, bold=True, color="#c9b9a6")
    m.lamp("com", "Sistema.ComPLC", 14, 446, 18, "@Marcha", "@Disparo")
    m.label("com_l", "PLC · OPC UA cifrado", 40, 444, 150, 22, size=12, color="#e6ddd2")
    m.label("evento_t", "ÚLTIMO EVENTO", 14, 486, 172, 18, size=10, bold=True, color="#c9b9a6")
    m.add("text", "evento", 10, 506, 180, 70, text="", tag="Sistema.UltimoEvento", font_size=11, text_align="left",
          color="#4a4037", border_color="#5d5146", text_color="#ffffff")
    m.label("sesion_t", "SESIÓN", 14, 596, 172, 18, size=10, bold=True, color="#c9b9a6")
    m.label("sesion", "Inicia sesión desde la barra de estado inferior. Sin sesión, solo lectura.",
            14, 616, 176, 56, size=11, color="#e6ddd2")
    m.label("pant_t", "PANTALLA", 14, 742, 172, 18, size=10, bold=True, color="#c9b9a6")
    m.add("text", "pantalla", 10, 762, 180, 26, text="", tag="Sistema.Pantalla", font_size=11, text_align="left",
          color="@Menu", border_color="@Menu", text_color="#e6ddd2")
    m.button("ayuda", "Ayuda", 10, 792, 180, 30, action="popup", screen="99_ayuda", color="#4a4037",
             border_color="#5d5146", text_color="#ffffff")


def draw_brewhouse(d, x0, y0, compact=False):
    """Hot liquor → mash tun → lauter tun → kettle → cooler → cellar."""
    s = 0.8 if compact else 1.0
    hh = int(200 * s)
    vessel(d, "hlt", x0 + 20, y0, 80, hh, "Servicios.NivelHLT", 30, "Agua caliente", "@Agua", "Servicios.TempHLT")
    vessel(d, "mt", x0 + 190, y0, 110, hh, "Cocina.NivelMT", 12, "Macerador", "@Mosto", "Cocina.TempMT")
    vessel(d, "lt", x0 + 380, y0, 110, hh, "Cocina.NivelLT", 14, "Cuba filtro", "@Mosto")
    vessel(d, "bk", x0 + 570, y0, 110, hh, "Cocina.NivelBK", 14, "Hervidor / whirlpool", "@Mosto", "Cocina.TempBK")
    top, bottom = y0 + 16, y0 + hh - 14
    pipe(d, "agua_mt", [[x0 + 100, top], [x0 + 190, top]], step(1), color="@Agua")
    pipe(d, "agua_lt", [[x0 + 100, top - 10], [x0 + 140, top - 10], [x0 + 140, y0 - 34], [x0 + 435, y0 - 34], [x0 + 435, y0]],
         step(7), color="@Agua", width=5)
    pipe(d, "mt_lt", [[x0 + 300, bottom], [x0 + 380, bottom]], step(6))
    pipe(d, "lt_bk", [[x0 + 490, bottom], [x0 + 570, bottom]], step(7))
    # Wort cooler: a plate heat exchanger, chilled water on the other side.
    hx = x0 + (740 if compact else 770)
    d.add("rectangle", "hx", hx, y0 + 40, 54, int(120 * s), color="#ffffff", stroke_color="@Linea", stroke_width=2)
    for i in range(5):
        d.path("line", f"hx_p{i}", [[hx + 9 + i * 9, y0 + 46], [hx + 9 + i * 9, y0 + 34 + int(120 * s)]],
               stroke_color="@Glicol", stroke_width=2)
    d.label("hx_t", "Enfriador", hx - 20, y0 + 14, 94, 20, size=12, bold=True, color="@Texto", align="center")
    d.value("hx_v", "Cocina.TempMostoSalida", hx - 14, y0 + 50 + int(120 * s), 82, 26, "°C", 1, size=13, align="center",
            alarms=[])
    pipe(d, "bk_hx", [[x0 + 680, bottom], [hx - 10, bottom], [hx - 10, y0 + 100], [hx, y0 + 100]], step(11))
    pipe(d, "hx_fv", [[hx + 54, y0 + 100], [hx + (130 if compact else 100), y0 + 100]], step(11), color="@Cerveza")
    d.label("hx_fv_t", "→ bodega", hx + 64, y0 + 74, 80, 20, size=11)
    # Steam to the mash tun and the kettle
    pipe(d, "vapor_mt", [[x0 + 245, y0 + hh + 92], [x0 + 245, y0 + hh + 62]], ("Cocina.VaporMT", "gt", 1.0),
         color="@Vapor", width=4)
    pipe(d, "vapor_bk", [[x0 + 625, y0 + hh + 92], [x0 + 625, y0 + hh + 62]], ("Cocina.VaporBK", "gt", 1.0),
         color="@Vapor", width=4)
    d.label("vapor_t", "vapor", x0 + 252, y0 + hh + 72, 60, 18, size=10)
    d.label("vapor_t2", "vapor", x0 + 632, y0 + hh + 72, 60, 18, size=10)


def build_overview(project):
    d = screen(project, "10_general", "Vista general de la cervecería",
               "Sala de cocción de 10 hl · 3 fermentadores cilindrocónicos de 12 hl · PLC por OPC UA cifrado")
    d.panel("sinoptico", 10, 60, 1380, 320)
    draw_brewhouse(d, 30, 110, compact=True)
    d.panel("estado", 970, 70, 410, 300, "Cocción en curso")
    step_list(d, "paso", "Cocina.Paso", 986, 100, 378, 34, 14)
    rows = [("Lote", "Cocina.Lote", "", 0), ("Receta", "Cocina.RecetaLote", "", 0),
            ("Fermentador de destino", "Cocina.FVLote", "", 0), ("Tiempo restante del paso", "Cocina.TiempoRestante", "min", 0),
            ("Densidad del mosto", "Cocina.DensidadMosto", "°P", 1)]
    for i, (caption, tag, unit, decimals) in enumerate(rows):
        d.field(f"e{i}", caption, tag, 986, 144 + i * 30, unit, 378, 150, decimals)
    d.add("text_list", "aviso", 986, 300, 378, 30, tag="Cocina.Aviso", font_size=12, bold=True, text_color="@Texto",
          color="@Valor", border_color="@Borde", default_text="—",
          texts=[dict(value=str(i), text=t or "Sin avisos para el operador") for i, t in enumerate(PROMPTS)],
          dynamics=dict(states=[dict(when=condition("Cocina.EsperaOperador", "eq", True),
                                     style=dict(color="@Aviso", border_color="@Aviso", text_color="#ffffff"))]))
    d.button("ir_cocina", "Sala de cocción →", 1214, 336, 150, 28, action="screen", screen="20_cocina",
             target_container="contenido", color="@Mando", border_color="@Mando", text_color="#ffffff", font_size=12)

    for i, fv in enumerate(FERMENTERS):
        x = 10 + i * 326
        d.label(f"{fv}_t", f"{fv} · 12 hl", x, 388, 200, 20, size=13, bold=True, color="@Texto")
        d.add("faceplate", f"tile_{fv}", x, 410, 318, 236, template="fermentador", bindings=fv_bindings(fv))
    d.panel("servicios", 10, 654, 970, 176, "Servicios")
    rows = [("Agua caliente", "Servicios.TempHLT", "°C", 1, []),
            ("Presión de vapor", "Servicios.PresionVapor", "bar", 1, [("lt", 4.0, "@Disparo")]),
            ("Agua fría del enfriador", "Servicios.TempAguaFria", "°C", 1, []),
            ("Glicol", "Servicios.TempGlicol", "°C", 1, [("gt", 0.0, "@Disparo")]),
            ("Nivel de glicol", "Servicios.NivelGlicol", "%", 0, [("lt", 40.0, "@Aviso")]),
            ("Lotes cocinados en esta sesión", "Sistema.LotesCocinados", "", 0, [])]
    for i, (caption, tag, unit, decimals, alarms) in enumerate(rows):
        d.field(f"s{i}", caption, tag, 26 + (i // 3) * 480, 688 + (i % 3) * 44, unit, 440, 110, decimals, alarms)
    d.add("alarm_view", "alarmas", 988, 388, 402, 442, view="activas")


def build_brewhouse(project):
    d = screen(project, "20_cocina", "Sala de cocción",
               "Macerador, cuba filtro, hervidor-whirlpool y enfriador · secuencia por receta (1 min de receta = 1 s)")
    step_list(d, "estado", "Cocina.Paso", 930, 10, 460, 40, 16)
    d.panel("proceso", 10, 60, 900, 470)
    draw_brewhouse(d, 30, 130)
    d.lamp("agitador", "Cocina.AgitadorMT", 226, 418, 18)
    d.label("agitador_t", "Agitador", 248, 416, 90, 22, size=12, color="@Texto")
    d.lamp("rastrillos", "Cocina.Rastrillos", 416, 418, 18, "@Aviso")
    d.label("rastrillos_t", "Rastrillos", 438, 416, 90, 22, size=12, color="@Texto")
    d.field("lecho", "Lecho", "Cocina.PresionLecho", 410, 442, "mbar", 180, 100, 0, [("gt", 200.0, "@Disparo"), ("gt", 150.0, "@Aviso")])
    d.field("filtrado", "Filtrado", "Cocina.CaudalFiltrado", 410, 474, "hl/h", 180, 100, 1)
    d.label("espuma_t", "Espuma", 712, 130, 70, 20, size=11, align="center")
    d.bar("espuma", "Cocina.NivelEspuma", 728, 152, 36, 160, 0, 100, color="@Cerveza",
          alarms=[("ge", 80.0, "@Disparo"), ("ge", 60.0, "@Aviso")])
    d.value("espuma_v", "Cocina.NivelEspuma", 714, 316, 64, 24, "%", 0, size=12, align="center",
            alarms=[("ge", 80.0, "@Disparo")])
    d.lamp("ebullicion", "Cocina.Ebullicion", 606, 418, 18, "@Marcha")
    d.label("ebullicion_t", "Ebullición", 628, 416, 90, 22, size=12, color="@Texto")
    d.field("trasiego", "Trasiego", "Cocina.CaudalTrasiego", 760, 442, "hl/h", 144, 70, 0)
    d.field("vmt", "Vapor", "Cocina.VaporMT", 196, 442, "%", 180, 100, 0)
    d.field("vbk", "Vapor", "Cocina.VaporBK", 600, 474, "%", 150, 86, 0)
    d.lamp("mt_fuera", "Cocina.FueraTemperaturaMT", 196, 478, 18, "@Disparo")
    d.label("mt_fuera_t", "Fuera de escalón", 218, 476, 150, 22, size=12, color="@Texto")
    d.status("siembra", "Siembra caliente", "Cocina.SiembraCaliente", 760, 478, 150, "@Disparo", "@Paro")

    d.panel("secuencia", 920, 60, 470, 470, "Secuencia de cocción")
    for i in range(1, len(STEPS)):
        y = 90 + (i - 1) * 24
        d.add("rectangle", f"paso{i}", 936, y + 4, 13, 13, color="#ffffff", stroke_color="@Linea", stroke_width=1,
              dynamics=dict(states=[dict(when=condition("Cocina.Paso", "eq", i), style=dict(color="@Aviso", stroke_color="@Aviso")),
                                    dict(when=condition("Cocina.Paso", "eq", 0), style=dict(color="#ffffff")),
                                    dict(when=condition("Cocina.Paso", "gt", i), style=dict(color="@Marcha", stroke_color="@Marcha"))]))
        d.label(f"paso{i}_t", f"{i}. {STEPS[i]}", 958, y, 400, 20, size=12, color="@Texto")
    rows = [("Consigna del paso", "Cocina.ConsignaActual", "°C", 1), ("Tiempo en el paso", "Cocina.TiempoPaso", "min", 1),
            ("Tiempo restante", "Cocina.TiempoRestante", "min", 1)]
    for i, (caption, tag, unit, decimals) in enumerate(rows):
        d.field(f"t{i}", caption, tag, 936, 392 + i * 32, unit, 438, 130, decimals)
    d.state_text("retenido", "Cocina.Retenido", 936, 492, 438, 28, "SECUENCIA RETENIDA", "SECUENCIA EN AUTOMÁTICO",
                 "@Aviso", "@Linea", 12)

    d.panel("mando", 10, 540, 560, 290, "Preparar y mandar el lote")
    d.label("rec_t", "Receta", 26, 572, 120, 20, size=12, bold=True, color="@Texto")
    for i in range(1, RECIPE_COUNT + 1):
        y = 594 + (i - 1) * 32
        # The recipe name comes from the PLC: a text shows it and a transparent button on top selects it.
        d.add("text", f"rec{i}_n", 26, y, 220, 28, text="", tag=f"Recetas.Nombre{i}", font_size=12, bold=True,
              text_align="left", color="#ffffff", border_color="@Borde", text_color="@Texto",
              dynamics=dict(states=[dict(when=condition("Cocina.RecetaSeleccionada", "eq", i),
                                         style=dict(color="@Mando", border_color="@Mando", text_color="#ffffff"))]))
        d.add("button", f"rec{i}_b", 26, y, 220, 28, text="", tag="Cocina.RecetaSeleccionada", action="set", value=i,
              color="#00000000", border_color="#00000000", description=f"Elegir la receta {i} para el próximo lote")
    d.label("fv_t", "Fermentador de destino", 270, 572, 200, 20, size=12, bold=True, color="@Texto")
    for i, fv in enumerate(FERMENTERS, 1):
        y = 594 + (i - 1) * 32
        d.add("button", f"fv{i}", 270, y, 90, 28, text=fv, tag="Cocina.FVDestino", action="set", value=i,
              font_size=12, bold=True, color="#ffffff", border_color="@Mando", text_color="@Mando",
              dynamics=dict(states=[dict(when=condition("Cocina.FVDestino", "eq", i),
                                         style=dict(color="@Mando", text_color="#ffffff"))]))
        d.add("text_list", f"fv{i}_libre", 368, y, 186, 28, tag=f"{fv}.Fase", font_size=11, bold=True,
              text_color="@Texto", color="@Valor", border_color="@Borde", default_text="—",
              texts=[dict(value="0", text="Libre")] + [dict(value=str(p), text=PHASES[p]) for p in range(1, len(PHASES))])
    d.command("iniciar", "INICIAR LOTE", "Cocina.OrdenIniciar", 26, 728, 170, 42, "@Marcha",
              enabled=condition("Cocina.ListoIniciar", "eq", True),
              reason="Cocina ocupada, fermentador de destino lleno o servicios no preparados")
    d.command("retener", "RETENER", "Cocina.OrdenRetener", 206, 728, 110, 42, "@Aviso",
              enabled=condition("Cocina.Paso", "gt", 0), reason="No hay cocción en marcha")
    d.command("reanudar", "REANUDAR", "Cocina.OrdenReanudar", 326, 728, 110, 42, "@Mando",
              enabled=condition("Cocina.Retenido", "eq", True), reason="La secuencia no está retenida")
    d.button("abortar", "ABORTAR", 446, 728, 110, 42, action="popup", screen="95_abortar", modal=True,
             color="@Disparo", border_color="#8e1c1c", text_color="#ffffff", font_size=13)
    d.status("listo", "Listo para iniciar", "Cocina.ListoIniciar", 26, 782, 300)
    d.label("listo_n", "Requiere fermentador libre, vapor > 4 bar y agua caliente ≥ 70 °C.", 26, 804, 530, 20, size=11)

    d.panel("aviso", 580, 540, 400, 150, "Aviso al operador")
    d.add("text_list", "aviso_t", 596, 572, 368, 50, tag="Cocina.Aviso", font_size=14, bold=True, text_color="@Texto",
          color="@Valor", border_color="@Borde", default_text="—",
          texts=[dict(value=str(i), text=t or "Sin avisos") for i, t in enumerate(PROMPTS)],
          dynamics=dict(states=[dict(when=condition("Cocina.EsperaOperador", "eq", True),
                                     style=dict(color="@Aviso", border_color="@Aviso", text_color="#ffffff"))]))
    d.command("confirmar", "CONFIRMAR", "Cocina.OrdenConfirmar", 596, 632, 368, 44, "@Marcha",
              enabled=condition("Cocina.EsperaOperador", "eq", True), reason="No hay nada que confirmar")
    d.panel("lote", 580, 700, 400, 130, "Lote en la cocina")
    rows = [("Lote", "Cocina.Lote", "", 0), ("Receta", "Cocina.RecetaLote", "", 0), ("Densidad del mosto", "Cocina.DensidadMosto", "°P", 2)]
    for i, (caption, tag, unit, decimals) in enumerate(rows):
        d.field(f"l{i}", caption, tag, 596, 730 + i * 32, unit, 368, 150, decimals)
    d.add("trend", "tendencia", 990, 540, 400, 290, view="coccion")

    c = screen(project, "95_abortar", "Confirmar aborto de la cocción", None, 520, 260, "#fbeaea")
    c.label("icono", "⚠", 20, 20, 60, 60, size=40, bold=True, color="@Disparo")
    c.label("texto", "¿Abortar el lote en curso?", 90, 22, 410, 40, size=17, bold=True, color="@Texto")
    c.label("detalle", "El mosto de la sala de cocción, y el del fermentador si se estaba trasegando, va a desagüe. "
            "No se puede deshacer.", 90, 66, 410, 80, size=13, color="@Texto")
    c.command("confirmar", "ABORTAR LOTE", "Cocina.OrdenAbortar", 90, 170, 220, 46, "@Disparo")
    c.button("cancelar", "Cerrar", 330, 170, 170, 46, action="close_popup")


def build_cellar(project):
    d = screen(project, "30_bodega", "Bodega · fermentación y guarda",
               "Las fases siguen la receta copiada al iniciar el lote (1 día de fermentación = 1 min) · «Mando…» abre cada fermentador")
    for i, fv in enumerate(FERMENTERS):
        x = 10 + i * 465
        d.label(f"{fv}_t", f"{fv} · cilindrocónico 12 hl", x, 64, 300, 20, size=13, bold=True, color="@Texto")
        d.add("faceplate", f"tile_{fv}", x, 86, 318, 236, template="fermentador", bindings=fv_bindings(fv))
        d.panel(f"{fv}_extra", x + 326, 86, 130, 236)
        d.label(f"{fv}_v_t", "GLICOL", x + 336, 92, 110, 18, size=10, bold=True)
        d.bar(f"{fv}_v", f"{fv}.ValvulaGlicol", x + 352, 114, 36, 120, 0, 100, color="@Glicol")
        d.value(f"{fv}_v_v", f"{fv}.ValvulaGlicol", x + 336, 240, 110, 24, "%", 0, size=12, align="center")
        d.status(f"{fv}_parada", "Parada", f"{fv}.FermentacionParada", x + 336, 270, 120, "@Disparo", "@Paro")
        d.add("text_list", f"{fv}_modo", x + 336, 296, 110, 22, tag=f"{fv}.Automatico", font_size=10, bold=True,
              text_color="@Texto", texts=[dict(value="true", text="RECETA"), dict(value="false", text="MANUAL")],
              default_text="—", dynamics=dict(states=[dict(when=condition(f"{fv}.Automatico", "eq", False),
                                                           style=dict(text_color="@Aviso"))]))
        d.add("trend", f"{fv}_tend", x, 330, 456, 500, view=f"fermentacion_{fv.lower()}")


def build_recipes(project):
    d = screen(project, "40_recetas", "Recetas",
               "Gestor de recetas del PLC: cargar, modificar y guardar · editar exige el permiso «Recetas y parámetros de proceso»")
    d.panel("lista", 10, 60, 340, 400, "Recetas guardadas en el PLC")
    for i in range(1, RECIPE_COUNT + 1):
        y = 96 + (i - 1) * 44
        d.add("text", f"r{i}", 26, y, 308, 36, text="", tag=f"Recetas.Nombre{i}", font_size=15, bold=True,
              text_align="left", color="#ffffff", border_color="@Borde", text_color="@Texto",
              dynamics=dict(states=[dict(when=condition("Recetas.Numero", "eq", i),
                                         style=dict(color="@Mando", border_color="@Mando", text_color="#ffffff"))]))
        d.add("button", f"r{i}_b", 26, y, 308, 36, text="", tag="Recetas.Numero", action="set", value=i,
              color="#00000000", border_color="#00000000", description=f"Cargar la receta {i} en el editor")
    d.label("lista_n", "Pulsa una receta para cargarla en el editor. Los cambios sin guardar se descartan al cambiar de receta.",
            26, 276, 308, 56, size=12)
    d.status("modificada", "Cambios sin guardar", "Recetas.Modificada", 26, 340, 300, "@Aviso", "@Paro")
    d.status("en_uso", "En uso por el lote en cocción", "Recetas.EnUso", 26, 368, 300, "@Mando", "@Paro")
    d.add("button", "guardar", 26, 404, 150, 40, text="GUARDAR", tag="Recetas.OrdenGuardar", action="set", value=True,
          permission=RECIPES_PERMISSION, font_size=13, bold=True, color="@Marcha", border_color="@Marcha", text_color="#ffffff",
          dynamics=dict(enabled=condition("Recetas.Modificada", "eq", True),
                        disabled=dict(color="#d7dce0", text_color="#8a949d", border_color="#c3c9ce"),
                        disabled_reason="No hay cambios que guardar"))
    d.add("button", "descartar", 184, 404, 150, 40, text="DESCARTAR", tag="Recetas.OrdenDescartar", action="set", value=True,
          permission=RECIPES_PERMISSION, font_size=13, bold=True, color="@Linea", border_color="@Linea", text_color="#ffffff",
          dynamics=dict(enabled=condition("Recetas.Modificada", "eq", True),
                        disabled=dict(color="#d7dce0", text_color="#8a949d", border_color="#c3c9ce"),
                        disabled_reason="No hay cambios que descartar"))
    d.panel("roles", 10, 470, 340, 360, "Quién puede hacer qué")
    lines = ["Observador: consulta todas las pantallas.",
             "Operador de cocción: elige receta y fermentador, manda la secuencia y reconoce alarmas.",
             "Maestro cervecero: además, modifica y guarda recetas.",
             "Administrador: todo, más usuarios y acceso por OPC UA.",
             "Cliente MES: solo lee por el servidor OPC UA del SCADA.",
             "Un lote en marcha usa la copia de la receta tomada al iniciar: guardar no lo altera."]
    for i, line in enumerate(lines):
        d.label(f"rol{i}", "• " + line, 26, 502 + i * 52, 316, 50, size=12, color="@Texto")

    d.panel("editor", 360, 60, 1030, 770, "Editor de receta")
    d.label("nombre_t", "Nombre", 380, 98, 120, 24, size=14, bold=True, color="@Texto")
    d.add("input", "nombre", 500, 94, 300, 32, text="", tag="Recetas.Nombre", font_size=15, bold=True, text_align="left",
          color="#ffffff", border_color="@Mando", text_color="@Mando", permission=RECIPES_PERMISSION)
    d.label("nombre_n", "Máximo 20 caracteres", 812, 100, 200, 22, size=11)
    groups = [("Maceración", ["VolumenAgua", "TempE1", "TiempoE1", "TempE2", "TiempoE2", "TempE3", "TiempoE3"]),
              ("Cocción", ["TiempoHervido", "LupuloAroma", "DensidadOriginal"]),
              ("Fermentación y guarda", ["DensidadFinal", "TempFermentacion", "DiasFermentacion", "TempDiacetilo",
                                         "DiasDiacetilo", "TempGuarda", "DiasGuarda"])]
    info = {name: (caption, unit) for name, _, caption, unit, _, _ in RECIPE_PARAMETERS}
    columns = [(380, groups[0:2]), (890, groups[2:3])]
    for x, column in columns:
        y = 146
        for title, fields in column:
            d.label(f"g_{title}", title.upper(), x, y, 300, 20, size=11, bold=True)
            y += 26
            for field in fields:
                caption, unit = info[field]
                low, high = ranges(field)
                d.label(f"p_{field}_t", caption, x, y + 4, 300, 22, size=13, color="@Texto")
                d.add("input", f"p_{field}", x + 300, y, 110, 30, text="", tag=f"Recetas.{field}", unit=unit, decimals=1,
                      font_size=14, text_align="right", color="#ffffff", border_color="@Mando", text_color="@Mando",
                      bold=True, permission=RECIPES_PERMISSION)
                d.label(f"p_{field}_r", f"{low:g} – {high:g}", x + 418, y + 6, 80, 20, size=11)
                y += 36
            y += 14
    d.label("editor_n", "Los valores fuera de rango se recortan al guardar: el PLC nunca almacena una receta imposible. "
            "El tiempo de receta está comprimido: 1 min de cocción = 1 s y 1 día de fermentación = 1 min.",
            890, 466, 480, 66, size=12)
    d.add("trend", "perfil", 890, 536, 480, 284, view="perfil_receta")


def build_services(project):
    d = screen(project, "50_servicios", "Servicios", "Agua caliente, vapor, glicol y agua fría del enfriador de mosto")
    d.panel("hlt", 10, 60, 340, 400, "Depósito de agua caliente (HLT)")
    vessel(d, "hlt", 40, 120, 100, 240, "Servicios.NivelHLT", 30, "30 hl", "@Agua", "Servicios.TempHLT")
    d.setpoint("hlt_sp", "Consigna", "Servicios.ConsignaHLT", 160, 130, "°C", 176, 90)
    d.label("hlt_n", "Se rellena con agua de red por debajo de 15 hl. Calienta con vapor.", 160, 176, 176, 80, size=11)

    d.panel("vapor", 360, 60, 340, 400, "Generador de vapor")
    d.add("gauge", "vapor_m", 400, 100, 220, 220, tag="Servicios.PresionVapor", min=0, max=8, unit="bar", decimals=1,
          text="Vapor", gauge_style="dial", warning=7, alarm=7.5,
          dynamics=dict(states=[dict(when=condition("Servicios.PresionVapor", "lt", 4.0), style=dict(color="@Disparo"))]))
    d.status("caldera", "Caldera en marcha", "Servicios.Caldera", 380, 340, 300)
    d.status("caldera_f", "Fallo de caldera", "Servicios.FalloCaldera", 380, 370, 300, "@Disparo", "@Paro")
    d.label("vapor_n", "Por debajo de 4 bar la cocina no puede iniciar lotes.", 380, 402, 300, 40, size=11)

    d.panel("glicol", 710, 60, 680, 400, "Glicol y agua fría")
    d.add("rectangle", "gl_marco", 740, 110, 90, 240, color="#ffffff", stroke_color="@Linea", stroke_width=2)
    d.bar("gl_nivel", "Servicios.NivelGlicol", 744, 114, 82, 232, 0, 100, color="@Glicol",
          alarms=[("lt", 20.0, "@Disparo"), ("lt", 40.0, "@Aviso")])
    d.label("gl_t", "Depósito", 730, 86, 110, 20, size=12, bold=True, color="@Texto", align="center")
    d.value("gl_v", "Servicios.NivelGlicol", 740, 356, 90, 26, "%", 0, align="center",
            alarms=[("lt", 20.0, "@Disparo"), ("lt", 40.0, "@Aviso")])
    rows = [("Temperatura de glicol", "Servicios.TempGlicol", "°C", 2, [("gt", 0.0, "@Disparo")]),
            ("Agua fría del enfriador", "Servicios.TempAguaFria", "°C", 1, [])]
    for i, (caption, tag, unit, decimals, alarms) in enumerate(rows):
        d.field(f"g{i}", caption, tag, 860, 110 + i * 36, unit, 500, 130, decimals, alarms)
    d.setpoint("gl_sp", "Consigna de glicol", "Servicios.ConsignaGlicol", 860, 182, "°C", 500, 130)
    d.status("enfriadora", "Enfriadora en marcha", "Servicios.Enfriadora", 860, 230, 300)
    d.status("enfriadora_f", "Fallo de enfriadora (o nivel de glicol < 20 %)", "Servicios.FalloEnfriadora", 860, 258, 500,
             "@Disparo", "@Paro")
    d.label("gl_n", "El glicol enfría las camisas de los fermentadores y el agua fría del enfriador de mosto. "
            "Si se calienta, los fermentadores pierden la consigna y el mosto llega caliente a bodega.",
            860, 296, 500, 80, size=12)
    d.add("trend", "tendencia", 10, 470, 1380, 360, view="servicios")


def build_trends(project):
    tabs = [("70_tend_coccion", "Cocción", "coccion")] + \
           [(f"7{i}_tend_{fv.lower()}", fv, f"fermentacion_{fv.lower()}") for i, fv in enumerate(FERMENTERS, 1)] + \
           [("74_tend_servicios", "Servicios", "servicios")]
    for key, caption, view in tabs:
        d = screen(project, key, f"Tendencias · {caption}", "Tiempo real e histórico · zoom, cursor y exportación CSV")
        for i, (other, other_caption, _) in enumerate(tabs):
            active = other == key
            d.button(f"tab{i}", other_caption, 930 + i * 92, 14, 88, 32, action="screen", screen=other,
                     target_container="contenido", color="@Mando" if active else "#ffffff",
                     border_color="@Mando", text_color="#ffffff" if active else "@Mando", font_size=12)
        d.add("trend", "tendencia", 10, 60, 1380, 770, view=view)


def build_alarm_screens(project):
    tabs = [("80_alarmas", "Activas", "activas"), ("81_alarmas_historico", "Histórico", "historico"),
            ("82_alarmas_eventos", "Eventos", "eventos")]
    for key, caption, view in tabs:
        d = screen(project, key, f"Alarmas · {caption}",
                   "Reconocer exige sesión con el permiso «Reconocer alarmas» · el registro guarda quién hizo cada cosa")
        for i, (other, other_caption, _) in enumerate(tabs):
            active = other == key
            d.button(f"tab{i}", other_caption, 1110 + i * 94, 14, 90, 32, action="screen", screen=other,
                     target_container="contenido", color="@Mando" if active else "#ffffff", border_color="@Mando",
                     text_color="#ffffff" if active else "@Mando", font_size=12)
        d.add("alarm_view", "visor", 10, 60, 1380, 770, view=view)


def build_instructor(project):
    d = screen(project, "90_instructor", "Panel del instructor · simulación",
               "Solo para formación: inyecta averías en el PLC simulado (abscada --simulador cerveceria)")
    d.add("rectangle", "banda", 10, 60, 1380, 40, color="#fff4dc", stroke_color="@Aviso", stroke_width=2)
    d.label("banda_t", "MODO FORMACIÓN · las órdenes de esta pantalla activan averías simuladas. Desactívalas para volver a la normalidad.",
            24, 68, 1350, 24, size=14, bold=True, color="#7a4b00")

    def fault(key, x, y, w, tag, caption, detail):
        d.state_text(key, tag, x, y, 100, 30, "ACTIVA", "NORMAL", "@Disparo", "@Paro", 12)
        d.add("button", key + "_b", x + 110, y, w - 110, 30, text=caption, tag=tag, action="toggle", font_size=13,
              bold=True, color="#ffffff", border_color="@Aviso", text_color="#7a4b00")
        d.label(key + "_d", detail, x + 110, y + 34, w - 110, 48, size=11)

    d.panel("cocina", 10, 110, 450, 300, "Sala de cocción")
    fault("espuma", 26, 146, 420, "Cocina.SimEspuma", "Espuma en el hervor",
          "La espuma sube en el hervido: aviso al 60 %, alarma al 80 % y el PLC baja el vapor.")
    fault("lecho", 26, 246, 420, "Cocina.SimLechoColmatado", "Lecho filtrante colmatado",
          "Sube la presión del lecho: los rastrillos no bastan, cae el caudal y salta la alarma a 200 mbar.")
    d.panel("servicios", 10, 420, 450, 410, "Servicios")
    fault("caldera", 26, 456, 420, "Servicios.SimFalloCaldera", "Fallo de caldera",
          "Cae la presión de vapor: los escalones y el hervido se detienen. No se pueden iniciar lotes.")
    fault("enfriadora", 26, 556, 420, "Servicios.SimFalloEnfriadora", "Fallo de la enfriadora de glicol",
          "El glicol se calienta: los fermentadores se desvían y el mosto llega caliente a bodega.")
    fault("fuga", 26, 656, 420, "Servicios.SimFugaGlicol", "Fuga de glicol",
          "Baja el nivel del depósito: alarma al 40 %, la enfriadora se protege al 20 %.")
    for i, fv in enumerate(FERMENTERS):
        x = 470 + i * 310
        d.panel(f"p{fv}", x, 110, 300, 400, fv)
        fault(f"{fv}_valv", x + 12, 146, 278, f"{fv}.SimValvulaAtascada", "Válvula de glicol atascada",
              "Se queda cerrada: la temperatura sube con la fermentación.")
        fault(f"{fv}_pres", x + 12, 266, 278, f"{fv}.SimSobrepresion", "Válvula de presión bloqueada",
              "El CO₂ no sale: alarma a 1,6 bar y válvula de seguridad a 2,5 bar.")
        fault(f"{fv}_parada", x + 12, 386, 278, f"{fv}.SimFermentacionParada", "Levadura inactiva",
              "La densidad deja de bajar: alarma de fermentación parada al cabo de un día.")
    d.panel("guia", 470, 520, 920, 310, "Ejercicio recomendado")
    steps = ["1. Inicia sesión como operador. En «Sala de cocción» elige la receta Tostada, el FV3 e INICIAR LOTE.",
             "2. Confirma la malta en el empaste y los lúpulos en el hervido cuando lo pida el aviso.",
             "3. Activa «Espuma en el hervor» durante el hervido: reconoce la alarma y mira cómo el PLC baja el vapor.",
             "4. Con el lote en el FV3, activa «Fallo de la enfriadora»: sigue en Bodega cómo se desvían las temperaturas.",
             "5. Inicia sesión como operador e intenta guardar una receta: no puedes. Hazlo como maestro cervecero.",
             "6. Cuando el FV2 esté «Listo para envasar», abre su «Mando…» y trasiégalo para dejarlo libre."]
    for i, line in enumerate(steps):
        d.label(f"g{i}", line, 486, 556 + i * 44, 890, 40, size=13, color="@Texto")


def build_help(project):
    d = screen(project, "99_ayuda", "Ayuda de operación", None, 760, 560, "#ffffff")
    d.label("t", "LA TOLVA · AYUDA RÁPIDA", 24, 18, 700, 30, size=18, bold=True, color="@Texto")
    lines = [
        "• Sin sesión todo es de solo lectura. Inicia sesión en la barra de estado inferior.",
        "• Sala de cocción: receta, fermentador de destino, INICIAR, RETENER / REANUDAR y ABORTAR.",
        "• Los avisos ámbar piden una acción manual (malta, lúpulo): hazla y pulsa CONFIRMAR.",
        "• Bodega: cada fermentador sigue la receta copiada al iniciar el lote; «Mando…» abre su ventana.",
        "• Recetas: cualquiera puede consultarlas; solo el maestro cervecero las modifica y guarda.",
        "• Alarmas: reconocer queda registrado con tu usuario. Filtros e histórico en CSV.",
        "• El PLC habla OPC UA cifrado: la primera vez hay que confiar en su certificado.",
        "• El propio SCADA publica sus variables por OPC UA en el puerto 4850 (rol Cliente MES).",
        "• Simulación: abscada --simulador cerveceria.",
    ]
    for i, line in enumerate(lines):
        d.label(f"l{i}", line, 24, 62 + i * 48, 712, 44, size=14, color="@Texto")
    d.button("cerrar", "Cerrar", 560, 500, 176, 40, action="close_popup")


# ---------------------------------------------------------------------------
# Operations: alarms, logging, trends, scripts
# ---------------------------------------------------------------------------
def build_operations(project):
    categories = [("cocina", "Sala de cocción", "#c2872b"), ("bodega", "Bodega", "#2b6cb0"),
                  ("servicios", "Servicios", "#3c8fa6"), ("sistema", "Sistema SCADA", "#4a5568")]
    items = []

    def alarm(identifier, tag, category, cond, threshold, message, priority, ack=True, hysteresis=0.0, on=1000, off=500):
        items.append(dict(id=identifier, tag=tag, category=category, condition=cond, threshold=threshold, message=message,
                          priority=priority, ack_required=ack, enabled=True, hysteresis=hysteresis,
                          on_delay_ms=on, off_delay_ms=off))

    alarm("mt_escalon", "Cocina.FueraTemperaturaMT", "cocina", "true", 0, "Macerador fuera de la temperatura del escalón", 700, on=3000)
    alarm("espuma_aviso", "Cocina.NivelEspuma", "cocina", "high", 60, "Espuma alta en el hervidor", 400, ack=False, hysteresis=5)
    alarm("espuma", "Cocina.NivelEspuma", "cocina", "high", 80, "Riesgo de desbordamiento del hervidor", 850, hysteresis=5)
    alarm("lecho", "Cocina.PresionLecho", "cocina", "high", 200, "Lecho filtrante colmatado", 700, hysteresis=20)
    alarm("siembra", "Cocina.SiembraCaliente", "cocina", "true", 0, "Mosto a bodega por encima de la temperatura de siembra", 750, on=3000)
    alarm("espera", "Cocina.EsperaOperador", "cocina", "true", 0, "La cocción espera una confirmación del operador", 300, ack=False)
    alarm("retenido", "Cocina.Retenido", "cocina", "true", 0, "Secuencia de cocción retenida", 250, ack=False)
    for fv in FERMENTERS:
        key = fv.lower()
        alarm(f"{key}_alta", f"{fv}.Desviacion", "bodega", "high", 1.5, f"{fv} · Temperatura por encima de la consigna", 700,
              hysteresis=0.3, on=5000)
        alarm(f"{key}_baja", f"{fv}.Desviacion", "bodega", "low", -1.5, f"{fv} · Temperatura por debajo de la consigna", 500,
              hysteresis=0.3, on=5000)
        alarm(f"{key}_presion", f"{fv}.Presion", "bodega", "high", 1.6, f"{fv} · Presión de CO₂ alta", 800, hysteresis=0.1)
        alarm(f"{key}_seguridad", f"{fv}.Presion", "bodega", "high", 2.2, f"{fv} · Presión muy alta: va a abrir la válvula de seguridad",
              1000, hysteresis=0.1, on=0)
        alarm(f"{key}_parada", f"{fv}.FermentacionParada", "bodega", "true", 0, f"{fv} · Fermentación parada: la densidad no baja", 600)
        alarm(f"{key}_listo", f"{fv}.Fase", "bodega", "high", 5.5, f"{fv} · Cerveza lista para envasar", 200, ack=False)
        alarm(f"{key}_manual", f"{fv}.Automatico", "bodega", "false", 0, f"{fv} · Temperatura en consigna manual", 200, ack=False)
    alarm("vapor", "Servicios.PresionVapor", "servicios", "low", 4.0, "Presión de vapor baja", 800, hysteresis=0.2)
    alarm("caldera", "Servicios.FalloCaldera", "servicios", "true", 0, "Fallo de caldera", 900, on=0)
    alarm("enfriadora", "Servicios.FalloEnfriadora", "servicios", "true", 0, "Fallo de la enfriadora de glicol", 900, on=0)
    alarm("glicol_caliente", "Servicios.TempGlicol", "servicios", "high", 0.0, "Glicol por encima de 0 °C", 700, hysteresis=0.5)
    alarm("glicol_nivel", "Servicios.NivelGlicol", "servicios", "low", 40, "Nivel bajo en el depósito de glicol", 800, hysteresis=2)
    alarm("hlt_nivel", "Servicios.NivelHLT", "servicios", "low", 10, "Nivel bajo de agua caliente", 400, hysteresis=1)
    alarm("com", "Sistema.ComPLC", "sistema", "false", 0, "Sin comunicación con el PLC (OPC UA)", 950, on=3000)
    project.alarms = dict(retention_days=365, categories=[dict(id=i, name=n, color=c) for i, n, c in categories], items=items)

    columns = ["priority", "category", "message", "state", "entered_at", "returned_at", "ack_at", "actor"]
    views = {
        "activas": dict(title="Alarmas activas y pendientes de reconocer", mode="pending"),
        "historico": dict(title="Histórico de alarmas", mode="history"),
        "eventos": dict(title="Registro de eventos", mode="events"),
    }
    project.alarm_views = {k: dict(dict(categories=[], min_priority=1, allow_ack=True, columns=columns), **v) for k, v in views.items()}

    cellar = [f"{fv}.{f}" for fv in FERMENTERS for f in ("Temperatura", "ConsignaTemp", "Densidad", "Presion", "ValvulaGlicol", "Fase")]
    project.historian = dict(retention_days=365, files=[
        dict(id="coccion", name="Sala de cocción · 2 s", interval_ms=2000, variables=[
            "Cocina.Paso", "Cocina.TempMT", "Cocina.ConsignaActual", "Cocina.TempBK", "Cocina.NivelMT", "Cocina.NivelLT",
            "Cocina.NivelBK", "Cocina.VaporMT", "Cocina.VaporBK", "Cocina.NivelEspuma", "Cocina.PresionLecho",
            "Cocina.TempMostoSalida", "Cocina.DensidadMosto", "Cocina.Lote"]),
        dict(id="bodega", name="Bodega · 5 s", interval_ms=5000, variables=cellar),
        dict(id="servicios", name="Servicios · 5 s", interval_ms=5000, variables=[
            "Servicios.TempHLT", "Servicios.NivelHLT", "Servicios.PresionVapor", "Servicios.TempGlicol",
            "Servicios.NivelGlicol", "Servicios.TempAguaFria"]),
    ])

    def axis(identifier, title, side="left", auto=True, low=0, high=100):
        return dict(id=identifier, title=title, side=side, auto=auto, min=low, max=high, visible=True)

    def curve(identifier, tag, axis_id, color, width=2):
        return dict(id=identifier, tag=tag, axis=axis_id, color=color, width=width, visible=True)

    project.trends = {
        "coccion": dict(title="Maceración y hervido", window_seconds=600,
                        axes=[axis("c", "Temperatura (°C)", auto=False, low=0, high=105), axis("hl", "Nivel (hl)", "right", auto=False, low=0, high=14)],
                        curves=[curve("mt", "Cocina.TempMT", "c", "#c2872b", 3), curve("sp", "Cocina.ConsignaActual", "c", "#5f676e", 1),
                                curve("bk", "Cocina.TempBK", "c", "#d32f2f", 2), curve("nbk", "Cocina.NivelBK", "hl", "#4f86b8", 2)]),
        "servicios": dict(title="Vapor, agua caliente y glicol", window_seconds=900,
                          axes=[axis("c", "Temperatura (°C)"), axis("b", "Presión (bar)", "right", auto=False, low=0, high=8)],
                          curves=[curve("hlt", "Servicios.TempHLT", "c", "#4f86b8", 2), curve("gl", "Servicios.TempGlicol", "c", "#3c8fa6", 3),
                                  curve("af", "Servicios.TempAguaFria", "c", "#7aa6c2", 1), curve("v", "Servicios.PresionVapor", "b", "#9a6fb0", 2)]),
        "perfil_receta": dict(title="Último lote: temperatura de maceración", window_seconds=600,
                              axes=[axis("c", "Temperatura (°C)", auto=False, low=40, high=105)],
                              curves=[curve("mt", "Cocina.TempMT", "c", "#c2872b", 3), curve("sp", "Cocina.ConsignaActual", "c", "#5f676e", 1)]),
    }
    for fv in FERMENTERS:
        project.trends[f"fermentacion_{fv.lower()}"] = dict(
            title=f"{fv}: curva de fermentación", window_seconds=1800,
            axes=[axis("c", "Temperatura (°C)", auto=False, low=-2, high=24), axis("p", "Densidad (°P) · presión (bar)", "right", auto=False, low=0, high=18)],
            curves=[curve("t", f"{fv}.Temperatura", "c", "#d32f2f", 3), curve("sp", f"{fv}.ConsignaTemp", "c", "#5f676e", 1),
                    curve("d", f"{fv}.Densidad", "p", "#c2872b", 3), curve("p", f"{fv}.Presion", "p", "#3c8fa6", 1)])

    project.scripts = {
        "inicio": '''"""Arranque del Runtime: marca la sesión."""
from datetime import datetime

ctx.write("Sistema.Inicio", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
print("SCADA La Tolva iniciado")
''',
        "ciclo_1s": '''"""Cada segundo: reloj y estado de la comunicación con el PLC."""
from datetime import datetime

now = datetime.now()
ctx.write("Sistema.Fecha", now.strftime("%d/%m/%Y"))
ctx.write("Sistema.Hora", now.strftime("%H:%M:%S"))
ctx.write("Sistema.ComPLC", ctx.quality("Cocina.Paso") == "good")
''',
        "seguimiento_lotes": '''"""Cada 2 s: anota en «Último evento» los hitos de cada lote (inicio, llegada a bodega, listo)."""
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
''',
        "apertura": '''"""Al abrir una pantalla: la muestra en el menú."""
ctx.write("Sistema.Pantalla", ctx.screen)
''',
    }
    project.automation = dict(startup=["inicio"], timeout_seconds=5, tasks=[
        dict(id="ciclo_1s", script="ciclo_1s", interval_ms=1000, enabled=True),
        dict(id="seguimiento_lotes", script="seguimiento_lotes", interval_ms=2000, enabled=True)])


# Studio tree: folders by function (runtime ignores them).
FOLDERS = [("Estructura", ("00_", "01_", "02_")), ("Proceso", ("10_", "20_", "30_", "40_", "50_")),
           ("Tendencias", ("7",)), ("Alarmas", ("8",)), ("Emergentes", ("95_",)), ("Utilidades", ("90_", "99_"))]


def organise(project):
    for key, document in project.screens.items():
        document["folder"] = next(folder for folder, prefixes in FOLDERS if key.startswith(prefixes))
    own_viewers(project)


# ---------------------------------------------------------------------------
def build_project(root, force=False):
    root = Path(root).resolve()
    kept = {}
    if is_project(root):
        if not force:
            raise ValueError("El proyecto ya existe; usa --force para regenerarlo (se pierden sus cambios)")
        # The README is hand-written and the accounts carry salted hashes: keep both.
        kept = {name: (root / name).read_bytes() for name in ("README.md", "users.json") if (root / name).exists()}
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in kept.items():
        (root / name).write_bytes(content)
    project = Project(root, dict(schema_version=1, name="La Tolva", startup_screen="00_layout", palette=PALETTE,
                                 display=dict(main=dict(mode="maximized"))),
                      {}, [], [], {}, {}, manifest_file="la_tolva.abscada")
    project.types, project.variables = build_variables()
    project.connections = build_connections()
    project.faceplates = build_faceplates()
    build_layout(project)
    build_overview(project)
    build_brewhouse(project)
    build_cellar(project)
    build_recipes(project)
    build_services(project)
    build_trends(project)
    build_alarm_screens(project)
    build_instructor(project)
    build_help(project)
    for key, data in project.screens.items():
        if key not in ("00_layout", "01_cabecera", "02_menu") and data.get("width") == SCREEN_W:
            data["on_open"] = ["apertura"]
    build_operations(project)
    project.security = build_security()
    project.opcua_server = dict(enabled=True, port=4850, security=["Basic256Sha256_SignAndEncrypt"], allow_anonymous=False)
    organise(project)
    project.validate()
    project.save()
    build_accounts(project)
    return project


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="examples/brewery")
    parser.add_argument("--force", action="store_true", help="Regenerar aunque exista (borra la carpeta)")
    args = parser.parse_args()
    built = build_project(args.output, args.force)
    print(f"{built.root}: {len(built.screens)} pantallas, {len(built.tags())} variables, "
          f"{len(built.connections)} conexiones, {len(built.alarms['items'])} alarmas")
