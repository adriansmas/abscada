# Formato de proyecto v1

```text
mi-proyecto/
  MiPlanta.abscada
  types.json
  variables.json
  connections.json
  screens/
    main.json
  faceplates/
    pump.json
  assets/
    esquema.png
```

Todos los documentos usan UTF-8. El orden del array de elementos determina el orden de dibujo. Los nombres de pantalla y faceplate corresponden a sus archivos, sin extensión. Se recomienda usar letras, números, guiones y guiones bajos. `schema_version` se refiere al proyecto completo.

El manifiesto principal es `<nombre>.abscada`, también en JSON. Se admite `project.json` por compatibilidad. Abrir desde archivo o carpeta no modifica los archivos hasta guardar.

## Manifest

```json
{"schema_version": 1, "name": "Planta", "startup_screen": "main"}
```

El manifiesto admite `languages`, `default_language` e `initial_language`. Los textos pueden ser cadenas o mapas, como `"text":{"es":"Bomba","en":"Pump"}`. Véase [Idiomas del proyecto](STUDIO.md) para edición, CSV, validación y runtime.

`screen_defaults` puede contener `width` y `height`, enteros de 1 a 10000; propone el tamaño de pantallas nuevas (1280 × 720 por defecto). No cambia las existentes. `display` configura ventanas de operación, según la sección de monitores.

## Tipos

`types.json` es un objeto con definiciones de estructura. Tipos primitivos: `bool`, `int`, `float`, `string`. Los campos pueden usar otros tipos definidos, pero se prohíben ciclos. No hay arrays ni tipos numéricos de anchura explícita en v1. El tipo lógico SCADA se separa de la codificación en el equipo, definida por cada enlace.

```json
{"Pump": {"running": "bool", "flow": "float", "setpoint": "float"}}
```

