# Modelo de amenazas

Método STRIDE sobre los límites de confianza de una instalación típica. Se revisa con cada cambio de arquitectura o de protocolo. Versión de octubre de 2026.

## Elementos y límites de confianza

```text
            Zona de oficina / IT                │   Zona de control (OT)
                                                │
  Cliente OPC UA (MES, historian) ──OPC UA──────┼──▶ abSCADA runtime ──S7 / Modbus / ADS──▶ PLC
  (certificado + usuario abSCADA)   cifrado     │     │  ▲   │
                                                │     │  │   └─ OPC UA cifrado ──▶ PLC S7-1500 / servidor OPC UA
  Ingeniero con Studio ─────────────────────────┼─────┘  │
  (edita el proyecto: JSON, scripts)            │        └─ Operador en el HMI (usuario y rol)
                                                │
                    Archivos del puesto: proyecto (versionado) · runtime/ (cuentas, secretos,
                    certificados, histórico SQLite) — no versionado, solo en ese equipo
```

| Límite | Qué lo cruza | Protección |
| --- | --- | --- |
| Operador → runtime | Mandos, consignas, ACK, scripts de botón | Sesión con usuario y rol; cierre por inactividad; auditoría |
| Red IT → servidor OPC UA | Lecturas y escrituras de clientes | Firma y cifrado; certificado del cliente aceptado expresamente; usuario con permiso «Acceso por OPC UA»; escritura solo con «Mandos y consignas»; anónimo desactivado por defecto |
| Runtime → PLC | Lecturas y órdenes | OPC UA cifrado cuando el PLC lo permite; S7 clásico y Modbus sin protección (aislar en la red) |
| Ingeniero → proyecto | JSON, scripts Python | Permisos del sistema de archivos y control de versiones Git; los scripts son código de confianza |
| Disco del puesto | Cuentas, secretos, claves privadas, histórico | Hash scrypt; DPAPI; claves con permisos restringidos; `runtime/` nunca va al repositorio |

## Amenazas (STRIDE)

| # | Tipo | Amenaza | Mitigación | Riesgo residual |
| --- | --- | --- | --- | --- |
| T1 | Suplantación | Alguien usa el HMI sin ser operador | Inicio de sesión, bloqueo por intentos, cierre por inactividad | Contraseñas compartidas en el turno: política del cliente |
| T2 | Suplantación | Un equipo se hace pasar por servidor OPC UA o PLC | Certificado del servidor en lista de confianza; ninguna aceptación automática | El operador acepta un certificado sin comprobar la huella |
| T3 | Suplantación | Un cliente OPC UA no autorizado se conecta | Certificado del cliente aceptado expresamente y usuario abSCADA | — |
| T4 | Manipulación | Órdenes falsas a un PLC por S7 clásico o Modbus desde la red | Fuera del alcance del SCADA: el protocolo no autentica. Segmentación y cortafuegos ([HARDENING.md](HARDENING.md)) | Alto si la red de control no está aislada |
| T5 | Manipulación | Modificar el proyecto o un script para que ejecute órdenes | Permisos de archivos, Git y revisión de cambios; Studio detecta ediciones externas | Un ingeniero malintencionado con acceso al proyecto |
| T6 | Manipulación | Sustituir el ejecutable o una actualización | Descarga por HTTPS, SHA-256 y atestación de procedencia | Sin firma Authenticode todavía |
| T7 | Repudio | Un usuario niega haber dado una orden | Auditoría con usuario, origen (HMI, OPC UA, script) y valor | El usuario de Windows con acceso al disco puede borrar el SQLite |
| T8 | Divulgación | Robo de contraseñas desde el disco | Solo hash scrypt; secretos de conexión con DPAPI | En Linux los secretos solo están protegidos por permisos de archivo |
| T9 | Divulgación | Escucha del tráfico de proceso | OPC UA con cifrado | S7 clásico y Modbus viajan en claro |
| T10 | Denegación de servicio | Saturar el servidor OPC UA o un PLC lento | Un trabajador por conexión; colas acotadas; timeouts | Sin limitación de sesiones OPC UA concurrentes (pendiente) |
| T11 | Denegación de servicio | Bloquear cuentas a base de contraseñas falsas | Bloqueo temporal, no permanente | Un atacante en la red puede bloquear a un operador unos minutos |
| T12 | Elevación de privilegios | Un operador obtiene permisos de gestión | Roles definidos en el proyecto; las cuentas solo se gestionan desde Studio | Quien edita `runtime/users.json` en el disco puede alterar roles: proteger el puesto |
| T13 | Elevación de privilegios | Un script de proyecto hace más de lo previsto | Proceso aparte sin acceso al runtime ni a Qt; sus escrituras pasan por las mismas validaciones | No es una sandbox: código de confianza |

## Supuestos

- El sistema operativo del puesto está actualizado y bastionado, y su sesión está protegida.
- La red de control está segmentada (zonas y conductos según la IEC 62443-3-3).
- Las funciones de seguridad de máquina y de personas no dependen del SCADA.
