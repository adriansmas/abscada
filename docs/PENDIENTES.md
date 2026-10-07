# Pendientes

Lista vigente, revisada el 7 de octubre de 2026. Las funciones implementadas se describen en las guías y en [CHANGELOG.md](../CHANGELOG.md), sin repetir aquí su historial.

## Validación y distribución

- Comprobar en GitHub Actions el resultado de la revisión publicada; matriz Windows/Linux con Python 3.11/3.14.
- Probar interfaz y protocolos en Linux y macOS con sesión gráfica real; añadir macOS a CI si se mantiene como plataforma soportada.
- Ensayar PLC físicos S7-1200/1500, Beckhoff TwinCAT y servidor OPC UA de S7-1500.
- Verificar varios monitores, DPI 125/150 %, entrada táctil y accesibilidad en puestos reales.
- Medir carga sostenida, histórico de meses y desconexiones antes de anunciar capacidades de tags o ciclos.
- Validar recuperación ante corte de alimentación y disco lleno.
- Instalador Windows, asociación `.abscada`, firma Authenticode y distribución Linux/macOS.
- Recoger una segunda ronda de pruebas de usabilidad con el probador.

## Comunicaciones

- Lecturas agrupadas en S7, Modbus y ADS; *sum commands* ADS.
- Suscripciones OPC UA y notificaciones ADS.
- Explorador de nodos OPC UA y tabla de símbolos ADS en Studio.
- Calidad stale, última lectura buena, métricas y confirmación correlacionada de órdenes.
- Ampliar tipos/arrays cuando haya requisitos concretos; mantener límites documentados en [PROTOCOLS.md](PROTOCOLS.md).

## Ingeniería y operación

- Expresiones visuales compuestas y esquemas JSON para VS Code.
- Objetos de librería anidados y propiedades visuales parametrizadas.
- Shelving, alarmas PLC nativas y ACK asociado al PLC.
- Gestor genérico de recetas, informes y calendarios de tareas. La cervecería ya demuestra recetas gestionadas en su PLC.
- Zonas de aviso/alarma en el extremo bajo del indicador analógico.
- Ejecutor de scripts persistente para reducir el coste de lanzar el `.exe` en cada tarea.
- Límites de recursos y auditoría persistente de ejecuciones Python.
- Fusión de cambios externos y recuperación de una revisión completa tras corte de alimentación.

## Seguridad

- Activar seguridad de usuarios por defecto en proyectos nuevos antes de comercializar.
- Verificar/activar el aviso privado de vulnerabilidades en GitHub.
- Análisis estático en CI y pruebas de intrusión/fuzzing de conectores.
- Límites de sesiones OPC UA y autenticación corporativa si una instalación lo requiere.
- Asignar responsable, requisitos de seguridad y trazabilidad formal. Véase [SECURITY_DEVELOPMENT.md](SECURITY_DEVELOPMENT.md).
