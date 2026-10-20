# Guía de Studio

Studio edita el proyecto; Runtime lo opera en otra ventana sobre una copia tomada al arrancar. Puedes seguir diseñando mientras Runtime funciona, pero los cambios se aplican al reiniciarlo. El lienzo de Studio muestra marcadores neutros, nunca valores de proceso.

## Crear y organizar

Sin argumentos, abSCADA muestra proyectos recientes y ejemplos. **Archivo → Nuevo proyecto…** crea una carpeta con un manifiesto `.abscada` y sus documentos JSON.

- Clic derecho en **Proyecto → Pantallas**: nueva pantalla o carpeta, renombrar, duplicar, eliminar y **Usar como pantalla de inicio**. Arrastra pantallas entre carpetas.
- **Librerías → Proyecto**: objetos reutilizables, con el mismo menú.
- **Elementos**: objetos de la pantalla abierta, del fondo al frente. Sirve para seleccionar objetos solapados, bloquearlos, ocultarlos solo en diseño, describirlos y agruparlos.

**Proyecto → Ajustes del proyecto…** reúne nombre, pantalla inicial, idiomas, tamaño propuesto para pantallas nuevas, escalado de las existentes, monitores y retención.

## Dibujar

Inserta con clic o arrastra una herramienta al lienzo. El inspector muestra las propiedades de la pantalla o de la selección.

| Gesto | Resultado |
| --- | --- |
| Clic en un objeto | Seleccionar sin mover |
| Arrastrar un objeto seleccionado | Mover |
| Ctrl+clic o rectángulo | Selección múltiple |
| Tiradores | Redimensionar |
| Flechas / Shift+flechas | Mover 1 px / un paso de cuadrícula |
| Ctrl+rueda / botón central | Zoom / desplazar |
| Esc o clic en el fondo | Volver a las propiedades de pantalla |

Líneas: clic en origen y destino. Polilíneas y tuberías: clic por vértice; Enter, doble clic o botón derecho termina, Retroceso quita el último punto y Shift restringe a horizontal/vertical. Las tuberías conservan tramos ortogonales y no crean enlaces de proceso.

**Orden**, **Alinear**, **Duplicar**, copiar/pegar y deshacer/rehacer actúan sobre la selección. Con selección múltiple, el inspector muestra las propiedades comunes; un campo vacío no sobrescribe nada hasta que lo editas. **Orden → Copiar formato / Pegar formato** repite un estilo sin tocar variables ni acciones.

Los colores son explícitos en cada objeto y estado: `#RRGGBB` o `#AARRGGBB`. No hay paleta compartida; los proyectos antiguos con paleta se convierten a HEX al abrirlos.

## Variables y conexiones

**Variables** y su pestaña **Tipos de datos** definen primitivas (`bool`, `int`, `float`, `string`), estructuras anidadas y arrays. Un array se escribe en el campo Tipo como `float[8]` o `Motor[4]`, tanto en un campo de un tipo como en una variable; sus elementos aparecen como `Motores[2].marcha`. Cada hoja tiene valor inicial, acceso, enlace y registro propios. **Enlace…** elige conexión y dirección con un formulario propio de cada protocolo. **Duplicar** crea la copia sin enlaces para que asignes sus direcciones.

Las variables se ordenan en **carpetas** (clic derecho → Nueva carpeta, Mover a carpeta, Renombrar, Mover o Eliminar carpeta). Son solo organización: el nombre de una variable no cambia y debe ser único en todo el proyecto. Eliminar una carpeta sube su contenido a la carpeta superior.

### Renombrar y buscar usos

Clic derecho sobre una variable → **Renombrar…**, o sobre un campo de una estructura → **Renombrar campo…** (también cambiando su nombre en la tabla de **Tipos de datos**). Antes de aplicar, abSCADA muestra cuántos usos se actualizarán y dónde. Cambian a la vez:

