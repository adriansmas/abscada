# Conexiones, enlaces y extensión de protocolos

## Separación de responsabilidades

Una variable es un dato del proyecto: nombre, tipo lógico, valor inicial y acceso. Una conexión identifica un destino y contiene sus opciones de sesión. Un enlace identifica un dato de ese destino y su representación en el protocolo. Pantallas y faceplates referencian nombres SCADA; no contienen DB, registros, NodeIds ni símbolos de PLC.

| Protocolo | Configuración de conexión | Configuración del enlace | Estado |
| --- | --- | --- | --- |
| S7 | Host, puerto TCP, rack, slot, ciclo | DB, byte, bit para BOOL, codificación | Implementado |
| Modbus TCP | Host, puerto TCP, Unit ID, timeout, ciclo | Área, offset base 0, codificación, orden de bytes y registros | Implementado |
| OPC UA | Endpoint, política de seguridad, usuario (contraseña en `secrets.json` del proyecto), timeout | NodeId (`ns=…;s=…` o `nsu=<URI>;s=…`) | Implementado (cliente con polling; servidor propio) |
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

## OPC UA y ADS: evolución de la adquisición

No basta con implementar `read` para afirmar que están resueltos. Ambos tienen funciones de notificación y gestión de sesión que deben conservarse:

- En OPC UA ya se resuelve el Namespace URI al conectar y se gestionan certificados y políticas. Las contraseñas viven en `secrets.json` del proyecto, codificadas pero no cifradas. Sigue pendiente el descubrimiento de nodos en Studio.
- En ADS, diferenciar IP, AMS Net ID y puerto ADS; gestionar rutas, resolución de símbolos, handles y su invalidación al cambiar el programa PLC.
- Añadir una estrategia de adquisición de suscripción/notificaciones además del polling. Cada conexión mantendrá su ciclo configurado: intervalo de muestreo/publicación en la estrategia de suscripción y ciclo de lectura en polling.
- Ampliar el contrato de muestras para preservar calidad y timestamp del servidor, junto con timestamp de recepción. La implementación actual genera calidad y timestamp en el runtime.
- Añadir interfaces opcionales de exploración/importación y lectura por lotes. Estos controles necesitan editores específicos —árbol de nodos, selector de símbolos, certificados—, no únicamente los campos sencillos que genera `ProtocolForm`.

La frontera estable es variable → enlace → protocolo y muestras → runtime. El contrato de transporte actual es síncrono y admite polling; habrá que ampliarlo para las suscripciones. Las pantallas y variables no tendrán que introducir campos de OPC UA o ADS.

## OPC UA implementado

**Cliente** (`opcua.py`, conector `opcua`, extra `.[opcua]` con `asyncua>=2.1`). Lee y escribe el atributo Value por NodeId. La forma `nsu=<URI>;…` resuelve el índice de namespace al conectar y sobrevive a servidores que reordenan su tabla. Cada trabajador tiene su propio bucle asyncio, sin hilos adicionales. La escritura usa el tipo de datos del nodo (leído una vez y guardado en caché) y no envía marcas de tiempo, porque muchos servidores, entre ellos el de la S7-1500, rechazan escrituras con timestamp.

- **Seguridad**: Basic256Sha256 con firma y cifrado por defecto. Aes256-Sha256-RsaPss, Aes128-Sha256-RsaOaep y «solo firma» son opcionales; «Sin seguridad» es solo para pruebas.
- **Certificados** (`pki.py`): cada proyecto crea el suyo en `pki/own` y lo lleva consigo, con el URI de aplicación `urn:abscada:<carpeta del proyecto>:client|server`. El del servidor solo se acepta si está en `pki/trusted`. El primer intento lo deja en `pki/rejected` y falla con su huella; se acepta en Proyecto → Certificados OPC UA o desde la conexión. Si se renombra la carpeta del proyecto, cambia el URI y se genera un certificado nuevo que el PLC tendrá que volver a aceptar.
- **Credenciales**: el usuario va en la conexión. La contraseña va en `secrets.json` del proyecto, codificada en base64 (no cifrada, porque el runtime tiene que enviarla), y se introduce con el botón Contraseña… de la conexión.

**Servidor** (`opcua_server.py`, configuración en `opcua_server.json`). Ver [PROJECT_FORMAT.md](PROJECT_FORMAT.md).

Pendiente: suscripciones (monitored items) en el cliente, lectura por lotes, explorador de nodos en Studio y límite de sesiones en el servidor.

Siemens S7-1200/1500 con DB optimizados: usar el servidor OPC UA integrado en la CPU (requiere su licencia de runtime). El conector S7 clásico sigue necesitando PUT/GET y DB no optimizados.

## TwinCAT ADS implementado

