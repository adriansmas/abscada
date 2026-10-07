# abSCADA

SCADA de escritorio libre **GPL-3.0-or-later**, construido con Python y PySide6. Studio diseña proyectos y Runtime los opera en otra ventana, con Siemens S7, Modbus TCP, Beckhoff TwinCAT ADS y OPC UA, usuarios y roles, alarmas persistentes, históricos SQLite y tendencias. Los proyectos son JSON abiertos con un manifiesto `.abscada`.

## Instalar desde el código

Requiere Git, Python **3.11 o posterior** y una sesión gráfica.

```bash
git clone https://github.com/adriansmas/abscada.git
cd abscada
```

En Windows, desde PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,s7,modbus,opcua]"
.venv\Scripts\python -m abscada
```

En macOS o Linux:

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,s7,modbus,opcua]'
.venv/bin/python -m abscada
```

Comprueba que `python3` sea 3.11 o posterior. Linux necesita las bibliotecas de sistema de Qt. Verificado localmente en Windows; falta validar la interfaz y los protocolos en Linux y macOS. CI configura Windows/Linux, Python 3.11/3.14; no incluye macOS. Una clonación solo incluye lo publicado en GitHub, no cambios locales pendientes.

## Probar un proyecto

Sin argumentos se abre la pantalla de inicio. Elige un ejemplo y **Arrancar también su PLC simulado**: trabajarás sobre una copia en Documentos. En Studio pulsa **Abrir runtime**. Los simuladores también se gestionan desde **Herramientas → Simuladores de PLC…**.

Para abrir un proyecto directamente, con el Python de tu entorno:

```bash
python -m abscada examples/brewery
python -m abscada examples/brewery --runtime
```

El primer comando abre Studio; el segundo, solo Runtime. Si no has activado el entorno, sustituye `python` por `.venv/bin/python` en macOS/Linux o `.venv\Scripts\python` en Windows. En PowerShell puedes usar `./run.ps1 examples/brewery`.

| Ejemplo | Qué permite probar |
| --- | --- |
| `examples/demo` y `examples/s7` | Controles básicos y comunicación S7 con `python -m abscada --simulador s7` |
| `examples/plant` | Bombeo, layouts, ventanas, alarmas, registros y scripts sobre S7 |
| [Laboratorio](examples/showcase/README.md) | Variables internas, estados, dibujo, librerías y S7/Modbus |
| [Central hidroeléctrica](examples/hydro/README.md) | Secuencias, protecciones, tres PLC S7, contador Modbus y varios monitores |
| [Cervecería La Tolva](examples/brewery/README.md) | Recetas en el PLC, fermentación, OPC UA cifrado, usuarios y roles |
| [Banco Beckhoff](examples/beckhoff/README.md) | Comunicación ADS sin instalar TwinCAT en el puesto SCADA |
| [Autoría de equipos](examples/library_author/README.md) | Crear, publicar y actualizar objetos de librería |

Los ocho proyectos incluyen español e inglés y colores HEX explícitos por objeto. La cervecería tiene botones ES/EN y cuentas de demostración documentadas en su guía. Su primera conexión requiere aceptar el certificado del PLC simulado después de comprobar su huella.

Studio muestra diseño sin valores de proceso; Runtime usa una copia del proyecto. Guardar no cambia una ejecución abierta: reinicia para aplicar el diseño nuevo. Las conexiones sin PLC o simulador marcan calidad mala y conservan el último valor; no inventan lecturas.

![Studio: composición de pantallas](docs/editor-layout.png)

## Documentación

| Necesito… | Leer |
| --- | --- |
| Diseñar, usar librerías, traducir y guardar | [Guía de Studio](docs/STUDIO.md) |
| Operar alarmas, históricos, gráficas y scripts | [Guía de operación](docs/OPERATIONS.md) |
| Editar JSON o crear paquetes de librería | [Referencia de formato](docs/PROJECT_FORMAT.md) |
| Configurar PLC y direcciones | [Protocolos](docs/PROTOCOLS.md) |
| Desarrollar, probar o publicar | [Desarrollo](docs/DEVELOPMENT.md) |
| Saber qué falta | [Pendientes](docs/PENDIENTES.md) |
| Preparar una instalación protegida | [Bastionado](docs/HARDENING.md) |
| Revisar amenazas y el proceso de seguridad | [Desarrollo seguro](docs/SECURITY_DEVELOPMENT.md) |

La [guía breve de la beta](docs/BETA.md) acompaña al ejecutable Windows. [CHANGELOG.md](CHANGELOG.md) recoge cambios por versión y [SECURITY.md](SECURITY.md) el procedimiento de comunicación de vulnerabilidades.

## Ejecutable Windows

```powershell
.venv\Scripts\python -m pip install -e ".[s7,modbus,opcua]" pyinstaller
.venv\Scripts\python packaging/build_exe.py
```

Genera `dist/abSCADA/abscada.exe` y un ZIP con versión. La publicación mediante etiquetas `v*` se describe en Desarrollo. El ejecutable aún no tiene firma Authenticode ni instalador.

## Límites y licencia

Faltan validación con PLC físicos, carga sostenida, suscripciones OPC UA, notificaciones ADS, objetos de librería anidados, redundancia y un gestor genérico de recetas. Los scripts Python son código de confianza; su proceso separado no es una sandbox. abSCADA no sustituye las protecciones ni funciones de seguridad del PLC.

Código propio [GPL-3.0-or-later](LICENSE). Las dependencias y recursos de terceros mantienen sus licencias; la licencia del motor no determina automáticamente la de los proyectos de usuario. No se incorporan código ni recursos de AVEVA.
