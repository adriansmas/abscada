# Validación de Studio 0.2

Fecha: 4 de octubre de 2026.

## Entorno local

Windows x64, Python 3.14.3, PySide6 6.11.2, python-snap7 3.2.0, pyModbusTCP 0.3.0 y pytest 9.1.1. Instalación editable del paquete y extras completada.

## Resultado

**254 pruebas superadas** en la batería completa (86,23 segundos), incluidas 36 pruebas de aceptación de la revisión Fernando. Incluye integración TCP S7 y GUI Qt sin pantalla. El comando de validación acepta `examples/demo`, `examples/s7` y `examples/plant`. La ejecución headless utiliza adaptadores S7 o Modbus TCP según el proyecto. Las pruebas y capturas arrancan un servidor TCP de desarrollo en un puerto efímero.

La [revisión transversal del 4 de octubre](AUDIT_2026-10-04.md) documenta los fallos corregidos y los límites pendientes. Se regeneraron las capturas con `tools/capture_visual_editor.py` y se inspeccionaron el editor con propiedades de pantalla y el runtime con layout. Se mantiene la separación entre diseño y operación.

Las pruebas de interfaz comprueban clic en la caja de herramientas, arrastrar/soltar, redimensionado real con ratón, cambios de propiedades, persistencia, duplicado/eliminación, deshacer/rehacer y formularios sin JSON. Runtime abre otra ventana, contiene solo operación y escribe mediante un botón de su escena. Se verifica el cierre del trabajador y la reapertura con los nuevos cambios. La copia de Runtime no cambia al editar en Studio. Una comparación de imágenes comprueba que la adquisición no modifica el lienzo de diseño. También se verifica navegar a una plantilla de faceplate sin cambiar el runtime activo.

La integración S7 usa el cliente y servidor reales de python-snap7 sobre TCP localhost; lee la consigna, escribe un REAL y un bit y comprueba su lectura posterior. La prueba de codificación con memoria también cubre INT/DINT negativos y conservación de bits vecinos.

Las pruebas de fallos cubren conexión inicial fallida, marcado bad de tags asociados, descarte de una escritura offline y posterior reconexión. La persistencia se valida mediante roundtrip a una carpeta temporal y comparación de variables y elementos expandidos.

## Revisión visual

Se renderizan la ventana del editor y la del runtime con `tools/capture_demo.py`, y se inspeccionan `docs/editor.png` y `docs/runtime.png`. Se revisaron separación entre ventanas, caja de herramientas, inspector, placeholders sin valores y ajuste del lienzo. La captura editor-runtime-active.png muestra Studio durante la ejecución sin valores en vivo.

## Pendiente

Linux, ejecución del workflow remoto, PLC físico, CPUs concretas, comunicación cifrada, instaladores, benchmark de adquisición, carga sostenida y validación operacional en instalaciones reales. Las pruebas actuales no acreditan capacidad industrial ni comportamiento de seguridad funcional.

## Ajustes de densidad, estructuras y S7

Verificados paneles compactos, visibilidad de las siete herramientas, ocultación automática del inspector, grupos de variables colapsados, filtrado de campos y agrupación anidada. Una prueba de formulario enlaza `Pump1.flow` a otro PLC y a `%DB3.DBD8` sin cambiar los campos vecinos. Se prueba guardar/recargar estos enlaces. La integración TCP S7 utiliza `%DB1.DBX0.0` y `%DB1.DBD8`. Las pruebas también cubren DBW, DBD como entero/REAL, DBB, sintaxis anterior y direcciones inválidas. Las capturas variables.png y connections.png muestran las vistas actualizadas.

## Eliminación de simulación interna y textos de ayuda

El registro productivo contiene S7 y Modbus TCP. La prueba de PLC no disponible verifica calidad bad y conservación del valor inicial, sin generación de valores. La interfaz de variables no contiene el banner explicativo de variable local; se comprueban los nombres de campo reales. Se eliminaron subtítulos de ayuda, instrucciones de edición y mensajes redundantes de ventana abierta. Las dos demos utilizan el mismo DB1 por TCP.

## Protocolos y ciclos independientes

El conjunto completo termina con 90 pruebas correctas. Se prueban enlaces S7 estructurados y compatibilidad con sus direcciones anteriores. Un protocolo de símbolos registrado exclusivamente en la prueba comprueba que el proyecto y el generador de formularios se amplían mediante metadatos.

Modbus TCP se prueba contra el servidor real de pyModbusTCP en localhost: lectura de las cuatro áreas, escritura de coils y holding registers, seis codificaciones numéricas y cuatro combinaciones de orden de bytes/registros. Se comprueba el contenido físico de los registros y la lectura posterior. También se validan áreas de solo lectura, codificaciones incompatibles, offsets inválidos y datos que exceden el área.

