# 🎛️ Akai MPC Sample Database & Finder Toolkit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![SQLite 3](https://img.shields.io/badge/database-SQLite_3-orange.svg)](https://www.sqlite.org/)
[![Akai MPC](https://img.shields.io/badge/Hardware-MPC_Standalone_Ready-red.svg)](https://www.akaipro.com/)

Un toolkit universal, ligero y autónomo en **Python 3 + SQLite + HTML5** diseñado para la comunidad de productores y beatmakers que utilizan hardware **Akai MPC Standalone** (Live, Live II, One, One+, X, X SE, Key 37, Key 61) y la serie MPC Studio / Touch.

Permite indexar automáticamente cualquier tarjeta Micro SD, unidad USB o carpeta de samples en segundos, estructurando una **base de datos SQLite relacional** y generando un **catálogo interactivo web en HTML5** con reproductor de audio, filtros multidimensionales y buscador de rutas para el explorador del hardware MPC.

---

## 🚀 Características Principales

1. **Base de Datos SQLite Relacional (`mpc_sample.db`)**:
   - Indexación ultrarrápida de miles de archivos de audio (`.wav`, `.aif`, `.mp3`, `.flac`).
   - Clasificación inteligente por tipo de sonido: `KICK`, `SNARE`, `CLAP`, `HIHAT`, `808/BASS`, `KEYS/SYNTH`, `MELODIC_LOOPS`, `DRUM_LOOPS/BREAKS`, `VOCALS`, `FX`.
   - Detección automática de **Tempo (BPM)** y asignación a rangos rítmicos de producción musical (Lo-Fi, Boom Bap, Trap, House, DnB).
   - Detección de **Tonalidad Musical (Key)** y mapeo automático a la rueda **Camelot** (ej: *Dm / 7A*, *C / 8B*).
   - Estimación lógica del nivel de energía sonora (*Chill*, *Groove*, *Banger*).

2. **Auditoría de Proyectos MPC Standalone (`.xpj`)**:
   - Descomprime y analiza los proyectos `.xpj` en formato JSON interno.
   - Detecta tempo de secuencia, escala musical y todas las muestras referenciadas.
   - Comprueba automáticamente si todas las muestras existen en su carpeta `_[ProjectData]`, marcando el proyecto como `HEALTHY` o `ATTENTION`.

3. **Reconocimiento de Expansiones Oficiales MPC**:
   - Parsea los archivos `Expansion.xml` en la carpeta `/Expansions`.
   - Extrae el fabricante, tipo, versión, imagen de portada y contabiliza programas (`.xpm`) y samples.

4. **Catálogo Web Interactivo en HTML5**:
   - Sin dependencias externas ni servidores web requeridos (abre con doble clic).
   - Búsqueda en tiempo real por palabra clave, BPM, clave musical o categoría.
   - Reproductor de audio integrado para escuchar las muestras al instante.
   - Botón para **copiar la ruta exacta** para cargar en los pads del MPC.

---

## 📦 Estructura del Repositorio

```text
mpc-sample-database-toolkit/
├── install.sh                # Instalador interactivo para macOS y Linux
├── installer.py              # Instalador universal multiplataforma (Windows / Mac / Linux)
├── index_mpc_library.py      # Motor autónomo de indexación en Python 3 puro
├── schema.sql                # Definición formal de la base de datos SQLite
├── catalogo_universal.html   # Plantilla del catálogo HTML interactivo
├── LICENSE                   # Licencia MIT
└── README.md                 # Documentación del proyecto
```

---

## ⚡ Instalación Rápida

### Opción 1: En macOS o Linux (Vía Terminal)
```bash
# 1. Clona el repositorio
git clone https://github.com/TU_USUARIO/mpc-sample-database-toolkit.git
cd mpc-sample-database-toolkit

# 2. Da permisos de ejecución e inicia el instalador
chmod +x install.sh
./install.sh
```

### Opción 2: Multiplataforma con Python (Windows, Mac, Linux)
```bash
python3 installer.py
```

### Opción 3: Indexación Directa desde la Línea de Comandos
Puedes apuntar el indexador directamente a tu tarjeta SD o disco:
```bash
python3 index_mpc_library.py --path "/Volumes/MPCSMPL"
```

El script creará automáticamente la carpeta `SQLITE_DATABASE/` en tu tarjeta con:
- `mpc_sample.db`
- `mpc_sample.json`
- `mpc_sample_resumen.csv`
- `catalogo_mpc_sample.html`

---

## 💻 Consultas SQLite de Ejemplo

Puedes interactuar directamente con la base de datos usando `sqlite3`:

```bash
# Buscar todos los bombos (Kicks) en la librería:
sqlite3 mpc_sample.db "SELECT filename, sub_pack, size_mb FROM samples WHERE sound_type='KICK' LIMIT 10;"

# Buscar loops a 140 BPM en escala Dm (Trap / Drill):
sqlite3 mpc_sample.db "SELECT filename, sub_pack, camelot FROM samples WHERE bpm=140 AND musical_key='Dm';"

# Ver distribución de muestras por energía sonora:
sqlite3 mpc_sample.db "SELECT energy_level, count(*) FROM samples GROUP BY energy_level;"
```

---

## 🌐 English Quickstart

### What is this?
A lightweight, zero-dependency toolkit for **Akai MPC Standalone** users (MPC One, Live, X, Key) that indexes your SD card or sound library into a relational **SQLite database** and generates a **standalone interactive HTML catalog**.

### How to use:
1. Clone this repo:
   ```bash
   git clone https://github.com/YOUR_USERNAME/mpc-sample-database-toolkit.git
   cd mpc-sample-database-toolkit
   ```
2. Run the indexer pointing to your MPC SD card or sample folder:
   ```bash
   python3 index_mpc_library.py --path "/path/to/your/mpc/sdcard"
   ```
3. Open the generated `catalogo_mpc_sample.html` in any web browser to search, filter by BPM/Key, listen to audio samples, and copy paths for your MPC hardware!

---

## 📄 Licencia

Este proyecto está bajo la Licencia **MIT**. Consulta el archivo [LICENSE](LICENSE) para más detalles.
Contribuidores y productores de la comunidad MPC son bienvenidos a enviar Pull Requests y mejoras.