## Variables

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
     "Pump1.flow": {"connection": "plc", "address": "%DB1.DBD4"},
     "Pump1.setpoint": {"connection": "plc", "address": "%DB1.DBD8"}
   }}
]
```

Los nombres de variables raíz no contienen puntos. Para estructuras, `initial` debe contener exactamente los campos del tipo. `bindings` usa nombres completos de campos; `overrides` usa rutas relativas (por ejemplo `motor.running`) y admite `writable`. Sin enlace, el campo es interno. `writable` es false por defecto y se hereda de la estructura salvo override.

Booleanos escritos desde texto aceptan `true`, `false`, `True`, `False`, `0` y `1`. No se aceptan enteros fraccionarios ni flotantes NaN o infinitos.

## Conexiones

```json
[
  {"id": "plc", "protocol": "s7", "host": "192.168.1.10", "rack": 0,
   "slot": 1, "port": 102, "poll_ms": 250}
]
```

`id` es estable y único. `protocol` elige el adaptador registrado. `poll_ms` admite 50 a 60000; es un intervalo objetivo, no una garantía de tiempo real. Los adaptadores disponibles son S7, Modbus TCP, TwinCAT ADS y OPC UA. La prueba sin PLC físico utiliza un servidor TCP externo y las mismas direcciones DB. No hay direcciones de simulación internas.

## Pantallas y gráficos

```json
{"width": 1000, "height": 650, "elements": [
  {"id": "level", "kind": "text", "x": 20, "y": 20, "w": 180, "h": 45,
   "text": "Nivel", "tag": "Level", "unit": "%", "decimals": 2}
]}
```

Cada elemento tiene identificador único en el documento, `kind` y geometría positiva `w`, `h`. `x`, `y` son coordenadas del documento. La vista ajusta inicialmente la escena a su área disponible. En Studio admite Ctrl+rueda para zoom y Encajar para restaurar la vista completa. Las propiedades adicionales son específicas del elemento.

| kind | Propiedades principales | Comportamiento |
| --- | --- | --- |
| text | text, tag opcional, unit, decimals, color | Texto fijo o valor leído |
| lamp | tag bool | Verde si true, apagado si false, ámbar si calidad mala |
| button | text, tag, action, value | `toggle` para bool; `set` envía value |
| input | text, tag, unit | Doble clic abre entrada de valor en runtime |
| bar | tag numérico, min, max | Fracción limitada al intervalo; ámbar si calidad mala |
| image | source | Archivo relativo dentro del proyecto |
| faceplate | template, bindings | Instancia de plantilla parametrizada |
| gauge | tag numérico, min, max, gauge_style, warning, alarm, text, unit, decimals, color | dial (240°), semi (180°) o thermometer; zonas superiores de aviso/alarma; alarm ≥ warning |
| text_list | tag, texts, default_text | Valor exacto → texto; admite traducciones |
| line / polyline / pipe | points, stroke_color, stroke_width, stroke_style, arrows | Trazados con 2 / 2–1000 / 2–1000 puntos |
| rectangle / ellipse | color, filled, stroke_color, stroke_width, stroke_style | Formas editables; sin radio de esquina configurable |
| trend / alarm_view | view | Visor solo en pantallas, caja mínima 400 × 280 |
| screen_container | screen | Zona con una pantalla sin otros contenedores |

Las acciones toggle/set se activan al soltar dentro del botón; momentary y press_release gestionan pulsación y liberación. La pérdida de red o alimentación puede impedir enviar una liberación: no sustituyen una función de seguridad del PLC. Los botones pueden invocar un script del proyecto mediante action=script; no se evalúan expresiones Python dentro de las propiedades gráficas.

| action | Campos y efecto |
| --- | --- |
| toggle | tag bool escribible; invierte el valor |
| set | tag escribible y value compatible; asigna |
| momentary | tag bool escribible; true al pulsar y false al soltar |
| press_release | tag escribible, press_value y release_value compatibles |
| screen | screen y target_container opcional; navega |
| popup | screen, modal y window opcionales; abre pantalla emergente |
| faceplate_popup | template, bindings, title, modal y window; abre un objeto por equipo |
| close_popup | Cierra la ventana emergente actual |
| script | script; invoca una fuente del proyecto |
| set_language | language declarado; cambia el idioma del runtime |

Las imágenes deben vivir dentro de la carpeta del proyecto; las rutas que escapan se rechazan. No se incrustan dentro del JSON. La aplicación no carga imágenes remotas.

## Faceplates (objetos de librería)

En Studio se llaman **objetos de librería** (ver [STUDIO.md](STUDIO.md)). Un objeto puede llevar `"folder": "Válvulas/Agua"` para ordenarlo en la librería del proyecto; las carpetas vacías se guardan en el manifiesto `.abscada` → `library_folders`. Las plantillas `estandar__*` pertenecen a la librería estándar de la aplicación y nunca se guardan en el proyecto.

```json
{"width": 320, "height": 180,
 "parameters": {"running": "bool"},
 "elements": [
   {"id": "pilot", "kind": "lamp", "x": 10, "y": 10, "w": 40, "h": 40, "tag": "$running"}
 ]}
```

Instancia en una pantalla:

```json
{"id": "pump1", "kind": "faceplate", "x": 30, "y": 100, "w": 320, "h": 180,
 "template": "pump", "bindings": {"running": "Pump1.running"}}
```

Se exige que estén enlazados todos los parámetros y coincidan los tipos. En este MVP los parámetros son variables primitivas; no hay parámetros gráficos, eventos ni estructuras como parámetro único.

## Propiedades visuales

`font_size` define tamaño de texto en píxeles del documento (entero de 8 a 72). `color`, `text_color` y `border_color` permiten configurar colores. El inspector expone tamaño, fondo, color de texto, borde, negrita y alineación para los controles de texto. Studio no escribe valores de runtime en archivos: un enlace se representa mediante un marcador, y Runtime resuelve su valor desde el almacén de muestras.

## Edición de estructuras y enlaces

Studio agrupa variables de estructura en un árbol desplegable. Los campos anidados conservan su jerarquía. Cada hoja mantiene un nombre completo como `Station1.pump.flow` en el dominio, aunque el árbol muestra `flow` bajo sus grupos. El botón Enlace permite modificar valor inicial, permiso y enlace por hoja. El formulario actualiza `initial`, `overrides` y `bindings` del documento existente sin aplanar ni duplicar la estructura. El DB pertenece a `binding.address`; una conexión puede leer varios DB.

## Enlaces estructurados por protocolo

El formulario guarda `binding.connection`, `binding.version=1` y `binding.address` como objeto específico del protocolo. El nombre `address` se conserva como clave del archivo por compatibilidad; no representa una cadena universal. El tipo SCADA y sus pantallas no cambian al sustituir un enlace.

```json
{"connection": "plc", "version": 1,
 "address": {"db": 2, "offset": 4, "encoding": "float32"}}
