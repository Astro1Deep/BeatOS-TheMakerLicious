# 🔌 11. Auto-Reconocimiento y Onboarding de Nuevos Discos

El módulo **Auto-Disk Recon & Onboarding Wizard** permite extender la arquitectura de bases de datos relacionales y catálogos web interactivos a cualquier disco o volumen externo conectado en macOS.

---

## 🔍 1. Detección Forense de Hardware

Al conectar un nuevo disco o memoria externa, el motor analiza en tiempo real:
* **Punto de Montaje y Capacidad**: Espacio total, usado, libre y porcentaje de utilización.
* **Sistema de Archivos**:
  - `ExFAT`: Compatibilidad universal con hardware standalone (Akai MPC, Roland SP-404, Windows y macOS).
  - `APFS`: Rendimiento nativo óptimo para macOS Apple Silicon y clonación instantánea de inodos.
* **Salud Forense e Inodos**: Detección de archivos residuo AppleDouble (`._*`) y carpetas `.DS_Store`.

---

## 🧠 2. Clasificación de Vocación en 5 Pilares

El algoritmo inspecciona firmas, nombres de carpetas y extensiones para determinar la vocación óptima del almacenamiento:

1. **🎻 Native Instruments & Reaktor**: Archivos `.nki`, `.nicnt`, `.ens`, `.nkm`.
2. **🎹 Ableton Live & Producción DAW**: Proyectos `.als`, presets `.adv`/`.adg`, tarjetas SP-404.
3. **🎧 Cabina Serato DJ & VJ Loops**: Carpetas `_Serato_`, archivos `.crate`, loops de vídeo `.mp4`/`.mov`.
4. **🎛️ Hardware Multi-Sampler**: Proyectos `.xpj`, `.xpm`, tiras Drum Reel PO-33 y kits Maschine.
5. **📦 Bóveda de Respaldo & Almacén**: Archivos comprimidos `.zip`, imágenes de disco `.dmg`, `.iso`.

---

## ⚡ 3. Generación Automatizada en 1-Click

Desde la terminal o a través del panel web `master_ecosistema_discos.html`, puedes:
* **Copiar el Script Indexador Python**: Genera un script autónomo con SQLite WAL mode adaptado a la unidad.
* **Copiar el Prompt IA**: Genera un informe forense estructurado listo para transferir a ChatGPT, Claude o Cerebro OS.
* **Ejecutar Limpieza**: Purga archivos AppleDouble mediante `dot_clean -m`.
