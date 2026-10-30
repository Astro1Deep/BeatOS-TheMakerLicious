# Browser catalog, prelisten and pad playback

**BeatOS 3.8.0 · English** · [Español / Versión española](../06-Catalogo-Web-y-Audio-Player.md) · [Complete English manual](../../en/MANUAL_COMPLETO.md#6-audio-preview) · [Hardware compatibility](../../en/COMPATIBILIDAD_HARDWARE.md)

Indexing builds a single `BeatOS/data/catalogo.html`, while root HTML files provide lightweight entrypoints. To play from the sample browser, use the local HTTP server and a browser that supports your particular audio encoding. Filtering, sorting and pages show **up to 60 samples** each; project and expansion cards use smaller pages. Playback of a raw sample is different from playing a rack pad with its own gain, rate-based pitch, available Web Audio panning and mute-group behavior. Pitch adjusts speed, **not time-stretching**. A file that previews in the browser may still require FFmpeg for export. Refresh a catalog after reindexing and perform a full page reload after replacing the application code; an ordinary in-page project-card refresh does not reload its JavaScript.

---

[English documentation index](../Home_EN.md) · [Installation](../../../GUIA_INSTALACION_EN.md) · [Technical API / SQLite reference](../../en/REFERENCIA_TECNICA.md)
