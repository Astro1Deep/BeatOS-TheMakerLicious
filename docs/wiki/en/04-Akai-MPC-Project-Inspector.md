# Inspecting Akai MPC XPJ projects and Drum banks

**BeatOS 3.8.0 · English** · [Español / Versión española](../04-Auditoria-de-Proyectos-MPC-(xpj).md) · [Complete English manual](../../en/MANUAL_COMPLETO.md#8-akai-mpc-projects) · [Hardware compatibility](../../en/COMPATIBILIDAD_HARDWARE.md)

The Projects view lists indexed XPJ files, sample-reference status and available Drum material. Choose **Edit copy in rack** to open a supported Drum track and one bank of 16 pads (A–H where available). The importer preserves missing references rather than silently guessing among same-name files; it uses the **first active layer** per pad. Changes stay in the browser rack, not in your original XPJ. Export each edited bank under a different name before switching tracks/projects or reloading the page. An INDEX_OK status reports that the indexer did not detect missing references in its limited check: it is **not** proof of native playback. BeatOS cannot reproduce an entire song, MPC effects/plugins, automation, all layers or arrangement. The generated XPJ uses the **MPC Sample / AC50** template rather than a guaranteed universal One/Live project profile.

---

[English documentation index](../Home_EN.md) · [Installation](../../../GUIA_INSTALACION_EN.md) · [Technical API / SQLite reference](../../en/REFERENCIA_TECNICA.md)
