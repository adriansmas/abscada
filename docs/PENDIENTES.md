# Pendientes

Lista vigente, revisada el 10 de octubre de 2026. Las funciones implementadas se describen en las guías y en [CHANGELOG.md](../CHANGELOG.md), sin repetir aquí su historial.

## Validación y distribución

- Comprobar en GitHub Actions el resultado de la revisión publicada; matriz Windows/Linux con Python 3.11/3.14.
- Probar interfaz y protocolos en Linux y macOS con sesión gráfica real; añadir macOS a CI si se mantiene como plataforma soportada.
- Ensayar PLC físicos S7-1200/1500 (incluidas las lecturas S7 agrupadas), Beckhoff TwinCAT y servidor OPC UA de S7-1500.
- Ensayar Modbus RTU en un bus RS-485 real y la conexión serie en bruto con una báscula, por puerto COM y por conversor serie-Ethernet.
- Verificar varios monitores, DPI 125/150 %, entrada táctil y accesibilidad en puestos reales.
- Medir carga sostenida, histórico de meses y desconexiones antes de anunciar capacidades de tags o ciclos.
- Validar recuperación ante corte de alimentación y disco lleno.
- Instalador Windows, asociación `.abscada`, firma Authenticode y distribución Linux/macOS.
- Recoger una segunda ronda de pruebas de usabilidad con el probador.

## Comunicaciones

- Lecturas agrupadas en Modbus y ADS (*sum commands* ADS), con el contrato `prepare_reads` que ya usa S7.
- Suscripciones OPC UA y notificaciones ADS.
- Explorador de nodos OPC UA y tabla de símbolos ADS en Studio.
- Calidad stale, última lectura buena, calidad y hora del servidor en las muestras, métricas y confirmación correlacionada de órdenes.
- Lectura y escritura de arrays completos en un solo acceso (hoy cada elemento es una variable con su propia dirección); mantener límites documentados en [PROTOCOLS.md](PROTOCOLS.md).
- Enlace por estructura: una dirección base por variable de tipo estructura o array, y cada campo deriva la suya mediante un gancho opcional en `Factory.definition` (sin condiciones por protocolo en `project.py`); un enlace propio de un campo tiene prioridad.
  - OPC UA y ADS, por nombre: la base más la ruta relativa (`"DB_Valvulas"."V101"."Abierta"`, `MAIN.V101.Abierta`). Primer paso, sin ambigüedad.
  - S7: hecho al importar un DB desde su fuente de TIA Portal (Variables → Más → Importar DB de TIA Portal…), que calcula y guarda la dirección de cada campo. Falta guardar la base y el tipo PLC de cada campo para recalcular las direcciones si cambia el número de DB sin volver a importar.
  - Studio: el «Enlace…» de una estructura pide la base y muestra las direcciones resultantes para cotejarlas con TIA.
  - Importación desde TIA: tipos aún sin soporte (`LReal`, `String`, `Date_And_Time`, `SInt`, `Char`…) se omiten respetando su espacio; leer `Word`, `UInt`, `DWord` y `UDInt` sin signo; instancias de FB.
  - Integración opcional con TIA Portal Openness como complemento aparte, nunca en el paquete: requiere TIA Portal con licencia en el equipo del usuario y no se puede redistribuir `Siemens.Engineering.dll`. El núcleo debe funcionar con las fuentes exportadas.

## Ingeniería y operación

- Expresiones visuales compuestas y esquemas JSON para VS Code.
- Propiedades visuales parametrizadas y giro de objetos de librería completos.
- Shelving, alarmas PLC nativas y ACK asociado al PLC.
- Gestor genérico de recetas, informes y calendarios de tareas. La cervecería ya demuestra recetas gestionadas en su PLC.
- Zonas de aviso/alarma en el extremo bajo del indicador analógico.
- Límites de recursos y auditoría persistente de ejecuciones Python.
- Fusión de cambios externos y recuperación de una revisión completa tras corte de alimentación.

## Seguridad

- Activar seguridad de usuarios por defecto en proyectos nuevos antes de comercializar.
- Verificar/activar el aviso privado de vulnerabilidades en GitHub.
- Análisis estático en CI y pruebas de intrusión/fuzzing de conectores.
- Límites de sesiones OPC UA y autenticación corporativa si una instalación lo requiere.
- Asignar responsable, requisitos de seguridad y trazabilidad formal. Véase [SECURITY_DEVELOPMENT.md](SECURITY_DEVELOPMENT.md).
