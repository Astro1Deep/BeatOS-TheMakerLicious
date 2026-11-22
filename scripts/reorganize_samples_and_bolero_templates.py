#!/usr/bin/env python3
"""Reorganize one-shot/loop/vocal sample libraries and build structural Bolero Chop Templates.

Part A — Pure One-Shot / Loop / Vocal / Amen-Break libraries:
- Moves pure sample libraries out of `Expansions/` into `MPC-Sample/Samples/` as
  clean browseable WAV folders (zero homogeneous artificial `.xpm`/`.xpj`/`_[ProjectData]`):
  - `araabMUZIK - Essentials Vol 2` -> `05_DRUM_KITS_&_ONE_SHOTS/`
  - `Zenhiser - Lofi Hip Hop` -> `01_BOOM_BAP_&_LOFI/`
  - `Sample Magic - Dubbed Vocals` -> `07_VOCALS_&_CHOPS/`
  - `Rhythm Lab - Ultimate Amen Breaks` -> `03_ELECTRONIC_HOUSE_DNB/`
  - `Test Press - DnB Textures 2` (`one_shots` + `loops`) -> `03_ELECTRONIC_HOUSE_DNB/`,
    keeping ONLY the 3 genuine mixed Beatmaker kits in `Expansions/`.
  - `Vocal Destiny` (12 vocal-only banks / 171 vocal+melodic WAVs) -> `07_VOCALS_&_CHOPS/`,
    keeping ONLY the 2 genuine full Bonus kits + `.sxq` sequences in `Expansions/`.
  - `Serato Studio - Artist Collection`: removes only the 4 artificial WAV-gap programs
    in `Bonus_Loops_&_Shots/` and `Core/Sets_Audio/`, preserving all 203 real drum kits.

Part B — `Astro1Deep - Bolero & Ranchera 1950s (Mono Vinyl)`:
- `01_Full_Tracks_Mono_44k/`: pure 32 full mono WAVs (no `.xpm`/`.xpj`).
- `02_Song_Sections/`: 32 per-song folders containing ~8-bar (4–8 bar at real MIR
  structural boundaries) standalone WAVs with zero clicks and zero `.xpm`/`.xpj`,
  ready for standalone loading and 16/32 Auto-Chop on MPC/Melodee.
- `03_Chop_Templates/`: 32 Bank-C Chop Templates (`.xpm` + `.xpj` ACVS 1.3.0.12 +
  `_[ProjectData]`) with Bank A (drums) EMPTY, Bank B (chopping) EMPTY, Bank C
  `C01–C15` populated with structural sections, and `C16` populated with the Full Track.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
import struct
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

import librosa
import numpy as np
import soundfile as sf
from scipy.ndimage import maximum_filter1d
from scipy.signal import butter, sosfiltfilt

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for p in (REPO_ROOT, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import hardware_kit_builder as hkb  # noqa: E402
import mpc_compat  # noqa: E402
import repair_mpc_expansions as rme  # noqa: E402

AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac"}
TARGET_PEAK_LINEAR = 10.0 ** (-0.80 / 20.0)  # -0.80 dBFS ceiling
SR_TARGET = 44100
HOP = 256

FULL_TRACK_STEMS: Dict[str, str] = {
    "01": "A1D_01_BoleroOrq_Bbm_81BPM",
    "02": "A1D_02_BoleroRom_Dm_75BPM",
    "03": "A1D_03_Serenata_Bbm_77BPM",
    "04": "A1D_04_Ranchera35mm_Ebm_85BPM",
    "05": "A1D_05_BoleroCuerdas_E_75BPM",
    "06": "A1D_06_BoleroNoct_Cm_75BPM",
    "07": "A1D_07_Ranchera50_C_75BPM",
    "08": "A1D_08_BoleroReq_E_73BPM",
    "09": "A1D_09_SerenataBrass_E_76BPM",
    "10": "A1D_10_CineDeOro_C#m_75BPM",
    "11": "A1D_11_RancheraOrq_E_75BPM",
    "12": "A1D_12_BoleroCantina_E_75BPM",
    "13": "A1D_13_ValsBolero_C#m_75BPM",
    "14": "A1D_14_BoleroPiano_E_71BPM",
    "15": "A1D_15_RancheraMariachi_E_75BPM",
    "16": "A1D_16_BoleroSpring_E_75BPM",
    "17": "A1D_17_SerenataTrio_E_75BPM",
    "18": "A1D_18_BoleroFinal_E_75BPM",
    "19": "A1D_19_BoleroTerciopelo_E_77BPM",
    "20": "A1D_20_SerenataOro_E_76BPM",
    "21": "A1D_21_BoleroSalon_E_76BPM",
    "22": "A1D_22_RancheraContrabajo_E_81BPM",
    "23": "A1D_23_BoleroSombra_Ab_86BPM",
    "24": "A1D_24_SerenataBruma_Eb_81BPM",
    "25": "A1D_25_BoleroPenumbra_Cm_82BPM",
    "26": "A1D_26_BoleroCadencia_F_81BPM",
    "27": "A1D_27_RancheraCinta_C_76BPM",
    "28": "A1D_28_BoleroCuarteto_A_75BPM",
    "29": "A1D_29_SerenataNostalgia_E_82BPM",
    "30": "A1D_30_BoleroProfundo_Fm_89BPM",
    "31": "A1D_31_BoleroDorada_F#m_80BPM",
    "32": "A1D_32_EnLaPenumbra_Dm_81BPM",
}

NOTE_TO_SEMITONE: Dict[str, int] = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


# ---------------------------------------------------------------------------
# Shared file / audio helpers
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy_if_needed(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and dst.stat().st_size == src.stat().st_size:
        return
    shutil.copy2(src, dst)


def _archive_metadata_files(pack_dir: Path, archive_dir: Path) -> int:
    """Save Expansion.xml, Artwork, Cache JSONs before removing a moved pack."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for item in sorted(pack_dir.iterdir()):
        if not item.is_file() or item.name.startswith("."):
            continue
        if item.suffix.lower() in (".xml", ".jpg", ".jpeg", ".png", ".json", ".txt"):
            _copy_if_needed(item, archive_dir / item.name)
            saved += 1
    return saved


def _iter_clean_audio_files(
    root_dir: Path,
    *,
    include_txt: bool = True,
    exclude_top_dirs: set[str] | None = None,
) -> List[Tuple[Path, Path]]:
    """Return `(src_path, rel_path)` for clean audio/txt files outside `[Previews]` and `_[ProjectData]`."""
    allowed = set(AUDIO_EXTS)
    if include_txt:
        allowed.add(".txt")
    excl = exclude_top_dirs or set()
    items: List[Tuple[Path, Path]] = []
    # Never wrap os.walk() in sorted(): pruning dns[:] only works while lazily iterating!
    for dp, dns, fns in os.walk(root_dir):
        dp_p = Path(dp)
        dns[:] = sorted(
            d
            for d in dns
            if not d.startswith(".")
            and d not in ("[Previews]", "__MACOSX")
            and not d.endswith(("_[ProjectData]", "_[TrackData]", "_[ProgramData]"))
            and (dp_p != root_dir or d not in excl)
        )
        rel_dir = dp_p.relative_to(root_dir)
        for fn in sorted(fns):
            if fn.startswith("."):
                continue
            src = dp_p / fn
            if src.suffix.lower() not in allowed:
                continue
            rel = (rel_dir / fn) if str(rel_dir) != "." else Path(fn)
            items.append((src, rel))
    return items


def _copy_clean_audio_tree(
    src_root: Path,
    dst_root: Path,
    *,
    include_txt: bool = True,
    exclude_top_dirs: set[str] | None = None,
) -> int:
    """Copy clean WAV/audio/txt files excluding .xpm/.xpj/_[ProjectData]/[Previews]."""
    items = _iter_clean_audio_files(src_root, include_txt=include_txt, exclude_top_dirs=exclude_top_dirs)
    for src, rel in items:
        _copy_if_needed(src, dst_root / rel)
    return len(items)


def _count_clean_audio_files(root_dir: Path, *, include_txt: bool = True, exclude_top_dirs: set[str] | None = None) -> int:
    return len(_iter_clean_audio_files(root_dir, include_txt=include_txt, exclude_top_dirs=exclude_top_dirs))


def _categorize_vocal_destiny_wav(filename: str) -> str:
    low = filename.lower()
    if "adlib" in low:
        return "Adlibs"
    if "harm" in low:
        return "Harmonies"
    if "hook" in low:
        return "Hooks"
    if "onsht" in low or "one shot" in low or "oneshot" in low:
        return "One_Shots"
    if "phrase" in low or "phrse" in low:
        return "Phrases"
    if "loop" in low or "piano" in low or "rhodes" in low:
        return "Melodic_Loops"
    return "Other"


# ---------------------------------------------------------------------------
# Part A: Reorganize Pure One-Shot / Loop / Vocal / Amen-Break Packs
# ---------------------------------------------------------------------------

