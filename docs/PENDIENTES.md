# Pendientes

Lista viva, revisada el 5 de octubre de 2026. Ordenada por lo que hace falta para entregar una **beta en .exe** a un compañero, y después por producto. Marca con `[x]` lo terminado.

## Fase 0 · Base de trabajo (ahora)

- [ ] **Git y GitHub.** Instalar Git, crear el repositorio, `.gitignore` completo (artifacts, datos de runtime, `.claude/`), primer commit y subida a GitHub privado.
- [ ] **CI en GitHub Actions.** `tests.yml` existe (Windows y Linux, Python 3.11/3.14) pero nunca se ha ejecutado. Ver que pasa en Linux; los 2 tests de Git fallan aquí solo porque no hay Git instalado.
- [ ] **Decidir dónde se desarrolla** (Windows o Linux) y clonar allí.

## Fase 1 · Beta en .exe para pruebas externas

### Bloqueantes para el ejecutable
- [ ] **Scripts dentro del .exe.** `script_runner` lanza un intérprete Python aparte; en un ejecutable congelado `sys.executable` es el propio .exe. Hay que relanzar el .exe en «modo ejecutor de scripts».
- [ ] **Arranque sin rutas relativas.** Sin argumentos se abre `examples/plant` relativo al directorio actual. Debe abrir una pantalla de inicio (proyectos recientes, nuevo, abrir, ejemplos).
- [ ] **Ejemplos y recursos empaquetados.** Incluir `examples/` en el paquete y copiarlos a *Documentos* del usuario al abrirlos, para no escribir en *Program Files*.
- [ ] **Simuladores accesibles sin Python.** S7, central hidroeléctrica y ADS como `abscada.exe --simulador hydro|s7|ads` o desde un menú *Herramientas → Simuladores*, para que el probador pueda usar los ejemplos.
- [ ] **Empaquetado con PyInstaller** en modo carpeta (`onedir`): arranca más rápido y da menos falsos positivos de antivirus que `onefile`. Icono, versión y metadatos del ejecutable. Comprobar que entran PySide6, python-snap7 (`snap7.dll`) y pyModbusTCP.
- [ ] **Compilación del .exe en CI** (runner de Windows) que publique un ZIP descargable en cada versión etiquetada.

### Proyecto como archivo (en lugar de carpeta)
- [ ] **Archivo principal `.abscada`.** El usuario abre `MiPlanta.abscada`; la carpeta con pantallas y scripts queda al lado, como en TIA Portal o Visual Studio. Se mantiene el formato abierto (JSON legible, Git y VS Code).
- [ ] **Nuevo proyecto con «Guardar como»**: nombre del archivo y carpeta creada automáticamente.
- [ ] **Abrir** con filtro `*.abscada` (y `project.json` de proyectos antiguos), **proyectos recientes** y apertura por línea de comandos o doble clic.
- [ ] **Asociación de la extensión** `.abscada` al instalar (en Fase 2, con instalador).
- [ ] **Migración** de proyectos existentes: los ejemplos actuales y los de los usuarios siguen abriendo.

### Para que el probador pueda reportar
- [ ] **Registro de errores** en un archivo (`%LOCALAPPDATA%\abSCADA\logs`) y diálogo de error con «Copiar detalles» en lugar de cierres silenciosos.
- [ ] **Acerca de** con versión y fecha de compilación.
- [ ] **Guía de prueba** de una página para el compañero: qué probar y cómo reportar (issue en GitHub con plantilla).

## Fase 2 · Producto

### Comunicaciones
- [ ] **Probar ADS con un PLC Beckhoff real** (TwinCAT 3 y, si es posible, TwinCAT 2): rutas, estructuras y cambio de programa en caliente.
- [ ] **Probar S7 con un PLC físico**: S7-1200/1500 con acceso PUT/GET y DB no optimizados.
- [ ] **Lecturas agrupadas**: rangos de DB en S7, *sum commands* en ADS y bloques de registros en Modbus. Ahora se lee variable a variable, lo que limita a pocos cientos de variables por equipo.
- [ ] Notificaciones ADS, calidad *stale*, `last_good_timestamp`, métricas y benchmarks de carga.
- [ ] OPC UA (diseñado en PROTOCOLS.md, sin implementar).
- [ ] Explorar la tabla de símbolos del PLC desde Studio (ADS) para no escribir los nombres a mano.

### Ingeniería y operación
- [ ] Usuarios, roles y autorización; ACK con identidad real.
- [ ] Copiar y pegar entre documentos; esquemas JSON para VS Code.
- [ ] Faceplates anidados y propiedades visuales parametrizadas.
- [ ] Alarmas: *shelving*, alarmas nativas del PLC y ACK enlazado al PLC.
- [ ] Recetas, informes y calendarios de tareas.
- [ ] Indicador analógico: zonas de aviso y alarma en el extremo bajo (presiones mínimas).

### Calidad
- [ ] Ejecutar la suite en Linux y verificar la interfaz con una sesión gráfica real.
- [ ] Ensayos sostenidos: muchas variables, histórico de meses, desconexiones con hardware real.
- [ ] Recuperación ante corte de alimentación durante el guardado.
- [ ] Instalador Windows (Inno Setup) y paquete Linux (AppImage).

