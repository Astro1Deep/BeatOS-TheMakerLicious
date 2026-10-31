# Pocket Operator Studio (PO-32, PO-33, PO-35, PO-133, PO-137) y EP-133: alcance real de BeatOS

[Manual completo: Hub PO y respaldos](../MANUAL_COMPLETO.md#11-hub-po-33-y-po-133) · [Carga por modelo](../COMPATIBILIDAD_HARDWARE.md)

## PO-33 / PO-133: Reels de muestras (≤ 40 s)

El reel reúne los pads ocupados del rack en audio mono PCM 16-bit/44.1 kHz. Ese es el formato del archivo de intercambio, no una afirmación sobre la electrónica interna. Volumen y afinación se procesan en el audio y luego se normaliza el conjunto; panorama y mutes no se transfieren al PO.

El Hub permite fijar presupuesto de 1–40 s y pausas de 0–500 ms. Introduce la memoria libre que muestra el dispositivo: BeatOS no la consulta. Si hace falta, el exportador recorta con fade-out y guarda un manifiesto con segundos, frames, número de corte y pad de origen. Los 150 ms predeterminados ayudan a separar golpes, pero no garantizan cortes perfectos: revisa TRIM.

Conecta la salida de audio a LINE IN y graba manteniendo RECORD y el slot de batería elegido (9–16). Ajusta nivel sin saturación. No hay un porcentaje universal de volumen válido para todas las interfaces. Los modelos sin muestreo de usuario como el PO-20 Arcade no admiten esta carga de samples.

### Respaldar, archivar y restaurar proyectos por audio-datos (5 modelos)

En la familia Pocket Operator, la transferencia completa de proyectos y sonidos por línea estéreo sólo está documentada oficialmente en **cinco modelos**:

| Modelo | Contenido del respaldo | Comando Enviar (Exportar del PO) | Comando Recibir (Restaurar al PO) | Verificación de paquetes en BeatOS |
| :--- | :--- | :--- | :--- | :--- |
| **PO-32 Tonic** | Parches de batería + patrones | `WRITE` + `SOUND` (o `BPM`) | `RECORD` + `SOUND` (o `BPM`) | Cabecera WAV + SHA-256 (protocolo propietario no decodificado) |
| **PO-33 K.O.!** | 16 slots de muestras + 16 patrones | `WRITE` + `SOUND` + `PLAY` | `WRITE` + `SOUND` + `RECORD` | **Verificador experimental CRC de paquetes (`vendor/po33_verify.py`)** + SHA-256 |
| **PO-35 Speak** | Voces sintetizadas + kit + patrones | `WRITE` + `SOUND` + `PLAY` | `WRITE` + `SOUND` + `RECORD` | Cabecera WAV + SHA-256 |
| **PO-133 Street Fighter** | 16 slots de muestras + 16 patrones | `WRITE` + `SOUND` + `PLAY` | `WRITE` + `SOUND` + `RECORD` | Cabecera WAV + SHA-256 (misma arquitectura que PO-33) |
| **PO-137 Rick & Morty** | Voces sintetizadas + kit + patrones | `WRITE` + `SOUND` + `PLAY` | `WRITE` + `SOUND` + `RECORD` | Cabecera WAV + SHA-256 (misma arquitectura que PO-35) |

> **Nota importante sobre modelos sin backup:** Los modelos **PO-12 Rhythm, PO-14 Sub, PO-16 Factory, PO-20 Arcade, PO-24 Office, PO-28 Robot y PO-128 Mega Man** carecen de transferencia de proyectos por audio-datos documentada por Teenage Engineering; BeatOS rechaza explícitamente etiquetar grabaciones como backups restaurables de esos modelos.

1. Conecta PO LINE OUT a una **entrada de línea estéreo** de tu interfaz. En el Hub selecciona el **modelo de Pocket Operator** (`PO-32`, `PO-33`, `PO-35`, `PO-133` o `PO-137`), escribe el **nombre del beat/proyecto**, pulsa «Detectar entradas», selecciona la interfaz y pulsa «Grabar backup». Se pide permiso al navegador únicamente al detectar o grabar; no se inicia una grabación al abrir el menú.
2. BeatOS solicita dos canales, sin eco, reducción de ruido ni ganancia automática. Rechaza una entrada mono o procesamiento de voz anunciado como activo. Captura PCM 16-bit a 44.1/48 kHz con AudioWorklet, sin monitorización de retorno, mezcla de canales, efectos ni compresión. Comprueba también los ajustes físicos y del sistema operativo. Si el navegador o interfaz no admiten esta captura, usa un grabador externo en WAV PCM estéreo e importa el archivo.
3. Con la grabación ya iniciada, ejecuta el comando **Enviar** correspondiente a tu modelo (`WRITE + SOUND + PLAY` en PO-33/35/133/137; `WRITE + SOUND` en PO-32). Espera a que termine todo el envío y pulsa «Finalizar y guardar». No apliques normalización, fades, recortes, MP3, limpieza de ruido ni conversión a mono a un backup. La captura se limita a diez minutos y ofrece un enlace visible para descargarla antes de intentar archivarla en la biblioteca.
4. «Importar backup WAV» conserva **los bytes originales**, verifica que el PCM declarado está completo y archiva en `BeatOS/data/po33_backups/<MODELO>/`, junto con un manifiesto lateral `.po.json` no destructivo que registra el modelo, nombre del beat y SHA-256 sin alterar jamás el WAV original. Los archivos heredados sin modelo declarado aparecen como `UNSPECIFIED` y pueden clasificarse desde la interfaz sin tocar el audio.
5. Para grabaciones etiquetadas como **`PO-33`**, el botón **«Verificar paquetes PO-33»** ejecuta el decodificador experimental [`vendor/po33_verify.py`](../../vendor/po33_verify.py) (derivado bajo licencia MIT de `p0k3t0/po-33-exploration`), comprobando la integridad CRC de los paquetes modulados a 44.1 kHz estéreo.
6. «Preparar restauración» pide confirmar el reemplazo y carga el WAV original en un reproductor separado, detenido, a velocidad 1×. Conecta salida estéreo → PO LINE IN; entra en recepción con el comando de tu modelo y después reproduce. **El PO borra todos los sonidos y patrones actuales al empezar a recibir**. No hay restauración por slot ni fusión de proyectos en este flujo.

Para certificar un respaldo hace falta restaurarlo y comprobar sonidos y patrones en el PO. Fuentes: [PO-32](https://teenage.engineering/guides/po-32/en), [PO-33, sección 8](https://teenage.engineering/guides/po-33/en), [PO-35](https://teenage.engineering/guides/po-35/en), [PO-133](https://teenage.engineering/guides/po-133/en) y [PO-137](https://teenage.engineering/guides/po-137/en).

## EP-133 K.O. II

BeatOS genera WAV PCM 16-bit/44.1 kHz, conservando mono/estéreo y niveles originales, más un mapa JSON y un ZIP de transporte. Sólo incluye pads ocupados. FFmpeg es necesario para convertir formatos o frecuencias distintos; un fallo detiene la exportación y no deja un kit parcial anunciado como válido.

Extrae el ZIP y carga los WAV con [EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool). El ZIP BeatOS no es un respaldo nativo. El mapa propone A: teclas 1–9, punto, 0, ENTER; y B: teclas 1–4. La asignación, volumen, panorama, tono y mutes del mapa se aplican manualmente; cargar un WAV no transmite esos parámetros.

La herramienta oficial usa **Web MIDI** por USB-C. El soporte oficial incluye Chrome, Edge y Firefox de escritorio, y excluye Safari y móviles. Permite importar muestras y gestionar respaldos de sistema o proyecto. [Instrucciones oficiales](https://support.teenage.engineering/hc/en-us/articles/11639171890204-how-to-use-the-EP-sample-tool).

La guía actual 2.5 describe 128 MB y hasta 999 muestras; el artículo antiguo de soporte aún menciona 64 MB. Comprueba la capacidad indicada por tu herramienta y firmware. La frecuencia nativa indicada en la guía es 46.875 kHz; el archivo exportado por BeatOS a 44.1 kHz es un formato de intercambio admitido, no la frecuencia nativa. [Guía actual](https://teenage.engineering/guides/ep-133) · [Transferencia y CHOP](https://teenage.engineering/guides/ep-133/functions) · [Ajustes y mutes](https://teenage.engineering/guides/ep-133/modes).

No se ha conectado ni actualizado firmware de hardware durante esta revisión. Una prueba de software no sustituye la carga y escucha física.