def stage_reorganize_oneshots(card_root: Path, tpl: rme.AcvsTemplateLoader) -> Dict[str, Any]:
    exp_root = card_root / "Expansions"
    smp_root = card_root / "MPC-Sample" / "Samples"
    meta_archive = card_root / "_RAW_SOURCE_ARCHIVES" / "moved_sample_packs_meta"
    stats: Dict[str, Any] = {"moved_packs": {}, "test_press_kits": 0, "vocal_destiny": {}, "serato_removed": 0}

    # 1. Move 4 pure one-shot / loop / vocal / Amen Break packs to MPC-Sample/Samples/
    pure_moves = [
        ("araabMUZIK - Essentials Vol 2", smp_root / "05_DRUM_KITS_&_ONE_SHOTS" / "araabMUZIK - Essentials Vol 2"),
        ("Zenhiser - Lofi Hip Hop", smp_root / "01_BOOM_BAP_&_LOFI" / "Zenhiser - Lofi Hip Hop"),
        ("Sample Magic - Dubbed Vocals", smp_root / "07_VOCALS_&_CHOPS" / "Sample Magic - Dubbed Vocals"),
        ("Rhythm Lab - Ultimate Amen Breaks", smp_root / "03_ELECTRONIC_HOUSE_DNB" / "Rhythm Lab - Ultimate Amen Breaks"),
    ]
    for pack_name, dst_dir in pure_moves:
        src_dir = exp_root / pack_name
        if not src_dir.is_dir():
            continue
        _archive_metadata_files(src_dir, meta_archive / pack_name)
        expected = _count_clean_audio_files(src_dir, include_txt=True)
        copied = _copy_clean_audio_tree(src_dir, dst_dir, include_txt=True)
        actual = _count_clean_audio_files(dst_dir, include_txt=True)
        assert expected > 0 and copied == expected and actual >= expected, (
            f"Count mismatch moving {pack_name}: expected={expected}, copied={copied}, actual={actual}"
        )
        shutil.rmtree(src_dir)
        stats["moved_packs"][pack_name] = {"wav_and_txt": copied, "dest": str(dst_dir)}

    # 2. Test Press - DnB Textures 2: move one_shots & loops to Samples/, keep 3 clean Beatmaker kits
    tp_src = exp_root / "Test Press - DnB Textures 2"
    tp_dst = smp_root / "03_ELECTRONIC_HOUSE_DNB" / "Test Press - DnB Textures 2"
    if tp_src.is_dir():
        tp_moved = 0
        for sub_name in ("one_shots", "loops"):
            sub_dir = tp_src / sub_name
            if sub_dir.is_dir():
                exp_n = _count_clean_audio_files(sub_dir, include_txt=False)
                cpy_n = _copy_clean_audio_tree(sub_dir, tp_dst / sub_name, include_txt=False)
                assert cpy_n == exp_n
                tp_moved += cpy_n
                shutil.rmtree(sub_dir)
        stats["moved_packs"]["Test Press - DnB Textures 2 (one_shots+loops)"] = {"wavs": tp_moved, "dest": str(tp_dst)}

        # Rebuild Beatmaker kits with exact non-truncated names
        bm_root = tp_src / "beatmaker_kits"
        prev_dir = tp_src / "[Previews]"
        if prev_dir.is_dir():
            for f in list(prev_dir.glob("*.wav")):
                f.unlink()
        if bm_root.is_dir():
            for kit_dir in sorted(bm_root.iterdir()):
                if not kit_dir.is_dir() or kit_dir.name.startswith("."):
                    continue
                kit_name = kit_dir.name
                # Remove any prior generated .xpm/.xpj/_[ProjectData] (including truncated ones)
                for old in list(kit_dir.glob("*.xpm")) + list(kit_dir.glob("*.xpj")):
                    old.unlink()
                for sub in list(kit_dir.iterdir()):
                    if sub.is_dir() and sub.name.endswith("_[ProjectData]"):
                        shutil.rmtree(sub, ignore_errors=True)

                wavs = sorted(w for w in kit_dir.glob("*.wav") if not w.name.startswith("."))
                if not wavs:
                    continue
                pdata_dir = kit_dir / f"{kit_name}_[ProjectData]"
                pdata_dir.mkdir(parents=True, exist_ok=True)
                kit_bpm = float(hkb.infer_kit_bpm(f"{kit_name} {wavs[0].name}", fallback=174.0))

                pads_xpm: Dict[int, Dict[str, Any]] = {}
                trk = tpl.clone_track()
                trk["name"] = kit_name
                trk["volume"] = 0.7079457640647888
                trk["pan"] = 0.5
                trk["program"]["name"] = kit_name
                trk["program"]["type"] = 0
                acvs_insts = trk["program"]["drum"]["instruments"]
                for ai in acvs_insts:
                    hkb._reset_xpj_instrument_slot(ai)

                linked_samples: List[Dict[str, Any]] = []
                for pad_num, wav_p in enumerate(wavs[:64], 1):
                    rme._ensure_sample_in_dir(wav_p, pdata_dir)
                    wf = wav_p.name
                    n_frames = hkb._get_wav_frames(wav_p)
                    stype = hkb.detect_sound_type(wf)
                    vol = float(hkb.compute_smart_pad_volume(stype, wav_p)["volume"])
                    mute = int(hkb.default_mute_group(stype))
                    oneshot = stype not in ("MELODY_LOOP", "PAD", "VOCAL", "LOOP")
                    pads_xpm[pad_num] = {
                        "sample_file": wf,
                        "sample_name": wav_p.stem,
                        "source_path": str(wav_p),
                        "n_frames": n_frames,
                        "sound_type": stype,
                        "volume": vol,
                        "pan": 0.5,
                        "tune": 0,
                        "mute_group": mute,
                        "trigger_mode": "oneshot" if oneshot else "noteon",
                        "monophonic": True,
                        "key_track": False,
                    }
                    ai = acvs_insts[pad_num - 1]
                    ai["monophonic"] = True
                    ai["polyphony"] = 1
                    ai["whichMuteGroup"] = mute
                    ai["triggerMode"] = 0 if oneshot else 2
                    ai["mixable"]["volume"] = vol
                    ai["mixable"]["pan"] = 0.5
                    ai["mixable"]["muteGroup"] = mute
                    ai["synthSection"]["ampEnvelope"]["OneShot"] = {"value0": oneshot}
                    lay0 = ai["layersv"][0]
                    lay0["active"] = True
                    lay0["mute"] = False
                    lay0["sampleFile"] = wf
                    lay0["sampleName"] = wav_p.stem
                    lay0["sliceIndex"] = 129
                    lay0["keyTrackEnable"] = False
                    lay0["volume"] = {"gainCoefficient": 1.0, "controlValue": 1.0, "law": 1}
                    lay0["sliceInfo"] = {
                        "Start": 0, "End": int(n_frames), "LoopStart": 0, "LoopMode": 0,
                        "PulsePosition": 0, "LoopCrossfadeLength": 0, "LoopCrossfadeType": 0,
                        "TailLength": 0.0, "TailLoopPosition": 0.5,
                    }
                    linked_samples.append({
                        "version": 1, "name": wav_p.stem, "path": wf, "loadImpl": 0,
                        "metadata": {"tempo": kit_bpm, "rootNote": 60, "tune": 0.0, "key": "C Major"},
                    })
                trk["samples"] = linked_samples
                tpl.write_fast_xpm(kit_name, pads_xpm, kit_dir / f"{kit_name}.xpm")
                rme.write_acvs_project(
                    kit_dir / f"{kit_name}.xpj", [trk], [], tpl,
                    master_tempo=kit_bpm, master_tempo_enabled=False,
                )
                prev_dir.mkdir(parents=True, exist_ok=True)
                _copy_if_needed(wavs[0], prev_dir / f"{kit_name}.wav")
                stats["test_press_kits"] += 1

    # 3. Vocal Destiny: keep 2 Bonus kits + .sxq, move vocal/melodic samples to Samples/
    vd_src = exp_root / "Vocal Destiny"
    vd_dst = smp_root / "07_VOCALS_&_CHOPS" / "Vocal Destiny"
    if vd_src.is_dir():
        bonus_stems = {"NeoSoul-Kit-Marie Bonus 1 Eb 94", "NeoSoul-Kit-Marie Bonus 2 Dm 119"}
        bonus_wavs_low: set[str] = set()
        for bstem in bonus_stems:
            xpm_p = vd_src / f"{bstem}.xpm"
            if xpm_p.is_file():
                root = ET.fromstring(xpm_p.read_bytes())
                for lay in root.findall(".//Layer"):
                    if (lay.findtext("Active") or "").lower() == "false":
                        continue
                    # IMPORTANT: keep trailing spaces like "... Sunlight Shaker "
                    sn = (lay.findtext("SampleName") or "").rstrip("\r\n")
                    sf = (lay.findtext("SampleFile") or "").strip()
                    ref = sn if sn.strip() else sf
                    if ref:
                        low = (ref if ref.lower().endswith(".wav") else f"{ref}.wav").lower()
                        bonus_wavs_low.add(low)

        vd_xpm_archive = card_root / "_RAW_SOURCE_ARCHIVES" / "vocal_destiny_vocal_banks_xpm"
        vd_xpm_archive.mkdir(parents=True, exist_ok=True)

        removed_kits = 0
        for item in sorted(vd_src.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_file() and item.suffix.lower() == ".xpm" and item.stem not in bonus_stems:
                _copy_if_needed(item, vd_xpm_archive / item.name)
                item.unlink()
                xpj_pair = vd_src / f"{item.stem}.xpj"
                if xpj_pair.is_file():
                    xpj_pair.unlink()
                pd_pair = vd_src / f"{item.stem}_[ProjectData]"
                if pd_pair.is_dir():
                    shutil.rmtree(pd_pair, ignore_errors=True)
                removed_kits += 1

        # Clean previews not belonging to the 2 Bonus kits
        vd_prev = vd_src / "[Previews]"
        if vd_prev.is_dir():
            for pf in list(vd_prev.iterdir()):
                if pf.is_file() and not pf.name.startswith("."):
                    if not any(pf.name.startswith(bs) for bs in bonus_stems):
                        pf.unlink()

        moved_vocals = 0
        copied_shared_vocals = 0
        for item in sorted(vd_src.iterdir()):
            if not item.is_file() or item.name.startswith(".") or item.suffix.lower() != ".wav":
                continue
            low = item.name.lower()
            is_vocal_or_melody = ("vocal" in low) or ("loop" in low)
            if low not in bonus_wavs_low:
                cat = _categorize_vocal_destiny_wav(item.name)
                dst_wav = vd_dst / cat / item.name
                dst_wav.parent.mkdir(parents=True, exist_ok=True)
                _copy_if_needed(item, dst_wav)
                item.unlink()
                moved_vocals += 1
            elif is_vocal_or_melody:
                cat = _categorize_vocal_destiny_wav(item.name)
                dst_wav = vd_dst / cat / item.name
                dst_wav.parent.mkdir(parents=True, exist_ok=True)
                _copy_if_needed(item, dst_wav)
                copied_shared_vocals += 1

        stats["vocal_destiny"] = {
            "archived_and_removed_vocal_kits": removed_kits,
            "bonus_wavs_preserved": len(bonus_wavs_low),
            "moved_to_samples": moved_vocals,
            "copied_shared_vocals_to_samples": copied_shared_vocals,
        }

    # 4. Serato Studio - Artist Collection: remove the 4 artificial WAV-gap programs
    serato = exp_root / "Serato Studio - Artist Collection"
    if serato.is_dir():
        art_targets = [
            serato / "Bonus_Loops_&_Shots" / "Bonus_Loops_&_Shots_V1",
            serato / "Bonus_Loops_&_Shots" / "Bonus_Loops_&_Shots_V2",
            serato / "Bonus_Loops_&_Shots" / "Bonus_Loops_&_Shots_V3",
            serato / "Core" / "Sets_Audio" / "Sets_Audio",
        ]
        for base in art_targets:
            removed_any = False
            for ext in (".xpm", ".xpj"):
                p = base.with_suffix(ext)
                if p.is_file():
                    p.unlink()
                    removed_any = True
            pd = base.parent / f"{base.name}_[ProjectData]"
            if pd.is_dir():
                shutil.rmtree(pd, ignore_errors=True)
                removed_any = True
            if removed_any:
                stats["serato_removed"] += 1

    return stats


# ---------------------------------------------------------------------------
# Part B: Bolero & Ranchera Boom Bap v2 Engine (Downbeat/Chord-Locked + atem/slic)
# ---------------------------------------------------------------------------

FLAT_TO_SHARP_NOTE: Dict[str, str] = {
    "C": "C", "C#": "C#", "Db": "C#",
    "D": "D", "D#": "D#", "Eb": "D#",
    "E": "E", "F": "F", "F#": "F#", "Gb": "F#",
    "G": "G", "G#": "G#", "Ab": "G#",
    "A": "A", "A#": "A#", "Bb": "A#", "B": "B",
}


def _parse_bolero_filename(filename: str) -> Dict[str, Any]:
    m = re.match(
        r"Astro1Deep\s*-\s*(\d+)\s+(.+?)\s+\[([A-G][b#]?m?)\s+(\d+)BPM\s+(\d)-(\d)\s+Mono\]\.wav$",
        filename,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"Unexpected Bolero filename format: {filename}")
    idx_str, title, key_short, bpm_str, num_str, den_str = m.groups()
    is_min = key_short.endswith("m")
    root_name = key_short[:-1] if is_min else key_short
    full_key = f"{root_name} {'Minor' if is_min else 'Major'}"
    sharp_note = FLAT_TO_SHARP_NOTE.get(root_name, "C")
    scale_name = "Natural Minor" if is_min else "Major"
    midi_root = 60 + NOTE_TO_SEMITONE.get(root_name, 0)
    return {
        "index": idx_str,
        "stem": FULL_TRACK_STEMS.get(idx_str, f"A1D_{idx_str}_{key_short}_{bpm_str}BPM"),
        "title": title,
        "key_short": key_short,
        "full_key": full_key,
        "sharp_note": sharp_note,
        "scale_name": scale_name,
        "midi_root": midi_root,
        "nominal_bpm": float(bpm_str),
        "meter_num": int(num_str),
        "meter_den": int(den_str),
    }


def _slice_json_entry(
    start_frame: int, end_frame: int, pulse_pos: int = 0, *, crossfade: int = 0
) -> Dict[str, Any]:
    return {
        "Start": int(start_frame),
        "End": int(end_frame),
        "LoopStart": int(start_frame),
        "LoopMode": 0,
        "PulsePosition": int(pulse_pos),
        "LoopCrossfadeLength": int(crossfade),
        "LoopCrossfadeType": 0,
        "TailLength": 0.0,
        "TailLoopPosition": 0.5,
    }


def _pack_riff_chunk(cid: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if (len(payload) & 1) else b""
    return cid + struct.pack("<I", len(payload)) + payload + pad


def _akai_smpl_chunk(n_frames: int, root_note: int = 60) -> bytes:
    """94-byte `smpl` chunk exactly as the MPC Sample (ACVS 1.3.0.12) writes it."""
    last = max(0, int(n_frames) - 1)
    std = struct.pack(
        "<9I6I",
        0x01000047, 0x5E, 22675, int(root_note), 0, 25, 0, 1, 0,
        0, 0, 0, last, 0, 0,
    )
    trailer = (
        struct.pack("<HH", 3, int(root_note)) + b"\x00" * 10
        + struct.pack("<I", last) + b"\x00\x00\xff\xff\xff\xff" + b"\x00" * 9 + b"\x3f"
    )
    blob = std + trailer
    assert len(blob) == 94
    return blob


def _parse_wav_core(raw: bytes) -> Tuple[bytes, bytes, Dict[bytes, bytes]]:
    """Return (fmt_body, data_body, other_chunks) tolerating truncated tails."""
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("Not a valid RIFF WAVE file")
    fmt_body = b""
    data_body = b""
    others: Dict[bytes, bytes] = {}
    pos = 12
    while pos + 8 <= len(raw):
        cid = raw[pos : pos + 4]
        csz = struct.unpack_from("<I", raw, pos + 4)[0]
        body = raw[pos + 8 : min(len(raw), pos + 8 + csz)]
        if cid == b"fmt ":
            fmt_body = body
        elif cid == b"data" and not data_body:
            data_body = body
        else:
            others.setdefault(cid, body)
        pos += 8 + csz + (csz & 1)
    if len(fmt_body) < 16 or not data_body:
        raise ValueError("WAV without fmt/data")
    align = max(1, int(struct.unpack_from("<H", fmt_body, 12)[0]))
    data_body = data_body[: (len(data_body) // align) * align]
    return fmt_body[:16] if struct.unpack_from("<H", fmt_body, 0)[0] in (1, 3) else fmt_body, data_body, others


def write_plain_wav(wav_path: Path, src_raw: Optional[bytes] = None) -> None:
    """Rewrite a WAV as the minimal `fmt ` + `data` layout every MPC loader accepts."""
    raw = src_raw if src_raw is not None else wav_path.read_bytes()
    fmt_body, data_body, _ = _parse_wav_core(raw)
    blob = bytearray(b"RIFF\x00\x00\x00\x00WAVE" + _pack_riff_chunk(b"fmt ", fmt_body) + _pack_riff_chunk(b"data", data_body))
    struct.pack_into("<I", blob, 4, len(blob) - 8)
    rme._atomic_write_bytes(wav_path, bytes(blob))


def embed_mpc_atem_slic(
    wav_path: Path,
    slices_frames: List[Tuple[int, int]],
    *,
    num_bars: int = 4,
    note_sharp: str = "C",
    scale_name: str = "Major",
    bpm: float = 0.0,
    beats_per_bar: int = 4,
) -> None:
    """Write the native MPC Sample sliced-WAV layout: fmt, atem, slic, smpl(94), meta(4), data.

    Mirrors WAVs saved by the MPC Sample itself (MPC-Sample/Projects): the `atem`
    chunk size is always even (a NUL is appended only when the JSON length is odd),
    no LIST/JUNK chunks, slice PulsePosition on the 960-PPQ bar grid.
    """
    raw = wav_path.read_bytes()
    fmt_body, data_body, _ = _parse_wav_core(raw)
    align = max(1, int(struct.unpack_from("<H", fmt_body, 12)[0]))
    n_frames = len(data_body) // align
    if n_frames <= 0:
        raise ValueError(f"WAV file has 0 PCM frames: {wav_path}")

    # Normalize consecutive non-overlapping slices covering [0 .. n_frames - 1]
    clean_slices: List[Tuple[int, int]] = []
    if slices_frames:
        starts = sorted({max(0, min(n_frames - 2, int(s[0]))) for s in slices_frames})
        if starts and starts[0] != 0:
            starts[0] = 0
        for idx, st in enumerate(starts):
            en = starts[idx + 1] if (idx + 1 < len(starts)) else (n_frames - 1)
            if en > st:
                clean_slices.append((st, en))
    if not clean_slices:
        clean_slices = [(0, n_frames - 1)]

    bars_eff = int(max(1, num_bars))
    total_pulses = float(bars_eff * max(1, int(beats_per_bar)) * 960)
    val0: Dict[str, Any] = {
        "defaultSlice": _slice_json_entry(0, n_frames - 1, 0, crossfade=-1),
        "numBars": bars_eff,
        "Num slices": len(clean_slices),
    }
    for idx, (st, en) in enumerate(clean_slices):
        pulse_pos = 0 if idx == 0 else max(1, int(round(st * total_pulses / float(max(1, n_frames)))))
        val0[f"Slice {idx}"] = _slice_json_entry(st, en, pulse_pos, crossfade=(-1 if idx == 0 else 0))

    atem_doc = {
        "version": 1,
        "value0": val0,
        "value1": {
            "version": 1,
            "note": FLAT_TO_SHARP_NOTE.get(note_sharp, note_sharp),
            "scale": scale_name,
        },
    }
    atem_bytes = json.dumps(atem_doc, indent=4).encode("utf-8")
    # Akai ACVS 1.3.0.12 invariant: `atem` chunk size is ALWAYS even; NUL is added inside csz only if odd.
    if len(atem_bytes) & 1:
        atem_bytes += b"\x00"

    slic_parts = [struct.pack("<HHH", 1, len(clean_slices), 0)]
    for st, en in clean_slices:
        slic_parts.append(struct.pack("<IIIH", int(st), int(en), int(st), 0))
    slic_bytes = b"".join(slic_parts)

    smpl_bytes = _akai_smpl_chunk(n_frames, root_note=60)
    bpm_eff = float(bpm) if bpm and bpm > 0 else max(40.0, min(220.0, (bars_eff * max(1, int(beats_per_bar)) * 60.0) / max(0.25, n_frames / float(SR_TARGET))))
    meta_bytes = struct.pack("<I", int(round(bpm_eff * 1000.0)))

    out_parts: List[bytes] = [
        b"RIFF",
        b"\x00\x00\x00\x00",
        b"WAVE",
        _pack_riff_chunk(b"fmt ", fmt_body),
        _pack_riff_chunk(b"atem", atem_bytes),
        _pack_riff_chunk(b"slic", slic_bytes),
        _pack_riff_chunk(b"smpl", smpl_bytes),
        _pack_riff_chunk(b"meta", meta_bytes),
        _pack_riff_chunk(b"data", data_body),
    ]

    full_blob = bytearray(b"".join(out_parts))
    struct.pack_into("<I", full_blob, 4, len(full_blob) - 8)
    rme._atomic_write_bytes(wav_path, bytes(full_blob))


def read_mpc_atem_slic(wav_path: Path) -> Dict[str, Any]:
    """Read and validate embedded `atem` and `slic` chunks from a WAV file."""
    raw = wav_path.read_bytes()
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"Invalid RIFF WAVE header: {wav_path}")
    riff_size = struct.unpack_from("<I", raw, 4)[0]
    pos = 12
    order: List[str] = []
    atem_obj: Optional[Dict[str, Any]] = None
    atem_null_terminated = False
    atem_even_size = False
    smpl_size = 0
    meta_size = 0
    slic_tuples: List[Tuple[int, int, int, int]] = []
    slic_header: Optional[Tuple[int, int, int]] = None
    align = 2
    n_frames = 0

    while pos + 8 <= len(raw):
        cid = raw[pos : pos + 4]
        csz = struct.unpack_from("<I", raw, pos + 4)[0]
        body = raw[pos + 8 : pos + 8 + csz]
        order.append(cid.decode("latin1", errors="replace"))
        if cid == b"fmt " and len(body) >= 16:
            align = max(1, int(struct.unpack_from("<H", body, 12)[0]))
        elif cid == b"data":
            n_frames = len(body) // align
        elif cid == b"atem":
            atem_even_size = (csz & 1) == 0
            atem_null_terminated = body.endswith(b"\x00")
            txt = body.rstrip(b"\x00 ").decode("utf-8")
            atem_obj = json.loads(txt)
        elif cid == b"smpl":
            smpl_size = csz
        elif cid == b"meta":
            meta_size = csz
        elif cid == b"slic" and len(body) >= 6:
            slic_header = struct.unpack_from("<HHH", body, 0)
            cnt = slic_header[1]
            for i in range(cnt):
                off = 6 + i * 14
                if off + 14 <= len(body):
                    slic_tuples.append(struct.unpack_from("<IIIH", body, off))
        pos += 8 + csz + (csz & 1)

    return {
        "riff_size_ok": (riff_size == len(raw) - 8),
        "chunk_order": order,
        "n_frames": n_frames,
        "atem": atem_obj,
        "atem_even_size": atem_even_size,
        "atem_null_terminated": atem_null_terminated,
        "smpl_size": smpl_size,
        "meta_size": meta_size,
        "slic_header": slic_header,
        "slic_slices": slic_tuples,
    }


def _estimate_bpm_autocorr(onset_curve: np.ndarray, hop_sec: float, nominal_bpm: float) -> float:
    """Zero-mean unbiased FFT autocorrelation in [62, 118] BPM with parabolic refinement."""
    x = onset_curve.astype(np.float64) - float(np.mean(onset_curve))
    n = len(x)
    if n < 32 or np.allclose(x, 0.0):
        return nominal_bpm
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    spec = np.fft.rfft(x, n=nfft)
    acf = np.fft.irfft(spec * np.conj(spec), n=nfft)[:n]
    denom = np.arange(n, 0, -1, dtype=np.float64)
    acf = acf / np.maximum(denom, 1.0)

    min_lag = max(2, int(np.floor(60.0 / (118.0 * hop_sec))))
    max_lag = min(n // 2, int(np.ceil(60.0 / (62.0 * hop_sec))))
    if max_lag <= min_lag + 2:
        return nominal_bpm

    region = acf[min_lag : max_lag + 1]
    peaks: List[Tuple[float, int]] = []
    for k in range(1, len(region) - 1):
        if region[k] >= region[k - 1] and region[k] >= region[k + 1]:
            peaks.append((float(region[k]), min_lag + k))
    if not peaks:
        best_lag = min_lag + int(np.argmax(region))
    else:
        peaks.sort(reverse=True)
        top_score = peaks[0][0]
        best_lag = peaks[0][1]
        for sc, lag in peaks:
            bpm_cand = 60.0 / (lag * hop_sec)
            if abs(bpm_cand - nominal_bpm) / max(nominal_bpm, 1.0) <= 0.10 and sc >= 0.65 * top_score:
                best_lag = lag
                break

    if 0 < best_lag < len(acf) - 1:
        y0, y1, y2 = acf[best_lag - 1], acf[best_lag], acf[best_lag + 1]
        d = y0 - 2.0 * y1 + y2
        shift = float(np.clip(0.5 * (y0 - y2) / d, -0.5, 0.5)) if abs(d) > 1e-12 else 0.0
    else:
        shift = 0.0
    bpm_est = 60.0 / ((best_lag + shift) * hop_sec)
    if abs(bpm_est - nominal_bpm) / max(nominal_bpm, 1.0) > 0.15:
        return nominal_bpm
    return round(float(bpm_est), 1)


def _snap_zero_crossing_backward(
    y: np.ndarray,
    idx: int,
    back_samples: int = 220,
    ahead_samples: int = 44,
) -> int:
    """Asymmetric zero-crossing snap matching Melodee `chop.h:87-105`.

    Looks up to 5 ms (220 samples) before `idx` and 1 ms (44 samples) after `idx`,
    penalizing forward distance 2x so a cut sits on or just before a hit and never
    blunts the transient attack.
    """
    n = len(y)
    if n == 0:
        return 0
    frame = int(max(0, min(n - 1, idx)))
    lo = max(0, frame - back_samples)
    hi = min(n - 1, frame + ahead_samples)

    def _cost(i: int) -> int:
        return (frame - i) if i <= frame else 2 * (i - frame)

    best = frame
    quiet = frame
    found = False
    for i in range(lo, hi + 1):
        m = float(y[i])
        q_val = float(y[quiet])
        if abs(m) < abs(q_val) or (abs(m) == abs(q_val) and _cost(i) < _cost(quiet)):
            quiet = i
        if i == 0:
            continue
        before = float(y[i - 1])
        if not (m == 0.0 or (before < 0.0) != (m < 0.0)):
            continue
        at = i if (m == 0.0 or abs(m) <= abs(before) or i - 1 < lo) else (i - 1)
        if not found or _cost(at) < _cost(best):
            best = at
            found = True
    return int(best if found else quiet)


def _write_boombap_wav_16bit(out_path: Path, seg_f32: np.ndarray, seed: int) -> float:
    """Write punch-preserving Boom Bap 16-bit PCM WAV (0.5 ms start de-click, 6 ms cosine tail, <= -0.80 dBFS)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.array(seg_f32, dtype=np.float64, copy=True)

    # 0.5 ms (22 samples) start ramp preserves 100% of Beat-1 transient attack; 6 ms (264 samples) end fade
    fin = min(22, len(audio) // 8)
    fout = min(264, len(audio) // 4)
    if fin > 1:
        t = np.linspace(0.0, np.pi / 2.0, fin)
        audio[:fin] *= np.sin(t) ** 2
    if fout > 1:
        t = np.linspace(0.0, np.pi / 2.0, fout)
        audio[-fout:] *= np.cos(t) ** 2

    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > TARGET_PEAK_LINEAR:
        audio *= TARGET_PEAK_LINEAR / peak

    rng = np.random.Generator(np.random.PCG64(seed))
    lsb = 1.0 / 32768.0
    dither = (rng.uniform(-0.5, 0.5, size=len(audio)) + rng.uniform(-0.5, 0.5, size=len(audio))) * lsb
    quant = np.clip(np.round((audio + dither) * 32767.0), -32768, 32767).astype(np.int16)

    sf.write(str(out_path), quant, SR_TARGET, subtype="PCM_16")
    return float(np.max(np.abs(quant)) / 32768.0)


def _compute_superflux(y: np.ndarray, sr: int, hop: int) -> np.ndarray:
    """Böck & Widmer SuperFlux spectral onset curve suppressing string/vocal vibrato."""
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=2048, hop_length=hop, n_mels=80, fmin=40.0, fmax=8000.0)
    log_mel = librosa.power_to_db(mel, ref=np.max)
    # Maximum filter across 3 frequency bins and 2 frame lag suppresses vibrato modulation
    ref_spec = maximum_filter1d(log_mel, size=3, axis=0)
    diff = np.zeros_like(log_mel)
    diff[:, 2:] = np.maximum(0.0, log_mel[:, 2:] - ref_spec[:, :-2])
    diff[:, 1] = np.maximum(0.0, log_mel[:, 1] - ref_spec[:, 0])
    return np.mean(diff, axis=0)


def _compute_chord_change_novelty(chroma: np.ndarray, beat_frames_est: int) -> np.ndarray:
    """Macro harmonic chord-change novelty comparing causal pre-window vs post-window CQT chroma."""
    n_frames = chroma.shape[1]
    w_prev = max(4, int(round(0.45 * beat_frames_est)))
    w_next = max(6, int(round(0.75 * beat_frames_est)))
    cnorm = librosa.util.normalize(chroma, norm=2, axis=0)
    nov = np.zeros(n_frames, dtype=np.float64)
    for t in range(w_prev, n_frames - w_next):
        c_pre = np.mean(cnorm[:, t - w_prev : t], axis=1)
        c_nxt = np.mean(cnorm[:, t : t + w_next], axis=1)
        n_pre = float(np.linalg.norm(c_pre))
        n_nxt = float(np.linalg.norm(c_nxt))
        if n_pre > 1e-6 and n_nxt > 1e-6:
            cos_sim = float(np.clip(np.dot(c_pre, c_nxt) / (n_pre * n_nxt), -1.0, 1.0))
            nov[t] = max(0.0, 1.0 - cos_sim)
    # Half-wave rectify local prominence so peaks land sharply at the chord onset
    smooth = np.convolve(nov, np.ones(5) / 5.0, mode="same")
    return np.maximum(0.0, nov - 0.55 * smooth)


def _snap_to_musical_attack(
    y: np.ndarray,
    target_sec: float,
    d_curve: np.ndarray,
    atk_env: np.ndarray,
    hop: int,
    sr: int,
    *,
    window_sec: float = 0.14,
    pre_roll_sec: float = 0.003,
) -> int:
    """Snap a beat/bar time to the exact onset foot of the local Bass/Chord/Attack peak + backward zero-crossing."""
    n_samples = len(y)
    n_frames = len(d_curve)
    if n_samples == 0 or n_frames == 0:
        return 0
    center_f = int(round(target_sec * sr / hop))
    win_f = max(2, int(round(window_sec * sr / hop)))
    lo_f = max(0, center_f - win_f)
    hi_f = min(n_frames - 1, center_f + win_f)

    # Distance-weighted search so we lock onto the true local attack without jumping to neighbors
    sub = d_curve[lo_f : hi_f + 1].copy()
    dists = np.abs(np.arange(lo_f, hi_f + 1) - center_f) / float(max(1, win_f))
    weighted = sub * (1.0 - 0.30 * dists)
    peak_f = lo_f + int(np.argmax(weighted))

    # If the local peak is weak (< 15% of local 90th percentile), keep target_sec
    local_ref = float(np.percentile(d_curve[max(0, center_f - 4 * win_f) : min(n_frames, center_f + 4 * win_f)], 90))
    if d_curve[peak_f] < 0.15 * max(local_ref, 1e-6):
        raw_sample = int(round(target_sec * sr))
        return _snap_zero_crossing_backward(y, raw_sample)

    # Backtrack from peak_f along high-resolution attack envelope (hop // 2 = 128 samples ~ 2.9 ms)
    sub_hop = hop // 2
    peak_af = min(len(atk_env) - 1, max(0, peak_f * 2))
    # Refine peak at sub_hop resolution within +-2 sub-frames
    af_lo = max(0, peak_af - 2)
    af_hi = min(len(atk_env) - 1, peak_af + 2)
    peak_af = af_lo + int(np.argmax(atk_env[af_lo : af_hi + 1]))

    peak_val = float(atk_env[peak_af])
    pre_lo = max(0, peak_af - 8)  # up to ~23 ms before peak
    floor_val = float(np.min(atk_env[pre_lo : peak_af + 1]))
    foot_thresh = floor_val + 0.18 * (peak_val - floor_val)

    foot_af = peak_af
    while foot_af > pre_lo and float(atk_env[foot_af - 1]) > foot_thresh and float(atk_env[foot_af - 1]) <= float(atk_env[foot_af]):
        foot_af -= 1

    foot_sample = int(foot_af * sub_hop) - int(round(pre_roll_sec * sr))
    foot_sample = max(0, min(n_samples - 1, foot_sample))
    return _snap_zero_crossing_backward(y, foot_sample)


def _compute_embedded_slices_for_region(
    y: np.ndarray,
    reg_s0: int,
    reg_s1: int,
    bars: int,
    meter: int,
    beat_samples_all: np.ndarray,
    d_curve: np.ndarray,
    atk_env: np.ndarray,
) -> List[Tuple[int, int]]:
    """Compute 16 (or 12/8/6) Boom Bap `atem`/`slic` slice regions inside `[reg_s0, reg_s1]`."""
    n_reg = reg_s1 - reg_s0
    if n_reg <= 2048:
        return [(0, max(1, n_reg - 1))]

    # Filter tracked beats falling inside [reg_s0 - 0.15s, reg_s1 + 0.15s]
    tol = int(0.15 * SR_TARGET)
    local_beats = [int(b - reg_s0) for b in beat_samples_all if (reg_s0 - tol) <= b <= (reg_s1 + tol)]
    expected_beats = max(2, bars * meter)
    if len(local_beats) < expected_beats // 2:
        local_beats = [int(round(i * n_reg / float(expected_beats))) for i in range(expected_beats)]

    # Determine target cut positions (relative to reg_s0)
    cut_rel: List[int] = [0]
    min_gap = int(0.18 * SR_TARGET)  # minimum 180 ms per slice

    if meter == 4:
        if bars >= 8:
            # 16 slices = every 2 beats (half-bar)
            target_n = 16
            step_beats = max(1, len(local_beats) / float(target_n))
            raw_targets = [local_beats[min(len(local_beats) - 1, int(round(k * step_beats)))] for k in range(1, target_n)]
        elif bars == 4:
            # 16 slices = every 1 beat
            target_n = 16
            if len(local_beats) >= 16:
                raw_targets = [local_beats[k] for k in range(1, 16)]
            else:
                raw_targets = [int(round(k * n_reg / 16.0)) for k in range(1, 16)]
        else:
            # 2-bar loop -> 8 slices (every 1 beat)
            target_n = 8
            if len(local_beats) >= 8:
                raw_targets = [local_beats[k] for k in range(1, 8)]
            else:
                raw_targets = [int(round(k * n_reg / 8.0)) for k in range(1, 8)]
    else:
        # 3/4 Bolero-Vals / Ranchera
        if bars >= 8:
            # 16 slices = 2 per bar (Beat 1 downbeat + strongest mid-bar turnaround on Beat 2 or 3)
            raw_targets = []
            for b_idx in range(8):
                b1_pos = local_beats[b_idx * 3] if (b_idx * 3 < len(local_beats)) else int(round(b_idx * n_reg / 8.0))
                b_next = local_beats[(b_idx + 1) * 3] if ((b_idx + 1) * 3 < len(local_beats)) else (
                    n_reg if b_idx == 7 else int(round((b_idx + 1) * n_reg / 8.0))
                )
                if b_idx > 0:
                    raw_targets.append(b1_pos)
                # Pick stronger of Beat 2 (1/3 of bar) vs Beat 3 (2/3 of bar) in D[t]
                cand2 = b1_pos + (b_next - b1_pos) // 3
                cand3 = b1_pos + 2 * (b_next - b1_pos) // 3
                f2 = min(len(d_curve) - 1, max(0, (reg_s0 + cand2) // HOP))
                f3 = min(len(d_curve) - 1, max(0, (reg_s0 + cand3) // HOP))
                mid_pos = cand2 if float(d_curve[f2]) >= float(d_curve[f3]) else cand3
                raw_targets.append(mid_pos)
        elif bars == 4:
            # 12 slices = 1 per beat
            target_n = 12
            if len(local_beats) >= 12:
                raw_targets = [local_beats[k] for k in range(1, 12)]
            else:
                raw_targets = [int(round(k * n_reg / 12.0)) for k in range(1, 12)]
        else:
            # 2-bar 3/4 -> 6 slices (1 per beat)
            target_n = 6
            if len(local_beats) >= 6:
                raw_targets = [local_beats[k] for k in range(1, 6)]
            else:
                raw_targets = [int(round(k * n_reg / 6.0)) for k in range(1, 6)]

    for rt in raw_targets:
        abs_t = (reg_s0 + rt) / float(SR_TARGET)
        snapped_abs = _snap_to_musical_attack(
            y, abs_t, d_curve, atk_env, HOP, SR_TARGET, window_sec=0.10, pre_roll_sec=0.003
        )
        rel_s = snapped_abs - reg_s0
        if rel_s >= cut_rel[-1] + min_gap and (n_reg - rel_s) >= min_gap:
            cut_rel.append(int(rel_s))

    slices: List[Tuple[int, int]] = []
    for i, st in enumerate(cut_rel):
        en = cut_rel[i + 1] if (i + 1 < len(cut_rel)) else (n_reg - 1)
        if en > st:
            slices.append((int(st), int(en)))
    return slices


def analyze_boombap_bolero(
    wav_path: Path,
    meta: Dict[str, Any],
) -> Tuple[np.ndarray, float, List[Dict[str, Any]], List[Dict[str, Any]], np.ndarray, np.ndarray, np.ndarray]:
    """Full Boom Bap v2 MIR pipeline: Downbeat/Chord-Change locking, 4/8-bar DP, Inst/Vox & Boom Bap Loops."""
    y, sr = sf.read(str(wav_path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR_TARGET:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR_TARGET)
    dur = len(y) / float(SR_TARGET)

    # 1. Active audio span (-42 dBFS threshold)
    rms_all = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    thresh = 10.0 ** (-42.0 / 20.0)
    active_frames = np.where(rms_all >= thresh)[0]
    if len(active_frames) == 0:
        t_start_active, t_end_active = 0.0, dur
    else:
        t_start_active = max(0.0, float(active_frames[0] * HOP) / SR_TARGET - 0.015)
        t_end_active = min(dur, float(active_frames[-1] * HOP) / SR_TARGET + 0.25)

    # 2. HPSS + Tuning + CQT Chroma + MFCC
    y_harm, y_perc = librosa.effects.hpss(y, margin=2.0)
    tuning = float(librosa.estimate_tuning(y=y_harm, sr=SR_TARGET, bins_per_octave=36))
    chroma = librosa.feature.chroma_cqt(
        y=y_harm, sr=SR_TARGET, hop_length=HOP, bins_per_octave=36, tuning=tuning
    )
    mfcc = librosa.feature.mfcc(y=y, sr=SR_TARGET, n_mfcc=13, hop_length=HOP)

    # 3. Three Boom Bap Attack Curves: Bass (45-180 Hz), Macro Chord Change, and SuperFlux
    sos_bass = butter(2, [45.0 / (SR_TARGET / 2.0), 180.0 / (SR_TARGET / 2.0)], btype="bandpass", output="sos")
    y_bass = sosfiltfilt(sos_bass, y).astype(np.float32)
    rms_bass = librosa.feature.rms(y=y_bass, frame_length=1024, hop_length=HOP)[0]
    log_bass = 20.0 * np.log10(np.maximum(rms_bass, 1e-6))
    c_bass = np.maximum(0.0, np.diff(log_bass, prepend=log_bass[0]))

    c_sflux = _compute_superflux(y, SR_TARGET, HOP)
    beat_frames_nom = max(8, int(round((60.0 / max(meta["nominal_bpm"], 60.0)) * SR_TARGET / HOP)))
    c_chord = _compute_chord_change_novelty(chroma, beat_frames_nom)

    L_frames = min(len(c_bass), len(c_sflux), len(c_chord), len(rms_all), chroma.shape[1])

    def _p95_norm(v: np.ndarray) -> np.ndarray:
        sub = v[:L_frames].astype(np.float64)
        p95 = float(np.percentile(sub, 95)) if len(sub) else 1.0
        return np.clip(sub / max(p95, 1e-8), 0.0, 2.5)

    nbass = _p95_norm(c_bass)
    nchord = _p95_norm(c_chord)
    nsflux = _p95_norm(c_sflux)

    # Downbeat score D[t] (85% Chord + Contrabajo Bass pluck!) & Beat tracking envelope O[t]
    d_curve = 0.45 * nchord + 0.40 * nbass + 0.15 * nsflux
    o_curve = 0.35 * nsflux + 0.35 * nbass + 0.30 * nchord

    # High-resolution attack envelope (sub_hop = 128 ~ 2.9 ms) for exact onset-foot backtracking
    atk_env = librosa.feature.rms(y=y, frame_length=512, hop_length=HOP // 2)[0]

    a_f0 = int(t_start_active * SR_TARGET / HOP)
    a_f1 = max(a_f0 + 64, min(L_frames, int(t_end_active * SR_TARGET / HOP)))
    bpm_est = _estimate_bpm_autocorr(o_curve[a_f0:a_f1], HOP / float(SR_TARGET), meta["nominal_bpm"])

    _, beat_frames = librosa.beat.beat_track(
        onset_envelope=o_curve[:L_frames],
        sr=SR_TARGET,
        hop_length=HOP,
        start_bpm=bpm_est,
        tightness=110,
    )
    meter = int(meta["meter_num"])
    beat_dur = 60.0 / bpm_est
    if len(beat_frames) < meter * 4:
        beat_times = np.arange(t_start_active, t_end_active, beat_dur)
        beat_frames = np.clip((beat_times * SR_TARGET / HOP).astype(int), 0, L_frames - 1)
    else:
        beat_times = librosa.frames_to_time(beat_frames, sr=SR_TARGET, hop_length=HOP)

    # 4. Optimal Downbeat Phase phi* maximizing D[t] (Chord Change + Contrabajo Pluck in neighborhood +-2 frames)
    d_local_max = maximum_filter1d(d_curve, size=5)
    best_phi, best_sc = 0, -1e9
    for phi in range(meter):
        b_idx = beat_frames[phi::meter]
        sc = float(np.mean(d_local_max[b_idx])) if len(b_idx) else -1e9
        if sc > best_sc:
            best_sc, best_phi = sc, phi

    # Snap every tracked beat to its exact musical attack foot
    snap_win = min(0.14, 0.28 * beat_dur)
    beat_samples_list: List[int] = []
    for bt in beat_times:
        s_pos = _snap_to_musical_attack(
            y, float(bt), d_curve, atk_env, HOP, SR_TARGET, window_sec=snap_win, pre_roll_sec=0.003
        )
        if not beat_samples_list or s_pos > beat_samples_list[-1] + int(0.25 * beat_dur * SR_TARGET):
            beat_samples_list.append(s_pos)
    beat_samples_all = np.array(beat_samples_list, dtype=np.int64)

    raw_downbeats: List[float] = [float(beat_times[k]) for k in range(best_phi, len(beat_times), meter)]
    bar_dur = float(meter) * beat_dur

    # Guard intro/outro without rigid mid-phrase slicing
    while raw_downbeats and (raw_downbeats[0] - t_start_active) >= 1.35 * bar_dur:
        raw_downbeats.insert(0, max(t_start_active, raw_downbeats[0] - bar_dur))
    if raw_downbeats:
        if (raw_downbeats[0] - t_start_active) >= 0.55 * bar_dur:
            raw_downbeats.insert(0, t_start_active)
        else:
            raw_downbeats[0] = t_start_active
    else:
        raw_downbeats = [t_start_active]

    end_boundaries_sec: List[float] = list(raw_downbeats)
    while (t_end_active - end_boundaries_sec[-1]) >= 1.35 * bar_dur:
        end_boundaries_sec.append(min(t_end_active, end_boundaries_sec[-1] + bar_dur))
    if (t_end_active - end_boundaries_sec[-1]) >= 0.45 * bar_dur:
        end_boundaries_sec.append(t_end_active)
    else:
        end_boundaries_sec[-1] = min(dur, max(t_end_active, end_boundaries_sec[-1]))

    # Snap every bar boundary to exact musical attack foot + backward zero-crossing
    bar_samples: List[int] = []
    min_bar_samples = int(0.55 * bar_dur * SR_TARGET)
    for b_idx, b_sec in enumerate(end_boundaries_sec):
        if b_idx == len(end_boundaries_sec) - 1:
            s_b = _snap_zero_crossing_backward(y, int(round(b_sec * SR_TARGET)))
        else:
            s_b = _snap_to_musical_attack(
                y, b_sec, d_curve, atk_env, HOP, SR_TARGET, window_sec=min(0.16, 0.28 * beat_dur), pre_roll_sec=0.003
            )
        if not bar_samples or s_b >= bar_samples[-1] + min_bar_samples:
            bar_samples.append(s_b)
    if len(bar_samples) < 5:
        step_s = int(round(bar_dur * SR_TARGET))
        bar_samples = list(range(int(t_start_active * SR_TARGET), int(t_end_active * SR_TARGET), max(1, step_s)))
        if bar_samples[-1] < int(t_end_active * SR_TARGET):
            bar_samples.append(int(t_end_active * SR_TARGET))

    N = len(bar_samples) - 1
    sync_frames = np.clip((np.array(bar_samples) / float(HOP)).astype(int), 0, L_frames - 1)

    # 5. Vocal vs. Instrumental Pocket Score per bar (3 Cues)
    sos_vox = butter(2, [350.0 / (SR_TARGET / 2.0), 3000.0 / (SR_TARGET / 2.0)], btype="bandpass", output="sos")
    y_vox_band = sosfiltfilt(sos_vox, y_harm).astype(np.float32)
    rms_vox = librosa.feature.rms(y=y_vox_band, hop_length=HOP)[0][:L_frames]
    rms_harm = librosa.feature.rms(y=y_harm, hop_length=HOP)[0][:L_frames]

    # Cue 1: Vocal formant energy ratio (350-3000 Hz vs total harmonic + overall)
    formant_ratio = rms_vox / np.maximum(rms_harm + 0.25 * rms_all[:L_frames], 1e-6)
    # Cue 2: Delta-MFCC 1..6 temporal variance (syllable formant rate)
    dmfcc = np.linalg.norm(np.diff(mfcc[1:7, :L_frames], axis=1, prepend=mfcc[1:7, :1]), axis=0)
    # Cue 3: 4.5-7.5 Hz vocal vibrato modulation envelope energy in vocal band
    env_sr = SR_TARGET / float(HOP)  # ~172.27 Hz
    sos_vib = butter(2, [4.5 / (env_sr / 2.0), 7.5 / (env_sr / 2.0)], btype="bandpass", output="sos")
    vib_env = np.abs(sosfiltfilt(sos_vib, rms_vox)) / np.maximum(rms_vox, 1e-5)

    bar_vocal_raw = np.zeros(N, dtype=np.float64)
    bar_downbeat_strength = np.zeros(N, dtype=np.float64)
    bar_harm_richness = np.zeros(N, dtype=np.float64)

    for b in range(N):
        f0, f1 = int(sync_frames[b]), max(int(sync_frames[b]) + 1, int(sync_frames[b + 1]))
        c1 = float(np.mean(formant_ratio[f0:f1])) * float(np.mean(rms_vox[f0:f1]))
        c2 = float(np.mean(dmfcc[f0:f1]))
        c3 = float(np.mean(vib_env[f0:f1])) * float(np.mean(rms_vox[f0:f1]))
        bar_vocal_raw[b] = 0.45 * c1 + 0.30 * c2 + 0.25 * c3
        bar_downbeat_strength[b] = float(np.max(d_curve[max(0, f0 - 2) : min(L_frames, f0 + 4)]))
        bar_harm_richness[b] = float(np.mean(nchord[f0:f1])) + 0.5 * float(np.std(chroma[:, f0:f1]))

    def _norm01(arr: np.ndarray) -> np.ndarray:
        if len(arr) == 0:
            return arr
        lo, hi = float(np.percentile(arr, 15)), float(np.percentile(arr, 85))
        if hi - lo < 1e-8:
            return np.zeros_like(arr)
        return np.clip((arr - lo) / (hi - lo), 0.0, 1.0)

    bar_vocal_score = _norm01(bar_vocal_raw)
    bar_db_norm = _norm01(bar_downbeat_strength)
    bar_hr_norm = _norm01(bar_harm_richness)

    # 6. Strict {4, 8}-Bar Structural DP with Complexity Penalty (6-9 sections max)
    chroma_b = librosa.util.sync(chroma[:, :L_frames], sync_frames, aggregate=np.median)[:, :N]
    mfcc_b = librosa.util.sync(mfcc[1:, :L_frames], sync_frames, aggregate=np.mean)[:, :N]
    rms_b = librosa.util.sync(rms_all[:L_frames][None, :], sync_frames, aggregate=np.mean)[0, :N]

    def _zscore(arr: np.ndarray) -> np.ndarray:
        std = float(np.std(arr))
        return (arr - float(np.mean(arr))) / (std if std > 1e-8 else 1.0)

    feat = np.vstack([
        librosa.util.normalize(chroma_b, axis=0),
        0.70 * librosa.util.normalize(mfcc_b, axis=0),
        0.45 * _zscore(bar_vocal_score)[None, :],
        0.35 * _zscore(rms_b)[None, :],
    ])
    feat = librosa.util.normalize(feat, axis=0)
    sim = feat.T @ feat

    def _cb_nov(k: int) -> np.ndarray:
        nv = np.zeros(N + 1, dtype=np.float64)
        for i in range(k, N - k + 1):
            same = float(sim[i - k : i, i - k : i].mean() + sim[i : i + k, i : i + k].mean())
            cross = float(sim[i - k : i, i : i + k].mean() + sim[i : i + k, i - k : i].mean())
            nv[i] = max(0.0, same - cross)
        return nv

    nov = 0.60 * _cb_nov(4) + 0.40 * _cb_nov(8)
    nov_norm = nov / (float(np.max(nov)) + 1e-8)

    dp = np.full(N + 1, -1e9, dtype=np.float64)
    prev = np.full(N + 1, -1, dtype=int)
    dp[0] = 0.0

    for end in range(4, N + 1):
        # Strictly {4, 8} for interior segments; final segment allows tail lengths if N % 4 != 0
        allowed_lengths = [4, 8] if end < N else [4, 6, 8, 10, 12]
        if end == N and (N % 4 != 0):
            for tail_l in range(4, 13):
                if tail_l not in allowed_lengths and dp[max(0, end - tail_l)] > -1e8:
                    allowed_lengths.append(tail_l)
        for length in allowed_lengths:
            st = end - length
            if st < 0 or dp[st] < -1e8:
                continue
            split_cost = -0.85 if end < N else 0.0
            len_bonus = 0.50 if length == 8 else (0.0 if length == 4 else -0.25)
            coherence = 0.30 * float(sim[st:end, st:end].mean())
            b_nov = (1.40 * float(nov_norm[end])) if (end < N and nov_norm[end] >= 0.40) else 0.0
            cand = dp[st] + split_cost + len_bonus + coherence + b_nov
            if cand > dp[end]:
                dp[end] = cand
                prev[end] = st

    if prev[N] < 0:
        bounds = list(range(0, N, 8))
        if N - bounds[-1] < 4 and len(bounds) > 1:
            bounds[-1] = N
        else:
            bounds.append(N)
    else:
        bounds = []
        cur = N
        while cur > 0:
            bounds.append(cur)
            cur = int(prev[cur])
        bounds.append(0)
        bounds.reverse()

    segments = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    while len(segments) > 9:
        # Merge adjacent pair with lowest boundary novelty (preferring merges that produce <= 8 bars)
        def _merge_key(i: int) -> float:
            combined_len = segments[i + 1][1] - segments[i][0]
            len_pen = 0.5 if combined_len > 8 else 0.0
            return float(nov_norm[segments[i][1]]) + len_pen

        m_idx = min(range(len(segments) - 1), key=_merge_key)
        merged = (segments[m_idx][0], segments[m_idx + 1][1])
        segments = segments[:m_idx] + [merged] + segments[m_idx + 2 :]

    # Label structural sections with role + Inst/Vox
    sec_vecs = [librosa.util.normalize(feat[:, st:en].mean(axis=1)[:, None], axis=0)[:, 0] for st, en in segments]
    prototypes: List[Tuple[str, np.ndarray]] = []
    part_names = ["PartA", "PartB", "PartC", "Bridge", "Theme", "VarA"]
    sections: List[Dict[str, Any]] = []

    for idx, (st, en) in enumerate(segments):
        s0 = int(bar_samples[st])
        s1 = int(bar_samples[en])
        t0 = s0 / float(SR_TARGET)
        t1 = s1 / float(SR_TARGET)
        mean_vox = float(np.mean(bar_vocal_score[st:en]))
        vox_tag = "Inst" if mean_vox <= 0.45 else "Vox"

        if idx == 0 and len(segments) >= 4:
            role = "Intro"
        elif idx == len(segments) - 1 and len(segments) >= 4:
            role = "Outro"
        elif vox_tag == "Inst" and idx > 0 and idx < len(segments) - 1:
            role = "Solo"
        else:
            vec = sec_vecs[idx]
            matched_lbl = None
            best_s = 0.0
            for pname, pvec in prototypes:
                sc = float(np.dot(vec, pvec))
                if sc >= 0.86 and sc > best_s:
                    best_s = sc
                    matched_lbl = pname
            if matched_lbl is None:
                pidx = len(prototypes)
                matched_lbl = part_names[pidx] if pidx < len(part_names) else f"Part{pidx + 1}"
                prototypes.append((matched_lbl, vec))
            role = matched_lbl

        mm, ss = divmod(int(round(t0)), 60)
        bars_cnt = en - st
        slices_rel = _compute_embedded_slices_for_region(
            y, s0, s1, bars_cnt, meter, beat_samples_all, d_curve, atk_env
        )
        sections.append({
            "sec_num": idx + 1,
            "bar_start": st + 1,
            "bar_end": en,
            "bars": bars_cnt,
            "s0": s0,
            "s1": s1,
            "t0": t0,
            "t1": t1,
            "duration": t1 - t0,
            "role": role,
            "vox_tag": vox_tag,
            "label": f"{role}_{vox_tag}",
            "vocal_score": round(mean_vox, 3),
            "time_tag": f"{mm}m{ss:02d}s",
            "slices": slices_rel,
        })

    # 7. Select Top 4-6 Non-Overlapping Instrumental Boom Bap Loops (4-bar preferred, 2-bar fallback)
    loop_cands: List[Tuple[float, int, int]] = []
    for win_bars in (4, 2):
        for st in range(0, N - win_bars + 1, 2):
            en = st + win_bars
            s0, s1 = int(bar_samples[st]), int(bar_samples[en])
            if (s1 - s0) < int(3.5 * SR_TARGET):
                continue
            v_sc = float(np.mean(bar_vocal_score[st:en]))
            db_sc = float(bar_db_norm[st])
            hr_sc = float(np.mean(bar_hr_norm[st:en]))
            len_pref = 0.12 if win_bars == 4 else 0.0
            score = 0.50 * (1.0 - v_sc) + 0.25 * db_sc + 0.25 * hr_sc + len_pref
            loop_cands.append((score, st, en))

    loop_cands.sort(reverse=True, key=lambda x: x[0])
    chosen_loops: List[Tuple[int, int, float]] = []
    used_bars: set[int] = set()
    for sc, st, en in loop_cands:
        if len(chosen_loops) >= 6:
            break
        if any(b in used_bars for b in range(st, en)):
            continue
        chosen_loops.append((st, en, sc))
        used_bars.update(range(st, en))

    chosen_loops.sort(key=lambda x: x[0])
    boombap_loops: List[Dict[str, Any]] = []
    for lidx, (st, en, sc) in enumerate(chosen_loops, 1):
        s0, s1 = int(bar_samples[st]), int(bar_samples[en])
        t0, t1 = s0 / float(SR_TARGET), s1 / float(SR_TARGET)
        bars_cnt = en - st
        mean_vox = float(np.mean(bar_vocal_score[st:en]))
        vtag = "Inst" if mean_vox <= 0.55 else "Pocket"
        mm, ss = divmod(int(round(t0)), 60)
        slices_rel = _compute_embedded_slices_for_region(
            y, s0, s1, bars_cnt, meter, beat_samples_all, d_curve, atk_env
        )
        boombap_loops.append({
            "loop_num": lidx,
            "pad_num": 41 + lidx,  # C10..C15 (Pads 42..47)
            "bar_start": st + 1,
            "bar_end": en,
            "bars": bars_cnt,
            "s0": s0,
            "s1": s1,
            "t0": t0,
            "t1": t1,
            "duration": t1 - t0,
            "vox_tag": vtag,
            "score": round(sc, 3),
            "time_tag": f"{mm}m{ss:02d}s",
            "slices": slices_rel,
        })

    return y, bpm_est, sections, boombap_loops, beat_samples_all, d_curve, atk_env


def stage_rebuild_bolero_structural_templates(card_root: Path, tpl: rme.AcvsTemplateLoader) -> Dict[str, Any]:
    exp_root = card_root / "Expansions"
    bol_dir = exp_root / "Astro1Deep - Bolero & Ranchera 1950s (Mono Vinyl)"
    if not bol_dir.is_dir():
        return {"songs_processed": 0}

    full_dir = bol_dir / "01_Full_Tracks_Mono_44k"
    sec_root = bol_dir / "02_Song_Sections"
    tpl_root = bol_dir / "03_Chop_Templates"
    prev_dir = bol_dir / "[Previews]"
    old_chop_kits = bol_dir / "02_Chop_Kits"

    for p in list(full_dir.glob("*.xpm")) + list(full_dir.glob("*.xpj")):
        p.unlink()
    for d in list(full_dir.iterdir()):
        if d.is_dir() and d.name.endswith("_[ProjectData]"):
            shutil.rmtree(d, ignore_errors=True)

    full_wavs = sorted(w for w in full_dir.iterdir() if w.is_file() and not w.name.startswith(".") and w.suffix.lower() == ".wav")
    assert len(full_wavs) > 0, f"No full WAVs found in {full_dir}"

    sec_root.mkdir(parents=True, exist_ok=True)
    tpl_root.mkdir(parents=True, exist_ok=True)
    prev_dir.mkdir(parents=True, exist_ok=True)

    summary_lines: List[str] = [
        "Astro1Deep - Boleros & Rancheras 1950s (Mono Vinyl - Boom Bap v2 Edition)",
        "Formato: WAV PCM 16-bit / 44.1 kHz / MONO (Peak <= -0.80 dBFS + Chunks nativos Akai atem/slic)",
        "Estructura:",
        "  - 01_Full_Tracks_Mono_44k/: Temas completos en WAV puro para Sample Browser",
        "  - 02_Song_Sections/: 6-9 secciones exactas de 4 u 8 compases (Inst/Vox) + BoomBap_Loops/",
        "      con 16 marcadores nativos atem/slic anclados al ataque real del acorde y downbeat",
        "  - 03_Chop_Templates/: Plantillas (.xpj + .xpm) con:",
        "      * Banco A (Pads 1-16): VACIO (para baterias Boom Bap)",
        "      * Banco B (Pads 17-32): VACIO (destino para CHOP -> TO PADS)",
        "      * Banco C (Pads 33-48): C01-C09 Secciones (Inst/Vox) | C10-C15 Loops Boom Bap 2-4b | C16 Full Track",
        "=" * 84,
        "",
    ]

    songs_processed = 0
    total_sections = 0
    total_loops = 0
    min_sec_dur = 999.0
    max_peak = 0.0

    for wpath in full_wavs:
        meta = _parse_bolero_filename(wpath.name)
        tstem = meta["stem"]
        y, bpm_est, sections, boombap_loops, _beats, _d, _atk = analyze_boombap_bolero(wpath, meta)
        assert 3 <= len(sections) <= 9, f"{tstem}: unexpected section count {len(sections)}"

        song_sec_dir = sec_root / tstem
        if song_sec_dir.is_dir():
            shutil.rmtree(song_sec_dir)
        song_sec_dir.mkdir(parents=True, exist_ok=True)
        loops_sub_dir = song_sec_dir / "BoomBap_Loops"
        loops_sub_dir.mkdir(parents=True, exist_ok=True)

        song_tpl_dir = tpl_root / tstem
        if song_tpl_dir.is_dir():
            shutil.rmtree(song_tpl_dir)
        song_tpl_dir.mkdir(parents=True, exist_ok=True)
        pdata_dir = song_tpl_dir / f"{tstem}_[ProjectData]"
        pdata_dir.mkdir(parents=True, exist_ok=True)

        pads_xpm: Dict[int, Dict[str, Any]] = {}
        trk = tpl.clone_track()
        trk["name"] = tstem
        trk["volume"] = 0.7079457640647888
        trk["pan"] = 0.5
        prog = trk["program"]
        prog["name"] = tstem
        prog["type"] = 0

        pad_colors = {f"value{i}": 0 for i in range(128)}
        acvs_insts = prog["drum"]["instruments"]
        for ai in acvs_insts:
            hkb._reset_xpj_instrument_slot(ai)

        linked_samples: List[Dict[str, Any]] = []
        preview_wav: Optional[Path] = None

        def _register_bank_c_pad(pad_1based: int, wav_file: Path, color_int: int) -> None:
            _copy_if_needed(wav_file, pdata_dir / wav_file.name)
            n_frames = hkb._get_wav_frames(wav_file)
            end_frame = max(0, int(n_frames) - 1)
            wf = wav_file.name
            norm_key = mpc_compat.normalize_key(meta["full_key"])
            pads_xpm[pad_1based] = {
                "sample_file": wf,
                "sample_name": wav_file.stem,
                "source_path": str(wav_file),
                "n_frames": n_frames,
                "slice_end": end_frame,
                "sound_type": "MELODY_LOOP",
                "volume": 0.7079457640647888,
                "pan": 0.5,
                "tune": 0,
                "mute_group": 1,
                "trigger_mode": "oneshot",
                "monophonic": True,
                "root_note": 0,
                "key_track": False,
            }
            ai = acvs_insts[pad_1based - 1]
            ai["monophonic"] = True
            ai["polyphony"] = 1
            ai["whichMuteGroup"] = 1
            ai["triggerMode"] = 0
            ai["mixable"]["volume"] = 0.7079457640647888
            ai["mixable"]["pan"] = 0.5
            ai["mixable"]["muteGroup"] = 1
            ai["synthSection"]["ampEnvelope"]["OneShot"] = {"value0": True}
            lay0 = ai["layersv"][0]
            lay0["active"] = True
            lay0["mute"] = False
            lay0["sampleFile"] = wf
            lay0["sampleName"] = wav_file.stem
            lay0["sampleStart"] = 0
            lay0["sampleEnd"] = end_frame
            lay0["sliceIndex"] = 129
            lay0["rootNote"] = 0
            lay0["keyTrackEnable"] = False
            lay0["volume"] = {"gainCoefficient": 1.0, "controlValue": 1.0, "law": 1}
            lay0["sliceInfo"] = {
                "Start": 0, "End": end_frame, "LoopStart": 0, "LoopMode": 0,
                "PulsePosition": 0, "LoopCrossfadeLength": -1, "LoopCrossfadeType": 0,
                "TailLength": 0.0, "TailLoopPosition": 0.5,
            }
            linked_samples.append({
                "version": 1,
                "name": wav_file.stem,
                "path": wf,
                "loadImpl": 0,
                "metadata": {
                    "tempo": float(bpm_est),
                    "rootNote": 60,
                    "tune": 0.0,
                    "key": norm_key,
                },
            })
            pad_colors[f"value{pad_1based - 1}"] = color_int

        sec_desc_list: List[str] = []
        full_track_sec_slices: List[Tuple[int, int]] = []
        meter = int(meta["meter_num"])

        # 1. Write C01..C09 Structural Sections (with native MPC atem/slic/smpl/meta)
        for sidx, sec in enumerate(sections):
            s0, s1 = int(sec["s0"]), int(sec["s1"])
            if s1 - s0 < int(4.0 * SR_TARGET):
                s1 = min(len(y), s0 + int(4.0 * SR_TARGET))
            seg_audio = y[s0:s1]
            sec_dur = len(seg_audio) / float(SR_TARGET)
            min_sec_dur = min(min_sec_dur, sec_dur)

            s_fname = f"{sec['sec_num']:02d}_{sec['label']}_{sec['bars']}b_{sec['time_tag']}.wav"
            seed = int.from_bytes(hashlib.blake2b(s_fname.encode(), digest_size=8).digest(), "little")

            sec_wav_standalone = song_sec_dir / s_fname
            pk = _write_boombap_wav_16bit(sec_wav_standalone, seg_audio, seed)
            max_peak = max(max_peak, pk)
            embed_mpc_atem_slic(
                sec_wav_standalone,
                sec["slices"],
                num_bars=int(sec["bars"]),
                note_sharp=meta["sharp_note"],
                scale_name=meta["scale_name"],
                bpm=float(bpm_est),
                beats_per_bar=meter,
            )

            tpl_wav = song_tpl_dir / s_fname
            _copy_if_needed(sec_wav_standalone, tpl_wav)

            if preview_wav is None and sec["vox_tag"] == "Inst":
                preview_wav = sec_wav_standalone
            elif sidx == 0 and preview_wav is None:
                preview_wav = sec_wav_standalone

            col = 0x2B95D6 if sec["vox_tag"] == "Inst" else 0xD9822B
            _register_bank_c_pad(33 + sidx, tpl_wav, col)
            total_sections += 1
            full_track_sec_slices.append((s0, s1))
            sec_desc_list.append(f"C{sec['sec_num']:02d}={sec['label']}({sec['bars']}b,{len(sec['slices'])}sl@{sec['time_tag']})")

        # 2. Write C10..C15 Top Instrumental Boom Bap Loops (with native MPC atem/slic/smpl/meta)
        loop_desc_list: List[str] = []
        for lp in boombap_loops:
            s0, s1 = int(lp["s0"]), int(lp["s1"])
            seg_audio = y[s0:s1]
            c_idx = lp["pad_num"] - 32  # 10..15
            l_fname = f"{c_idx:02d}_Loop{lp['loop_num']}_{lp['vox_tag']}_{lp['bars']}b_{lp['time_tag']}.wav"
            seed = int.from_bytes(hashlib.blake2b(l_fname.encode(), digest_size=8).digest(), "little")

            lp_wav_standalone = loops_sub_dir / l_fname
            pk = _write_boombap_wav_16bit(lp_wav_standalone, seg_audio, seed)
            max_peak = max(max_peak, pk)
            embed_mpc_atem_slic(
                lp_wav_standalone,
                lp["slices"],
                num_bars=int(lp["bars"]),
                note_sharp=meta["sharp_note"],
                scale_name=meta["scale_name"],
                bpm=float(bpm_est),
                beats_per_bar=meter,
            )

            tpl_lp_wav = song_tpl_dir / l_fname
            _copy_if_needed(lp_wav_standalone, tpl_lp_wav)
            _register_bank_c_pad(lp["pad_num"], tpl_lp_wav, 0xE6B800)  # Gold for Boom Bap Loops
            total_loops += 1
            loop_desc_list.append(f"C{c_idx:02d}=Loop{lp['loop_num']}_{lp['vox_tag']}({lp['bars']}b,{len(lp['slices'])}sl@{lp['time_tag']})")

        # 3. Pad 48 (C16): Full Track WAV with embedded structural section markers
        c16_fname = f"16_C16_Full_{tstem[4:]}.wav"
        c16_tpl_wav = song_tpl_dir / c16_fname
        full_peak = float(np.max(np.abs(y))) if len(y) else 0.0
        if full_peak <= TARGET_PEAK_LINEAR:
            _copy_if_needed(wpath, c16_tpl_wav)
            pk_full = full_peak
        else:
            full_seed = int.from_bytes(hashlib.blake2b(c16_fname.encode(), digest_size=8).digest(), "little")
            pk_full = _write_boombap_wav_16bit(c16_tpl_wav, y, full_seed)
        max_peak = max(max_peak, pk_full)
        embed_mpc_atem_slic(
            c16_tpl_wav,
            full_track_sec_slices,
            num_bars=sum(int(s["bars"]) for s in sections),
            note_sharp=meta["sharp_note"],
            scale_name=meta["scale_name"],
            bpm=float(bpm_est),
            beats_per_bar=meter,
        )
        _register_bank_c_pad(48, c16_tpl_wav, 0xC23030)  # Crimson for Full Track

        program_pads = {
            "Universal": {"value0": False},
            "Type": {"value0": 5},
            "universalPad": 0xD9822B,
            "pads": pad_colors,
            "UnusedPads": {"value0": 0},
            "PadsFollowTrackColour": {"value0": False},
        }
        prog["programPads"] = program_pads
        trk["samples"] = linked_samples

        pp_json = json.dumps({"ProgramPads-v2.10": program_pads}, indent=4)
        xpm_out = song_tpl_dir / f"{tstem}.xpm"
        tpl.write_fast_xpm(tstem, pads_xpm, xpm_out, program_pads_json=pp_json)
        _copy_if_needed(xpm_out, pdata_dir / f"{tstem}.xpm")

        seq_len_bars = 4
        empty_seq = [{
            "key": 0,
            "name": "Sequence 01",
            "bpm": float(bpm_est),
            "length_bars": seq_len_bars,
            "length_pulses": int(seq_len_bars * meter * 960),
            "beats_per_bar": meter,
            "beat_unit": int(meta["meter_den"]),
            "clips": {},
        }]
        rme.write_acvs_project(
            song_tpl_dir / f"{tstem}.xpj",
            [trk],
            empty_seq,
            tpl,
            master_tempo=float(bpm_est),
            master_tempo_enabled=False,
            project_key=mpc_compat.normalize_key(meta["full_key"]),
        )

        if preview_wav is not None:
            raw_prev = preview_wav.read_bytes()
            write_plain_wav(prev_dir / f"{tstem}.wav", src_raw=raw_prev)
            write_plain_wav(prev_dir / f"{tstem}.xpm.wav", src_raw=raw_prev)

        songs_processed += 1
        line = (
            f"#{meta['index']} {tstem} | {bpm_est:.1f} BPM ({meter}/{meta['meter_den']}) {meta['full_key']} | "
            f"{len(sections)} secs + {len(boombap_loops)} loops + C16 Full | "
            + ", ".join(sec_desc_list + loop_desc_list)
        )
        summary_lines.append(line)
        print(
            f"  [{songs_processed:02d}/{len(full_wavs):02d}] {tstem}: "
            f"{len(sections)} secs (C01-C{len(sections):02d}) + {len(boombap_loops)} loops (C10-C{9+len(boombap_loops):02d}) "
            f"({meter}/{meta['meter_den']} @ {bpm_est:.1f} BPM)"
        )

    if old_chop_kits.is_dir():
        shutil.rmtree(old_chop_kits)
    valid_stems = { _parse_bolero_filename(w.name)["stem"] for w in full_wavs }
    valid_prev_names = {f"{s}.wav" for s in valid_stems} | {f"{s}.xpm.wav" for s in valid_stems}
    for pf in list(prev_dir.iterdir()):
        if pf.is_file() and not pf.name.startswith(".") and pf.name not in valid_prev_names:
            pf.unlink()

    rme._atomic_write_bytes(bol_dir / "README_Astro1Deep_Tracklist.txt", ("\n".join(summary_lines) + "\n").encode("utf-8"))
    return {
        "songs_processed": songs_processed,
        "total_sections": total_sections,
        "total_loops": total_loops,
        "min_section_sec": round(min_sec_dur, 2),
        "max_peak_dbfs": round(20.0 * np.log10(max(max_peak, 1e-8)), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reorganize One-Shot/Loop packs & rebuild Bolero Chop Templates")
    parser.add_argument("--card", default="/Volumes/MPCSMPL", help="Mounted MPC SD card root")
    parser.add_argument("--bolero-only", action="store_true", help="Run only Part B (Bolero & Ranchera Boom Bap v2)")
    args = parser.parse_args()
    card_root = Path(args.card)
    if not card_root.is_dir():
        raise SystemExit(f"Card root not found: {card_root}")

    free_before = shutil.disk_usage(card_root).free / (1024 ** 3)
    print(f"Target card: {card_root} (free before: {free_before:.2f} GB)")
    tpl = rme.AcvsTemplateLoader()

    if not args.bolero_only:
        print("\n=== Part A: Reorganizing Pure One-Shot / Loop / Vocal / Amen-Break Packs ===")
        res_a = stage_reorganize_oneshots(card_root, tpl)
        print("Part A:", json.dumps(res_a, ensure_ascii=False))

    print("\n=== Part B: Rebuilding Astro1Deep Bolero & Ranchera Boom Bap v2 Bank-C Templates ===")
    res_b = stage_rebuild_bolero_structural_templates(card_root, tpl)
    print("Part B:", json.dumps(res_b, ensure_ascii=False))

    free_after = shutil.disk_usage(card_root).free / (1024 ** 3)
    print(f"\nDone. Free space on {card_root}: {free_after:.2f} GB")
    if free_after < 35.0:
        raise RuntimeError(f"Safety threshold breached: free space {free_after:.2f} GB < 35 GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
