# Formato de proyecto v1

```text
mi-proyecto/
  project.json
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

## Manifest

```json
{"schema_version": 1, "name": "Planta", "startup_screen": "main"}
```

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

`id` es estable y único. `protocol` elige el adaptador registrado. `poll_ms` admite 50 a 60000; es un intervalo objetivo, no una garantía de tiempo real. Los adaptadores disponibles son S7 y Modbus TCP. La prueba sin PLC físico utiliza un servidor TCP externo y las mismas direcciones DB. No hay direcciones de simulación internas.

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

En v1, los botones son órdenes al soltar; no son mandos momentáneos mantenidos. No usar para funciones que exijan detección segura de liberación. Los botones pueden invocar un script del proyecto mediante action=script; no se evalúan expresiones Python dentro de las propiedades gráficas.

Las imágenes deben vivir dentro de la carpeta del proyecto; las rutas que escapan se rechazan. No se incrustan dentro del JSON. La aplicación no carga imágenes remotas.

## Faceplates (objetos de librería)

En Studio se llaman **objetos de librería** (ver [FACEPLATE_LIBRARIES.md](FACEPLATE_LIBRARIES.md)). Un objeto puede llevar `"folder": "Válvulas/Agua"` para ordenarlo en la librería del proyecto; las carpetas vacías se guardan en `project.json` → `library_folders`. Las plantillas `estandar__*` pertenecen a la librería estándar de la aplicación y nunca se guardan en el proyecto.

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

## Propiedades visuales de Studio 0.2

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

Propiedades opcionales del documento: title (texto), background (#RRGGBB), grid_size (entero 1–200), show_grid y snap_to_grid (booleanos). Valores por defecto: fondo blanco, paso 10 y ambas opciones activadas. La pantalla inicial continúa en project.json → startup_screen.

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

`project.json` puede incluir `display` para colocar el runtime en varios monitores:

```json
"display": {
  "main": {"monitor": 1, "mode": "maximized"},
  "windows": [
    {"screen": "80_alarmas", "monitor": 2, "mode": "fullscreen"},
    {"screen": "10_general", "monitor": 3, "mode": "maximized", "on_top": false}
  ]
}
```

`main` coloca la ventana principal. Cada elemento de `windows` abre una ventana adicional al arrancar, con la pantalla indicada. `mode` admite `normal`, `maximized` o `fullscreen`. Todas las ventanas comparten el mismo runtime: no hay conexiones ni registros adicionales. Sin `display`, el comportamiento es el de siempre: una ventana principal.

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

Se guardan en `screens/<nombre>.json`, con `layout: true` para agruparlos como Layouts en el explorador. Comparten el formato, dimensiones, fondo y elementos de una pantalla. `startup_screen` puede apuntar al layout. No cambia el formato de los proyectos anteriores.

```json
{"layout":true,"width":1200,"height":730,"elements":[
 {"id":"cabecera","kind":"screen_container","x":0,"y":0,"w":1200,"h":90,"screen":"common_header"},
 {"id":"contenido","kind":"screen_container","x":0,"y":90,"w":1200,"h":640,"screen":"process_design"}
]}
```

Un botón de navegación añade `"action":"screen", "screen":"history", "target_container":"contenido"`. La propiedad target_container vacía u omitida significa zona actual; `__window__` significa ventana completa. Los demás valores deben coincidir con un ID de contenedor definido en el proyecto; su disponibilidad se comprueba además en la ventana activa al navegar. El ID __window__ está reservado. No se permiten contenedores en faceplates ni pantallas con contenedores dentro de otros contenedores (tampoco navegación a un layout desde una zona). Estos controles no crean comunicaciones adicionales.

## Automatización y versiones

Las fuentes residen en scripts/<nombre>.py; automation.json define startup, timeout_seconds y tasks. Los eventos de pantalla se guardan en on_open. Ver [Scripts y tareas](SCRIPTING.md) para la API y [Guardado y versiones](PROJECT_WORKFLOW.md) para Git y el guardado conjunto.


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

`project.json.palette` es un diccionario nombre → HEX. Los campos cromáticos admiten `@nombre` para referenciarlo. La evaluación resuelve las referencias conservando el vínculo en JSON. No se eliminan colores en uso sin corregir sus referencias.

Las acciones `momentary` y `press_release` complementan a las existentes. La primera escribe true/false sobre bool; la segunda requiere `press_value` y `release_value` compatibles con la variable. No son acciones de seguridad del PLC.

`editor_hidden` y `editor_locked` solo afectan al diseño; `group` identifica un grupo plano y `description` da un nombre descriptivo en Objetos. `visible: false` oculta estáticamente en operación. Las condiciones admiten `$parámetro` en plantillas y se resuelven en cada instancia. La guía VISUAL_STATES.md describe precedencia y tratamiento de calidad.
