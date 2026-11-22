# Playbook de Ingeniería de Audio, MIR y Chopping Musical (BeatOS + Cerebro OS)

Guía técnica de referencia sobre cómo **BeatOS** y **Cerebro OS (MLX + DSP)** analizan, masterizan, detectan estructura musical y trocean muestras para **Akai MPC Sample (AC50 1.3.0.12)** sin distorsión ni errores rítmicos.

Para contexto general del hardware y del servidor véanse también [REFERENCIA_TECNICA.md](REFERENCIA_TECNICA.md) y [MANUAL_COMPLETO.md](MANUAL_COMPLETO.md).

---

## 1. Cadena `float32` Anti-Clipping (`MP4 / AAC / MP3 → WAV 16-bit 44.1 kHz`)

Las fuentes comprimidas en `.mp4` / AAC suelen decodificarse con picos inter-muestra reales de **`+2.5 dBFS` a `+3.0 dBFS`**. Si se convierten directamente a PCM entero de 16 bits, la forma de onda queda truncada de forma irreversible.

1. Decodificar siempre a **`float32` crudo (`-f f32le`)** a **44.100 Hz** (mono para expansiones vintage mono-vinilo o estéreo según kit).
2. Aplicar filtro **pasa-altos Butterworth orden 2 fase cero (`24 Hz`, `sosfiltfilt`)** para suprimir offset DC y retumbo subsónico sin desfasar transientes.
3. Escalar linealmente el pico exacto a **`-0.80 dBFS`** (`10^(-0.80/20)`), conservando la microdinámica natural (`~-15 dBFS` RMS en vinilo) sin limitadores agresivos.
4. Añadir **dither triangular TPDF (`±1 LSB`)** antes de cuantizar a **PCM 16-bit (`int16`)**.

---

## 2. Separación Armónica/Percusiva, Afinación Vintage y Camelot

- **HPSS (`margin=2.0`)**: separa la capa armónica (`y_harm`) de la percusiva (`y_perc`) para evitar que maracas, güiro o chasquidos de vinilo contaminen el cromagrama.
- **Compensación de deriva `A440`**: calcular `estimate_tuning` (`36 bins/octava`) antes de extraer `chroma_cqt`, corrigiendo desviaciones de `±10..±25 cents` habituales en cintas y vinilos de los años 50–70.
- **Ponderación RMS + Perfiles Duales**: ponderar por RMS armónico y correlacionar contra plantillas combinadas **Krumhansl-Schmuckler + Temperley**, mapeando a la rueda **Camelot (`1A–12B`)**.
- **Auditoría de Choques Armónicos (`Bass / 808 vs Loop`)**: toda diferencia `semitone_fix != 0` fuera de tónica o quinta justa se corrige por semitonos para eliminar disonancias en subgraves.

---

## 3. Tempo Real, Compás y Fase del Downbeat ($\phi^*$)

- Se evita `beat_track(hop=512)` (cuantización gruesa a buckets como `76.0 / 80.7 / 86.1 BPM`) y ventanas cortas que duplican tempo por percusión aguda (`130–160 BPM`).
- Se calcula una curva unificada a **`hop=256`**:
  `O[t] = 0.45 * perc_onset + 0.30 * bass_onset(<= 220 Hz) + 0.25 * HCDF`
  donde **HCDF** (*Harmonic Change Detection Function*) mide los cambios armónicos reales en pistas con o sin batería (*drumless*).
- Se estima el BPM mediante **autocorrelación FFT insesgada de media cero** en **`62–118 BPM`**, desambiguando octavas con la cadencia armónica HCDF y siguiendo beats con **`tightness=120`**.
- **Compás (`3/4`, `4/4`, `6/8`, `12/8`, `5/4`)**: comparación de autocorrelación síncrona al beat en `lag=3` vs `lag=4` sobre `(0.55*HCDF + 0.45*Bass)`.
- **Tiempo 1 ($\phi^*$)**: selección de la fase modular $M$ que maximiza `0.55*HCDF + 0.35*Bass + 0.10*RMS_jump` para anclar el primer chop al inicio armónico real del compás.

---

## 4. Chopping Musical MMR (3 Bancos / 48 Pads) y Cortes Limpios

1. Proyección de cromagrama síncrono a **24 tríadas (mayores/menores)** para etiquetado armónico por chop.
2. Selección por **Maximal Marginal Relevance (MMR)** en **16 zonas cronológicas** (`cos_sim <= 0.94` sobre `[Chroma + MFCC]`), premiando claridad HCDF de arranque, novedad estructural y presencia melódica/vocal (`300–3.200 Hz`).
3. **Arquitectura estándar de 3 bancos (`48 pads`)**:
   - **Banco A (`01–16`)**: frases completas de **1 compás**.
   - **Banco B (`17–32`)**: chops rítmicos de **2 tiempos** (ideales para Boom-Bap, Lo-Fi y **puentes `3/4 → 4/4`** en pasos `1, 5, 9, 13`).
   - **Banco C (`33–48`)**: **turnarounds de 3 / 2.5 tiempos y hooks vocales**.
4. **Cero Clicks ni Micro-Stubs**:
   - Ajuste a cruce por cero más cercano (`±5 ms`) y **micro-fades coseno (`2 ms` in / `8 ms` out)**.
   - Bloqueo de colas residuales cortas mediante `min_dist_frames` adaptativo y `min_tail_frames` en `hardware_kit_builder.py`.
   - En `.xpm`: plantilla completa (`>900 KB`), `MuteGroup=1` (o `M6` en kits híbridos), `Mono=True`, `Polyphony=1`, `OneShot=False`, `RootNote=MIDI_Key`.

---

## 5. Reglas de Producción, Rubato, Formantes e Higiene

- **Rubato / Drumless**: no aplicar Time-Stretch / Warp global largo; cortar por frases cortas en grupo monofónico **`M6`**.
- **Límite de Formantes (`±4.5 st`)**: si la adaptación de BPM exige `|repitch_semitones| > 4.5`, **Cerebro MLX Copilot** advierte distorsión de formantes y prioriza **`MPC Warp 0 st`** o chops de 2 tiempos frente a *Vinyl Repitch*.
- **Mezcla y Submix MPC**: **HPF `95–120 Hz`** en chops para liberar Kick/808, limpieza opcional de **`220–380 Hz`** (`-2/-3 dB`) en muestras densas y grupos **`M1`/`M6`** (Chops), **`M2`** (Hi-Hats), **`M3`** (Bass/808).
- **Higiene de archivos fuente**: deduplicación **SHA-256** antes de procesar lotes; mover `.mp4` originales ya convertidos fuera de `/Volumes/MPCSMPL/Expansions/` hacia `/Volumes/MPCSMPL/_RAW_SOURCE_ARCHIVES/...` sin tocar nunca `/autorun` ni `/mpcqol.conf`.
