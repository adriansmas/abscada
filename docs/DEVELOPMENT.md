# Desarrollo

## Entorno

Python ≥ 3.11. Probado en Windows con Python 3.14, PySide6 6.11 y python-snap7 3.2; `requirements-lock.txt` fija las dependencias principales probadas.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,s7,modbus,opcua,serial]"
.venv\Scripts\python -m pytest -q
```

Extras: `s7` (python-snap7), `modbus` (pyModbusTCP), `opcua` (asyncua), `serial` (pyserial, para Modbus RTU y Serie/TCP en bruto). ADS no necesita dependencias.

## Pruebas

`python -m pytest -q` cubre el dominio, los protocolos contra servidores TCP reales en localhost (los serie, contra equipos simulados por TCP y `loop://`), alarmas y archivo, scripts, seguridad, idiomas, librerías, la interfaz de Studio y Runtime (Qt offscreen) y los ejemplos. Las pruebas S7 se omiten si falta python-snap7.

CI (`.github/workflows/tests.yml`) ejecuta Windows y Linux con Python 3.11 y 3.14, además de `pip-audit`. macOS no está en la matriz.

```powershell
.venv\Scripts\python tools/i18n_check.py                       # traducciones de la interfaz
.venv\Scripts\python -m abscada examples/brewery --validate    # validar un proyecto
```

## Arquitectura

Monolito modular. El dominio y las comunicaciones no importan Qt; los adaptadores no conocen pantallas.

| Módulos | Responsabilidad |
| --- | --- |
| `project`, `project_storage`, `validation`, `versioning` | Carga, validación, guardado con recuperación y versiones Git |
| `connectors`, `protocol_definition`, `modbus`, `modbus_rtu`, `serial_link`, `serial_ascii`, `ads`, `opcua` | Transporte y esquemas de conexión y enlace (S7 está en `connectors`; `serial_link` es el puerto serie o TCP en bruto común) |
| `runtime` | Almacén de muestras, órdenes y un trabajador por conexión |
| `operations`, `alarms`, `storage`, `recording` | Motor de alarmas y escritor SQLite; consultas aparte |
| `security`, `pki`, `opcua_server` | Usuarios y roles, certificados y servidor OPC UA |
| `scripting`, `script_runner` | Cola de eventos y proceso Python por ejecución |
| `ui`, `studio_shell`, `graphics`, `graphic_properties`, `*_editor` | Studio |
| `runtime_window`, `screen_container`, `operation_windows`, `viewers` | Runtime |
| `project_languages`, `i18n`, `locales/` | Textos del proyecto y de la interfaz |
| `faceplate_libraries`, `system_library`, `standard_library/` | Librerías publicadas y estándar |

- Cada muestra tiene valor, calidad (good, uncertain, bad), hora de recepción y error.
- Una escritura valida tipo, permiso y calidad y entra en la cola de su conexión. Las acciones de la interfaz pasan por `Runtime.write`; nunca llaman a una conexión desde un evento Qt.
- `Operations` es el único escritor de alarmas, registros y auditoría. Un bloqueo de archivo impide dos Runtime sobre el mismo proyecto.
- Studio y Prueba visual usan el mismo renderizador que Runtime, sin adquisición.
- Los simuladores de `tools/plc_simulators/` corren siempre en otro proceso; Runtime no los importa. Viajan dentro del `.exe` (`abscada --simulador <id>`).

## Añadir un protocolo

1. Crea un módulo con un adaptador que implemente `connect()`, `read(address, kind)`, `write(address, kind, value)` y `close()` (idempotente). Importa la biblioteca de red dentro de `connect()`, no al abrir Studio.
2. Opcional, `prepare_reads(requests)` para agrupar lecturas: recibe `[(address, kind), ...]` tras conectar y devuelve funciones sin argumentos que leen un bloque y devuelven `{índice: valor}`. Ejemplo: el adaptador S7 y `read_groups` en `connectors.py`. Si un bloque falla solo por sus datos (un esclavo del bus que no responde), lanza `GroupError(índices, mensaje)` de `protocol_definition`: esas variables pasan a *bad* y la conexión sigue abierta (ejemplo: `modbus_rtu.py`).
3. Publica `Factory.definition` como `ProtocolDefinition`: campos de conexión y de enlace con tipos, límites y etiquetas, normalización, validación, resumen y versión del enlace. Studio genera los formularios a partir de ella.
4. Regístralo con `register("protocol_id", Factory)` y añade la dependencia como extra opcional.
5. Prueba contra un servidor TCP real, incluidos fallos de conexión.