`ads.py` implementa AMS/TCP directamente sobre un socket, sin depender de `pyads`, `TcAdsDll.dll` ni TwinCAT en el puesto SCADA. Las pruebas locales se han ejecutado en Windows; falta validar otros sistemas y un PLC físico. El PLC debe tener una ruta estática hacia el AMS Net ID del SCADA (por defecto, IP local + `.1.1`). Al conectar se comprueba que el runtime está en RUN (`ReadState`).

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

## Comunicación Siemens S7

El adaptador v1 usa `python-snap7` 3.2 y operaciones `db_read`/`db_write`. Está aislado del editor y de las variables. Se instala mediante `pip install -e '.[s7]'`.

### Direcciones del adaptador

La conexión identifica el equipo (IP/rack/slot/puerto). Cada variable o campo de estructura selecciona esa conexión y su propia dirección DB. No existe un único DB asignado a un PLC.

| Dirección | Tipo de variable | Formato |
| --- | --- | --- |
| %DB1.DBX0.0 | bool | Bit 0 del byte 0 |
| %DB1.DBB1 | int | Byte sin signo, 8 bits |
| %DB1.DBW2 | int | Entero con signo de 16 bits, big-endian |
| %DB1.DBD4 | int | Entero con signo de 32 bits, big-endian |
| %DB1.DBD8 | float | IEEE 754 REAL de 32 bits, big-endian |

DBD indica anchura de 32 bits; el tipo de variable decide entre entero DINT y REAL. El prefijo `%` es opcional, las mayúsculas/minúsculas no afectan y se recortan espacios al principio/final. Para compatibilidad se conservan `DB1.X0.0`, `DB1.W2`, `DB1.D4` y `DB1.R8`; en la sintaxis antigua `R` indica REAL explícitamente.

DB >= 1, offsets >= 0, bit entre 0 y 7. Una escritura fuera de rango se rechaza durante la codificación. No se incluyen strings S7, arrays, áreas M/I/Q, acceso simbólico ni bloques optimizados.

La escritura de bit hace lectura-modificación-escritura del byte para preservar los bits vecinos. El trabajador serializa sus operaciones; un PLC u otro cliente puede cambiar ese byte entre la lectura y la escritura. Por tanto, reservar bytes de mando o implementar un handshake en el PLC antes de uso real.

### PLC de desarrollo

`python -m abscada.s7_simulator --port 1102` inicia un servidor TCP S7 local. El servidor no es una CPU Siemens ni simula todas sus restricciones. Es útil para comprobar la ruta completa del adaptador.

| Dirección | Significado |
| --- | --- |
| %DB1.DBX0.0 | Marcha bomba 1 |
| %DB1.DBD4 | Caudal bomba 1 (consigna si está en marcha; 0 si parada) |
| %DB1.DBD8 | Consigna bomba 1 (60 inicial) |
| %DB1.DBD12 | Nivel de depósito, onda simulada |
| %DB1.DBX16.0 | Marcha bomba 2 |
| %DB1.DBD20 | Caudal bomba 2 |
| %DB1.DBD24 | Consigna bomba 2 (45 inicial) |

`examples/s7` y `examples/demo` apuntan a localhost:1102 mediante Siemens S7 TCP. Ambos necesitan python-snap7 y un PLC o servidor S7 disponible. El SCADA no contiene un simulador interno.

### PLC físico

Editar `connections.json`: dirección IP, rack, slot y puerto. Estos valores dependen de la CPU y configuración; los valores del ejemplo no son universales. Asegurar que las direcciones y los tipos coincidan con el programa PLC. Para S7-1200/1500 con acceso clásico, la configuración del PLC puede requerir habilitar PUT/GET y usar DB no optimizados. Consultar el manual específico de la CPU y sus restricciones de acceso antes de cambiar la configuración.

Este adaptador usa comunicación S7 clásica, sin TLS ni autenticación PLC-HMI configurada. El cliente OPC UA cifrado ya está disponible como adaptador independiente para servidores compatibles; consulta [PROTOCOLS.md](PROTOCOLS.md). No añade cifrado a estas llamadas S7 clásicas.

Ante un fallo se conserva el último valor, se marca calidad bad, se cierra el adaptador y se reintenta después de dos segundos. Se rechazan escrituras cuando la conexión no está disponible. No hay replay automático de órdenes.

### Evidencia de validación

`tests/test_s7_integration.py` abre un servidor local en un puerto disponible y ejecuta el runtime con un cliente Snap7 real. Comprueba lectura, escritura REAL y escritura bool mediante TCP. `test_core.py` comprueba INT, DINT, endianness y conservación de bits con un cliente de memoria.

No se ha conectado un PLC Siemens físico. No se ha verificado acceso seguro, rendimiento con miles de tags, restricciones de CPUs concretas ni interferencia entre clientes. El tiempo de bloqueo de una llamada depende de la librería; el cierre espera hasta cinco segundos y mantiene el runtime referenciado si el trabajador sigue activo.

Referencia: [API oficial python-snap7](https://python-snap7.readthedocs.io/en/latest/API/client.html).
