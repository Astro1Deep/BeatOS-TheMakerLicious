# Taxonomía e identificación de audio

La versión actual separa identificación por etiquetas y medición del nivel del audio. [Guía completa](../../GUIA_INSTALACION.md) · [Reglas y límites](../IDENTIFICACION_BIBLIOTECA.md).

El nombre del archivo tiene prioridad sobre carpetas específicas de instrumento. Las categorías generales de género no determinan su sonido. Los tipos son KICK, SNARE, CLAP, HIHAT, CYMBAL, PERCUSSION, BASS_808, KEYS_SYNTH, MELODIC_LOOP, DRUM_LOOP, VOCAL, FX, STEM y ROLL_FILL; UNKNOWN indica que no hay evidencia suficiente. Shakers y panderetas son PERCUSSION.

Formato distingue ONE_SHOT, LOOP, STEM, ROLL_FILL y UNSPECIFIED. Es una estimación por etiquetas, no un detector acústico de instrumentos. BPM también se extrae del nombre.

Tonalidad reconoce modos explícitos como Dm, F#min o Cmajor. «Kit A» no es La mayor; C1 se muestra como nota, sin modo ni Camelot. La conversión Camelot sólo se hace con modo mayor/menor declarado.

La energía se mide como RMS aproximado de tres ventanas de hasta 4096 frames de WAV PCM entero, sin normalizar. Cortes: baja < −24 dBFS, media de −24 a < −12 y alta ≥ −12. No es LUFS ni intensidad musical y puede omitir transitorios entre ventanas. Otros formatos/cabeceras quedan «Sin medir» y un cero sólo significa silencio en las ventanas observadas.
