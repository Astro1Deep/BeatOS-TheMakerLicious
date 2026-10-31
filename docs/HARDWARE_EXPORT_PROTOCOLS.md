# BeatOS — Protocolos avanzados de exportación y validación en hardware

**Referencia técnica para músicos, beatmakers y productores de música basada en samples** · [English](en/HARDWARE_EXPORT_PROTOCOLS.md) · [Manual completo](MANUAL_COMPLETO.md) · [Compatibilidad](COMPATIBILIDAD_HARDWARE.md) · [Referencia de API](REFERENCIA_TECNICA.md)

**Alcance:** exportadores implementados en BeatOS 3.8.0, examinados el 30 de octubre de 2026. Se distingue entre **estructura del archivo exportado**, **procedimiento admitido por el fabricante** y **prueba física de funcionamiento**. Ni una extensión, ni un manifiesto JSON, ni la correcta ejecución del software garantizan compatibilidad nativa con todos los firmwares.

## 1. Cadena de trabajo y medidas de seguridad

`Biblioteca original → indexación (SQLite/JSON/CSV) → rack 16 pads → validación de parámetros → exportación específica → transferencia/importación del fabricante → escucha, guardado y reapertura en hardware`.

Conserva los samples originales y las **copias de seguridad nativas** de cada equipo. BeatOS rechaza sobrescribir una carpeta de kit ya existente y elimina, cuando puede, una carpeta nueva que haya quedado incompleta por error. No trates la exportación como un backup del aparato.

La conversión de audio genera WAV PCM. Si un archivo de origen necesita conversión, remuestreo o afinación, se requiere **FFmpeg**; algunos WAV compatibles pueden copiarse directamente. Compara niveles y duración **después** de exportar. El rack maneja referencias de samples, ganancia, panorama, afinación en semitonos y grupo de silenciamiento, pero un ajuste en el JSON no demuestra que el hardware lo aplique automáticamente.

## 2. Akai MPC — XPM frente a XPJ

**Entrega:** programa Drum `Akai_MPC/<kit>.xpm` construido a partir de una plantilla XML que contempla archivo por pad, volumen, panorama, afinación gruesa y grupo de mute. Proyecto `Akai_MPC/<kit>/<kit>.xpj` con carpeta `<kit>_[ProjectData]/`, derivado de plantilla comprimida ACVS/JSON orientada a **MPC Sample / AC50**. No equivale a un proyecto One/Live/X universal ni integra sin más todos los efectos, pistas y capas.

**Procedimiento:** conserva juntos XPJ, su carpeta de datos y muestras referenciadas. Revisa nombres, capas, tempo, memoria y programa Drum en la MPC; guarda una **copia nueva** desde el propio aparato y vuelve a cargarla. Akai documenta compatibilidad de proyectos MPC Sample con MPC 3.8 o superior según software/modelo; MPC 2 puede rechazar proyectos recientes. Un XPM válido no certifica que cualquier XPJ abra en cualquier equipo.

