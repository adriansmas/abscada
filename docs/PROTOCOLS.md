# Protocolos

Una **variable** es un dato del proyecto (nombre, tipo, valor inicial, acceso). Una **conexión** identifica un equipo y sus opciones de sesión. Un **enlace** une una variable a un dato de esa conexión. Las pantallas solo usan nombres de variable: cambiar de PLC o de protocolo no obliga a tocarlas.

| Protocolo | Conexión | Enlace |
| --- | --- | --- |
| Siemens S7 | Host, puerto, rack, slot, ciclo | DB, byte, bit para BOOL, codificación |
| Modbus TCP | Host, puerto, Unit ID, timeout, ciclo | Área, offset base 0, codificación, orden de bytes y registros |
| Modbus RTU | Puerto serie (o TCP a un conversor), baudios, paridad, timeout, ciclo | Esclavo, y lo mismo que Modbus TCP |
| Serie / TCP en bruto | Puerto serie o TCP, fin de trama, codificación, textos al conectar y desconectar | Función (última trama, contador, petición, envío) y comando |
| TwinCAT ADS | IP, puerto TCP 48898, AMS Net ID remoto y local, puerto ADS, timeout | Símbolo o grupo:offset, tipo PLC, longitud de STRING |
| OPC UA | Endpoint, política de seguridad, usuario, timeout | NodeId |

El tipo de la variable (`int`, `float`…) es distinto de la codificación en el equipo (INT16, REAL…), que decide el enlace. Los campos de una estructura pueden enlazarse a equipos o protocolos distintos. Formato JSON de cada enlace: [PROJECT_FORMAT.md](PROJECT_FORMAT.md#conexiones-y-enlaces).

## Adquisición

Cada conexión tiene su propio hilo, cliente y cola de escritura, de modo que un equipo lento o caído no afecta a los demás. `poll_ms` (50–60000) es un intervalo objetivo, no tiempo real: si una lectura tarda más, el siguiente ciclo empieza al terminar, sin solaparse.

Si una lectura falla, **toda la conexión** pasa a calidad *bad*, conserva los últimos valores, cierra el cliente y reconecta a los 2 s. Excepción: en Modbus RTU, un esclavo que no responde o devuelve una excepción solo pone en *bad* sus variables, y el resto del bus sigue leyéndose. Las escrituras pendientes de una conexión caída se descartan y no se repiten al reconectar.

S7 y Modbus RTU agrupan las lecturas; Modbus TCP, ADS y OPC UA leen cada variable por separado. La capacidad en número de equipos y variables todavía no se ha medido.

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

## Puerto serie

Modbus RTU y Serie/TCP en bruto usan `pyserial` (extra `serial`, incluido en el `.exe`). No necesita drivers propios, solo el del adaptador USB-RS232/485 si lo hay. El **medio** puede ser:

- **Puerto serie**: `COM3` en Windows o `/dev/ttyUSB0` en Linux, con baudios, bits de datos, paridad y bits de parada. También admite URL de pyserial (`loop://`, `rfc2217://host:puerto`).
- **TCP**: un conversor serie-Ethernet (Moxa, USR…) en modo *TCP server* transparente. IP y puerto TCP.

Un puerto serie solo lo puede abrir un programa: si está ocupado, la conexión queda en *bad* con el error del sistema.

### Modbus RTU

Maestro Modbus RTU con las mismas áreas, offsets base 0 y codificaciones que Modbus TCP. El **esclavo** (1-247) va en cada variable, porque un puerto atiende todo el bus RS-485.

- **Lecturas**: funciones 1-4, agrupando datos contiguos del mismo esclavo y área (hasta 125 registros o 2000 bits).
- **Escrituras**: función 5 para coils y 16 para registros. Con la opción «FC06» de la conexión, un dato de un solo registro se escribe con la 6.
- **Tramas**: respeta el silencio de 3,5 caracteres entre tramas y comprueba el CRC. *Pausa entre peticiones* añade más tiempo para equipos lentos.
- Sin broadcast (esclavo 0).

Cada esclavo que no responde cuesta su *timeout* en cada ciclo. Con varios esclavos caídos, baja el timeout o separa los buses.

### Serie / TCP en bruto

Para equipos que hablan por texto o tramas propias: básculas, lectores de códigos, medidores, displays. El conector **no interpreta nada**: corta tramas, entrega el texto y envía lo que se le pide. Entender la trama es trabajo del proyecto, normalmente un script.

**Conexión**:

- **Fin de trama**:
  - *Terminador*: `\r\n`, `\r`, `\x03`…
  - *Inicio y fin*: por ejemplo `\x02`…`\x03`.
  - *Longitud fija*.
  - *Silencio en la línea*: la trama termina cuando no llegan bytes durante X ms.

  Los delimitadores no forman parte de la trama y las tramas vacías se descartan.
- **Codificación**: ASCII, Latin-1, UTF-8 o *Hexadecimal*. En hexadecimal cada trama se muestra como `01 03 02 00 0A`, y lo que se envía se escribe en ese mismo formato.
- **Añadir a cada envío**: sufijo para todo lo que se envía, típicamente `\r\n`.
- **Enviar al conectar / al desconectar**: por ejemplo, la orden de transmisión continua y la de pararla. El texto de conexión se repite al reconectar.
- **Error si no llegan tramas en**: con un valor distinto de 0, si el equipo deja de emitir, la conexión pasa a *bad* y reconecta, con lo que reenvía el texto de conexión.

Los textos admiten escapes `\r`, `\n`, `\t` y `\xNN`.

**Funciones de enlace**:

| Función | Tipo | Valor |
| --- | --- | --- |
| Última trama recibida | string | La última trama completa, llegue cuando llegue |
| Tramas recibidas | int | Contador desde la conexión; cambia aunque la trama se repita |
| Petición y respuesta | string | En cada ciclo envía el comando y guarda la primera trama que llega antes del *timeout* |
| Enviar texto | string, escritura | Escribir la variable envía el texto (más el sufijo); leerla devuelve lo último enviado |

**Ejemplo: báscula KERN PNS** (1200 8N1, trama `+0075.55 G S`).

- **Conexión**: *Añadir a cada envío* `\r\n`, *Enviar al conectar* `O1` (transmisión continua) y *Enviar al desconectar* `O0`.
- **Variables**: `BasculaTrama` (Última trama recibida), `BasculaOrden` (Enviar texto, para `T` de tara) y dos internas, `Peso` y `Estable`.
- **Script**: sin límite de tiempo y en los eventos de inicio; rellena `Peso` y `Estable`:

```python
import re
while ctx.sleep(0.2):
    if ctx.quality('BasculaTrama') != 'good':
        continue
    m = re.match(r'\s*([+-])\s*([\d./]+)\s*(\w*)\s*([SUE])?', ctx.read('BasculaTrama'))
    if m and m.group(4) != 'E':
        valor = float(m.group(2).replace('/', ''))
        ctx.write('Peso', -valor if m.group(1) == '-' else valor)
        ctx.write('Estable', m.group(4) == 'S')
```

Para una báscula de consulta, enlaza `BasculaTrama` con *Petición y respuesta* y comando `O8`, y no envíes nada al conectar.

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

Las pruebas usan servidores TCP reales en localhost: `test_s7_integration.py` y `test_s7_reads.py` (S7), `test_modbus.py`, `test_ads.py` y `test_opcua.py`; los conectores serie, `test_serial.py`, contra equipos simulados por TCP y el puerto `loop://` de pyserial. **No se ha probado ningún PLC físico** ni el rendimiento con miles de variables.