```

S7: `db`, `offset` en bytes, `encoding` (bool, uint8, int16, int32, float32), `bit` únicamente para bool. Los enlaces S7 de texto de las versiones anteriores siguen admitidos. Al editar un enlace se guarda la forma estructurada. Cargar un proyecto no lo modifica en disco.

```json
{"connection": "meter", "version": 1,
 "address": {"area": "holding_registers", "offset": 0,
             "encoding": "float32", "byte_order": "big", "word_order": "little"}}
```

Modbus TCP: áreas coils/discrete_inputs para bool y holding_registers/input_registers para números. Offset de 0 a 65535. Codificaciones uint16/int16/uint32/int32/float32/float64; bool para áreas de bits. Órdenes big/little para bytes dentro de cada registro y para secuencia de registros; no se incluyen en enlaces bool. Los datos multirregistro deben caber en el área. No se admiten escrituras a áreas de entrada.

```json
{"id": "meter", "protocol": "modbus_tcp", "host": "192.168.1.20",
 "port": 502, "unit_id": 1, "timeout_ms": 1000, "poll_ms": 100}
```

La versión del enlace pertenece a la definición del protocolo; las versiones desconocidas se rechazan. Los enlaces heredados sin `version` se consideran versión 1. La versión global del proyecto sigue siendo 1 porque esta extensión mantiene la lectura de todos los proyectos anteriores; las aplicaciones antiguas no pueden leer los nuevos objetos de enlace.

## Documentos operativos opcionales

Los proyectos anteriores sin estos archivos cargan con configuración vacía. Studio los guarda al guardar el proyecto. Los datos operativos no se incluyen en estos JSON.

- `alarms.json`: objeto `categories`, `items` y `retention_days`. Cada categoría tiene id/name/color; cada alarma tiene id/message/tag/category/condition/threshold/hysteresis/priority/ack_required/enabled/on_delay_ms/off_delay_ms.
- `historian.json`: `retention_days` y `files`. Cada fichero declara id/name/interval_ms/variables. Una variable puede aparecer en un único fichero o en ninguno. `interval_ms` se aplica a todas sus variables.
- `trends.json`: diccionario de visores con title/window_seconds/axes/curves. Ejes: id/title/side (left/right)/auto/min/max/visible. Curvas: id/tag/axis/color/width/visible.
- `alarm_views.json`: diccionario de visores con title/categories/min_priority/mode/allow_ack y columns opcional. Las claves de columna están en operational_config.ALARM_COLUMNS.

```json
{"width": 1200, "height": 700, "elements": [
  {"id": "trend", "kind": "trend", "view": "process", "x": 10, "y": 10, "w": 1180, "h": 680}
]}
```

`kind=alarm_view` referencia una entrada de alarm_views; `kind=trend`, una de trends. Ambas configuraciones deben existir. Los visores se añaden directamente en pantallas, con w≥400 y h≥280. No se guardan valores en vivo ni estado de consultas en el documento.

El ejemplo completo es examples/showcase. Véase OPERATIONS.md para las condiciones, unidades de tiempo, retención y semántica del ACK.


```json
{"retention_days": 90, "files": [
  {"id": "process", "name": "Proceso", "interval_ms": 1000,
   "variables": ["TankLevel", "Pump1.flow"]}
]}
```

Los IDs de registro son portables: 1–64 caracteres ASCII de letras, números, _ y -, sin nombres reservados Windows ni duplicados al ignorar mayúsculas. Los datos se particionan por día UTC en runtime/records/<id>/AAAA-MM-DD.sqlite3. El formato antiguo tags se convierte a files al cargar; sus históricos se siguen leyendo.

Un botón puede navegar con `action: "screen"` y `screen: "nombre"`. No requiere tag ni escribe al PLC. Runtime no añade controles automáticamente. Al insertar un visor en Studio se crea su configuración; Configurar… edita esa entrada. Mostrar curvas en tiempo real no implica registrar sus variables.


## Pantallas y dibujo vectorial

Propiedades opcionales del documento: title (texto), background (#RRGGBB), grid_size (entero 1–200), show_grid y snap_to_grid (booleanos). Valores por defecto: fondo blanco, paso 10 y ambas opciones activadas. La pantalla inicial se declara en el manifiesto `.abscada` → `startup_screen`.

Nuevos tipos: line, polyline, pipe, rectangle y ellipse. Los trazados guardan points como pares normalizados entre 0 y 1 dentro de x/y/w/h, para poder moverlos y escalarlos sin reescribir cada coordenada. El inspector expone coordenadas absolutas. Una línea tiene dos puntos; los demás trazados admiten 2–1000. Las líneas horizontales/verticales conservan una caja de al menos 1 px sin alterar su dirección.

```json
{"id":"supply","kind":"pipe","x":100,"y":100,"w":300,"h":150,
 "points":[[0,0],[1,0],[1,1]],"stroke_width":14,
 "stroke_color":"#7c94a5","stroke_style":"solid","arrows":"end"}
