# Desarrollo seguro (IEC 62443-4-1 y Cyber Resilience Act)

Este documento describe **cómo se desarrolla y mantiene** abSCADA desde el punto de vista de la seguridad, y qué parte de las exigencias de la IEC 62443-4-1 y del Reglamento (UE) 2024/2847 (CRA) se cumple hoy. **No es una certificación**: es la base para preparar una auditoría (TÜV, ISASecure SDLA u otra) cuando el proyecto la necesite.

Estado: fase 1 (prácticas sin coste). Revisión: octubre de 2026.

## Prácticas de la IEC 62443-4-1

| Práctica | Qué pide | Qué se hace hoy | Pendiente |
| --- | --- | --- | --- |
| **SM** Gestión de la seguridad | Proceso definido, responsables, gestión de componentes de terceros, entorno de desarrollo protegido | Este documento; dependencias fijadas en `requirements-lock.txt`; Dependabot; CI en GitHub con permisos mínimos (`contents: read`) | Nombrar responsable de seguridad; formación registrada; revisar el proceso una vez al año |
| **SR** Requisitos de seguridad | Contexto de uso, modelo de amenazas, requisitos de seguridad del producto | [SECURITY_DEVELOPMENT.md](SECURITY_DEVELOPMENT.md); requisitos implícitos en usuarios, roles, auditoría y OPC UA | Lista formal de requisitos con nivel objetivo (SL1/SL2) y trazabilidad a pruebas |
| **SD** Seguro por diseño | Defensa en profundidad, superficie mínima, revisión del diseño | Mínimo privilegio por roles; seguridad OPC UA con firma y cifrado por defecto; certificados nunca aceptados automáticamente; cuentas solo con huella scrypt | Revisión de diseño documentada para cada cambio grande |
| **SI** Implementación segura | Normas de codificación, análisis estático, revisión de código | Revisiones en cada cambio; contraseñas con scrypt y comparación en tiempo constante; mensajes de error que no revelan cuentas | Análisis estático en CI (por ejemplo Bandit/CodeQL); guía de codificación escrita |
| **SVV** Verificación y validación | Pruebas de requisitos de seguridad, de amenazas, de vulnerabilidades y de intrusión | Pruebas automáticas de autenticación, bloqueo, permisos, auditoría, confianza de certificados OPC UA y escrituras denegadas (`tests/test_security*.py`, `tests/test_opcua.py`); `pip-audit` en CI | Fuzzing de los conectores; prueba de intrusión externa antes de 1.0 |
| **DM** Gestión de problemas de seguridad | Recibir, evaluar y resolver vulnerabilidades | [SECURITY.md](../SECURITY.md): canal privado, plazos, gravedad CVSS | Activar el aviso privado de vulnerabilidades en GitHub; registro interno de incidencias |
| **SUM** Gestión de actualizaciones | Actualizaciones verificadas, publicadas a tiempo, con información | Versiones con SBOM, `SHA256SUMS.txt` y atestación de procedencia firmada por GitHub (`release.yml`); [CHANGELOG.md](../CHANGELOG.md) con sección de seguridad | Firma Authenticode del `.exe` (certificado de firma de código); aviso de actualización en la aplicación |
| **SG** Guías de seguridad | Documentación de defensa en profundidad, bastionado, desmantelamiento | [HARDENING.md](HARDENING.md) | Guía de desmantelamiento detallada; revisarla con un integrador |

## Requisitos esenciales del CRA (anexo I)

### Parte I · Propiedades del producto

| Requisito | Estado |
| --- | --- |
| Sin vulnerabilidades explotables conocidas al comercializarse | `pip-audit` en CI; revisión antes de cada versión |
| Configuración segura por defecto | Parcial: OPC UA seguro por defecto y servidor OPC UA desactivado; **la seguridad de usuarios está desactivada por defecto** para no romper proyectos existentes. Antes de comercializar, el asistente de nuevo proyecto debería activarla |
| Actualizaciones de seguridad | Versiones con SBOM y procedencia; falta aviso automático |
| Protección frente a acceso no autorizado (autenticación, gestión de identidades) | Usuarios, roles, bloqueo por intentos, caducidad de sesión, cambio de contraseña en el primer acceso; OPC UA con usuario y certificado |
| Confidencialidad (cifrado) | OPC UA con firma y cifrado. Las contraseñas de conexión van en el proyecto codificadas, no cifradas: la confidencialidad depende del acceso al proyecto. **S7 clásico y Modbus TCP no admiten cifrado**: mitigación por arquitectura de red ([HARDENING.md](HARDENING.md)) |
| Integridad de datos, órdenes y configuración | Escrituras como órdenes explícitas validadas por tipo y permiso; guardado con detección de cambios externos y recuperación ante errores de E/S (sin transacción frente a cortes de alimentación); versiones Git del proyecto |
| Minimizar datos | El runtime no recoge datos personales salvo el nombre de usuario en la auditoría |
| Disponibilidad y resiliencia | Un trabajador por conexión; colas acotadas; reconexión. Falta prueba de carga sostenida |
| Minimizar la superficie de ataque | El servidor OPC UA está desactivado por defecto; no hay servicios de red adicionales |
| Registro de eventos relevantes | Auditoría en SQLite: inicios de sesión, fallos, órdenes (con usuario y origen HMI, OPC UA o script), órdenes denegadas, ACK y certificados rechazados |
| Borrado seguro de datos | Guía de desmantelamiento en [HARDENING.md](HARDENING.md): secretos y certificados están en la carpeta del proyecto; `runtime/` contiene históricos y auditoría. Falta validar el procedimiento de borrado con el integrador |