Referencia: [Akai — MPC Sample FAQ](https://support.akaipro.com/en/support/solutions/articles/69000876967-mpc-sample-frequently-asked-questions).

## 3. Native Instruments Maschine — WAV y mapa, no grupo nativo

**Entrega:** `NI_Maschine/<kit>/Samples/Group_A/A##_*.wav` y `Groups/<kit>_Maschine_Map.json` con número de pad, nombre, ruta, afinación, panorama, volumen y grupo choke. El JSON es un **mapa operativo**, no un formato `.mxgrp` ni un proyecto `.mxprj`.

**Procedimiento:** importa los WAV en sonidos del grupo de Maschine, reconstruye niveles, choke y organización en la aplicación y **guarda el grupo/proyecto desde Maschine**. Al transferirlo a otro ordenador o Maschine+, incluye todos los samples vinculados y comprueba rutas.

Referencia: [NI — Transferencia de proyectos y samples](https://support.native-instruments.com/support/solutions/articles/69000879595-maschine-sharing-projects-across-multiple-computers).

## 4. Roland SP-404MKII — importación WAV a 48 kHz

**Entrega:** hasta 16 WAV PCM **16-bit/48 kHz**, `PAD_01_*.wav` a `PAD_16_*.wav`, con `sp404mk2_manifest.json`. No genera un backup de proyecto/patrones reconocido como nativo.

**Procedimiento:** utiliza la carpeta y el menú de importación SD adecuados a tu firmware o la aplicación oficial SP-404MKII. Elige banco y pad, importa, escucha y comprueba trim, gate, nivel, afinación y panorama. Los nombres de archivo no aplican automáticamente todos los ajustes del hardware.

Referencias: [Roland — importar/exportar](https://static.roland.com/manuals/sp-404mk2_reference_v500/en-US/7958234778537099.html) · [Formatos y frecuencia](https://static.roland.com/manuals/sp-404mk2_reference_v500/en-US/8010023578592395.html).

## 5. Roland SP-404A/SX — 12 pads por banco

**Entrega:** `A01.wav`–`A12.wav`, PCM **16-bit/44.1 kHz**. Solo se toman los **primeros doce pads** del rack y no se exportan patrones ni una imagen nativa de tarjeta.

**Procedimiento:** importa los WAV siguiendo el manual de tu SP-404A/SX, valida los doce pads y respalda los bancos originales antes de trabajar. Los pads 13–16 del rack no se transfieren a este perfil.

## 6. PO-33/PO-133 — reel de audio y backup módem son procesos distintos

**Entrega:** reel mono PCM **16-bit/44.1 kHz** y JSON con cortes previstos. Pausa configurable 0–500 ms (valor habitual 150 ms); presupuesto elegido de **1–40 segundos**. Puede aplicar recorte y fade para respetarlo. **No es un backup FSK** del contenido y patrones del aparato.

**Procedimiento:** conecta la salida de línea del ordenador a la entrada de la PO, ajusta nivel sin saturar, inicia la grabación en pads de batería, reproduce el reel y revisa los cortes en TRIM. BeatOS **no consulta la memoria real disponible** en la PO. El respaldo completo por audio módem es otro procedimiento: un WAV íntegro con hash SHA-256 no demuestra que sus datos internos hayan sido decodificados ni restaurados correctamente.

## 7. EP-133 K.O. II — herramientas de transferencia de muestras

**Entrega:** hasta 16 WAV PCM **16-bit/44.1 kHz** en `sounds/`, `meta.json` con referencias de grupos/teclas y ZIP de transporte. Los doce primeros pads se asocian al grupo A en el mapa elegido por BeatOS y cuatro al B. **El ZIP no es backup nativo ni aplica automáticamente todos los parámetros.**

**Procedimiento:** extrae el ZIP, conecta por USB-C y abre la [herramienta oficial EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool) desde navegador compatible. Importa WAV y asigna teclas, revisa memoria, volumen, afinación y grupos manualmente. Comprueba el audio y guarda desde el aparato. Firmwares recientes admiten otras tasas mediante la herramienta oficial: 44.1 kHz es la política elegida por BeatOS, no una limitación universal del instrumento.

Referencia: [Teenage Engineering — funciones EP-133](https://teenage.engineering/guides/ep-133/functions).

## 8. Protocolo mínimo de aceptación física

1. Registra **modelo exacto, versión de firmware, aplicación auxiliar y medio** (SD, USB, audio).
2. Genera un kit sintético con samples mono y estéreo; incluye archivos 44.1/48 kHz y nombres Unicode; comprueba WAV, tamaño, duración, rutas y hash de originales.
3. Importa en el dispositivo; verifica sonido por pad, nivel, clipping, panorámica, trim/loop, pitch, choke y número de pads.
4. **Guarda, reinicia o cambia de proyecto y vuelve a cargarlo**. Confirma que referencias, patrones y asignaciones persisten.
5. Registra resultado **CORRECTO**, **FALLO**, **PARCIAL** o **NO PROBADO**, junto con evidencia y pasos de reproducción. Repite tras actualizar firmware.

**Una prueba automatizada correcta acredita el exportador, no la compatibilidad física completa.** Si un equipo exige un archivo propietario nativo, habrá que investigar su estructura y probar un ciclo real de exportación/importación antes de declarar soporte.
