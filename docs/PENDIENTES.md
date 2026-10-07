# Pendientes

Lista viva, revisada el 6 de octubre de 2026. Ordenada por lo que hace falta para entregar una **beta en .exe** a un compañero, y después por producto. Marca con `[x]` lo terminado.

## Fase 0 · Base de trabajo (ahora)

- [x] **Git y GitHub.** Instalar Git, crear el repositorio, `.gitignore` completo (artifacts, datos de runtime, `.claude/`), primer commit y subida a GitHub privado.
- [ ] **CI en GitHub Actions.** `tests.yml` existe (Windows y Linux, Python 3.11/3.14) pero nunca se ha ejecutado. Ver que pasa en Linux; los 2 tests de Git fallan aquí solo porque no hay Git instalado.
- [ ] **Decidir dónde se desarrolla** (Windows o Linux) y clonar allí.

## Fase 1 · Beta en .exe para pruebas externas

### Bloqueantes para el ejecutable
- [x] **Scripts dentro del .exe.** `script_runner` lanza un intérprete Python aparte; en un ejecutable congelado `sys.executable` es el propio .exe. Hay que relanzar el .exe en «modo ejecutor de scripts».
- [x] **Arranque sin rutas relativas.** Sin argumentos se abre `examples/plant` relativo al directorio actual. Debe abrir una pantalla de inicio (proyectos recientes, nuevo, abrir, ejemplos).
- [x] **Ejemplos y recursos empaquetados.** Incluir `examples/` en el paquete y copiarlos a *Documentos* del usuario al abrirlos, para no escribir en *Program Files*.
- [x] **Simuladores accesibles sin Python.** S7, central hidroeléctrica y ADS como `abscada.exe --simulador hydro|cerveceria|s7|ads` o desde un menú *Herramientas → Simuladores*, para que el probador pueda usar los ejemplos.
- [x] **Empaquetado con PyInstaller** en modo carpeta (`onedir`): arranca más rápido y da menos falsos positivos de antivirus que `onefile`. Icono, versión y metadatos del ejecutable. Hecho: `packaging/build_exe.py`, 133 MB en carpeta; python-snap7 3.x es Python puro (sin DLL).
- [x] **Compilación del .exe en CI** (runner de Windows) que publique un ZIP descargable en cada versión etiquetada.

### Proyecto como archivo (en lugar de carpeta)
- [x] **Archivo principal `.abscada`.** El usuario abre `MiPlanta.abscada`; la carpeta con pantallas y scripts queda al lado, como en TIA Portal o Visual Studio. Se mantiene el formato abierto (JSON legible, Git y VS Code).
- [x] **Nuevo proyecto con «Guardar como»**: nombre del archivo y carpeta creada automáticamente.
- [x] **Abrir** con filtro `*.abscada` (y `project.json` de proyectos antiguos), **proyectos recientes** y apertura por línea de comandos o doble clic.
- [ ] **Asociación de la extensión** `.abscada` al instalar (en Fase 2, con instalador).
- [x] **Migración** de proyectos existentes: los ejemplos actuales y los de los usuarios siguen abriendo.

### Para que el probador pueda reportar
- [x] **Registro de errores** en un archivo (`%LOCALAPPDATA%\abSCADA\logs`) y diálogo de error con «Copiar detalles» en lugar de cierres silenciosos.
- [x] **Acerca de** con versión y fecha de compilación.
- [x] **Guía de prueba** de una página para el compañero: qué probar y cómo reportar (issue en GitHub con plantilla).

### Detectado al probar el .exe (beta 0.5.0b1)
- [ ] **Ejecutor de scripts persistente.** En el .exe cada ejecución relanza el ejecutable (~0,7 s frente a ~0,1 s con Python). Con tareas de 1 s funciona, pero gasta CPU. Mantener un proceso hijo vivo que reciba las peticiones por la tubería.
- [ ] **Simuladores: ubicación definitiva.** Hoy van en el mismo .exe (`--simulador`, menú *Simuladores…*). Para 1.0, etiquetarlos como *herramientas de formación* o separarlos en `abscada-simuladores.exe` opcional en el instalador.
- [ ] **Firma de código** para evitar el aviso de SmartScreen («Windows protegió su PC»).
- [ ] **Modo consola**: el .exe es de ventana, así que `--validate` y `--headless` no muestran salida. Añadir un `abscada-cli.exe` o mostrar el resultado en un diálogo.
- [ ] Plantilla de *issue* en GitHub para los reportes de la beta.
- [x] **Simulador hidráulico en el .exe** se cerraba al escribir «→» en su registro (cp1252). Salida en UTF-8.