### Parte II · Gestión de vulnerabilidades

| Requisito | Estado |
| --- | --- |
| Identificar y documentar componentes (SBOM) | SBOM CycloneDX en CI y en cada versión |
| Corregir sin demora y con actualizaciones | Plazos en [SECURITY.md](../SECURITY.md) |
| Pruebas y revisiones periódicas | CI en cada cambio y Dependabot semanal |
| Divulgar las vulnerabilidades corregidas | GitHub Security Advisories y [CHANGELOG.md](../CHANGELOG.md) |
| Política de divulgación coordinada | [SECURITY.md](../SECURITY.md) |
| Punto de contacto | Aviso privado de GitHub (activarlo en la configuración del repositorio) |
| Distribución segura de actualizaciones | HTTPS de GitHub, sumas SHA-256 y atestación de procedencia; falta firma Authenticode |
| Actualizaciones gratuitas y avisos | Proyecto GPL: las correcciones se publican para todos |

Las obligaciones de notificación del CRA (vulnerabilidades explotadas e incidentes graves) se aplican desde el 11 de septiembre de 2026; el resto, desde el 11 de diciembre de 2027. Afectan a abSCADA en cuanto se comercialice; el software libre sin actividad comercial queda fuera. Este análisis no sustituye a un asesoramiento legal.

## Requisitos de producto (orientación hacia IEC 62443-4-2, SL1)

| Requisito de componente | Estado en abSCADA |
| --- | --- |
| CR 1.1 Identificación y autenticación de usuarios | ✅ Runtime y servidor OPC UA |
| CR 1.2 Identificación de procesos y dispositivos | ✅ Certificados de aplicación OPC UA con listas de confianza |
| CR 1.5 Gestión de autenticadores | ⚠️ Hash scrypt y cambio obligatorio para las cuentas; las contraseñas de conexión se guardan recuperables en el proyecto |
| CR 1.7 Robustez de contraseñas | ✅ Longitud mínima configurable y comprobaciones básicas |
| CR 1.11 Intentos fallidos | ✅ Bloqueo configurable, compartido entre HMI y OPC UA |
| CR 2.1 Aplicación de la autorización | ✅ Permisos por rol en mandos, scripts, ACK y escrituras OPC UA |
| CR 2.5 / 2.6 Bloqueo y cierre de sesión | ✅ Cierre por inactividad |
| CR 2.8 Eventos auditables | ✅ Ver Parte I |
| CR 3.1 Integridad de las comunicaciones | ✅ OPC UA; ❌ S7 clásico y Modbus (limitación del protocolo) |
| CR 3.4 Integridad del software | ⏳ Falta firma Authenticode del ejecutable |
| CR 4.1 / 4.3 Confidencialidad y criptografía | ✅ OPC UA; ⚠️ secretos de conexión recuperables en el proyecto; ❌ S7 clásico y Modbus |
| CR 7.x Disponibilidad | ⏳ Pendiente de ensayos de carga |

## Cómo se publica una versión

1. Todas las pruebas y `pip-audit` pasan en CI.
2. `CHANGELOG.md` actualizado, con la sección **Seguridad** si procede.
3. Etiqueta `v*`: el flujo `release.yml` compila, prueba el ejecutable, genera SBOM y sumas, firma la procedencia y publica.
4. Si la versión corrige una vulnerabilidad, se publica el aviso (GitHub Security Advisory) a la vez.

Verificación por el cliente:

```bash
gh attestation verify abSCADA-<versión>-windows.zip --repo <propietario>/<repositorio>
sha256sum -c SHA256SUMS.txt
```

## Modelo de amenazas

Método STRIDE sobre los límites de confianza de una instalación típica. Se revisa con cada cambio de arquitectura o de protocolo. Versión de octubre de 2026.

### Elementos y límites de confianza

