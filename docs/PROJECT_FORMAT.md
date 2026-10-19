# Formato de proyecto v1

Un proyecto es una carpeta de documentos JSON en UTF-8. Studio los escribe al guardar; también se pueden editar a mano y validar con `python -m abscada <carpeta> --validate`.

```text
mi-proyecto/
  MiPlanta.abscada        manifiesto
  types.json              tipos de estructura
  variables.json
  connections.json
  screens/<nombre>.json   pantallas y layouts
  faceplates/<nombre>.json objetos de librería del proyecto
  assets/                 imágenes
  scripts/<nombre>.py
  automation.json         eventos y tareas de scripts
  alarms.json  historian.json  trends.json  alarm_views.json
  libraries.json          librerías vinculadas
  security.json  users.json  secrets.json  opcua_server.json
  pki/                    certificados OPC UA
  runtime/                históricos y auditoría (no se versiona)
```

Los documentos opcionales que faltan se cargan vacíos. Los nombres de pantallas, faceplates y scripts son los de sus archivos sin extensión; usa letras, números, `-` y `_`. Abrir un proyecto no modifica nada hasta guardar.

## Manifiesto

`<nombre>.abscada` (se admite `project.json` por compatibilidad):

```json
{"schema_version": 1, "name": "Planta", "startup_screen": "main",
 "languages": ["es", "en"], "default_language": "es", "initial_language": "project",
 "screen_defaults": {"width": 1280, "height": 720}}
```

