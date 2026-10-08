"""Memory map shared by the hydro example builder and its PLC simulator.

One source of truth: build_hydro.py derives the SCADA bindings from these
tables and hydro.py serves exactly the same addresses.

Each entry is (field, scada_type, s7_address, writable_from_scada).
REAL = 'float' on %DBn.DBDx, DINT = 'int' on %DBn.DBDx, BOOL on %DBn.DBXb.i.
"""

# --- Unit PLC (identical layout on PLC_G1 and PLC_G2), DB1 -----------------
UNIT_FIELDS = [
    # Commands (pulses: the PLC clears them once accepted)
    ("OrdenArranque", "bool", "%DB1.DBX0.0", True),
    ("OrdenParada", "bool", "%DB1.DBX0.1", True),
    ("OrdenEmergencia", "bool", "%DB1.DBX0.2", True),
    ("OrdenRearme", "bool", "%DB1.DBX0.3", True),
    # Status
    ("Remoto", "bool", "%DB1.DBX0.4", False),
    ("ListoArranque", "bool", "%DB1.DBX0.5", False),
    ("Acoplado", "bool", "%DB1.DBX0.6", False),
    ("Disparo", "bool", "%DB1.DBX0.7", False),
    ("ValvulaAbierta", "bool", "%DB1.DBX1.0", False),
    ("ValvulaCerrada", "bool", "%DB1.DBX1.1", False),
    ("Interruptor52G", "bool", "%DB1.DBX1.2", False),
    ("InterruptorCampo", "bool", "%DB1.DBX1.3", False),
    ("Frenos", "bool", "%DB1.DBX1.4", False),
    ("Refrigeracion", "bool", "%DB1.DBX1.5", False),
    ("BombaOleo", "bool", "%DB1.DBX1.6", False),
    ("AlarmaGrupo", "bool", "%DB1.DBX1.7", False),
    # Training faults injected from the instructor screen
    ("SimCojinete", "bool", "%DB1.DBX2.0", True),
    ("SimRefrigeracion", "bool", "%DB1.DBX2.1", True),
    ("SimVibracion", "bool", "%DB1.DBX2.2", True),
    ("SimLocal", "bool", "%DB1.DBX2.3", True),
    ("ZonaRugosa", "bool", "%DB1.DBX2.4", False),
    ("FalloRefrigeracion", "bool", "%DB1.DBX2.5", False),
    ("FalloBombaOleo", "bool", "%DB1.DBX2.6", False),
    # Analog and counters
    ("Paso", "int", "%DB1.DBD4", False),
    ("ConsignaP", "float", "%DB1.DBD8", True),
    ("ConsignaQ", "float", "%DB1.DBD12", True),
    ("Velocidad", "float", "%DB1.DBD16", False),
    ("VelocidadRpm", "float", "%DB1.DBD20", False),
    ("Distribuidor", "float", "%DB1.DBD24", False),
    ("PosValvula", "float", "%DB1.DBD28", False),
    ("Caudal", "float", "%DB1.DBD32", False),
    ("Potencia", "float", "%DB1.DBD36", False),
    ("Reactiva", "float", "%DB1.DBD40", False),
    ("Tension", "float", "%DB1.DBD44", False),
    ("Intensidad", "float", "%DB1.DBD48", False),
    ("Frecuencia", "float", "%DB1.DBD52", False),
    ("CosPhi", "float", "%DB1.DBD56", False),
    ("TempGuiaSup", "float", "%DB1.DBD60", False),
    ("TempEmpuje", "float", "%DB1.DBD64", False),
    ("TempGuiaTurbina", "float", "%DB1.DBD68", False),
    ("TempEstator", "float", "%DB1.DBD72", False),
    ("TempAceite", "float", "%DB1.DBD76", False),
    ("Vibracion", "float", "%DB1.DBD80", False),
    ("PresionOleo", "float", "%DB1.DBD84", False),
    ("CaudalRefrigeracion", "float", "%DB1.DBD88", False),
    ("PresionEspiral", "float", "%DB1.DBD92", False),
    ("CorrienteExcitacion", "float", "%DB1.DBD96", False),
    ("Energia", "float", "%DB1.DBD100", False),
    ("HorasMarcha", "float", "%DB1.DBD104", False),
    ("Arranques", "int", "%DB1.DBD108", False),
    ("CausaDisparo", "int", "%DB1.DBD112", False),
]
UNIT_DB_SIZE = 116

