"""OPC UA address space shared by the brewery example builder and its PLC simulator.

One source of truth: build_brewery.py derives the SCADA bindings from these tables and
the simulator publishes exactly the same nodes. Every node lives in the namespace
NAMESPACE with a string identifier ``<object>.<field>``, so a binding reads
``nsu=urn:latolva:plc;s=FV1.Temperatura`` whatever index the server gives the namespace.

Each entry is (field, scada_type, writable_from_scada).
"""

NAMESPACE = "urn:latolva:plc"
PORT = 4841
ENDPOINT = f"opc.tcp://127.0.0.1:{PORT}/latolva"
FERMENTERS = ("FV1", "FV2", "FV3")

# Process time is compressed: one recipe minute lasts one real second in the
# brewhouse, and one fermentation day lasts one real minute in the cellar.
MINUTES_PER_SECOND = 1.0
DAYS_PER_SECOND = 1.0 / 60.0

STEPS = ["Reposo", "Llenado de agua", "Empaste", "Escalón 1 · proteico", "Escalón 2 · sacarificación",
         "Escalón 3 · mash-out", "Trasiego y recirculación", "Filtrado y lavado", "Calentamiento a ebullición",
         "Hervido", "Whirlpool", "Enfriado y trasiego a FV", "Limpieza CIP"]
PROMPTS = ["", "Añade la malta al macerador y confirma", "Añade el lúpulo de amargor y confirma",
           "Añade el lúpulo aromático y confirma"]
PHASES = ["Vacío y limpio", "Llenado", "Fermentación", "Reposo de diacetilo", "Enfriamiento (cold crash)",
          "Guarda", "Listo para envasar"]

BREWHOUSE_FIELDS = [
    # Commands (pulses: the PLC clears them once read)
    ("OrdenIniciar", "bool", True),
    ("OrdenRetener", "bool", True),
    ("OrdenReanudar", "bool", True),
    ("OrdenAbortar", "bool", True),
    ("OrdenConfirmar", "bool", True),
    # Next batch
    ("RecetaSeleccionada", "int", True),
    ("FVDestino", "int", True),
    ("NombreReceta", "string", False),
    # Sequence
    ("Paso", "int", False),
    ("ListoIniciar", "bool", False),
    ("Retenido", "bool", False),
    ("EsperaOperador", "bool", False),
    ("Aviso", "int", False),
    ("Lote", "int", False),
    ("RecetaLote", "string", False),
    ("FVLote", "int", False),
    ("TiempoPaso", "float", False),
    ("TiempoRestante", "float", False),
    ("ConsignaActual", "float", False),
    # Mash tun
    ("TempMT", "float", False),
    ("NivelMT", "float", False),
    ("VaporMT", "float", False),
    ("AgitadorMT", "bool", False),
    ("FueraTemperaturaMT", "bool", False),
    # Lauter tun
    ("NivelLT", "float", False),
    ("CaudalFiltrado", "float", False),
    ("PresionLecho", "float", False),
    ("Rastrillos", "bool", False),
    # Kettle and whirlpool
    ("TempBK", "float", False),
    ("NivelBK", "float", False),
    ("VaporBK", "float", False),
    ("Ebullicion", "bool", False),
    ("NivelEspuma", "float", False),
    # Wort cooler
    ("TempMostoSalida", "float", False),
    ("CaudalTrasiego", "float", False),
    ("DensidadMosto", "float", False),
    ("SiembraCaliente", "bool", False),
    ("AlarmaCocina", "bool", False),
    # Training faults
    ("SimEspuma", "bool", True),
    ("SimLechoColmatado", "bool", True),
]

FERMENTER_FIELDS = [
    ("OrdenVaciar", "bool", True),
    ("Automatico", "bool", True),
    ("ConsignaManual", "float", True),
    ("Fase", "int", False),
    ("Lote", "int", False),
    ("NombreReceta", "string", False),
    ("Dia", "float", False),
    ("Temperatura", "float", False),
    ("ConsignaTemp", "float", False),
    ("Desviacion", "float", False),
    ("Densidad", "float", False),
    ("DensidadOriginal", "float", False),
    ("DensidadObjetivo", "float", False),
    ("Atenuacion", "float", False),
    ("Presion", "float", False),
    ("Nivel", "float", False),
    ("ValvulaGlicol", "float", False),
    ("FermentacionParada", "bool", False),
    ("Alarma", "bool", False),
    ("SimValvulaAtascada", "bool", True),
    ("SimSobrepresion", "bool", True),
    ("SimFermentacionParada", "bool", True),
]

SERVICES_FIELDS = [
    ("ConsignaHLT", "float", True),
    ("ConsignaGlicol", "float", True),
    ("TempHLT", "float", False),
    ("NivelHLT", "float", False),
    ("PresionVapor", "float", False),
    ("Caldera", "bool", False),
    ("FalloCaldera", "bool", False),
    ("Enfriadora", "bool", False),
    ("FalloEnfriadora", "bool", False),
    ("TempGlicol", "float", False),
    ("NivelGlicol", "float", False),
    ("TempAguaFria", "float", False),
    ("AlarmaServicios", "bool", False),
    ("SimFalloCaldera", "bool", True),
    ("SimFalloEnfriadora", "bool", True),
    ("SimFugaGlicol", "bool", True),
]