```

stroke_width: 1–100; stroke_style: solid/dash/dot; arrows: none/start/end/both. Formas: color como relleno, filled como booleano y stroke_color/stroke_width para el contorno. Texto: bold booleano y text_align left/center/right. El orden del array elements continúa definiendo las capas. El fondo explícito de un faceplate se conserva al expandirlo para runtime.

## Acciones de ventana en botones

Un botón puede incluir `"action": "popup", "screen": "pump_settings", "modal": false` para abrir una pantalla emergente. `screen` referencia una pantalla existente; `modal` es booleano y por defecto false. El título y tamaño inicial se toman de la pantalla destino.

`"action": "close_popup"` cierra la ventana emergente que contiene el botón. No requiere variable ni destino. `"action": "screen"` sigue navegando dentro de la ventana que contiene el botón.

### Faceplate emergente

```json
{"kind": "button", "action": "faceplate_popup", "template": "pump_detail",
 "bindings": {"running": "Pump1.running", "flow": "Pump1.flow"},
 "title": "Bomba 1", "modal": false, "window": {"monitor": 2, "on_top": true}}
```

Abre una instancia del faceplate `template` en una ventana propia, con las variables de `bindings`. Igual que en una instancia sobre pantalla, `bindings` asigna todos los parámetros del faceplate con variables del mismo tipo; si el faceplate escribe un parámetro, la variable debe ser escribible. El tamaño inicial es el del faceplate. `title` es opcional: por defecto se usa el título del faceplate (o su nombre) seguido de la parte común de las variables, por ejemplo «Detalle · Pump1».

Dentro de un faceplate, el botón puede reenviar sus propios parámetros con `"$nombre"` (`"bindings": {"running": "$running"}`). Así el símbolo de un equipo abre su detalle: cada instancia del símbolo abre la ventana de su propio equipo.

Hay una ventana por faceplate y equipo (plantilla + variables). Pulsar otra vez trae la existente al frente; equipos distintos abren ventanas distintas, ligeramente desplazadas para no superponerse.

`window` es opcional y vale también para `"action": "popup"`:

- `monitor` (1–16): abre la ventana en ese monitor. Los monitores se numeran de izquierda a derecha y, a igualdad, de arriba abajo. Si el equipo no tiene ese monitor se usa el principal y se registra un aviso. Sin `monitor`, la ventana se centra sobre la que la abre.
- `mode`: `normal` (por defecto), `maximized` o `fullscreen`, aplicado al abrir la ventana.
- `on_top` (booleano): siempre por encima de otras aplicaciones. Las emergentes siempre quedan por encima de la ventana principal del runtime.

Una emergente puede ser un layout con sus propios contenedores. Los botones de navegación con `target_container` buscan la zona en la ventana donde se pulsan, así que una pantalla con pestañas sigue funcionando dentro de la emergente sin cambiar la ventana principal (ejemplo: `05_ventana_alarmas` en `examples/hydro`).

## Monitores de operación

El manifiesto `.abscada` puede incluir `display` para colocar el runtime en varios monitores:

```json
"display": {
  "main": {"monitor": 1, "mode": "maximized"},
  "windows": [
    {"screen": "80_alarmas", "monitor": 2, "mode": "fullscreen"},
    {"screen": "10_general", "monitor": 3, "mode": "maximized", "on_top": false}
  ]
}
```

`main` coloca la ventana principal. Cada elemento de `windows` abre una ventana adicional al arrancar, con la pantalla indicada. `mode` admite `normal`, `maximized` o `fullscreen`. Todas las ventanas comparten el mismo runtime: no hay conexiones ni registros adicionales. Sin `display`, se abre una ventana principal maximizada. `main.scale` admite `fit` (mantener proporciones), `stretch` (ocupar la ventana) o `none` (tamaño del documento, con barras de desplazamiento).

La posición y el tamaño de cada ventana se recuerdan en las preferencias del usuario (QSettings), no en el proyecto, por carpeta de proyecto y por ventana; los faceplates emergentes se recuerdan por equipo. Si una ventana tiene monitor configurado y la posición recordada queda en otro, se respeta el monitor configurado.

## Lista de textos

```json
{"id":"estado","kind":"text_list","x":20,"y":20,"w":220,"h":40,
 "tag":"Pump1.running",
 "texts":[{"value":"0","text":"Parada"},{"value":"1","text":"En marcha"}],
 "default_text":"Desconocido","font_size":16,"text_align":"center"}
