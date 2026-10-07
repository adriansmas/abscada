# abSCADA · beta para pruebas

Gracias por probar abSCADA. Es un SCADA de escritorio libre en desarrollo: lo que encuentres ahora nos ahorra problemas en una planta de verdad.

## Instalar

1. Descomprime el ZIP en una carpeta propia, por ejemplo `C:\abSCADA`. No hace falta instalar Python ni nada más.
2. Ejecuta `abscada.exe`.
3. La primera vez, Windows puede mostrar **«Windows protegió su PC»**, porque el programa aún no está firmado. Pulsa **Más información → Ejecutar de todos modos**.

Los ejemplos abiertos desde la pantalla inicial se copian a `Documentos\abSCADA`. Los proyectos se guardan en la carpeta que elijas. La carpeta del programa no se modifica.

## Primeros pasos (15 minutos)

1. En la pantalla de inicio, abre el ejemplo **Central hidroeléctrica** con *Arrancar también su PLC simulado* marcado.
2. En Studio pulsa **▶ Abrir runtime**.
3. Ve a **Grupo 1 → ARRANCAR** y sigue la secuencia hasta *EN CARGA*.
4. Abre **Simulación (instructor)** y provoca una avería. Reconoce las alarmas.
5. Cierra el runtime, cambia algo en una pantalla de Studio, guarda (Ctrl+S) y vuelve a abrir el runtime.
6. Crea un **Nuevo proyecto** desde cero: una variable interna, un botón y un indicador.

Los PLC simulados también se arrancan y detienen desde **Herramientas → Simuladores de PLC…**.

## Qué nos interesa especialmente

- Cosas que **no se entienden** o que no están donde las buscarías.
- Pantallas que se ven mal: textos cortados, solapes o colores confusos.
- Cierres inesperados, ventanas que no responden o datos que no cuadran.
- Pasos de las guías que no coinciden con lo que ves.

## Cómo reportar un fallo

Para cada fallo indica:

- **Qué hacías:** los pasos para repetirlo.
- **Qué esperabas** y **qué pasó**.
- Una **captura** si es visual.
- El **registro**: menú **Ayuda → Abrir carpeta de registros** y adjunta `abscada.log`. Si apareció la ventana de *error inesperado*, copia también sus detalles.

Envíalo por correo o, si tienes acceso, como *issue* en el repositorio de GitHub.

## Limitaciones conocidas de esta beta

- Usuarios y roles desactivados por defecto: actívalos en Proyecto → Usuarios y roles (el ejemplo de la cervecería los trae activados con cuentas de demostración).
- Comunicación con S7, Modbus TCP, Beckhoff ADS y OPC UA probada con simuladores, todavía no con PLC físicos.
- Los tiempos del ejemplo hidroeléctrico están comprimidos a propósito: un arranque dura unos 40 s.
- abSCADA **no es un sistema de seguridad**: no lo uses para controlar equipos reales sin las protecciones propias del PLC.
