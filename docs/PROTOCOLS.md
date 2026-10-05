# Conexiones, enlaces y extensión de protocolos

## Separación de responsabilidades

Una variable es un dato del proyecto: nombre, tipo lógico, valor inicial y acceso. Una conexión identifica un destino y contiene sus opciones de sesión. Un enlace identifica un dato de ese destino y su representación en el protocolo. Pantallas y faceplates referencian nombres SCADA; no contienen DB, registros, NodeIds ni símbolos de PLC.

| Protocolo | Configuración de conexión | Configuración del enlace | Estado |
| --- | --- | --- | --- |
| S7 | Host, puerto TCP, rack, slot, ciclo | DB, byte, bit para BOOL, codificación | Implementado |
| Modbus TCP | Host, puerto TCP, Unit ID, timeout, ciclo | Área, offset base 0, codificación, orden de bytes y registros | Implementado |
| OPC UA | Endpoint, política de seguridad, certificado y referencia a credenciales | Namespace URI, identificador del nodo y atributo | Diseño pendiente de implementar |
| TwinCAT ADS | IP, puerto TCP 48898, AMS Net ID remoto/local, puerto ADS (851/801), timeout | Símbolo o index group:offset, tipo PLC, longitud de STRING | Implementado (lectura cíclica, sin notificaciones) |

Esta tabla expresa configuraciones diferentes, no un formulario universal de dirección. Los tipos lógicos `int`/`float` son distintos de los tipos de transporte INT16/UINT32/REAL, etc. La codificación la decide el enlace. Una estructura SCADA puede enlazar sus campos a equipos o protocolos diferentes.

## Extensión implementada

Cada adaptador publica una `ProtocolDefinition`, independiente de Qt y de las dependencias de red:

- Campos de conexión y campos de enlace, con tipos, límites, opciones y etiquetas.
- Normalización, validación del enlace y resumen legible para la tabla.
- Versión del enlace, independiente de la versión del proyecto.

`ProtocolForm` genera controles a partir de estos metadatos. `BindingEditor` cambia el formulario al seleccionar conexión y conserva un borrador por conexión. La validación del proyecto delega en la definición registrada. El runtime selecciona el adaptador y le entrega el enlace; no interpreta DB, áreas Modbus o símbolos.

Para añadir un protocolo:

1. Crear un módulo con definición y adaptador (`connect`, `read`, `write`, `close`). Las librerías de red se importan al conectar, no al abrir Studio.
2. Registrar mediante `register("protocol_id", Adapter)`. El adaptador debe publicar `definition`. El registro rechazará IDs duplicados o definiciones ausentes.
3. Añadir la dependencia como extra opcional, pruebas del esquema y pruebas de integración contra un servidor externo.
4. Si cambia el formato de enlace, aumentar su versión y añadir una migración probada. No reutilizar una versión para formatos incompatibles.

No hay descubrimiento automático de paquetes externos todavía: la composición registra los módulos explícitamente. Una prueba registra un protocolo ficticio de símbolos y verifica validación, guardado, recarga y generación del formulario sin cambiar Project ni el editor. Ese protocolo solo existe durante la prueba; no aparece en el producto.

## Adquisición independiente

El runtime crea un trabajador por conexión. Cada trabajador posee un cliente, una cola de escritura y un reloj monotónico. `poll_ms` establece su intervalo objetivo. Los clientes nunca se comparten entre trabajadores. Fallos, reintentos y órdenes de un equipo no se ejecutan en el trabajador de otro.

La agenda se calcula desde el comienzo del ciclo; si una lectura tarda más que el intervalo, el siguiente ciclo puede empezar inmediatamente al terminar. No existe garantía de tiempo real ni se lanzan lecturas solapadas. Tras un fallo se cierra el cliente y se espera dos segundos antes de reconectar. Las escrituras pendientes de una conexión no disponible se descartan; no se reproducen al reconectar. Detener señala a todos los trabajadores y espera su salida; los timeouts de la biblioteca determinan cuánto puede tardar una operación ya iniciada.

Actualmente hay lecturas individuales dentro de cada conexión. Para miles de variables se necesitan planes de lectura agrupada, medición de tiempos, presupuestos de carga y calidad stale. Un hilo por conexión es apropiado para un número moderado de equipos; miles de conexiones requerirían un ejecutor asíncrono o un servicio independiente. El número de equipos y variables que admite el sistema aún no se ha medido.

## OPC UA y ADS: adquisición futura

No basta con implementar `read` para afirmar que están resueltos. Ambos tienen funciones de notificación y gestión de sesión que deben conservarse:

