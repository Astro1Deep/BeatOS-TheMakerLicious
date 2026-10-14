# 🎹 3. Taxonomía y Detección de Audio

El indexador `index_mpc_library.py` integra un motor heurístico de análisis de nomenclatura musical. Sin requerir pesadas librerías de procesado DSP o inteligencia artificial en la nube, procesa decenas de miles de archivos por minuto deduciendo el rol sonoro, tempo, clave y energía a partir de los patrones de producción estándar de la industria.

---

## 🥁 Los 12 Tipos de Sonido Universales

Cada muestra de audio (`.wav`, `.aif`, `.mp3`, `.flac`) es evaluada contra una matriz de expresiones regulares y asignada a uno de los siguientes 12 códigos:

| Código | Icono | Descripción y Palabras Clave Detectadas |
| :--- | :---: | :--- |
| `KICK` | 🥁 | Bombos acústicos, sintéticos, 808 kicks, sub kicks (`kick`, `kik`, `bd`, `bassdrum`, `bombo`). |
| `SNARE` | 💥 | Cajas, tarolas, rimshots, cross sticks (`snare`, `snr`, `rim`, `sidestick`, `caja`, `tarola`). |
| `CLAP` | 👏 | Aplausos, palmas, chasquidos de dedos (`clap`, `clp`, `snap`, `palmas`, `handclap`). |
| `HIHAT` | ✨ | Hi-hats abiertos, cerrados, pedales, shakers y panderetas (`hihat`, `hat`, `openhh`, `closedhh`, `shaker`, `tamb`). |
| `CYMBAL` | 💿 | Platos crash, ride, splash, china y gongs (`crash`, `ride`, `cymbal`, `splash`, `china`). |
| `PERCUSSION` | 🪘 | Congas, bongos, toms, foley orgánico, cencerros, claves, cajón (`perc`, `conga`, `bongo`, `tom`, `foley`, `woodblock`). |
| `BASS_808` | 🔊 | Bajos 808, sub-bajos, Reese bass, bajo eléctrico, sintetizado (`808`, `sub`, `bass`, `subbass`, `reese`, `bassline`). |
| `KEYS_SYNTH` | 🎹 | Pianos de cola, Rhodes, Wurlitzer, sintes, leads, pads, metales, cuerdas (`piano`, `rhodes`, `synth`, `lead`, `pad`, `brass`, `strings`). |
| `MELODIC_LOOP` | 🎸 | Loops melódicos, chops de sample, riffs de guitarra, acordes arpegiados (`melody`, `riff`, `chops`, `stem`, `loop`, `lick`). |
| `DRUM_LOOP` | 🔁 | Breakbeats clásicos, bucles de batería rítmica, ritmos completos (`break`, `breakbeat`, `drumloop`, `amen`, `top loop`). |
| `VOCAL` | 🎤 | Voces, acapellas, frases habladas, ad-libs, coros (`vocal`, `vox`, `acapella`, `chant`, `adlib`, `phrase`). |
| `FX` | ⚡ | Risers, sweeps, ruidos blancos, texturas de vinilo, ecos espaciales (`fx`, `sfx`, `riser`, `sweep`, `vinyl`, `crackle`, `noise`). |

---

## ⏱️ Detección de Tempo (BPM) y Rangos Rítmicos

El algoritmo extrae números de tempo comprendidos entre **55 y 190 BPM** presentes en el nombre del archivo (ej: `Soul_Rhodes_92BPM.wav`, `Trap_Loop_[140]_Dm.wav`, `Break_88_vinyl.wav`).

Posteriormente, asigna automáticamente la muestra a un **Rango de Tempo (BPM Tier)**:

* **`DOWN_TEMPO`** (< 85 BPM): Lo-Fi suave, ambient, downtempo, trip-hop lento.
* **`BOOM_BAP_LOFI`** (85 - 98 BPM): El tempo dorado del Hip-Hop clásico de los 90s, Boom Bap y Lo-Fi beats.
* **`MID_TEMPO`** (99 - 118 BPM): R&B, Funk, Disco, Pop moderno y Afrobeats.
* **`HOUSE_GARAGE`** (119 - 132 BPM): Deep House, Tech House, UK Garage, Electro.
* **`TRAP_HALFTIME`** (133 - 155 BPM): Trap contemporáneo, Drill británico/neoyorquino y Dubstep a medio tiempo.
* **`DNB_JUNGLE`** (> 155 BPM): Drum & Bass, Jungle, Breakcore y Footwork.

---

## 🎼 Tonalidad Musical y Mapeo Rueda Camelot

El motor detecta claves mayores y menores escritas con notación tradicional y las convierte al sistema armónico **Camelot** (1A a 12B) para facilitar mezclas armónicas y combinaciones de melodías en el MPC:

| Tonalidad Mayor | Camelot | Tonalidad Menor | Camelot |
| :---: | :---: | :---: | :---: |
| **B** | 1B | **G#m / Abm** | 1A |
| **F# / Gb** | 2B | **D#m / Ebm** | 2A |
| **Db / C#** | 3B | **Bbm / A#m** | 3A |
| **Ab** | 4B | **Fm** | 4A |
| **Eb** | 5B | **Cm** | 5A |
| **Bb** | 6B | **Gm** | 6A |
| **F** | 7B | **Dm** | 7A |
| **C** | 8B | **Am** | 8A |
| **G** | 9B | **Em** | 9A |
| **D** | 10B | **Bm** | 10A |
| **A** | 11B | **F#m** | 11A |
| **E** | 12B | **C#m** | 12A |

> **Ejemplo Práctico**: Si estás produciendo un beat en escala **Dm (7A)**, puedes filtrar en el catálogo todas las muestras con código `7A`, `8A` o `6A` para asegurar compatibilidad armónica perfecta sin desafinaciones.

---

## ⚡ Estimación del Nivel de Energía

Cada sonido se clasifica en 3 intensidades de producción:
* **`CHILL`**: Samples suaves, Rhodes apagados, texturas ambientales, ruidos de vinilo o tempos lentos.
* **`GROOVE`**: Ritmos estándar de bombo y caja, ritmos house de 124 BPM, licks melódicos y líneas de bajo con cadencia rítmica.
* **`BANGER`**: 808s distorsionados, sub-bajos pesados, claps agudos, drops a 140 BPM o percusión de alta intensidad.
