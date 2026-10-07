# Desarrollo

## Entorno

Python >= 3.11; entorno probado localmente: Windows, Python 3.14.3, PySide6 6.11.2, python-snap7 3.2.0, pytest 9.1.1. `requirements-lock.txt` fija las dependencias principales probadas; no es un lock universal con hashes de todos los paquetes transitivos.

Instalar: `python -m pip install -e '.[dev,s7,modbus,opcua]'`. Ejecutar: `python -m abscada examples/demo`. Los ejemplos S7 necesitan `s7`, los Modbus necesitan `modbus` y la cervecería requiere `opcua`; ADS no requiere un paquete de transporte adicional. Las pruebas arrancan servidores TCP S7 independientes en puertos efímeros; no registran un protocolo de simulación interno. No introducir importaciones Qt en el dominio ni en comunicaciones.

## Pruebas

`python -m pytest -q` ejecuta:

- Expansión de estructuras y enlaces de faceplate.
- Guardado y recarga sin pérdida de datos.
- Rechazo de referencias inválidas, ciclos, valores y direcciones incorrectas.
- Permisos de escritura y lectura posterior a una orden.
- Calidad bad, descarte de escritura offline y reconexión.
- Codificación S7 y conservación de bits vecinos.
- Servidor TCP S7 y runtime completo.
- Studio: clic en herramientas, drop, propiedades, historial, duplicado/eliminación, resize y formularios.
- Runtime en otra ventana: controles, cierre, reinicio y aislamiento del proyecto.
- Comparación de imágenes del lienzo de Studio antes y después de adquirir valores: el diseño permanece idéntico.

Las pruebas S7 TCP se omiten si falta python-snap7. Qt se necesita para las pruebas de interfaz. El workflow de GitHub cubre Windows/Linux y Python 3.11/3.14. El estado de sus ejecuciones se consulta en GitHub Actions; esta guía no acredita una ejecución remota concreta. macOS no está incluido en esa matriz.

`python tools/capture_demo.py` regenera `docs/editor.png`, `docs/runtime.png` y `docs/editor-runtime-active.png`. Revisar visualmente las capturas cuando cambie el renderizador. No sustituir las pruebas funcionales por una captura. En Windows offscreen se cargan explícitamente las fuentes del sistema.

## Añadir un protocolo

1. Crear un módulo que implemente `connect()`, `read(address, kind)`, `write(address, kind, value)` y `close()`.
2. Publicar `Factory.definition` como `ProtocolDefinition`, con campos, normalización, validación y resumen del enlace. Registrar mediante `register("protocol_id", Factory)` antes de cargar el proyecto.
3. Añadir la dependencia opcional. Project y el editor delegan en la definición; no añadir condiciones de protocolo en esos módulos. Véase [PROTOCOLS.md](PROTOCOLS.md).
4. Probar contra un servidor TCP externo y fallos de conexión. `close()` debe ser idempotente y los errores deben conservar su contexto.
5. Documentar coerción, límites, derechos de escritura y qué significa la confirmación del protocolo.

El registro no ejecuta plugins externos encontrados en archivos del proyecto. No hay descubrimiento automático mediante entry points todavía. Una conexión no debe crear widgets ni acceder al almacén de variables directamente.

## Añadir elementos gráficos

Incorporar el tipo a `KINDS`, validación del proyecto, herramientas de dibujo (`graphics.TOOL_NAMES`), renderizador y pruebas. Mantener la representación como datos. Las acciones deben pasar por `Runtime.write`, nunca llamar a una conexión desde un evento Qt.

## Textos de la aplicación e idiomas

La interfaz se escribe en español, el idioma de origen, y cada texto visible pasa por `tr()` de `abscada/i18n.py`. Las traducciones están en `src/abscada/locales/<idioma>.json`, que relaciona el texto en español con el traducido. El usuario elige el idioma en **Ayuda → Idioma / Language**. Se guarda en `settings.json`, dentro de la carpeta de estado de abSCADA, y se aplica al volver a abrir el programa. `ABSCADA_LANG=en` lo fuerza para una prueba.

