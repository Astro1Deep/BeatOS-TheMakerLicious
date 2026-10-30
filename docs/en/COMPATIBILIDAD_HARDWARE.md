# BeatOS 3.8.0 — Hardware compatibility and loading guide (EN)

**Languages:** [English](COMPATIBILIDAD_HARDWARE.md) · [Español](../COMPATIBILIDAD_HARDWARE.md)  
[English manual](MANUAL_COMPLETO.md) · [Technical reference](REFERENCIA_TECNICA.md) · [Project home](../../README.md)

**Review basis: 30 October 2026.** Distinguish: **(1) the files BeatOS writes; (2) what the manufacturer documents; (3) actual loading, playback and saving on the exact model and firmware.** Synthetic and structural software tests cannot certify all devices. No physical compatibility-test register is included in this review.

## 1. Akai MPC Sample vs MPC One, Live, X and other models

The BeatOS `mpc` exporter writes **two different deliveries**:

| Artifact | Output | Meaning |
| --- | --- | --- |
| **Drum XPM** | `Akai_MPC/<kit>.xpm` alongside WAV files | A drum program containing implemented sample assignment, volume, pan, pitch and mute settings. Not an entire song. |
| **Sample-derived XPJ** | `Akai_MPC/<kit>/<kit>.xpj` plus `<kit>_[ProjectData]/` | A new project derived from a template identifying `AC50`, `engineMode=Sample`, and internal `data.version=28`. It is **not** a dedicated One/Live/X exporter. |

BeatOS exports **the current 16 pads**, not the source song, full track arrangement, plugins, effects, sequences or all sample layers. The internal template data version is **not** a firmware version. BeatOS does not invoke Akai's official “As MPC Sample File” command and does not detect firmware automatically.

**Akai MPC 3.8 release notes** document both importing MPC Sample projects into supported MPC desktop/standalone software and exporting a Drum track as an MPC Sample file. This manufacturer-supported operation does **not** automatically validate BeatOS's derivative XPJ. Older desktop/standalone version incompatibilities also matter. [Akai MPC 3.8 release notes](https://cdn.inmusicbrands.com/Software/AM20P3C8FWUPGZL12/MPC%203.8%20Release%20Notes.pdf) · [Akai program loading](https://support.akaipro.com/en/support/solutions/articles/69000804211-akai-pro-mpc-series-understanding-and-loading-programs).

| Hardware family | Practical approach | Limitation |
| --- | --- | --- |
| MPC Sample (AC50) | Review Sample-derived XPJ with its ProjectData, or import WAV manually. | A Drum XPM is not a full MPC Sample project. |
| MPC One / One+ | Start with XPM+WAV; verify official procedures/version when trying Sample-derived XPJ. | Not every older engine/firmware can load the same XPJ. |
| MPC Live / Live II / Live III | Keep XPM/program and Sample-derived XPJ distinct; validate installed engine. | “Live” covers multiple hardware generations and firmware states. |
| MPC X / X SE, Key 37 / Key 61 | Check program-loading documentation for installed MPC software. | Missing original effects/sequences cannot be recreated by the exported samples. |
| MPC XL / Force and other models | Consult the exact device/software workflow before assuming compatibility. | No dedicated automatic schema selection or certification. |

**Loading check:** preserve source projects, place the entire exported folder (including samples and ProjectData) on an appropriate medium, use the manufacturer's open/load process, inspect every pad, then save and reopen from the destination software. Do **not** use a successful import dialog as proof of sound/mute/pitch correctness.

## 2. Native Instruments Maschine

BeatOS outputs `NI_Maschine/<kit>/Samples/Group_A/` WAVs at 44.1 kHz and `Groups/<kit>_Maschine_Map.json`, which lists slot and suggested parameters. **It does not generate a native `.mxgrp`**, pattern, scene, plugin chain or Maschine project.

**Maschine MK3, Mikro MK3 and Studio** run with compatible Maschine desktop software. **Maschine+** can use its standalone user sample storage, or compatible computer workflows. **Maschine Jam** is a controller, not a hardware destination for a BeatOS kit. Legacy MK1/MK2 and Mikro MK1/MK2 controllers are not supported by Maschine 3 according to NI's FAQ; WAV exports do not change driver/software requirements. [Official Maschine 3 FAQ](https://support.native-instruments.com/support/solutions/articles/69000879549-maschine-3-faq).

1. Export the `maschine` target and preserve its `Samples/` and `Groups/` subfolders.
2. Load the WAV files into the Sounds of a group through the compatible Maschine application or Maschine+ user sample browser.
3. Use the JSON fields `slot`, `file`, `volume`, `pan`, `tune` and `choke_group` as an assignment/checklist reference.
4. Apply volume, pan, tune and choke manually; exported WAVs do not encode these rack settings.
5. Save the group/project from **Maschine** itself.

## 3. Roland SP-404MKII

The `sp404mk2` export writes PCM **16-bit/48 kHz** WAVs (`PAD_01_…wav` etc.) and `sp404mk2_manifest.json` under `Roland_SP404MK2/<kit>/`. The manifest describes source mapping: it is not an instruction executed by Roland hardware.

1. Install FFmpeg where sample conversion to 48 kHz is necessary, then export the target.
2. Check every generated WAV and the manifest.
3. Import via the specific firmware's SD workflow or Roland's official SP-404MKII application.
4. Check the destination pad; a file named `PAD_05` does not auto-place the sound at pad 5. Loading over an occupied pad may overwrite it.
5. Configure volume, pan, pitch, effects and mute behavior **on the SP**, save and verify playback.

