# Crear, guardar y versionar

Nuevo documento, debajo del explorador, permite elegir Pantalla, Layout o Faceplate. El formulario reúne nombre de archivo, título y dimensiones; valida el nombre antes de cerrarse. Los layouts siguen apareciendo en su grupo propio. Las propiedades de los documentos existentes se editan en el inspector.

## Guardado único

Los cambios del inspector y Aceptar en los diálogos actualizan el proyecto en memoria. Guardar proyecto o Ctrl+S guarda variables, tipos, conexiones, pantallas, faceplates, alarmas, registros, gráficas, fuentes Python y programación de tareas. El asterisco del título indica cambios pendientes. El editor Python participa en el historial de deshacer/rehacer.

Antes de escribir se validan todos los documentos y scripts. Se preparan los archivos en una carpeta temporal y se sustituyen únicamente los modificados. Los archivos de pantallas, faceplates o scripts eliminados del modelo se retiran del disco. Si una sustitución falla por error de E/S, se intenta restaurar lo ya sustituido. Esto no constituye una transacción resistente a un corte de alimentación entre varios archivos; las versiones Git aportan puntos de recuperación adicionales.

Un bloqueo exclusivo evita dos guardados concurrentes. Tras un cierre anormal puede quedar `.abscada-save.lock`; antes de retirarlo, comprueba que no hay otro Studio guardando. La carpeta temporal `.abscada-save-*` no forma parte del proyecto.

La restauración utiliza copias previas preparadas en disco. Si también falla la restauración, se conservan las copias restantes en `.abscada-recovery-*` y el error indica dónde recuperarlas; estas carpetas se excluyen al inicializar Git. No las elimines antes de revisar la recuperación. Los nombres de documentos se validan para Windows y Linux, incluyendo nombres reservados y duplicados que solo difieren en mayúsculas.

Studio compara las fuentes en disco con las que cargó/guardó. Si otro editor las modifica, rechaza sobrescribirlas: revisa tus cambios pendientes antes de usar Recargar archivos. No hay fusión automática entre ediciones de Studio y VS Code. Las imágenes importadas se copian a assets al seleccionarlas; sus referencias se guardan con el proyecto.

## Git local

Versiones… → Activar Git inicializa un repositorio en la carpeta del proyecto y crea la versión inicial. Git debe estar instalado y disponible en PATH. A partir de ahí Guardar proyecto crea automáticamente un commit cuando cambian las fuentes. Un guardado sin cambios no genera una versión vacía. Los commits automáticos tienen autor abSCADA y mensaje Guardar proyecto.

El diálogo muestra las últimas 30 versiones y el diff de la más reciente. El repositorio es Git estándar y puede abrirse desde VS Code. No se configura remoto, no se hace push y no se restaura ni descarta trabajo automáticamente. Para recuperar o comparar otras versiones usa las herramientas habituales de Git, detén el runtime y recarga después el proyecto en Studio.

Se versionan los JSON de configuración, screens, faceplates, scripts y assets. Se excluyen runtime (SQLite e históricos), temporales de guardado, cachés Python y archivos ajenos. Los cambios ajenos previamente staged no se incluyen en los commits del SCADA. Si Git falla después del guardado, Studio avisa de que los archivos están guardados pero la versión no se creó; se puede volver a guardar para reintentarla.
