# Music libraries, folders and MicroSD cards

**BeatOS 3.8.0 · English** · [Español / Versión española](../02-Organizacion-MicroSD-para-MPC.md) · [Complete English manual](../../en/MANUAL_COMPLETO.md#3-libraries-and-files) · [Hardware compatibility](../../en/COMPATIBILIDAD_HARDWARE.md)

BeatOS separates its installed code, the audio library, the generated search index and exported kits. Your library can reside on an external disk, SD card or ordinary folder—**it does not need to be named MPCSMPL**. Indexing keeps original audio paths and does not reorganize samples. In a typical organized library, `BeatOS/data/` holds SQLite/CSV/JSON and the single HTML catalog; `BeatOS/config/` holds local display preferences; `Custom_Kits/` holds new deliveries. The two catalog HTML entrypoints do not mean there are two separate databases. Back up source audio and projects before moving disks. After moving a library, reindex at its new root because database paths may be absolute. Avoid publishing your personal index, which can include personal file paths.

---

[English documentation index](../Home_EN.md) · [Installation](../../../GUIA_INSTALACION_EN.md) · [Technical API / SQLite reference](../../en/REFERENCIA_TECNICA.md)