Roland notes supported audio formats and conversion handling; very short sounds (below around 100 ms) can require special attention. [Roland format support](https://support.roland.com/hc/en-us/articles/4408190553883-SP-404MK2-What-audio-file-formats-can-be-imported-into-the-SP-404MK2) · [Roland application manual](https://static.roland.com/assets/media/pdf/SP-404mk2_app_eng02_W.pdf).

**DOOM OS:** the name may appear in UI text, but BeatOS does not ship a dedicated alternate-firmware exporter or certified protocol. The same WAV delivery is created.

## 4. Roland SP-404A and SP-404SX

The `sp404a` target generates **only occupied rack pads 1–12**, named `A01.wav`–`A12.wav`, as PCM **16-bit/44.1 kHz**. **Pads 13–16 are omitted**. It generates no silence fillers for gaps and no native project/backup/JSON settings map.

1. Move all desired sounds into rack positions 1–12 before export.
2. Back up the current SD card and prepare the import folder/procedure for your exact SP model.
3. On SX, Roland documents the `ROLAND/IMPORT` WAV/AIFF route, `FUNC + pad 3`, destination selection and `REC`. Imported files can be removed from the staging folder; filenames alone do not preserve empty pad gaps.
4. Verify every assignment and apply hardware settings manually.

Use the [SX import guide](https://support.roland.com/hc/en-us/articles/201977679-SP-404SX-Importing-Samples), [SX operating manual](https://cdn.roland.com/assets/media/pdf/SP-404SX_OM.pdf) and [SP-404A manual](https://static.roland.com/assets/media/pdf/SP-404A_eng01_W.pdf). Original SP-404 CompactFlash has a different procedure and **no dedicated BeatOS profile**.

## 5. Teenage Engineering PO-33 K.O! and PO-133

The target is a **sample reel**, **not** an SD/USB transfer, patch file or complete Pocket Operator data backup.

- Exported audio: mono PCM **16-bit/44.1 kHz**, with cut manifest.
- Total reel duration: **1–40 s** in the PO hub; the general rack uses **40 s**.
- Inter-slice gaps: **0–500 ms**; general rack default **150 ms**.
- BeatOS **cannot query free memory** on the Pocket Operator.
- Pitch and volume are applied to the reel; the overall audio is normalized. Panning and mute groups do not transfer.
- Over-budget audio may be shortened with a fade; review the manifest's trim report.

Connect the interface output to **PO LINE IN**, record onto a PO drum slot using the manufacturer's procedure, and adjust slices with TRIM. Occupied pads become successive cuts in one recorded sound, **not** 16 independent USB slots. Do not claim automatic slice accuracy without checking the device. [Official PO-33 guide](https://teenage.engineering/guides/po-33/en) · [PO-133 guide](https://teenage.engineering/guides/po-133/en).

**PO backup WAV workflow:** a device-originated audio-data dump encodes sounds/patterns, unlike the sample reel. BeatOS can capture/import/save a WAV and prepare restore playback, but does **not** decode modem payload or prove that a restore will work. Never change (normalize, trim, mono-downmix, compress) your only backup. Restoring data onto the PO **replaces the current state**; verify on a separate device if preserving the original is essential. [Detailed English backup workflow](MANUAL_COMPLETO.md#12-pocket-operator-backup-wavs).

Other PO models such as PO-20 and PO-35 have no dedicated exporter even if their imagery/themes appear in the interface.

## 6. Teenage Engineering EP-133 K.O. II

The `ep133` exporter produces **PCM 16-bit/44.1 kHz** mono/stereo WAVs in `sounds/`, a `meta.json`, TXT instructions and a ZIP **for transport**. The ZIP is **not** a native EP backup or project.

1. Generate the EP destination and extract the transport ZIP where needed.
2. Connect the EP by a USB-C **data** cable, not a charging-only cable.
3. Use [EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool) in a manufacturer-supported desktop browser with Web MIDI permissions. Import WAVs carefully into chosen free or replaceable slots.
4. Follow the JSON map: rack 1–12 map to group A's twelve listed keys, and 13–16 map to the first four group B keys.
5. Apply rack volume, pan, tuning and mutes **manually**, then save/reopen on device.

A file's numeric prefix is a suggestion, **not** reservation of an internal EP ID. Some official documentation versions describe different storage capacities: check your **actual device and firmware**, not a hardcoded free-memory assumption. The export rate is an interchange rate, **not** necessarily the instrument's native recording rate. [Official EP-133 guide](https://teenage.engineering/guides/ep-133) · [Function guide](https://teenage.engineering/guides/ep-133/functions).

Other EP models do not automatically share this mapping.

## 7. Minimal physical verification protocol

For any “tested hardware compatibility” claim, record: **BeatOS version and commit; exported target; sample kit name; exact device model; hardware firmware and companion software; original sample formats; export settings; loading method; every pad's result; save/reopen result; unresolved limitations**.

A useful test kit includes short and long drum hits, stereo source, a deliberately empty pad, nonzero tuning and two sounds sharing one choke group. For A/SX, test the 12-pad limit and gaps. For PO, check total available memory and slicing. For MPC, test XPM and Sample-derived XPJ separately. Always test on a copy, never your only project.

[Español: guía original y fuentes adicionales](../COMPATIBILIDAD_HARDWARE.md).
