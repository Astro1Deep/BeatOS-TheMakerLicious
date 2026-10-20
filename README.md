# 🎛️ BeatOS — The MakerLicious
### The system ★ [universal beatmaker station]
> `│ ref: pocket operator · ep-133 · akai mpc sample · roland sp-404mk2 · ni maschine │`  
> **Universal Beatmaker Hub & Multi-Sampler Toolkit**

<p align="center">
  <img src="docs/assets/branding/banner_variant_01_mpc_sample.jpg?v=20261020" alt="BeatOS (The System) - The MakerLicious Edition Hardware Blueprint" width="100%">
  <br>
  <sub><b>Hardware Suite Specifications (3 Variantes Oficiales):</b> <a href="docs/assets/branding/banner_variant_01_mpc_sample.jpg">01 / MPC Sample Edition</a> · <a href="docs/assets/branding/banner_variant_02_mpc_one.jpg">02 / MPC One Edition</a> · <a href="docs/assets/branding/banner_variant_03_mpc_live3.jpg">03 / MPC Live III Edition</a></sub>
</p>

[![License: CC BY-NC-ND 4.0](https://img.shields.io/badge/License-CC%20BY--NC--ND%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-nd/4.0/)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Astro1Deep-ff5e5b.svg?logo=ko-fi&logoColor=white)](https://ko-fi.com/astro1deep)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-ea4aaa.svg?logo=github&logoColor=white)](https://github.com/sponsors/Astro1Deep)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![SQLite 3](https://img.shields.io/badge/database-SQLite_3-orange.svg)](https://www.sqlite.org/)
[![Multi-Sampler](https://img.shields.io/badge/Hardware-MPC_·_EP133_·_SP404_·_Maschine_·_PO33-red.svg)](https://github.com/Astro1Deep/mpc-sample-database)
[![Themes](https://img.shields.io/badge/Themes-TE_Arcade_|_Cerebro_|_MPC_|_SP404_|_Maschine-orange.svg)](#-los-4-pilares-culturales-y-temas-visuales)
[![Bilingual](https://img.shields.io/badge/Language-ES_|_EN-cyan.svg)](#-bilingual-support--soporte-bilingüe)
[![Wiki](https://img.shields.io/badge/Docs-Official_Wiki-success.svg)](https://github.com/Astro1Deep/mpc-sample-database/wiki)

Un ecosistema universal, ultraligero y autónomo en **Python 3 + SQLite + HTML5** diseñado para beatmakers y productores musicales. Permite indexar, preescuchar, auditar y diseñar drum kits para:
- **Akai MPC Standalone & Studio** (MPC Sample, One, One+, Live, Live II, X, X SE, Key 37/61, Studio MK2)
- **Teenage Engineering EP-133 K.O. II** (128 MB Sampler Composer, paquetes `.pak` y `sounds/`)
- **Roland SP-404MK2 / SP-404A / SX** (16 pads / 12 pads)
- **Teenage Engineering Pocket Operator** (PO-20 Arcade, PO-33 K.O.!, PO-133)
- **Native Instruments Maschine** (MK3, Plus, Mikro)

---

## ☕ Apoya el Proyecto / Support the Project

BeatOS es un proyecto comunitario independiente desarrollado con pasión por el beatmaking y el diseño de hardware musical. Es **100% autónomo, libre de telemetría y sin dependencias externas pesadas**.

Si BeatOS te ahorra tiempo organizando tus librerías de samples, diseñando drum kits o pasando audio a tu hardware, puedes apoyar su desarrollo continuo con una microdonación (1€ a 3€):

* ☕ **[Ko-fi: Invitar a un café en Ko-fi (1€)](https://ko-fi.com/astro1deep)**
* 💖 **[GitHub Sponsors: Astro1Deep](https://github.com/sponsors/Astro1Deep)**

Cada aportación ayuda a costear el mantenimiento, la investigación en ingeniería inversa de formatos propietarios y el soporte de nuevas plataformas de sampling.

---

## 🌐 Bilingual Support / Soporte Bilingüe

El catálogo web interactivo y la documentación cuentan con **soporte bilingüe instantáneo (Español / English)**:
* Pulsa el botón **`🌐 ES | EN`** en la barra superior para alternar de forma inmediata todo el entorno visual.
* La preferencia de idioma se almacena automáticamente en el navegador (`localStorage`).
* Toda la documentación de la Wiki y guías técnicas están organizadas con referencias claras en ambos idiomas.

---

## 📚 Documentación Oficial y Wiki / Official Wiki

Visita la **[Wiki Oficial en GitHub](https://github.com/Astro1Deep/mpc-sample-database/wiki)** o consulta los artículos en el repositorio:

* **[🏠 Portada de la Wiki / Home](docs/wiki/Home.md)**
* **[🚀 1. Instalación y Puesta en Marcha](docs/wiki/01-Instalacion-y-Puesta-en-Marcha.md)**: Instalador interactivo y streaming local.
* **[📁 2. Organización MicroSD para MPC](docs/wiki/02-Organizacion-MicroSD-para-MPC.md)**: Las 7 macro-categorías y purga de `._*`.
* **[🎹 3. Taxonomía y Detección de Audio](docs/wiki/03-Taxonomia-y-Deteccion-de-Audio.md)**: 12 tipos de sonido, rangos BPM y Camelot.
* **[🔍 4. Auditoría de Proyectos (.xpj)](docs/wiki/04-Auditoria-de-Proyectos-MPC-(xpj).md)**: Inspección de JSON interno y verificación `_[ProjectData]`.
* **[📦 5. Expansiones Oficiales Akai](docs/wiki/05-Expansiones-Oficiales-Akai.md)**: Parseo de `Expansion.xml`, kits `.xpm` y programas.
* **[🌐 6. Catálogo Web y Audio Player](docs/wiki/06-Catalogo-Web-y-Audio-Player.md)**: Servidor RFC 7233 Range Requests (HTTP 206).
* **[📊 7. Consultas Avanzadas SQLite](docs/wiki/07-Consultas-Avanzadas-SQLite.md)**: Cheat sheet de consultas SQL para beatmakers.
* **[🎛️ 8. Universal Beatmaker Rack](docs/wiki/08-Universal-Hardware-Beatmaker-Rack-(MPC-Maschine-SP404-PO33).md)**: Rack de 16 pads, afinación, choke groups y exportación.
* **[🕹️ 9. Pocket Operator PO-33 Studio](docs/wiki/09-Pocket-Operator-PO-33-KO-Studio-y-FSK-Modem.md)**: Drum Reels calibrados a 150 ms y módem FSK.
* **[🌐 10. Manual Bilingüe (ES / EN)](docs/wiki/10-Manual-Bilingue-y-Selector-de-Idioma-(ES-EN).md)**: Guía de internacionalización y configuración.
* **[🔌 11. Auto-Reconocimiento de Discos](docs/wiki/11-Auto-Reconocimiento-y-Onboarding-de-Discos.md)**: Diagnóstico y autoconfiguración de nuevos volúmenes.

---

## 🚀 Características Principales

1. **Universal Beatmaker Kit Rack (16 Pads)**:
   - Cuadrícula táctil e interactiva disparable por ratón o teclado físico (`Z-V`, `A-F`, `Q-R`, `1-4`).
   - **Pad Inspector Modal**: Volumen lineal, paneo estéreo, afinación (**-24 a +24 semitonos**), **Choke / Mute Groups (1-8)** e intercambio de pads (Pad Swap).
   - Generación en 1 clic de programas nativos para Akai MPC (`.xpm`/`.xpj`), NI Maschine (`.mxgrp`), Roland SP-404MK2, Pocket Operator PO-33 y Teenage Engineering EP-133 K.O. II (`.pak` & `sounds/`).

2. **Pocket Operator PO-33 / PO-133 Studio**:
   - Generador de **Drum Reel** con silencios de exactamente **150 ms** para el algoritmo de Auto-Slice en los pads 9-16.
   - Control matemático estricto del presupuesto de RAM (**≤ 40.0 s**).
   - Verificador y preescucha de respaldos por audio módem **FSK (~73.6 s)**.

3. **Base de Datos SQLite Relacional (`mpc_sample.db`)**:
   - Indexación ultrarrápida de archivos `.wav`, `.aif`, `.mp3` y `.flac`.
   - Taxonomía automática: `KICK`, `SNARE`, `CLAP`, `HIHAT`, `CYMBAL`, `PERCUSSION`, `BASS_808`, `KEYS_SYNTH`, `MELODIC_LOOP`, `DRUM_LOOP`, `VOCAL`, `FX`.
   - Estimación de tonalidad musical, rueda Camelot y nivel de energía (*Chill*, *Groove*, *Banger*).

4. **Servidor de Audio Streaming de Alto Rendimiento (`serve_mpc.py`)**:
   - Soporte completo para **RFC 7233 Range Requests (HTTP 206 Partial Content)** y CORS.
   - Reproducción sin bloqueos en Safari, Chrome, Firefox y WebKit.
   - API REST completa para tareas de reindexación, limpieza y creación de kits.

---

## 🎨 Los 4 Pilares Culturales y Temas Visuales

El diseño de BeatOS (*The MakerLicious*) rinde homenaje a los cuatro grandes movimientos del diseño industrial y la cultura beatmaker:

1. **La Escuela Suiza & Funcionalismo Dieter Rams (Braun / Teenage Engineering)**:
   - *Tema*: `🕹️ Teenage Engineering PO-20 Arcade` (Flagship).
   - *ADN*: Retículas ortogonales milimétricas, serigrafía técnica en blanco hueso y negro mate con acentos naranja arcade (`#ff6600`).
2. **La Estética Stones Throw & Cultura de Vinilo (Jeff Jank / Madlib / J Dilla)**:
   - *Tema*: `🎚️ Roland SP-404MK2 (Vinyl Dark)`.
   - *ADN*: Textura profunda de vinilo negro, resplandor ámbar cálido en diales OLED y modo DJFX.
3. **Simbolismo Arcade & Chiptune (PO-Series / Playdate)**:
   - *Tema*: `⚡ Cerebro OS Neon`.
   - *ADN*: Neón reactivo cian (`#00f0ff`) y magenta (`#ff0055`) con tipografía pixel y contraste cibernético.
4. **Cyber-Industrial Japonés de los 80/90 (Roger Linn Akai MPC / Roland TR / NI)**:
   - *Temas*: `🎛️ Akai MPC Vintage` (1988 Roger Linn stone-gray y carmín) y `🎹 NI Maschine Studio` (carbón anodizado con retroiluminación RGB de pads).

El sistema cuenta con **sincronización global bidireccional** vía `/api/theme` y persistencia en `ecosystem_theme.json`, alineando instantáneamente BeatOS con **Cerebro OS** y **DjProducerTool**.

---

## ⚡ Instalación Rápida

### En macOS o Linux
```bash
# 1. Clona el repositorio
git clone https://github.com/Astro1Deep/mpc-sample-database.git
cd mpc-sample-database

# 2. Concede permisos e inicia el instalador interactivo
chmod +x install.sh
./install.sh
```

El menú interactivo te permite:
1. Indexar cualquier tarjeta SD o carpeta local.
2. Iniciar el servidor local de audio streaming (`http://localhost:8888`).
3. Purgar archivos residuales `._*` y `.DS_Store`.
4. Sincronizar la documentación con GitHub Wiki.

---

## 📦 Estructura del Repositorio

```text
mpc-sample-database/
├── .github/
│   └── FUNDING.yml           # Configuración de patrocinio (Ko-fi & GitHub Sponsors)
├── catalogo_universal.html   # Catálogo interactivo web HTML5 bilingüe (ES/EN)
├── hardware_kit_builder.py   # Motor multi-sampler universal (MPC, SP404, Maschine, PO-33)
├── serve_mpc.py              # Servidor HTTP RFC 7233 con API REST y streaming parcial
├── index_mpc_library.py      # Motor autónomo de indexación en Python 3 puro
├── install.sh                # Instalador interactivo para macOS y Linux
├── installer.py              # Instalador multiplataforma (Windows / Mac / Linux)
├── sync_wiki.sh              # Sincronizador automatizado con GitHub Wiki
├── schema.sql                # Esquema relacional formal SQLite
├── language_config.json      # Configuración de localización bilingüe
├── docs/
│   ├── assets/branding/      # Banners esquemáticos Teenage Engineering en SVG/PNG
│   └── wiki/                 # Los 11 artículos técnicos completos de la Wiki
├── LICENSE                   # Licencia Creative Commons BY-NC-ND 4.0
└── README.md                 # Documentación principal bilingüe
```

---

## 📄 Licencia

Este proyecto está bajo la licencia **Creative Commons Atribución-NoComercial-SinDerivadas 4.0 Internacional (CC BY-NC-ND 4.0)**. Consulta el archivo [LICENSE](LICENSE) para más detalles.