```

Los valores de `texts` se guardan como strings y se validan y comparan según el tipo de variable enlazada. `texts` puede estar vacío durante la configuración. `default_text` tiene por defecto —. La calidad inválida muestra — independientemente del texto por defecto. Admite los mismos atributos de apariencia de texto y enlaces `$parametro` en faceplates. La resolución vive en `text_lists.py`, sin dependencias Qt.

## Layouts

Se guardan en `screens/<nombre>.json` como pantallas normales con controles `screen_container`. No existe un tipo o grupo separado de layouts; la antigua marca `layout` se retira al cargar. Comparten dimensiones, fondo y elementos de una pantalla. `startup_screen` puede apuntar al layout. No cambia el formato de los proyectos anteriores.

```json
{"width":1200,"height":730,"elements":[
 {"id":"cabecera","kind":"screen_container","x":0,"y":0,"w":1200,"h":90,"screen":"common_header"},
 {"id":"contenido","kind":"screen_container","x":0,"y":90,"w":1200,"h":640,"screen":"process_design"}
]}
```

Un botón de navegación añade `"action":"screen", "screen":"history", "target_container":"contenido"`. La propiedad target_container vacía u omitida significa zona actual; `__window__` significa ventana completa. Los demás valores deben coincidir con un ID de contenedor definido en el proyecto; su disponibilidad se comprueba además en la ventana activa al navegar. El ID __window__ está reservado. No se permiten contenedores en faceplates ni pantallas con contenedores dentro de otros contenedores (tampoco navegación a un layout desde una zona). Estos controles no crean comunicaciones adicionales.

## Automatización y versiones

Las fuentes residen en scripts/<nombre>.py; automation.json define startup, timeout_seconds y tasks. Los eventos de pantalla se guardan en on_open. Ver [Scripts y tareas](OPERATIONS.md) para la API y [Guardado y versiones](STUDIO.md) para Git y el guardado conjunto.


## Usuarios y roles

`security.json` (opcional; solo se escribe si difiere del valor por defecto):

```json
{"enabled": true, "session_timeout_minutes": 15, "password_min_length": 10,
 "max_failed_logins": 5, "lockout_minutes": 5,
 "roles": [{"id": "operator", "name": "Operador", "permissions": ["operate", "acknowledge"]}]}
