# Rack de 16 pads y exportación

Asigna samples desde el explorador o importa una copia de una pista de batería XPJ / programa XPM Drum. Elige banco A–H cuando exista. El rack usa la primera capa activa y exporta los 16 pads visibles; no es un motor completo de reproducción MPC.

Ajusta volumen, panorama, afinación y grupo de mute desde el inspector del pad. El grupo 0 permite superposición; por defecto bombo=1, hi-hat=2 y caja=3, con el resto libre. Los grupos explícitos de un archivo importado se conservan. Puedes cambiar posiciones e intercambiar pads. Shuffle elige muestras por categorías: no utiliza un modelo de IA.

| Destino | Resultado y límites |
| --- | --- |
| MPC | XPM Drum, XPJ y muestras. Conserva posiciones y ajustes implementados; no replica secuencias, efectos, plugins o edición de cuatro capas. |
| Maschine | WAV y mapa JSON de asignación; no genera MXGRP nativo. |
| SP-404MK2 | Archivos de banco con conversión a PCM 16-bit/48 kHz cuando corresponde. No restaura un proyecto nativo completo. |
| SP-404A/SX | WAV y mapa de 12 pads. |
| PO-33 / PO-133 | Reel mono y mapa de cortes, con pausas y presupuesto ajustables. Panorama y mutes no se transfieren. Comprueba memoria libre y TRIM en el dispositivo. |
| EP-133 K.O. II | WAV mono/estéreo, mapa JSON y ZIP de transporte. Extrae el ZIP e importa los WAV; asignación y parámetros del mapa se aplican manualmente. No es un backup nativo. |

Los WAV de otros formatos/frecuencias y el procesamiento de afinación del reel pueden requerir FFmpeg. Si falta el decodificador o falla una conversión, se informa del error; no basta con cambiar la extensión.

La creación de kits valida muestras y parámetros, rechaza sobrescribir un kit existente y limpia la salida parcial si falla. Exportar no sustituye el proyecto original. Para conservar tu trabajo, exporta antes de cambiar de pista/origen o cerrar la página.

[Guía PO/EP y enlaces del fabricante](09-Pocket-Operator-PO-33-KO-Studio-y-FSK-Modem.md). La validación automatizada usa fixtures; la carga final debe comprobarse en el modelo y firmware de destino.
