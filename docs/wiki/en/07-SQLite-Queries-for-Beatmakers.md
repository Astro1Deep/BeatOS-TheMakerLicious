# Read-only SQLite analysis for a music sample collection

**BeatOS 3.8.0 · English** · [Español / Versión española](../07-Consultas-Avanzadas-SQLite.md) · [Complete English manual](../../en/MANUAL_COMPLETO.md#3-generated-library-files) · [Hardware compatibility](../../en/COMPATIBILIDAD_HARDWARE.md)

BeatOS stores index metadata in `BeatOS/data/mpc_sample.db`. Tables include `samples`, `projects`, `expansions`, `sound_categories` and `packs`; the last exists in the schema but is not a populated standalone pack catalog. Never treat reconstructed row IDs as permanent. Use read-only mode when inspecting a production index: `sqlite3 -readonly "BeatOS/data/mpc_sample.db" "SELECT sound_type,COUNT(*) FROM samples GROUP BY sound_type;"`. Example for boom-bap breaks: `SELECT filename,bpm,rel_path FROM samples WHERE sound_type='DRUM_LOOP' AND bpm BETWEEN 88 AND 94 ORDER BY bpm;`. Example for missing MPC references: `SELECT name,missing_samples_count FROM projects WHERE status='ATTENTION';`. The database may contain private absolute paths and should not be uploaded publicly. SQLite WAL files require a consistent backup mechanism if the index is open for writing.

---

[English documentation index](../Home_EN.md) · [Installation](../../../GUIA_INSTALACION_EN.md) · [Technical API / SQLite reference](../../en/REFERENCIA_TECNICA.md)
