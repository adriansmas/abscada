# Evolución del proyecto

## 0.1 — MVP implementado

Editor de pantallas, tabla filtrable de variables, estructuras, faceplates parametrizados, JSON por documento, runtime sin Qt, comunicación S7 DB y servidor PLC simulado, validación y pruebas.

## 0.2 — Studio y Runtime separados (implementado)

Nueva interfaz de ingeniería con navegación lateral, caja de herramientas visible, inserción por clic y drag/drop, inspector sin JSON como paso habitual, deshacer/rehacer, selección múltiple, duplicado, cuadrícula, redimensionado, zoom y preview de faceplates. Formularios para variables, tipos, conexiones y dimensiones/parámetros de documentos.

Las estructuras se muestran como grupos desplegables, con jerarquía anidada, filtrado y edición de enlaces por campo. Se admite dirección Siemens absoluta `%DB1.DBW0`, con el DB configurado en cada variable. El editor reúne la navegación en un explorador y mantiene el inspector visible con propiedades de pantalla u objeto.

Runtime abre una ventana independiente, sin herramientas de diseño, sobre una copia aislada del proyecto. Studio sigue editable y nunca muestra valores en vivo en el lienzo. La operación también puede iniciarse directamente con `--runtime`.

Pendiente de ingeniería: copiar/pegar entre documentos, expresiones visuales compuestas, esquemas JSON para VS Code, recuperación automática tras corte de alimentación y fusión de cambios externos.

## 0.3 — Adquisición escalable

Implementado: trabajador, ciclo y cola por conexión; metadatos de configuración y enlace por protocolo; enlaces estructurados; Modbus TCP con áreas, codificación y orden de bytes/registros; integración S7 y Modbus simultánea y prueba de aislamiento ante conexión bloqueada.

Pendiente: lecturas agrupadas DB/registros, freshness y last-good timestamp, métricas, benchmarks, confirmación correlacionada, cancelación de operaciones activas y pruebas de desconexión durante una escritura. OPC UA y TwinCAT ADS requieren suscripciones/notificaciones y configuración de sesión propias; el diseño se recoge en PROTOCOLS.md.

## 0.4 — Funciones SCADA (implementadas parcialmente)

Implementado: alarmas digitales/numéricas, categorías, prioridades, histéresis y retardos, ocurrencias y eventos persistentes, ACK y recuperación; ficheros de registro con frecuencia común, asignación única por variable y particiones SQLite diarias, retención y backup; tendencias con curvas/ejes configurables, visibilidad, consulta, cursor, zoom y CSV; visores incrustados, gráficas en tiempo real independientes del registro, consulta histórica entre días, navegación mediante botones del proyecto y auditoría básica de escrituras.

Pendiente: usuarios/roles y autorización, shelving, alarmas PLC nativas, pruebas de pérdida de energía/disco lleno y benchmarks de carga/archivo.

## 0.5 — Componentes y programación

Implementado: eventos de inicio y apertura de pantallas, scripts invocados desde botones, tareas cíclicas, editor Python, proceso de ejecución separado con timeout, diagnóstico, guardado conjunto con detección de cambios externos y versiones Git locales.

Pendiente: calendarios diarios/semanales, límites de recursos del sistema, auditoría persistente de scripts, faceplates anidados, propiedades visuales parametrizadas y versionado de bibliotecas. Los scripts actuales son código de confianza del proyecto; el proceso independiente no es una sandbox de seguridad.

## 1.0 — Distribución y validación industrial

Paquetes Windows/Linux, actualizaciones y migraciones, matriz de CPUs/protocolos realmente probados, comunicación segura como adaptador específico y documentación operacional. Evaluar servicio runtime separado y clientes remotos según requisitos medidos. No asignar fecha de 1.0 hasta definir criterios de aceptación y validar instalaciones reales.

## Decisiones que requieren contexto de producto

- Familias exactas de CPU Siemens, configuración y cantidad de PLC simultáneos.
- Cantidad de tags, frecuencias de adquisición y latencia de operación esperada.
- Solo escritorio o también servicio sin sesión gráfica y clientes web.
- Alarmas/históricos requeridos y retención.
- Modelo de usuarios y permisos.
- Lenguaje y alcance de programación para pantallas.
- Política de distribución de la aplicación y proyectos de terceros.

Estas decisiones no bloquean el MVP, pero condicionan el diseño de las siguientes versiones.

Implementado en el editor: líneas, polilíneas, tuberías con vértices editables, rectángulos y elipses, ocho tiradores, capas, alineación, cuadrícula por documento, propiedades de pantalla y estilo de texto.


## Revisión de ingeniería visual — implementada

Condiciones de visibilidad y habilitación por tag, reglas ordenadas de apariencia, colores de piloto y paleta compartida, preview aislado, acciones al pulsar/soltar, edición múltiple, copia de formato, grupos y marcas de edición. Formularios tipados y estructuras anidadas sin JSON, validación conservando borradores y diagnóstico de lectura desde el formulario. Véase FERNANDO_REVIEW_RESOLUTION.md para trazabilidad y verificaciones externas pendientes.