### Revisión de usabilidad (6 de octubre de 2026, con el primer probador)
- [x] Menú Archivo / Edición / Proyecto / Herramientas / Ayuda; barra corta (Guardar, Deshacer, Rehacer).
- [x] Barra lateral de secciones; «Tipos de datos» como pestaña de Variables.
- [x] Pantallas en carpetas, layout como pantalla normal, renombrar / duplicar / eliminar pantallas y faceplates.
- [x] Tendencias y visores de alarmas se configuran desde su control (sin sección «Gráficas» ni pestaña «Visores»).
- [x] Copiar / cortar / pegar entre pantallas.
- [x] «Ajustes del proyecto»: pantalla de inicio, tamaño de pantallas, monitores, escalado del runtime (maximizado por defecto) y retención.
- [x] Inspector sin «Aplicar propiedades»; «Propiedades dinámicas» con una sola página de apariencia; JSON en «Avanzado».
- [x] Filtros de las listas separados de los botones, con aviso de filas ocultas; aviso «Cambios sin guardar».
- [ ] Rehacer las capturas de Studio del README con la interfaz nueva.
- [ ] Probar con el probador la nueva versión y recoger una segunda ronda de comentarios.

## Fase 2 · Producto

### Comunicaciones
- [ ] **Probar ADS con un PLC Beckhoff real** (TwinCAT 3 y, si es posible, TwinCAT 2): rutas, estructuras y cambio de programa en caliente.
- [ ] **Probar S7 con un PLC físico**: S7-1200/1500 con acceso PUT/GET y DB no optimizados.
- [ ] **Lecturas agrupadas**: rangos de DB en S7, *sum commands* en ADS y bloques de registros en Modbus. Ahora se lee variable a variable, lo que limita a pocos cientos de variables por equipo.
- [ ] Notificaciones ADS, calidad *stale*, `last_good_timestamp`, métricas y benchmarks de carga.
- [x] OPC UA: cliente (conector) y servidor, con seguridad, certificados y usuarios. Ver PROTOCOLS.md.
- [ ] OPC UA: suscripciones en el cliente, explorador de nodos en Studio y **ensayo con una S7-1500 real** (servidor integrado y su licencia).
- [ ] Explorar la tabla de símbolos del PLC desde Studio (ADS) para no escribir los nombres a mano.

### Ingeniería y operación
- [x] Usuarios, roles y autorización; ACK con identidad real; auditoría con usuario y origen.
- [ ] Activar la seguridad por defecto en el asistente de nuevo proyecto (requisito del CRA: configuración segura por defecto).
- [ ] Copiar y pegar entre documentos; esquemas JSON para VS Code.
- [ ] Faceplates anidados y propiedades visuales parametrizadas.
- [ ] Alarmas: *shelving*, alarmas nativas del PLC y ACK enlazado al PLC.
- [ ] Recetas, informes y calendarios de tareas.
- [ ] Indicador analógico: zonas de aviso y alarma en el extremo bajo (presiones mínimas).

### Seguridad (IEC 62443-4-1 y CRA, ver SECURITY_DEVELOPMENT.md)
- [x] Fase 1: SECURITY.md, modelo de amenazas, guía de bastionado, CHANGELOG, `pip-audit`, SBOM, sumas y atestación de procedencia, Dependabot.
- [ ] Activar en GitHub el aviso privado de vulnerabilidades (Settings → Code security).
- [ ] Análisis estático en CI (CodeQL o Bandit).
- [ ] Firma Authenticode del ejecutable.

### Calidad
- [ ] Ejecutar la suite en Linux y verificar la interfaz con una sesión gráfica real.
- [ ] Ensayos sostenidos: muchas variables, histórico de meses, desconexiones con hardware real.
- [ ] Recuperación ante corte de alimentación durante el guardado.
- [ ] Instalador Windows (Inno Setup) y paquete Linux (AppImage).

