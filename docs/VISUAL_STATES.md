# Estados visuales y trabajo de ingeniería

## Bomba con marcha y paro superpuestos, sin código

1. En Variables, crea `Marcha` de tipo `bool`, inicial Falso y acceso de escritura. Si va a operar un PLC, configura su conexión y dirección mediante Enlace. Para practicar la composición gráfica no hace falta enlazar un equipo.
2. Inserta un Botón, escribe MARCHA, selecciona la variable y elige **Escribir valor**, con `true` como valor. En **Condiciones y estados → Visibilidad**, activa «Cuando se cumpla», variable `Marcha`, operador Igual a, valor Falso.
3. Duplica el botón, cambia el texto a PARO y el valor de escritura a `false`. Cambia su condición de visibilidad a Verdadero. Pon las mismas coordenadas en ambos. En diseño puedes seleccionarlos por separado desde **Objetos**.
4. Inserta un Piloto con la misma variable. En **Condiciones y estados → Piloto**, configura los colores de Falso, Verdadero y sin calidad válida.
5. Abre **Prueba visual**, selecciona `Marcha`, alterna Falso/Verdadero y aplica el estado. Cambia también la calidad. Se utiliza el mismo evaluador y renderizador que en operación.
6. Guarda el proyecto. Abre Runtime para operar. Si modificas el proyecto con Runtime abierto, aparece **Cambios posteriores al arranque** y **Reiniciar con cambios**. El reinicio interrumpe la sesión y pide confirmación; guardar no reinicia la ejecución.

Prueba visual es una ventana de previsualización de pantallas, con una copia de los valores y la calidad que introduces. No crea un Runtime, no usa adaptadores, no ejecuta scripts, no escribe históricos y no envía órdenes. Los botones no modifican esos valores; se modifican con los controles de prueba. Los visores de alarmas y gráficas se representan como marcadores, sin cargar datos de proceso. Studio conserva su lienzo de diseño sin valores vivos.

## Condiciones y apariencia

Visibilidad y habilitación son condiciones independientes. Una condición admite variable, operador y valor tipado. Booleanos y textos admiten igual/distinto; números también mayor, menor e inclusivos. Por defecto, una condición no se cumple si falta la muestra o su calidad no es buena. La opción de mala calidad permite cambiar ese comportamiento explícitamente. Esto no elimina la protección de escritura a variables PLC sin lectura válida.

Un objeto invisible no recibe clics en Runtime. Un objeto deshabilitado conserva su presencia y muestra el motivo configurado en el tooltip. Las condiciones se conservan al guardar, duplicar y deshacer; admiten parámetros `$nombre` dentro de faceplates. Las condiciones de una instancia también limitan a sus objetos hijos.

En **Estados**, las reglas se evalúan en orden: se aplica la primera coincidente. La apariencia base se combina con Predeterminado, el estado coincidente, Mala calidad y Deshabilitado, en ese orden. Un campo vacío conserva el valor anterior. Se muestran únicamente las propiedades compatibles con el tipo de objeto: texto/fondo/borde en controles textuales, trazo/relleno en formas, trazo en tuberías, colores de pilotos o imagen por ruta del proyecto. Los contenedores, faceplates y visores ofrecen condiciones; no ofrecen estilos que sus widgets ignorarían.

Los datos con calidad mala o incierta conservan el último valor e incorporan `!` y un tooltip con su calidad. Las cifras, unidades y textos de botones se ajustan al ancho disponible, sin añadir frases dentro de su caja. Un valor antiguo no se presenta como una lectura válida.

## Colores exactos y reutilizables

Los campos cromáticos admiten HEX y un selector con controles RGB. La muestra y el tooltip permiten consultar el color resultante. La flecha junto a la muestra ofrece colores de la paleta y colores recientes del usuario.

