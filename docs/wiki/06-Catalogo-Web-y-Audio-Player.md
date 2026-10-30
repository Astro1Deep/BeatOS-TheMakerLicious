# Catálogo web y reproductor

El catálogo se guarda una sola vez en `BeatOS/data/catalogo.html`. Los dos HTML de la raíz son accesos ligeros. El servidor conserva las URL de catálogos antiguos sin volver a crear sus carpetas ni duplicar el contenido.

Abre BeatOS desde el servidor local para preescuchar, inspeccionar proyectos, crear kits o reindexar. La interfaz muestra la biblioteca activa. Una página `file://` puede consultar el catálogo, pero sus acciones locales están bloqueadas; inicia el servidor y utiliza la URL HTTP que muestra.

El explorador combina búsqueda por palabras, filtros y ordenación. Presenta hasta 60 samples por página; proyectos y expansiones usan páginas de 24 tarjetas. El rendimiento depende del equipo y tamaño de la biblioteca. El reproductor utiliza los formatos que admite el navegador; una extensión reconocida no garantiza decodificación.

## Proyectos y expansiones

«Recargar» actualiza las tarjetas del catálogo guardado conservando filtros y rack. «Reindexar» vuelve a leer el disco y actualiza los índices; no modifica el audio ni los proyectos. Tras una actualización de la aplicación, recarga la página completa para cargar también el código nuevo: la recarga de tarjetas no sustituye el JavaScript ya abierto.

«Editar copia en rack» solicita el XPJ concreto. Mientras espera, el botón indica que está procesando. Al terminar activa el rack, lo desplaza a la vista, enfoca el nombre del origen y confirma cuántos pads hay en el banco visible. Un error conserva la copia anterior y muestra el motivo. Si no carga, comprueba la ruta activa, el servidor, las referencias y que la página esté actualizada.

El servidor escucha en loopback y valida origen/host. Las solicitudes externas y las rutas privadas del sistema están bloqueadas. La base SQLite y la configuración no se publican como archivos estáticos.