# --- Common services PLC (dam, spillway, substation, auxiliaries), DB1 -----
COMMON_FIELDS = [
    ("CompuertaTomaAbierta", "bool", "%DB1.DBX0.0", False),
    ("CompuertaTomaCerrada", "bool", "%DB1.DBX0.1", False),
    ("OrdenAbrirToma", "bool", "%DB1.DBX0.2", True),
    ("OrdenCerrarToma", "bool", "%DB1.DBX0.3", True),
    ("Interruptor52L", "bool", "%DB1.DBX0.4", False),
    ("OrdenAbrir52L", "bool", "%DB1.DBX0.5", True),
    ("OrdenCerrar52L", "bool", "%DB1.DBX0.6", True),
    ("RedPresente", "bool", "%DB1.DBX0.7", False),
    ("BombaDrenaje1", "bool", "%DB1.DBX1.0", False),
    ("BombaDrenaje2", "bool", "%DB1.DBX1.1", False),
    ("Compresor", "bool", "%DB1.DBX1.2", False),
    ("CargadorOk", "bool", "%DB1.DBX1.3", False),
    ("TrafoAuxOk", "bool", "%DB1.DBX1.4", False),
    ("GrupoDiesel", "bool", "%DB1.DBX1.5", False),
    ("AliviaderoAuto", "bool", "%DB1.DBX1.6", True),
    ("SimAvenida", "bool", "%DB1.DBX1.7", True),
    ("SimFalloRed", "bool", "%DB1.DBX2.0", True),
    ("SimFalloCargador", "bool", "%DB1.DBX2.1", True),
    ("AlarmaPresa", "bool", "%DB1.DBX2.2", False),
    ("AlarmaSubestacion", "bool", "%DB1.DBX2.3", False),
    ("AlarmaAuxiliares", "bool", "%DB1.DBX2.4", False),
    ("FalloDrenaje", "bool", "%DB1.DBX2.5", False),
    ("FalloCompresor", "bool", "%DB1.DBX2.6", False),
    ("NivelEmbalse", "float", "%DB1.DBD4", False),
    ("Volumen", "float", "%DB1.DBD8", False),
    ("CaudalEntrada", "float", "%DB1.DBD12", False),
    ("CaudalSalida", "float", "%DB1.DBD16", False),
    ("PosCompuerta1", "float", "%DB1.DBD20", False),
    ("ConsignaCompuerta1", "float", "%DB1.DBD24", True),
    ("PosCompuerta2", "float", "%DB1.DBD28", False),
    ("ConsignaCompuerta2", "float", "%DB1.DBD32", True),
    ("CaudalAliviadero", "float", "%DB1.DBD36", False),
    ("CaudalEcologico", "float", "%DB1.DBD40", False),
    ("NivelDesague", "float", "%DB1.DBD44", False),
    ("SaltoBruto", "float", "%DB1.DBD48", False),
    ("Lluvia", "float", "%DB1.DBD52", False),
    ("PresionTuberia", "float", "%DB1.DBD56", False),
    ("NivelPozo", "float", "%DB1.DBD60", False),
    ("PresionAire", "float", "%DB1.DBD64", False),
    ("TensionBaterias", "float", "%DB1.DBD68", False),
    ("Tension400V", "float", "%DB1.DBD72", False),
    ("TensionBarras66", "float", "%DB1.DBD76", False),
    ("FrecuenciaRed", "float", "%DB1.DBD80", False),
    ("TempAmbiente", "float", "%DB1.DBD84", False),
    ("PosCompuertaToma", "float", "%DB1.DBD88", False),
]
COMMON_DB_SIZE = 92

# --- Fiscal energy meter on the 66 kV boundary, Modbus TCP ------------------
# (field, scada_type, area, offset, encoding, writable)
METER_FIELDS = [
    ("Comunicacion", "bool", "discrete_inputs", 0, "bool", False),
    ("Potencia", "float", "input_registers", 0, "float32", False),
    ("Reactiva", "float", "input_registers", 2, "float32", False),
    ("Tension", "float", "input_registers", 4, "float32", False),
    ("Frecuencia", "float", "input_registers", 6, "float32", False),
    ("CosPhi", "float", "input_registers", 8, "float32", False),
    ("EnergiaExportada", "int", "input_registers", 10, "uint32", False),
    ("EnergiaImportada", "int", "input_registers", 12, "uint32", False),
]

# Ports used by the simulator and the shipped connections.
PORTS = {"PLC_G1": 1102, "PLC_G2": 1103, "PLC_SSCC": 1104, "Contador_66kV": 1502}

# Start/stop sequence as shown on the unit screens. The PLC uses the same numbers.
STEPS = [
    "Parado",
    "Arranque de auxiliares",
    "Apertura válvula de entrada",
    "Aceleración",
    "Excitación",
    "Sincronización",
    "En carga",
    "Descarga",
    "Desacoplamiento",
    "Cierre y frenado",
    "Disparo · bloqueo 86",
]

TRIP_CAUSES = [
    "Sin disparo",
    "Parada de emergencia",
    "Temperatura de cojinete",
    "Sobrevelocidad",
    "Vibración muy alta",
    "Presión de aceite muy baja",
    "Temperatura de estator",
    "Protección eléctrica / red",
]