Un runtime adquiere simultáneamente S7 y Modbus TCP, escribe un UINT32, detecta la caída del servidor Modbus y mantiene buenas las lecturas S7. Una prueba con una conexión deliberadamente bloqueada verifica al menos cinco ciclos de otra conexión antes de liberar la primera; al detener, todos los trabajadores terminan.

Las pruebas Qt comprueban que el primer clic y arrastre sobre un elemento no seleccionado solo seleccionan, sin movimiento, snap ni entrada en el historial. Un segundo clic simple tampoco cambia la posición; un arrastre posterior mueve y puede deshacerse. Se crean conexiones Modbus y enlaces desde formularios, se comprueban campos específicos y conservación del borrador al cambiar entre conexiones. Las capturas binding-s7.png y binding-modbus.png fueron inspeccionadas.

Estas pruebas no sustituyen benchmarks con miles de variables ni validación contra equipos físicos. OPC UA y TwinCAT ADS siguen pendientes.

## Operación persistente 0.4

135 pruebas correctas en Windows/Python 3.14.3. Se prueban histéresis high/low, retardos de entrada/salida, calidad inválida, ACK idempotente, retorno antes del ACK, reactivación con una ocurrencia pendiente, recuperación tras reinicio, retención que protege activas/no reconocidas, bloqueo de escritor, esquema SQLite y backup online con datos en WAL.

Se prueba registro cíclico y por cambio/banda muerta, preservación de transiciones de calidad, reducción de 12000 registros conservando extremos/fechas y mala calidad, exportación de 6000 muestras originales, integración de alarmas/históricos con S7 TCP, formularios y undo/redo, configuración de curvas/ejes, visores incrustados, ACK desde Qt, estilos y huecos de mala calidad.

Las capturas reproducibles de tools/capture_product.py utilizan un servidor externo Snap7 con puerto efímero y un archivo de datos temporal. Se inspeccionaron studio-alarms.png, studio-historian.png, trend-configuration.png, runtime-trends.png y runtime-alarms.png. Se corrigió un rango inicial degenerado del eje temporal de Qt y se verificaron sus etiquetas de hora en la captura actualizada. La adquisición no genera valores dentro de la aplicación.

No se han ejecutado pruebas remotas Linux/Windows del workflow, validación contra PLC físico, pruebas de alimentación/disco lleno ni benchmarks de carga industrial. Los nombres de operador del ACK son texto, sin autenticación.


## Registros independientes y particiones diarias

La suite incluye pertenencia única, movimiento y desasignación desde la tabla con undo; IDs portables; ciclos independientes de ficheros; fecha común para sus variables; rotación UTC con commit del día anterior; retención de días completos; lectura y gráfica de días anteriores; conservación de datos al cambiar de registro y compatibilidad de históricos anteriores. El catálogo evita consultar registros ajenos a la variable.

Las pruebas Qt verifican una gráfica en tiempo real sin servicio de registro ni SQLite, inserción de controles sin configuraciones previas, Runtime sin pestañas automáticas y navegación programada sin escritura PLC. La nueva creación atómica de particiones impide consultar un SQLite antes de que tenga tablas.

Se regeneraron y revisaron studio-variable-recording.png, studio-historian.png y runtime-trends.png mediante el servidor S7 externo de tools/capture_product.py. La validación del proyecto examples/plant pasa. Estas comprobaciones no sustituyen ensayos de carga, pérdida de alimentación y aceptación en equipos físicos.


## Editor visual — 3 de octubre de 2026

148 pruebas correctas en Windows/Python 3.14.3. La ampliación verifica propiedades de pantalla y persistencia, fondo/título en runtime, trazado ortogonal con ratón, cancelación, deshacer por trazado completo, primer clic sin desplazamiento, edición de vértices, hit testing de tuberías, estilos y flechas, orden de capas, alineación, tiradores, geometría inválida, edición de texto con Suprimir y fondo de faceplates expandido.

Se inspeccionaron editor-screen-properties.png, editor-pipe-properties.png y runtime-process-design.png generadas con tools/capture_visual_editor.py y un servidor S7 TCP externo. Se corrigieron huecos de selección en tiradores por la regla de relleno del contorno. Las ventanas se destruyen explícitamente al cerrarse en Qt; la suite completa pasa tras esa corrección.

La comprobación de frecuencias de registro compara intervalos observados y frecuencia relativa; no exige un cociente exacto de muestras en tiempo de pared, que depende de planificación y confirmaciones de disco. Sigue verificando ciclos distintos y el intervalo mínimo configurado.

## Ventanas emergentes

Siete pruebas nuevas comprueban apertura y cierre mediante clic real, escritura compartida, varias ventanas, reutilización, modalidad, navegación local, cierre del runtime, cancelación de acciones pendientes, configuración persistente con deshacer/rehacer y validación de referencias. Una prueba usa TCP S7: escribe desde la emergente y confirma la lectura en ambas ventanas, luego cierra la emergente y vuelve a escribir desde la principal. Suite completa: 155 pruebas, 47,46 segundos.

