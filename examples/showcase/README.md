# Laboratorio SCADA

Proyecto de demostración editable: **21 pantallas, 33 variables agrupadas, 2 conexiones independientes, 1 faceplate local, 1 biblioteca con 2 plantillas, 3 registros, 3 gráficas, 6 alarmas y 5 scripts**. Incluye todos los tipos de controles gráficos y acciones de botón disponibles actualmente.

**Bibliotecas…** muestra el vínculo `equipos` a «Equipos de proceso 1.0.0». La unidad Siemens de la pantalla 05 usa `equipos__unidad`; la interna utiliza la plantilla local. También puedes insertar `equipos__valvula`. El proyecto editable de autoría está en `examples/library_author`; consulta [cómo publicar y actualizar](../../docs/FACEPLATE_LIBRARIES.md).

## Arranque

Desde la raíz del repositorio, en Windows:

```powershell
.\run.ps1 examples/showcase
```

O directamente con el entorno instalado:

```powershell
.venv\Scripts\python -m abscada examples/showcase
```

En Linux: `.venv/bin/python -m abscada examples/showcase`.

En Studio pulsa **Abrir runtime**. El layout `00_layout` conserva cabecera y menú mientras cambia el contenedor `contenido`. Todo el banco interno funciona sin equipos conectados. Las variables S7/Modbus muestran calidad de comunicación; no reciben valores locales de sustitución.

Para probar los protocolos sin PLC físico, abre otra terminal:

```powershell
.venv\Scripts\python tools/showcase_plcs.py
```

Este proceso independiente sirve **S7 TCP en 127.0.0.1:1102** y **Modbus TCP en 127.0.0.1:1502**. Ctrl+C lo detiene. Requiere los extras `s7,modbus` de instalación. Para comprobar la independencia de conexiones, ejecuta dos terminales con `--protocol s7` y `--protocol modbus` y detén solo una. Se pueden cambiar los puertos con `--s7-port` / `--modbus-port`; actualiza también Conexiones en Studio. No se inicia automáticamente al abrir el proyecto.

## Recorrido recomendado

| Menú | Qué comprobar |
|---|---|
| 01 · Recorrido | Accesos, ventana completa y ajustes modales. Volver restaura el layout. |
| 02 · Proceso interno | Marcha/paro, piloto, depósito, tuberías, barra de nivel y entradas numéricas/texto. Doble clic para editar. «Señal local» activa ondas escritas por la tarea Python; desactívala para introducir nivel manual. |
| 03 · Estados y mandos | Botones de marcha/paro superpuestos con visibilidad condicional; permiso que bloquea una orden; pulsador momentáneo; escritura 10 al pulsar y 0 al soltar; lista de textos para modos 0, 1, 2 y texto por defecto para 9. |
| 04 · Dibujo e imágenes | Línea con flechas, polilínea discontinua, tubería dinámica, rectángulo, elipse e imagen SVG que cambia con la marcha. En Studio prueba grupos, bloqueo y ocultación de diseño. |
| 05 · Faceplates y ventanas | Misma plantilla enlazada a variables internas y a S7. Ajustes no modales y ayuda modal; valores compartidos entre ventanas. |
| 06 · Siemens S7 | Dos bombas en DB1. Escribe consigna y pulsa marcha: el servidor externo actualiza el caudal. Nivel cíclico y calidad real de adquisición. |
| 07 · Modbus TCP | Cuatro áreas, bool, float32, uint32 y uint16. Activa coil 0: cambia discrete input 0 y la temperatura sigue la consigna con una oscilación. El contador crece cada segundo. Modo es un registro de lectura/escritura independiente. |
| 08 · Gráficas en vivo | Nivel/consigna en eje izquierdo, temperatura en derecho, marcha inicialmente oculta y eje ocultable. Zoom, seguimiento, selección de curvas/ejes y CSV. Abre la curva no registrada y la gráfica conjunta S7/Modbus. |
| 09 · Histórico diario | Selecciona Histórico, desmarca Seguir, establece el intervalo y pulsa Consultar. Lee archivos de varios días en una única gráfica. Preparación de datos antiguos más abajo. |
| 10 · Alarmas y ACK | Con señal local detenida, pulsa nivel alto, espera entrada, reconoce e introduce operador/comentario si procede, luego nivel normal. Prueba también fallo digital y retorno antes de ACK. |
| 11 · Eventos y retorno | Consulta transiciones; «Ver ocurrencias» muestra entrada, retorno y reconocimiento de cada ocurrencia. Filtros, periodo y exportación CSV. |
| 12 · Scripts y tareas | Fecha de inicio, contador periódico, aperturas de pantalla, script por botón y restablecimiento del banco interno. Las ejecuciones se consultan en Studio → Scripts y tareas. |

La variable `Sistema.Operador` es una etiqueta demostrativa editable; **no representa autenticación ni cambia automáticamente el actor introducido al reconocer alarmas**.

## Variables y comunicaciones

`Local` contiene mandos y valores internos. `Sistema` contiene el estado de sesión y resultados de scripts. `Siemens` contiene una estructura con dos estructuras Bomba. `Modbus` reúne el equipo de registros. Las estructuras se expanden en la tabla de variables; cada hoja conserva su acceso, enlace y registro.

**S7_Laboratorio:** adquisición 250 ms, rack 0, slot 1. REAL de 32 bits, big endian.

