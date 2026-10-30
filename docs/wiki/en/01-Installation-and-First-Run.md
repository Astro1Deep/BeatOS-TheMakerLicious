# Installing BeatOS and opening the local catalog

**BeatOS 3.8.0 · English** · [Español / Versión española](../01-Instalacion-y-Puesta-en-Marcha.md) · [Complete English manual](../../en/MANUAL_COMPLETO.md#2-requirements-and-installation) · [Hardware compatibility](../../en/COMPATIBILIDAD_HARDWARE.md)

Install **Python 3.11+** and use your own writable sample-library directory. Download the [official BeatOS release](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases/latest) and its checksum, then extract it into a fresh folder. The organized ZIP uses `python3 BeatOS/installer.py --lang en`; a cloned source checkout uses `python3 installer.py --lang en`. Windows may use `py`. Choose installer option **1** and provide the location of your samples; afterwards choose **2** to start the local server against the same library. Open the localhost URL printed by the server. A `file://` copy can display a catalog but cannot run server-side export, backup or reindex actions. Verify the active library shown on screen. **FFmpeg is needed** for format conversions and some audio processing. Do not invoke cleanup option 3 unless you expressly want to remove AppleDouble and `.DS_Store` auxiliary files.

---

[English documentation index](../Home_EN.md) · [Installation](../../../GUIA_INSTALACION_EN.md) · [Technical API / SQLite reference](../../en/REFERENCIA_TECNICA.md)