# Recipe parameters: (field, type, caption, unit, low, high)
RECIPE_PARAMETERS = [
    ("VolumenAgua", "float", "Agua de empaste", "hl", 4.0, 9.0),
    ("TempE1", "float", "Escalón 1 · temperatura", "°C", 45.0, 58.0),
    ("TiempoE1", "float", "Escalón 1 · tiempo (0 = sin escalón)", "min", 0.0, 30.0),
    ("TempE2", "float", "Escalón 2 · temperatura", "°C", 60.0, 72.0),
    ("TiempoE2", "float", "Escalón 2 · tiempo", "min", 20.0, 90.0),
    ("TempE3", "float", "Mash-out · temperatura", "°C", 74.0, 80.0),
    ("TiempoE3", "float", "Mash-out · tiempo", "min", 5.0, 20.0),
    ("TiempoHervido", "float", "Tiempo de hervido", "min", 45.0, 120.0),
    ("LupuloAroma", "float", "Lúpulo aromático · antes del final", "min", 0.0, 30.0),
    ("DensidadOriginal", "float", "Densidad original", "°P", 9.0, 20.0),
    ("DensidadFinal", "float", "Densidad final", "°P", 1.5, 5.0),
    ("TempFermentacion", "float", "Fermentación · temperatura", "°C", 8.0, 24.0),
    ("DiasFermentacion", "float", "Fermentación · días", "d", 3.0, 14.0),
    ("TempDiacetilo", "float", "Reposo de diacetilo · temperatura", "°C", 12.0, 24.0),
    ("DiasDiacetilo", "float", "Reposo de diacetilo · días", "d", 0.0, 4.0),
    ("TempGuarda", "float", "Guarda · temperatura", "°C", -1.0, 6.0),
    ("DiasGuarda", "float", "Guarda · días", "d", 1.0, 21.0),
]
RECIPE_FIELDS = [("Nombre", "string")] + [(name, kind) for name, kind, *_ in RECIPE_PARAMETERS]
RECIPE_COUNT = 4

# Recipe editor: the classic load / edit / save buffer of a PLC recipe manager.
RECIPE_EDITOR_FIELDS = [
    ("Numero", "int", True),
    ("OrdenGuardar", "bool", True),
    ("OrdenDescartar", "bool", True),
    ("Modificada", "bool", False),
    ("EnUso", "bool", False),
    *[(name, kind, True) for name, kind in RECIPE_FIELDS],
    *[(f"Nombre{i}", "string", False) for i in range(1, RECIPE_COUNT + 1)],
]

DEFAULT_RECIPES = [
    dict(Nombre="Rubia", VolumenAgua=6.5, TempE1=52.0, TiempoE1=10.0, TempE2=65.0, TiempoE2=60.0, TempE3=78.0,
         TiempoE3=10.0, TiempoHervido=60.0, LupuloAroma=10.0, DensidadOriginal=12.0, DensidadFinal=2.4,
         TempFermentacion=19.0, DiasFermentacion=5.0, TempDiacetilo=21.0, DiasDiacetilo=2.0, TempGuarda=2.0, DiasGuarda=4.0),
    dict(Nombre="Tostada", VolumenAgua=7.0, TempE1=52.0, TiempoE1=0.0, TempE2=68.0, TiempoE2=60.0, TempE3=78.0,
         TiempoE3=10.0, TiempoHervido=60.0, LupuloAroma=5.0, DensidadOriginal=13.5, DensidadFinal=3.2,
         TempFermentacion=18.0, DiasFermentacion=6.0, TempDiacetilo=20.0, DiasDiacetilo=2.0, TempGuarda=2.0, DiasGuarda=7.0),
    dict(Nombre="IPA", VolumenAgua=7.5, TempE1=52.0, TiempoE1=0.0, TempE2=65.0, TiempoE2=75.0, TempE3=77.0,
         TiempoE3=10.0, TiempoHervido=75.0, LupuloAroma=15.0, DensidadOriginal=15.5, DensidadFinal=2.8,
         TempFermentacion=19.0, DiasFermentacion=6.0, TempDiacetilo=22.0, DiasDiacetilo=3.0, TempGuarda=1.0, DiasGuarda=5.0),
    dict(Nombre="Negra", VolumenAgua=7.0, TempE1=52.0, TiempoE1=0.0, TempE2=67.0, TiempoE2=60.0, TempE3=78.0,
         TiempoE3=10.0, TiempoHervido=60.0, LupuloAroma=0.0, DensidadOriginal=12.5, DensidadFinal=3.5,
         TempFermentacion=18.0, DiasFermentacion=5.0, TempDiacetilo=20.0, DiasDiacetilo=1.0, TempGuarda=3.0, DiasGuarda=5.0),
]

OBJECTS = [("Cocina", BREWHOUSE_FIELDS), *[(fv, FERMENTER_FIELDS) for fv in FERMENTERS],
           ("Servicios", SERVICES_FIELDS), ("Recetas", RECIPE_EDITOR_FIELDS)]


def node(obj, field):
    return f"nsu={NAMESPACE};s={obj}.{field}"
