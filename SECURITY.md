# Política de seguridad · Security policy

*English summary: report vulnerabilities privately through GitHub «Report a vulnerability» (Security tab). Do not open public issues. We acknowledge within 5 working days.*

## Versiones con soporte

| Versión | Correcciones de seguridad |
| --- | --- |
| Última versión publicada (incluidas betas 0.x) | Sí |
| Versiones anteriores | No: actualiza a la última |

abSCADA está en fase beta. Mientras no haya una versión 1.0, solo la última versión publicada recibe correcciones.

## Cómo informar de una vulnerabilidad

**No abras una incidencia pública.** Usa el aviso privado de GitHub: pestaña **Security → Report a vulnerability** del repositorio. Si la opción no está disponible, solicita al responsable del repositorio un canal privado antes de compartir detalles sensibles. Este proyecto no publica todavía una dirección de correo de seguridad alternativa.

Incluye, si puedes:
- versión de abSCADA (Ayuda → Acerca de) y sistema operativo;
- componente afectado (runtime, Studio, servidor o cliente OPC UA, conector S7/Modbus/ADS…);
- pasos para reproducirlo y su impacto (qué puede hacer un atacante y desde dónde);
- si ya es público o lo has comunicado a otros.

## Qué puedes esperar

| Paso | Plazo objetivo |
| --- | --- |
| Acuse de recibo | 5 días laborables |
| Primera evaluación (gravedad CVSS y alcance) | 10 días laborables |
| Corrección o mitigación publicada | 90 días como máximo; antes si es grave o se está explotando |
| Aviso público (GitHub Security Advisory, CVE si procede) | Al publicar la corrección, coordinado contigo |

Te mantendremos informado y, si quieres, te reconoceremos en el aviso.

## Vulnerabilidades explotadas activamente

Cuando una vulnerabilidad se esté explotando o haya un incidente grave que afecte a la seguridad del producto, se notificará conforme al Reglamento (UE) 2024/2847 (Cyber Resilience Act) en cuanto esas obligaciones sean aplicables a abSCADA como producto comercializado.

## Alcance y límites

- abSCADA **no es un sistema de seguridad funcional**: las protecciones de máquina y de personas deben residir en relés y PLC de seguridad, nunca en el SCADA.
- Los scripts de proyecto son código de confianza que se ejecuta con los permisos del usuario de Windows. No es una vulnerabilidad que un script del proyecto pueda leer ficheros: protege quién puede modificar el proyecto.
- S7 clásico (PUT/GET) y Modbus TCP no tienen autenticación ni cifrado por diseño del protocolo. Ver [docs/HARDENING.md](docs/HARDENING.md) para aislarlos en la red.

## Documentación relacionada

- [docs/SECURITY_DEVELOPMENT.md](docs/SECURITY_DEVELOPMENT.md): cómo se desarrolla abSCADA (IEC 62443-4-1, CRA).
- [docs/SECURITY_DEVELOPMENT.md](docs/SECURITY_DEVELOPMENT.md): modelo de amenazas.
- [docs/HARDENING.md](docs/HARDENING.md): guía de bastionado para instalaciones.