| Clave | Contenido |
| --- | --- |
| `startup_screen` | Pantalla o layout inicial de Runtime |
| `languages`, `default_language`, `initial_language` | Véase [Idiomas](#idiomas) |
| `screen_defaults` | Tamaño propuesto para pantallas nuevas (1–10000); no cambia las existentes |
| `display` | Monitores; véase [Monitores](#monitores) |
| `library_folders` | Carpetas vacías de la librería del proyecto |

## Tipos y variables

`types.json` define estructuras con campos primitivos (`bool`, `int`, `float`, `string`) u otras estructuras, sin ciclos. No hay arrays.

```json
{"Pump": {"running": "bool", "flow": "float", "setpoint": "float"}}
```

`variables.json`:

```json
[
  {"name": "Level", "type": "float", "initial": 0.0, "writable": false,
   "binding": {"connection": "plc", "address": "%DB1.DBD12"}},
  {"name": "Pump1", "type": "Pump",
   "initial": {"running": false, "flow": 0.0, "setpoint": 60.0},
   "writable": true,
   "overrides": {"flow": {"writable": false}},
   "bindings": {
     "Pump1.running": {"connection": "plc", "address": "%DB1.DBX0.0"},
     "Pump1.flow": {"connection": "plc", "address": "%DB1.DBD4"}
   }}
]
```

- Los nombres raíz no llevan puntos. Las hojas se nombran con la ruta completa (`Pump1.flow`).
- En una estructura, `initial` contiene exactamente los campos del tipo; `bindings` usa nombres completos y `overrides` rutas relativas.
- `writable` es `false` por defecto y los campos lo heredan salvo override. Un campo sin enlace es una variable interna.
- No se admiten NaN, infinitos ni enteros con decimales.

## Conexiones y enlaces

```json
[
  {"id": "plc", "protocol": "s7", "host": "192.168.1.10", "rack": 0, "slot": 1, "port": 102, "poll_ms": 250},
  {"id": "meter", "protocol": "modbus_tcp", "host": "192.168.1.20", "port": 502, "unit_id": 1, "timeout_ms": 1000, "poll_ms": 100},
  {"id": "bus", "protocol": "modbus_rtu", "transport": "serial", "port": "COM3", "baudrate": 19200, "bytesize": 8,
   "parity": "E", "stopbits": 1, "timeout_ms": 300, "single_register": "fc16", "gap_ms": 0, "poll_ms": 500},
  {"id": "scale", "protocol": "serial_ascii", "transport": "tcp", "host": "192.168.1.30", "tcp_port": 4001,
   "framing": "terminator", "terminator": "\\r\\n", "encoding": "ascii", "suffix": "\\r\\n",
   "on_connect": "O1", "on_close": "O0", "stale_ms": 3000, "timeout_ms": 1000, "poll_ms": 200}
]
```

`id` es único y estable. `protocol` es `s7`, `modbus_tcp`, `modbus_rtu`, `serial_ascii`, `ads` u `opcua`. `poll_ms` va de 50 a 60000. Las conexiones serie guardan todos los campos del medio (`transport` `serial` o `tcp`, `port`, `baudrate`, `bytesize`, `parity` N/E/O/M/S, `stopbits`, `host`, `tcp_port`), aunque solo use los suyos. Los textos de `serial_ascii` guardan los escapes tal cual se escriben (`\r\n`).

Un enlace guarda la conexión, la versión del formato de enlace y una dirección propia de cada protocolo:

```json
{"connection": "plc", "version": 1, "address": {"db": 2, "offset": 4, "encoding": "float32"}}
{"connection": "meter", "version": 1,
 "address": {"area": "holding_registers", "offset": 0, "encoding": "float32", "byte_order": "big", "word_order": "little"}}
```

- **S7**: `db`, `offset` en bytes, `encoding` (bool, uint8, int16, int32, float32) y `bit` solo para bool. También se acepta el texto `%DB1.DBD4`; al editar se guarda la forma estructurada.
- **Modbus**: `area` (coils, discrete_inputs, holding_registers, input_registers), `offset` 0–65535, `encoding` y, en registros multipalabra, `byte_order` y `word_order` (big/little).
- **Modbus RTU**: `unit_id` (esclavo 1–247) y los mismos campos que Modbus.
- **Serie / TCP en bruto**: `function` (`rx` y `request` para string, `count` para int, `send` para string escribible) y `command` en `request`.
- **ADS** y **OPC UA**: véase [PROTOCOLS.md](PROTOCOLS.md).

Un enlace sin `version` es versión 1; las versiones desconocidas se rechazan.

## Pantallas

```json
{"width": 1000, "height": 650, "title": "General", "background": "#dde1e4",
 "grid_size": 10, "show_grid": true, "snap_to_grid": true,
 "elements": [
   {"id": "level", "kind": "text", "x": 20, "y": 20, "w": 180, "h": 45,
    "text": "Nivel", "tag": "Level", "unit": "%", "decimals": 2}
 ]}
```

El orden de `elements` es el orden de dibujo. Cada elemento tiene `id` único en el documento, `kind` y geometría `x`, `y`, `w`, `h`.

| kind | Propiedades principales |
| --- | --- |
| `text` | `text`, `tag` opcional, `unit`, `decimals` |
| `lamp` | `tag` bool, `lamp_colors` (`on`, `off`, `bad`) |
| `button` | `text` y acción; véase [Botones y acciones](#botones-y-acciones) |
| `input` | `text`, `tag`, `unit`; doble clic para escribir en Runtime |
| `bar` | `tag` numérico, `min`, `max` |
| `gauge` | `tag`, `min`, `max`, `gauge_style` (dial, semi, thermometer), `warning`, `alarm` ≥ `warning` |
| `text_list` | `tag`, `texts`, `default_text`; véase [Listas de textos](#listas-de-textos) |
| `image` | `source`: ruta relativa dentro del proyecto |
| `line`, `polyline`, `pipe` | `points`, `stroke_color`, `stroke_width` (1–100), `stroke_style` (solid, dash, dot), `arrows` (none, start, end, both) |
| `rectangle`, `ellipse` | `color` (relleno), `filled`, `stroke_color`, `stroke_width`, `stroke_style` |
| `faceplate` | `template`, `bindings` |
| `trend`, `alarm_view` | `view`; mínimo 400 × 280, solo en pantallas |
| `screen_container` | `screen`; véase [Layouts](#layouts) |

`points` son pares normalizados entre 0 y 1 dentro de la caja del elemento: una línea tiene 2 y los demás trazados, de 2 a 1000.

```json
{"id": "supply", "kind": "pipe", "x": 100, "y": 100, "w": 300, "h": 150,
 "points": [[0,0],[1,0],[1,1]], "stroke_width": 14, "stroke_color": "#7c94a5", "arrows": "end"}
```

**Apariencia común**: `font_size` (8–72), `color`, `text_color`, `border_color`, `bold`, `text_align` (left, center, right), `tooltip`. Los colores son `#RRGGBB` o `#AARRGGBB`.

**Solo diseño**: `editor_hidden`, `editor_locked`, `group` y `description` afectan solo a Studio. `visible: false` oculta el elemento en Runtime.

Las imágenes deben estar dentro de la carpeta del proyecto; no se incrustan en el JSON ni se cargan de la red.

## Botones y acciones

| `action` | Campos | Efecto |
| --- | --- | --- |
| `toggle` | `tag` bool | Invierte el valor |
| `set` | `tag`, `value` | Escribe el valor |
| `momentary` | `tag` bool | `true` al pulsar, `false` al soltar |
| `press_release` | `tag`, `press_value`, `release_value` | Escribe un valor al pulsar y otro al soltar |
| `screen` | `screen`, `target_container` | Navega |
| `popup` | `screen`, `modal`, `window` | Abre una pantalla emergente |
| `faceplate_popup` | `template`, `bindings`, `title`, `modal`, `window` | Abre un objeto de librería en su ventana |
| `close_popup` | — | Cierra la emergente que contiene el botón |
| `script` | `script` | Ejecuta un script |
| `set_language` | `language` | Cambia el idioma de Runtime |
| `sequence` | `actions` | Lista de acciones |

`toggle` y `set` actúan al soltar dentro del botón. `momentary` y `press_release` no son funciones de seguridad: una caída de red puede impedir enviar la liberación. `permission` exige un permiso concreto; sin él, los botones que escriben o ejecutan scripts piden `operate` y la navegación no pide nada.

**Lista de acciones.** Hasta 20 acciones con los mismos campos que una acción simple; el botón no lleva `tag`. Admite `set`, `toggle`, `script`, `set_language`, `screen`, `popup`, `faceplate_popup` y `close_popup`. Abrir o cerrar pantallas solo puede ser la última.

```json
{"id": "arranque", "kind": "button", "text": "Arrancar", "action": "sequence",
 "actions": [{"action": "set", "tag": "Bomba1.consigna", "value": 50.0},
             {"action": "toggle", "tag": "Bomba1.marcha"},
             {"action": "script", "script": "registrar_arranque"},
             {"action": "screen", "screen": "detalle"}]}
```

Al soltar se comprueban todas las acciones; si alguna no es posible, no se envía ninguna. Después se envían en orden sin esperar: las escrituras a una misma conexión salen en ese orden, pero entre conexiones distintas no hay orden garantizado, y las escrituras de un script salen cuando este termina. Si una falla al enviarse, las anteriores no se deshacen y las siguientes no se envían. El permiso se comprueba una vez y cada escritura se audita por separado.

**Emergentes.** El título y el tamaño salen de la pantalla o del faceplate de destino. `faceplate_popup` abre una ventana por plantilla y conjunto de variables; pulsar otra vez trae la existente al frente. Dentro de un faceplate, `"bindings": {"running": "$running"}` reenvía sus parámetros.

```json
{"kind": "button", "action": "faceplate_popup", "template": "pump_detail",
 "bindings": {"running": "Pump1.running", "flow": "Pump1.flow"},
 "title": "Bomba 1", "window": {"monitor": 2, "mode": "normal", "on_top": true}}
```

`window` (opcional en `popup` y `faceplate_popup`): `monitor` 1–16, numerados de izquierda a derecha (si no existe, se usa el principal); `mode` normal, maximized o fullscreen; `on_top`.

## Condiciones y estados

```json
"dynamics": {
  "visible": {"tag": "Pump1.running", "op": "eq", "value": true, "bad": false},
  "states": [{"when": {"tag": "Level", "op": "ge", "value": 90}, "style": {"color": "#c0392b"}}],
  "default": {}, "bad": {"color": "#f0a020"}, "disabled": {}, "disabled_reason": "Sin permiso"
}
```

`visible` y `enabled` son condiciones; `op` es `eq`, `ne`, `gt`, `ge`, `lt` o `le` (las ordenadas solo con números) y `bad` es el resultado sin calidad válida. En `states` gana la primera condición que se cumple. Las condiciones admiten `$parametro` dentro de faceplates.

## Listas de textos

```json
{"id": "estado", "kind": "text_list", "x": 20, "y": 20, "w": 220, "h": 40, "tag": "Pump1.running",
 "texts": [{"value": "0", "text": "Parada"}, {"value": "1", "text": "En marcha"}],
 "default_text": "Desconocido"}
```

Los valores se guardan como texto y se comparan según el tipo de la variable. `default_text` (por defecto `—`) se usa si no hay coincidencia; con calidad mala siempre se muestra `—`.

## Objetos de librería

`faceplates/<nombre>.json` es una plantilla con parámetros primitivos que sus elementos usan como `$nombre`. `folder` la coloca en una carpeta de la librería. Las plantillas `estandar__*` son de la librería estándar y nunca se guardan en el proyecto.

```json
{"width": 320, "height": 180, "folder": "Bombas",
 "parameters": {"running": "bool"},
 "elements": [{"id": "pilot", "kind": "lamp", "x": 10, "y": 10, "w": 40, "h": 40, "tag": "$running"}]}
```

```json
{"id": "pump1", "kind": "faceplate", "x": 30, "y": 100, "w": 320, "h": 180,
 "template": "pump", "bindings": {"running": "Pump1.running"}}
```

Cada instancia enlaza todos los parámetros con variables del mismo tipo (escribibles si la plantilla escribe). No se admiten objetos anidados, visores ni contenedores dentro de una plantilla.

## Layouts

Un layout es una pantalla con elementos `screen_container`:

```json
{"width": 1200, "height": 730, "elements": [
  {"id": "cabecera", "kind": "screen_container", "x": 0, "y": 0, "w": 1200, "h": 90, "screen": "cabecera"},
  {"id": "contenido", "kind": "screen_container", "x": 0, "y": 90, "w": 1200, "h": 640, "screen": "general"}
]}
```

Un botón navega en una zona con `"action": "screen", "screen": "historico", "target_container": "contenido"`. Sin `target_container` navega en la zona actual; `__window__` sustituye la ventana completa. Una pantalla alojada no puede contener contenedores.

## Monitores

```json
"display": {
  "main": {"monitor": 1, "mode": "maximized", "scale": "fit"},
  "windows": [{"screen": "alarmas", "monitor": 2, "mode": "fullscreen", "on_top": false}]
}
```

`main` coloca la ventana principal; cada entrada de `windows` abre otra al arrancar. `scale` es `fit` (mantener proporciones), `stretch` o `none` (tamaño real con barras de desplazamiento). Sin `display` se abre la principal maximizada. Las posiciones que deja el operador se guardan en sus preferencias, no en el proyecto.

## Alarmas, registros y visores

```json
{"retention_days": 365,
 "categories": [{"id": "proceso", "name": "Proceso", "color": "#c0392b"}],
 "items": [{"id": "nivel_alto", "message": "Nivel alto", "tag": "Level", "category": "proceso",
            "condition": "high", "threshold": 80, "hysteresis": 3, "priority": 800,
            "on_delay_ms": 500, "off_delay_ms": 300, "ack_required": true, "enabled": true}]}
```

- `alarms.json`: arriba. `condition` es `true` o `false` para bool, `high`, `low`, `equal` o `not_equal` para números, y `bad_quality` (sin datos válidos) para cualquier tipo simple; prioridad hasta 1000.
- `historian.json`: `retention_days` y `files`, cada uno con `id`, `name`, `interval_ms` y `variables`. Una variable solo puede estar en un fichero. Los ID tienen 1–64 caracteres ASCII (letras, números, `_`, `-`).
- `trends.json`: visores con `title`, `window_seconds`, `axes` (`id`, `title`, `side`, `auto`, `min`, `max`, `visible`) y `curves` (`id`, `tag`, `axis`, `color`, `width`, `visible`).
- `alarm_views.json`: visores con `title`, `categories`, `min_priority`, `mode`, `allow_ack` y `columns`.

```json
{"retention_days": 90, "files": [
  {"id": "process", "name": "Proceso", "interval_ms": 1000, "variables": ["Level", "Pump1.flow"]}]}
```

Los datos se guardan en `runtime/records/<id>/AAAA-MM-DD.sqlite3`, por día UTC.

## Scripts

`automation.json`:

```json
{"startup": ["startup"], "timeout_seconds": 10,
 "tasks": [{"id": "quality", "script": "check_quality", "interval_ms": 5000, "enabled": true}],
 "folders": ["Proceso/Bombas"], "script_folders": {"arranque": "Proceso/Bombas"},
 "limits": {"lector_bascula": null, "informe": 60}}
```

Una pantalla añade `"on_open": ["screen_open"]` y un botón `"action": "script", "script": "nombre"`. `folders` y `script_folders` solo organizan Studio. `limits` es opcional: segundos propios de un script (0,1–86400) o `null` para que no tenga límite; los que no aparecen usan `timeout_seconds`. Las referencias se validan al guardar y al arrancar. Véase [SCRIPTS.md](SCRIPTS.md).

## Usuarios y roles

`security.json` (solo se escribe si difiere del valor por defecto):

```json
{"enabled": true, "session_timeout_minutes": 15, "password_min_length": 10,
 "max_failed_logins": 5, "lockout_minutes": 5,
 "roles": [{"id": "operator", "name": "Operador", "permissions": ["operate", "acknowledge"]}]}
```

| Permiso | Permite |
| --- | --- |
| `operate` | Mandos, consignas y scripts de botón |
| `acknowledge` | Reconocer alarmas |
| `recipes` | Lo que tenga `"permission": "recipes"`; ningún control lo pide por defecto |
| `manage_users` | Gestionar cuentas |
| `opcua` | Iniciar sesión en el servidor OPC UA |

Con `enabled: false` (por defecto) todo está permitido.

- `users.json`: cuentas con nombre, roles, cambio obligatorio, desactivada y la huella scrypt de la contraseña. Studio las escribe al momento, sin esperar a Guardar, porque Runtime también las cambia.
- `secrets.json`: contraseñas de conexión (`connection:<id>:password`, valor `plain:<base64>`), **codificadas, no cifradas**.
- `pki/own`, `pki/trusted`, `pki/rejected`: certificados OPC UA.

Todo esto viaja y se versiona con el proyecto. Protégelo como información confidencial ([HARDENING.md](HARDENING.md)).

## Servidor OPC UA

`opcua_server.json`:

```json
{"enabled": true, "port": 4840, "security": ["Basic256Sha256_SignAndEncrypt"], "allow_anonymous": false}
```

Publica `opc.tcp://<equipo>:<port>/abscada`, namespace `urn:abscada:<proyecto>`, con un nodo `ns=<índice>;s=<variable>` por variable dentro de `Objects/abSCADA` y la calidad como StatusCode.

- Los clientes inician sesión con cuentas de abSCADA con permiso `opcua`; para escribir necesitan también `operate`. Sus escrituras son órdenes auditadas.
- El acceso anónimo, si `allow_anonymous` es true, es siempre de solo lectura.
- Políticas: `Basic256Sha256_SignAndEncrypt`, `Aes256_Sha256_RsaPss_SignAndEncrypt`, `Aes128_Sha256_RsaOaep_SignAndEncrypt`, `Basic256Sha256_Sign` y `None` (solo pruebas).

## Idiomas

Sin `languages`, el proyecto está en español. `default_language` debe estar declarado. `initial_language` es `project` (el de por defecto), `station` (el último elegido en el puesto) o `user` (la preferencia de la cuenta al iniciar sesión).

`text`, `title`, `message`, `default_text`, `disabled_reason`, `tooltip`, `description` y el `name` de las categorías de alarma admiten un texto o un mapa por idioma:

```json
{"id": "titulo", "kind": "text", "x": 10, "y": 10, "w": 300, "h": 40, "text": {"es": "Sala de cocción", "en": "Brewhouse"}}
```

El mapa debe contener el idioma por defecto. Una traducción ausente o vacía usa ese idioma. Identificadores, valores de listas, unidades y datos del PLC no se traducen. En el CSV de textos, los elementos y alarmas se identifican por `@id` y las filas de listas por `=valor`; los estados dinámicos, por posición.

## Librerías

Un paquete `.abscada-library.json` es autónomo:

```json
{"schema_version": 1, "name": "Equipos", "version": "1.0.0",
 "languages": ["es", "en"], "default_language": "es",
 "author": "Mi equipo", "license": "GPL-3.0-or-later",
 "faceplates": {"bomba": {"width": 100, "height": 60, "parameters": {}, "elements": []}},
 "assets": {}}
```

`assets` relaciona rutas relativas con su contenido en base64; se rechazan rutas absolutas, `..`, `:` y `\`. Las plantillas solo pueden depender de sus parámetros y recursos.

`libraries.json` vincula cada paquete por alias con su `source`, su `sha256` y una copia completa, así el proyecto funciona sin el archivo original. El alias empieza por letra y admite letras, números, `_` y `-` (hasta 40). Las plantillas se usan como `alias__nombre`. Una actualización exige el mismo `name`, una versión nueva si cambia el contenido y compatibilidad con todas las instancias.

```python
from abscada.project import Project
from abscada.faceplate_libraries import export_library, link
export_library(Project.load("autor"), ["bomba"], "equipos-1.0.0.abscada-library.json",
               "Equipos", "1.0.0", author="Mi equipo", license="GPL-3.0-or-later")
consumer = Project.load("consumidor")
link(consumer, "equipos-1.0.0.abscada-library.json", "equipos")
consumer.save()
```

`python tools/validate_library.py <paquete>` valida un paquete. No sobrescribas versiones ya distribuidas: publica un archivo nuevo.

## Compatibilidad

Se cargan sin cambios en disco y se guardan en el formato actual: el manifiesto `project.json`, los enlaces S7 de texto y sin `version`, las paletas `@nombre` (se convierten a HEX y se retira `palette`), la marca antigua `layout`, los registros por variable (pasan a `files`; sus históricos se siguen leyendo) y las cuentas, secretos y certificados de 0.5.0b2 en `runtime/` (se mueven a la raíz del proyecto la primera vez).

Antes de cambiar el formato, lee [DEVELOPMENT.md](DEVELOPMENT.md#cambiar-el-formato).
