# Instalación y puesta en marcha

Requiere Python 3.11+. Descarga el ZIP de [Releases](https://github.com/Astro1Deep/mpc-sample-database/releases) o clona el repositorio. Descomprime en una carpeta nueva y sigue la [guía de instalación actual](../../GUIA_INSTALACION.md).

Ejecuta `python3 installer.py` (Windows: `py installer.py`). Opción 1: indexar tu propia biblioteca. Opción 2: iniciar el servidor sobre esa misma biblioteca. El programa no incluye samples comerciales ni datos personales. En macOS/Linux puede usarse `./install.sh`.

Para código y biblioteca separados:

```bash
python3 index_mpc_library.py --path "/ruta/a/tu/biblioteca"
python3 serve_mpc.py "/ruta/a/tu/biblioteca" --port 8888
```

Abre la URL que muestra el servidor. El puerto puede variar si lo ocupa otro servicio. La reproducción y las acciones dependen de que el servidor esté activo, de los formatos de audio y del navegador; no se garantiza reproducción de cualquier formato. FFmpeg habilita conversiones y ciertos ajustes/destinos.

La limpieza de metadatos elimina auxiliares de macOS y es opcional; no instala el sistema ni mejora el audio. No requiere ejecutar supervisores automáticos. No sobrescribas una biblioteca anterior ni restaures backups antiguos para instalar una entrega nueva.
