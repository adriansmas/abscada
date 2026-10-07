# Autoría de Equipos de proceso

Abre este proyecto con `.\run.ps1 examples/library_author` desde la raíz del repositorio.

Objetos de librería locales:

- **unidad**: piloto, PV, entrada SP, marcha/paro y lista de textos. Parámetros `run: bool`, `pv: float`, `sp: float`.
- **valvula**: imagen SVG con estado abierto/cerrado y mando. Parámetro `run: bool`.

La pantalla principal sirve como banco de pruebas con tres variables internas. Edita las plantillas desde Librerías → Proyecto, guarda y prueba en Runtime. Para distribuirlas utiliza **Proyecto → Librerías externas… → Publicar biblioteca…**, nombre **Equipos de proceso** y una versión nueva, por ejemplo **1.1.0**.

El paquete inicial está en `examples/libraries/equipos-1.0.0.abscada-library.json`. El proyecto `examples/showcase` lo tiene vinculado como `equipos`. Allí puedes probar **Actualizar desde…** con el nuevo archivo.

Consulta [la guía de bibliotecas](../../docs/STUDIO.md).

## Idiomas y colores

El proyecto incluye español e inglés. Cambia el idioma de edición en Studio y el de operación desde Runtime; las traducciones se guardan junto a cada texto. Cada objeto utiliza colores HEX explícitos, editables en sus propiedades. Véase [la guía de Studio](../../docs/STUDIO.md#idiomas).