No añadas condiciones por protocolo en `project.py` ni en el editor: todo pasa por la definición. Si cambia el formato de enlace, sube su versión y añade una migración probada. No hay descubrimiento automático de plugins.

## Añadir un elemento gráfico

Añade el tipo a `KINDS`, a la validación del proyecto, a las herramientas de dibujo (`graphics.TOOL_NAMES`), al renderizador y a las pruebas. La representación es siempre datos JSON.

## Textos e idiomas

La interfaz se escribe en español y cada texto visible pasa por `tr()` de `abscada/i18n.py`. Las traducciones están en `src/abscada/locales/<idioma>.json`.

- Con datos: `tr("¿Eliminar la cuenta {name}?", name=name)`. Nunca una f-string dentro de `tr()`.
- Para un texto en un idioma distinto del activo, márcalo con `N_("…")` y tradúcelo con `i18n.load_catalog(código)`.
- No traduzcas claves, tipos, identificadores ni datos guardados en el proyecto.
- `script_runner.py` corre en otro proceso y no puede importar `tr`.

```powershell
.venv\Scripts\python tools/i18n_check.py               # textos sin traducir o sin uso
.venv\Scripts\python tools/i18n_check.py --leftovers   # literales en español fuera de tr()
.venv\Scripts\python tools/i18n_check.py --export en   # añade a en.json los textos nuevos, vacíos
.venv\Scripts\python tools/i18n_wrap.py <módulo.py>    # envuelve en tr() los textos de un módulo
```

`tests/test_i18n.py` falla si falta una traducción o no coinciden los marcadores `{…}`. Para añadir un idioma: `--export <código>`, traduce el archivo y añade el código a `LANGUAGES`. `ABSCADA_LANG=en` fuerza un idioma para probar.

## Cambiar el formato

Decide si es compatible con v1. Si no lo es, sube la versión e implementa una migración explícita con copia de seguridad, con un fixture del formato anterior y su prueba. Nunca conviertas en silencio un archivo desconocido ni deserialices código.

## Ejemplos y capturas

Los ejemplos se generan con `tools/build_hydro.py`, `build_brewery.py`, `build_beckhoff.py` y `build_showcase.py` (sus README se escriben a mano y se conservan). `src/abscada/example_translations.json` contiene sus textos en inglés. `examples/demo` es un proyecto mínimo para las pruebas.

`tools/capture_docs.py` regenera las capturas de `docs/img/` sobre copias temporales de los ejemplos y sus simuladores. Revísalas cuando cambie el renderizador; no sustituyen a las pruebas.

## Publicar una versión

Anota cada cambio visible en `CHANGELOG.md`, bajo `## [Sin publicar]` (*Añadido*, *Cambiado*, *Corregido*, *Seguridad*). Para publicar, con todo en commit en `main`:

```powershell
.\publicar-version.ps1 --beta --dry-run   # comprobar sin tocar nada
.\publicar-version.ps1 --beta             # 0.5.0b1 -> 0.5.0b2
.\publicar-version.ps1 --patch            # beta -> 0.5.0
.\publicar-version.ps1 0.6.0rc1 --watch   # versión explícita y seguir la compilación
```

`tools/release.py` comprueba que estás en `main`, sin cambios, al día y con notas; ejecuta las pruebas; cambia la versión en `__init__.py` y `pyproject.toml`; fecha el CHANGELOG; y, tras confirmar, hace commit, etiqueta `v…` y sube.

Después, `release.yml` comprueba que la etiqueta coincide con la versión, prueba, compila y prueba el `.exe`, genera SBOM, sumas SHA-256 y atestación, y publica la release con las notas del CHANGELOG (`a`, `b` y `rc` como pre-versión). Si falla, corrige y publica la siguiente versión: no reutilices etiquetas.

Para compilar el ejecutable en local:

```powershell
.venv\Scripts\python -m pip install -e ".[s7,modbus,opcua,serial]" pyinstaller
.venv\Scripts\python packaging/build_exe.py   # dist/abSCADA/abscada.exe y un ZIP
```

## Convenciones

Nombres de API en inglés; interfaz y documentación en español. Evita dependencias nuevas si Python o Qt ya lo resuelven. No prometas capacidades ni compatibilidad con CPU sin pruebas que lo respalden.