```

Permisos: `operate` (mandos, consignas y scripts de botón), `acknowledge` (reconocer alarmas), `recipes` (recetas y parámetros de proceso; ningún control lo pide por defecto, se asigna con `permission`), `manage_users` (gestionar cuentas) y `opcua` (iniciar sesión por OPC UA). Con `enabled: false`, el valor por defecto, todo está permitido como en versiones anteriores.

Las **cuentas forman parte del proyecto**: `users.json`, versionado y copiado con él. Cada cuenta guarda nombre, roles, «cambiar en el primer acceso», desactivada y la huella scrypt de su contraseña, nunca la contraseña. Se gestionan en Proyecto → Usuarios y roles → Cuentas y se escriben al momento, sin pasar por Guardar, porque el runtime también las cambia cuando un operador renueva su contraseña. Los intentos fallidos y los bloqueos solo existen en la memoria del runtime. Un proyecto de 0.5.0b2 con `runtime/users.json` pasa sus cuentas a `users.json` la primera vez que se usan.

Las **contraseñas de las conexiones** van en `secrets.json` (clave `connection:<id>:password`, valor `plain:<base64>`): codificadas, no cifradas, porque el runtime tiene que enviarlas al PLC. Se escriben al momento desde el botón Contraseña… de la conexión. Los **certificados OPC UA** van en `pki/` (`own`, `trusted`, `rejected`). Igual que las cuentas, viajan con el proyecto; los de 0.5.0b2 (`runtime/secrets.json` cifrado con DPAPI y `runtime/pki`) se mueven solos la primera vez.

Un botón o una entrada puede exigir un permiso concreto con `"permission": "manage_users"`. Sin esa propiedad, los controles que escriben y los scripts piden `operate`, y la navegación no pide nada.

## Servidor OPC UA

`opcua_server.json` (opcional):

```json
{"enabled": true, "port": 4840, "security": ["Basic256Sha256_SignAndEncrypt"], "allow_anonymous": false}
```

Endpoint `opc.tcp://<equipo>:<port>/abscada`, namespace `urn:abscada:<nombre del proyecto>`, una variable por tag con NodeId `ns=<índice>;s=<nombre del tag>` dentro de `Objects/abSCADA`, y la calidad como StatusCode.

- **Acceso**: los clientes inician sesión con cuentas de abSCADA con el permiso `opcua`; para escribir necesitan además `operate`.
- **Escrituras**: son órdenes auditadas que pasan por la cola de la conexión; el valor publicado cambia cuando el runtime lo observa.
- **Anónimo**: siempre de solo lectura, y solo si `allow_anonymous` es true.
- **Políticas** válidas: `Basic256Sha256_SignAndEncrypt`, `Aes256_Sha256_RsaPss_SignAndEncrypt`, `Aes128_Sha256_RsaOaep_SignAndEncrypt`, `Basic256Sha256_Sign` y `None` (solo pruebas).

## Condiciones y colores

Un elemento puede contener `dynamics.visible` y `dynamics.enabled` como `{ "tag": "Pump1.running", "op": "eq", "value": true, "bad": false }`. Los operadores son `eq`, `ne`, `gt`, `ge`, `lt`, `le`; las comparaciones ordenadas requieren números. `dynamics.states` es una lista ordenada de `{ "when": condición, "style": apariencia }`, donde gana la primera coincidencia. `default`, `bad` y `disabled` contienen apariencias; `disabled_reason` contiene el motivo visible en tooltip. Las propiedades de apariencia se validan según el objeto. `lamp_colors` define `on`, `off` y `bad`.

Los colores son valores explícitos `#RRGGBB` o `#AARRGGBB` (alfa al principio), en el fondo de cada documento, cada objeto y cada estado. Los nuevos documentos no admiten referencias `@nombre`. Al cargar un manifiesto antiguo con `palette`, se sustituyen sus referencias por el HEX correspondiente en pantallas y objetos de librería; el siguiente guardado retira `palette`. No se modifica ningún texto ni identificador que empiece por `@`. Una referencia de color sin definición se rechaza.