- Texto fijo: `tr("Guardar")`. Con datos: `tr("¿Eliminar la cuenta {name}?", name=name)`; nunca una f-string dentro de `tr()`, porque cambiaría el texto que se busca en el catálogo.
- Un texto que debe mostrarse en otro idioma que el activo se marca con `N_("…")` y se traduce con `i18n.load_catalog(código)`.
- No traduzcas claves, nombres de tipos (`bool`, `float`…), identificadores ni datos que se guardan en el proyecto y se comparan después (por ejemplo, los roles por defecto de `security.py`).
- `script_runner.py` se ejecuta como archivo suelto en otro proceso: no puede importar `tr`.

```powershell
.venv\Scripts\python tools/i18n_check.py               # textos traducidos y sin uso por idioma
.venv\Scripts\python tools/i18n_check.py --leftovers   # literales en español fuera de tr()
.venv\Scripts\python tools/i18n_check.py --export en   # añade a en.json los textos nuevos, vacíos, para traducirlos
.venv\Scripts\python tools/i18n_wrap.py src/abscada/nuevo.py   # envuelve en tr() los textos de un módulo nuevo
```

`tests/test_i18n.py` falla si un texto no tiene traducción o si sus marcadores `{…}` no coinciden. Para añadir un idioma, crea `locales/<código>.json` con `--export <código>`, tradúcelo y añade el código a `LANGUAGES`.

Los textos de **los proyectos** (pantallas, alarmas y títulos) no pasan por los catálogos de interfaz: son cadenas o mapas por idioma junto a cada propiedad. Véase [STUDIO.md](STUDIO.md). Los nombres de recetas recibidos del PLC siguen siendo datos de proceso. `example_translations.json` sirve únicamente para generar los ocho ejemplos bilingües.

## Antes de cambiar el formato

Decidir si es compatible con v1. Si no lo es, incrementar versión e implementar migración explícita con respaldo. Añadir fixture del formato anterior y una prueba de migración. No convertir automáticamente un archivo desconocido ni deserializar código ejecutable.

## Publicar una versión

Mientras trabajas, apunta cada cambio visible en `CHANGELOG.md`, bajo `## [Sin publicar]` (secciones *Añadido*, *Cambiado*, *Corregido* y *Seguridad*). Para publicar, con todo en commit y en la rama `main`:

```powershell
.\publicar-version.ps1 --beta --dry-run   # comprobar sin tocar nada
.\publicar-version.ps1 --beta             # 0.5.0b1 -> 0.5.0b2
.\publicar-version.ps1 --patch            # beta -> 0.5.0 estable
.\publicar-version.ps1 0.6.0rc1 --watch   # versión explícita y seguir la compilación
```

El script (`tools/release.py`):
1. **Comprueba** que estás en `main`, sin cambios pendientes, al día con GitHub, con la etiqueta libre y con notas en `[Sin publicar]`.
2. **Ejecuta las pruebas.**
3. **Cambia la versión** en `__init__.py` y `pyproject.toml`, y fecha la sección del registro de cambios.
4. **Pide confirmación**, hace commit, crea la etiqueta `v…` y sube las dos cosas.

A partir de ahí trabaja `release.yml` en GitHub, unos 10 minutos:
- comprueba que la etiqueta coincide con la versión;
- prueba, compila y prueba el `.exe`;
- genera SBOM, sumas y atestación;
- crea la release con el ZIP y las notas de esa versión del `CHANGELOG.md`. Las versiones `a`, `b` y `rc` se marcan como pre-versión.

No hay que editar nada en GitHub. Si algo falla en CI, la etiqueta ya existe pero no hay release: corrige, haz commit y publica la siguiente versión. No reutilices una etiqueta.

## Convenciones

