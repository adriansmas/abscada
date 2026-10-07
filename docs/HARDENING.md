# Guía de bastionado de una instalación

Para el integrador o el responsable de la planta. Aplica la defensa en profundidad de la IEC 62443-3-3: aislar zonas, limitar conductos, usuarios con lo mínimo y registro de lo que pasa.

## 1. Red

- **Zona de control separada** de la red de oficina (VLAN o red física) con un cortafuegos entre ambas.
- Entre oficina y control, solo los conductos necesarios. Lo habitual es **OPC UA (TCP 4840) desde los equipos de oficina autorizados hacia el puesto abSCADA**, nunca al revés.
- **S7 clásico (TCP 102), Modbus TCP (502) y ADS (48898) no tienen autenticación ni cifrado.** Deben quedarse dentro de la zona de control, sin salida a la red de oficina ni a internet.
- Sin acceso remoto directo al puesto. Si hace falta, VPN con doble factor hasta una máquina de salto, no hasta el SCADA.

## 2. Puesto Windows

- Windows con soporte y actualizaciones aplicadas tras probarlas en el puesto de ingeniería.
- Cuenta de Windows de operación **sin permisos de administrador**, con inicio de sesión automático solo si el puesto está en una sala controlada.
- Antivirus o EDR activos, con la carpeta del archivo SQLite (`<proyecto>\runtime`) excluida del análisis en tiempo real si afecta al rendimiento.
- BitLocker activado: protege cuentas, secretos y claves privadas si roban el disco.
- Cortafuegos de Windows: entrada solo al puerto OPC UA configurado y solo desde las IP autorizadas.
- Desactivar USB de almacenamiento si la política de la planta lo permite.

## 3. abSCADA

1. **Usuarios y roles** (Proyecto → Usuarios y roles): activa *Exigir inicio de sesión*.
   - Una cuenta por persona; nunca cuentas compartidas.
   - Rol «Observador» para quien solo mira; «Operador» para mandos y ACK; «Supervisor» con *Gestionar usuarios* para muy pocas personas.
   - Contraseña de al menos 12 caracteres, cierre por inactividad entre 10 y 15 minutos y bloqueo tras 5 fallos.
   - Controles críticos (por ejemplo, el panel del instructor o los rearmes) con un permiso específico en la propiedad `permission` del botón.
2. **Servidor OPC UA** (Proyecto → Servidor OPC UA): actívalo solo si un sistema externo lo necesita.
   - Solo políticas con **firma y cifrado**. «Sin seguridad», nunca en planta.
   - Lectura anónima desactivada.
   - Una cuenta abSCADA por sistema cliente, con un rol que tenga *Acceso por OPC UA* y, solo si debe escribir, *Mandos y consignas*.
   - Acepta los certificados de cliente en Proyecto → Certificados OPC UA **después de comprobar la huella** con el administrador del otro sistema.
3. **Conexiones OPC UA a PLC**: política con firma y cifrado y usuario del PLC. La contraseña se guarda cifrada en el puesto, nunca en el proyecto. Acepta el certificado del PLC comprobando su huella en TIA Portal.
4. **Scripts**: revísalos como código. Quien puede editar el proyecto puede ejecutar código en el puesto.
5. **Auditoría**: haz copia del archivo con Herramientas → Copia de seguridad de los registros y revisa los inicios de sesión fallidos y las órdenes denegadas.

## 4. Archivos sensibles del puesto

| Ruta | Contenido | Protección |
| --- | --- | --- |
| `<proyecto>\runtime\users.json` | Cuentas (hash scrypt, roles) | Permisos NTFS: solo la cuenta de operación y los administradores |
| `<proyecto>\runtime\secrets.json` | Contraseñas de conexiones (DPAPI) | Solo descifrable por la misma cuenta de Windows en el mismo equipo |
| `<proyecto>\runtime\pki\own\*.pem` | Claves privadas OPC UA | Permisos restringidos; no copiar a otros equipos |
| `<proyecto>\runtime\*.sqlite3` | Histórico, alarmas y auditoría | Copias de seguridad periódicas |

`runtime\` no forma parte del proyecto ni de sus versiones Git. Al copiar un proyecto a otro puesto, las cuentas, los secretos y los certificados **no viajan**: se crean de nuevo en el puesto de destino.

## 5. Desmantelamiento

Al retirar un puesto, borra `<proyecto>\runtime\` (cuentas, secretos, claves y archivo, después de guardar las copias que deban conservarse). Quita su certificado de las listas de confianza de los servidores y PLC con los que hablaba y revoca las cuentas de OPC UA que usaban otros sistemas.

## 6. Lo que abSCADA no hace (todavía)

- No firma el ejecutable con Authenticode: comprueba `SHA256SUMS.txt` y la atestación de la versión ([SECURITY_DEVELOPMENT.md](SECURITY_DEVELOPMENT.md)).
- No integra cuentas de Windows ni del directorio activo.
- No limita el número de sesiones OPC UA simultáneas.