Las acciones `momentary` y `press_release` complementan a las existentes. La primera escribe true/false sobre bool; la segunda requiere `press_value` y `release_value` compatibles con la variable. No son acciones de seguridad del PLC.

`editor_hidden` y `editor_locked` solo afectan al diseño; `group` identifica un grupo plano y `description` da un nombre descriptivo en Elementos. `visible: false` oculta estáticamente en operación. Las condiciones admiten `$parámetro` en plantillas y se resuelven en cada instancia. La guía STUDIO.md describe precedencia y tratamiento de calidad.

## Idiomas y textos

El manifiesto declara `languages`, `default_language` e `initial_language` (project, station o user). Sin estos campos se considera español. El idioma por defecto debe estar declarado; se admiten variantes como en-GB.

```json
{"schema_version":1,"name":"Planta","startup_screen":"main",
 "languages":["es","en"],"default_language":"es","initial_language":"project"}
```

`text`, `title`, `message`, `default_text`, `disabled_reason`, `tooltip` y `description` admiten cadenas o mapas por idioma, incluidas apariencias dinámicas, listas, objetos de librería y ejes/curvas. Las categorías de alarma usan este formato en `name`. Cada mapa contiene el idioma por defecto y solo cadenas de idiomas declarados. Una traducción ausente o vacía utiliza el idioma por defecto; una cadena se muestra literalmente.

```json
{"id":"titulo","kind":"text","x":10,"y":10,"w":300,"h":40,
 "text":{"es":"Sala de cocción","en":"Brewhouse"}}
```

No se traducen identificadores, valores de listas, unidades ni datos adquiridos. Las rutas CSV identifican elementos y alarmas por `@id` y filas de listas por `=valor`; reordenarlos no cambia su identidad. Los estados dinámicos usan posición, por lo que conviene reexportar si se reorganizan.

Un botón cambia el idioma con `action: "set_language"` y `language: "en"`. Scripts usan `ctx.language` y `ctx.set_language()`. El idioma inicial project usa el predeterminado; station utiliza la elección guardada para el proyecto en el puesto; user aplica además la preferencia de cuenta al iniciar sesión. Una preferencia ausente o no declarada conserva el fallback. Todas las ventanas comparten el idioma sin reiniciar adquisición ni repetir eventos de apertura.

La preferencia de usuario se guarda junto a la cuenta; la del puesto, en ajustes locales. Los controles comunes de Runtime usan el catálogo de interfaz de su idioma, sin cambiar Studio; sin catálogo usan español. Las alarmas históricas se presentan mediante alarm_id y su definición actual, con respaldo del texto traducible para definiciones retiradas. Las cadenas de archivos antiguos siguen siendo legibles.

## Bibliotecas publicadas

El paquete `.abscada-library.json` incluye schema_version, name, version, author, license, faceplates y assets. Los paquetes traducidos incluyen languages y default_language; el consumidor debe declarar los idiomas usados. Los textos de objetos vinculados se editan en su origen o en una copia local.

```json
{"schema_version":1,"name":"Equipos","version":"1.0.0",
 "languages":["es","en"],"default_language":"es",
 "author":"Mi equipo","license":"GPL-3.0-or-later",
 "faceplates":{"bomba":{"width":100,"height":60,"parameters":{},"elements":[]}},
 "assets":{}}
```

assets relaciona rutas relativas con bytes base64, incluidas imágenes de estados. Se rechazan rutas absolutas, `..`, dos puntos y barras invertidas; el exportador asigna nombres por hash. Una plantilla distribuible usa parámetros `$nombre`, colores HEX y recursos capturados, sin depender de variables, scripts, pantallas o visores del autor.

