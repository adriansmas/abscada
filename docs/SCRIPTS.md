# Scripts

Los scripts son archivos Python del proyecto (`scripts/<nombre>.py`) que Runtime ejecuta ante eventos. Reciben un objeto `ctx` para leer variables y solicitar escrituras. Esta guía describe toda la API; no enseña Python.

## Crear un script

1. En Studio, abre **Scripts → Scripts Python**, escribe un nombre en «+ Nuevo script» y pulsa Intro. Usa letras sin acentos, números, `_` o `-`.
2. Escribe el código. `ctx` ya existe: no hay que importarlo ni definir funciones de entrada.
3. **Comprobar** revisa la sintaxis y las referencias configuradas, sin ejecutar. No comprueba los nombres de variables escritos dentro del código.
4. Asocia el script a un disparador, guarda y abre Runtime (o reinícialo).
5. La pestaña **Ejecuciones** muestra resultados y errores del Runtime abierto desde Studio.

| Disparador | Dónde se configura | `ctx.event` | `ctx.screen` |
| --- | --- | --- | --- |
| Arranque de Runtime | Scripts → Eventos de inicio… | `"startup"` | `""` |
| Apertura de pantalla | Sin objetos seleccionados → Scripts al abrir la pantalla… | `"screen_open"` | Pantalla abierta |
| Botón | Acción → Ejecutar script, o dentro de una Lista de acciones | `"button"` | Pantalla del botón |
| Periódico | Scripts → Tareas cíclicas (periodo y activación) | `"task:<id>"` | `""` |

- Los scripts de inicio se ejecutan en orden, con las comunicaciones ya iniciadas pero quizá sin lecturas válidas todavía.
- La apertura de pantalla se dispara también en contenedores y emergentes, pero no al volver a enfocar una emergente ya abierta. Un layout dispara su evento antes que los de sus pantallas iniciales.
- Una tarea se dispara por primera vez tras su periodo, no al arrancar. Si necesitas una ejecución inmediata, añade el script también al inicio.
- En una Lista de acciones, el botón no espera al script: las acciones siguientes se envían enseguida y las escrituras del script llegan al terminar. Si el orden importa, haz todas las escrituras en el script.
- El modo sin interfaz ejecuta inicio y tareas, pero no aperturas de pantalla.

La lista de scripts admite carpetas (menú contextual o arrastrar). Las carpetas solo organizan Studio: el archivo sigue en `scripts/` y se referencia solo por su nombre, que es único. **Renombrar…** (F2) actualiza botones, listas de acciones, eventos y tareas, y avisa si otro script menciona el nombre antiguo como texto. Un script en uso no se puede eliminar.

## Referencia

Los nombres de variable son los de **Variables**, con mayúsculas y puntos exactos: `"Bomba.Consigna"` es un nombre, no un atributo Python ni una dirección del PLC.

| API | Uso | Devuelve |
| --- | --- | --- |
| `ctx.read(nombre)` | Leer una variable con calidad buena | `bool`, `int`, `float` o `str` |
| `ctx.quality(nombre)` | Consultar la calidad | `"good"`, `"uncertain"` o `"bad"` |
| `ctx.write(nombre, valor)` | Solicitar una escritura | `None` |
| `ctx.set_quality(nombre, calidad, motivo="")` | Cambiar la calidad de una variable interna sin tocar su valor | `None` |
| `ctx.set_language(codigo)` | Solicitar otro idioma del proyecto | `None` |
| `ctx.event`, `ctx.screen` | Qué disparó la ejecución y desde qué pantalla | Texto |
| `ctx.state` | Datos que se conservan entre ejecuciones del mismo script | Diccionario |
| `ctx.commit()` | Aplicar ya las escrituras pendientes, el idioma y el estado, y releer las variables | `None` |
| `ctx.sleep(segundos)` | `commit()`, esperar y releer; para bucles | `False` si Runtime se detiene |
| `ctx.stopping` | Runtime ha pedido detenerse | `bool` |
| `ctx.samples` | Instantánea de todas las variables | `{nombre: {"value", "quality"}}` |
| `ctx.language`, `ctx.languages` | Idioma actual y declarados | Código y lista de códigos |

`ctx.actions` y `ctx.language_change` son campos internos que rellenan `write()`, `set_quality()` y `set_language()`; no los modifiques.

## Leer

`ctx.read()` devuelve el valor de la instantánea tomada **al empezar la ejecución**. Lanza `KeyError` si la variable no existe y `ValueError` si su calidad no es `good`. `ctx.quality()` devuelve la calidad sin exigir que sea buena.

