# Rack de 16 pads y exportación para varios samplers

El rack es el punto común de preparación para MPC, Maschine, SP-404MK2, SP-404A/SX, PO-33/PO-133 y EP-133 K.O. II. No necesitas importar un proyecto MPC: puedes montar el kit desde muestras de tu biblioteca. [Primer kit paso a paso y comparación de destinos](../../README.md#rack-y-destinos).

Asigna samples desde el explorador o importa una copia de una pista de batería XPJ / programa XPM Drum. Elige banco A–H cuando exista. El rack usa la primera capa activa y exporta los 16 pads visibles; no es un motor completo de reproducción MPC.

Ajusta volumen, panorama, afinación y grupo de mute desde el inspector del pad. El grupo 0 permite superposición; por defecto bombo=1, hi-hat=2 y caja=3, con el resto libre. Los grupos explícitos de un archivo importado se conservan. Puedes cambiar posiciones e intercambiar pads. Shuffle elige muestras por categorías: no utiliza un modelo de IA.

| Destino | Resultado y límites |
| --- | --- |
| MPC | XPM Drum, XPJ y muestras. Conserva posiciones y ajustes implementados; no replica secuencias, efectos, plugins o edición de cuatro capas. |
| Maschine | WAV y mapa JSON de asignación; no genera MXGRP nativo. |
| SP-404MK2 | Archivos de banco con conversión a PCM 16-bit/48 kHz cuando corresponde. No restaura un proyecto nativo completo. |
| SP-404A/SX | WAV `A01.wav`–`A12.wav`; sólo pads 1–12, sin mapa JSON. Los pads 13–16 quedan fuera de esta entrega. |
| PO-33 / PO-133 | Reel mono y mapa de cortes, con pausas y presupuesto ajustables. Panorama y mutes no se transfieren. Comprueba memoria libre y TRIM en el dispositivo. |
| EP-133 K.O. II | WAV mono/estéreo, mapa JSON y ZIP de transporte. Extrae el ZIP e importa los WAV; asignación y parámetros del mapa se aplican manualmente. No es un backup nativo. |

Los WAV de otros formatos/frecuencias y el procesamiento de afinación del reel pueden requerir FFmpeg. Si falta el decodificador o falla una conversión, se informa del error; no basta con cambiar la extensión.

La creación de kits valida muestras y parámetros, rechaza sobrescribir un kit existente y limpia la salida parcial si falla. Exportar no sustituye el proyecto original. Para conservar tu trabajo, exporta antes de cambiar de pista/origen o cerrar la página.

[Guía PO/EP y enlaces del fabricante](09-Pocket-Operator-PO-33-KO-Studio-y-FSK-Modem.md). La validación automatizada usa fixtures; la carga final debe comprobarse en el modelo y firmware de destino.

## Exportar desde la interfaz

Abre la biblioteca por HTTP y prepara el rack. En «Exportar Kit», indica el nombre, elige «Destino de Hardware» y pulsa «Generar Kit en Tarjeta MicroSD». Se guarda en `Custom_Kits/<nombre>/` de la biblioteca activa; ésta puede ser una carpeta del ordenador o una unidad montada. El aviso final indica las rutas generadas. Elegir un equipo produce sólo su entrega; «Bundle Universal» ejecuta los seis exportadores.

Si partes de XPJ/XPM, confirma el banco visible antes de exportar. El resultado usa los pads de ese banco, no todas las pistas y bancos del proyecto original. Para SP-404A/SX mueve los sonidos que necesites a los pads 1–12 antes de generar.

## Localizar y utilizar los archivos

Las rutas siguientes son relativas a `Custom_Kits/<nombre>/`. `<nombre>` representa el nombre del kit, normalizado a letras sin acentos, números, guiones y guiones bajos.

| Carpeta de destino | Qué encontrarás | Qué haces después |
| --- | --- | --- |
| `Akai_MPC/` | `<nombre>.xpm` con WAV junto al programa; además, `<nombre>/<nombre>.xpj` y su carpeta `<nombre>_[ProjectData]/`. | Conserva las muestras y la estructura de carpetas al copiar. Abre el programa o proyecto en MPC y comprueba las referencias y pads. |
| `NI_Maschine/<nombre>/` | `Samples/Group_A/` y `Groups/<nombre>_Maschine_Map.json`. | Carga los WAV en los slots indicados. Aplica manualmente volumen, panorama, afinación y choke group del mapa; Maschine no importa este JSON como un `.mxgrp`. |
| `Roland_SP404MK2/<nombre>/` | `PAD_01_*.wav`–`PAD_16_*.wav` para los pads ocupados y `sp404mk2_manifest.json`. | Importa los WAV siguiendo el procedimiento del modelo. El manifiesto relaciona pad, archivo y original; no contiene una sesión ni traslada los parámetros del rack. |
| `Roland_SP404A/<nombre>/` | `A01.wav`–`A12.wav` para los pads ocupados de ese rango. | Prepara la carga con el procedimiento de importación de A/SX; verifica posiciones. No se generan archivos para los pads 13–16 ni un manifiesto de ajustes. |
| `Pocket_Operator_PO33/` | `<nombre>_PO33_AutoSlice_Reel.wav` y `<nombre>_PO33_Slices.json`. | Reproduce el reel hacia la entrada de audio del PO y grábalo. Usa el mapa de tiempos y frames para revisar los cortes; el JSON no se carga en el aparato. |
| `Teenage_Engineering_EP133/<nombre>/` | `sounds/`, `meta.json` y `README_EP133_KO_II.txt`; el ZIP de transporte queda en la carpeta superior. | Extrae el ZIP, importa los WAV con EP Sample Tool y usa el mapa para asignar teclas y ajustes. El ZIP no restaura un proyecto EP. |

## Parámetros, audio y memoria

En MPC se escriben los ajustes implementados en el programa/proyecto. Maschine y EP-133 reciben los ajustes como datos de un mapa para aplicarlos manualmente: sus WAV conservan nivel y canales originales. Las entregas SP-404 convierten el audio, pero no incorporan los parámetros del rack en un proyecto nativo. El reel PO convierte a mono y procesa volumen y afinación en el propio audio; después normaliza el conjunto. No conserva panorama ni grupos de mute.

El rack general usa los valores PO predeterminados de 40 s y 150 ms entre golpes. Si necesitas adaptarlos a la memoria libre, genera el reel desde el Hub PO, con presupuesto de 1–40 s y pausas de 0–500 ms. Las pausas cuentan dentro del presupuesto. Si el audio no cabe, puede recortarse con fade-out; revisa `smart_trim_applied` y los cortes en el manifiesto. El indicador no mide la memoria real del dispositivo.

## Si no se genera el kit

- **Vista por archivo o servidor detenido:** abre la URL HTTP que muestra el servidor para esa biblioteca.
- **Nombre ya existente:** usa otro nombre; no se sobrescribe la entrega anterior.
- **Sample ausente o fuera de la biblioteca:** comprueba la ruta activa y la ubicación de los archivos. Reindexa si has cambiado la biblioteca y vuelve a asignar las muestras afectadas.
- **Conversión no disponible:** comprueba FFmpeg y el formato de la fuente. SP-404MK2 pide 48 kHz; los demás exportadores aquí descritos generan audio de intercambio a 44.1 kHz.
- **Fallo del bundle universal:** cualquiera de sus exportadores puede cancelar la operación y retirar la salida parcial. Si sólo necesitas un aparato, selecciona su destino y resuelve el error indicado.

Antes de cerrar, exporta el rack y comprueba que los archivos existen. La confirmación del servidor verifica la generación en disco; la comprobación final de carga, escucha y parámetros se realiza en el aparato o software de destino.
