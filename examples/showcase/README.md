# Laboratorio SCADA

Recorrido por todos los controles gráficos y acciones de botón, con un banco de variables internas que funciona sin equipos, un PLC S7 y un equipo Modbus TCP. También es el ejemplo de **objetos de librería**: la pantalla 05 usa `equipos__unidad`, del paquete vinculado `examples/libraries/equipos-1.0.0.abscada-library.json`.

| | |
| --- | --- |
| Conexiones | S7 (127.0.0.1:1102, 250 ms) y Modbus TCP (127.0.0.1:1502, 500 ms) |
| Contenido | 21 pantallas, 33 variables, 3 registros, 3 gráficas, 6 alarmas y 5 scripts |

## Arrancar

Desde la pantalla de inicio, con **Arrancar también su PLC simulado**. O en dos terminales (requiere los extras `s7,modbus`):

```powershell
.venv\Scripts\python -m abscada --simulador laboratorio
.\run.ps1 examples/showcase
```

El banco de variables internas funciona sin simulador. Sin él, las variables S7 y Modbus muestran calidad *bad*; nunca reciben valores de sustitución.

## Recorrido

| Pantalla | Qué probar |
| --- | --- |
| 01 · Recorrido | Navegación, ventana completa y ajustes modales |
| 02 · Proceso interno | Marcha/paro, piloto, depósito, tuberías, barra y entradas. «Señal local» genera ondas desde una tarea Python |
| 03 · Estados y mandos | Botones superpuestos con visibilidad condicional, permiso que bloquea una orden, pulsador momentáneo, press/release y lista de textos |
| 04 · Dibujo e imágenes | Líneas, polilíneas, tuberías dinámicas, formas e imagen SVG con estados |
| 05 · Faceplates y ventanas | La misma plantilla enlazada a variables internas y a S7; emergentes modales y no modales |
| 06 · Siemens S7 | Dos bombas en DB1: escribe la consigna, pulsa marcha y el caudal sigue |
| 07 · Modbus TCP | Coils, discrete inputs, float32, uint32 y uint16 |
| 08 · Gráficas en vivo | Dos ejes, curvas ocultables, zoom, seguimiento y CSV |
| 09 · Histórico diario | Consulta de varios días en una gráfica |
| 10 · Alarmas y ACK | Nivel alto/bajo, fallo digital, retorno antes de ACK |
| 11 · Eventos y retorno | Transiciones, ocurrencias, filtros y CSV |
| 12 · Scripts y tareas | Inicio, tarea periódica, apertura de pantalla, script de botón y lista de acciones |

Para tener histórico en la pantalla 09, ejecuta una vez con Runtime cerrado `.venv\Scripts\python tools/seed_showcase_history.py`: crea datos **sintéticos** de 12:00 a 13:00 UTC de ayer y anteayer.

## Direcciones

| Variable | S7 | | Variable | Modbus |
| --- | --- | --- | --- | --- |
| Siemens.Bomba1.Marcha | %DB1.DBX0.0 | | Modbus.Habilitar | coils[0] |
| Siemens.Bomba1.Caudal | %DB1.DBD4 | | Modbus.Listo | discrete_inputs[0] |
| Siemens.Bomba1.Consigna | %DB1.DBD8 | | Modbus.Consigna | holding_registers[0..1] float32 |
| Siemens.Nivel | %DB1.DBD12 | | Modbus.Temperatura | input_registers[0..1] float32 |
| Siemens.Bomba2.Marcha | %DB1.DBX16.0 | | Modbus.Contador | input_registers[2..3] uint32 |
| Siemens.Bomba2.Caudal / Consigna | %DB1.DBD20 / DBD24 | | Modbus.Modo | holding_registers[2] uint16 |

Modbus usa offsets base 0 y orden big endian (ABCD).

## Librerías

Para practicar la publicación: abre **Librerías → Proyecto**, publica `unidad` con **Proyecto → Importar librería externa… → Publicar biblioteca…** en un archivo nuevo y vincúlalo desde otro proyecto con **Vincular…**. Véase [Librerías](../../docs/STUDIO.md#librerías).

Copia limpia: `tools/build_showcase.py --output <carpeta>`. Pruebas: `tests/test_showcase.py`.
