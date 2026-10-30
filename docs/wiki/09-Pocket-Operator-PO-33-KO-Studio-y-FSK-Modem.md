# PO-33, PO-133 y EP-133: alcance real de BeatOS

## PO-33 / PO-133

El reel reúne los pads ocupados del rack en audio mono PCM 16-bit/44.1 kHz. Ese es el formato del archivo de intercambio, no una afirmación sobre la electrónica interna. Volumen y afinación se procesan en el audio y luego se normaliza el conjunto; panorama y mutes no se transfieren al PO.

El Hub permite fijar presupuesto de 1–40 s y pausas de 0–500 ms. Introduce la memoria libre que muestra el dispositivo: BeatOS no la consulta. Si hace falta, el exportador recorta con fade-out y guarda un manifiesto con segundos, frames, número de corte y pad de origen. Los 150 ms predeterminados ayudan a separar golpes, pero no garantizan cortes perfectos: revisa TRIM.

Conecta la salida de audio a LINE IN y graba manteniendo RECORD y el slot de batería elegido (9–16). Ajusta nivel sin saturación. No hay un porcentaje universal de volumen válido para todas las interfaces. El PO-20 no admite esta carga de samples.

### Respaldar, archivar y restaurar proyectos del PO

En el PO, el intercambio completo de sonidos y patrones se realiza mediante un volcado de datos en audio. El reel del rack sólo prepara muestras para grabarlas; no contiene patrones, automatizaciones ni un proyecto nativo del PO. BeatOS no decodifica ni convierte ese volcado a XPJ, MIDI o pads editables.

1. Conecta PO LINE OUT a una **entrada de línea estéreo** de tu interfaz. En el Hub pulsa «Detectar entradas», selecciona la interfaz y pulsa «Grabar backup». Se pide permiso al navegador únicamente al detectar o grabar; no se inicia una grabación al abrir el menú.
2. BeatOS solicita dos canales, sin eco, reducción de ruido ni ganancia automática. Rechaza una entrada mono o procesamiento de voz anunciado como activo. Captura PCM 16-bit a 44.1/48 kHz con AudioWorklet, sin monitorización de retorno, mezcla de canales, efectos ni compresión. Comprueba también los ajustes físicos y del sistema operativo. Si el navegador o interfaz no admiten esta captura, usa un grabador externo en WAV PCM estéreo e importa el archivo.
3. Con la grabación ya iniciada, pulsa WRITE + SOUND + PLAY en el PO. Espera a que termine todo el envío y pulsa «Finalizar y guardar». No apliques normalización, fades, recortes, MP3, limpieza de ruido ni conversión a mono a un backup. La captura se limita a diez minutos y descarga una copia antes de intentar archivarla en la biblioteca.
4. «Importar backup WAV» conserva **los bytes originales** y verifica que el PCM declarado está completo. Archiva en `BeatOS/data/po33_backups/`, con nombre y SHA-256; no sobrescribe archivos anteriores. El límite de importación es 128 MiB. Cada WAV puede representar un estado/proyecto distinto del PO: dale un nombre descriptivo y conserva copias fuera de la tarjeta. La huella detecta cambios de archivo, no errores ya presentes en la grabación.
5. «Preparar restauración» pide confirmar el reemplazo y carga el WAV original en un reproductor separado, detenido, a velocidad 1×. Conecta salida estéreo → PO LINE IN; entra en recepción con WRITE + SOUND + RECORD y después reproduce. **El PO borra todos los sonidos y patrones actuales al empezar a recibir**. No hay restauración por slot ni fusión de proyectos en este flujo. El navegador no puede confirmar que el PO haya recibido correctamente el envío.

El inventario incluye WAV y WAV en mayúsculas dentro de las subcarpetas admitidas y mantiene lectura de las ubicaciones históricas. Descargar devuelve el original sin convertirlo. La inspección comprueba estructura WAV completa, SHA-256 y amplitud de los primeros cuatro segundos; **no decodifica ni verifica los datos del módem**. Un WAV estéreo completo puede contener audio musical o un volcado corrupto. Un WAV mono se conserva, pero no se habilita su restauración integrada. Las grabaciones interrumpidas se descargan/archivan como INCOMPLETO cuando hay audio recuperable; deben repetirse antes de confiar en ellas.

Para certificar un respaldo hace falta restaurarlo y comprobar sonidos y patrones en el PO. El fabricante recomienda un segundo PO para evitar sobrescribir el original durante esa verificación. Con un solo PO no hay prueba de restauración sin sustituir su estado actual. Las pruebas automáticas de BeatOS usan audio sintético, no un volcado real del equipo. Fuentes: [PO-33, sección 8](https://teenage.engineering/guides/po-33/en) y [PO-133](https://teenage.engineering/guides/po-133/en).

## EP-133 K.O. II

BeatOS genera WAV PCM 16-bit/44.1 kHz, conservando mono/estéreo y niveles originales, más un mapa JSON y un ZIP de transporte. Sólo incluye pads ocupados. FFmpeg es necesario para convertir formatos o frecuencias distintos; un fallo detiene la exportación y no deja un kit parcial anunciado como válido.

Extrae el ZIP y carga los WAV con [EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool). El ZIP BeatOS no es un respaldo nativo. El mapa propone A: teclas 1–9, punto, 0, ENTER; y B: teclas 1–4. La asignación, volumen, panorama, tono y mutes del mapa se aplican manualmente; cargar un WAV no transmite esos parámetros.

La herramienta oficial usa **Web MIDI** por USB-C. El soporte oficial incluye Chrome, Edge y Firefox de escritorio, y excluye Safari y móviles. Permite importar muestras y gestionar respaldos de sistema o proyecto. [Instrucciones oficiales](https://support.teenage.engineering/hc/en-us/articles/11639171890204-how-to-use-the-EP-sample-tool).

La guía actual 2.5 describe 128 MB y hasta 999 muestras; el artículo antiguo de soporte aún menciona 64 MB. Comprueba la capacidad indicada por tu herramienta y firmware. La frecuencia nativa indicada en la guía es 46.875 kHz; el archivo exportado por BeatOS a 44.1 kHz es un formato de intercambio admitido, no la frecuencia nativa. [Guía actual](https://teenage.engineering/guides/ep-133) · [Transferencia y CHOP](https://teenage.engineering/guides/ep-133/functions) · [Ajustes y mutes](https://teenage.engineering/guides/ep-133/modes).

No se ha conectado ni actualizado firmware de hardware durante esta revisión. Una prueba de software no sustituye la carga y escucha física.
