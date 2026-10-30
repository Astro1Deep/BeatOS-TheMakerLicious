# Sample classification, BPM, musical key and RMS energy

**BeatOS 3.8.0 · English** · [Español / Versión española](../03-Taxonomia-y-Deteccion-de-Audio.md) · [Complete English manual](../../en/MANUAL_COMPLETO.md#4-indexing-and-audio-classification) · [Hardware compatibility](../../en/COMPATIBILIDAD_HARDWARE.md)

BeatOS identifies kicks, snares, hi-hats, claps, percussion, 808 basses, melodic loops, drum loops, vocals, stems, effects and other categories primarily through **file and folder names**, not acoustic machine learning. ONE_SHOT/LOOP/STEM labels describe musical role, not file codec. BPM is inferred from recognizable filename tokens between **55 and 190**, and **not** automatically measured from the recording. Musical keys require explicit mode (`Dm`, `F#min`, `Cmajor`); a multisample note such as `C1` does not imply major/minor. Camelot derives only from explicit keys with mode. Energy classification is a limited RMS calculation across up to three short WAV PCM windows (CHILL <−24 dBFS, GROOVE −24 to <−12, BANGER ≥−12); it is **not LUFS or perceived loudness**, and can miss events between those windows. Recheck unknown labels by listening.

---

[English documentation index](../Home_EN.md) · [Installation](../../../GUIA_INSTALACION_EN.md) · [Technical API / SQLite reference](../../en/REFERENCIA_TECNICA.md)
