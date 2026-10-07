# Librerías

En Studio, la sección **Librerías** agrupa los objetos reutilizables: símbolos y plantillas de equipo con parámetros (internamente siguen siendo *faceplates*: `faceplates/*.json` y elementos `kind: "faceplate"`). Tiene tres tipos de librería:

| Librería | Dónde vive | Edición |
| --- | --- | --- |
| **Proyecto** | `faceplates/` del proyecto, en carpetas (`folder` en cada objeto y `library_folders` en `project.json`) | Editable: clic derecho para crear objetos y carpetas, renombrar, duplicar y mover; también arrastrando |
| **Estándar (sistema)** | Dentro de la aplicación (`src/abscada/standard_library`), generada por `tools/build_standard_library.py` | Solo lectura. No se guarda en el proyecto: las pantallas solo guardan `estandar__<nombre>`. «Copiar al proyecto para modificarlo» crea una copia editable |
| **Externas** | Paquete `*.abscada-library.json` vinculado con un alias (ver abajo) | Solo lectura, con versión fija |

Para usar un objeto, **arrástralo desde el árbol al lienzo** o usa la herramienta *Objeto de librería*, que abre un selector con buscador. Si el objeto tiene parámetros, Studio pide la variable de cada uno.

La librería estándar contiene:
- **Gráficos**: símbolos SVG estáticos de depósitos, válvulas, bombas y motores, equipos de proceso, instrumentos (LT, PT, TT, FT) y aparamenta eléctrica.
- **Objetos**: símbolos animados con estilo ISA-101: gris parado o cerrado, verde en marcha o abierto, rojo fallo y ámbar calidad dudosa. Son la bomba, el motor y el ventilador (`marcha`, `fallo`), la válvula (`abierta`), el interruptor (`cerrado`; rojo cerrado y verde abierto, convención eléctrica) y el depósito con nivel (`nivel` en %).

Los recursos de la librería estándar se direccionan como `library://estandar/graficos/<símbolo>.svg` y también pueden usarse en imágenes propias. El prefijo `estandar__` y el alias `estandar` están reservados.

## Librerías externas

Una librería externa publica plantillas parametrizadas e imágenes para reutilizarlas en varios proyectos. Se vincula con un alias y una versión concreta. Cada instancia mantiene sus enlaces a variables del proyecto consumidor.

## Vincular y utilizar

1. Abre **Proyecto → Librerías externas…** y pulsa **Vincular…**.
2. Selecciona un archivo `*.abscada-library.json` y escribe un alias, por ejemplo `equipos`.
3. La librería aparece en el árbol, dentro de Librerías. Arrastra sus objetos (`equipos__unidad`, `equipos__valvula`…) al lienzo.
4. Asigna sus parámetros a variables compatibles, igual que con los objetos del proyecto.
5. Guarda con **Ctrl+S**. El vínculo participa en deshacer/rehacer, guardado único e historial Git.

El explorador muestra las bibliotecas agrupadas por alias y versión. Sus plantillas son de solo lectura: seleccionarlas abre el gestor, donde se muestran la versión, el origen, la huella y los parámetros. Las instancias se pueden mover, redimensionar y enlazar en las pantallas.

La biblioteca se incorpora como una instantánea completa a `libraries.json`, incluidas sus imágenes. La carpeta original puede desaparecer: el proyecto sigue abriendo y Runtime sigue usando la versión guardada. No hay actualizaciones automáticas ni lecturas de plantillas externas durante la ejecución. Copiar la carpeta completa del proyecto conserva sus dependencias.

## Crear y publicar

Desarrolla los faceplates locales en un proyecto normal de Studio, con sus parámetros, dinámicas y recursos. Usa una pantalla como banco de pruebas para enlazarlos a variables internas.

Desde **Bibliotecas… → Publicar biblioteca…** selecciona las plantillas, indica nombre, versión, autor y licencia, y elige un archivo nuevo. Publicar toma el estado actual de las plantillas en Studio. El paquete contiene JSON legible y recursos gráficos codificados en base64; no necesita instalar Python ni un plugin en el consumidor.

Las referencias de variables del componente deben ser parámetros `$nombre`. No se admiten dependencias implícitas de variables, scripts, pantallas o configuraciones de visor del proyecto de autoría. La publicación comprueba que las plantillas sean autónomas. Las imágenes normales y las imágenes de estados dinámicos se incluyen automáticamente. Los colores de paleta se convierten en sus valores concretos al publicar para que la biblioteca mantenga su aspecto en otros proyectos.

Los archivos ya publicados no se sobrescriben. Conserva el proyecto de autoría y publica cada revisión en un archivo nuevo, por ejemplo `equipos-1.1.0.abscada-library.json`. El nombre identifica la biblioteca; la versión identifica la revisión. Autor y licencia son metadatos introducidos por quien publica.

## Actualizar

Selecciona el vínculo y pulsa **Actualizar desde…**. Elige la nueva versión de la misma biblioteca. Se comprueban las plantillas y todos los enlaces de las instancias existentes antes de aplicar el cambio. Quitar un parámetro utilizado, cambiar su tipo, añadir uno obligatorio o eliminar una plantilla utilizada rechaza la actualización y conserva el estado anterior.

El alias permanece estable y las instancias reciben el nuevo diseño conservando sus variables. Un paquete diferente no puede reutilizar la misma versión de la biblioteca vinculada. Es posible seleccionar una versión anterior compatible para volver a ella.

La actualización queda pendiente de Ctrl+S y se puede deshacer. Un Runtime ya abierto conserva su copia hasta reiniciarlo con los cambios. El campo Origen sirve para localizar el archivo de actualización; si se ha movido, se puede elegir otro archivo.

**Desvincular** solo funciona cuando ninguna pantalla utiliza plantillas de esa biblioteca. El error enumera las pantallas afectadas. Retira o sustituye esas instancias antes de desvincular.

## Ejemplos incluidos

- `examples/library_author`: proyecto editable de autoría y banco de pruebas, con `unidad` y `valvula`.
- `examples/libraries/equipos-1.0.0.abscada-library.json`: paquete publicado, con sus SVG y estados dinámicos.
- `examples/showcase`: vínculo `equipos`; la unidad Siemens de «Faceplates y ventanas» utiliza `equipos__unidad`. La unidad interna utiliza una plantilla local para comparar ambos casos.

```powershell
.\run.ps1 examples/library_author
.\run.ps1 examples/showcase
```

## Formato y límites actuales

El formato de paquete `schema_version: 1` contiene `name`, `version`, `author`, `license`, `faceplates` y `assets`. `libraries.json` guarda un objeto por alias con `source`, `sha256` y el paquete completo. La huella comprueba integridad, no autenticidad del autor. Las plantillas vinculadas se resuelven en memoria con nombres `alias__plantilla` y no se duplican en la carpeta de faceplates locales.

Los recursos se resuelven mediante `library://alias/assets/...` y una caché temporal por contenido. No se extraen rutas suministradas por un paquete; se rechazan rutas absolutas, recorridos `..` y recursos ausentes. Al guardar, el paquete queda dentro de la misma transacción de archivos del proyecto.

Se mantienen los límites actuales del motor de faceplates: sin anidamiento de faceplates y sin visores de gráficas/alarmas dentro de una plantilla. Las bibliotecas no incorporan ejecución de scripts, dependencias entre bibliotecas ni sincronización automática con repositorios remotos. Es posible distribuir y versionar los archivos publicados mediante Git u otro sistema de archivos.