Código propio GPL-3.0-or-later. Mantener nombres de API en inglés, mensajes de interfaz y documentación en español. Evitar dependencias nuevas cuando el estándar de Python o Qt ya cubran la necesidad. Usar tipado y pruebas para contratos importantes. No prometer capacidad de producción ni compatibilidad de CPU sin evidencia.

## Arquitectura

Monolito modular con fronteras entre proyecto, adquisición, archivo, scripts y Qt. El núcleo funciona sin interfaz; los adaptadores no conocen pantallas ni widgets.

| Módulos | Responsabilidad |
| --- | --- |
| project, project_storage, versioning | Carga/validación, guardado con recuperación y versiones Git |
| connectors, protocol_definition, modbus, ads, opcua | Transporte y esquemas de conexiones/enlaces, incluido S7 en connectors |
| runtime | Almacén de muestras, órdenes y trabajador independiente por conexión |
| operations, alarms, storage, recording | Motor de alarmas y escritores SQLite; consultas separadas |
| scripting, script_runner | Eventos/tareas serializados, proceso Python y timeout |
| ui, studio_shell, graphics, graphic_properties | Studio, dibujo e inspectores |
| runtime_window, screen_container, operation_windows | Ventanas y zonas con un Runtime compartido |
| project_languages, project_text_editor, runtime_language_ui | Traducciones por texto, CSV y catálogo de Runtime |
| faceplate_libraries, system_library, legacy_colors | Paquetes, objetos estándar y conversión de colores antiguos |

Cada conexión tiene cliente, cola y agenda propios. Lecturas y escrituras se serializan dentro de ella; todavía no hay lecturas agrupadas. Las muestras contienen value, quality, timestamp y error; su fecha es de recepción en Runtime. good/uncertain/bad no sustituyen una futura marca de última lectura buena.

Una escritura valida tipo, permiso y calidad y pasa por la cola del adaptador. Su Future confirma el transporte, no el estado físico: la lectura posterior actualiza el valor observado. No se reproducen órdenes descartadas al reconectar.

La ventana principal posee Runtime y la copia del proyecto; emergentes y contenedores comparten servicios. Un cambio de zona destruye sus visores, sin reconstruir las zonas hermanas. Studio y Prueba visual usan el renderizador compartido en modos explícitos, sin adquisición.

Operations es el escritor de alarmas/auditoría y programa registros diarios UTC. Los lectores trabajan separados de Qt. El bloqueo por proyecto impide dos runtimes y se libera al caer el proceso. El cierre cancela scripts, detiene adquisición y vacía el archivo antes de liberar recursos.

El guardado usa huellas de disco y un bloqueo exclusivo. Prepara archivos y backups, reemplaza solo cambios y restaura ante E/S; no promete atomicidad multarchivo frente a corte eléctrico. Los scripts son código de confianza, aunque su ejecución aislada permita timeout y cancelación.

## Validación actual

Revisión local del 7 de octubre de 2026: **452 pruebas superadas** con `python -m pytest -q` (301,35 s). Los ocho ejemplos validan, tienen traducciones ES/EN completas y no contienen referencias de color. El catálogo de interfaz tiene 1105/1105 textos traducidos, sin entradas sin uso. Se comprobaron 80 enlaces locales en los 17 Markdown vigentes y se regeneraron las capturas de Studio con `tools/capture_visual_editor.py`.

Las pruebas se ejecutan localmente en Windows con Qt offscreen y servidores TCP de desarrollo. Comprueban transporte S7/Modbus/ADS/OPC UA, autenticación y permisos, alarmas/archivo, scripts, edición Qt, layouts, librerías, idiomas y compatibilidad de colores antiguos.

```bash
python -m pytest -q
python tools/i18n_check.py
python -m abscada examples/brewery --validate
```

Una ejecución local no acredita el resultado remoto de CI, varios monitores físicos, Linux/macOS, PLC reales, carga sostenida o comportamiento ante corte de alimentación. Los ensayos pendientes se mantienen en [PENDIENTES.md](PENDIENTES.md); no se conservan informes de etapas antiguas como documentación vigente.