- En OPC UA, persistir Namespace URI e identificador del nodo, resolviendo el índice de namespace al conectar. Incorporar descubrimiento de nodos, certificados, políticas de seguridad y credenciales referenciadas desde un almacén seguro. No guardar contraseñas en los documentos del proyecto.
- En ADS, diferenciar IP, AMS Net ID y puerto ADS; gestionar rutas, resolución de símbolos, handles y su invalidación al cambiar el programa PLC.
- Añadir una estrategia de adquisición de suscripción/notificaciones además del polling. Cada conexión mantendrá su ciclo configurado: intervalo de muestreo/publicación en la estrategia de suscripción y ciclo de lectura en polling.
- Ampliar el contrato de muestras para preservar calidad y timestamp del servidor, junto con timestamp de recepción. La implementación actual genera calidad y timestamp en el runtime.
- Añadir interfaces opcionales de exploración/importación y lectura por lotes. Estos controles necesitan editores específicos —árbol de nodos, selector de símbolos, certificados—, no únicamente los campos sencillos que genera `ProtocolForm`.

La frontera estable es variable → enlace → protocolo y muestras → runtime. El contrato de transporte actual es síncrono y admite polling; habrá que ampliarlo para las suscripciones. Las pantallas y variables no tendrán que introducir campos de OPC UA o ADS.

## TwinCAT ADS implementado

`ads.py` implementa AMS/TCP directamente sobre un socket. No depende de `pyads` ni de `TcAdsDll.dll`, así que funciona igual en Windows y Linux sin instalar TwinCAT. El PLC debe tener una ruta estática hacia el AMS Net ID del SCADA (por defecto, IP local + `.1.1`). Al conectar se comprueba que el runtime está en RUN (`ReadState`).

- **Acceso por símbolo.** Se obtiene un handle con `ReadWrite` en el grupo `0xF003` y se lee o escribe por `0xF005`. Los handles se guardan en caché por conexión, sin distinguir mayúsculas. Si el PLC responde *símbolo no encontrado* o *versión de símbolos no válida*, por ejemplo tras una descarga del programa, el handle se pide de nuevo una vez. Al cerrar se liberan con `0xF006`.
- **Acceso por dirección.** `grupo:offset`, por ejemplo `0x4020:0` para %MB0 o `0xF030:4` para %QB4.
- **Tipos.** De BOOL a LREAL y STRING(n), codificados en little endian y cp1252.
- **Errores.** Los códigos ADS se traducen a mensajes legibles. Como en S7 y Modbus, un fallo de lectura marca la conexión entera como *bad* y reconecta a los 2 s.

`ads_simulator.py` es un servidor AMS/TCP en Python puro con tabla de símbolos, handles, áreas %M/%I/%Q y estado del PLC. Lo usan las pruebas y el ejemplo `examples/beckhoff`.

Pendiente: notificaciones ADS (*device notifications*), lecturas agrupadas (*sum commands*, grupo `0xF080`), WSTRING, arrays completos, tipos de fecha y exploración de la tabla de símbolos desde Studio.

## Modbus implementado

Coils y discrete inputs son bits; holding registers e input registers son registros de 16 bits. Se admiten codificaciones uint16/int16/uint32/int32/float32/float64 y orden configurable para datos multirregistro. Las áreas de entrada rechazan escritura tanto al validar el proyecto como en el adaptador. Los offsets son base 0: una referencia documental holding register 40001 corresponde al offset 0, pero deben comprobarse las convenciones del equipo. No se implementan todavía cadenas, arrays ni extracción de bits de registros.

## Referencias primarias

- [Modbus Application Protocol V1.1b3](https://www.modbus.org/file/secure/modbusprotocolspecification.pdf): áreas, funciones y direccionamiento.
- [pyModbusTCP Client](https://pymodbustcp.readthedocs.io/en/stable/package/class_ModbusClient.html): cliente TCP, Unit ID y operaciones.
- [OPC UA NodeId](https://reference.opcfoundation.org/specs/OPC-10000-3/8.2): namespace e identificadores.
- [OPC UA Services](https://reference.opcfoundation.org/specs/OPC-10000-4/5): sesiones, suscripciones y monitored items.
- [Beckhoff ADS device identification](https://infosys.beckhoff.com/content/1033/tc3_ads_intro/116159883.html): AMS Net ID y puerto ADS.
- [Beckhoff AMS Header](https://infosys.beckhoff.com/content/1033/tcadscommon/12440283915.html): identificación y operaciones ADS.
