# Instalación y puesta en marcha

[Manual completo: instalación y arranque](../MANUAL_COMPLETO.md#2-instalación-y-primer-arranque)

Requiere Python 3.11 o superior. Descarga el ZIP adjunto en [Releases](https://github.com/Astro1Deep/mpc-sample-database/releases/latest) y su checksum. Descomprime en una carpeta nueva. La biblioteca inicial está vacía: no incluye samples comerciales, proyectos personales ni una base de datos del autor.

| Origen de la descarga | Menú de instalación | Inicio del servidor |
| --- | --- | --- |
| ZIP BeatOS adjunto a la versión | `python3 BeatOS/installer.py` | `python3 BeatOS/serve_mpc.py "/ruta/a/biblioteca"` |
| Clon / «Source code» de GitHub | `python3 installer.py` | `python3 serve_mpc.py "/ruta/a/biblioteca"` |

En Windows sustituye `python3` por `py`. Elige la opción 1 para indexar tus propios samples y la 2 para servir esa misma biblioteca. No necesita que la tarjeta tenga un nombre concreto ni una cuenta del autor. FFmpeg es necesario para conversiones y ciertos destinos/ajustes; el instalador no lo descarga automáticamente.

En macOS, el ZIP incluye `BeatOS/ABRIR_BEATOS.command`. Si macOS no permite abrirlo, usa el comando Python anterior desde Terminal; no necesitas desactivar la seguridad del sistema.

Abre la dirección HTTP que imprime el servidor y comprueba la biblioteca activa. El puerto puede variar si está ocupado. Abrir un HTML como archivo no habilita las acciones locales. El código puede estar en una carpeta y la biblioteca en otra.

[Guía completa](../../GUIA_INSTALACION.md) · [Mapa de archivos](../ESTRUCTURA_BIBLIOTECA.md)