```python
nombre = "Deposito.Temperatura"
if ctx.quality(nombre) == "good":
    print("Temperatura:", ctx.read(nombre))
else:
    print("Sin dato:", ctx.quality(nombre))
```

La instantánea no cambia por sí sola: leer otra vez, o esperar con `time.sleep()`, devuelve lo mismo, incluso después de un `ctx.write()`. Solo `ctx.commit()` y `ctx.sleep()` la renuevan. Para ver el resultado de una orden, usa la siguiente ejecución o la siguiente vuelta de un bucle con `ctx.sleep()`. No hay hora de muestra ni antigüedad del dato, y las muestras de distintos PLC no son del mismo instante.

`ctx.samples` permite comprobar si existe una variable y recorrerlas todas. Su `value` no se filtra por calidad: úsalo para diagnóstico y `ctx.read()` para lógica de proceso.

```python
for nombre, muestra in ctx.samples.items():
    if muestra["quality"] != "good":
        print(nombre, muestra["quality"])
```

## Escribir

`ctx.write()` añade una solicitud; no escribe en ese momento ni devuelve confirmación.

1. El script acumula hasta **1000** solicitudes entre aplicaciones.
2. Si termina bien, o al llamar a `ctx.commit()` o `ctx.sleep()`, Runtime valida todas: que existan, tipo, permiso de escritura y, si están enlazadas, calidad buena.
3. Si una falla, no se aplica ninguna.
4. Si pasan, se aplican en orden: las internas al momento y las enlazadas a la cola de su conexión. Después se aplica el cambio de idioma y se guarda `ctx.state`.

Si `ctx.commit()` o `ctx.sleep()` encuentran una solicitud inválida, lanzan `ValueError` en el script y no aplican ninguna de ese grupo; el script puede capturarla y seguir. Una excepción no capturada, un timeout o un resultado no serializable descartan las solicitudes pendientes y el nuevo estado (lo ya aplicado con `commit()` se queda), pero no deshacen lo que el código haya hecho por su cuenta (por ejemplo, escribir un archivo).

| Tipo | Valores admitidos |
| --- | --- |
| `bool` | `True`/`False`, 0/1 y los textos `"true"`, `"false"`, `"True"`, `"False"` |
| `int` | Enteros finitos; no booleanos ni con decimales |
| `float` | Números finitos; no NaN ni infinito |
| `string` | Texto |

**No es una transacción.** Un fallo al aplicar puede dejar solicitudes anteriores ya enviadas, y cada PLC tiene su cola. Un resultado `ok` no confirma que el PLC haya aceptado la orden: compruébalo con la lectura posterior. Escribir `True` y luego `False` en la misma ejecución no garantiza un pulso.

## Calidad

Una variable interna escrita por un script tiene calidad `good`. Si el script calcula un valor a partir de un equipo que deja de responder, puede decirlo con `ctx.set_quality(nombre, calidad, motivo)`: `"bad"` (sin dato válido), `"uncertain"` (dudoso) o `"good"`. El valor se conserva y el motivo aparece como error de la muestra. La siguiente `ctx.write()` de esa variable la deja de nuevo en `good`.

Con calidad distinta de `good`, la variable se comporta como una de PLC sin comunicación: la pantalla la marca, el registro guarda la calidad, la tendencia corta la curva, `ctx.read()` lanza `ValueError` y las alarmas de valor no cambian de estado. La condición de alarma **Sin datos válidos** salta precisamente entonces.

```python
if ctx.quality("BasculaTrama") != "good":
    ctx.set_quality("Peso", "bad", "Báscula sin comunicación")
else:
    ctx.write("Peso", calcular(ctx.read("BasculaTrama")))
```

Se valida y se aplica junto con las escrituras, en el mismo orden. Solo admite variables internas escribibles: la calidad de una variable enlazada la da su conexión.

## Estado e idioma

`ctx.state` empieza vacío al arrancar Runtime y se conserva entre ejecuciones del mismo script, sea cual sea el disparador; cada script tiene el suyo. Solo admite datos JSON y solo se guarda si la ejecución termina bien o en cada `ctx.commit()`/`ctx.sleep()` aceptado. Las variables Python normales no sobreviven: cada ejecución es un proceso nuevo.

```python
nombre = "Bomba.Marcha"
if ctx.quality(nombre) == "good":
    actual, anterior = ctx.read(nombre), ctx.state.get("marcha")
    if anterior is not None and actual != anterior:
        print("Cambio de marcha:", anterior, "→", actual)
    ctx.state["marcha"] = actual
```

`ctx.set_language("en")` solicita un idioma declarado (`ValueError` si no lo está) y se aplica al terminar. Asignar `ctx.language` directamente no cambia nada.

