# BeatOS 3.8.0 — Complete user manual (English)

**The MakerLicious · Universal beatmaker station**  
Version documented: **3.8.0** · Documentation review: **30 October 2026**.

**Language:** [Español — manual original](../MANUAL_COMPLETO.md) · **English — this manual**  
[Installation](../../GUIA_INSTALACION_EN.md) · [Hardware compatibility](COMPATIBILIDAD_HARDWARE.md) · [Technical reference and HTTP API](REFERENCIA_TECNICA.md) · [BeatOS repository](../../README.md)

> **Scope:** This is an English operator's manual for the current BeatOS workflow. It does not certify compatibility with every firmware or reproduce a hardware manufacturer's manual. The Spanish source is the most detailed reference for unusual cases; check both if operating outside the workflows below. Some UI labels and terminal prompts still appear in Spanish.

## Contents

1. [What BeatOS does](#1-what-beatos-does)
2. [Requirements and installation](#2-requirements-and-installation)
3. [Libraries and files](#3-libraries-and-files)
4. [Indexing and audio classification](#4-indexing-and-audio-classification)
5. [Sample browser](#5-sample-browser)
6. [Audio preview](#6-audio-preview)
7. [16-pad kit rack](#7-16-pad-kit-rack)
8. [Akai MPC projects](#8-akai-mpc-projects)
9. [MPC expansions](#9-mpc-expansions)
10. [Kit export workflow](#10-kit-export-workflow)
11. [PO-33 and PO-133 sample reel](#11-po-33-and-po-133-sample-reel)
12. [Pocket Operator backup WAVs](#12-pocket-operator-backup-wavs)
13. [EP-133 K.O. II workflow](#13-ep-133-ko-ii-workflow)
14. [Library statistics](#14-library-statistics)
15. [Maintenance and integrations](#15-maintenance-and-integrations)
16. [Language, themes and support](#16-language-themes-and-support)
17. [Backing up and moving your work](#17-backing-up-and-moving-your-work)
18. [Producer walkthroughs](#18-producer-walkthroughs)
19. [Troubleshooting](#19-troubleshooting)
20. [Validation scope and known limits](#20-validation-scope-and-known-limits)

## 1. What BeatOS does

BeatOS is computer-hosted software for **music producers, beatmakers, sample-based musicians and owners of hardware samplers**. A normal workflow is **select a sample library → index it → search and preview sounds → fill a 16-pad rack → export files for a particular device → import, audition and save on that device**.

You can build a drum kit from loose WAV files: an Akai MPC project is *not* required. The indexer maintains a searchable SQLite/CSV/JSON catalog. The local web app handles browsing, auditioning, pad editing, MPC Drum project inspection and destination-specific exports. The Teenage Engineering hubs provide additional PO sample-reel, PO backup and EP-133 workflows.

BeatOS is **not** a DAW, standalone sampler firmware, a complete MPC engine, a sequencer, or an automatic project converter between every device. It does not reproduce the original MPC song, effects, plugins, automation or all pad layers.

## 2. Requirements and installation

**Required:** Python 3.11+, a readable/writable library directory, a suitable modern browser, and free space for the index and generated kits. **FFmpeg** is required when source audio needs format, sample-rate or bit-depth conversion, and for particular tuning operations. Node.js is for development tests, not ordinary kit preparation.

There are two differently structured distributions:

| Distribution | Command from the extracted/cloned root |
| --- | --- |
| Downloaded release **BeatOS-3.8.0.zip** | `python3 BeatOS/installer.py` |
| Git clone / GitHub “Source code” | `python3 installer.py` |

On Windows, use `py` instead of `python3` if that is how Python is installed. From the release ZIP, the other scripts are inside `BeatOS/`; from a clone, they are at the repository root.

To use a separate library from a source clone:

```bash
python3 index_mpc_library.py --path "/path/to/My Samples"
python3 serve_mpc.py "/path/to/My Samples" --port 8888
```

The installer menu has these actions: **1** index a chosen library, **2** start a server for that library, **3** explicitly remove AppleDouble/`.DS_Store` auxiliary files (destructive), **4** initialize the schema at the default installation location (not a library scan), **5** open the wiki, and **6** exit. Run a menu action again as needed; do not treat “clean” as part of normal installation.

Open the **local HTTP URL printed by the server**, usually at `127.0.0.1:8888`. If that port is busy, a different port may be selected. Check the **active library path** in the UI, not the port number. Keep the server terminal open; `Ctrl+C` stops it. A `file://` HTML view can display a catalog but does **not** enable server-backed imports, reindexing, backups and exports.

[Detailed installation in English](../../GUIA_INSTALACION_EN.md).

## 3. Libraries and files

Keep these concepts separate: **installation** (scripts/resources), **library** (your own audio and projects), **generated index**, and **exported kits**. A library can live on a Mac/Windows disk, an SD card, or a folder independent of the software.

```text
MyLibrary/
  catalogo_universal.html
  catalogo_mpc_sample.html
  BeatOS/
    data/
      catalogo.html
      mpc_sample.db
      mpc_sample_resumen.csv
      mpc_sample.json
    config/
  Samples/
  Expansions/
  Projects/
  Custom_Kits/
```

The HTML files in the root are lightweight access points to a single generated catalog; they are not two independent databases. The installation ZIP also contains scripts under `BeatOS/`. Reindexing **does not** relocate, rename or normalize your original samples. `Custom_Kits` contains generated copies and may itself be included in a later indexing pass. Your personal library and index may contain private file names and absolute paths: do not publish them in a release.

## 4. Indexing and audio classification

The indexer visits `.wav`, `.aif`, `.aiff`, `.mp3` and `.flac` audio; looks for `.xpj` projects; and catalogs supported expansion metadata. It skips certain hidden, backup, installation and project-data paths in the *general browser*. The project importer can still resolve media from a related `_[ProjectData]` directory.

Sound-type labels include KICK, SNARE, CLAP, HIHAT, CYMBAL, PERCUSSION, BASS_808, KEYS_SYNTH, MELODIC_LOOP, DRUM_LOOP, VOCAL, FX, STEM, ROLL_FILL and UNKNOWN. Format labels include ONE_SHOT, LOOP, STEM, ROLL_FILL and UNSPECIFIED. These are **filename and folder heuristics**, not acoustic instrument recognition or machine-learning classifications.

**BPM** is parsed from filenames in the **55–190** range; it is not detected from the recording. A key requires an explicit note and mode, for example `Dm`, `F#min` or `Cmajor`. Multisample note `C1` is not evidence of C major. Camelot is calculated only when both note and mode are known.

**Energy** is a limited RMS estimate from up to three 4,096-frame windows of supported integer PCM WAVs (up to eight channels): CHILL < −24 dBFS; GROOVE −24 to < −12 dBFS; BANGER ≥ −12 dBFS; SILENT for silent observed windows; UNMEASURED when unreadable by that estimator. These are **not LUFS**, whole-file loudness or creative genre judgments.

Reindexing regenerates the sample/project/expansion index, CSV, JSON and catalog; SQLite row IDs are not stable between runs. Do not edit reconstructed tables expecting changes to persist. If interrupted during indexing, rerun the index and reload the browser. The process does not normalize or modify source audio.

## 5. Sample browser

1. Open the sample browser (**Explorador de Samples**). Search multiple terms across available filename, category, pack, type, format, BPM, key and Camelot fields.
2. Apply sound type, musical format, energy and BPM-range filters. Clear both general filters and expansion filters if a known file disappears.
3. Sort by name, format, size, BPM, pack or category. The displayed “date” ordering uses index order/IDs, **not** necessarily filesystem modification dates.
4. Browse up to **60 samples per page**. Listen before assigning.
5. Select the target pad, then assign. Replacing an occupied rack pad does not replace the sample file.

Auto-advance may select a used position if all pads are occupied. “Show in Finder”/file manager is server-based and requires an accessible library path.

## 6. Audio preview

Browser preview plays the source file. Pad playback applies its own volume, playback-rate pitch, available Web Audio panning and choke/mute behavior. Pitch alters speed by `2^(semitones/12)`, **changing duration**; this is not time-stretching. Browser decoding and FFmpeg conversion are separate capabilities: an MP3 can preview correctly yet fail during export if FFmpeg is missing.

Use a safe listening level, especially when moving between unprocessed sample previews and normalized PO reels. BeatOS does not emulate device mixing, filters, effects or sequencing.

## 7. 16-pad kit rack

Assign samples, import a supported copy of a Drum kit, drag/replace positions or use **Shuffle**. Moving a pad can exchange it with a populated or empty position. Clearing a pad or the rack changes the current browser state, **not** the original disk files.

Keyboard mapping:

| Pads | Keys |
| --- | --- |
| 1–4 | Z X C V |
| 5–8 | A S D F |
| 9–12 | Q W E R |
| 13–16 | 1 2 3 4 |

**Pad editor:** volume, pan, pitch in semitones and mute group. A mute group of **0** means unrestricted layering; positive groups 1–32 cut one another. Default grouping uses kick=1, hi-hat=2, snare=3 and otherwise 0, unless an imported kit explicitly provides different values.

The web volume scale is not dBFS: **100% is approximately gain 0.707946**. The UI slider reaches 150%, but the exporter validates volume **0–1**; visually exceeding approximately **141%** may fail validation. Use ≤100% for a conservative workflow. The editor supports pitch ±24 semitones; the API validates ±36. The rack's web session is **not saved to disk by “Save” in the editor**.

Supported imported MPC material may expose banks A–H, but each export uses **only the currently visible 16 pads**. Export every bank you want to keep under a distinct kit name before changing project, track, source, or reloading the page. Shuffle uses sample categories and may repeat sources; it is not generative AI.

## 8. Akai MPC projects

Indexing identifies XPJ projects and records metadata, sample references and warning states. Browse/search project cards; **INDEX_OK** means the indexer's reference check found no issue, **ATTENTION** indicates missing references and **ERROR** indicates a read/parse error. None of those labels certifies playback on physical hardware.

Choose **Editar copia en rack** (“Edit copy in rack”) for an eligible project, select a Drum track and bank A–H, then edit up to 16 pads. The importer uses the first active sample layer; multilayer details, missing samples and unsupported project types must be checked separately. It does not recreate sequences, plugins, effects, automations or the original song. Exporting creates a **new kit**; it never writes back over the source project.

An unambiguous reference must resolve inside the selected library. BeatOS must not silently substitute another file just because it has a similar basename. Save/export before replacing the working source or doing a full page reload.

## 9. MPC expansions

The expansion browser reads available `Expansion.xml` metadata and explores indexed programs, projects, samples and covers. “View programs” can list XPM files, including nested files. **Drum** programs are editable as rack copies; **Keygroup** files need their native MPC engine. “View projects” filters to XPJ files **within the selected expansion folder**; “View all projects” removes that filter.

Indexing neither installs nor redistributes commercial expansions. An expansion can contain no XPJ at all, or an XPJ dependent on external plugins. Reindex after adding/removing source files, and do not claim the entire expansion plays natively in the browser.

## 10. Kit export workflow

In the connected browser: load pads → choose **Exportar Kit** → enter a new kit name → choose **Destino de Hardware** → press **Generar Kit en Tarjeta MicroSD**. The name of that button does not require an SD card: results go to `Custom_Kits/<name>/` inside the active library.

| Target | Exported content | What is NOT transferred automatically |
| --- | --- | --- |
| Akai MPC | Drum XPM plus samples; separate Sample/AC50-derived XPJ + ProjectData | Original song, plugins, effects, complete song arrangement, all layers or guaranteed compatibility with every MPC version |
| Native Instruments Maschine | WAV in `Samples/Group_A/` and a JSON assignment map | Native `.mxgrp` file, pad parameters automatically imported, patterns |
| Roland SP-404MKII | PCM 16-bit **48 kHz** WAV and pad manifest | Native SP project, automatically applied pad assignment and settings |
| Roland SP-404A/SX | PCM 16-bit **44.1 kHz** `A01.wav`–`A12.wav` for populated pads **1–12 only** | Pads 13–16, gaps, native backup/project and encoded rack settings |
| Teenage Engineering PO-33/PO-133 | Mono PCM 16-bit **44.1 kHz** sample reel + slice manifest | Pattern backup, direct project transfer, pan and mute groups |
| Teenage Engineering EP-133 K.O. II | PCM 16-bit **44.1 kHz** WAV, JSON map, TXT guide and transport ZIP | Native EP project/backup, automatic pad settings or device ID allocation |

**Universal bundle** runs all six destination exporters. If any target conversion fails, the bundle can be aborted and partial output removed. For a single instrument, choose its specific export. Existing kit names are not overwritten: choose a new name.

Check the generated folder, its sample files, the device-specific manifest and any required FFmpeg conversion. Then transfer **using the manufacturer's instructions**, listen to every occupied pad and save in the native device/software. The presence of a ZIP or WAV is not evidence of successful installation.

[Hardware-specific loading steps](COMPATIBILIDAD_HARDWARE.md).

## 11. PO-33 and PO-133 sample reel

The **PO sample reel** is a sound-recording workflow, not an electronic project backup. It concatenates up to 16 occupied rack pads into **mono 16-bit/44.1 kHz** audio for recording through the Pocket Operator's line input. The general rack export uses a **40-second** budget and **150 ms** gaps.

The PO hub allows **1–40 seconds** total and **0–500 ms** gaps. Enter your device's *actual free memory*: BeatOS cannot read it. The export can trim long tails with a fade when the reel exceeds its budget; review `smart_trim_applied`, source pads, slice positions and duration in the JSON manifest. Empty rack pads do not create guaranteed empty PO slices.

Connect computer/interface audio out to **PO LINE IN**; record to an appropriate PO drum slot, then check slice **TRIM** on the physical unit. Optimize levels by listening; there is no universal safe percentage for every audio output. The reel applies tone/volume in audio and normalizes the complete reel; it does not preserve pan or mute groups.

## 12. Pocket Operator backup WAVs

**Do not confuse** a sample reel with the PO's own **audio data backup**, which may encode sounds and patterns. BeatOS can capture/import/archive the original WAV and prepare playback for restoration, but **cannot decode or validate the modem payload** or certify restoration.

**Capturing:** connect PO LINE OUT to a real **stereo line input**, not a mono microphone path. In the connected PO hub choose “Detectar entradas”, authorize the browser, select an input and start “Grabar backup”. The browser requests two channels, 44.1/48 kHz, with echo cancellation, noise suppression and automatic gain disabled. An AudioWorklet captures 16-bit stereo PCM. Once capture has started, issue **WRITE + SOUND + PLAY** on the PO, wait for the entire transfer and then stop/save.

BeatOS provides a visible **Download WAV** recovery link before attempting to archive the capture. Use it if browser download or disk archiving fails; do not close the tab while your only copy is still in memory. Recordings interrupted before completion are labelled **INCOMPLETE** and should not be used as confirmed backups. A maximum capture time of ten minutes is a safeguard, not modem completion detection.

**Import and inspect:** imports preserve the original bytes, calculate SHA-256 and store a file in `BeatOS/data/po33_backups/` without replacing a different existing recording. The import/inspection limit is **128 MiB**; WAV parser limits are 8–384 kHz and one to eight channels, but integrated restore playback only accepts **complete stereo 16-bit 44.1/48 kHz** recordings. Inspection checks WAV completeness and limited initial amplitude, not encoded content. A valid file hash cannot establish whether the original recording was usable.

**Restoring is destructive to the PO's current sounds and patterns.** Preserve its state first. After explicit confirmation, BeatOS loads an original backup into a separate **stopped** player at 1×. Connect stereo audio out → PO LINE IN, put the PO into receive mode (**WRITE + SOUND + RECORD**), play the complete backup, and verify the result on the device. No partial-slot merge is supported, and the browser cannot tell whether the PO accepted the transfer. A second PO is preferable for restoration tests that must preserve the primary unit.

Never normalize, trim, noise-reduce, fade, encode as MP3, or downmix your **only original backup**.

## 13. EP-133 K.O. II workflow

Generate the `ep133` target from the rack/hub. Review `sounds/`, `meta.json`, the generated TXT instructions and the ZIP. This is a **transport package, not an EP project or system backup**. The proposed map assigns pads **1–12** to EP group A (keys 1–9, period, 0, Enter), and pads **13–16** to four keys in group B.

Extract the ZIP, connect EP-133 by USB-C data cable and open the official [EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool) in a supported **desktop Web MIDI browser**. Import WAVs into free or deliberately chosen slots. Apply volume, pan, tune, mute and key assignments **manually**. Save/verify on the actual EP. BeatOS does not install firmware or report available IDs. The WAV interchange rate of 44.1 kHz must not be confused with device-internal processing rates.

## 14. Library statistics

The distribution cards summarize the **generated index** by musical format, instrument type, macro folder, estimated energy and BPM tiers. They do not read device RAM or show live pad-rack contents. Category and subpack reflect folder placement, not semantic machine-learning labels. After changing your audio collection, reindex and then fully reload the browser to refresh embedded data.

## 15. Maintenance and integrations

**Reload project/expansion cards** refreshes their displayed catalog data and preserves the current rack; **Reindex** rereads the active library and rebuilds generated files. Only one web reindex runs at a time **per server process**: do not start a separate CLI indexer over the same output concurrently. A full page reload after updating software refreshes JavaScript but may discard the unsaved rack.

**Clean metadata** explicitly removes `._*` and `.DS_Store` helper files; the web action may also run macOS `dot_clean -m`. This is a filesystem mutation, not a read-only integrity check, and is not required for indexing or playback.

The local status endpoint reports active root, count/space and task state. A historical MPCSMPL indicator does not imply that an unrelated drive is unavailable. **Cerebro dashboard sync** and certain theme integrations rely on external scripts from the author's private environment; they are optional, not requirements for BeatOS kit export. Do not launch historic maintenance scripts merely to open the catalog.

## 16. Language, themes and support

The **ES/EN** UI switch translates **only labels covered by its dictionary**, storing a browser preference; several menus, errors, help strings and terminal prompts remain in Spanish. File/sample names always retain their originals. The English documentation does **not** mean that the entire runtime has been localized.

Theme/background selections are cosmetic; an MPC60 or PO-20 visual theme **does not** add a corresponding exporter. Some theme sync actions write local and optional ecosystem preference files. Support links open third-party services; support is voluntary.

## 17. Backing up and moving your work

Preserve:

- Original audio, project files and associated ProjectData folders.
- Entire `Custom_Kits/<name>/` output (or the full chosen destination directory).
- An individual export for **each edited MPC bank** before leaving the browser; the rack does not persist complete sessions.
- `BeatOS/data/` only when you need its generated index; it can be rebuilt, and it may contain **personal file paths**.
- Original PO backup WAVs, hashes and **an external copy**; these are not reconstructible from the index.
- Final projects saved through the *native* sampler/software.

After moving a library, reindex it at the **new root** so absolute references no longer point to the old disk. Do not assume two matching basenames identify one unique sample. Share the clean installer ZIP, **not** your private music library. An exported kit that contains copyrighted samples is not automatically licensed for redistribution.

## 18. Producer walkthroughs

### A. Build a hip-hop / boom-bap or electronic drum kit from loose samples

Index your folder → filter KICK/SNARE/HIHAT/PERCUSSION, preview individual sounds → fill relevant rack pads → check mute groups and pitch → select an export target → give the kit a new name → import, listen and save on the device. Genre names are organization hints only: the sound must be auditioned.

### B. Reuse one Drum bank from an MPC project

Find an XPJ → inspect missing media → load a supported Drum track as a copy → select the correct bank → edit the visible 16 pads → export it under a new name. Repeat for each other bank. The original project's song arrangement is **not** recreated.

### C. One performance kit for MPC, SP-404, Maschine, PO and EP

Prepare the rack once, then choose **Universal** if all conversions can be completed. Review every destination separately. SP-404A/SX uses only pads 1–12; PO uses a recorded mono reel; Maschine and EP require manual sample/parameter loading. No universal native-project file is produced.

### D. A fresh installation without the author's hardware

Install the ZIP or clone, select *your own* library, index it, serve it by HTTP and use browser/rack/export. You do not need a drive named MPCSMPL, Cerebro, or DJProducerTools.

## 19. Troubleshooting

| Problem | Check |
| --- | --- |
| “Not connected” / export disabled | Use the local HTTP page, not `file://`. Confirm the terminal server is running. |
| Wrong sample library | Check the displayed active root; restart with an explicit library path. |
| Port 8888 busy | Use the port shown by the server. |
| New audio does not appear | Clear filters and expansion scope; check extensions/ignored folders, reindex and fully reload. |
| XPJ appears indexed but cannot be opened | Check Drum structure, ProjectData references, selected track/bank and precise error. |
| Audio previews but export fails | Browser codec ≠ FFmpeg support; check executable PATH, free space and conversion format. |
| SP-404MKII rejects 44.1 kHz audio | BeatOS target converts to 48 kHz; FFmpeg is needed for incompatible sources. |
| “volume out of range” | Lower the rack's visual level; the exporter validates volume ≤1. |
| Kit already exists | Change the name; BeatOS does not overwrite that output. |
| Universal export fails | Inspect the failing target; try one device-specific export. |
| Missing SP-404A/SX sounds | Only occupied pads 1–12 are exported; empty pad gaps are not encoded. |
| PO reel cuts or tails sound wrong | Revisit duration, gaps, trim report and physical PO TRIM. |
| PO backup cannot record | Stereo line input, browser permissions, 44.1/48 kHz and voice DSP off; otherwise use an external unprocessed WAV recorder. |
| Captured PO backup says INCOMPLETE | Download recoverable WAV and repeat the entire data transfer. |
| PO backup looks healthy but fails restoring | Header/hash inspection cannot verify modem payload; preserve originals and test only with a safe rollback path. |
| EP Sample Tool cannot see device | Use a real USB data cable and supported desktop Web MIDI browser; authorize device access. |
| Labels remain old after updating | Reload the entire page from the current installation; card reload does not reload JavaScript. |

For bug reports, include BeatOS version and commit, operating system, active root (without private data), source file type, intended target, exact error, and hardware model/firmware where applicable. Prefer a reproducible synthetic sample to uploading commercial sample libraries.

## 20. Validation scope and known limits

Automated repository tests cover parts of indexing, metadata, parsers, routes, server, mute groups, exporters, installer, web interactions and build artifacts. CI includes Linux tests and a Windows install check for release packages; **verify the actual workflow run for the relevant commit** before claiming any test passed. These tests do **not** certify every hardware model, firmware revision or browser.

Known limitations include the Sample/AC50-derived XPJ template (no independent MPC One/Live profile); no native Maschine/SP/EP project generation; no modem-data decoding for PO backups; rack state that is not fully saved across sessions; UI volume/export validation differences; and partially translated runtime labels.

**Version numbers are unrelated:** *BeatOS 3.8.0* is not *Akai MPC 3.8*. For device operations, consult the [hardware compatibility guide](COMPATIBILIDAD_HARDWARE.md). For API and file structures, consult the [technical reference](REFERENCIA_TECNICA.md). [Back to Spanish manual](../MANUAL_COMPLETO.md).
