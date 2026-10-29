# BeatOS — instalación limpia

Edición 3.6.5-layout.20261029. Herramientas de biblioteca y sampling para ejecutar en el ordenador; no es firmware ni sustituye el sistema de un MPC.

Requiere Python 3.11 o superior. No incluye samples comerciales, proyectos personales, bases de datos de Iván, claves ni configuraciones privadas. La biblioteca inicial está vacía.

1. Descomprime el ZIP en una carpeta nueva, sin sobrescribir tu biblioteca anterior.
2. Ejecuta `python3 installer.py` (en Windows, `py installer.py`).
3. Elige indexar e indica la carpeta de tus propios samples. No se eliminan metadatos automáticamente al indexar.
4. Inicia el servidor indicando esa misma carpeta: `python3 serve_mpc.py "/ruta/a/tu/biblioteca" --port 8888`.
5. Usa la dirección local que muestra el programa. Abrir el HTML directamente como `file://` no habilita las acciones del servidor.

El servidor escucha en 127.0.0.1. No lo publiques mediante un túnel o un proxy sin autenticación. Rechaza peticiones web de otros orígenes y rutas que salgan de la biblioteca. La opción explícita de limpieza de metadatos sí elimina archivos auxiliares: no es necesaria para arrancar ni indexar.

Los kits se generan dentro de `Custom_Kits` en la biblioteca seleccionada. Guarda una copia de tu tarjeta antes de cualquier modificación. Las exportaciones están verificadas por pruebas de estructura y audio sintético, pero deben probarse en el modelo y firmware de hardware de destino.

Pruebas locales sin hardware: `python3 -B -m unittest discover -s tests -v`. El ZIP contiene un manifiesto SHA-256 para comprobar sus archivos; los hashes comprueban integridad, no identidad del editor.

## Conexión y formatos de audio

Inicia `00_ABRIR_BEATOS/ABRIR_BEATOS.command` en la tarjeta y abre http://127.0.0.1:8888. El HTML por archivo funciona como catálogo sin conexión. Comprueba la raíz indicada antes de exportar. Si la tarjeta no está montada, reconéctala e inicia su lanzador.

FFmpeg permite convertir AIFF, FLAC, MP3 y WAV con otra frecuencia/profundidad, además de procesar afinación del reel PO. Sin FFmpeg se admiten WAV PCM 16-bit/44.1kHz compatibles sin afinación; los demás casos muestran un error y no simulan conversión.

El perfil SP-404MK2 convierte a 48 kHz y necesita FFmpeg cuando la fuente usa otra frecuencia.

## Biblioteca: identificación y límites

El tipo usa primero el nombre y después carpetas específicas de instrumento. Un nombre genérico queda «Sin identificar»; no se inventa una familia de mute. Formato distingue loops, stems y fills por sus etiquetas. Estas reglas ayudan a organizar y no sustituyen la escucha.

La tonalidad usa etiquetas explícitas como Dm, F#min o Cmajor. Una nota de multisample (C1) se muestra «C (nota)», sin Camelot. «Kit A» no es La mayor. Camelot se convierte únicamente si hay modo mayor/menor declarado; no se analiza automáticamente la armonía del audio.

Energía significa nivel RMS aproximado del archivo original: tres ventanas de hasta 4096 frames al inicio, centro y final, combinadas sin normalizar (baja < −24 dBFS, media de −24 a < −12, alta ≥ −12). No es LUFS ni intensidad musical, y puede omitir transitorios fuera de las ventanas. Se mide WAV PCM entero de 8/16/24/32 bits; otros formatos o cabeceras incompatibles indican «Sin medir». «Silencio medido» sólo describe esas ventanas. Reindexar vuelve a calcular estas etiquetas, sin modificar el audio ni los proyectos.

## Para compartir con otro productor

Comparte sólo el ZIP de BeatOS y su SHA-256, nunca BACKUPS_SEGURIDAD ni los respaldos privados de auditoría. Puede instalarse en una carpeta con espacios y servir una biblioteca situada en otra ubicación. No requiere que exista MPCSMPL ni una cuenta de Iván. La primera indexación genera el catálogo y la base SQLite en la biblioteca elegida, por lo que ésta debe permitir escritura. Indexa tu propia carpeta de samples; el ZIP inicial está vacío. Si Windows no encuentra python3, usa `py` en los comandos.
