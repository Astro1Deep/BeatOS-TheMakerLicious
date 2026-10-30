# BeatOS library layout and data isolation

[Español](../ESTRUCTURA_BIBLIOTECA.md) · [Installation](../../GUIA_INSTALACION_EN.md) · [Technical reference](REFERENCIA_TECNICA.md)

For the **organized release ZIP**, the distribution contains a `BeatOS/` software directory inside the extracted package. A sample library selected by the user can share that folder or be stored separately.

```text
MyLibrary/
├── catalogo_universal.html       lightweight catalog entry
├── catalogo_mpc_sample.html      legacy-compatible entry
├── BeatOS/
│   ├── data/                    generated SQLite, CSV, JSON, catalog, po33_backups/
│   └── config/                  local presentation preferences
├── Samples/                      illustrative user folder
├── Expansions/                   optional user expansion folder
├── Projects/                     optional user XPJ folder
└── Custom_Kits/                  newly generated exported kits
```

A release installed directly alongside the library additionally carries `BeatOS/installer.py`, `serve_mpc.py`, `index_mpc_library.py`, `hardware_kit_builder.py`, `templates/` and documentation. With a **source clone**, the Python scripts are in the repository root, not automatically copied into every library.

Reindexing preserves existing musical folders, writes the current index in `BeatOS/data/`, and does not recreate older SQLite/INDEX directory layouts. SQLite `.db-wal` and `.db-shm` files may legitimately exist while the database is active; use a consistent backup process. Exported kits are written to `Custom_Kits/`, not to an automatic hardware memory dump.

The local HTTP server blocks generic reads of private installation data, scripts, configuration and SQLite; it serves explicitly permitted catalog/media assets and exposes a **specific authenticated-by-origin/host but not user-authenticated** PO WAV API. Do not expose it to public networks. Legacy catalog URLs may redirect to the current catalog without recreating old directories.