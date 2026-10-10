# Manual de scripts de abSCADA

Referencia de la API disponible en 0.5.0b5, comprobada contra `script_runner.py`, `scripting.py` y `runtime.py`. Explica las funciones de abSCADA, no el lenguaje Python. Las carpetas de scripts y la ejecución de un script dentro de una lista de acciones de un botón están sin publicar en 0.5.0b5.

## Índice

- [Crear y ejecutar un script](#crear-y-ejecutar-un-script)
- [Referencia rápida](#referencia-rápida)
- [Leer variables y calidad](#leer-variables-y-calidad)
- [Escribir variables](#escribir-variables)
- [Propiedades del contexto](#propiedades-del-contexto)
- [Cambiar el idioma](#cambiar-el-idioma)
- [Ejemplos prácticos](#ejemplos-prácticos)
- [Diagnóstico y errores](#diagnóstico-y-errores)
- [Ejecución, permisos y límites](#ejecución-permisos-y-límites)
- [Funciones no disponibles](#funciones-no-disponibles)

## Crear y ejecutar un script

1. Abre la sección **Scripts** de Studio y la pestaña **Scripts Python**.
2. Escribe un nombre en «+ Nuevo script» y pulsa Intro. Usa letras sin acentos, números, `_` o `-`, sin extensión `.py`.
3. Escribe el código directamente en el editor. El objeto `ctx` ya existe: no hay que importarlo ni definir una función de entrada.
4. Pulsa **Comprobar**. Revisa sintaxis y referencias configuradas; no ejecuta el código ni comprueba las cadenas de nombres de tags dentro del código.
5. Asocia el script a uno de los disparadores de la tabla siguiente.
6. Guarda el proyecto y abre Runtime. Si ya estaba abierto, reinícialo para aplicar cambios.
7. Consulta la pestaña **Ejecuciones** para ver resultados y errores del runtime abierto desde Studio.

| Cuándo ejecutarlo | Dónde configurarlo | `ctx.event` | `ctx.screen` |
| --- | --- | --- | --- |
| Al arrancar Runtime | Scripts → Eventos de inicio… | `"startup"` | `""` |
| Al abrir una pantalla | Sin objetos seleccionados → Al abrir pantalla… | `"screen_open"` | Nombre de la pantalla |
| Al pulsar un botón | Propiedades del botón → Acción → Ejecutar script; elegir script. También como una acción de Lista de acciones | `"button"` | Nombre de la pantalla de origen |
| Periódicamente | Scripts → Tareas cíclicas; elegir script, periodo y activación | `"task:<id>"` | `""` |

La apertura de pantallas incluye contenedores y ventanas emergentes. Volver a enfocar una emergente que ya estaba abierta no repite el evento. El modo sin interfaz ejecuta inicio y tareas, pero no genera aperturas de pantalla. El servicio también admite el evento `"manual"` como valor interno por defecto; no hay una función `ctx` para dispararlo.

Los archivos se guardan en `scripts/<nombre>.py`. Puedes editarlos externamente, pero Runtime utiliza la copia del proyecto que recibió al arrancar. Las carpetas de la lista de Scripts solo organizan Studio: no cambian la ruta del archivo ni el nombre con el que se referencia el script.

## Referencia rápida

Los nombres de tags son los de **Variables** del proyecto, con sus mayúsculas y puntos exactos. `"Bomba.Consigna"` es un nombre completo, no un acceso a un atributo Python. No uses una dirección como `DB1.DBD4` salvo que ese sea literalmente el nombre de tu variable: la conexión y dirección se configuran en Studio.

| Función o propiedad | Para qué sirve | Resultado / contenido |
| --- | --- | --- |
| `ctx.read(nombre)` | Leer un tag con calidad buena | Valor `bool`, `int`, `float` o `str` |
| `ctx.quality(nombre)` | Consultar la calidad de un tag | `"good"`, `"uncertain"` o `"bad"` |
| `ctx.write(nombre, valor)` | Añadir una solicitud de escritura | `None`; no devuelve confirmación |
| `ctx.set_language(codigo)` | Solicitar otro idioma del proyecto | `None` |
| `ctx.event` | Saber qué disparó la ejecución | Texto, según la tabla de eventos |
| `ctx.screen` | Consultar la pantalla de origen | Texto; vacío en inicio y tareas |
| `ctx.state` | Conservar datos entre ejecuciones del mismo script | Inicialmente `{}`; usar un diccionario con datos JSON |
| `ctx.samples` | Consultar la instantánea de todos los tags | Diccionario por nombre con `value` y `quality` |
| `ctx.language` | Consultar el idioma del proyecto | Código de idioma |
| `ctx.languages` | Consultar los idiomas declarados | Lista de códigos |

También existen `ctx.actions` y `ctx.language_change` como campos internos del intercambio con Runtime. Se describen más abajo para distinguirlos de las funciones de uso normal.

## Leer variables y calidad

### `ctx.read(nombre)`

Devuelve el valor de la instantánea capturada **al comenzar la ejecución**, si su calidad es `good`.

```python
temperatura = ctx.read("Deposito.Temperatura")
print("Temperatura:", temperatura)
```

- Tag inexistente: `KeyError`.
- Calidad `bad` o `uncertain`: `ValueError`.
- No consulta directamente al PLC ni fuerza una nueva adquisición.

### `ctx.quality(nombre)`

Devuelve la calidad de la misma instantánea, sin exigir que sea buena. Un nombre inexistente produce `KeyError`.

| Calidad | Interpretación para el script |
| --- | --- |
| `good` | El valor está disponible con calidad buena |
| `uncertain` | No hay una lectura válida confirmada, por ejemplo al iniciar una variable enlazada |
| `bad` | Hay un fallo de adquisición; el valor conservado no debe tratarse como una lectura válida actual |

```python
nombre = "Deposito.Temperatura"
if ctx.quality(nombre) == "good":
    print("Temperatura:", ctx.read(nombre))
else:
    print("Temperatura no disponible:", ctx.quality(nombre))
```

La calidad buena no proporciona una medida de antigüedad: esta API no expone la hora de la muestra ni la última lectura buena.

### La instantánea no cambia mientras se ejecuta el script

Leer dos veces obtiene el mismo valor, salvo que el propio código modifique `ctx.samples`, algo que no debe usarse para operar el proceso. Hacer una espera tampoco refresca los datos. Las muestras de distintos PLC no representan necesariamente un mismo instante físico.

```python
anterior = ctx.read("Bomba.Consigna")
ctx.write("Bomba.Consigna", 50.0)
print(ctx.read("Bomba.Consigna"))  # Sigue mostrando el valor anterior.
```

Para comprobar un resultado, usa una ejecución posterior que reciba una nueva instantánea.

## Escribir variables

### `ctx.write(nombre, valor)`

Añade una solicitud a la lista de escrituras de esta ejecución. No escribe inmediatamente y no devuelve un resultado del PLC.

```python
ctx.write("Bomba.Marcha", True)
ctx.write("Bomba.Consigna", 42.5)
```

Ambos tags deben existir y tener escritura permitida. Si están enlazados a un PLC, necesitan calidad buena cuando Runtime valida las solicitudes al terminar el script.

| Tipo del tag | Valor recomendado | Validación |
| --- | --- | --- |
| `bool` | `True` o `False` | También admite 0, 1 y los textos `"true"`, `"false"`, `"True"`, `"False"` |
| `int` | `25` | Debe representar un entero finito; rechaza booleanos y valores con parte fraccionaria |
| `float` | `25.5` | Convertible a número finito; rechaza NaN e infinito |
| `string` | `"Preparado"` | Debe ser texto |

Además del tipo del proyecto, el enlace PLC impone sus tipos y rangos de codificación. Que una solicitud supere la validación del script no garantiza que el adaptador pueda enviarla o que el PLC la acepte.

### Cuándo se aplican las solicitudes

1. El script acumula solicitudes, hasta **1000** por ejecución.
2. Si el código termina correctamente y el resultado es serializable, Runtime valida todos los tags, tipos, permisos de escritura de las variables y calidad de las enlazadas.
3. Si esa validación falla, no aplica ninguna de las solicitudes.
4. Si pasa, procesa las solicitudes en el orden registrado: las variables internas se actualizan en Runtime y las enlazadas se encolan en su conexión.
5. Después aplica el cambio de idioma solicitado, guarda `ctx.state` y registra el resultado del script.

Una excepción del código, un timeout o un resultado no serializable impiden aplicar las solicitudes y guardar el nuevo estado. Esto no revierte operaciones externas que el código haya hecho por su cuenta, como escribir un archivo.

**No es una transacción.** Un fallo durante la aplicación puede dejar solicitudes anteriores ya aplicadas o encoladas. Las conexiones PLC trabajan de forma independiente. Un resultado `ok` del script tampoco confirma la ejecución física de las órdenes; verifica las lecturas posteriores y el diagnóstico de comunicaciones.

Escribir `True` y después `False` en la misma ejecución no garantiza un pulso detectable por el PLC. La temporización y confirmación de mandos deben tener un mecanismo explícito de proceso.

## Propiedades del contexto

### `ctx.event` y `ctx.screen`

Son datos de contexto para consultar. Cambiar su valor en el script no navega a otra pantalla ni genera eventos.

```python
print("Evento:", ctx.event)
print("Pantalla:", ctx.screen or "Sin pantalla de origen")
```

En un botón dentro de un contenedor, `ctx.screen` identifica la pantalla alojada donde se pulsó.

### `ctx.state`

Permite guardar datos entre ejecuciones del **mismo script** durante ese Runtime. Se comparte entre todos sus disparadores; dos scripts distintos tienen estados separados. También se comparte si el mismo script se usa desde varias pantallas.

```python
ctx.state["ejecuciones"] = ctx.state.get("ejecuciones", 0) + 1
ctx.state["ultimo_evento"] = ctx.event
print("Ejecución", ctx.state["ejecuciones"])
```

- Empieza vacío y se reinicia al detener y arrancar Runtime.
- No se guarda como estado persistente en disco.
- Se conserva el nuevo estado solo si la ejecución y su aplicación final terminan correctamente.
- Usa claves de texto y valores JSON: textos, números finitos, booleanos, `None`, listas y diccionarios. No guardes fechas como objetos, archivos abiertos, clientes PLC o widgets. Para una fecha puedes guardar su representación textual.
- Las variables Python ordinarias no sobreviven: cada ejecución crea un proceso nuevo.

### `ctx.samples`

Diccionario de instantáneas, con esta estructura por tag:

```python
{"value": 42.5, "quality": "good"}
```

Permite comprobar existencia y recorrer los tags:

```python
nombre = "Deposito.Temperatura"
if nombre not in ctx.samples:
    print("No existe el tag:", nombre)
else:
    muestra = ctx.samples[nombre]
    print("Valor conservado:", muestra["value"], "Calidad:", muestra["quality"])
```

El acceso directo a `value` no rechaza calidad mala: úsalo para diagnóstico; para lógica de proceso, utiliza `ctx.read()`. Trata `ctx.samples` como datos de consulta. Modificarlo solo cambia la copia del script y puede falsear sus propias lecturas; no escribe en Runtime.

**No contiene** `timestamp`, `error`, tipo, dirección PLC, unidad, descripción, límites ni atributo `writable`. Solo se transmiten `value` y `quality`.

### `ctx.language` y `ctx.languages`

`ctx.language` contiene el idioma del proyecto al empezar; `ctx.set_language()` también actualiza ese valor dentro de la ejecución. `ctx.languages` contiene los códigos declarados en el proyecto.

```python
print("Idioma:", ctx.language)
print("Idiomas disponibles:", ctx.languages)
```

Asignar directamente `ctx.language` no solicita un cambio en Runtime. Modificar `ctx.languages` no añade idiomas al proyecto.

### Campos internos: `ctx.actions` y `ctx.language_change`

| Campo | Contenido inicial | Uso interno |
| --- | --- | --- |
| `ctx.actions` | `[]` | Lista de parejas `[nombre, valor]` que rellena `ctx.write()` |
| `ctx.language_change` | `None` | Código solicitado por `ctx.set_language()` |

Aunque son accesibles en Python, no deben editarse directamente. Usa los métodos para mantener sus comprobaciones. No son funciones adicionales para controlar pantallas o el PLC.

## Cambiar el idioma

### `ctx.set_language(codigo)`

Solicita un idioma declarado en el proyecto. Un código desconocido produce `ValueError`. No traduce textos ni cambia el idioma de Studio.

```python
if "en" in ctx.languages:
    ctx.set_language("en")
else:
    print("El proyecto no tiene declarado el inglés")
```

El cambio se aplica al finalizar correctamente. Si se llama varias veces, queda la última solicitud. La configuración de idiomas se explica en [Studio](STUDIO.md).

## Ejemplos prácticos

Los nombres siguientes son ilustrativos: crea las variables o sustitúyelos por los nombres exactos del proyecto. Los destinos de `ctx.write()` deben permitir escritura.

### Calcular un valor interno a partir de un tag del PLC

Asocia este script a una tarea cíclica. `Deposito.Nivel` debe representar un porcentaje y `Resumen.NivelAlto` ser un booleano interno escribible.

```python
if ctx.quality("Deposito.Nivel") == "good":
    ctx.write("Resumen.NivelAlto", ctx.read("Deposito.Nivel") >= 90.0)
else:
    print("No se actualiza el resumen: nivel sin calidad buena")
```

### Solicitar varias consignas desde un botón

Configura el botón con **Ejecutar script** y selecciona este script.

```python
destinos = ["Receta.Temperatura", "Receta.Tiempo"]
if all(ctx.quality(nombre) == "good" for nombre in destinos):
    ctx.write("Receta.Temperatura", 65.0)
    ctx.write("Receta.Tiempo", 30)
    print("Consignas preparadas para su envío al terminar el script")
else:
    print("No se solicitan cambios: alguna variable no tiene calidad buena")
```

Esto no garantiza aplicación simultánea. Si el proceso necesita cargar una receta completa de forma coordinada, debe definir un intercambio de solicitud y confirmación con el PLC.

### Detectar un cambio entre ejecuciones

Configúralo como tarea cíclica. Detecta diferencias entre las muestras observadas; no garantiza capturar transiciones más rápidas que la tarea.

```python
nombre = "Bomba.Marcha"
if ctx.quality(nombre) == "good":
    actual = ctx.read(nombre)
    anterior = ctx.state.get("marcha_anterior")
    if anterior is not None and actual != anterior:
        print("Cambio de marcha:", anterior, "→", actual)
    ctx.state["marcha_anterior"] = actual
else:
    ctx.state.pop("marcha_anterior", None)
```

### Enumerar variables con problemas

```python
for nombre, muestra in ctx.samples.items():
    if muestra["quality"] != "good":
        print(nombre, muestra["quality"])
```

Hay ejemplos completos en [los scripts de la cervecería](../examples/brewery/scripts/ciclo_1s.py) y en `examples/showcase/scripts/`.

## Diagnóstico y errores

`print()` genera salida de diagnóstico, no un aviso emergente. En **Scripts → Ejecuciones** se muestran hora, script, estado `ok`/`error` y mensaje. Sin salida, una ejecución correcta muestra el nombre del evento.

Se conservan hasta **500 resultados** en memoria. La salida del proceso se limita a sus últimos **16000 caracteres**. Los errores del código se registran con su traza; en ese camino el servicio actual registra el error y no incorpora la salida previa de `print()`. No es un archivo persistente de ejecuciones.

| Síntoma | Qué revisar |
| --- | --- |
| `KeyError` con el nombre del tag | Nombre exacto en Variables; `ctx.samples` permite comprobar existencia |
| Calidad `uncertain` al inicio | La primera adquisición puede no haber llegado; comprobar calidad en otra ejecución |
| Calidad `bad` | Estado de conexión; no sustituir una lectura fallida por un dato supuesto |
| Variable de solo lectura | Configuración de escritura del tag |
| Error de tipo | Tipo del tag y valor solicitado; después, rango del enlace PLC |
| Error de serialización | Contenido de `ctx.state` y valores de escritura; evitar objetos no JSON y números no finitos |
| Tiempo de ejecución excedido | Bucles, esperas u operaciones lentas; dividir el trabajo entre ejecuciones |
| Cola de eventos llena | Se descartó un evento; reducir frecuencia o duración de scripts |
| Resultado `ok`, pero el PLC no cambió | `ok` no confirma transporte ni proceso; revisar comunicaciones y lectura posterior |
| Cambios de código sin efecto | Guardar y reiniciar Runtime |

## Ejecución, permisos y límites

| Aspecto | Comportamiento actual |
| --- | --- |
| Ejecuciones simultáneas | El servicio ejecuta los scripts uno detrás de otro |
| Proceso | Un proceso Python nuevo por ejecución |
| Tiempo máximo | 10 s por defecto; configurable entre 0,1 y 300 s en Eventos de inicio…; incluye arranque del proceso |
| Periodo de tareas | Entre 100 y 86400000 ms; próximo plazo calculado al terminar la ejecución |
| Primer disparo periódico | Después del periodo configurado, tras terminar los scripts de inicio |
| Eventos en cola | Hasta 128; los adicionales se descartan con diagnóstico |
| Escrituras | Hasta 1000 solicitudes por ejecución usando `ctx.write()` |
| Parada | Cancela la ejecución activa y descarta eventos pendientes |
| Directorio de trabajo | La carpeta del proyecto |

Los scripts de inicio se ejecutan en el orden configurado antes de atender otros eventos y tareas. Si uno falla, se registra el error y el servicio sigue con el siguiente. Un script lento retrasa otros scripts, aunque la adquisición y la interfaz usan otros hilos. No uses un bucle de espera para buscar una nueva lectura: su instantánea no se actualiza.

Con seguridad de usuarios activada, pulsar un botón de script exige el permiso del control (`operate` por defecto, o el configurado). Sin embargo, el contexto del script no recibe la sesión ni la identidad del operador: `ctx.write()` utiliza la vía de automatización y no vuelve a autorizar cada escritura con la sesión de quien pulsó. Las solicitudes se auditan con origen `script` y actor vacío en esta implementación. Inicio y tareas no requieren que haya un operador conectado. Los scripts deben considerarse código de confianza del proyecto.

El proceso separado permite timeout y cancelación, pero no es una sandbox: el código puede usar bibliotecas instaladas y archivos con los permisos del usuario del sistema. Para archivos propios de ejecución, la carpeta prevista es `runtime/`, excluida de las versiones Git. Estas operaciones de archivo no forman parte de la API `ctx`.

## Funciones no disponibles

La API actual no incluye métodos para:

- Leer directamente una dirección PLC, forzar una adquisición o esperar la confirmación de una escritura.
- Obtener la fecha de muestra, error de conexión o metadatos de un tag desde `ctx`.
- Abrir/cerrar pantallas o ventanas, manipular objetos gráficos o mostrar cuadros de diálogo.
- Consultar usuarios, roles o la sesión del operador.
- Reconocer alarmas, consultar históricos o generar informes mediante un método de `ctx`.
- Invocar otro script, programar una nueva tarea o suscribirse a cambios de variables.
- Crear variables o modificar la configuración del proyecto.

Estas funciones no deben deducirse de las capacidades de los botones o de otras partes de Runtime. Este manual enumera toda la superficie actual del objeto `ctx`; las ampliaciones deberán añadirse aquí cuando se implementen.
