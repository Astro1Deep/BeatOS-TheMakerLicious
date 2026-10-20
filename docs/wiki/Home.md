# 🎛️ BeatOS — The MakerLicious
### The system ★ [universal beatmaker station]
> `│ ref: mpc · sp-404 · pocket operator · maschine │`  
> **Universal Beatmaker Hub & Multi-Sampler Toolkit**

> **Idioma / Language**: [Español (ES)](#-español) | [English (EN)](#-english)

---

## 🇪🇸 Español

**BeatOS — The MakerLicious** (*The system ★ [universal beatmaker station]*) es un ecosistema abierto de alto rendimiento diseñado para maximizar la velocidad de navegación, la estabilidad y la creación de kits musicales en hardware **Akai MPC Standalone**, **Roland SP-404MK2 / SP-404A**, **Native Instruments Maschine** y **Teenage Engineering Pocket Operator (PO-33 / PO-20 / PO-133)**.

### 📌 ¿Por qué este proyecto?
El hardware musical autónomo cuenta con recursos de memoria dedicados. Cuando conectamos tarjetas Micro SD con decenas de miles de samples desordenados o con residuos `._*` de macOS, surgen problemas críticos:
1. **Lentitud extrema en el Browser del hardware**.
2. **Pérdida de muestras en proyectos (`Missing Samples`)**.
3. **Dificultad para ensamblar drum kits compatibles con múltiples samplers**.

Este toolkit resuelve estos desafíos combinando **SQLite 3**, un indexador autónomo en **Python 3**, un **servidor de streaming RFC 7233 Range Requests** y un **Catálogo Web Bilingüe en HTML5** con Beatmaker Kit Rack interactivo de 16 pads.

---

## 🗺️ Índice de la Wiki / Wiki Chapters

| Módulo / Chapter | Descripción / Description |
| :--- | :--- |
| **[🚀 1. Instalación y Puesta en Marcha](01-Instalacion-y-Puesta-en-Marcha.md)** | Requisitos mínimos, instalador interactivo multiplataforma en macOS, Linux y Windows. |
| **[📁 2. Organización MicroSD para MPC](02-Organizacion-MicroSD-para-MPC.md)** | Las 7 macro-categorías canónicas, formato ExFAT y purga de archivos `._*`. |
| **[🎹 3. Taxonomía y Detección de Audio](03-Taxonomia-y-Deteccion-de-Audio.md)** | 12 tipos de sonido, rangos BPM (Lo-Fi a DnB), rueda armónica Camelot y energía. |
| **[🔍 4. Auditoría de Proyectos (.xpj)](04-Auditoria-de-Proyectos-MPC-(xpj).md)** | Inspección interna JSON, verificación contra `_[ProjectData]` y estados HEALTHY. |
| **[📦 5. Expansiones Oficiales Akai](05-Expansiones-Oficiales-Akai.md)** | Parseo de `Expansion.xml`, programas `.xpm` / `.pgm` y carátulas gráficas. |
| **[🌐 6. Catálogo Web y Audio Player](06-Catalogo-Web-y-Audio-Player.md)** | Catálogo interactivo HTML5, streaming local y botón de copiado de rutas. |
| **[📊 7. Consultas Avanzadas SQLite](07-Consultas-Avanzadas-SQLite.md)** | Consultas SQL prácticas para beatmakers y exportaciones a CSV/JSON. |
| **[🎛️ 8. Universal Beatmaker Rack](08-Universal-Hardware-Beatmaker-Rack-(MPC-Maschine-SP404-PO33).md)** | Rack de 16 pads, afinación, choke groups, pad swap y exportación multi-sampler. |
| **[🕹️ 9. Pocket Operator PO-33 Studio](09-Pocket-Operator-PO-33-KO-Studio-y-FSK-Modem.md)** | Drum Reels con silencios de 150 ms (≤ 40s) y verificación de copias FSK. |
| **[🌐 10. Manual Bilingüe (ES / EN)](10-Manual-Bilingue-y-Selector-de-Idioma-(ES-EN).md)** | Selector dinámico de idioma, persistencia en localStorage y workflow internacional. |
| **[🔌 11. Auto-Reconocimiento de Discos](11-Auto-Reconocimiento-y-Onboarding-de-Discos.md)** | Motor forense para diagnosticar y estructurar cualquier disco externo nuevo. |

---

## 🇬🇧 English

### Overview
**BeatOS (The System)** — *Edition: The MakerLicious* is a lightweight, zero-dependency open source ecosystem (**Universal Beatmaker Hub & Multi-Sampler Toolkit**) built with **Python 3, SQLite 3, and HTML5**. It provides instant local sample search, automatic sonic taxonomy, project integrity auditing, and a 16-pad **Universal Beatmaker Kit Rack** that exports programs and kits natively to:
* **Akai MPC Standalone** (`.xpm` Drum Programs & `.xpj` Projects)
* **Native Instruments Maschine** (`.mxgrp` Groups & mapping)
* **Roland SP-404MK2 & SP-404A / SX** (Bank A import folders)
* **Teenage Engineering PO-33 / PO-20 / PO-133** (Calibrated 150ms Drum Reels & FSK modem backup tools)

---

## 💡 Contribuir o Enviar Sugerencias
Mantenido por **[Astro1Deep](https://github.com/Astro1Deep)**. Si tienes ideas sobre nuevas reglas de clasificación sonora, abre un [Issue o Pull Request en GitHub](https://github.com/Astro1Deep/mpc-sample-database/issues).
