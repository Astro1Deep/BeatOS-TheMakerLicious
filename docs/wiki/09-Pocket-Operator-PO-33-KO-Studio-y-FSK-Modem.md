# PO-33, PO-133 y EP-133: alcance real de BeatOS

## PO-33 / PO-133

El reel reúne los pads ocupados del rack en audio mono PCM 16-bit/44.1 kHz. Ese es el formato del archivo de intercambio, no una afirmación sobre la electrónica interna. Volumen y afinación se procesan en el audio y luego se normaliza el conjunto; panorama y mutes no se transfieren al PO.

El Hub permite fijar presupuesto de 1–40 s y pausas de 0–500 ms. Introduce la memoria libre que muestra el dispositivo: BeatOS no la consulta. Si hace falta, el exportador recorta con fade-out y guarda un manifiesto con segundos, frames, número de corte y pad de origen. Los 150 ms predeterminados ayudan a separar golpes, pero no garantizan cortes perfectos: revisa TRIM.

Conecta la salida de audio a LINE IN y graba manteniendo RECORD y el slot de batería elegido (9–16). Ajusta nivel sin saturación. No hay un porcentaje universal de volumen válido para todas las interfaces. El PO-20 no admite esta carga de samples.

Los respaldos de audio se catalogan y descargan sin modificarlos. La inspección revisa encabezado y amplitud de los primeros cuatro segundos: **no decodifica ni verifica el contenido del módem**, y nunca debe interpretarse como garantía de restauración. Guarda antes el estado del PO; recibir un respaldo sustituye muestras y patrones. Fuentes: [PO-33](https://teenage.engineering/guides/po-33/en) y [PO-133](https://teenage.engineering/guides/po-133/en).

## EP-133 K.O. II

BeatOS genera WAV PCM 16-bit/44.1 kHz, conservando mono/estéreo y niveles originales, más un mapa JSON y un ZIP de transporte. Sólo incluye pads ocupados. FFmpeg es necesario para convertir formatos o frecuencias distintos; un fallo detiene la exportación y no deja un kit parcial anunciado como válido.

Extrae el ZIP y carga los WAV con [EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool). El ZIP BeatOS no es un respaldo nativo. El mapa propone A: teclas 1–9, punto, 0, ENTER; y B: teclas 1–4. La asignación, volumen, panorama, tono y mutes del mapa se aplican manualmente; cargar un WAV no transmite esos parámetros.

La herramienta oficial usa **Web MIDI** por USB-C. El soporte oficial incluye Chrome, Edge y Firefox de escritorio, y excluye Safari y móviles. Permite importar muestras y gestionar respaldos de sistema o proyecto. [Instrucciones oficiales](https://support.teenage.engineering/hc/en-us/articles/11639171890204-how-to-use-the-EP-sample-tool).

La guía actual 2.5 describe 128 MB y hasta 999 muestras; el artículo antiguo de soporte aún menciona 64 MB. Comprueba la capacidad indicada por tu herramienta y firmware. La frecuencia nativa indicada en la guía es 46.875 kHz; el archivo exportado por BeatOS a 44.1 kHz es un formato de intercambio admitido, no la frecuencia nativa. [Guía actual](https://teenage.engineering/guides/ep-133) · [Transferencia y CHOP](https://teenage.engineering/guides/ep-133/functions) · [Ajustes y mutes](https://teenage.engineering/guides/ep-133/modes).

No se ha conectado ni actualizado firmware de hardware durante esta revisión. Una prueba de software no sustituye la carga y escucha física.