```text
            Zona de oficina / IT                │   Zona de control (OT)
                                                │
  Cliente OPC UA (MES, historian) ──OPC UA──────┼──▶ abSCADA runtime ──S7 / Modbus / ADS──▶ PLC
  (certificado + usuario abSCADA)   cifrado     │     │  ▲   │
                                                │     │  │   └─ OPC UA cifrado ──▶ PLC S7-1500 / servidor OPC UA
  Ingeniero con Studio ─────────────────────────┼─────┘  │
  (edita el proyecto: JSON, scripts)            │        └─ Operador en el HMI (usuario y rol)
                                                │
                    Archivos del puesto: proyecto (versionado: roles, cuentas, contraseñas de
                    conexión, certificados) · runtime/ (histórico SQLite) — no versionado
```

| Límite | Qué lo cruza | Protección |
| --- | --- | --- |
| Operador → runtime | Mandos, consignas, ACK, scripts de botón | Sesión con usuario y rol; cierre por inactividad; auditoría |
| Red IT → servidor OPC UA | Lecturas y escrituras de clientes | Firma y cifrado; certificado del cliente aceptado expresamente; usuario con permiso «Acceso por OPC UA»; escritura solo con «Mandos y consignas»; anónimo desactivado por defecto |
| Runtime → PLC | Lecturas y órdenes | OPC UA cifrado cuando el PLC lo permite; S7 clásico y Modbus sin protección (aislar en la red) |
| Ingeniero → proyecto | JSON, scripts Python | Permisos del sistema de archivos y control de versiones Git; los scripts son código de confianza |
| Disco del puesto y repositorio | Cuentas (huellas scrypt), contraseñas de conexión, clave privada OPC UA, histórico | Hash scrypt y longitud mínima; acceso restringido a la carpeta y al repositorio; `runtime/` nunca va al repositorio |

### Amenazas (STRIDE)

| # | Tipo | Amenaza | Mitigación | Riesgo residual |
| --- | --- | --- | --- | --- |
| T1 | Suplantación | Alguien usa el HMI sin ser operador | Inicio de sesión, bloqueo por intentos, cierre por inactividad | Contraseñas compartidas en el turno: política del cliente |
| T2 | Suplantación | Un equipo se hace pasar por servidor OPC UA o PLC | Certificado del servidor en lista de confianza; ninguna aceptación automática | El operador acepta un certificado sin comprobar la huella |
| T3 | Suplantación | Un cliente OPC UA no autorizado se conecta | Certificado del cliente aceptado expresamente y usuario abSCADA | — |
| T4 | Manipulación | Órdenes falsas a un PLC por S7 clásico o Modbus desde la red | Fuera del alcance del SCADA: el protocolo no autentica. Segmentación y cortafuegos ([HARDENING.md](HARDENING.md)) | Alto si la red de control no está aislada |
| T5 | Manipulación | Modificar el proyecto o un script para que ejecute órdenes | Permisos de archivos, Git y revisión de cambios; Studio detecta ediciones externas | Un ingeniero malintencionado con acceso al proyecto |
| T6 | Manipulación | Sustituir el ejecutable o una actualización | Descarga por HTTPS, SHA-256 y atestación de procedencia | Sin firma Authenticode todavía |
| T7 | Repudio | Un usuario niega haber dado una orden | Auditoría con usuario, origen (HMI, OPC UA, script) y valor | El usuario de Windows con acceso al disco puede borrar el SQLite |
| T8 | Divulgación | Robo de contraseñas desde el disco | Solo hash scrypt para las cuentas | Las contraseñas de conexión y la clave OPC UA van en el proyecto: quien lo copie las tiene. Proteger el repositorio y no publicar proyectos reales |
| T9 | Divulgación | Escucha del tráfico de proceso | OPC UA con cifrado | S7 clásico y Modbus viajan en claro |
| T10 | Denegación de servicio | Saturar el servidor OPC UA o un PLC lento | Un trabajador por conexión; colas acotadas; timeouts | Sin limitación de sesiones OPC UA concurrentes (pendiente) |
| T11 | Denegación de servicio | Bloquear cuentas a base de contraseñas falsas | Bloqueo temporal, no permanente | Un atacante en la red puede bloquear a un operador unos minutos |
| T12 | Elevación de privilegios | Un operador obtiene permisos de gestión | Roles definidos en el proyecto; las cuentas solo se gestionan desde Studio | Quien edita `users.json` en el disco o en el repositorio puede alterar roles: proteger el puesto y revisar los cambios de ese archivo en Git |
| T13 | Elevación de privilegios | Un script de proyecto hace más de lo previsto | Proceso aparte sin acceso al runtime ni a Qt; sus escrituras pasan por las mismas validaciones | No es una sandbox: código de confianza |

### Supuestos

- El sistema operativo del puesto está actualizado y bastionado, y su sesión está protegida.
- La red de control está segmentada (zonas y conductos según la IEC 62443-3-3).
- Las funciones de seguridad de máquina y de personas no dependen del SCADA.