- pantallas y objetos de librería: variables de los elementos, condiciones, estados, giro y nivel, pasos de botones y enlaces de instancias y ventanas emergentes;
- alarmas, ficheros de registro y curvas de tendencia;
- los enlaces PLC de los campos (las direcciones no cambian);
- al renombrar un campo, todas las variables de ese tipo, sus valores iniciales y los `$motor.campo` de los objetos cuyos parámetros son de ese tipo.

El historial ya grabado se sigue mostrando con el nombre nuevo. Los scripts no se reescriben solos: el diálogo lista los que citan el nombre entre comillas y ofrece sustituirlo en ellos; revísalos si construyen nombres por partes. Si el servidor OPC UA está activo, avisa de que los clientes externos verán el nombre nuevo. Se deshace con Ctrl+Z.

**¿Dónde se usa?** lista los usos de una variable o de una parte de ella. **Eliminar** se niega mientras la variable se use en algún sitio.

### Importar un DB de TIA Portal

**Más → Importar DB de TIA Portal…** (o clic derecho sobre una carpeta) crea un DB completo de una vez:

1. En TIA Portal, clic derecho sobre el DB → **Generar fuente a partir de bloques** → **Incluir todos los bloques dependientes**. El archivo contiene los UDT (`TYPE`) y el DB (`DATA_BLOCK`).
2. Pega su texto en el diálogo (o ábrelo con **Abrir archivo de fuente…**), elige la conexión S7, el número de DB y la carpeta.
3. Revisa la vista previa (variable, tipo PLC, tipo, dirección y valor inicial) y los avisos, y acepta.

El DB se crea como **una variable estructurada con su nombre**, así las rutas son las de TIA: `DB_Valvulas.V101.Abierta`, `DB_Valvulas.Niveles[1]`. Cada UDT y cada `Struct` anónimo pasan a ser tipos de datos (un `Struct` se llama `<Padre>_<campo>`), los `Array[a..b]` conservan sus índices y los valores iniciales salen de las declaraciones y de la sección `BEGIN`. Las direcciones se calculan con la disposición de un DB **no optimizado**: bools bit a bit, bytes en el byte siguiente y lo demás, cada estructura y cada array en byte par.

- Un DB con acceso optimizado no tiene direcciones absolutas: se importa la estructura sin enlaces. Desactiva «Acceso optimizado al bloque» en TIA Portal o enlázalo por OPC UA.
- `Bool`, `Byte`, `USInt`, `Int`, `Word`, `UInt`, `DInt`, `DWord`, `UDInt`, `Time` (milisegundos) y `Real` se importan. `Word`, `UInt`, `DWord` y `UDInt` se leen con signo. El resto (`LReal`, `String`, `Date_And_Time`…) se omite con aviso, pero su espacio se respeta para que los campos siguientes tengan su dirección correcta.
- **Sustituir** actualiza una variable o un tipo que ya existan con el mismo nombre (por ejemplo tras cambiar el DB en TIA). Sin marcarlo, la importación se niega a sobrescribir.
- No se importan instancias de FB ni bloques de código.

En **Conexiones**, **Probar conexión** abre una conexión de solo lectura con el borrador y **Leer variable** muestra valor, calidad y hora de una dirección. Ninguna de las dos envía órdenes. Direcciones y límites: [PROTOCOLS.md](PROTOCOLS.md).

## Propiedades dinámicas

**Propiedades dinámicas** cambia visibilidad, habilitación y apariencia según variables, sin scripts. Cada condición tiene variable, operador, valor y comportamiento sin calidad válida.

La apariencia se aplica en este orden: propiedades del objeto, Normal, primer estado que se cumple, Sin comunicación y Deshabilitado. Un estado marcado **Parpadear** alterna su apariencia con la normal una vez por segundo. Los objetos invisibles no reciben clics; los deshabilitados pueden mostrar un motivo.

La pestaña **Giro y nivel** añade:

