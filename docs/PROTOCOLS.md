# Protocolos

Una **variable** es un dato del proyecto (nombre, tipo, valor inicial, acceso). Una **conexión** identifica un equipo y sus opciones de sesión. Un **enlace** une una variable a un dato de esa conexión. Las pantallas solo usan nombres de variable: cambiar de PLC o de protocolo no obliga a tocarlas.

| Protocolo | Conexión | Enlace |
| --- | --- | --- |
| Siemens S7 | Host, puerto, rack, slot, ciclo | DB, byte, bit para BOOL, codificación |
| Modbus TCP | Host, puerto, Unit ID, timeout, ciclo | Área, offset base 0, codificación, orden de bytes y registros |
| TwinCAT ADS | IP, puerto TCP 48898, AMS Net ID remoto y local, puerto ADS, timeout | Símbolo o grupo:offset, tipo PLC, longitud de STRING |
| OPC UA | Endpoint, política de seguridad, usuario, timeout | NodeId |

El tipo de la variable (`int`, `float`…) es distinto de la codificación en el equipo (INT16, REAL…), que decide el enlace. Los campos de una estructura pueden enlazarse a equipos o protocolos distintos. Formato JSON de cada enlace: [PROJECT_FORMAT.md](PROJECT_FORMAT.md#conexiones-y-enlaces).

## Adquisición

Cada conexión tiene su propio hilo, cliente y cola de escritura, de modo que un equipo lento o caído no afecta a los demás. `poll_ms` (50–60000) es un intervalo objetivo, no tiempo real: si una lectura tarda más, el siguiente ciclo empieza al terminar, sin solaparse.

Si una lectura falla, **toda la conexión** pasa a calidad *bad*, conserva los últimos valores, cierra el cliente y reconecta a los 2 s. Las escrituras pendientes de una conexión caída se descartan y no se repiten al reconectar.

S7 agrupa las lecturas; Modbus, ADS y OPC UA leen cada variable por separado. La capacidad en número de equipos y variables todavía no se ha medido.

## Siemens S7

Usa `python-snap7` 3.2 (extra `s7`) con `db_read`/`db_write`: comunicación S7 clásica, **sin cifrado ni autenticación**.

| Dirección | Tipo | Formato |
| --- | --- | --- |
| `%DB1.DBX0.0` | bool | Bit 0 del byte 0 |
| `%DB1.DBB1` | int | Byte sin signo |
| `%DB1.DBW2` | int | Entero de 16 bits con signo |
| `%DB1.DBD4` | int | Entero de 32 bits con signo (DINT) |
| `%DB1.DBD8` | float | REAL de 32 bits |

Todo en big endian. En DBD, el tipo de la variable decide entre DINT y REAL. El `%` es opcional y no distingue mayúsculas; también se aceptan las formas antiguas `DB1.X0.0`, `DB1.W2`, `DB1.D4` y `DB1.R8`. No hay strings, arrays, áreas M/I/Q, acceso simbólico ni DB optimizados.

Escribir un bit lee el byte, cambia el bit y lo escribe. Otro cliente puede cambiar ese byte entretanto: reserva bytes de mando o usa un handshake en el PLC.

**Lecturas agrupadas.** Al conectar, las variables se agrupan por DB en bloques de bytes contiguos (sin leer huecos) y cada ciclo hace una petición por bloque. El bloque máximo es el PDU negociado menos 18 bytes (462 con PDU 480). Si un bloque devuelve menos bytes, falla la conexión entera como cualquier otra lectura. En localhost, 134 variables pasaron de 134 peticiones y 59 ms a 2 peticiones y 1 ms por ciclo; no indica el rendimiento con un PLC real.

**PLC real.** Edita IP, rack, slot y puerto en **Conexiones**. En S7-1200/1500 hay que habilitar PUT/GET y usar DB no optimizados; con DB optimizados, usa el servidor OPC UA de la CPU.

**Simulador.** `abscada --simulador s7 --port 1102` sirve `examples/demo`:

| Dirección | Significado |
| --- | --- |
| `%DB1.DBX0.0` / `%DB1.DBX16.0` | Marcha bomba 1 / 2 |
| `%DB1.DBD4` / `%DB1.DBD20` | Caudal bomba 1 / 2 (la consigna si está en marcha) |
| `%DB1.DBD8` / `%DB1.DBD24` | Consigna bomba 1 / 2 |
| `%DB1.DBD12` | Nivel del depósito, onda simulada |

No es una CPU Siemens: sirve para probar el adaptador de punta a punta.

## Modbus TCP

Usa `pyModbusTCP` (extra `modbus`). Coils y discrete inputs son bits; holding e input registers, registros de 16 bits. Codificaciones uint16, int16, uint32, int32, float32 y float64, con orden de bytes y de registros configurable. Los offsets son **base 0**: el holding register documentado como 40001 es el offset 0. Las áreas de entrada no admiten escritura. No hay cadenas, arrays ni bits dentro de registros.

## TwinCAT ADS

`ads.py` implementa AMS/TCP directamente: no necesita `pyads`, `TcAdsDll.dll` ni TwinCAT en el puesto SCADA. El PLC debe tener una ruta estática hacia el AMS Net ID del SCADA (por defecto, su IP + `.1.1`) y estar en RUN. Paso a paso: [ejemplo Beckhoff](../examples/beckhoff/README.md#conectar-un-plc-real).

- **Por símbolo**: `MAIN.rVelocidad`, `GVL.aMotores[2].bMarcha`. No distingue mayúsculas. Los handles se guardan en caché y se piden de nuevo si el PLC cambia de programa.
- **Por dirección**: `grupo:offset`, por ejemplo `0x4020:0` (%MB0), `0xF020:4` (%IB4) o `0xF030:4` (%QB4).
- **Tipos**: BOOL, SINT, USINT, BYTE, INT, UINT, WORD, DINT, UDINT, DWORD, LINT, ULINT, REAL, LREAL y STRING(n) (80 por defecto), en little endian y cp1252. Las estructuras del PLC se enlazan campo a campo.
- **Puerto ADS**: 851 en TwinCAT 3 y 801 en TwinCAT 2.

Sin notificaciones ADS, lecturas agrupadas, WSTRING, arrays completos ni tipos de fecha. ADS no tiene autenticación ni cifrado. El simulador (`abscada --simulador ads`) tiene tabla de símbolos, handles, áreas %M/%I/%Q y estado del PLC, pero no es un runtime TwinCAT.

## OPC UA

**Cliente** (extra `opcua`, `asyncua`). Lee y escribe el atributo Value por NodeId: `ns=3;s="DB_Motor"."Velocidad"`, `ns=2;i=1001` o `nsu=<URI>;s=Nivel`. La forma `nsu=` resuelve el namespace al conectar y sigue funcionando aunque el servidor reordene su tabla. Las escrituras usan el tipo del nodo y no envían marca de tiempo, porque muchos servidores, entre ellos la S7-1500, la rechazan.

- **Seguridad**: Basic256Sha256 con firma y cifrado por defecto. Aes256-Sha256-RsaPss, Aes128-Sha256-RsaOaep y «solo firma» son opcionales; «Sin seguridad», solo para pruebas.
- **Certificados**: cada proyecto crea el suyo en `pki/own` con el URI `urn:abscada:<carpeta>:client`. El certificado del servidor solo se acepta si está en `pki/trusted`: el primer intento lo deja en `pki/rejected` y falla mostrando su huella. Se acepta en **Proyecto → Certificados OPC UA**. Renombrar la carpeta del proyecto cambia el URI y genera un certificado nuevo que el PLC tendrá que aceptar otra vez.
- **Credenciales**: el usuario va en la conexión y la contraseña en `secrets.json` del proyecto, codificada pero **no cifrada** (botón **Contraseña…**).

Cada conexión lee por polling: aún no hay suscripciones ni explorador de nodos. El **servidor OPC UA** propio de abSCADA se describe en [PROJECT_FORMAT.md](PROJECT_FORMAT.md#servidor-opc-ua).

## Validación

Las pruebas usan servidores TCP reales en localhost: `test_s7_integration.py` y `test_s7_reads.py` (S7), `test_modbus.py`, `test_ads.py` y `test_opcua.py`. **No se ha probado ningún PLC físico** ni el rendimiento con miles de variables.
