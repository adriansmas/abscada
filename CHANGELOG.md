# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Cada versión incluye una sección **Seguridad** cuando corrige vulnerabilidades o cambia el comportamiento de seguridad (requisito de divulgación del CRA y práctica SUM de la IEC 62443-4-1).

## [Sin publicar]

### Añadido
- **Arrays en tipos y variables:** un campo o una variable puede ser `float[8]`, `Motor[4]` o `float[2][3]` (hasta 1000 elementos). Cada elemento es una variable (`Motores[2].marcha`) con su valor inicial, acceso y enlace propios. Véase [PROJECT_FORMAT.md](docs/PROJECT_FORMAT.md#tipos-y-variables).
- **Parámetros de tipo estructura en objetos de librería:** un parámetro puede ser un tipo de datos o un array y se enlaza de una vez con una variable entera o una parte (`Bomba1`, `Bombas[2]`) en lugar de campo a campo. Basta con que tenga los mismos campos y tipos, así que un tipo del proyecto sirve para el tipo idéntico de una librería.
- **Objetos de librería anidados:** un objeto puede contener otros objetos y reenviarles sus parámetros (`$motor`, `$motor.marcha`), hasta 8 niveles y sin ciclos.
- **Librerías con tipos de datos (formato 2):** un paquete `.abscada-library.json` incluye los tipos de sus parámetros y los objetos anidados que usa. Se vinculan como `alias__Tipo`, de solo lectura. Los paquetes sin tipos se siguen publicando en formato 1.
- **Importar un DB de TIA Portal:** en Variables → Más → «Importar DB de TIA Portal…» se pega la fuente generada en TIA («Generar fuente a partir de bloques», con los UDT dependientes). El DB se crea como una variable estructurada con su nombre (`DB_Valvulas.V101.Abierta`), los UDT y `Struct` como tipos, los `Array[a..b]` con sus índices, los valores iniciales de la fuente y la dirección S7 de cada campo calculada para un DB no optimizado. Muestra una vista previa con avisos de lo que no se puede importar. Véase [STUDIO.md](docs/STUDIO.md#importar-un-db-de-tia-portal).
- **Ventana emergente según condiciones:** un botón «Abrir objeto en ventana» puede abrir otro objeto cuando se cumple una condición («Alternativas según condiciones…»); viajan con las librerías y siguen a los renombrados.
- **Índice variable en rutas:** `Juegos[Seleccion].Temp` muestra y escribe el elemento del array que indica una variable entera (dentro de un objeto, también un parámetro: `$juegos[$sel].temp`). La pantalla y las ventanas abiertas cambian de elemento en cuanto cambia el índice. Los campos de enlace de objetos admiten escribir la ruta a mano.
- **Renombrar tipos de datos:** desde su editor o con clic derecho → «Renombrar…»; cambia en las variables (también en arrays), en otros tipos y en los parámetros de los objetos.
- **Condiciones con «Y»:** visibilidad, habilitación, estados y giro continuo admiten varias condiciones que se tienen que cumplir todas.
- **Desplazar y escalar según una variable**, y **unidad y decimales de un texto, entrada o indicador tomados de variables** (también de parámetros de un objeto de librería).
- **Renombrar variables y campos:** clic derecho → «Renombrar…» (o «Renombrar campo…» en una estructura, o cambiando el nombre en Tipos de datos) actualiza pantallas, objetos, alarmas, registros, tendencias y enlaces PLC, y al renombrar un campo, todas las variables del tipo y los `$parametro.campo` de los objetos. Ofrece sustituir el nombre citado en los scripts, el historial grabado se sigue leyendo con el nombre nuevo y se deshace con Ctrl+Z. «¿Dónde se usa?» lista los usos y ya no se puede eliminar una variable en uso. Al reimportar un DB, la vista previa avisa de los campos en uso que desaparecen.
- **Carpetas de variables:** la lista de variables admite carpetas y subcarpetas (crear, renombrar, mover, eliminar subiendo su contenido, «Mover a carpeta»). Son organización de Studio: los nombres de las variables no cambian.
- **Arrays con índice inicial:** `int[1..10]` tiene índices de 1 a 10, como un `Array[1..10]` de Siemens.
- **Más dinámicas:** parpadeo de estados, giro según una variable, giro continuo mientras se cumple una condición y nivel de llenado sobre imágenes, rectángulos y elipses (en una imagen solo se colorea el dibujo, no su fondo transparente).
- **Conectores serie:** **Modbus RTU** (maestro con el esclavo en cada variable, lecturas agrupadas por esclavo; un esclavo que no responde solo marca sus variables) y **Serie / TCP en bruto** para básculas, lectores y equipos con protocolo propio (última trama, contador, petición y respuesta, envío de texto; el análisis de la trama se hace en scripts). Ambos funcionan por puerto COM o por un conversor serie-Ethernet en TCP. Necesitan el extra `serial` (pyserial), incluido en el `.exe`. Véase [PROTOCOLS.md](docs/PROTOCOLS.md#puerto-serie).
- **Scripts sin límite de tiempo:** cada script puede tener su propio límite o ninguno. Los que no tienen límite corren en paralelo hasta terminar; `ctx.commit()` y `ctx.sleep()` aplican escrituras durante la ejecución.
- **Calidad desde scripts y alarma «Sin datos válidos»:** `ctx.set_quality()` marca una variable interna como `bad` o `uncertain` sin cambiar su valor, y la condición de alarma `bad_quality` avisa mientras una variable no tiene un dato bueno.
- **Botones con varias acciones:** la acción «Lista de acciones» ejecuta con un clic varias acciones en orden (escribir valor, alternar, ejecutar script, cambiar idioma y, como última, abrir o cerrar pantallas). Se editan en Studio con «Editar acciones…». Antes de enviar nada se comprueban todas; las acciones no esperan al script ni a la confirmación del PLC.
- **Carpetas de scripts:** la lista de Scripts admite carpetas y subcarpetas (crear, renombrar, eliminar subiendo su contenido, arrastrar o «Mover a carpeta»). Son organización de Studio: los archivos siguen en `scripts/` y las referencias no cambian. Los selectores de script muestran la carpeta.
- **Renombrar scripts** desde Studio actualiza botones, listas de acciones, eventos de inicio, aperturas de pantalla y tareas, y avisa de los scripts que mencionan el nombre como texto. Eliminar un script en uso indica dónde se usa.

### Cambiado
- **Pantalla completa en el runtime:** la pantalla se escala de borde a borde, sin margen ni barras de desplazamiento; si el monitor tiene otra proporción, el hueco sobrante es oscuro en lugar de blanco. En pantalla completa se oculta la barra de estado (salvo con usuarios activados) y sus mensajes aparecen superpuestos.
- **Lecturas S7 agrupadas:** cada ciclo lee en una sola petición los bytes contiguos de un DB en lugar de una petición por variable; los bits de un mismo byte se leen una vez. El tamaño de bloque se ajusta al PDU negociado. Calidad, errores, reconexión y escrituras se comportan igual que antes.
- **Ejemplos y documentación simplificados:** quedan cuatro ejemplos en la pantalla de inicio (central hidroeléctrica, cervecería, banco Beckhoff y laboratorio); se retiran `plant`, `s7` y `library_author`. Las guías se reorganizan sin repeticiones y las capturas se reducen a seis, generadas con `tools/capture_docs.py`.

### Corregido
- `tools/validate_library.py` rechazaba las listas de acciones (`actions`) y otras propiedades válidas: ahora usa la misma lista de propiedades que el Studio.

## [0.5.0b5] - 2026-10-08

### Cambiado
- **Idiomas del proyecto más fáciles de usar:** el desplegable de idioma de la barra superior tiene la opción «＋ Añadir idioma…» (lista de idiomas comunes u otro código), y Ajustes del proyecto → General sustituye los códigos separados por comas por una lista con casillas y un idioma por defecto. Quitar un idioma elimina sus traducciones.

## [0.5.0b4] - 2026-10-08

### Cambiado
- **Variables → pestaña «Forzado»:** escribe el valor de cualquier variable con escritura permitida mientras el runtime está en marcha (valor actual en vivo, Intro para escribir), sin pantallas ni scripts.
- En el runtime, un campo de entrada se edita en el propio campo (un clic, Intro para escribir, Esc para cancelar) en lugar de abrir una ventana emergente.
- La lista de variables se lee mejor: filas alternas más marcadas y fila seleccionada con texto oscuro sobre fondo azul claro.
- Los objetos de librería se pueden colocar sin que existan sus variables: el parámetro queda «(sin asignar)» y se enlaza después en el panel de propiedades. «Revisar el proyecto» avisa de los que sigan sin asignar, y en el runtime un mando sin variable lo explica en lugar de fallar.
- Los visores de tendencias y de alarmas se maquetan al tamaño real del elemento y escalan de forma uniforme con la pantalla; sus barras de herramientas y selectores de curvas se reparten en varias líneas. Una tendencia admite hasta 64 ejes (antes 8) y tantas curvas como se quiera.
- Los simuladores de PLC pasan de `src/abscada` a `tools/plc_simulators` y siguen incluidos en el .exe (`abscada --simulador <id>`). Eliminado código sin uso y las utilidades `tools/hydro_plc.py`, `hydro_map.py`, `showcase_plcs.py`, `create_s7_demo.py` y `capture_review_fixes.py`.

## [0.5.0b3] - 2026-10-07

### Cambiado
- Retirado el botón verde «+ Crear» de Studio; los documentos se crean desde el menú contextual del árbol.
- Retiradas las paletas de colores: cada objeto y estado conserva su HEX explícito. Los ocho ejemplos y generadores usan colores locales; las referencias de proyectos antiguos se convierten al abrirlos.
- Documentación revisada: menús actuales, layouts, protocolos implementados, persistencia, credenciales y ejecución desde macOS.
- Documentación agrupada: `docs/` pasa de 23 a 9 Markdown, con guías únicas de Studio y operación, referencias técnicas e índice en README. Eliminados los informes antiguos y actualizados los enlaces y capturas.
- El runtime espera hasta 30 s, en lugar de 5, a que el archivo SQLite esté listo al arrancar: en discos lentos o con el antivirus revisando archivos nuevos fallaba sin motivo.
- **«Faceplates» pasa a llamarse «Librerías»**, y cada plantilla, «objeto de librería». El formato de archivo no cambia (`faceplates/*.json`), así que los proyectos existentes abren igual. «Bibliotecas de faceplates» pasa a ser «Librerías externas».

### Añadido
- **Studio, ronda de usabilidad:** un contenedor de pantalla puede existir sin pantalla asociada (se diseña primero el layout); «Nueva pantalla» pide solo el nombre y deriva de él el archivo; clic derecho sobre un elemento del lienzo con copiar, orden, alinear, agrupar, bloquear, propiedades dinámicas y suprimir.
- Variables: la última fila de la lista es donde se escribe una variable nueva (Intro para crear), con numeración, tipo editable en la propia fila y clic derecho para insertar encima o debajo, mover o eliminar. Tipos de datos y conexiones tienen numeración y menú contextual; los tipos, también fila de alta.
- Propiedades dinámicas: las condiciones sobre variables booleanas piden solo «Verdadero / Falso» (antes «igual a» y «distinto de» decían lo mismo).
- Scripts: la pantalla explica para qué sirven, crea scripts escribiendo el nombre en la última línea y tiene menú contextual; «Scripts al abrir la pantalla» remite a la sección Scripts si aún no hay ninguno. «Librerías externas» explica cómo importar una librería y se alcanza también desde el árbol del proyecto.
- **Idiomas por proyecto** con traducciones junto a cada texto, fallback, idioma de edición, tabla con filtro e intercambio CSV, cambio en runtime y scripts, preferencias por puesto/usuario y alarmas históricas traducidas. Los ocho ejemplos incluyen español e inglés.
- **Studio y el runtime en inglés**: **Ayuda → Idioma / Language** elige el idioma de la aplicación (español o inglés), que se aplica al volver a abrirla. Es un ajuste del usuario, independiente de los proyectos. Catálogo en `src/abscada/locales/en.json` y herramientas `tools/i18n_check.py` e `tools/i18n_wrap.py`.
- **Librería estándar del sistema** (solo lectura, viene con la aplicación y no se copia al proyecto): carpeta **Gráficos** con 35 símbolos SVG (depósitos, válvulas, bombas y motores, proceso, instrumentos y eléctrico) y carpeta **Objetos** con versiones animadas (bomba, motor y ventilador con marcha y fallo; válvula abierta o cerrada; interruptor; depósito con nivel). «Copiar al proyecto» crea una copia editable.
- **Carpetas en la librería del proyecto**: crear, renombrar, eliminar y arrastrar objetos entre carpetas (`library_folders` en `project.json`).
- **Insertar objetos arrastrándolos** desde el árbol de Librerías al lienzo, o con el selector con buscador de la herramienta «Objeto de librería».
- Las imágenes SVG se dibujan vectorialmente: nítidas a cualquier tamaño y zoom.
- Ejemplo **Microcervecería La Tolva** (`examples/brewery`): cocción por lotes con recetas, tres fermentadores, servicios y panel del instructor. Lee el PLC por **OPC UA cifrado**, publica sus variables con el servidor OPC UA propio y trae los **usuarios y roles** activados. Simulador `abscada --simulador cerveceria`.
- Permiso `recipes` («Recetas y parámetros de proceso»): ningún control lo pide por defecto; se asigna con `permission` a las entradas y botones que deben quedar reservados.

### Seguridad
- **Las cuentas pasan a formar parte del proyecto**: `users.json`, versionado y copiado con él, en lugar de `runtime/users.json` en cada puesto. Solo contiene huellas scrypt. Los intentos fallidos y los bloqueos ya no se escriben en disco: viven en la memoria del runtime. Las cuentas existentes se mueven solas la primera vez. Quien tenga el proyecto o su repositorio tiene las huellas: usa contraseñas largas y protege el repositorio.
- **Las contraseñas de las conexiones y los certificados OPC UA también van en el proyecto**: `secrets.json` (codificado en base64, no cifrado: el runtime tiene que enviar la contraseña al PLC) y `pki/`. Al copiar el proyecto a otro PC, los PLC siguen confiando en él. El URI de aplicación pasa a depender de la carpeta del proyecto en lugar del nombre del equipo, así que el primer arranque genera un certificado nuevo que los PLC y clientes deben volver a aceptar. Los datos de `runtime/` de 0.5.0b2 se mueven solos; las contraseñas cifradas con DPAPI solo se recuperan en el equipo y la cuenta de Windows que las guardaron.

## [0.5.0b2] - 2026-10-07

### Añadido
- **Usuarios y roles** (Proyecto → Usuarios y roles). Política en `security.json` y cuentas por instalación en `runtime/users.json` (hash scrypt). El runtime arranca sin sesión y pide usuario para mandos, consignas, scripts y reconocimiento de alarmas. Incluye bloqueo por intentos, cierre por inactividad y cambio de contraseña en el primer acceso.
- Auditoría con el usuario real y el origen de cada orden (HMI, OPC UA o script), órdenes denegadas e inicios de sesión.
- **Cliente OPC UA** como conector: firma y cifrado por defecto, certificados por instalación con listas de confianza y contraseña cifrada con DPAPI fuera del proyecto.
- **Servidor OPC UA** (Proyecto → Servidor OPC UA) que publica las variables. Inicio de sesión con cuentas abSCADA y escrituras como órdenes auditadas.
- Propiedad `permission` en botones y entradas para exigir un permiso concreto.
- Cadena de suministro: `pip-audit` en CI, SBOM CycloneDX, `SHA256SUMS.txt` y atestación de procedencia en cada versión, y Dependabot.
- Documentación: [SECURITY.md](SECURITY.md), [docs/SECURITY_DEVELOPMENT.md](docs/SECURITY_DEVELOPMENT.md), [docs/SECURITY_DEVELOPMENT.md](docs/SECURITY_DEVELOPMENT.md) y [docs/HARDENING.md](docs/HARDENING.md).

### Seguridad
- La seguridad de usuarios está **desactivada por defecto** para no cambiar el comportamiento de los proyectos existentes. Actívala en las instalaciones reales ([docs/HARDENING.md](docs/HARDENING.md)).
