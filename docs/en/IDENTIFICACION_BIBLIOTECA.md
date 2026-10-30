# Library indexing and identification semantics

[Español](../IDENTIFICACION_BIBLIOTECA.md) · [English manual](MANUAL_COMPLETO.md#4-indexing-and-audio-classification)

BeatOS preserves uncertainty explicitly. A sample without recognized filename/folder evidence is not automatically categorized as percussion, a major key or medium-energy audio. The catalog retains its **12-column structure** for compatibility with the browser filters, rack and exporters.

A musical key requires a declared **note and major/minor mode**. Camelot conversion follows the standard major/minor [Mixed In Key Camelot wheel](https://mixedinkey.com/camelot-wheel/0/). Filenames containing a single multisample note such as `C1` do not establish C major.

The RMS estimator uses short windows read through Python's built-in [wave module](https://docs.python.org/3.11/library/wave.html). Its low, medium and high thresholds are **organizing conventions**, not standardized perceptual loudness, full-file LUFS, musical intensity or reliable transient detection. Unknown/unmeasured values should remain visible until reviewed.

BPM is extracted from known filename patterns, **not acoustically estimated**. Reindexing rebuilds generated metadata but should never alter original sample waveforms.