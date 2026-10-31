# BeatOS — Advanced hardware export protocols and acceptance testing

**English technical operator reference** · [Español](../HARDWARE_EXPORT_PROTOCOLS.md) · [Complete manual](MANUAL_COMPLETO.md) · [Hardware compatibility](COMPATIBILIDAD_HARDWARE.md) · [API reference](REFERENCIA_TECNICA.md)

**Scope:** implemented BeatOS 3.8.0 exporters as inspected on 30 October 2026, with cross-checks against manufacturer documentation. The notes below distinguish BeatOS **output structure**, the **manufacturer's import protocol**, and **physical acceptance evidence**. A structurally valid WAV, XPM, XPJ or ZIP alone does not certify native playback, pattern restoration or firmware compatibility.

## 1. Signal/data path and protection

`Sample library (unchanged) → index (SQLite/JSON/CSV) → 16-pad rack → validated export request → per-target conversion → output directory → manufacturer-supported transfer/import → device audition/save/reload`.

**Keep an untouched copy of source audio and genuine hardware backups.** Do not overwrite an existing BeatOS kit: the exporter reserves a new output directory and refuses a duplicate name. A failed operation attempts to remove its incomplete new output. The original sample library should not be used as an export destination. Keep the BeatOS HTTP server local; its action API is not authenticated for internet exposure.

Audio conversions use PCM WAV output. For a nonconforming source, BeatOS calls **FFmpeg** if installed; without it, supported direct-copy inputs must already be compatible PCM. Level and processing should be checked **after** conversion. The sample rack passes sample references, gain, pan, semitone tune and mute group; only parameters the target exporter actually encodes can be transferred. A parameter present in JSON does *not* mean the hardware will automatically load it.

### Release acceptance criteria

1. Verify ZIP checksum and `BeatOS/MANIFEST.sha256.json`; prove the installed `BeatOS/data/catalogo.html` was rendered from the expected template.
2. Exercise EN-first and ES selection on an actual HTTP-served page. Verify every native dialog, toast, warning, hover hint, progress text, and API diagnostic in both directions.
3. Generate a synthetic kit containing kick, snare, hi-hat and stereo loop; include non-ASCII filenames and 44.1/48 kHz inputs. Hash original sources before and after.
4. Parse all outputs; verify expected PCM bit depth, channel count, sample rate, nonzero duration, filenames, pad references and output-manifest paths. Do not silently drop unsupported pads or effects.
5. On each physical device, record model, exact firmware/software version, input media/connection, successful import, pad/sample recall, level, looping, trim, choke behavior, project save, power cycle and reload. Mark untested conditions **NOT VERIFIED**, never “fully supported”.

## 2. Akai MPC — Drum XPM and Sample-derived XPJ

**BeatOS implementation:** `Akai_MPC/<kit>.xpm` is an XML Drum program derived from `templates/template_drum.xpm`, with pad assignments, sample filenames, coarse tuning, volume, pan and mute group. The project path `Akai_MPC/<kit>/<kit>.xpj` uses `<kit>_[ProjectData]/`, an ACVS + gzip/JSON template whose engine profile identifies Sample/AC50. The project payload references WAV filenames and includes tempo, first track/program and instrument-layer state. Only the first editable sample layer of the visible rack is represented; no guarantee is made about effects, plugin states, full arrangements or arbitrary extra tracks.

**Do not confuse MPC Sample and MPC One/Live/X:** Akai documents MPC Sample project support in MPC 3.8+ but compatibility depends on exact engine/software version. Exported XPM and XPJ should be tested independently; a successfully parsed XPM is not proof of a cross-device XPJ project. Earlier MPC 2 versions may reject recent MPC Sample projects.

**Transfer and validation:** keep the complete project folder and `[ProjectData]` directory together, do not rename referenced WAVs, and import using the target MPC's supported browser/transfer mechanism. Inspect sample resolution and note velocity/layer/pitch/choke differences in the device. Save a *new* project on the MPC itself, reopen it, and document any conversions or missing voices. If an incompatible firmware reports a failed project load, verify engine generation and firmware before modifying the export.

