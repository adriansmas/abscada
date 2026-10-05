# Scripts Python y tareas

En Studio, Scripts y tareas reúne el editor Python, los eventos de inicio, las tareas cíclicas y las últimas ejecuciones. El editor tiene resaltado, números de línea, sangrado automático y comprobación de sintaxis. Las fuentes se guardan como `scripts/<nombre>.py`, editables desde VS Code. El botón Comprobar valida sin ejecutar.

## Eventos

- Eventos de inicio… selecciona los scripts que se ejecutan una vez al arrancar el runtime. Las comunicaciones ya se han iniciado, pero puede no haber todavía una lectura válida del PLC.
- Sin seleccionar objetos, Al abrir pantalla… configura los scripts de ese documento. Se ejecutan al abrirlo en una ventana o contenedor y al navegar a él. Volver a enfocar una emergente ya abierta no repite el evento. La apertura de un layout dispara primero su evento y después los de sus pantallas iniciales.
- Un botón puede usar Acción → Ejecutar script. Recibe como contexto la pantalla donde se pulsó, incluida una pantalla alojada en un contenedor.
- Tareas cíclicas permite nombre, script, periodo en milisegundos y activación. El primer disparo llega tras el periodo configurado, no al arrancar. Usa un evento de inicio si también necesitas ejecución inmediata.

Studio no ejecuta scripts de proceso. El runtime utiliza la copia de fuentes y configuración tomada al arrancar. Reinícialo para ejecutar cambios nuevos. El modo headless ejecuta inicio y tareas; no genera aperturas de pantalla.

## API

```python
# Instantánea coherente tomada al empezar esta ejecución.
if ctx.quality("Pump1.running") == "good":
    running = ctx.read("Pump1.running")
    print(f"Bomba 1: {running}")

# Estado por script, compartido por sus distintos eventos, durante este runtime.
ctx.state["executions"] = ctx.state.get("executions", 0) + 1
print(ctx.event, ctx.screen, ctx.state["executions"])
```

`ctx.read(nombre)` devuelve el valor y rechaza lecturas cuya calidad no sea good. `ctx.quality(nombre)` devuelve good, uncertain o bad. Ambas rechazan variables inexistentes. `ctx.event` es startup, screen_open, button o task:<id>. `ctx.screen` está vacío para inicio y tareas.

`ctx.write(nombre, valor)` solicita una escritura. Ejemplo: `ctx.write("Pump1.setpoint", 50.0)`. Se recogen hasta 1000 solicitudes y se validan al terminar correctamente el script. Si hay una excepción, sus solicitudes y cambios de estado se descartan. Se comprueban tipo, acceso de escritura y calidad de la variable enlazada antes de aplicar. Las escrituras PLC se envían por la cola habitual de su conexión; el retorno del script no confirma que el PLC las haya aceptado. Consultar el diagnóstico de comunicación y la lectura posterior. Las escrituras de un script no constituyen una transacción entre PLC distintos.

`ctx.state` debe contener datos JSON serializables y se reinicia al detener/iniciar el runtime. `print()` y las excepciones aparecen en Ejecuciones (hasta 500 resultados, salida limitada a los últimos 16000 caracteres por ejecución). No es un registro persistente de auditoría de scripts.

## Ejecución y límites

Los eventos y tareas se serializan en un servicio independiente de Qt y de la adquisición. Cada ejecución usa un proceso Python nuevo. El límite configurable es de 0,1 a 300 segundos, por defecto 10. Al excederlo se termina ese proceso y se registra un error; el servicio continúa. La parada del runtime cancela la ejecución activa y descarta eventos pendientes. La cola admite 128 eventos; al llenarse se registra el descarte.

Los scripts de inicio se ejecutan en el orden configurado antes de atender aperturas de pantalla, botones o tareas. Los primeros plazos de las tareas comienzan después de terminar esa inicialización. Los fallos de un script se registran y el servicio continúa con el siguiente.

Las tareas no se solapan ni acumulan recuperaciones de periodos perdidos: el siguiente plazo se calcula desde el final de la ejecución. Son tareas periódicas de aplicación, no planificación de tiempo real ni calendarios diarios/semanales. Un script lento retrasa otros scripts, pero no bloquea Qt ni la adquisición. La captura normal de salida conserva un búfer limitado durante la ejecución, sin acumular todo el texto impreso.

Los scripts son código Python de confianza del proyecto: tienen los permisos del usuario, pueden importar las bibliotecas instaladas y trabajar con archivos. El proceso separado permite cancelación; no es una sandbox de seguridad ni limita toda la memoria o los subprocesos que el propio script decida crear. El directorio de trabajo es la carpeta del proyecto. La API ctx no expone widgets ni clientes PLC. Para datos propios usa `runtime/`, excluido de las versiones Git.

`examples/plant` incluye inicio, apertura de pantalla y una tarea de calidad de comunicación cada cinco segundos. Los ejemplos no escriben al PLC ni fabrican valores.

## Archivos

```json
{
  "startup": ["startup"],
  "timeout_seconds": 10,
  "tasks": [
    {"id":"quality","script":"check_quality","interval_ms":5000,"enabled":true}
  ]
}
```

Se guarda en `automation.json`. Una pantalla añade `"on_open":["screen_open"]`. Un botón añade `"action":"script", "script":"nombre"`. Los proyectos anteriores cargan con configuración vacía. Las referencias y sintaxis se validan al guardar y al iniciar el runtime.