## Scripts sin límite y bucles

Un script puede tener su propio límite de tiempo o ninguno: clic derecho en la lista → **Límite de ejecución…**. Las opciones son el general, un límite propio (0,1 s a 24 h) o **Sin límite**. La lista muestra el límite junto al nombre cuando no es el general.

Un script **sin límite** corre en paralelo, en su propio proceso, hasta que termina: no bloquea a los demás scripts. Sirve para bucles que leen un equipo, calculan o vigilan algo de forma continua. Reglas:

- Solo hay una ejecución de cada script a la vez. Un evento que llega mientras corre se descarta con aviso en **Ejecuciones**.
- Pon el bucle con `while ctx.sleep(segundos):`. Cada vuelta aplica las escrituras, guarda el estado, envía lo impreso a **Ejecuciones** y relee las variables. Al detener Runtime, `ctx.sleep()` devuelve `False` enseguida.
- Si no llama a `ctx.sleep()` en 2 s desde que Runtime pide detenerse, se mata el proceso.
- En **Eventos de inicio** arranca sin esperar a que termine; los siguientes scripts de inicio se ejecutan a continuación.
- Una **tarea cíclica** sobre un script sin límite lo vuelve a arrancar si ha terminado (por ejemplo, tras un error) y no hace nada mientras corre: sirve de vigilante.

```python
# Sin límite, en Eventos de inicio y con una tarea cíclica de 10 s como vigilante.
import re
while ctx.sleep(0.2):
    if ctx.quality("BasculaTrama") == "good":
        m = re.search(r"([+-]?\s*\d+\.?\d*)", ctx.read("BasculaTrama"))
        if m:
            ctx.write("Peso", float(m.group(1).replace(" ", "")))
print("Detenido")
```

`ctx.commit()` sirve también en scripts con límite, para aplicar órdenes antes de terminar. `time.sleep()` funciona, pero no aplica nada ni se entera de la parada: usa `ctx.sleep()`.

## Ejecución y límites

| Aspecto | Comportamiento |
| --- | --- |
| Concurrencia | Los scripts con límite, uno detrás de otro: uno lento retrasa a los demás, pero no a la interfaz ni a la adquisición. Los sin límite, en paralelo |
| Proceso | Uno nuevo por ejecución, con la carpeta del proyecto como directorio de trabajo |
| Tiempo máximo | General: 10 s por defecto, de 0,1 a 300 s (Eventos de inicio…). Propio por script: de 0,1 s a 24 h, o sin límite. Al superarlo se mata el proceso |
| Tareas | Periodo de 100 ms a 24 h, contado desde el final de la ejecución; no se solapan ni recuperan periodos perdidos |
| Cola | 128 eventos; los que no caben se descartan con aviso |
| Ejecuciones | Se guardan las últimas 500 en memoria, con los últimos 16000 caracteres de salida |
| Parada | Cancela la ejecución en curso y descarta los eventos pendientes |

`print()` y las excepciones aparecen en **Ejecuciones**, no en un aviso emergente.

**Seguridad.** Con usuarios activados, pulsar un botón de script exige su permiso (`operate` por defecto), pero el script no recibe la sesión: sus escrituras se auditan con origen `script` y sin usuario. Los scripts son **código de confianza** con los permisos del usuario del sistema; el proceso separado permite cancelarlos, pero no es una sandbox. Para archivos propios usa `runtime/`, que no se versiona.

## Lo que la API no hace

No lee direcciones del PLC directamente, ni fuerza lecturas, ni espera confirmaciones. Tampoco abre pantallas, muestra diálogos, consulta usuarios, reconoce alarmas, consulta históricos, llama a otros scripts ni cambia la configuración del proyecto.

## Problemas frecuentes

| Síntoma | Causa probable |
| --- | --- |
| `KeyError` | Nombre de variable mal escrito |
| `uncertain` al arrancar | Aún no ha llegado la primera lectura |
| `bad` | Fallo de comunicación |
| Error de serialización | `ctx.state` o un valor escrito no es JSON, o no es finito |
| Tiempo excedido | Bucles o esperas: reparte el trabajo entre ejecuciones, o quita el límite al script y usa `ctx.sleep()` |
| `Ya está en ejecución` | El script sin límite sigue corriendo; el evento se descarta |
| `ok` pero el PLC no cambia | Revisa comunicaciones y la lectura posterior |
| Los cambios no hacen efecto | Guarda y reinicia Runtime |

Hay ejemplos en `examples/brewery/scripts/` y `examples/showcase/scripts/`. El formato de `automation.json` está en [PROJECT_FORMAT.md](PROJECT_FORMAT.md#scripts).