- **Girar según una variable**: el ángulo sigue al valor entre un mínimo y un máximo (una válvula de mariposa, una aguja).
- **Girar continuamente**: una vuelta cada N segundos mientras se cumple una condición (un ventilador o un agitador en marcha).
- **Nivel de llenado** (imágenes, rectángulos y elipses): pinta el nivel sobre la propia figura; en una imagen SVG o PNG solo se colorea el dibujo, no el fondo transparente.

**Herramientas → Prueba visual…** permite introducir valores y calidad a mano para revisar el resultado. No conecta PLC, no ejecuta scripts ni escribe históricos.

Ejemplo, dos botones superpuestos MARCHA/PARO sobre la misma variable bool: MARCHA escribe `true` y es visible cuando la variable es falsa; PARO escribe `false` y es visible cuando es verdadera.

**Lista de textos → Configurar textos…** relaciona valores exactos con rótulos. Con lectura válida sin coincidencia muestra el texto por defecto; con calidad mala, `—`.

## Botones

Cada botón tiene una acción: escribir un valor, alternar, pulsador momentáneo, pulsar/soltar, abrir pantalla, abrir emergente o faceplate emergente, cerrar emergente, ejecutar script, cambiar idioma o **Lista de acciones**.

**Lista de acciones** hace varias cosas con un clic. **Editar acciones…** permite añadir, quitar y reordenar. Abrir o cerrar pantallas solo puede ser la última acción y los pulsadores momentáneos no admiten lista. Orden de envío y fallos: [PROJECT_FORMAT.md](PROJECT_FORMAT.md#botones-y-acciones).

**Abrir faceplate emergente** abre un objeto de librería en su propia ventana, una por equipo. Dentro de una plantilla, el botón puede reenviar sus parámetros `$nombre`, así cada símbolo abre la ventana de su equipo.

## Layouts, ventanas y monitores

Un layout es una pantalla normal con contenedores:

1. Crea pantallas de cabecera, menú y contenido.
2. En la pantalla de composición, inserta **Contenedor de pantalla** y asigna a cada zona ID, tamaño y pantalla inicial.
3. En los botones de navegación, elige **Abrir pantalla** y **Abrir en**: un contenedor, Zona actual o Ventana completa.
4. Marca la composición como pantalla de inicio.

Hay un solo nivel: una pantalla alojada no puede tener contenedores. Todas las zonas y ventanas comparten adquisición, alarmas y registros.

**Proyecto → Ajustes del proyecto… → Operación** configura monitor, modo, escalado y ventanas que se abren al arrancar. En **Pantalla completa** la pantalla ocupa todo el monitor: la barra de estado se oculta y sus mensajes aparecen superpuestos abajo; solo se mantiene si el proyecto tiene usuarios, porque lleva el botón de sesión. Las emergentes también admiten monitor y «siempre encima». Runtime recuerda posiciones por proyecto y puesto.

**Abrir runtime** arranca en la pantalla seleccionada; `--runtime` usa la de inicio. **Reiniciar con cambios** aplica lo guardado, interrumpiendo la sesión.

## Alarmas

- **Alarmas → Categorías**: ID, nombre y color. Los visores filtran por categoría.
- **Alarmas → Alarmas**: ID, mensaje, variable, categoría, condición, umbral, histéresis, prioridad (1000 es la más alta), retardos de entrada y salida, ACK obligatorio y habilitación.

El comportamiento en operación está en [OPERATIONS.md](OPERATIONS.md#alarmas). No reutilices el ID de una alarma para otro proceso: su histórico se mezclaría.

## Registros, tendencias y visores de alarmas

**Registros** crea ficheros con ID, nombre, intervalo en milisegundos y variables. En **Variables**, el desplegable **Registro** de cada hoja asigna un fichero o Ninguno; una variable solo puede estar en un fichero. La retención se configura en días.

Los controles **Tendencia** y **Alarmas** se insertan desde las herramientas de dibujo. Cada uno recibe su configuración al insertarlo; **Configurar…** o doble clic la edita, y el selector permite reutilizar otra. En una tendencia se eligen variables, colores, grosores y de 1 a 64 ejes. En un visor de alarmas, título, modo inicial, categorías, prioridad mínima, columnas y si permite ACK.

Mostrar una variable en una tendencia no la registra: para ver su pasado tiene que estar en un registro.

## Librerías

El árbol reúne **Proyecto** (editable), **Estándar** (símbolos SVG y objetos animados incluidos en la aplicación, de solo lectura) y librerías externas vinculadas. Arrastra un objeto al lienzo o usa el selector; **Copiar al proyecto** crea una variante editable.

Los objetos propios viven en `faceplates/`. Sus parámetros (**Ajustes de pantalla / plantilla**) son primitivos, tipos de datos o arrays; sus elementos los referencian como `$nombre` o, por partes, `$motor.marcha` y `$motor.temps[0]`. Cada instancia los asigna a variables compatibles: un parámetro `Bomba` se enlaza de una vez con `Bomba1`, o con `Bombas[2]`, en lugar de campo a campo. Vale cualquier variable con los mismos campos y tipos, aunque tenga campos de más.

Un objeto puede contener otros objetos de librería: arrástralos a su lienzo y enlaza sus parámetros con los del objeto que los contiene (`$motor`, `$motor.marcha`). No admiten ciclos, visores ni contenedores.

- **Proyecto → Importar librería externa… → Publicar biblioteca…** genera un paquete `.abscada-library.json` nuevo con plantillas, imágenes, traducciones y los tipos de datos de sus parámetros; añade solos los objetos anidados o abiertos en ventana que usan. Exige que las plantillas no dependan de variables, scripts ni pantallas del proyecto. No sobrescribe versiones publicadas. Los tipos vinculados aparecen como `alias__Tipo`, de solo lectura, y las variables del proyecto pueden usarlos.
- **Vincular…** fija una copia del paquete con alias y huella SHA-256; funciona sin el archivo original.
- **Actualizar desde…** comprueba la compatibilidad con todas las instancias antes de aplicar.
- **Desvincular** exige resolver antes las instancias que lo usan.

La huella verifica integridad, no autoría. Formato del paquete: [PROJECT_FORMAT.md](PROJECT_FORMAT.md#librerías).

## Idiomas

El idioma de Studio, el de edición y el de Runtime son independientes.

- **Ayuda → Idioma / Language** cambia Studio al volver a abrirlo.
- **Proyecto → Ajustes del proyecto…** declara los idiomas del proyecto, el de por defecto y de dónde sale el inicial (proyecto, puesto o usuario).
- El selector de idioma de la barra superior cambia el idioma en que se ven y editan los textos.

Cada traducción vive junto a su texto; si falta, se usa el idioma por defecto. **Proyecto → Textos del proyecto…** muestra todos los textos con una columna por idioma y un filtro **Sin traducir**, y exporta e importa CSV UTF-8 con BOM (compatible con Excel). Los textos de librerías vinculadas y estándar son de solo lectura. Identificadores, unidades y datos del PLC no se traducen.

## Guardar y versionar

**Ctrl+S** guarda todo el proyecto, incluidos scripts y traducciones. El asterisco del título indica cambios sin guardar.

El guardado valida, bloquea guardados concurrentes, rechaza sobrescribir cambios hechos por otro editor y, si falla una escritura, restaura los archivos anteriores. No es una transacción frente a cortes de alimentación. Si la restauración también falla, deja una carpeta `.abscada-recovery-*` con tu trabajo; no la borres antes de recuperarlo. Si un cierre anormal deja `.abscada-save.lock`, bórralo solo tras comprobar que no hay otro guardado activo.

Si otro programa cambia los archivos, revisa tus cambios y usa **Archivo → Recargar desde disco**; no hay fusión automática.

**Archivo → Versiones del proyecto… → Activar Git** (requiere Git en PATH) hace un commit en cada guardado con cambios. No configura remoto ni hace push. Se versiona todo salvo `runtime/`, incluidas cuentas, contraseñas de conexión y certificados: **protege la carpeta y el repositorio** ([HARDENING.md](HARDENING.md)).
