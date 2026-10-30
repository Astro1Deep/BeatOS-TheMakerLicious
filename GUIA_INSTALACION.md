# BeatOS

**Idioma:** Español · [English installation guide](GUIA_INSTALACION_EN.md)

**The MakerLicious**

[universal beatmaker station]

[Manual completo del sistema](docs/MANUAL_COMPLETO.md) · [Compatibilidad por hardware](docs/COMPATIBILIDAD_HARDWARE.md)

## Instalación limpia

Edición 3.8.0. Biblioteca de samples y rack de 16 pads para preparar kits destinados a MPC, Maschine, SP-404MK2, SP-404A/SX, PO-33/PO-133 y EP-133 K.O. II. Se ejecuta en el ordenador y no instala firmware en los aparatos. No necesitas una MPC para trabajar desde samples sueltos.

Requiere Python 3.11 o superior. No incluye samples comerciales, proyectos personales, bases de datos de Iván, claves ni configuraciones privadas. La biblioteca inicial está vacía.

1. Descomprime el ZIP en una carpeta nueva, sin sobrescribir tu biblioteca anterior.
2. Ejecuta `python3 BeatOS/installer.py` (en Windows, `py BeatOS/installer.py`).
3. Elige indexar e indica la carpeta de tus propios samples. No se eliminan metadatos automáticamente al indexar.
4. Inicia el servidor indicando esa misma carpeta: `python3 BeatOS/serve_mpc.py "/ruta/a/tu/biblioteca" --port 8888`.
5. Usa la dirección local que muestra el programa. Abrir el HTML directamente como `file://` no habilita las acciones del servidor.

El servidor escucha en 127.0.0.1. No lo publiques mediante un túnel o un proxy sin autenticación. Rechaza peticiones web de otros orígenes y rutas que salgan de la biblioteca. La opción explícita de limpieza de metadatos sí elimina archivos auxiliares: no es necesaria para arrancar ni indexar.

Los kits se generan dentro de `Custom_Kits` en la biblioteca seleccionada. Guarda una copia de tu tarjeta antes de cualquier modificación. Las exportaciones están verificadas por pruebas de estructura y audio sintético, pero deben probarse en el modelo y firmware de hardware de destino.

Desde la carpeta del código (BeatOS/ en el ZIP o la raíz del clon), pruebas locales sin hardware: `python3 -B -m unittest discover -s tests -v`. El ZIP contiene un manifiesto SHA-256 para comprobar sus archivos; los hashes comprueban integridad, no identidad del editor.

## Primer kit después de instalar

Abre el catálogo por HTTP, busca y escucha tus samples, asígnalos al rack y elige un destino en «Exportar Kit». Las entregas se guardan en `Custom_Kits/<nombre>/` dentro de la biblioteca activa. El bundle universal genera las seis variantes; para un solo equipo, elige su formato. La carga final depende del destino: programa MPC, WAV para asignar en Maschine o SP-404, reel de audio para PO, o WAV y mapa para EP-133.

Sigue el [recorrido paso a paso y la tabla de formatos](README.md#rack-y-destinos). Ahí se explica qué ajustes se transfieren, cuáles se aplican manualmente y por qué SP-404A/SX sólo recibe los pads 1–12.

## Conexión y formatos de audio

Inicia `BeatOS/ABRIR_BEATOS.command` en la tarjeta y abre http://127.0.0.1:8888. El HTML por archivo funciona como catálogo sin conexión. Comprueba la raíz indicada antes de exportar. Si la tarjeta no está montada, reconéctala e inicia su lanzador.

FFmpeg permite convertir AIFF, FLAC, MP3 y WAV con otra frecuencia/profundidad, además de procesar afinación del reel PO. Sin FFmpeg se admiten WAV PCM 16-bit/44.1kHz compatibles sin afinación; los demás casos muestran un error y no simulan conversión.

El perfil SP-404MK2 convierte a 48 kHz y necesita FFmpeg cuando la fuente usa otra frecuencia.

## Biblioteca: identificación y límites

El tipo usa primero el nombre y después carpetas específicas de instrumento. Un nombre genérico queda «Sin identificar»; no se inventa una familia de mute. Formato distingue loops, stems y fills por sus etiquetas. Estas reglas ayudan a organizar y no sustituyen la escucha.

La tonalidad usa etiquetas explícitas como Dm, F#min o Cmajor. Una nota de multisample (C1) se muestra «C (nota)», sin Camelot. «Kit A» no es La mayor. Camelot se convierte únicamente si hay modo mayor/menor declarado; no se analiza automáticamente la armonía del audio.

Energía significa nivel RMS aproximado del archivo original: tres ventanas de hasta 4096 frames al inicio, centro y final, combinadas sin normalizar (baja < −24 dBFS, media de −24 a < −12, alta ≥ −12). No es LUFS ni intensidad musical, y puede omitir transitorios fuera de las ventanas. Se mide WAV PCM entero de 8/16/24/32 bits; otros formatos o cabeceras incompatibles indican «Sin medir». «Silencio medido» sólo describe esas ventanas. Reindexar vuelve a calcular estas etiquetas, sin modificar el audio ni los proyectos.

## Para compartir con otro productor

Comparte sólo el ZIP de BeatOS y su SHA-256, nunca BACKUPS_SEGURIDAD ni los respaldos privados de auditoría. Puede instalarse en una carpeta con espacios y servir una biblioteca situada en otra ubicación. No requiere que exista MPCSMPL ni una cuenta de Iván. La primera indexación genera el catálogo y la base SQLite en la biblioteca elegida, por lo que ésta debe permitir escritura. Indexa tu propia carpeta de samples; el ZIP inicial está vacío. Si Windows no encuentra python3, usa `py` en los comandos.

## Estructura desde 3.7.0

En la tarjeta o ZIP organizado, la raíz sólo necesita los accesos catalogo_universal.html y catalogo_mpc_sample.html. Ambos abren BeatOS/data/catalogo.html: el catálogo completo se guarda una sola vez. Los scripts, instalador, templates, documentación y recursos están dentro de BeatOS/. Las bases, CSV y JSON quedan en BeatOS/data/; las preferencias, en BeatOS/config/. Las carpetas de música no se cambian ni se mueven al reindexar.

Para una biblioteca situada en otra carpeta, ejecuta el instalador desde tu carpeta de código e indica esa biblioteca. El servidor sirve los recursos gráficos de la instalación; usa su URL local para disponer de toda la interfaz. Las opciones de limpieza no se ejecutan automáticamente. Las carpetas ocultas y AppleDouble que crea macOS no son archivos generados por BeatOS.
