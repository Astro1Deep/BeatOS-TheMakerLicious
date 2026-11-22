#!/usr/bin/env python3
"""Repair & normalize Akai MPC Sample Expansions, XPM/XPJ kits, XTD bundles, and SXQ sequences.

Ensures 100% compatibility across:
- Melodee (Project Browser `.xpj` ACVS 1.3.0.12 + Sample Browser `.xpm` XML)
- Akai MPC Sample Stock / SampQOL-OS (ACVS 1.3.0.12, lossless JSON floats, lengthPulses)
- BeatOS v3.8.0 catalog & SQLite index
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import hardware_kit_builder as hkb  # noqa: E402
import mpc_compat  # noqa: E402

ACVS_HEADER = "ACVS\n1.3.0.12\nSerialisableProjectData\njson\nLinux\n"
AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac", ".mp3"}
DEFAULT_MPC_TICKS_PER_QUARTER = 960
NOISE_STRINGS = {"All Ports", "Windows", "<none>", "MacOS", "Linux", "2147483647"}

# Standard packs that get companion .xpj + _[ProjectData] for every root .xpm kit
OFFICIAL_XPM_TO_XPJ_PACKS = [
    "80s Nostalgia",
    "Aquarius Earth (AKAINI)",
    "DJ Khalil (AKAINI)",
    "Marco Polo - BoomBap Essentials Vol 1",
    "Scott Storch Presents",
    "Vocal Destiny",
]

# Pure one-shot/loop/vocal sample libraries live cleanly in MPC-Sample/Samples/ rather than
# Expansions/ (managed by scripts/reorganize_samples_and_bolero_templates.py).
WAV_ONLY_PACKS: List[str] = []


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.stem}-", delete=False) as tf:
            tmp_path = Path(tf.name)
            tf.write(data)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, target)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _atomic_write_gzip_text(target: Path, text: str) -> None:
    payload = gzip.compress(text.encode("utf-8"), mtime=0)
    _atomic_write_bytes(target, payload)


def _backup_before_overwrite(file_path: Path, card_root: Path, backup_root: Path) -> None:
    """Save original file under _RAW_SOURCE_ARCHIVES/pre_repair_20261119/ once before editing."""
    if not file_path.is_file():
        return
    try:
        rel = file_path.resolve().relative_to(card_root.resolve())
    except ValueError:
        rel = Path(file_path.name)
    dst = backup_root / rel
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, dst)


def _norm_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _safe_kit_stem(name: str, limit: int = 48) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip(" ._-")
    return cleaned or "Kit"


def _compute_length_bars(max_tick: int, bar_pulses: int) -> int:
    if bar_pulses <= 0:
        bar_pulses = 3840
    raw_bars = max(1, (max_tick // bar_pulses) + 1)
    if raw_bars <= 2:
        return 2
    if raw_bars <= 4:
        return 4
    if raw_bars <= 8:
        return 8
    if raw_bars <= 16:
        return 16
    if raw_bars <= 32:
        return 32
    return min(128, ((raw_bars + 3) // 4) * 4)


def _make_acvs_note_event(tick: int, note_num: int, vel_127: int, length_pulses: int) -> Dict[str, Any]:
    vel_float = float(max(1, min(127, int(vel_127))) / 127.0)
    ev = {
        "version": 1,
        "time": int(max(0, tick)),
        "type": 3,
        "selected": False,
        "muted": False,
        "invented": False,
        "note": {
            "version": 1,
            "note": int(max(0, min(127, note_num))),
            "velocity": float(vel_float),
            "length": int(max(1, length_pulses)),
            "probability": 100,
            "ratchet": 1,
            "EnumCerealisationWrapper(selectedModifierType)": "Tuning (coarse)",
        },
    }
    for i in range(16):
        ev["note"][f"modifierValue{i}"] = 0.5 if i <= 5 else 0.0
        ev["note"][f"modifierActiveState{i}"] = False
    return ev


def _sanitize_acvs_event(ev: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(ev)
    out["time"] = int(max(0, int(out.get("time", 0))))
    note = out.get("note")
    if isinstance(note, dict):
        note["velocity"] = float(note.get("velocity", 1.0))
        note["length"] = int(max(1, int(note.get("length", 240))))
        for i in range(16):
            mk = f"modifierValue{i}"
            if mk in note:
                note[mk] = float(note[mk])
    return out


# ---------------------------------------------------------------------------
# 1. Akai .sxq Decoder (SMF + FF 7F Ga 0x10 / 0x11 proprietary records)
# ---------------------------------------------------------------------------

def _read_vlq(buf: bytes, idx: int) -> Tuple[int, int]:
    val = 0
    while idx < len(buf):
        b = buf[idx]
        idx += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return val, idx


def _extract_ga10_program_name(mdata: bytes) -> str:
    """Extract target program name from Akai Ga 0x10 track header across MPC 2.6..2.15."""
    if len(mdata) < 20:
        return ""
    ver = mdata[3]
    if ver == 0 and len(mdata) > 20:
        plen = mdata[19]
        if 20 + plen <= len(mdata):
            cand = mdata[20 : 20 + plen].decode("utf-8", errors="ignore").rstrip("\x00").strip()
            if cand and cand not in NOISE_STRINGS and all(32 <= ord(c) < 127 for c in cand):
                return cand[2:].strip() if cand.startswith("@ ") else cand

    # v1/v2 packets carry a 128-'1' note-map ASCII bitfield + zeros, then <len><program_name>
    search_start = 16
    zero_run = mdata.find(b"0000000000000000")
    if zero_run >= 0:
        search_start = zero_run + 16
    else:
        one_run = mdata.find(b"1111111111111111")
        if one_run >= 0:
            search_start = one_run
            while search_start < len(mdata) and mdata[search_start] in (48, 49):
                search_start += 1

    strs = [s.decode("utf-8", errors="ignore").strip() for s in re.findall(rb"[ -~]{3,}", mdata[search_start:])]
    for s in reversed(strs):
        if s in NOISE_STRINGS:
            continue
        if re.fullmatch(r"[01]+", s) or re.fullmatch(r"\d+", s):
            continue
        return s[2:].strip() if s.startswith("@ ") else s
    return ""


def decode_sxq(source: Path | bytes) -> Dict[str, Any]:
    """Decode an Akai .sxq sequence file (or raw bytes) into tempo, signature, and note lists per track."""
    raw = bytes(source) if isinstance(source, (bytes, bytearray, memoryview)) else Path(source).read_bytes()
    fallback_name = "Sequence" if isinstance(source, (bytes, bytearray, memoryview)) else Path(source).stem
    if raw[:4] != b"MThd" or len(raw) < 14:
        raise ValueError("Not an SMF/SXQ file")
    hlen = struct.unpack(">I", raw[4:8])[0]
    _fmt, ntrks, div = struct.unpack(">HHH", raw[8:14])
    scale = (float(DEFAULT_MPC_TICKS_PER_QUARTER) / float(div)) if div else 1.0
    pos = 8 + hlen

    seq_name = ""
    bpm = 120.0
    beats_per_bar = 4
    beat_unit = 4
    tracks: List[Dict[str, Any]] = []

    for ti in range(ntrks):
        if pos + 8 > len(raw) or raw[pos : pos + 4] != b"MTrk":
            break
        tlen = struct.unpack(">I", raw[pos + 4 : pos + 8])[0]
        body = raw[pos + 8 : pos + 8 + tlen]
        pos += 8 + tlen

        idx = 0
        tick = 0
        running = 0
        tname = ""
        prog_name = ""
        ga_notes: List[Tuple[int, int, int, int]] = []
        midi_notes: List[Tuple[int, int, int, int]] = []
        active_midi: Dict[Tuple[int, int], Tuple[int, int]] = {}

        while idx < len(body):
            delta, idx = _read_vlq(body, idx)
            tick += delta
            if idx >= len(body):
                break
            st = body[idx]
            if st < 0x80:
                st = running
            else:
                idx += 1
                if st < 0xF0:
                    running = st

            if st == 0xFF:
                if idx >= len(body):
                    break
                mtype = body[idx]
                idx += 1
                mlen, idx = _read_vlq(body, idx)
                mdata = body[idx : idx + mlen]
                idx += mlen
                if mtype == 0x03:
                    s = mdata.decode("utf-8", errors="replace").rstrip("\x00").strip()
                    if ti == 0 and not seq_name:
                        seq_name = s
                    elif ti > 0 and not tname:
                        tname = s
                elif mtype == 0x51 and len(mdata) == 3:
                    us = (mdata[0] << 16) | (mdata[1] << 8) | mdata[2]
                    if us > 0:
                        bpm = 60_000_000.0 / float(us)
                elif mtype == 0x58 and len(mdata) >= 2:
                    beats_per_bar = max(1, int(mdata[0]))
                    beat_unit = 1 << int(mdata[1])
                elif mtype == 0x7F and len(mdata) >= 4 and mdata[:2] == b"Ga":
                    sub = mdata[2]
                    if sub == 0x10 and not prog_name:
                        prog_name = _extract_ga10_program_name(mdata)
                    elif sub == 0x11 and len(mdata) >= 14:
                        note_num = int(mdata[4])
                        vel = max(1, min(127, int(mdata[5])))
                        dur = max(1, int(struct.unpack_from("<I", mdata, 10)[0]))
                        if 0 <= note_num <= 127:
                            ga_notes.append(
                                (int(round(tick * scale)), note_num, vel, int(round(dur * scale)))
                            )
            elif st in (0xF0, 0xF7):
                slen, idx = _read_vlq(body, idx)
                idx += slen
            else:
                hi = st & 0xF0
                ch = st & 0x0F
                if hi in (0xC0, 0xD0):
                    idx += 1
                elif hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    if idx + 1 >= len(body):
                        break
                    d1 = body[idx]
                    d2 = body[idx + 1]
                    idx += 2
                    if hi == 0x90 and d2 > 0:
                        active_midi[(ch, d1)] = (tick, d2)
                    elif hi == 0x80 or (hi == 0x90 and d2 == 0):
                        if (ch, d1) in active_midi:
                            st_t, vel = active_midi.pop((ch, d1))
                            midi_notes.append(
                                (
                                    int(round(st_t * scale)),
                                    int(d1),
                                    int(vel),
                                    max(1, int(round((tick - st_t) * scale))),
                                )
                            )
                else:
                    break

        notes = ga_notes if ga_notes else midi_notes
        if notes:
            tracks.append({"track_name": tname, "program_name": prog_name, "notes": notes})

    bar_pulses = int(round(beats_per_bar * DEFAULT_MPC_TICKS_PER_QUARTER * (4.0 / float(beat_unit))))
    max_tick = max((n[0] for tr in tracks for n in tr["notes"]), default=0)
    length_bars = _compute_length_bars(max_tick, bar_pulses)
    return {
        "name": seq_name or fallback_name,
        "bpm": round(float(bpm), 2),
        "beats_per_bar": int(beats_per_bar),
        "beat_unit": int(beat_unit),
        "bar_pulses": int(bar_pulses),
        "length_bars": int(length_bars),
        "length_pulses": int(length_bars * bar_pulses),
        "tracks": tracks,
    }


# ---------------------------------------------------------------------------
# 2. Sample Resolution & Template Caching
# ---------------------------------------------------------------------------

def _build_dir_sample_index(search_dirs: Iterable[Path]) -> Dict[str, Path]:
    """Case-insensitive filename index prioritized in the order of `search_dirs`."""
    idx: Dict[str, Path] = {}
    for sdir in search_dirs:
        if not sdir or not sdir.is_dir():
            continue
        try:
            for item in sdir.iterdir():
                if not item.is_file() or item.name.startswith("."):
                    continue
                low = item.name.lower()
                if low not in idx:
                    idx[low] = item
                stem_low = item.stem.lower()
                if item.suffix.lower() in AUDIO_EXTS and stem_low not in idx:
                    idx[stem_low] = item
        except OSError:
            continue
    return idx


def _resolve_from_index(ref: str, sindex: Dict[str, Path]) -> Optional[Path]:
    if not ref or not ref.strip():
        return None
    name = ref.replace("\\", "/").rsplit("/", 1)[-1].strip()
    low = name.lower()
    if low in sindex:
        return sindex[low]
    if not any(low.endswith(ext) for ext in AUDIO_EXTS):
        for ext in (".wav", ".aif", ".aiff", ".flac"):
            if (low + ext) in sindex:
                return sindex[low + ext]
    stem_low = Path(name).stem.lower()
    return sindex.get(stem_low)


def _ensure_sample_in_dir(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    try:
        src_sz = src.stat().st_size
    except OSError:
        src_sz = -1
    if not dst.is_file() or (src_sz >= 0 and dst.stat().st_size != src_sz):
        shutil.copy2(src, dst)
    return dst


def _normalize_float(val: Any, default: float = 0.0) -> float:
    try:
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return float(default)
        return float(val)
    except (TypeError, ValueError):
        return float(default)


def _normalize_int(val: Any, default: int = 0) -> int:
    try:
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return int(default)
        return int(round(float(val)))
    except (TypeError, ValueError):
        return int(default)


def _normalize_bool(val: Any, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
    return bool(default)


class AcvsTemplateLoader:
    """Caches deserialized template_project.xpj and template_drum.xpm XML/JSON payloads."""

    def __init__(self) -> None:
        tpl_xpj = REPO_ROOT / "templates" / "template_project.xpj"
        raw = gzip.decompress(tpl_xpj.read_bytes()).decode("utf-8")
        jidx = raw.index("{")
        self.xpj_header = raw[:jidx]
        self.xpj_payload = json.loads(raw[jidx:])

        tpl_xpm = REPO_ROOT / "templates" / "template_drum.xpm"
        self.xpm_tree = ET.parse(str(tpl_xpm))

    def clone_payload(self) -> Dict[str, Any]:
        return copy.deepcopy(self.xpj_payload)

    def clone_track(self) -> Dict[str, Any]:
        return copy.deepcopy(self.xpj_payload["data"]["tracks"][0])

    def clone_bus_tracks(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self.xpj_payload["data"]["tracks"][1:])

    def clone_sequence(self) -> Dict[str, Any]:
        return copy.deepcopy(self.xpj_payload["data"]["sequences"][0]["value"])

    def clone_clip(self) -> Dict[str, Any]:
        return copy.deepcopy(self.xpj_payload["data"]["sequences"][0]["value"]["trackClipMaps"][0][0]["value"])

    def write_fast_xpm(
        self,
        kit_name: str,
        pads_data: Dict[int, Dict[str, Any]],
        out_path: Path,
        *,
        program_pads_json: Optional[str] = None,
        pad_note_map: Optional[Dict[int, int]] = None,
    ) -> None:
        tree = copy.deepcopy(self.xpm_tree)
        root = tree.getroot()
        prog = root.find("Program")
        hkb._set_xml_text(prog, "ProgramName", kit_name)

        if program_pads_json:
            for tag_name in ("ProgramPads-v2.10", "ProgramPads"):
                el = prog.find(tag_name)
                if el is not None:
                    el.text = program_pads_json
                    break

        if pad_note_map:
            pnm = prog.find("PadNoteMap")
            if pnm is not None:
                for pn in pnm:
                    num = _normalize_int(pn.attrib.get("number"), 0)
                    if num in pad_note_map:
                        hkb._set_xml_text(pn, "Note", str(pad_note_map[num]))

        wav_dir = out_path.parent
        for inst in prog.findall("Instruments/Instrument"):
            pad_num = int(inst.get("number", "0"))
            p_info = pads_data.get(pad_num) or {}
            layers = inst.findall("Layers/Layer")

            for lay in layers:
                hkb._set_xml_text(lay, "Active", "False")
                hkb._set_xml_text(lay, "SampleName", "")
                hkb._set_xml_text(lay, "SampleFile", "")
                hkb._set_xml_text(lay, "SliceIndex", "129")
                hkb._set_xml_text(lay, "SliceStart", "0")
                hkb._set_xml_text(lay, "SliceEnd", "0")
                hkb._set_xml_text(lay, "SliceLoopStart", "0")
                hkb._set_xml_text(lay, "TuneCoarse", "0")
                hkb._set_xml_text(lay, "TuneFine", "0")
                hkb._set_xml_text(lay, "RootNote", "0")
                hkb._set_xml_text(lay, "KeyTrack", "False")
                hkb._set_xml_text(lay, "Direction", "0")
                hkb._set_xml_text(lay, "Offset", "0")
                hkb._set_xml_text(lay, "Loop", "False")
                hkb._set_xml_text(lay, "SliceLoop", "0")

            if not p_info:
                continue

            stype = p_info.get("sound_type") or hkb.detect_sound_type(p_info.get("sample_file", ""))
            raw_vol = p_info.get("volume")
            vol = float(raw_vol) if raw_vol is not None else hkb.default_pad_volume(stype)
            pan = float(p_info.get("pan", 0.5))
            tune = max(-24, min(24, int(p_info.get("tune", 0))))
            mute = hkb.pad_mute_group(p_info)
            ext = hkb._extract_extended_pad_params(p_info)

            hkb._set_xml_text(inst, "Volume", f"{vol:.6f}")
            hkb._set_xml_text(inst, "Pan", f"{pan:.6f}")
            hkb._set_xml_text(inst, "TuneCoarse", str(tune))
            hkb._set_xml_text(inst, "TuneFine", str(ext["fine_tune"]))
            hkb._set_xml_text(inst, "MuteGroup", str(mute))
            hkb._set_xml_text(inst, "OneShot", "True" if ext["is_oneshot"] else "False")
            hkb._set_xml_text(inst, "SimultTarget1", str(ext["simult_midi"]))
            if "monophonic" in p_info:
                hkb._set_xml_text(inst, "Mono", "True" if ext["monophonic"] else "False")
                hkb._set_xml_text(inst, "Polyphony", "1" if ext["monophonic"] else "8")
            for target in inst:
                if re.fullmatch(r"MuteTarget[1-4]?", target.tag):
                    target.text = "0"

            layer_specs = p_info.get("layers_list")
            if not layer_specs:
                s_file = p_info.get("sample_file") or ""
                s_name = p_info.get("sample_name") or (Path(s_file).stem if s_file else "")
                if s_file or s_name:
                    layer_specs = [p_info]
                else:
                    layer_specs = []

            for lidx, lspec in enumerate(layer_specs[: len(layers)]):
                lay_el = layers[lidx]
                lf_name = lspec.get("sample_file") or ""
                if not lf_name and lspec.get("sample_name"):
                    sn = lspec["sample_name"]
                    lf_name = sn if sn.lower().endswith(".wav") else f"{sn}.wav"
                if not lf_name:
                    continue
                l_stem = lspec.get("sample_name") or Path(lf_name).stem
                n_frames = int(lspec.get("n_frames") or 0)
                if not n_frames:
                    cand = wav_dir / lf_name
                    if not cand.is_file() and lspec.get("source_path"):
                        cand = Path(lspec["source_path"])
                    n_frames = hkb._get_wav_frames(cand) if cand.is_file() else 0

                ltune = max(-24, min(24, int(lspec.get("tune", tune))))
                lfine = int(lspec.get("fine_tune", ext["fine_tune"]))
                lroot = int(lspec.get("root_note", ext["root_note"]))
                lkeytrack = bool(lspec.get("key_track", ext["key_track"]))
                lrev = bool(lspec.get("reverse", ext["reverse"]))
                lslice_start = int(lspec.get("slice_start", 0))
                lslice_end = int(lspec.get("slice_end") or n_frames)
                lslice_loop = int(lspec.get("loop_mode", ext["loop_mode"]))
                lslice_loop_start = int(lspec.get("slice_loop_start", 0))

                hkb._set_xml_text(lay_el, "Active", "True")
                hkb._set_xml_text(lay_el, "SampleName", l_stem)
                hkb._set_xml_text(lay_el, "SampleFile", Path(lf_name).name)
                hkb._set_xml_text(lay_el, "VelStart", str(int(lspec.get("vel_start", 0))))
                hkb._set_xml_text(lay_el, "VelEnd", str(int(lspec.get("vel_end", 127))))
                hkb._set_xml_text(lay_el, "SliceIndex", str(int(lspec.get("slice_index", 129))))
                hkb._set_xml_text(lay_el, "SliceStart", str(lslice_start))
                hkb._set_xml_text(lay_el, "SliceEnd", str(lslice_end))
                hkb._set_xml_text(lay_el, "SliceLoopStart", str(lslice_loop_start))
                hkb._set_xml_text(lay_el, "TuneCoarse", str(ltune))
                hkb._set_xml_text(lay_el, "TuneFine", str(lfine))
                hkb._set_xml_text(lay_el, "RootNote", str(lroot))
                hkb._set_xml_text(lay_el, "KeyTrack", "True" if lkeytrack else "False")
                hkb._set_xml_text(lay_el, "Direction", "1" if lrev else "0")
                hkb._set_xml_text(lay_el, "Offset", str(int(lspec.get("sample_offset", ext["sample_offset"]))))
                hkb._set_xml_text(lay_el, "Loop", "True" if lslice_loop > 0 else "False")
                hkb._set_xml_text(lay_el, "SliceLoop", str(lslice_loop))

        ET.indent(tree, space="  ", level=0)
        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        _atomic_write_bytes(out_path, xml_bytes)


# ---------------------------------------------------------------------------
# 3. XML .xpm -> ACVS Track Converter (Drum & Keygroup) & Multi-Track Writer
# ---------------------------------------------------------------------------

def _populate_acvs_inst_from_xml(
    xml_inst: ET.Element,
    acvs_inst: Dict[str, Any],
    sindex: Dict[str, Path],
    pdata_dir: Path,
    linked_samples: Dict[str, Dict[str, Any]],
) -> bool:
    """Populate a single ACVS 1.3.0.12 instrument slot from XML `<Instrument>`."""
    layers_el = xml_inst.find("Layers")
    if layers_el is None:
        return False

    xml_layers = layers_el.findall("Layer")
    active_xml_layers: List[Tuple[ET.Element, Path, str]] = []
    for xlay in xml_layers:
        if not _normalize_bool(xlay.findtext("Active"), True) or _normalize_bool(xlay.findtext("Mute"), False):
            continue
        sn = (xlay.findtext("SampleName") or "").rstrip("\r\n")
        sf = (xlay.findtext("SampleFile") or "").strip()
        ref = ""
        if sn.strip():
            ref = sn if sn.lower().endswith((".wav", ".aif", ".aiff", ".flac")) else sn + ".WAV"
        elif sf:
            ref = sf
        if not ref:
            continue
        resolved = _resolve_from_index(ref, sindex)
        if resolved is None:
            continue
        copied = _ensure_sample_in_dir(resolved, pdata_dir)
        active_xml_layers.append((xlay, copied, ref))

    if not active_xml_layers:
        return False

    acvs_inst["coarseTune"] = _normalize_int(xml_inst.findtext("TuneCoarse"), 0)
    acvs_inst["fineTune"] = _normalize_int(xml_inst.findtext("TuneFine"), 0)
    acvs_inst["monophonic"] = _normalize_bool(xml_inst.findtext("Mono"), True)
    acvs_inst["polyphony"] = 1 if acvs_inst["monophonic"] else 8
    acvs_inst["whichMuteGroup"] = _normalize_int(xml_inst.findtext("MuteGroup"), 0)
    acvs_inst["lowNote"] = _normalize_int(xml_inst.findtext("LowNote"), 0)
    acvs_inst["highNote"] = _normalize_int(xml_inst.findtext("HighNote"), 127)
    acvs_inst["zonePlayTime"] = _normalize_int(xml_inst.findtext("ZonePlay"), 1)
    trig_txt = xml_inst.findtext("TriggerMode")
    if trig_txt is not None and trig_txt.strip() != "":
        acvs_inst["triggerMode"] = _normalize_int(trig_txt, 2)
    else:
        oneshot = _normalize_bool(xml_inst.findtext("OneShot"), True)
        acvs_inst["triggerMode"] = 0 if oneshot else 2
    acvs_inst["ignoreBaseNote"] = _normalize_bool(xml_inst.findtext("IgnoreBaseNote"), False)
    acvs_inst["loopLock"] = _normalize_bool(xml_inst.findtext("LoopLock"), True)

    mix = acvs_inst.setdefault("mixable", {})
    mix["volume"] = _normalize_float(xml_inst.findtext("Volume"), 0.7079457640647888)
    mix["pan"] = _normalize_float(xml_inst.findtext("Pan"), 0.5)
    mix["mute"] = _normalize_bool(xml_inst.findtext("Mute"), False)
    mix["solo"] = _normalize_bool(xml_inst.findtext("Solo"), False)
    mix["muteGroup"] = acvs_inst["whichMuteGroup"]

    synth = acvs_inst.setdefault("synthSection", {})
    amp = synth.setdefault("ampEnvelope", {})
    oneshot_flag = acvs_inst["triggerMode"] == 0
    if xml_inst.findtext("OneShot") is not None:
        oneshot_flag = _normalize_bool(xml_inst.findtext("OneShot"), True)
    amp["OneShot"] = {"value0": bool(oneshot_flag)}
    amp["DecayFromEnd"] = {"value0": _normalize_bool(xml_inst.findtext("VolumeDecayType"), True)}
    amp["Attack"] = {"value0": _normalize_float(xml_inst.findtext("VolumeAttack"), 0.0)}
    amp["Hold"] = {"value0": _normalize_float(xml_inst.findtext("VolumeHold"), 0.0)}
    amp["Decay"] = {"value0": _normalize_float(xml_inst.findtext("VolumeDecay"), 0.04724409431219101)}
    amp["Sustain"] = {"value0": _normalize_float(xml_inst.findtext("VolumeSustain"), 1.0)}
    amp["Release"] = {"value0": _normalize_float(xml_inst.findtext("VolumeRelease"), 0.0)}
    synth["velocitySensitivity"] = _normalize_float(xml_inst.findtext("VelocitySensitivity"), 1.0)

    flt = synth.setdefault("filterData", {}).setdefault("value0", {})
    flt["filterType"] = _normalize_int(xml_inst.findtext("FilterType"), 29)
    flt["filterCutoff"] = _normalize_float(xml_inst.findtext("Cutoff"), 1.0)
    flt["filterResonance"] = _normalize_float(xml_inst.findtext("Resonance"), 0.0)
    flt["filterEnvelopeAmount"] = _normalize_float(xml_inst.findtext("FilterEnvAmt"), 0.0)

    fenv = synth.setdefault("filterEnvelope", {})
    fenv["Attack"] = {"value0": _normalize_float(xml_inst.findtext("FilterAttack"), 0.0)}
    fenv["Decay"] = {"value0": _normalize_float(xml_inst.findtext("FilterDecay"), 0.04724409431219101)}
    fenv["Sustain"] = {"value0": _normalize_float(xml_inst.findtext("FilterSustain"), 1.0)}
    fenv["Release"] = {"value0": _normalize_float(xml_inst.findtext("FilterRelease"), 0.0)}

    layersv = acvs_inst.get("layersv", [])
    for lidx, lay in enumerate(layersv):
        if lidx >= len(active_xml_layers):
            lay["active"] = False
            lay["sampleName"] = ""
            lay["sampleFile"] = ""
            continue
        xlay, wav_path, _orig_ref = active_xml_layers[lidx]
        fname = wav_path.name
        fstem = wav_path.stem
        n_frames = hkb._get_wav_frames(wav_path) if fname.lower().endswith(".wav") else 0
        s_start = _normalize_int(xlay.findtext("SliceStart") or xlay.findtext("SampleStart"), 0)
        s_end = _normalize_int(xlay.findtext("SliceEnd") or xlay.findtext("SampleEnd"), n_frames)
        if n_frames > 0 and s_start == 0 and (s_end in (0, 300000, 500000) or s_end > n_frames):
            s_end = n_frames
        s_loop_start = _normalize_int(xlay.findtext("SliceLoopStart") or xlay.findtext("LoopStart"), 0)
        s_loop_mode = _normalize_int(xlay.findtext("SliceLoop"), 1 if _normalize_bool(xlay.findtext("Loop"), False) else 0)
        root_note = _normalize_int(xlay.findtext("RootNote"), 0)

        lay["active"] = True
        lay["mute"] = False
        lay["sampleName"] = fstem
        lay["sampleFile"] = fname
        lay["velocityStart"] = _normalize_int(xlay.findtext("VelStart"), 0)
        lay["velocityEnd"] = _normalize_int(xlay.findtext("VelEnd"), 127)
        lay["coarseTune"] = _normalize_int(xlay.findtext("TuneCoarse"), 0)
        lay["fineTune"] = _normalize_int(xlay.findtext("TuneFine"), 0)
        lay["pitch"] = _normalize_float(xlay.findtext("Pitch"), 0.0)
        lay["pan"] = _normalize_float(xlay.findtext("Pan"), 0.5)
        lay["direction"] = _normalize_int(xlay.findtext("Direction"), 0)
        lay["offset"] = _normalize_int(xlay.findtext("Offset"), 0)
        lay["rootNote"] = root_note
        lay["keyTrackEnable"] = _normalize_bool(xlay.findtext("KeyTrack"), False)
        lay["loopMode"] = s_loop_mode
        lay["loop"] = bool(s_loop_mode > 0)
        lay["sliceIndex"] = _normalize_int(xlay.findtext("SliceIndex"), 129)
        lay["layerLoopModeOverridesSliceLoopMode"] = True
        lay["volume"] = {
            "gainCoefficient": _normalize_float(xlay.findtext("Volume"), 1.0),
            "controlValue": 1.0,
            "law": 1,
        }
        lay["sliceInfo"] = {
            "Start": int(s_start),
            "End": int(s_end),
            "LoopStart": int(s_loop_start),
            "LoopMode": int(s_loop_mode),
            "PulsePosition": 0,
            "LoopCrossfadeLength": _normalize_int(xlay.findtext("SliceLoopCrossFadeLength") or xlay.findtext("LoopCrossfadeLength"), 0),
            "LoopCrossfadeType": 0,
            "TailLength": _normalize_float(xlay.findtext("SliceTailLength"), 0.0),
            "TailLoopPosition": _normalize_float(xlay.findtext("SliceTailPosition"), 0.5),
        }
        if fname not in linked_samples:
            linked_samples[fname] = {
                "version": 1,
                "name": fstem,
                "path": fname,
                "loadImpl": 0,
                "metadata": {
                    "tempo": 0.0,
                    "rootNote": int(root_note if root_note > 0 else 60),
                    "tune": 0.0,
                    "key": "C Major",
                },
            }
    return True


def build_acvs_tracks_from_xpm(
    xpm_path: Path,
    search_dirs: List[Path],
    pdata_dir: Path,
    tpl: AcvsTemplateLoader,
    *,
    track_name_override: Optional[str] = None,
    split_over_128: bool = False,
) -> List[Dict[str, Any]]:
    """Build 1 (or >1 if `split_over_128=True`) ACVS tracks from an XML `.xpm`."""
    tree = ET.parse(str(xpm_path))
    root = tree.getroot()
    prog_el = root.find("Program")
    if prog_el is None:
        return []
    ptype = (prog_el.attrib.get("type") or "Drum").strip()
    if ptype not in ("Drum", "Keygroup"):
        return []

    prog_name = (prog_el.findtext("ProgramName") or "").strip()
    clean_stem = re.sub(r"\.(Drum|Keygroup)$", "", xpm_path.stem)
    tname = track_name_override or clean_stem or prog_name or "Drum 001"
    sindex = _build_dir_sample_index([pdata_dir, xpm_path.parent] + search_dirs)

    xml_insts_map: Dict[int, ET.Element] = {}
    for inst_el in prog_el.findall("./Instruments/Instrument"):
        num = _normalize_int(inst_el.attrib.get("number"), 0)
        if num >= 1:
            xml_insts_map[num] = inst_el

    max_inst = max(xml_insts_map.keys(), default=0)
    chunks: List[Tuple[str, List[Tuple[int, ET.Element]]]] = []
    if split_over_128 and max_inst > 128:
        for start in range(1, max_inst + 1, 128):
            end = min(max_inst, start + 127)
            sub = [(pad_idx, xml_insts_map[num]) for pad_idx, num in enumerate(range(start, end + 1), 1) if num in xml_insts_map]
            label = f"{tname} {start:03d}-{end:03d}" if len(xml_insts_map) > 128 else tname
            chunks.append((label, sub))
    else:
        sub = [(num, xml_insts_map[num]) for num in range(1, 129) if num in xml_insts_map]
        chunks.append((tname, sub))

    # Parse shared program-level fields
    p_vol = _normalize_float(prog_el.findtext("Volume"), 0.7079457640647888)
    p_pan = _normalize_float(prog_el.findtext("Pan"), 0.5)
    prog_pads_obj = None
    for tag_name in ("ProgramPads-v2.10", "ProgramPads"):
        raw_pp = prog_el.findtext(tag_name)
        if raw_pp and raw_pp.strip().startswith("{"):
            try:
                parsed_pp = json.loads(raw_pp)
                if tag_name in parsed_pp and isinstance(parsed_pp[tag_name], dict):
                    parsed_pp = parsed_pp[tag_name]
                elif "ProgramPads" in parsed_pp and isinstance(parsed_pp["ProgramPads"], dict):
                    parsed_pp = parsed_pp["ProgramPads"]
                if isinstance(parsed_pp, dict):
                    prog_pads_obj = parsed_pp
                    break
            except json.JSONDecodeError:
                pass

    pnm_el = prog_el.find("PadNoteMap")
    note_for_pad = {f"value{i}": (36 + i) % 128 for i in range(128)}
    if pnm_el is not None:
        for child in pnm_el:
            num = _normalize_int(child.attrib.get("number"), 0)
            note = child.findtext("Note")
            if 1 <= num <= 128 and note is not None:
                note_for_pad[f"value{num - 1}"] = _normalize_int(note, 35 + num)

    built_tracks: List[Dict[str, Any]] = []
    for chunk_name, items in chunks:
        trk = tpl.clone_track()
        trk["name"] = chunk_name
        trk["volume"] = float(p_vol)
        trk["pan"] = float(p_pan)
        trk_samples: Dict[str, Dict[str, Any]] = {}
        prog = trk["program"]
        prog["name"] = chunk_name
        prog["type"] = 1 if (ptype == "Keygroup" and not (split_over_128 and max_inst > 128)) else 0
        if isinstance(prog.get("mixable"), dict):
            prog["mixable"]["volume"] = float(p_vol)
            prog["mixable"]["pan"] = float(p_pan)
        if prog_pads_obj is not None:
            prog["programPads"] = copy.deepcopy(prog_pads_obj)
        prog["padNoteMap"] = {"noteForPad": copy.deepcopy(note_for_pad)}

        drum_section = prog["drum"]
        drum_section["monophonic"] = _normalize_bool(prog_el.findtext("Mono"), False)
        drum_section["portamentoTime"] = _normalize_float(prog_el.findtext("PortamentoTime"), 0.0)
        drum_section["portamentoLegato"] = _normalize_bool(prog_el.findtext("PortamentoLegato"), False)

        acvs_insts = drum_section["instruments"]
        for acvs_i in acvs_insts:
            hkb._reset_xpj_instrument_slot(acvs_i)

        populated = 0
        for pad_1based, xinst in items:
            if 1 <= pad_1based <= len(acvs_insts):
                if _populate_acvs_inst_from_xml(xinst, acvs_insts[pad_1based - 1], sindex, pdata_dir, trk_samples):
                    populated += 1

        if populated == 0:
            continue

        if prog["type"] == 1:
            n_kg = _normalize_int(prog_el.findtext("KeygroupNumKeygroups"), populated)
            prog["keygroup"] = {
                "version": 1,
                "numKeygroups": int(max(1, min(128, n_kg or populated))),
                "transpose": _normalize_int(prog_el.findtext("TuneCoarse"), 0),
            }

        trk["samples"] = list(trk_samples.values())
        built_tracks.append(trk)

    return built_tracks


def write_acvs_project(
    xpj_path: Path,
    program_tracks: List[Dict[str, Any]],
    sequences_spec: List[Dict[str, Any]],
    tpl: AcvsTemplateLoader,
    *,
    master_tempo: float = 120.0,
    master_tempo_enabled: bool = False,
    current_sequence: int = 0,
    project_key: str = "C Major",
) -> None:
    """Write a complete multi-track / multi-sequence ACVS 1.3.0.12 `.xpj` atomically."""
    payload = tpl.clone_payload()
    data = payload["data"]
    data["key"] = mpc_compat.normalize_key(project_key)
    data["masterTempo"] = float(master_tempo if master_tempo > 0 else 120.0)
    data["masterTempoEnabled"] = bool(master_tempo_enabled)

    # Deduplicate sample table across all tracks and normalize metadata keys
    all_samples: Dict[str, Dict[str, Any]] = {}
    for trk in program_tracks:
        for smp in trk.get("samples", []):
            meta_s = smp.get("metadata")
            if isinstance(meta_s, dict) and "key" in meta_s:
                meta_s["key"] = mpc_compat.normalize_key(meta_s["key"])
            p = smp.get("path") or ""
            if p and p not in all_samples:
                all_samples[p] = copy.deepcopy(smp)
    data["samples"] = list(all_samples.values())

    bus_tracks = tpl.clone_bus_tracks()
    all_tracks = [copy.deepcopy(t) for t in program_tracks] + bus_tracks
    data["tracks"] = all_tracks
    mpc_compat.restore_mixer_tracks(data)
    all_tracks = data["tracks"]

    seq_entries: List[Dict[str, Any]] = []
    if not sequences_spec:
        sequences_spec = [
            {
                "key": 0,
                "name": "Sequence 01",
                "bpm": float(master_tempo),
                "length_bars": 4,
                "beats_per_bar": 4,
                "beat_unit": 4,
                "clips": {},
            }
        ]

    for sspec in sorted(sequences_spec, key=lambda s: int(s["key"])):
        s_key = int(sspec["key"])
        beats = int(sspec.get("beats_per_bar", 4))
        unit = int(sspec.get("beat_unit", 4))
        beat_len = int(round(DEFAULT_MPC_TICKS_PER_QUARTER * (4.0 / float(unit))))
        bar_pulses = int(beats * beat_len)
        l_bars = int(max(1, min(128, int(sspec.get("length_bars", 4)))))
        l_pulses = int(sspec.get("length_pulses") or (l_bars * bar_pulses))

        seq_obj = tpl.clone_sequence()
        seq_obj["name"] = str(sspec.get("name") or f"Sequence {s_key + 1:02d}")
        seq_obj["bpm"] = float(sspec.get("bpm") or master_tempo)
        seq_obj["lengthBars"] = int(l_bars)
        seq_obj["lengthPulses"] = int(l_pulses)
        seq_obj["loopStartBar"] = 0
        seq_obj["loopEndBar"] = int(l_bars)
        seq_obj["loopStartPulses"] = 0
        seq_obj["loopEndPulses"] = int(l_pulses)
        seq_obj["timeSignatureTrack"] = {
            "timeSignatures": [
                {"beatsPerBar": int(beats), "beatLength": int(beat_len), "barStart": 0}
            ]
        }

        clips_by_name = sspec.get("clips") or {}
        clip_list: List[Dict[str, Any]] = []
        for trk in all_tracks:
            tname = str(trk.get("name") or "")
            clip = tpl.clone_clip()
            clip["name"] = tname
            clip["startPulses"] = 0
            clip["endPulses"] = int(l_pulses)
            clip["loopStartPulses"] = 0
            clip["loopEndPulses"] = int(l_pulses)
            evs = list(clips_by_name.get(tname) or [])
            evs.sort(key=lambda e: (int(e.get("time", 0)), int((e.get("note") or {}).get("note", 0))))
            clip["eventList"]["events"] = evs
            clip_list.append({"key": tname, "value": clip})
        seq_obj["trackClipMaps"] = [clip_list]
        seq_entries.append({"key": s_key, "value": seq_obj})

    valid_keys = {e["key"] for e in seq_entries}
    data["sequences"] = seq_entries
    data["currentSequence"] = int(current_sequence if current_sequence in valid_keys else seq_entries[0]["key"])
    mpc_compat.reconcile_generated_clips(data)

    out_text = tpl.xpj_header + json.dumps(payload, indent=0)
    _atomic_write_gzip_text(xpj_path, out_text)


# ---------------------------------------------------------------------------
# 4. Stage A: Restoring Source Files & Cleaning Double Extensions
# ---------------------------------------------------------------------------

def stage_restore_sources_and_paths(
    card_root: Path,
    downloads_root: Path,
    backup_historico: Path,
    backup_root: Path,
) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "80s_riff_restored": 0,
        "test_press_beatmaker_restored": 0,
        "marco_polo_lofi_restored": False,
        "double_ext_fixed": 0,
    }
    exp_root = card_root / "Expansions"

    # A1: Copy 25 RIFF WAVs misnamed as .xpm from Downloads -> 80s Nostalgia/*.WAV
    dl_80 = downloads_root / "Akai Professional - 80s Nostalgia" / "80's Nostaligia"
    sd_80 = exp_root / "80s Nostalgia"
    if dl_80.is_dir() and sd_80.is_dir():
        for src in sorted(dl_80.glob("*.xpm")):
            if src.name.startswith("."):
                continue
            with src.open("rb") as f:
                head = f.read(4)
            if head == b"RIFF":
                dst = sd_80 / f"{src.stem}.WAV"
                if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
                    shutil.copy2(src, dst)
                    assert _sha256_file(src) == _sha256_file(dst), f"SHA mismatch copying {src}"
                    stats["80s_riff_restored"] += 1

    # A2: Restore Test Press DnB Textures 2 /Beatmaker WAV kits
    dl_tp_bm = downloads_root / "Test Press DnB Textures 2" / "Beatmaker"
    sd_tp_bm = exp_root / "Test Press - DnB Textures 2" / "beatmaker_kits"
    if dl_tp_bm.is_dir():
        for kit_dir in sorted(dl_tp_bm.iterdir()):
            if not kit_dir.is_dir() or kit_dir.name.startswith("."):
                continue
            jsons = sorted(kit_dir.glob("*.json"))
            kit_title = _safe_kit_stem(jsons[0].stem if jsons else kit_dir.name, 48)
            wavs = sorted(w for w in kit_dir.glob("*.wav") if not w.name.startswith("."))
            if not wavs:
                continue
            dst_dir = sd_tp_bm / kit_title
            dst_dir.mkdir(parents=True, exist_ok=True)
            for w in wavs:
                dst = dst_dir / w.name
                if not dst.is_file() or dst.stat().st_size != w.stat().st_size:
                    shutil.copy2(w, dst)
                    stats["test_press_beatmaker_restored"] += 1

    # A3: Restore intact Marco Polo - LoFi Boom Vol 1 Demo Project.xpj from backup_historico + patch lengthPulses
    bk_mp_dir = backup_historico / "Expansions" / "Marco Polo - LoFi Boom Vol 1"
    sd_mp_dir = exp_root / "Marco Polo - LoFi Boom Vol 1"
    bk_mp_xpj = bk_mp_dir / "Marco Polo - LoFi Boom Vol 1 Demo Project.xpj"
    sd_mp_xpj = sd_mp_dir / "Marco Polo - LoFi Boom Vol 1 Demo Project.xpj"
    if bk_mp_xpj.is_file() and sd_mp_dir.is_dir():
        _backup_before_overwrite(sd_mp_xpj, card_root, backup_root)
        # Ensure all demo ProjectData WAVs are present
        bk_pdata = bk_mp_dir / "Marco Polo - LoFi Boom Vol 1 Demo Project_[ProjectData]"
        sd_pdata = sd_mp_dir / "Marco Polo - LoFi Boom Vol 1 Demo Project_[ProjectData]"
        if bk_pdata.is_dir():
            sd_pdata.mkdir(parents=True, exist_ok=True)
            for f in bk_pdata.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    dst = sd_pdata / f.name
                    if not dst.is_file() or dst.stat().st_size != f.stat().st_size:
                        shutil.copy2(f, dst)
        raw = gzip.decompress(bk_mp_xpj.read_bytes()).decode("utf-8")
        jidx = raw.index("{")
        hdr = raw[:jidx]
        payload = json.loads(raw[jidx:])
        data = payload.get("data", {})
        for seq_entry in data.get("sequences", []):
            sv = seq_entry.get("value")
            if isinstance(sv, dict):
                lb = int(sv.get("lengthBars") or 8)
                if not sv.get("lengthPulses"):
                    sv["lengthPulses"] = int(lb * 3840)
                if sv.get("loopStartPulses") is None:
                    sv["loopStartPulses"] = 0
                if not sv.get("loopEndPulses"):
                    sv["loopEndPulses"] = int(sv["lengthPulses"])
                if "bpm" in sv:
                    sv["bpm"] = float(sv["bpm"])
                for m in sv.get("trackClipMaps", []) or []:
                    for clip in m or []:
                        cv = clip.get("value") or {}
                        for ev in (cv.get("eventList") or {}).get("events") or []:
                            nobj = ev.get("note")
                            if isinstance(nobj, dict) and "velocity" in nobj:
                                nobj["velocity"] = float(nobj["velocity"])
        _atomic_write_gzip_text(sd_mp_xpj, hdr + json.dumps(payload, indent=0))
        stats["marco_polo_lofi_restored"] = True

    # A4: Fix .wav.wav double extensions in Serato Studio UK Drill & Astro1Deep_Kit_DRill_C_Rebro
    for target_dir in [
        exp_root / "Serato Studio - Artist Collection" / "Artist Signature Kits" / "UK Drill Drum Kit",
        exp_root / "Astro1Deep Signature Pack" / "Astro1Deep - Signature Kits" / "Astro1Deep_Kit_DRill_C_Rebro",
        card_root / "Custom_Kits" / "Astro1Deep_Kit_DRill_C_Rebro",
    ]:
        if not target_dir.is_dir():
            continue
        for ww in list(target_dir.rglob("*.wav.wav")):
            if ww.name.startswith("."):
                continue
            clean_wav = ww.with_name(ww.name[:-4])
            if not clean_wav.is_file():
                shutil.copy2(ww, clean_wav)

        # Update .xpm references from *.wav.wav / trailing *.wav SampleName -> clean *.wav
        for xpm in target_dir.rglob("*.xpm"):
            if xpm.name.startswith(".") or any(
                part.endswith(("_[ProjectData]", "_[TrackData]"))
                for part in xpm.relative_to(target_dir).parts
            ):
                continue
            try:
                tree = ET.parse(str(xpm))
            except ET.ParseError:
                continue
            parent_lows = {
                f.name.lower()
                for f in xpm.parent.iterdir()
                if f.is_file() and not f.name.startswith(".")
            }
            modified = False
            for lay in tree.findall(".//Layer"):
                sf_el = lay.find("SampleFile")
                sn_el = lay.find("SampleName")
                sf_txt = (sf_el.text or "").strip() if sf_el is not None else ""
                sn_txt = (sn_el.text or "").rstrip("\r\n") if sn_el is not None else ""
                if sf_el is not None and sf_txt.lower().endswith(".wav.wav"):
                    clean_sf = sf_txt[:-4]
                    if Path(clean_sf).name.lower() in parent_lows:
                        sf_el.text = clean_sf
                        modified = True
                if sn_el is not None and sn_txt.lower().endswith(".wav"):
                    cand_wav = Path(sn_txt).name.lower()
                    if cand_wav in parent_lows:
                        sn_el.text = sn_txt[:-4]
                        modified = True
            if modified:
                _backup_before_overwrite(xpm, card_root, backup_root)
                _atomic_write_bytes(
                    xpm,
                    ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True),
                )

        # Update .xpj references from *.wav.wav -> *.wav cleanly
        for xpj in target_dir.rglob("*.xpj"):
            if xpj.name.startswith("."):
                continue
            _backup_before_overwrite(xpj, card_root, backup_root)
            raw = gzip.decompress(xpj.read_bytes()).decode("utf-8")
            jidx = raw.index("{")
            hdr = raw[:jidx]
            payload = json.loads(raw[jidx:])
            pdata = xpj.parent / f"{xpj.stem}_[ProjectData]"

            def _fix_refs(obj: Any) -> Any:
                if isinstance(obj, dict):
                    return {k: _fix_refs(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_fix_refs(i) for i in obj]
                if isinstance(obj, str) and obj.lower().endswith(".wav.wav"):
                    cand_name = obj[:-4]
                    if (pdata / Path(cand_name).name).is_file() or (xpj.parent / Path(cand_name).name).is_file():
                        return cand_name
                return obj

            fixed_payload = _fix_refs(payload)
            if fixed_payload != payload:
                _atomic_write_gzip_text(xpj, hdr + json.dumps(fixed_payload, indent=0))

        # Remove redundant *.wav.wav only if clean *.wav exists alongside it
        for ww in list(target_dir.rglob("*.wav.wav")):
            if ww.name.startswith("."):
                continue
            clean_wav = ww.with_name(ww.name[:-4])
            if clean_wav.is_file() and clean_wav.stat().st_size == ww.stat().st_size:
                ww.unlink()
                stats["double_ext_fixed"] += 1

    return stats


# ---------------------------------------------------------------------------
# 5. Stage B: Classic Drum Machines (72 .xtd -> .xpm + .xpj + Demo Fix)
# ---------------------------------------------------------------------------

def stage_classic_drum_machines(
    card_root: Path,
    backup_root: Path,
    tpl: AcvsTemplateLoader,
) -> Dict[str, Any]:
    cdm = card_root / "Expansions" / "Classic Drum Machines"
    if not cdm.is_dir():
        return {"xtd_converted": 0}

    # B1: Remove misgenerated .xpm files inside _[ProjectData] / _[TrackData]
    removed_bad_xpm = 0
    for p in list(cdm.rglob("*.xpm")):
        if any(part.endswith(("_[TrackData]", "_[ProjectData]")) for part in p.relative_to(cdm).parts):
            p.unlink()
            removed_bad_xpm += 1

    # B2: Patch Classic Drum Machines Demo Project.xpj sequence lengthPulses
    demo_xpj = cdm / "Classic Drum Machines Demo Project.xpj"
    demo_patched = False
    if demo_xpj.is_file():
        _backup_before_overwrite(demo_xpj, card_root, backup_root)
        raw = gzip.decompress(demo_xpj.read_bytes()).decode("utf-8")
        jidx = raw.index("{")
        hdr = raw[:jidx]
        payload = json.loads(raw[jidx:])
        data = payload.get("data", {})
        for seq_entry in data.get("sequences", []):
            sv = seq_entry.get("value")
            if isinstance(sv, dict):
                lb = int(sv.get("lengthBars") or 8)
                if not sv.get("lengthPulses"):
                    sv["lengthPulses"] = int(lb * 3840)
                if sv.get("loopStartPulses") is None:
                    sv["loopStartPulses"] = 0
                if not sv.get("loopEndPulses"):
                    sv["loopEndPulses"] = int(sv["lengthPulses"])
                if "bpm" in sv:
                    sv["bpm"] = float(sv["bpm"])
        _atomic_write_gzip_text(demo_xpj, hdr + json.dumps(payload, indent=0))
        demo_patched = True

    # B3: Convert all 72 .xtd bundles -> root <Kit>.xpm + <Kit>.xpj + <Kit>_[ProjectData]/
    xtd_files = sorted(p for p in cdm.glob("*.xtd") if not p.name.startswith("."))
    converted = 0
    total_notes = 0
    total_seqs = 0
    xtd_archive = card_root / "_RAW_SOURCE_ARCHIVES" / "classic_drum_machines_xtd"
    xtd_archive.mkdir(parents=True, exist_ok=True)
    to_archive: List[Tuple[Path, Path]] = []

    for xtd_path in xtd_files:
        kit_name = xtd_path.stem
        td_dir = cdm / f"{kit_name}_[TrackData]"
        pdata_dir = cdm / f"{kit_name}_[ProjectData]"
        pdata_dir.mkdir(parents=True, exist_ok=True)

        dec = gzip.decompress(xtd_path.read_bytes()).decode("utf-8")
        td_data = json.loads(dec[dec.index("{") :]).get("data", {})
        td_prog = td_data.get("program") or {}
        insts = ((td_prog.get("drum") or {}).get("instruments")) or []

        sindex = _build_dir_sample_index([td_dir, cdm])
        kit_bpm = float(hkb.infer_kit_bpm(kit_name, fallback=120.0))

        # Build pads dict for fast XPM generation + prepare clean ACVS 1.3 track
        pads_for_xpm: Dict[int, Dict[str, Any]] = {}
        trk = tpl.clone_track()
        trk["name"] = kit_name
        trk["volume"] = float(td_prog.get("mixable", {}).get("volume", 0.7079457640647888))
        trk["pan"] = float(td_prog.get("mixable", {}).get("pan", 0.5))
        prog = trk["program"]
        prog["name"] = kit_name
        prog["type"] = 0
        if isinstance(td_prog.get("programPads"), dict):
            prog["programPads"] = copy.deepcopy(td_prog["programPads"])
        if isinstance(td_prog.get("padNoteMap"), dict):
            prog["padNoteMap"] = copy.deepcopy(td_prog["padNoteMap"])
        acvs_insts = prog["drum"]["instruments"]
        for ai in acvs_insts:
            hkb._reset_xpj_instrument_slot(ai)

        linked_samples: Dict[str, Dict[str, Any]] = {}
        for pad_idx, xinst in enumerate(insts[:128], 1):
            act_lyrs = [l for l in (xinst.get("layersv") or []) if l.get("active", True) and (l.get("sampleFile") or l.get("sampleName"))]
            if not act_lyrs:
                continue
            mix = xinst.get("mixable") or {}
            synth = xinst.get("synthSection") or {}
            amp = synth.get("ampEnvelope") or {}
            oneshot = bool((amp.get("OneShot") or {}).get("value0", True))

            # Copy all active WAVs to both cdm/ (for XPM) and pdata_dir/ (for XPJ)
            xpm_layers: List[Dict[str, Any]] = []
            for lyr in act_lyrs:
                ref = lyr.get("sampleFile") or lyr.get("sampleName") or ""
                resolved = _resolve_from_index(ref, sindex)
                if resolved is None:
                    continue
                _ensure_sample_in_dir(resolved, cdm)
                copied_pd = _ensure_sample_in_dir(resolved, pdata_dir)
                n_frames = hkb._get_wav_frames(copied_pd)
                sinfo = lyr.get("sliceInfo") or {}
                lroot = int(lyr.get("rootNote") or 0)
                if copied_pd.name not in linked_samples:
                    linked_samples[copied_pd.name] = {
                        "version": 1,
                        "name": copied_pd.stem,
                        "path": copied_pd.name,
                        "loadImpl": 0,
                        "metadata": {
                            "tempo": 0.0,
                            "rootNote": int(lroot if lroot > 0 else 60),
                            "tune": 0.0,
                            "key": "C Major",
                        },
                    }
                xpm_layers.append(
                    {
                        "sample_file": copied_pd.name,
                        "sample_name": copied_pd.stem,
                        "source_path": str(copied_pd),
                        "n_frames": n_frames,
                        "tune": int(lyr.get("coarseTune") or 0),
                        "fine_tune": int(lyr.get("fineTune") or 0),
                        "root_note": lroot,
                        "key_track": bool(lyr.get("keyTrackEnable", False)),
                        "reverse": int(lyr.get("direction") or 0) == 1,
                        "loop_mode": int(lyr.get("loopMode") or sinfo.get("LoopMode") or 0),
                        "sample_offset": int(lyr.get("offset") or 0),
                        "vel_start": int(lyr.get("velocityStart") or 0),
                        "vel_end": int(lyr.get("velocityEnd") or 127),
                        "slice_index": int(lyr.get("sliceIndex") or 129),
                        "slice_start": int(sinfo.get("Start") or 0),
                        "slice_end": int(sinfo.get("End") or n_frames),
                        "slice_loop_start": int(sinfo.get("LoopStart") or 0),
                    }
                )

            if not xpm_layers:
                continue

            ai = acvs_insts[pad_idx - 1]
            ai["coarseTune"] = int(xinst.get("coarseTune") or 0)
            ai["fineTune"] = int(xinst.get("fineTune") or 0)
            ai["monophonic"] = bool(xinst.get("monophonic", True))
            ai["polyphony"] = 1 if ai["monophonic"] else 8
            ai["whichMuteGroup"] = int(xinst.get("whichMuteGroup") or 0)
            ai["triggerMode"] = 0 if oneshot else 2
            ai["mixable"]["volume"] = float(mix.get("volume", 0.7079457640647888))
            ai["mixable"]["pan"] = float(mix.get("pan", 0.5))
            ai["mixable"]["mute"] = bool(mix.get("mute", False))
            ai["mixable"]["muteGroup"] = ai["whichMuteGroup"]

            # Sync key filter & amp envelope fields
            ai_amp = ai["synthSection"]["ampEnvelope"]
            ai_amp["OneShot"] = {"value0": oneshot}
            for ek in ("Attack", "Hold", "Decay", "Sustain", "Release"):
                if ek in amp and isinstance(amp[ek], dict):
                    ai_amp[ek] = {"value0": float(amp[ek].get("value0", 0.0))}
            if isinstance((synth.get("filterData") or {}).get("value0"), dict):
                xf0 = synth["filterData"]["value0"]
                af0 = ai["synthSection"]["filterData"]["value0"]
                af0["filterType"] = int(xf0.get("filterType", 29))
                af0["filterCutoff"] = float(xf0.get("filterCutoff", 1.0))
                af0["filterResonance"] = float(xf0.get("filterResonance", 0.0))
                af0["filterEnvelopeAmount"] = float(xf0.get("filterEnvelopeAmount", 0.0))

            for lidx, xl in enumerate(xpm_layers[: len(ai["layersv"])]):
                al = ai["layersv"][lidx]
                al["active"] = True
                al["mute"] = False
                al["sampleFile"] = xl["sample_file"]
                al["sampleName"] = xl["sample_name"]
                al["velocityStart"] = xl["vel_start"]
                al["velocityEnd"] = xl["vel_end"]
                al["coarseTune"] = xl["tune"]
                al["fineTune"] = xl["fine_tune"]
                al["pitch"] = 0.0
                al["pan"] = 0.5
                al["direction"] = 1 if xl["reverse"] else 0
                al["offset"] = xl["sample_offset"]
                al["rootNote"] = xl["root_note"]
                al["keyTrackEnable"] = xl["key_track"]
                al["loopMode"] = xl["loop_mode"]
                al["loop"] = bool(xl["loop_mode"] > 0)
                al["sliceIndex"] = 129
                al["volume"] = {"gainCoefficient": 1.0, "controlValue": 1.0, "law": 1}
                al["sliceInfo"] = {
                    "Start": int(xl["slice_start"]),
                    "End": int(xl["slice_end"]),
                    "LoopStart": int(xl["slice_loop_start"]),
                    "LoopMode": int(xl["loop_mode"]),
                    "PulsePosition": 0,
                    "LoopCrossfadeLength": 0,
                    "LoopCrossfadeType": 0,
                    "TailLength": 0.0,
                    "TailLoopPosition": 0.5,
                }

            pads_for_xpm[pad_idx] = {
                "sample_file": xpm_layers[0]["sample_file"],
                "sample_name": xpm_layers[0]["sample_name"],
                "source_path": xpm_layers[0]["source_path"],
                "n_frames": xpm_layers[0]["n_frames"],
                "sound_type": hkb.detect_sound_type(xpm_layers[0]["sample_file"]),
                "volume": float(mix.get("volume", 0.7079457640647888)),
                "pan": float(mix.get("pan", 0.5)),
                "tune": int(xinst.get("coarseTune") or 0),
                "fine_tune": int(xinst.get("fineTune") or 0),
                "mute_group": int(xinst.get("whichMuteGroup") or 0),
                "trigger_mode": "oneshot" if oneshot else "noteon",
                "monophonic": bool(xinst.get("monophonic", True)),
                "layers_list": xpm_layers,
            }

        trk["samples"] = list(linked_samples.values())

        # Extract sequences from sharedClipMap
        pp_json = None
        if isinstance(td_prog.get("programPads"), dict):
            pp_json = json.dumps({"ProgramPads-v2.10": td_prog["programPads"]}, indent=4)
        pnm_dict = None
        nfp = (td_prog.get("padNoteMap") or {}).get("noteForPad")
        if isinstance(nfp, dict):
            pnm_dict = {int(k[5:]) + 1: int(v) for k, v in nfp.items() if k.startswith("value") and k[5:].isdigit()}

        xpm_out = cdm / f"{kit_name}.xpm"
        tpl.write_fast_xpm(kit_name, pads_for_xpm, xpm_out, program_pads_json=pp_json, pad_note_map=pnm_dict)

        seqs_spec: List[Dict[str, Any]] = []
        scm = td_data.get("sharedClipMap") or []
        for sidx, entry in enumerate(scm):
            cv = entry.get("value") or {}
            raw_evs = (cv.get("eventList") or {}).get("events") or []
            note_evs = [_sanitize_acvs_event(e) for e in raw_evs if e.get("type") == 3 and not e.get("muted")]
            if not note_evs:
                continue
            end_pulses = int(cv.get("endPulses") or 15360)
            max_t = max((e["time"] for e in note_evs), default=0)
            end_pulses = max(end_pulses, ((max_t // 3840) + 1) * 3840)
            l_bars = max(1, min(128, (end_pulses + 3839) // 3840))
            seqs_spec.append(
                {
                    "key": len(seqs_spec),
                    "name": str(cv.get("name") or f"Sequence {len(seqs_spec) + 1:02d}"),
                    "bpm": kit_bpm,
                    "length_bars": l_bars,
                    "length_pulses": int(l_bars * 3840),
                    "beats_per_bar": 4,
                    "beat_unit": 4,
                    "clips": {kit_name: note_evs},
                }
            )
            total_notes += len(note_evs)

        total_seqs += len(seqs_spec)
        write_acvs_project(
            cdm / f"{kit_name}.xpj",
            [trk],
            seqs_spec,
            tpl,
            master_tempo=kit_bpm,
            master_tempo_enabled=False,
        )
        converted += 1
        to_archive.append((xtd_path, td_dir))

    # Archive source .xtd + _[TrackData] out of Expansions/ once verified created
    for xtd_path, td_dir in to_archive:
        kit_name = xtd_path.stem
        assert (cdm / f"{kit_name}.xpm").is_file() and (cdm / f"{kit_name}.xpj").is_file()
        dst_xtd = xtd_archive / xtd_path.name
        if xtd_path.exists():
            if dst_xtd.exists():
                dst_xtd.unlink()
            shutil.move(str(xtd_path), str(dst_xtd))
        if td_dir.is_dir():
            dst_td = xtd_archive / td_dir.name
            if dst_td.exists():
                shutil.rmtree(dst_td)
            shutil.move(str(td_dir), str(dst_td))

    return {
        "removed_bad_xpm": removed_bad_xpm,
        "demo_patched": demo_patched,
        "xtd_converted": converted,
        "sequences_recovered": total_seqs,
        "notes_recovered": total_notes,
    }


# ---------------------------------------------------------------------------
# 6. Stage C: Multi-Track Demo / Beat Projects (XML 2.x + MPC Beats Demos)
# ---------------------------------------------------------------------------

def _add_audio_stems_track_if_needed(
    xpj_path: Path,
    pdata_dir: Path,
    existing_xpm_paths: List[Path],
    tpl: AcvsTemplateLoader,
) -> Optional[Dict[str, Any]]:
    """For Beat Audio projects, map any standalone stem loops in ProjectData to pads on an Audio Stems track."""
    if not ("Beat Audio" in xpj_path.stem and pdata_dir.is_dir()):
        return None
    referenced = set()
    for xp in existing_xpm_paths:
        try:
            el = ET.fromstring(xp.read_bytes())
        except Exception:
            continue
        for lyr in el.findall(".//Layer"):
            sn = (lyr.findtext("SampleName") or "").strip().lower()
            sf = (lyr.findtext("SampleFile") or "").strip()
            if sn:
                referenced.add(sn)
            if sf:
                referenced.add(Path(sf).stem.lower())
    unref_wavs = sorted(
        w
        for w in pdata_dir.iterdir()
        if w.is_file()
        and not w.name.startswith(".")
        and w.suffix.lower() == ".wav"
        and w.stem.lower() not in referenced
        and w.name.lower() != "project preview.wav"
    )
    if not unref_wavs:
        return None

    trk = tpl.clone_track()
    trk["name"] = "Audio Stems"
    trk["program"]["name"] = "Audio Stems"
    trk["program"]["type"] = 0
    acvs_insts = trk["program"]["drum"]["instruments"]
    for ai in acvs_insts:
        hkb._reset_xpj_instrument_slot(ai)

    trk_samples = []
    for idx, wav_p in enumerate(unref_wavs[:64]):
        ai = acvs_insts[idx]
        n_frames = hkb._get_wav_frames(wav_p)
        ai["monophonic"] = True
        ai["polyphony"] = 1
        ai["triggerMode"] = 0
        ai["whichMuteGroup"] = 0
        ai["mixable"]["volume"] = 0.7079457640647888
        ai["mixable"]["pan"] = 0.5
        lay0 = ai["layersv"][0]
        lay0["active"] = True
        lay0["mute"] = False
        lay0["sampleFile"] = wav_p.name
        lay0["sampleName"] = wav_p.stem
        lay0["sliceIndex"] = 129
        lay0["volume"] = {"gainCoefficient": 1.0, "controlValue": 1.0, "law": 1}
        lay0["sliceInfo"] = {
            "Start": 0,
            "End": int(n_frames),
            "LoopStart": 0,
            "LoopMode": 0,
            "PulsePosition": 0,
            "LoopCrossfadeLength": 0,
            "LoopCrossfadeType": 0,
            "TailLength": 0.0,
            "TailLoopPosition": 0.5,
        }
        trk_samples.append(
            {
                "version": 1,
                "name": wav_p.stem,
                "path": wav_p.name,
                "loadImpl": 0,
                "metadata": {"tempo": 0.0, "rootNote": 60, "tune": 0.0, "key": "C Major"},
            }
        )
    trk["samples"] = trk_samples
    return trk


def stage_rebuild_demo_projects(
    card_root: Path,
    backup_root: Path,
    tpl: AcvsTemplateLoader,
) -> Dict[str, Any]:
    exp_root = card_root / "Expansions"
    targets: List[Tuple[Path, List[Path]]] = []

    for xpj in sorted((exp_root / "MPC Beats Demos and Templates").rglob("*.xpj")):
        if not xpj.name.startswith("."):
            targets.append((xpj, [exp_root / "MPC Beats Demos and Templates", exp_root / "MPC Beats Producer Kits"]))
    for pack, xpj_name in [
        ("80s Nostalgia", "80s Nostalgia Demo Project.xpj"),
        ("Marco Polo - BoomBap Essentials Vol 1", "Marco Polo BoomBap Vol 1 Demo Project.xpj"),
    ]:
        xpj = exp_root / pack / xpj_name
        if xpj.is_file():
            targets.append((xpj, [exp_root / pack]))
    for xpj in sorted((exp_root / "Scott Storch Presents").glob("*.xpj")):
        if not xpj.name.startswith("."):
            pd_dir = xpj.parent / f"{xpj.stem}_[ProjectData]"
            if pd_dir.is_dir() and any(
                any(not q.name.startswith(".") for q in pd_dir.glob(pat))
                for pat in ("*.sxq", "*.Drum.xpm", "*.Audio.xpm")
            ):
                targets.append((xpj, [exp_root / "Scott Storch Presents"]))

    converted = 0
    total_seqs = 0
    total_notes = 0

    for xpj_path, extra_search in targets:
        pdata_dir = xpj_path.parent / f"{xpj_path.stem}_[ProjectData]"
        if not pdata_dir.is_dir():
            continue
        _backup_before_overwrite(xpj_path, card_root, backup_root)

        xpms = sorted(
            p
            for p in list(pdata_dir.glob("*.Drum.xpm")) + list(pdata_dir.glob("*.Keygroup.xpm"))
            if not p.name.startswith(".")
        )
        program_tracks: List[Dict[str, Any]] = []
        by_exact: Dict[str, str] = {}
        by_norm: Dict[str, str] = {}

        for xm in xpms:
            if len(program_tracks) >= 16:
                break
            built = build_acvs_tracks_from_xpm(xm, extra_search, pdata_dir, tpl)
            if not built:
                continue
            trk = built[0]
            canonical_name = trk["name"]
            program_tracks.append(trk)
            try:
                el = ET.fromstring(xm.read_bytes())
                xml_pname = (el.findtext("./Program/ProgramName") or "").strip()
            except Exception:
                xml_pname = ""
            for alias in (canonical_name, xml_pname):
                if alias:
                    by_exact[alias.lower()] = canonical_name
                    by_norm[_norm_name(alias)] = canonical_name

        stems_trk = _add_audio_stems_track_if_needed(xpj_path, pdata_dir, xpms, tpl)
        if stems_trk and len(program_tracks) < 16:
            program_tracks.append(stems_trk)

        if not program_tracks:
            # Fallback for Beat Audio edge cases: keep existing single track if valid
            continue

        sxqs = sorted(
            (p for p in pdata_dir.glob("*.sxq") if not p.name.startswith(".")),
            key=lambda p: (int(p.stem) if p.stem.isdigit() else 9999, p.name),
        )
        seqs_spec: List[Dict[str, Any]] = []
        # Map xpm track name -> target track object for fallback tempo inference
        for sidx, sxq_path in enumerate(sxqs):
            dec = decode_sxq(sxq_path)
            clips: Dict[str, List[Dict[str, Any]]] = {}
            for mtrk in dec["tracks"]:
                pn = mtrk["program_name"]
                tn = mtrk["track_name"]
                matched = by_exact.get(pn.lower()) or by_norm.get(_norm_name(pn))
                if not matched and tn:
                    matched = by_exact.get(tn.lower()) or by_norm.get(_norm_name(tn))
                if not matched:
                    continue
                bucket = clips.setdefault(matched, [])
                for t_tick, n_key, vel, dur in mtrk["notes"]:
                    bucket.append(_make_acvs_note_event(t_tick, n_key, vel, dur))
                total_notes += len(mtrk["notes"])

            seq_key = (int(sxq_path.stem) - 1) if sxq_path.stem.isdigit() else sidx
            seqs_spec.append(
                {
                    "key": max(0, min(127, seq_key)),
                    "name": dec["name"],
                    "bpm": float(dec["bpm"]),
                    "length_bars": dec["length_bars"],
                    "length_pulses": dec["length_pulses"],
                    "beats_per_bar": dec["beats_per_bar"],
                    "beat_unit": dec["beat_unit"],
                    "clips": clips,
                }
            )
            total_seqs += 1

        master_bpm = float(seqs_spec[0]["bpm"]) if seqs_spec else float(hkb.infer_kit_bpm(xpj_path.stem, 120.0))
        write_acvs_project(
            xpj_path,
            program_tracks,
            seqs_spec,
            tpl,
            master_tempo=master_bpm,
            master_tempo_enabled=False,
        )
        converted += 1

    return {"demo_projects_rebuilt": converted, "sequences": total_seqs, "notes": total_notes}


# ---------------------------------------------------------------------------
# 7. Stage D: Inject .sxq Sequences into MPC Beats Producer Kits (154 kits)
# ---------------------------------------------------------------------------

def stage_inject_producer_kit_sequences(card_root: Path, tpl: AcvsTemplateLoader) -> Dict[str, Any]:
    pk_dir = card_root / "Expansions" / "MPC Beats Producer Kits"
    if not pk_dir.is_dir():
        return {"injected": 0, "notes": 0}

    injected = 0
    total_notes = 0
    for sxq in sorted(pk_dir.glob("*.sxq")):
        if sxq.name.startswith("."):
            continue
        xpj = sxq.with_suffix(".xpj")
        if not xpj.is_file():
            continue
        dec = decode_sxq(sxq)
        if not dec["tracks"]:
            continue

        raw = gzip.decompress(xpj.read_bytes()).decode("utf-8")
        jidx = raw.index("{")
        hdr = raw[:jidx]
        payload = json.loads(raw[jidx:])
        data = payload.get("data", {})
        tracks = data.get("tracks") or []
        if not tracks:
            continue

        t0_name = str(tracks[0].get("name") or sxq.stem)
        evs: List[Dict[str, Any]] = []
        for mtrk in dec["tracks"]:
            for t_tick, n_key, vel, dur in mtrk["notes"]:
                evs.append(_make_acvs_note_event(t_tick, n_key, vel, dur))
        evs.sort(key=lambda e: (e["time"], e["note"]["note"]))
        if not evs:
            continue

        bpm = float(dec["bpm"] or hkb.infer_kit_bpm(sxq.stem, 120.0))
        beats = int(dec["beats_per_bar"])
        unit = int(dec["beat_unit"])
        beat_len = int(round(DEFAULT_MPC_TICKS_PER_QUARTER * (4.0 / float(unit))))
        l_bars = int(dec["length_bars"])
        l_pulses = int(dec["length_pulses"])

        seq_obj = tpl.clone_sequence()
        seq_obj["name"] = dec["name"]
        seq_obj["bpm"] = bpm
        seq_obj["lengthBars"] = l_bars
        seq_obj["lengthPulses"] = l_pulses
        seq_obj["loopStartBar"] = 0
        seq_obj["loopEndBar"] = l_bars
        seq_obj["loopStartPulses"] = 0
        seq_obj["loopEndPulses"] = l_pulses
        seq_obj["timeSignatureTrack"] = {
            "timeSignatures": [{"beatsPerBar": beats, "beatLength": beat_len, "barStart": 0}]
        }
        clip_list = []
        for idx, trk in enumerate(tracks):
            tname = str(trk.get("name") or "")
            clip = tpl.clone_clip()
            clip["name"] = tname
            clip["startPulses"] = 0
            clip["endPulses"] = l_pulses
            clip["loopStartPulses"] = 0
            clip["loopEndPulses"] = l_pulses
            clip["eventList"]["events"] = evs if idx == 0 else []
            clip_list.append({"key": tname, "value": clip})
        seq_obj["trackClipMaps"] = [clip_list]

        data["sequences"] = [{"key": 0, "value": seq_obj}]
        data["currentSequence"] = 0
        data["masterTempo"] = bpm
        data["masterTempoEnabled"] = False
        _atomic_write_gzip_text(xpj, hdr + json.dumps(payload, indent=0))
        injected += 1
        total_notes += len(evs)

    return {"injected": injected, "notes": total_notes}


# ---------------------------------------------------------------------------
# 8. Stage E: Companion .xpj + _[ProjectData] for Official Root .xpm Packs
# ---------------------------------------------------------------------------

def stage_build_official_companion_xpjs(card_root: Path, tpl: AcvsTemplateLoader) -> Dict[str, Any]:
    exp_root = card_root / "Expansions"
    created = 0
    sxq_attached = 0
    notes_attached = 0

    for pack_name in OFFICIAL_XPM_TO_XPJ_PACKS:
        pack_dir = exp_root / pack_name
        if not pack_dir.is_dir():
            continue
        for xpm in sorted(pack_dir.glob("*.xpm")):
            if xpm.name.startswith("."):
                continue
            kit_name = xpm.stem
            xpj_path = pack_dir / f"{kit_name}.xpj"
            pdata_dir = pack_dir / f"{kit_name}_[ProjectData]"

            # Do not clobber already-built Demo/Beat projects that are handled in Stage C
            if xpj_path.is_file() and xpj_path.read_bytes()[:2] == b"\x1f\x8b":
                continue

            pdata_dir.mkdir(parents=True, exist_ok=True)
            is_loose = kit_name == "80s Nostalgia mpc exp-Loose"
            tracks = build_acvs_tracks_from_xpm(
                xpm,
                [pack_dir],
                pdata_dir,
                tpl,
                split_over_128=is_loose,
            )
            if not tracks:
                continue

            # Look for companion .sxq matching stem
            sxq_cand = pack_dir / f"{kit_name}.sxq"
            seqs_spec: List[Dict[str, Any]] = []
            sample_bpms: List[float] = []
            for trk in tracks:
                for smp in trk.get("samples", []):
                    b = hkb._extract_explicit_bpm_from_text(smp.get("path") or smp.get("name") or "")
                    if b is not None:
                        sample_bpms.append(b)
            if sample_bpms:
                from collections import Counter
                bpm = float(Counter(sample_bpms).most_common(1)[0][0])
            else:
                bpm = float(hkb.infer_kit_bpm(pdata_dir if pdata_dir.is_dir() else kit_name, 120.0))
            if sxq_cand.is_file():
                dec = decode_sxq(sxq_cand)
                if dec["tracks"]:
                    evs = []
                    for mtrk in dec["tracks"]:
                        for t_tick, n_key, vel, dur in mtrk["notes"]:
                            evs.append(_make_acvs_note_event(t_tick, n_key, vel, dur))
                    if evs:
                        bpm = float(dec["bpm"] or bpm)
                        seqs_spec.append(
                            {
                                "key": 0,
                                "name": dec["name"],
                                "bpm": bpm,
                                "length_bars": dec["length_bars"],
                                "length_pulses": dec["length_pulses"],
                                "beats_per_bar": dec["beats_per_bar"],
                                "beat_unit": dec["beat_unit"],
                                "clips": {tracks[0]["name"]: evs},
                            }
                        )
                        sxq_attached += 1
                        notes_attached += len(evs)

            write_acvs_project(
                xpj_path,
                tracks,
                seqs_spec,
                tpl,
                master_tempo=bpm,
                master_tempo_enabled=False,
            )
            created += 1

    return {"created": created, "sxq_attached": sxq_attached, "notes_attached": notes_attached}


# ---------------------------------------------------------------------------
# 9. Stage F: Rebuild WAV-Only Packs + Serato/Custom_Kits Gaps (Zero Truncation)
# ---------------------------------------------------------------------------

def _folder_kit_base(rel_dir: Path, pack_root_name: str, used_stems: set[str]) -> str:
    if str(rel_dir) == ".":
        base = pack_root_name
    else:
        parts = list(rel_dir.parts)
        if len(parts) == 1:
            base = parts[0]
        else:
            # Preserve meaningful hierarchy so folders like vocal_kits/140_fire_Dm/verses_Dm/dry stay distinct
            filtered = [p for p in parts if p.lower() not in ("vocal_kits", "one_shots", "loops", "drums")]
            if not filtered:
                filtered = parts
            base = "_".join(filtered[-3:] if len(filtered) >= 3 else filtered)
    stem = _safe_kit_stem(base, limit=42)
    cand = stem
    n = 2
    while cand.lower() in used_stems:
        suffix = f"_{n}"
        cand = stem[: max(1, 42 - len(suffix))] + suffix
        n += 1
    used_stems.add(cand.lower())
    return cand


def _populate_wav_folder_kits(
    target_root: Path,
    pack_label: str,
    tpl: AcvsTemplateLoader,
    *,
    previews_dir: Optional[Path] = None,
    only_missing_folders: bool = False,
) -> Tuple[int, int]:
    """Create <=64-pad `.xpm` + `.xpj` + `_[ProjectData]` kits for every WAV folder under `target_root`."""
    xpms_made = 0
    xpjs_made = 0
    used_stems: set[str] = set()

    for dp, dns, fns in os.walk(target_root):
        dp_p = Path(dp)
        dns[:] = sorted(
            d
            for d in dns
            if not d.startswith(".")
            and d not in ("[Previews]", "__MACOSX")
            and not d.endswith(("_[ProjectData]", "_[TrackData]", "_[ProgramData]"))
        )
        wavs = sorted(f for f in fns if not f.startswith(".") and f.lower().endswith(".wav"))
        if not wavs:
            continue
        if only_missing_folders:
            has_existing = any(
                not f.startswith(".") and f.lower().endswith((".xpm", ".xpj", ".xty"))
                for f in fns
            )
            if has_existing:
                continue

        rel_p = dp_p.relative_to(target_root)
        base_kit = _folder_kit_base(rel_p, pack_label, used_stems)
        chunks = [wavs[i : i + 64] for i in range(0, len(wavs), 64)]

        for cidx, chunk in enumerate(chunks, 1):
            kit_name = base_kit if len(chunks) == 1 else f"{base_kit}_V{cidx}"
            if len(kit_name) > 48:
                kit_name = f"{base_kit[:42]}_V{cidx}"

            pdata_dir = dp_p / f"{kit_name}_[ProjectData]"
            pdata_dir.mkdir(parents=True, exist_ok=True)

            kit_bpm = float(hkb.infer_kit_bpm(f"{dp_p.name} {chunk[0]}", fallback=120.0))
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
            for pad_num, wf in enumerate(chunk, 1):
                src_wav = dp_p / wf
                copied_wav = _ensure_sample_in_dir(src_wav, pdata_dir)
                n_frames = hkb._get_wav_frames(copied_wav)
                stype = hkb.detect_sound_type(wf)
                vol = float(hkb.compute_smart_pad_volume(stype, src_wav)["volume"])
                mute = int(hkb.mute_group_for_profile(stype, wf, profile="club_clean"))
                oneshot = stype not in ("MELODY_LOOP", "PAD", "VOCAL", "LOOP")

                pads_xpm[pad_num] = {
                    "sample_file": wf,
                    "sample_name": Path(wf).stem,
                    "source_path": str(src_wav),
                    "n_frames": n_frames,
                    "sound_type": stype,
                    "volume": vol,
                    "pan": 0.5,
                    "tune": 0,
                    "mute_group": mute,
                    "trigger_mode": "oneshot" if oneshot else "noteon",
                    "monophonic": True,
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
                lay0["sampleName"] = Path(wf).stem
                lay0["sliceIndex"] = 129
                lay0["volume"] = {"gainCoefficient": 1.0, "controlValue": 1.0, "law": 1}
                lay0["sliceInfo"] = {
                    "Start": 0,
                    "End": int(n_frames),
                    "LoopStart": 0,
                    "LoopMode": 0,
                    "PulsePosition": 0,
                    "LoopCrossfadeLength": 0,
                    "LoopCrossfadeType": 0,
                    "TailLength": 0.0,
                    "TailLoopPosition": 0.5,
                }
                linked_samples.append(
                    {
                        "version": 1,
                        "name": Path(wf).stem,
                        "path": wf,
                        "loadImpl": 0,
                        "metadata": {"tempo": 0.0, "rootNote": 60, "tune": 0.0, "key": "C Major"},
                    }
                )

            trk["samples"] = linked_samples

            xpm_out = dp_p / f"{kit_name}.xpm"
            tpl.write_fast_xpm(kit_name, pads_xpm, xpm_out)
            xpms_made += 1

            xpj_out = dp_p / f"{kit_name}.xpj"
            write_acvs_project(
                xpj_out,
                [trk],
                [],
                tpl,
                master_tempo=kit_bpm,
                master_tempo_enabled=False,
            )
            xpjs_made += 1

            if previews_dir is not None and chunk:
                previews_dir.mkdir(parents=True, exist_ok=True)
                prev_out = previews_dir / f"{kit_name}.wav"
                if not prev_out.is_file():
                    shutil.copy2(dp_p / chunk[0], prev_out)

    return xpms_made, xpjs_made


def stage_rebuild_wav_packs_and_gaps(card_root: Path, tpl: AcvsTemplateLoader) -> Dict[str, Any]:
    exp_root = card_root / "Expansions"
    results: Dict[str, Tuple[int, int]] = {}

    for pack_name in WAV_ONLY_PACKS:
        pack_dir = exp_root / pack_name
        if not pack_dir.is_dir():
            continue
        # Remove previously truncated generated .xpm and empty _[ProjectData] while keeping all WAVs & Expansion.xml/Artwork
        for old_xpm in list(pack_dir.rglob("*.xpm")):
            old_xpm.unlink()
        for old_xpj in list(pack_dir.rglob("*.xpj")):
            old_xpj.unlink()
        for dp, dns, _ in os.walk(pack_dir):
            for d in list(dns):
                if d.endswith("_[ProjectData]"):
                    shutil.rmtree(Path(dp) / d, ignore_errors=True)
                    dns.remove(d)
        prev_dir = pack_dir / "[Previews]"
        if prev_dir.is_dir():
            for f in list(prev_dir.glob("*.wav")):
                f.unlink()

        xpms, xpjs = _populate_wav_folder_kits(pack_dir, pack_name, tpl, previews_dir=prev_dir)
        results[pack_name] = (xpms, xpjs)

    # Fill ONLY true WAV-only top-level folders inside Custom_Kits (ignore NI_Maschine/SP404/EP133 export subdirs of existing kits)
    ck_root = card_root / "Custom_Kits"
    if ck_root.is_dir():
        ck_xpms = 0
        ck_xpjs = 0
        for kit_dir in sorted(ck_root.iterdir()):
            if not kit_dir.is_dir() or kit_dir.name.startswith("."):
                continue
            has_mpc = any(
                not p.name.startswith(".")
                for p in list(kit_dir.rglob("*.xpm")) + list(kit_dir.rglob("*.xpj"))
            )
            if has_mpc:
                continue
            src_wavs = sorted(
                w
                for w in kit_dir.rglob("*.wav")
                if not w.name.startswith(".")
                and not any(part.startswith(".") or part.endswith("_[ProjectData]") for part in w.relative_to(kit_dir).parts)
            )
            if not src_wavs:
                continue
            akai_dir = kit_dir / "Akai_MPC"
            akai_dir.mkdir(parents=True, exist_ok=True)
            kit_name = kit_dir.name
            pdata_dir = akai_dir / f"{kit_name}_[ProjectData]"
            pdata_dir.mkdir(parents=True, exist_ok=True)

            kit_bpm = float(hkb.infer_kit_bpm(f"{kit_name} {src_wavs[0].stem}", fallback=120.0))
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
            for pad_num, src_wav in enumerate(src_wavs[:64], 1):
                copied_top = _ensure_sample_in_dir(src_wav, akai_dir)
                _ensure_sample_in_dir(src_wav, pdata_dir)
                wf = copied_top.name
                n_frames = hkb._get_wav_frames(copied_top)
                stype = hkb.detect_sound_type(wf)
                vol = float(hkb.compute_smart_pad_volume(stype, copied_top)["volume"])
                mute = int(hkb.mute_group_for_profile(stype, wf, profile="club_clean"))
                oneshot = stype not in ("MELODY_LOOP", "PAD", "VOCAL", "LOOP")
                pads_xpm[pad_num] = {
                    "sample_file": wf,
                    "sample_name": copied_top.stem,
                    "source_path": str(copied_top),
                    "n_frames": n_frames,
                    "sound_type": stype,
                    "volume": vol,
                    "pan": 0.5,
                    "tune": 0,
                    "mute_group": mute,
                    "trigger_mode": "oneshot" if oneshot else "noteon",
                    "monophonic": True,
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
                lay0["sampleName"] = copied_top.stem
                lay0["sliceIndex"] = 129
                lay0["volume"] = {"gainCoefficient": 1.0, "controlValue": 1.0, "law": 1}
                lay0["sliceInfo"] = {
                    "Start": 0,
                    "End": int(n_frames),
                    "LoopStart": 0,
                    "LoopMode": 0,
                    "PulsePosition": 0,
                    "LoopCrossfadeLength": 0,
                    "LoopCrossfadeType": 0,
                    "TailLength": 0.0,
                    "TailLoopPosition": 0.5,
                }
                linked_samples.append(
                    {
                        "version": 1,
                        "name": copied_top.stem,
                        "path": wf,
                        "loadImpl": 0,
                        "metadata": {"tempo": 0.0, "rootNote": 60, "tune": 0.0, "key": "C Major"},
                    }
                )
            trk["samples"] = linked_samples
            tpl.write_fast_xpm(kit_name, pads_xpm, akai_dir / f"{kit_name}.xpm")
            ck_xpms += 1
            write_acvs_project(
                akai_dir / f"{kit_name}.xpj",
                [trk],
                [],
                tpl,
                master_tempo=kit_bpm,
                master_tempo_enabled=False,
            )
            ck_xpjs += 1
        results["Custom_Kits (WAV gaps)"] = (ck_xpms, ck_xpjs)

    return results


# ---------------------------------------------------------------------------
# 10. Main Orchestration
# ---------------------------------------------------------------------------

def run_repair(
    card_root: Path,
    downloads_root: Path,
    backup_historico: Path,
) -> Dict[str, Any]:
    if not card_root.is_dir():
        raise SystemExit(f"Card root not found: {card_root}")
    free_gb = shutil.disk_usage(card_root).free / (1024 ** 3)
    print(f"Target card: {card_root} (free: {free_gb:.2f} GB)")

    tpl = AcvsTemplateLoader()
    backup_root = card_root / "_RAW_SOURCE_ARCHIVES" / "pre_repair_20261119"

    print("\n=== Stage A: Restoring missing sources, Lofi Boom Demo backup, and fixing .wav.wav ===")
    st_a = stage_restore_sources_and_paths(card_root, downloads_root, backup_historico, backup_root)
    print("Stage A:", json.dumps(st_a))

    print("\n=== Stage B: Converting Classic Drum Machines (.xtd -> .xpm + .xpj) & patching Demo ===")
    st_b = stage_classic_drum_machines(card_root, backup_root, tpl)
    print("Stage B:", json.dumps(st_b))

    print("\n=== Stage C: Rebuilding Multi-Track Demo/Beat XPJs (MPC2 XML + MPC Beats Demos) ===")
    st_c = stage_rebuild_demo_projects(card_root, backup_root, tpl)
    print("Stage C:", json.dumps(st_c))

    print("\n=== Stage D: Injecting .sxq sequences into MPC Beats Producer Kits ===")
    st_d = stage_inject_producer_kit_sequences(card_root, tpl)
    print("Stage D:", json.dumps(st_d))

    print("\n=== Stage E: Generating companion .xpj + _[ProjectData] for Official Root .xpm Packs ===")
    st_e = stage_build_official_companion_xpjs(card_root, tpl)
    print("Stage E:", json.dumps(st_e))

    print("\n=== Stage F: Rebuilding 5 WAV-only Packs + Serato/Custom_Kits gaps (64-pad kits, 0 truncation) ===")
    st_f = stage_rebuild_wav_packs_and_gaps(card_root, tpl)
    print("Stage F:", json.dumps(st_f))

    free_after_gb = shutil.disk_usage(card_root).free / (1024 ** 3)
    print(f"\nRepair completed. Free space on {card_root}: {free_after_gb:.2f} GB")
    if free_after_gb < 35.0:
        raise RuntimeError(f"Safety threshold breached: free space dropped to {free_after_gb:.2f} GB (< 35 GB)")
    return {"stage_a": st_a, "stage_b": st_b, "stage_c": st_c, "stage_d": st_d, "stage_e": st_e, "stage_f": st_f, "free_gb": round(free_after_gb, 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair Akai MPC / Melodee Expansions & Sequences")
    parser.add_argument("--card", default="/Volumes/MPCSMPL", help="Mounted MPC SD card root")
    parser.add_argument(
        "--downloads",
        default=str(Path.home() / "Downloads" / "LIBRERIAS MPC SAMPLE DE AKAI Y MAS"),
        help="Original downloaded expansions folder",
    )
    parser.add_argument(
        "--backup-historico",
        default="/Volumes/Realtek RTL9210B-CG Media/BACKUP_HISTORICO_MPCSMPL/auditoria-mpc-sample-20261016T101919Z/backup",
        help="Historical backup root for damaged Demo projects",
    )
    args = parser.parse_args()
    run_repair(Path(args.card), Path(args.downloads), Path(args.backup_historico))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