## Listas de textos

14 pruebas nuevas cubren correspondencias enteras, decimales, booleanas y cadenas, valor por defecto, calidad inválida, vista de edición sin valores, duplicados equivalentes, valores incompatibles, configuración desde el inspector, persistencia, deshacer/rehacer, actualización desde runtime y expansión en faceplates. Suite completa: 169 pruebas, 48,69 segundos. Captura del ejemplo en runtime-popup-settings.png.

## Layouts y contenedores

Diez pruebas comprueban navegación desde una cabecera con clic real, conservación de zonas hermanas, escritura y muestras compartidas, emergentes desde una zona, navegación local o de ventana completa, formularios, guardado/deshacer, creación de layouts y contenedores, referencias inválidas, rechazo de anidamiento y destrucción de gráficas/alarmas al cambiar de pantalla. La suite también incluye la regresión de la etiqueta huérfana del inspector. Resultado: 180 pruebas, 50,95 segundos. examples/plant pasa --validate. Se inspeccionaron editor-layout.png y runtime-layout.png; tools/capture_visual_editor.py reproduce ambas capturas.

## Scripts, flujo de proyecto y Git

Resultado final: 195 pruebas, 69,64 segundos. Se comprueban inicio, tareas activas/desactivadas, estado entre ejecuciones, excepciones sin aplicar escrituras, timeout de bucle infinito, cancelación al parar, eventos de pantalla y emergentes, botones dentro de contenedores y errores visibles en runtime independiente. La integración S7 verifica escritura desde Python, lectura posterior y rechazo de una secuencia que contiene una variable de solo lectura.

Las pruebas de proyecto cubren creación con título y dimensiones, guardado único, fuentes Python, deshacer y guardar después de un guardado anterior, rollback ante fallo de E/S, retirada de fuentes eliminadas y rechazo de cambios externos. Git se prueba en repositorios temporales: commits iniciales/sucesivos, ausencia de versiones vacías, eliminación de archivos y exclusión de runtime y staging ajeno. No se envía nada a remotos.

Se inspeccionaron editor-automation.png y new-screen-dialog.png. La captura se reproduce con tools/capture_visual_editor.py. compileall y la validación de examples/plant terminan correctamente. La prueba de timeout concede dos segundos al proceso Python para incluir su arranque bajo carga en Windows; sigue comprobando que un bucle infinito se cancela y el servicio continúa.

Límites de esta revisión: pruebas locales en Windows y Qt offscreen; no sustituye validación en Linux, instalación industrial, pruebas prolongadas de carga o pérdida de alimentación. El guardado restaura ante errores de E/S pero no es una transacción multarchivo resistente a cortes de energía. Los scripts no se ejecutan en una sandbox de permisos.


## Informe Fernando — ingeniería visual

Implementados los 16 puntos del informe; trazabilidad en [FERNANDO_REVIEW_RESOLUTION.md](FERNANDO_REVIEW_RESOLUTION.md). Las 36 pruebas nuevas cubren formularios que conservan el borrador, números con coma, booleanos, estructuras anidadas y duplicado sin enlaces heredados; condiciones y apariencia con paleta; selección compatible, edición común y grupos; previsualización sin Runtime y layouts con condiciones; momentos de pulsación/liberación, pérdida de permiso/calidad/foco, navegación y liberación mediante S7 antes del cierre. Las capturas se regeneran con `tools/capture_review_fixes.py`; se revisaron inspector a 1366×768, estructura y previsualización con mala calidad. La suite y ese script aíslan QSettings para no cambiar las preferencias del usuario.


## Faceplates emergentes y varios monitores

`tests/test_operation_windows.py` (25 pruebas) cubre la validación de faceplates emergentes (plantilla, parámetros completos, tipos, `$parámetros` desconocidos, variables de solo lectura en parámetros escritos, opciones de ventana) y de `display`. También comprueba la resolución de `$parámetros` al expandir instancias, el título por defecto y, con clics reales en Qt offscreen, una ventana por equipo con runtime compartido, escritura desde el detalle sin afectar al otro equipo, cierre individual, reutilización tras navegar, memoria de posición, ventanas de arranque con monitor inexistente, inspector (incluidos los `$parámetros` dentro de un faceplate) y el diálogo Monitores con deshacer. Suite completa: 311 pruebas correctas; las 2 pruebas de Git fallan en un equipo sin `git` instalado.

En `examples/hydro`, con los PLC simulados por TCP: Mando… de cada ficha abre una ventana por grupo; ARRANCAR en la de G2 arranca G2 sin afectar a G1 en carga; las bombas de auxiliares abren su detalle con el título del equipo; ⧉ Monitor 2 abre la ventana de alarmas maximizada y sus pestañas navegan dentro de ella sin cambiar la principal.

Límite: Qt offscreen tiene un único monitor. La colocación en varios monitores físicos, el modo pantalla completa por monitor y «siempre encima» deben comprobarse en un puesto real.