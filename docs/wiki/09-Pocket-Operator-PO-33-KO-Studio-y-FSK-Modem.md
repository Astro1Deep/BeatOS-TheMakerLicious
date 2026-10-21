# 🕹️ 09. Pocket Operator PO-33 / PO-133 Studio & FSK Audio Modem

Esta sección documenta el soporte de ingeniería para los samplers de bolsillo **Teenage Engineering Pocket Operator PO-33 K.O.! y PO-133 Street Fighter**.

---

## ⏱️ 1. Restricciones Críticas de Hardware

El microcontrolador del PO-33 opera bajo especificaciones estrictas:
* **Capacidad Máxima de Muestra**: **40.0 segundos totales** de memoria RAM compartida entre los 16 slots.
* **Distribución de Ranuras**:
  - Ranuras 1 a 8: **Slots Melódicos** (un sample asignado cromáticamente a lo largo de los 16 botones).
  - Ranuras 9 a 16: **Slots de Batería (Drum Kits)** (cada slot contiene hasta 16 slices o cortes independientes).
* **Frecuencia de Muestreo Hardware**: 16-bit / 44.1 kHz.

---

## 🥁 2. Generador de Drum Reel con Auto-Slice de 150 ms

El PO-33 cuenta con un algoritmo interno de corte por transitorios (**Auto-Slice**) que segmenta automáticamente un sonido en hasta 16 porciones cuando detecta pausas de silencio entre golpes.

### Calibración del Reel
El módulo [`hardware_kit_builder.py`](file:///Users/ivan/Documents/mpc-sample-database/hardware_kit_builder.py) sintetiza una única pista de audio continua concatenando los pads 9 al 16 con las siguientes características:
1. **Silencio Calibrado**: Exactamente **150 milisegundos de silencio digital puro** entre cada muestra. Menos de 100 ms puede provocar que el algoritmo una dos golpes; más de 250 ms desperdicia memoria RAM valiosa.
2. **Presupuesto Estricto**: El generador verifica matemáticamente que la suma total de los samples más los silencios **no supere los 40.0 segundos**, emitiendo una alerta si se excede el límite.
3. **Puntos de Trim**: Exporta un manifiesto en JSON y TXT con los puntos de corte en milisegundos (`start_ms` y `end_ms`).

---

## 📡 3. Protocolo de Respaldo por Audio Módem FSK (1 a 4 min)

El PO-33 permite realizar copias de seguridad completas de sus patrones, kits y sonidos mediante un flujo de modulación por desplazamiento de frecuencia (**FSK - Frequency Shift Keying**), transmitido a través del conector jack estéreo de 3.5 mm.

### Especificaciones del Archivo de Backup PO-33
* **Duración Dinámica**: La duración **no es fija**; depende directamente del volumen de datos ocupados en la memoria de muestreo (40s RAM) y de los patrones secuenciados. Un volcado suele durar **entre 1 y 4 minutos** (típicamente ~3 a 3.5 minutos cuando la memoria está al 100%; archivos de demostración o ligeros como `boombap.wav` duran ~73.6 segundos).
* **Estructura Estéreo**: 44.1 kHz / 16-bit PCM (Canal Izquierdo: Datos binarios modulados en FSK; Canal Derecho: Pista de audio de sincronización / clock o portadora complementaria).
* **Verificación Forense**:
  El analizador examina la cabecera del archivo WAV, la frecuencia de muestreo, estructura estéreo y la presencia de tonos de portadora de audio de alta frecuencia característicos del módem FSK.
* **Carga en los Pads Web**:
  Desde la pestaña **`🕹️ Pocket Operator (PO-33)`** del catálogo, puedes preescuchar y verificar cualquier archivo de backup existente en tu carpeta de usuario (ej. `boombap.wav`, `backup_po33.wav`), y cargarlo de vuelta a la interfaz web para editar o intercambiar sus sonidos.

---

## ⚡ 4. Comparativa Arquitectónica: PO-33 vs. EP-133 K.O. II

| Parámetro | Teenage Engineering PO-33 / PO-133 | Teenage Engineering EP-133 K.O. II |
| :--- | :--- | :--- |
| **Memoria de Muestreo** | 40.0 segundos totales (Mono, ~8/12-bit interno) | 64 MB / 128 MB (Estéreo/Mono, 999 slots) |
| **Carga de Drum Kits** | Tira de audio Drum Reel con auto-slice (pausas 150ms) | Transferencia digital directa o grabación estéreo |
| **Protocolo de Backup** | **Módem de audio FSK (analógico por jack 3.5mm)** | **USB-C Digital (WebMIDI / SysEx / EP Sample Tool)** |
| **Duración de Transferencia** | 1 a 4 minutos (audio audible en tiempo real) | Segundos / transferencia digital por cable USB |
| **Conectividad** | Jack 3.5mm LINE IN / LINE OUT | USB-C (Audio/MIDI/Alimentación) + MIDI DIN + Sync 3.5mm |
