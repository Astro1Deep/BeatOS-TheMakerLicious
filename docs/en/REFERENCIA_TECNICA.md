# BeatOS 3.8.0 — Technical reference and local API (English)

[Español](../REFERENCIA_TECNICA.md) · [English manual](MANUAL_COMPLETO.md) · [Hardware compatibility](COMPATIBILIDAD_HARDWARE.md)

**Scope:** implementation-specific reference, **not** a formally versioned public API with a stability promise. Keep the server local; no remote authentication is provided.

## 1. Main modules

| Source file | Purpose |
| --- | --- |
| `installer.py` | Menu for local indexing, server, explicit auxiliary-file cleanup, SQLite setup and documentation. Supports `--lang en` or `BEATOS_LANG=en`. |
| `index_mpc_library.py` | Library scan, rule-based labels, measured RMS windows, SQLite/CSV/JSON and rendered HTML. |
| `serve_mpc.py` | Local HTTP server, ranged audio, file validation, reindexing tasks and API. |
| `hardware_kit_builder.py` | MPC Drum import/parsers, audio conversion and target-specific exports. |
| `beatos_paths.py` | Installation/library paths and catalog entrypoints. |
| `templates/catalogo.html` | Web interface, player, rack, projects, expansions, ES/EN selector and PO/EP hubs. |
| `docs/assets/po33-capture-worklet.js` | Stereo PCM audio capture for PO backup recordings. |
| `schema.sql` | SQLite schema. |
| `build_release.py` | Clean ZIP packaging, template sanitization, SHA-256 manifest. |

Legacy disk-supervisor and Cerebro integration scripts are **not** required for core BeatOS operation.

## 2. Commands and installation layouts

The commands below assume the **source clone's root**. For the organized release ZIP, prefix the scripts with `BeatOS/`.

```bash
python3 installer.py --lang en
python3 index_mpc_library.py --path "/path/to/sample library"
python3 serve_mpc.py "/path/to/sample library" --port 8888 --no-browser
python3 -B -m unittest discover -s tests -v
python3 build_release.py "/path/to/BeatOS.zip"
```

Use `py` on Windows if appropriate. The indexer supports `--path/-p` and `--output/-o`; its custom output path changes SQLite/CSV/JSON output but **not** the standard catalog HTML location. The server supports an optional library path, `--port/-p` and `--no-browser`, and can select an available port from the next 50 ports. For reproducibility **always specify your library root explicitly**.

`hardware_kit_builder.py create` requires `--name`, `--b64` (base64 JSON array of pad records) and `--root`, with optional `--target`; supported targets are `universal`, `mpc`, `maschine`, `sp404mk2`, `sp404a`, `po33`, `ep133`. The standalone CLI does not expose all of the web API's PO timing or project tempo options.

## 3. Generated library files

| Location relative to selected library | Contents |
| --- | --- |
| `BeatOS/data/mpc_sample.db` | SQLite index, including absolute and relative file paths. |
| `BeatOS/data/mpc_sample_resumen.csv` | Exported sample table. |
| `BeatOS/data/mpc_sample.json` | Totals, generation metadata and project/expansion summary. |
| `BeatOS/data/catalogo.html` | Single generated web catalog. |
| `catalogo_universal.html`, `catalogo_mpc_sample.html` | Lightweight entrypoints to the single catalog. |
| `BeatOS/config/theme_config.json` | Saved local theme preferences; **not** the full rack state. |
| `Custom_Kits/<name>/` | Exported kits by destination. |
| `BeatOS/data/po33_backups/` | Archived **original** PO WAV recordings and metadata. |

SQLite uses WAL. Copying a live database file alone may omit pending WAL changes; use a SQLite backup or stop writers first. Index IDs are reconstructed on reindex. Do not store personal annotations in regenerated tables.

### Database tables

- **`sound_categories`**: codes, names and icons.
- **`samples`**: filename, musical format, sound type, macro/subpack folder labels, BPM and tier, key/Camelot, RMS-based energy tier, extension, size, absolute/relative path.
- **`projects`**: XPJ filename/path, tempo, sample reference count, missing count, summary status and size.
- **`expansions`**: metadata read from available manifests plus counts and source paths.
- **`packs`**: defined by the schema but currently **not populated as a separate pack catalog**.

Read-only terminal query:

```bash
sqlite3 -readonly "BeatOS/data/mpc_sample.db" "SELECT sound_type, COUNT(*) FROM samples GROUP BY sound_type;"
```

Example SQL:

```sql
SELECT filename, rel_path FROM samples
WHERE sound_type='DRUM_LOOP' AND bpm BETWEEN 88 AND 94
ORDER BY bpm, filename;
SELECT name, status, missing_samples_count FROM projects
WHERE status IN ('ATTENTION','ERROR');
```

## 4. Rack and API validation

Rack payloads contain **occupied pads**, numbered 1–16, with paths resolved inside the selected library. The API validates finite **volume 0–1**, **pan 0–1** (center 0.5), **tune −36…+36 semitones**, **mute group 0–32**, and **tempo 30–300 BPM** (default 120). The browser pitch editor is narrower (±24 semitones). Web **100%** volume corresponds to approximately **0.707946** linear gain, not a measured dBFS level; the UI slider is capped at 141% so its maximum remains within API validation.

PO options are `max_total_sec` (1–40 seconds) and `gap_ms` (0–500 milliseconds), defaults 40 seconds and 150 ms. The presence of an occupied pad does not certify that the source file can be decoded by an export target.

An export processes parameters differently:

- **MPC XPM/XPJ:** supported fields are written into generated program/project structures.
- **Maschine and EP-133:** volume/pan/tune/mute are listed in JSON maps; WAV levels remain unprocessed.
- **SP-404MKII / A/SX:** exported WAV and optional manifest, *not* rack parameters in a device project.
- **PO-33 / PO-133:** tone and volume are processed into normalized mono reel audio; pan/mutes are not transported.

## 5. MPC file inspection

XPM is parsed as XML. Compatible XPJ data use gzip and JSON structures. The parser is not a universal reader for all MPC formats/versions. Imports may expose up to 128 pads and multiple Drum tracks, but the web rack loads a **single 16-pad bank** and only the **first active layer per pad**. Relative and project-data sample resolution must stay within the selected library. Two ambiguous candidates are treated as unresolved instead of silently picking an arbitrary sample.

## 6. Local HTTP API

The server listens on the printed loopback address. It validates allowed hosts/origins and filesystem paths, but **does not have authentication for public network exposure**.

### Read-only

| Endpoint | Result |
| --- | --- |
| `GET /api/status` | Root, sample count, free space, indexing task status and historical MPCSMPL indicator. |
| `GET /api/task_status` | Current task name, running/success state, bounded log messages and timestamps. |
| `GET /api/theme` | Saved theme or default. |
| `GET /api/po33_backups` | Inspected local backup files; **does not verify modem data**. |
| `GET /api/po33_backup_audio?file=…` | Exact permitted original WAV; no conversion or restoration. |
| `GET /api/download_file?path=…` | An allowed file under the library; for example a kit ZIP. |
| `GET/HEAD` of permitted resources | HTML and ranged audio, subject to path checks. |

### Mutations and operations

| Endpoint | Purpose |
| --- | --- |
| `POST /api/create_kit` | Create a new kit: `name`, `target`, `pads`; optional `tempo` and `po_options`. |
| `POST /api/load_project` | Read supported XPJ into a rack copy; does **not** mutate source. |
| `POST /api/load_xpm_program` | Load program data for rack inspection. |
| `POST /api/list_expansion_programs` | Find compatible XPM programs under the selected expansion. |
| `POST /api/download_xpa` | Package a project and ProjectData as a ZIP named XPA; **not** a format conversion. |
| `POST /api/reindex` | Start controlled background index rebuild for the active root. |
| `POST /api/clean_metadata` | Explicitly delete auxiliary AppleDouble/`.DS_Store`; may run `dot_clean` on macOS. |
| `POST /api/reveal_in_finder` | Open an allowed file location with the platform's file manager. |
| `POST /api/launch_ep_tool` | Open the manufacturer's web tool; not a device transfer. |
| `POST /api/sync_dashboard` | Optional external Cerebro integration; unavailable on normal clean install. |
| `POST /api/theme` | Store theme preferences. |
| `POST /api/po33_backups?name=…` | Archive a raw WAV with `Content-Type: audio/wav`, up to 128 MiB. |

Most JSON requests cap at **1 MiB**; PO WAV import is **128 MiB**. Check both HTTP status and the response's `success`/`error` fields. Read `/api/task_status` to determine reindex completion.

Illustrative `create_kit` body (only succeeds if the file is actually in the library):

```json
{
  "name": "Kit_Example_01",
  "target": "ep133",
  "tempo": 90,
  "pads": [{"pad":1,"rel_path":"Samples/Kick.wav","volume":0.707946,"pan":0.5,"tune":0,"mute_group":1}]
}
```

For PO: `"target":"po33"` and `"po_options":{"max_total_sec":20,"gap_ms":150}`.

## 7. Concurrency and security

The server's web reindex lock is **process-local**. It does not coordinate independent terminals or separate servers indexing the same output: avoid doing so. Exports reserve a **new** output directory and attempt to remove partial files on failure. HTTP protection does not isolate BeatOS from other processes on your local computer.

PO backup archive checks WAV shape, preserves raw bytes and calculates SHA-256. Inspecting a WAV file and a hash **does not validate the modem's payload**. Only complete, stereo 16-bit 44.1/48 kHz compatible captures can be prepared by integrated restore playback, and restoration must be verified on hardware.

## 8. Build and regression checks

```bash
python3 -B -m unittest discover -s tests -v
node tests/test_library_ui.cjs
node tests/test_pad_audio.cjs
node tests/test_creator_identity.cjs
node tests/test_po33_backups.cjs
python3 build_release.py "/tmp/BeatOS.zip"
```

Review the GitHub Actions run associated with the actual source commit. CI tests a Linux build and Windows clean installation, but **not all device/firmware combinations**. The release generator sanitizes sample templates, removes private library content and writes a SHA-256 member manifest.

## 9. Known limits and terminology

- Sample/AC50-based XPJ output rather than per-model MPC profiles.
- No native Maschine `.mxgrp`, SP project or EP project generated.
- No PO FSK payload decoder, and no automatic proof of restored state.
- A 16-pad rack is **not** persisted as a full project/session.
- Web volume controls are now capped within the exporter's gain validation; third-party API clients must still validate numeric ranges.
- Some browser/CLI messages may remain Spanish as locale coverage is expanded.
- BPM is parsed from filenames and estimated RMS energy comes from short WAV windows; it is not whole-file acoustic analysis.

**BeatOS 3.8.0 and Akai MPC 3.8 are different product version numbers.** Consult the [hardware guide](COMPATIBILIDAD_HARDWARE.md) and [operator manual](MANUAL_COMPLETO.md) before relying on a transfer.