| Variable | Dirección | Acceso |
|---|---|---|
| Siemens.Bomba1.Marcha | %DB1.DBX0.0 | Lectura/escritura |
| Siemens.Bomba1.Caudal | %DB1.DBD4 | Lectura |
| Siemens.Bomba1.Consigna | %DB1.DBD8 | Lectura/escritura |
| Siemens.Nivel | %DB1.DBD12 | Lectura |
| Siemens.Bomba2.Marcha | %DB1.DBX16.0 | Lectura/escritura |
| Siemens.Bomba2.Caudal | %DB1.DBD20 | Lectura |
| Siemens.Bomba2.Consigna | %DB1.DBD24 | Lectura/escritura |

**Modbus_Laboratorio:** adquisición 500 ms, Unit ID 1, timeout 800 ms. Offsets **base 0**, bytes/registros big endian (ABCD). La dirección es un objeto con área, offset y codificación, no una cadena S7.

| Variable | Área y offset | Formato | Acceso |
|---|---|---|---|
| Modbus.Habilitar | coils[0] | bool | Lectura/escritura |
| Modbus.Listo | discrete_inputs[0] | bool | Lectura |
| Modbus.Consigna | holding_registers[0..1] | float32 | Lectura/escritura |
| Modbus.Temperatura | input_registers[0..1] | float32 | Lectura |
| Modbus.Contador | input_registers[2..3] | uint32 | Lectura |
| Modbus.Modo | holding_registers[2] | uint16 | Lectura/escritura |

Con un PLC físico, configura su host/puerto y adapta los enlaces a su programa. El servidor de laboratorio expone el mapa anterior; no es una emulación completa de CPU Siemens ni implementa conexión S7 segura. La prueba TCP de este ejemplo no sustituye la validación contra el equipo de destino.

## Registros e históricos

| Fichero lógico | Frecuencia | Variables |
|---|---|---|
| internas | 1 s | Nivel, Consigna, Temperatura y Marcha de Local |
| equipos | 2 s | Caudales y Nivel S7; Temperatura y Contador Modbus |
| estados | 5 s | Modo, Permiso y Fallo de Local |

Retención de muestras: 90 días. Cada variable pertenece a un solo registro o ninguno. `Local.SinRegistro` se dibuja en vivo y **no se archiva**. Las gráficas son configuraciones independientes del registro.

Ruta: `runtime/records/<fichero>/AAAA-MM-DD.sqlite3`. La rotación es por día **UTC**; los selectores de fecha del visor muestran hora local. Alarmas, eventos y auditoría se almacenan en `runtime/scada.sqlite3` (retención configurada de alarmas: 365 días).

Para disponer inmediatamente de histórico anterior, **con Runtime cerrado**:

```powershell
.venv\Scripts\python tools/seed_showcase_history.py
```

Genera una hora, 12:00–13:00 UTC, de ayer y anteayer, con cuatro variables **internas sintéticas** y frecuencia de 1 s. Imprime los días creados. Selecciona un intervalo que incluya ambos días en «Histórico diario»; el visor unifica los archivos. En Madrid durante horario de verano ese intervalo es 14:00–15:00 local. La herramienta deja constancia del origen sintético en la auditoría de cada archivo, no genera lecturas PLC y rechaza sobrescribir archivos existentes. No se incluyen bases de datos binarias precargadas en el proyecto.

## Alarmas y scripts

Alarmas de nivel alto (80) y bajo (15), fallo local, nivel S7 alto (80) y temperatura Modbus alta (65). Retardo de entrada 500 ms, retorno 300 ms, histéresis analógica 3. El aviso de modo manual (Modo = 1) no requiere ACK. Las categorías son filtros configurables del visor; no imponen secciones al Runtime.

| Fuente | Disparador | Efecto |
|---|---|---|
| scripts/startup.py | Inicio | Fecha de sesión y evento inicial |
| scripts/screen_open.py | Apertura de contenido/emergente | Contador y nombre de pantalla |
| scripts/periodic.py | Tarea cada 1 s | Reloj, contador, calidad de conexiones y señal local opcional |
| scripts/button_event.py | Botón | Contador propio de ejecuciones y mensaje |
| scripts/reset_local.py | Botón | Restablece mandos/valores internos y detiene señal local |

Los scripts no escriben PLCs. El estado de los contadores de scripts se reinicia con la sesión. El periodo de tarea se cuenta después de finalizar la ejecución; no es un planificador de tiempo real.

## Edición, guardado y reproducción

Selecciona pantallas desde el explorador de Studio; la plantilla está en Faceplates → unidad. Inspecciona dinámicas en Ajustes avanzados, paleta en su editor y enlaces en Variables. **Ctrl+S guarda el proyecto completo**. Versiones permite activar Git local; los datos de Runtime no forman parte del diseño. Haz una copia de esta carpeta para conservar tu variante.

Para generar otra copia limpia sin sobrescribir un proyecto existente:

```powershell
.venv\Scripts\python tools/build_showcase.py --output examples/mi_laboratorio
```

Las pruebas de `tests/test_showcase.py` comprueban cobertura de controles/acciones, reproducción del proyecto, scripts, lectura/escritura S7 y Modbus por TCP, independencia ante desconexión e histórico entre días. `tools/capture_showcase.py` genera capturas de todas las pantallas completas sin iniciar adquisición ni escribir datos en este proyecto.
