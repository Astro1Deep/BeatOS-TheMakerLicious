# BeatOS — Installation and first run (English)

**BeatOS 3.8.0 · The MakerLicious** · [Español](GUIA_INSTALACION.md) · [Complete user manual](docs/en/MANUAL_COMPLETO.md) · [Hardware compatibility](docs/en/COMPATIBILIDAD_HARDWARE.md).

BeatOS is a **computer-hosted sample library browser and 16-pad beatmaking workstation**. It exports device-specific audio and kit files; it does not flash or replace hardware firmware. You can start with loose WAV samples without owning an Akai MPC.

## Before you start

- **Python 3.11 or later** (Python 3 executable must be available in the terminal).
- A sample-library folder that you are allowed to read/write.
- A modern desktop browser for the local HTTP catalog.
- **FFmpeg** in your terminal's PATH if you need to convert compressed formats, sample rates, bit depths or tune the PO reel. Some pre-compatible PCM WAV exports work without it.
- Your own legally acquired samples. The distributed clean installer contains no personal audio library.
- Node.js is **not** required for normal use; it is only used by development tests.

**Installer language:** `python3 BeatOS/installer.py --lang en` for release ZIPs, or `python3 installer.py --lang en` when cloned. You can also use `BEATOS_LANG=en python3 BeatOS/installer.py` in a compatible shell. The web UI has its own ES/EN selector and stores that choice in the browser; the terminal and browser selections are independent.

## Get the correct archive

Go to the [latest BeatOS release](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases/latest) and download the **BeatOS-3.8.0.zip** asset and its SHA-256 checksum file. The asset has an organized installer layout. GitHub's generic **Source code** ZIP contains the development layout with a different script path. Do not replace an existing audio library with a downloaded archive.

### A. Official release ZIP

1. Extract `BeatOS-3.8.0.zip` into a **new folder**.
2. Open a terminal in the folder containing the `BeatOS/` subfolder.
3. Run:
   ```bash
   python3 BeatOS/installer.py --lang en
   ```
4. Select **1: Index** and provide the folder containing **your** samples. Wait for the index to finish.
5. Select **2: Start local server** with the **same** library path. Open the URL that the program prints, usually `http://127.0.0.1:8888/`.
6. In the web page, confirm the **active library** before assigning or exporting samples.

On Windows, use `py BeatOS/installer.py --lang en` if `py` is your installed launcher. On macOS/Linux you may also run `./BeatOS/install.sh` (the shell launcher may use its own language defaults). The macOS `ABRIR_BEATOS.command` launcher is optional; if blocked by OS security, use the explicit Python commands rather than disabling protection.

### B. Clone or GitHub source ZIP

In this layout the scripts are **at the repository root**:

```bash
git clone https://github.com/Astro1Deep/BeatOS-TheMakerLicious.git
cd BeatOS-TheMakerLicious
python3 installer.py --lang en
```

You can also set the library path directly:

```bash
python3 index_mpc_library.py --path "/path/to/My Samples"
python3 serve_mpc.py "/path/to/My Samples" --port 8888
```

For the release layout, prefix the last two Python file paths with `BeatOS/`.

## First session: from samples to a kit

1. In the local HTTP catalog, search and preview sample files.
2. Assign sounds to the 16-pad rack. Some keyboard keys map to pads, including Z/X/C/V.
3. Edit pitch, gain, pan and mute groups where appropriate.
4. Select **Export kit**, choose **one hardware target**, and use a distinct kit name.
5. Find the generated delivery under `Custom_Kits/<kit-name>/` inside the active library.
6. Import the files using the manufacturer's procedure; listen, confirm pad positions and **save on the device**. A generated export does not prove the physical device has accepted it.

The **Universal** target can generate six device-specific folders in one operation; each target has independent limits. In particular, SP-404A/SX exports only pads **1–12**, the PO exports an **audio reel** rather than a project, and Maschine/EP-133 need manual mapping.

## Installer options and safety

| Option | Behavior |
| --- | --- |
| 1 · Index | Build SQLite, CSV/JSON and a browser catalog for a chosen library; source audio is not moved or modified. |
| 2 · Web server | Start BeatOS for the selected library, normally on localhost. |
| 3 · Clean | **Destructive** removal of auxiliary `._*` and `.DS_Store` files. Not required for installation. |
| 4 · SQLite | Initialize schema at the default installation location; does not index media. |
| 5 · Docs | Open versioned documentation. |
| 6 · Exit | Leave the installer. |

The server is local and checks allowed paths and origins, but it is **not** an authenticated internet-facing service. Do not expose it via a public reverse proxy, tunnel or port forwarding. Your generated SQLite catalog may contain personal file names or paths.

## Audio and compatibility caveats

FFmpeg is required when a source format or sample rate cannot be used directly. The **SP-404MKII** delivery is PCM WAV **16-bit / 48 kHz**; **SP-404A/SX** is **16-bit / 44.1 kHz**. The **PO-33/PO-133** delivery is a mono reel with slices; **EP-133** is WAV plus a map and ZIP, not a native project backup.

Back up your device before importing anything that might overwrite occupied pads or memory. In particular, restoring a PO audio-data backup replaces the current PO sounds and patterns. **Never use the only copy of a backup as a restoration experiment.**

## Troubleshooting

- **Browser opens but actions fail:** you may be using `file://`; use the URL printed by the active server.
- **Wrong audio appears:** check the active library path and the source folder used during indexing.
- **Port 8888 taken:** use the actual port printed by the server.
- **Missing sounds:** remove filters, check extensions, reindex, then refresh the full page.
- **Export fails while audio preview works:** browser decoding and FFmpeg are separate; verify `ffmpeg -version`, path, storage space and input codec.
- **Kit already exists:** use a new name; BeatOS does not silently overwrite outputs.
- **A hardware device rejects files:** compare its model and firmware against the [hardware loading guide](docs/en/COMPATIBILIDAD_HARDWARE.md).

[Complete English manual](docs/en/MANUAL_COMPLETO.md) · [Technical reference](docs/en/REFERENCIA_TECNICA.md) · [Spanish installation guide](GUIA_INSTALACION.md).