**Paleta** define nombres y colores del proyecto y muestra las rutas de las referencias afectadas. `@Marcha` es una referencia compartida; `#147d75` es una excepción local. Cambiar el color compartido actualiza todas sus referencias en Studio y se puede deshacer. Runtime usa su copia hasta reiniciarlo. Las referencias a colores eliminados se rechazan al validar, en lugar de sustituirse silenciosamente.

**Orden → Copiar formato / Pegar formato** copia propiedades visuales compatibles, sin cambiar variables ni acciones. **Copiar solo colores** limita la copia a propiedades cromáticas y colores del piloto. La selección múltiple permite aplicar dimensiones, fuentes o colores comunes de una vez. Los valores diferentes aparecen vacíos; solo se modifica el campo editado. Cada operación se deshace en un paso.

## Pulsadores y eventos de escritura

**Pulsador momentáneo (1 / 0)** escribe Verdadero al pulsar y Falso al soltar una variable booleana. **Escribir al pulsar y soltar** permite dos valores tipados diferentes, por ejemplo códigos enteros de mando. Ambas acciones respetan la habilitación y los permisos del tag.

La liberación se solicita también al soltar fuera, perder el foco de la ventana, perder la captura del ratón, navegar, cerrar, ocultarse el objeto o dejar de cumplirse su permiso. Una pérdida de calidad cancela el gesto. Si no hay comunicación, se informa de que no pudo enviarse la liberación y no se programa su reproducción tras reconectar.

Antes de cerrar la comunicación, la ventana espera hasta dos segundos por sus liberaciones pendientes y registra los fallos. La confirmación es del transporte, no del estado físico del equipo. Una pérdida de red, cierre forzado o corte de alimentación puede impedir liberar el mando: el PLC debe implementar el tiempo máximo/permisivo que corresponda a esa orden. El botón no sustituye esa lógica del controlador.

## Variables, estructuras y diagnóstico

Los formularios validan antes de cerrarse y mantienen el borrador al fallar. Los booleanos usan Falso/Verdadero. Los campos numéricos aceptan coma o punto decimal y rechazan formatos mezclados y separadores de miles.

Al elegir un tipo estructurado aparece su árbol de campos, también para estructuras anidadas. Cada hoja tiene valor inicial y acceso de escritura. Después puedes asignar la conexión y ubicación de cada campo desde la tabla de variables. **Duplicar** muestra los enlaces originales para revisión y crea la copia sin direcciones PLC, evitando copiar mandos inadvertidamente a la misma dirección.

El selector de variables ofrece búsqueda, jerarquía, tipo, acceso y ubicación. Marca las incompatibles; el desplegable rápido ofrece las compatibles. La validación identifica pantalla y objeto cuando una escritura apunta a un tag de solo lectura. **Revisar** también enumera mandos todavía sin variable y propiedades no reconocidas.

En el formulario de una conexión, **Probar conexión** realiza una conexión de lectura independiente con la configuración del borrador de Studio. En el formulario de un tag, **Leer variable** comprueba su dirección y muestra valor, calidad y hora. No se escriben variables. Si hay runtime, su muestra se identifica por separado; la tabla de conexiones muestra su estado e indica cuándo ejecuta otra configuración.

## Objetos y espacio de trabajo

En **Objetos**, el menú contextual permite bloquear, ocultar solo en diseño, añadir nombre descriptivo, agrupar y desagrupar. La ocultación de edición no se guarda como una condición del runtime. Los objetos ocultos siguen en la lista y pueden seleccionarse allí. El bloqueo impide mover o redimensionar con ratón; sus propiedades se pueden editar expresamente en el inspector.

Los grupos comparten selección y desplazamiento; su movimiento con cuadrícula conserva las posiciones relativas. Duplicar genera un grupo independiente. Son grupos de objetos del documento, no nuevas instancias de faceplate ni grupos anidados.

La caja de herramientas se pliega y se filtra por categoría o nombre completo. Panel compacto reduce la barra lateral. La división del inspector, el estado plegado y la densidad se conservan por usuario; no ensucian los archivos del proyecto.