Manufacturer references: [MPC Sample FAQ](https://support.akaipro.com/en/support/solutions/articles/69000876967-mpc-sample-frequently-asked-questions) · [MPC Sample project version incompatibility](https://support.akaipro.com/en/support/solutions/articles/69000879081-mpc-2-desktop-mpc-project-failed-to-load-error-when-importing-mpc-sample-projects).

## 3. Native Instruments Maschine — audio + mapping guide, not a Group file

**BeatOS implementation:** `NI_Maschine/<kit>/Samples/Group_A/A##_*.wav` plus `Groups/<kit>_Maschine_Map.json`. Its JSON provides slot, sample name, relative file, tune, pan, volume and choke group. **BeatOS does not generate `.mxgrp` or `.mxprj`**; JSON is an operator-facing mapping guide and cannot be represented as a Maschine-native Group.

**Workflow:** import the WAVs into separate Maschine Sounds, assign pads in the specified order, reconstruct choke groups and levels manually, verify each trigger and save the Group/Project **in Maschine**. Collect the real Maschine project and its samples when moving between computers or Maschine+ storage. Never rename WAVs without updating mapping and relinking them.

Manufacturer reference: [NI — Sharing Maschine projects and associated samples](https://support.native-instruments.com/support/solutions/articles/69000879595-maschine-sharing-projects-across-multiple-computers).

## 4. Roland SP-404MKII — 48 kHz audio import

**BeatOS implementation:** `Roland_SP404MK2/<kit>/PAD_01_*.wav` through `PAD_16_*.wav`, with PCM **16-bit/48 kHz** and `sp404mk2_manifest.json`. Stereo is retained where supported by the source converter. The manifest is a BeatOS record; it is **not** the SP-404MKII native project/backup representation.

**Workflow:** use the firmware-appropriate SP-404MKII SD-card IMPORT folder/Import Sample procedure or Roland's SP-404MKII App. In the instrument, select pad destination and confirm sound plays correctly. Test velocity, gate/one-shot, trim, pitch and bank assignment because the WAV filenames alone do not set all device parameters. Before importing, verify the SD card's folder structure and supported format. Never confuse a sample-import folder with the manufacturer's project backup.

Manufacturer references: [Roland v5 import/export](https://static.roland.com/manuals/sp-404mk2_reference_v500/en-US/7958234778537099.html) · [Roland format/sample-rate specifications](https://static.roland.com/manuals/sp-404mk2_reference_v500/en-US/8010023578592395.html).

## 5. Roland SP-404A / SX — 12 samples per prepared bank

**BeatOS implementation:** prepares `A01.wav`–`A12.wav` in one output folder, with mono/stereo **16-bit/44.1 kHz** PCM. The exporter maps **only pads 1–12**. It does not create a native card image, bank layout or patterns.

**Workflow:** use the original SP-404A/SX manual's supported audio import procedure, prepare compatible media, and map imported WAVs to the intended 12 pads. Check that pads 13–16 were not inadvertently assumed to have transferred. Preserve any original bank/patterns and validate the physical result by auditioning and saving.

## 6. Teenage Engineering PO-33 / PO-133 — audio reel versus modem backup

**BeatOS implementation:** a mono **PCM 16-bit/44.1 kHz** reel with a separate JSON timeline of candidate slice boundaries. Default gaps are 150 ms; allowed gap setting is 0–500 ms; the **selected** memory budget is 1–40 seconds. BeatOS may trim and fade samples to fit. This reel is an **audio recording/import aid** for PO-33 drum slots, **not** a native FSK/modem backup of patterns and internal settings.

**Workflow:** connect the computer's line output to PO input, monitor safe signal level, enter the PO's drum-recording mode, play the reel and inspect the resulting slices with TRIM. The device's actual free recording memory is not queried by BeatOS; select the budget manually. Always verify the complete recorded reel and all slices. For full backups, use the manufacturer's audio-modem send/receive workflow separately. BeatOS backup-recording utilities can preserve an original WAV and compute SHA-256, but **do not decode or certify the modem payload**.

### Pocket Operator Studio — archive and protocol verification (development build)

The **Pocket Operator Studio** backup tool handles **PO-32, PO-33, PO-35, PO-133 and PO-137** audio-data recordings. Select the model **before recording or importing** and give the beat/project a distinctive name. BeatOS stores the original stereo WAV under `BeatOS/data/po33_backups/<MODEL>/` and writes a `.po.json` provenance sidecar with the original filename and SHA-256. It does not destructively overwrite recorded takes. Legacy recordings without a sidecar are marked **UNSPECIFIED** until their device model is established; a random WAV must not be offered for restore as a PO-33 project.

The **Verify digital transfer** action currently supports **only PO-33**: it uses a vendored MIT-licensed independent decoder, requires optional Python NumPy (`python3 -m pip install numpy`), and checks symbol recovery, preamble, full packet CRCs, payload structure and end marker **without modifying the original WAV**. The result `PROTOCOL_CHECKSUM_VERIFIED` **does not** assert editable PO-33 patterns or physical restore compatibility. `PO-133` remains separately unverified until real model-specific fixtures pass. PO-32/35/137 archive and replay are available, but the PO-32 decoder/encoder from `libpo32` has **not yet been integrated**. Do not reuse PO-33 packet rules on other models.

| Device | Send the device state | Prepare data reception | Digital verification in BeatOS |
| --- | --- | --- | --- |
| PO-33 / PO-133 | WRITE + SOUND + PLAY | WRITE + SOUND + RECORD | PO-33 packet checks only |
| PO-32 | WRITE + SOUND | ACC + SOUND | Not integrated |
| PO-35 / PO-137 | WRITE + SOUND | RECORD + SOUND | Not integrated |

**Safety:** restore may erase every existing sound and pattern on the receiving unit. First record and preserve a known-good backup of the receiver. Match the destination model, connect a **stereo wired** line output to LINE IN, disable EQ/spatial effects/Bluetooth and avoid clipping. Arm receive on the hardware, then manually start the paused backup-player at 1×. Browser/system audio processing and soundcard channel settings may still change the analog transmission. A successful upload or checksummed packet decoder is **not** physical proof: verify the device displays successful reception and that sounds/patterns survive a save/reload cycle. No PO-12/14/16/20/24/28/128 audio-data backup is claimed.

**Third-party decoder:** `vendor/po33_decode.py`, MIT copyright Daniel Pradilla; attribution in `vendor/PO33_DECODER_LICENSE.txt`. This optional decoder is source-visible and does not transmit files to the internet. The PO-33 format and any further edit/encode features remain independent, reverse-engineered research rather than manufacturer-endorsed support.

## 7. Teenage Engineering EP-133 K.O. II — Sample Tool import

**BeatOS implementation:** `Teenage_Engineering_EP133/<kit>/sounds/001_PAD01_*.wav`–`016_PAD16_*.wav` in 16-bit/44.1 kHz PCM, `meta.json` (sound, group, key, tune, pan, choke references), a readable loading guide and a transport ZIP. The manifest assigns 12 positions to group A and four to B, following BeatOS's chosen rack layout, *not* a complete native project format.

**Workflow:** extract the ZIP, connect the EP-133 via USB-C and use the [official EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool) in a compatible desktop browser. Transfer desired WAVs, assign sounds to the intended groups/keys and check total device memory. Configure the documented metadata parameters manually, audition and save in the device. **Never attempt native backup restore using BeatOS's transport ZIP.**

Teenage Engineering has added support for additional sample rates in newer EP-133 firmware/Sample Tool workflows, so 44.1 kHz is BeatOS's chosen output policy—not a claim about every rate currently accepted by the instrument. Consult [EP-133 functions and Sample Tool documentation](https://teenage.engineering/guides/ep-133/functions).

## 8. Physical validation record — minimum fields

| Field | Required observation |
| --- | --- |
| Device | Manufacturer, exact model, hardware revision, firmware, companion app version |
| Input | Export target, sample hash, source/output WAV rate/bit depth/channels, pad count |
| Transfer | USB/SD/audio path, import procedure, destination bank/slot, firmware warning |
| Playback | Audible sound on each pad, stereo/mono result, clipping, trim/loop, gain, pitch, choke |
| Persistence | Save on hardware, restart/reload, relinked samples and pattern/project integrity |
| Result | **PASS**, **FAIL**, **NOT TESTED** or **PARTIAL**; evidence path and reproduction steps |

A **PASS** requires a real device load/save/reload cycle. An automated file-structure check must be labelled **software-validated only**. Keep dated results per firmware; retest after major device updates. If functionality requires a manufacturer's proprietary native file format, implement it only after a documented schema, lawful testing and a physical round-trip, not by renaming a WAV/JSON/ZIP extension.
