# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Cada versión incluye una sección **Seguridad** cuando corrige vulnerabilidades o cambia el comportamiento de seguridad (requisito de divulgación del CRA y práctica SUM de la IEC 62443-4-1).

## [Sin publicar]

## [0.5.0b2] - 2026-10-07

### Añadido
- **Usuarios y roles** (Proyecto → Usuarios y roles). Política en `security.json` y cuentas por instalación en `runtime/users.json` (hash scrypt). El runtime arranca sin sesión y pide usuario para mandos, consignas, scripts y reconocimiento de alarmas. Incluye bloqueo por intentos, cierre por inactividad y cambio de contraseña en el primer acceso.
- Auditoría con el usuario real y el origen de cada orden (HMI, OPC UA o script), órdenes denegadas e inicios de sesión.
- **Cliente OPC UA** como conector: firma y cifrado por defecto, certificados por instalación con listas de confianza y contraseña cifrada con DPAPI fuera del proyecto.
- **Servidor OPC UA** (Proyecto → Servidor OPC UA) que publica las variables. Inicio de sesión con cuentas abSCADA y escrituras como órdenes auditadas.
- Propiedad `permission` en botones y entradas para exigir un permiso concreto.
- Cadena de suministro: `pip-audit` en CI, SBOM CycloneDX, `SHA256SUMS.txt` y atestación de procedencia en cada versión, y Dependabot.
- Documentación: [SECURITY.md](SECURITY.md), [docs/SECURITY_DEVELOPMENT.md](docs/SECURITY_DEVELOPMENT.md), [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) y [docs/HARDENING.md](docs/HARDENING.md).

### Seguridad
- La seguridad de usuarios está **desactivada por defecto** para no cambiar el comportamiento de los proyectos existentes. Actívala en las instalaciones reales ([docs/HARDENING.md](docs/HARDENING.md)).