libraries.json fija el paquete con source y sha256 por alias. El alias empieza por letra ASCII y admite letras, números, _ y -, hasta 40 caracteres. Las plantillas se resuelven como alias__nombre en memoria y no se duplican en faceplates/. La copia funciona sin el original. Actualizar exige el mismo nombre, una versión nueva si cambia contenido y compatibilidad con todas las instancias; se valida antes de aplicar. La huella es integridad, no firma de autoría.

```python
from abscada.project import Project
from abscada.faceplate_libraries import export_library, link
p = Project.load("autor")
export_library(p, ["bomba"], "equipos-1.0.0.abscada-library.json",
               "Equipos", "1.0.0", author="Mi equipo", license="GPL-3.0-or-later")
consumer = Project.load("consumidor")
link(consumer, "equipos-1.0.0.abscada-library.json", "equipos")
consumer.save()
```

Publica en un archivo nuevo; no sobrescribas versiones distribuidas. Véase [STUDIO.md](STUDIO.md#librerías) para la interfaz.

### Adaptar bibliotecas de otro sistema

Trabaja con la versión y los archivos de origen, sus interfaces, recursos y código. Una captura permite aproximar apariencia, pero no acredita equivalencia de lógica. Respeta licencias; no copies recursos ni código sin derechos.

Entrega un proyecto de autoría editable, un paquete nuevo, un consumidor de prueba y un informe de diferencias. Mantén nombres de parámetros estables y registra pérdidas de función o componentes omitidos. No añadas propiedades inventadas al JSON.


Esta tabla propone estrategias para el destino; debe contrastarse con la biblioteca y versión de origen. Una biblioteca de origen puede distinguir interfaces de variables, propiedades y eventos. abSCADA utiliza los parámetros de variables primitivas descritos aquí.

| Concepto de origen | Estrategia en abSCADA | Clasificación |
| --- | --- | --- |
| Tipo de faceplate e instancia | Documento de plantilla e instancia template/bindings | Adaptación directa de estructura básica |
| Variable de interfaz simple | Parámetro bool/int/float/string y `$parametro` | Revisar tipo y acceso |
| UDT o array de interfaz | Descomponer en parámetros de hojas; arrays necesitan transformación explícita | No equivalencia directa |
| Propiedad configurable de interfaz (color, tamaño, imagen, etc.) | Variantes de plantilla o propiedades fijas publicadas | Sin interfaz de propiedades equivalente |
| Eventos personalizados de interfaz | Trasladar lógica al consumidor con diseño explícito | Sin interfaz de eventos equivalente |
| Scripts y APIs del sistema de origen | Analizar función; usar acción declarativa si existe, o rediseñar lógica del anfitrión | No ejecutar ni pegar JavaScript |
| Color/visibilidad por variable | dynamics con comparaciones y primera coincidencia | Revisar precedencia, calidad y permisos |
| Texto según estado | text_list o estados con style.text | Admite mapas de texto por idioma; revisar idiomas del consumidor |
| Mandos de pulsación/liberación | momentary o press_release | Verificar contrato de escritura y pérdida de conexión |
| Símbolos vectoriales e imágenes | Figuras nativas o SVG estático empaquetado | Revisar escalado y proporciones |
| Faceplates dentro de faceplates | Aplanar geometría y parámetros con nombres únicos | Anidamiento no soportado |
| Pantalla emergente de configuración | Pantalla del consumidor y botón popup | No se empaquetan pantallas en bibliotecas v1 |
| Listas de acciones, expresiones complejas, animación | Informe de diferencias y propuesta separada | No inventar propiedades |


### Comprobar un paquete

Valida proyecto y paquete, prueba instancias con bindings completos y tipos compatibles, valores límite, calidad, permisos, solapamiento y pulsación/liberación. Revisa apariencia a escala nominal y redimensionada. Abre una copia sin acceso a recursos del autor y comprueba que una actualización incompatible se rechaza conservando el proyecto.

```bash
python tools/validate_library.py equipos-1.0.0.abscada-library.json
python -m pytest tests/test_faceplate_libraries.py
```

El ejemplo de autoría es `examples/library_author`; su paquete inicial está en `examples/libraries/`. Cargar sin error no acredita equivalencia con la biblioteca de origen.
