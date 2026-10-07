"""Build abSCADA's standard library: SVG symbols and the catalogue of objects.

    .venv\\Scripts\\python tools/build_standard_library.py

Writes src/abscada/standard_library/ (library.json + graficos/ + objetos/). The output is
committed: the application ships it read-only and never copies it into projects.

Style: high-performance HMI (ISA-101). Grey equipment, colour only for state:
grey stopped/closed, green running/open, red fault, amber bad quality, blue water.
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "abscada" / "standard_library"

INK = "#2f3b45"        # outlines
BODY = "#d9dfe4"       # equipment body
LIGHT = "#eef1f4"      # highlights
WATER = "#4f86b8"
STATES = {"paro": "#9aa3ab", "marcha": "#2e8b57", "fallo": "#d32f2f", "dudoso": "#e89a1c"}
SW = 2.5               # stroke width


def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            f'<g fill="{BODY}" stroke="{INK}" stroke-width="{SW}" stroke-linejoin="round" stroke-linecap="round">\n'
            f'{body}\n</g>\n</svg>\n')


def metal(identifier, horizontal=False):
    x2, y2 = ("0", "1") if horizontal else ("1", "0")
    return (f'<defs><linearGradient id="{identifier}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
            f'<stop offset="0" stop-color="#c3cbd2"/><stop offset="0.45" stop-color="{LIGHT}"/>'
            f'<stop offset="1" stop-color="#b6bfc7"/></linearGradient></defs>')


# -- symbols ------------------------------------------------------------------
def tank_vertical(fill=None):
    return svg(100, 140, metal("m") + f'''
<path d="M14 26 Q14 8 50 8 Q86 8 86 26 L86 114 Q86 132 50 132 Q14 132 14 114 Z" fill="{fill or 'url(#m)'}"/>
<path d="M14 26 Q50 38 86 26" fill="none" stroke-width="1.2" opacity="0.5"/>
<path d="M14 114 Q50 126 86 114" fill="none" stroke-width="1.2" opacity="0.5"/>
<rect x="44" y="2" width="12" height="6"/>''')


def tank_horizontal():
    return svg(160, 90, metal("m", True) + '''
<path d="M30 12 L130 12 Q152 12 152 45 Q152 78 130 78 L30 78 Q8 78 8 45 Q8 12 30 12 Z" fill="url(#m)"/>
<path d="M30 12 Q42 45 30 78 M130 12 Q118 45 130 78" fill="none" stroke-width="1.2" opacity="0.5"/>
<path d="M40 78 L36 88 M120 78 L124 88" fill="none"/>''')


def silo():
    return svg(100, 150, metal("m") + '''
<path d="M18 30 Q50 6 82 30 L82 96 L58 132 L42 132 L18 96 Z" fill="url(#m)"/>
<path d="M18 96 L82 96" fill="none" stroke-width="1.2" opacity="0.6"/>
<rect x="42" y="132" width="16" height="12"/>
<path d="M22 96 L14 148 M78 96 L86 148" fill="none"/>''')


def hopper():
    return svg(100, 110, metal("m") + '''
<path d="M8 10 L92 10 L92 40 L60 90 L40 90 L8 40 Z" fill="url(#m)"/>
<rect x="40" y="90" width="20" height="14"/>''')


def open_tank():
    return svg(110, 110, f'''
<path d="M10 12 L10 98 Q10 104 16 104 L94 104 Q100 104 100 98 L100 12" fill="{LIGHT}"/>
<path d="M12 46 L98 46 L98 98 Q98 102 94 102 L16 102 Q12 102 12 98 Z" fill="{WATER}" stroke="none" opacity="0.85"/>
<path d="M12 46 Q30 40 48 46 T86 46 T98 46" fill="none" stroke="#ffffff" stroke-width="1.5"/>''')


def sphere():
    return svg(110, 120, metal("m") + '''
<circle cx="55" cy="50" r="42" fill="url(#m)"/>
<path d="M13 50 Q55 64 97 50" fill="none" stroke-width="1.2" opacity="0.5"/>
<path d="M28 82 L20 116 M82 82 L90 116 M55 92 L55 116" fill="none"/>''')


def bowtie(fill=BODY):
    return f'<path d="M10 30 L10 58 L50 44 Z M90 30 L90 58 L50 44 Z" fill="{fill}"/>'


def valve(kind, fill=BODY):
    top = {
        "manual": '<path d="M50 44 L50 18 M36 18 L64 18" fill="none"/>',
        "motorizada": '<path d="M50 44 L50 26" fill="none"/><rect x="36" y="4" width="28" height="22" rx="3"/>'
                      '<text x="50" y="20" font-family="sans-serif" font-size="14" font-weight="bold" '
                      f'text-anchor="middle" fill="{INK}" stroke="none">M</text>',
        "neumatica": '<path d="M50 44 L50 24" fill="none"/><path d="M30 24 Q50 2 70 24 Z"/>',
        "reguladora": '<path d="M50 44 L50 24" fill="none"/><path d="M30 24 Q50 2 70 24 Z"/>'
                      '<path d="M22 64 L78 22" fill="none" stroke-width="1.8"/><path d="M78 22 L68 24 L74 31 Z" fill="'
                      f'{INK}"/>',
    }
    return svg(100, 64, bowtie(fill) + top.get(kind, ""))


def valve_ball():
    return svg(100, 64, bowtie() + '<circle cx="50" cy="44" r="9" fill="#ffffff"/>'
               '<path d="M50 35 L50 18 M38 18 L62 18" fill="none"/>')


def valve_butterfly():
    return svg(100, 64, '<circle cx="50" cy="40" r="22" fill="#ffffff"/>'
               '<path d="M10 40 L28 40 M72 40 L90 40" fill="none"/>'
               '<path d="M34 56 L66 24" fill="none" stroke-width="3.5"/><circle cx="50" cy="40" r="3" fill="'
               f'{INK}"/>')


def valve_check():
    return svg(100, 64, bowtie() + f'<path d="M90 30 L90 58" fill="none" stroke-width="4"/>'
               f'<path d="M24 16 L70 16 M62 10 L72 16 L62 22" fill="none" stroke-width="1.8"/>')


def valve_three_way():
    return svg(100, 90, '<path d="M10 30 L10 58 L50 44 Z M90 30 L90 58 L50 44 Z M36 84 L64 84 L50 44 Z"/>'
               '<path d="M50 44 L50 18 M36 18 L64 18" fill="none"/>')


def valve_safety():
    # Angle valve: inlet from below, outlet to the right, spring-loaded bonnet on top.
    return svg(90, 100, '<path d="M26 96 L54 96 L40 62 Z M86 48 L86 76 L40 62 Z"/>'
               '<path d="M40 62 L40 50" fill="none"/>'
               '<path d="M40 50 L30 45 L50 39 L30 33 L50 27 L30 21 L40 16" fill="none" stroke-width="1.8"/>'
               '<path d="M28 12 L52 12" fill="none" stroke-width="3"/>')


def pump_centrifugal(fill=BODY):
    return svg(100, 100, f'<path d="M50 50 L50 8 L92 8 L92 26 L68 26" fill="{fill}"/>'
               f'<circle cx="50" cy="56" r="34" fill="{fill}"/>'
               f'<path d="M32 76 L50 30 L68 76 Z" fill="#ffffff" stroke-width="1.8"/>'
               '<path d="M22 86 L14 96 L86 96 L78 86" fill="none"/>')


def pump_positive():
    return svg(100, 100, '<circle cx="50" cy="50" r="34"/>'
               '<circle cx="38" cy="50" r="11" fill="#ffffff"/><circle cx="62" cy="50" r="11" fill="#ffffff"/>'
               '<path d="M2 50 L16 50 M84 50 L98 50" fill="none"/><path d="M22 80 L14 92 L86 92 L78 80" fill="none"/>')


def motor(fill=BODY, letter="M"):
    return svg(100, 100, f'<circle cx="50" cy="50" r="38" fill="{fill}"/>'
               f'<text x="50" y="62" font-family="sans-serif" font-size="34" font-weight="bold" '
               f'text-anchor="middle" fill="{INK}" stroke="none">{letter}</text>')


def fan(fill=BODY):
    blades = "".join(f'<path d="M50 50 Q{50 + 30 * c} {50 + 30 * s} {50 + 8 * c - 26 * s} {50 + 8 * s + 26 * c} Z" '
                     f'fill="#ffffff" stroke-width="1.6" transform="rotate({a} 50 50)"/>'
                     for a, c, s in ((0, 1, 0), (120, 1, 0), (240, 1, 0)))
    return svg(100, 100, f'<circle cx="50" cy="50" r="40" fill="{fill}"/>{blades}<circle cx="50" cy="50" r="5" fill="{INK}"/>')


def compressor():
    return svg(100, 100, '<circle cx="50" cy="50" r="38"/>'
               '<path d="M24 22 L76 36 M24 78 L76 64" fill="none" stroke-width="2"/>'
               '<path d="M2 50 L12 50 M88 50 L98 50" fill="none"/>')


def agitator():
    return svg(80, 130, '<rect x="22" y="4" width="36" height="28" rx="4"/>'
               f'<text x="40" y="24" font-family="sans-serif" font-size="16" font-weight="bold" '
               f'text-anchor="middle" fill="{INK}" stroke="none">M</text>'
               '<path d="M40 32 L40 110" fill="none"/>'
               '<path d="M40 104 L14 96 L14 112 Z M40 104 L66 96 L66 112 Z" fill="#ffffff"/>')


def heat_exchanger():
    return svg(140, 80, metal("m", True) + '''
<rect x="10" y="18" width="120" height="44" rx="22" fill="url(#m)"/>
<path d="M22 40 L36 26 L50 54 L64 26 L78 54 L92 26 L106 54 L118 40" fill="none" stroke-width="2"/>
<path d="M36 18 L36 4 M104 62 L104 76" fill="none"/>''')


def filter_():
    return svg(90, 110, '<path d="M45 8 L82 55 L45 102 L8 55 Z" fill="#ffffff"/>'
               '<path d="M45 8 L45 102" fill="none" stroke-dasharray="6 5" stroke-width="2"/>')


def cyclone():
    return svg(90, 140, metal("m") + '''
<path d="M14 10 L76 10 L76 58 L54 120 L36 120 L14 58 Z" fill="url(#m)"/>
<rect x="36" y="120" width="18" height="14"/>
<path d="M76 22 L88 22 M45 10 L45 0" fill="none"/>
<path d="M24 30 Q45 44 66 30 M28 54 Q45 66 62 54" fill="none" stroke-width="1.2" opacity="0.6"/>''')


def boiler():
    return svg(110, 120, metal("m") + f'''
<rect x="10" y="10" width="90" height="98" rx="10" fill="url(#m)"/>
<path d="M40 96 Q34 80 46 68 Q46 80 54 82 Q50 66 62 56 Q60 74 70 80 Q76 92 68 96 Z" fill="#e89a1c" stroke="#b5651d" stroke-width="1.5"/>
<path d="M30 10 L30 2 M80 10 L80 2" fill="none"/>''')


def cooling_tower():
    return svg(110, 130, metal("m") + '''
<path d="M14 120 Q34 70 22 12 L88 12 Q76 70 96 120 Z" fill="url(#m)"/>
<path d="M30 0 Q36 8 30 14 M55 0 Q61 8 55 14 M80 0 Q86 8 80 14" fill="none" stroke-width="1.5" opacity="0.7"/>''')


def column():
    return svg(70, 160, metal("m") + '''
<path d="M12 22 Q12 6 35 6 Q58 6 58 22 L58 138 Q58 154 35 154 Q12 154 12 138 Z" fill="url(#m)"/>
<path d="M12 50 L58 50 M12 80 L58 80 M12 110 L58 110" fill="none" stroke-width="1.2" stroke-dasharray="5 4"/>''')


def instrument(letters):
    return svg(80, 80, '<circle cx="40" cy="40" r="32" fill="#ffffff"/>'
               '<path d="M8 40 L72 40" fill="none" stroke-width="1.5"/>'
               f'<text x="40" y="33" font-family="sans-serif" font-size="17" font-weight="bold" '
               f'text-anchor="middle" fill="{INK}" stroke="none">{letters}</text>')


def transformer():
    return svg(80, 120, '<circle cx="40" cy="42" r="26" fill="none"/><circle cx="40" cy="78" r="26" fill="none"/>'
               '<path d="M40 0 L40 16 M40 104 L40 120" fill="none"/>')


def breaker(fill="#ffffff"):
    return svg(60, 60, f'<rect x="8" y="8" width="44" height="44" fill="{fill}"/>')


def disconnector():
    return svg(60, 100, '<path d="M30 0 L30 28 M30 72 L30 100" fill="none"/>'
               '<circle cx="30" cy="72" r="3" fill="#ffffff"/><path d="M30 72 L14 32" fill="none"/>')


GRAPHICS = [
    # (file, title, folder, function, width, height)
    ("deposito_vertical", "Depósito vertical", "Depósitos", tank_vertical),
    ("deposito_horizontal", "Depósito horizontal", "Depósitos", tank_horizontal),
    ("silo", "Silo", "Depósitos", silo),
    ("tolva", "Tolva", "Depósitos", hopper),
    ("tanque_abierto", "Tanque abierto", "Depósitos", open_tank),
    ("deposito_esferico", "Depósito esférico", "Depósitos", sphere),
    ("valvula_manual", "Válvula manual", "Válvulas", lambda: valve("manual")),
    ("valvula_motorizada", "Válvula motorizada", "Válvulas", lambda: valve("motorizada")),
    ("valvula_neumatica", "Válvula neumática", "Válvulas", lambda: valve("neumatica")),
    ("valvula_reguladora", "Válvula reguladora", "Válvulas", lambda: valve("reguladora")),
    ("valvula_bola", "Válvula de bola", "Válvulas", valve_ball),
    ("valvula_mariposa", "Válvula de mariposa", "Válvulas", valve_butterfly),
    ("valvula_retencion", "Válvula de retención", "Válvulas", valve_check),
    ("valvula_tres_vias", "Válvula de tres vías", "Válvulas", valve_three_way),
    ("valvula_seguridad", "Válvula de seguridad", "Válvulas", valve_safety),
    ("bomba_centrifuga", "Bomba centrífuga", "Bombas y motores", pump_centrifugal),
    ("bomba_volumetrica", "Bomba volumétrica", "Bombas y motores", pump_positive),
    ("motor", "Motor", "Bombas y motores", motor),
    ("ventilador", "Ventilador", "Bombas y motores", fan),
    ("compresor", "Compresor", "Bombas y motores", compressor),
    ("agitador", "Agitador", "Bombas y motores", agitator),
    ("intercambiador", "Intercambiador de calor", "Proceso", heat_exchanger),
    ("filtro", "Filtro", "Proceso", filter_),
    ("ciclon", "Ciclón", "Proceso", cyclone),
    ("caldera", "Caldera", "Proceso", boiler),
    ("torre_refrigeracion", "Torre de refrigeración", "Proceso", cooling_tower),
    ("columna", "Columna", "Proceso", column),
    ("transmisor_nivel", "Transmisor de nivel", "Instrumentos", lambda: instrument("LT")),
    ("transmisor_presion", "Transmisor de presión", "Instrumentos", lambda: instrument("PT")),
    ("transmisor_temperatura", "Transmisor de temperatura", "Instrumentos", lambda: instrument("TT")),
    ("transmisor_caudal", "Transmisor de caudal", "Instrumentos", lambda: instrument("FT")),
    ("transformador", "Transformador", "Eléctrico", transformer),
    ("interruptor", "Interruptor", "Eléctrico", breaker),
    ("seccionador", "Seccionador", "Eléctrico", disconnector),
    ("generador", "Generador", "Eléctrico", lambda: motor(letter="G")),
]


def size_of(text):
    head = text.split(">", 1)[0]
    width = float(head.split('width="')[1].split('"')[0])
    height = float(head.split('height="')[1].split('"')[0])
    return width, height


def image_template(title, folder, source, width, height, parameters=None, extra=(), dynamics=None):
    image = dict(id="simbolo", kind="image", x=0, y=0, w=width, h=height, source=source)
    if dynamics:
        image["dynamics"] = dynamics
    return dict(title=title, folder=folder, width=width, height=height, parameters=parameters or {},
                elements=[image, *extra])


def state(tag, value, source):
    return dict(when=dict(tag=tag, op="eq", value=value, bad=False), style=dict(source=source))


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "graficos").mkdir(parents=True)
    (OUT / "objetos").mkdir(parents=True)
    templates = {}
    for name, title, folder, build in GRAPHICS:
        text = build()
        (OUT / "graficos" / f"{name}.svg").write_text(text, encoding="utf-8", newline="\n")
        width, height = size_of(text)
        templates[name] = image_template(title, f"Gráficos/{folder}", f"graficos/{name}.svg", width, height)

    # Animated objects: the same symbols in state colours, switched by their parameters.
    def variants(name, build):
        for key, colour in STATES.items():
            (OUT / "objetos" / f"{name}_{key}.svg").write_text(build(colour), encoding="utf-8", newline="\n")
        return {key: f"objetos/{name}_{key}.svg" for key in STATES}

    for name, title, build, width, height in (
            ("bomba", "Bomba", pump_centrifugal, 100, 100), ("motor", "Motor", lambda c: motor(c), 100, 100),
            ("ventilador", "Ventilador", fan, 100, 100)):
        files = variants(name, build)
        templates[f"{name}_estado"] = image_template(
            f"{title} con estado", "Objetos", files["paro"], width, height, dict(marcha="bool", fallo="bool"),
            dynamics=dict(states=[state("$fallo", True, files["fallo"]), state("$marcha", True, files["marcha"])],
                          bad=dict(source=files["dudoso"])))
    files = variants("valvula", lambda colour: valve("motorizada", colour))
    templates["valvula_estado"] = image_template(
        "Válvula abierta / cerrada", "Objetos", files["paro"], 100, 64, dict(abierta="bool"),
        dynamics=dict(states=[state("$abierta", True, files["marcha"])], bad=dict(source=files["dudoso"])))
    files = variants("interruptor", breaker)
    templates["interruptor_estado"] = image_template(
        "Interruptor abierto / cerrado", "Objetos", files["marcha"], 60, 60, dict(cerrado="bool"),
        dynamics=dict(states=[state("$cerrado", True, files["fallo"])], bad=dict(source=files["dudoso"])))
    templates["deposito_nivel"] = image_template(
        "Depósito con nivel", "Objetos", "graficos/deposito_vertical.svg", 100, 140, dict(nivel="float"),
        extra=[dict(id="nivel", kind="bar", x=24, y=30, w=52, h=88, tag="$nivel", min=0, max=100, color=WATER),
               dict(id="valor", kind="text", x=14, y=118, w=72, h=20, tag="$nivel", text="", unit="%", decimals=0,
                    font_size=11, bold=True, text_color=INK, color="#00000000", border_color="#00000000")])

    library = dict(schema_version=1, name="Estándar", version="1.0.0",
                   description="Librería del sistema: símbolos SCADA en SVG y objetos animados. Solo lectura.",
                   faceplates=templates)
    (OUT / "library.json").write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT}: {len(GRAPHICS)} gráficos, {len(templates) - len(GRAPHICS)} objetos animados")


if __name__ == "__main__":
    main()
