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

**Variables** y su pestaña **Tipos de datos** definen primitivas (`bool`, `int`, `float`, `string`) y estructuras anidadas. Cada hoja tiene valor inicial, acceso, enlace y registro propios. **Enlace…** elige conexión y dirección con un formulario propio de cada protocolo. **Duplicar** crea la copia sin enlaces para que asignes sus direcciones.

En **Conexiones**, **Probar conexión** abre una conexión de solo lectura con el borrador y **Leer variable** muestra valor, calidad y hora de una dirección. Ninguna de las dos envía órdenes. En una conexión **Siemens S7 simbólico**, **Certificado del PLC… → Leer del PLC y confiar…** acepta el certificado del PLC mostrando sus huellas (o importa el exportado de TIA) y **Variables → Más → Importar símbolos del PLC…** crea variables a partir de los símbolos del PLC. Direcciones y límites: [PROTOCOLS.md](PROTOCOLS.md).

## Propiedades dinámicas

**Propiedades dinámicas** cambia visibilidad, habilitación y apariencia según variables, sin scripts. Cada condición tiene variable, operador, valor y comportamiento sin calidad válida.

La apariencia se aplica en este orden: propiedades del objeto, Normal, primer estado que se cumple, Sin comunicación y Deshabilitado. Los objetos invisibles no reciben clics; los deshabilitados pueden mostrar un motivo.

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

**Proyecto → Ajustes del proyecto… → Operación** configura monitor, modo, escalado y ventanas que se abren al arrancar. Las emergentes también admiten monitor y «siempre encima». Runtime recuerda posiciones por proyecto y puesto.

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

Los objetos propios viven en `faceplates/`. Sus parámetros son variables primitivas que sus elementos referencian como `$nombre`; cada instancia los asigna a variables compatibles. No admiten objetos de librería anidados ni visores.

- **Proyecto → Importar librería externa… → Publicar biblioteca…** genera un paquete `.abscada-library.json` nuevo con plantillas, imágenes y traducciones. Exige que las plantillas no dependan de variables, scripts ni pantallas del proyecto. No sobrescribe versiones publicadas.
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
