#!/usr/bin/env python3
"""Idempotent normalizer for Akai MPC Expansions & Custom_Kits on SD Card.

Repairs cleanly without breaking ACVS 1.3.0.12 floats or SampQOL-OS invariants:
1. SliceEnd / sliceInfo.End placeholder truncation (`300000`, `500000`, or > n_frames)
   -> restores exact WAV PCM frame count for single-pad unchopped layers; `0` on inactive layers.
2. BPM mismatches in `.xpj` projects without MIDI events -> aligns `masterTempo` and
   sequence BPMs to embedded loop tempo (`[156]`, `90BPM`, loop numbers).
3. `club_clean` choke groups (`KICK/SNARE=1, HIHAT=2, BASS_808=4, TOM=5`) on Expansion Drum kits.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import hardware_kit_builder as hkb  # noqa: E402

ACVS_HEADER = "ACVS\n1.3.0.12\nSerialisableProjectData\njson\nLinux\n"
PLACEHOLDER_ENDS = {300000, 500000}

BPM_EXCLUDED_PACKS = {
    "Astro1Deep - Bolero & Ranchera 1950s (Mono Vinyl)",
    "MPC Beats Demos and Templates",
}

CLUB_CLEAN_EXCLUDED_PACKS = {
    "F9 Instruments Beats Edition",
    "MPC Samples - Real Horns",
    "Astro1Deep - Bolero & Ranchera 1950s (Mono Vinyl)",
    "Vocal Destiny",
    "MPC Beats Demos and Templates",
}

FORBIDDEN_PARTS = {
    "autorun",
    "autorun-melodee-v0.4.0",
    "Melodee",
    "_RAW_SOURCE_ARCHIVES",
    "BACKUPS_SEGURIDAD",
    "BeatOS",
}

_BRACK_BPM_RE = re.compile(r"\[(\d{2,3}(?:\.\d+)?)\]")
_EXPLICIT_BPM_RE = re.compile(
    r"(?:^|[\s_\-\(\[\.])(\d{2,3}(?:\.\d)?)\s*bpm(?![a-z0-9])"
    r"|bpm[\s_\-]*(\d{2,3}(?:\.\d)?)(?:$|[\s_\-\)\]\.])",
    re.I,
)
_LOOP_HINT_RE = re.compile(
    r"loop|stem|combo|break|beat|top|full|melod|chord|chrd|arp|riff|music|bassline|drum\s*lp|lp\d|hat\s*lp|perc\s*lp|[\[\(]\d{2,3}[\]\)]",
    re.I,
)
_KEYGROUP_NOTE_RE = re.compile(r"-\d{3}\s+[A-G][#b]?\d", re.I)
_TRAILING_NUM_RE = re.compile(r"(?:^|[\s_\-])(6\d|7\d|8\d|9\d|1[0-8]\d)(?:[\s_\-\.]|$)")
_BPM_FALSE_POS = {101, 102, 103, 104, 105, 106, 107, 108, 109, 127}


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp", delete=False
        ) as tf:
            tmp_path = Path(tf.name)
            tf.write(payload)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, target)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _backup_once(card: Path, backup_root: Path, src: Path) -> None:
    rel = src.resolve().relative_to(card.resolve())
    dst = backup_root / rel
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _is_forbidden_path(card: Path, target: Path) -> bool:
    rel = target.resolve().relative_to(card.resolve())
    parts = rel.parts
    if not parts:
        return True
    if parts[0] in FORBIDDEN_PARTS or target.name == "mpcqol.conf":
        return True
    if len(parts) >= 2 and parts[0] == "MPC-Sample" and parts[1] == "Projects":
        return True
    return False


def get_wav_frames(path: Path, cache: Dict[str, int]) -> int:
    key = str(path)
    if key in cache:
        return cache[key]
    n_frames = 0
    try:
        sz = path.stat().st_size
        with path.open("rb") as fh:
            head = fh.read(12)
            if len(head) == 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
                pos = 12
                block_align = 0
                data_sz = 0
                while pos + 8 <= sz:
                    fh.seek(pos)
                    hdr = fh.read(8)
                    if len(hdr) < 8:
                        break
                    cid = hdr[:4]
                    csz = struct.unpack("<I", hdr[4:8])[0]
                    if cid == b"fmt " and csz >= 14:
                        fb = fh.read(14)
                        if len(fb) == 14:
                            block_align = struct.unpack("<H", fb[12:14])[0]
                    elif cid == b"data":
                        data_sz = csz
                        break
                    pos += 8 + csz + (csz & 1)
                if block_align > 0 and data_sz > 0:
                    n_frames = int(data_sz // block_align)
    except OSError:
        n_frames = 0
    cache[key] = n_frames
    return n_frames


def extract_project_bpm(xpj_stem: str, sample_names: List[str]) -> Optional[float]:
    """Infer genuine tempo from loop filenames `[156]`, `90BPM`, or loop numbers."""
    brack: List[float] = []
    for n in sample_names:
        for m in _BRACK_BPM_RE.finditer(n):
            v = float(m.group(1))
            if 55.0 <= v <= 200.0:
                brack.append(round(v, 2))
    if brack:
        return float(Counter(brack).most_common(1)[0][0])

    expl_samples: List[float] = []
    for n in sample_names:
        for m in _EXPLICIT_BPM_RE.finditer(n):
            v = float(m.group(1) or m.group(2))
            if 55.0 <= v <= 200.0:
                expl_samples.append(round(v, 2))
    if expl_samples:
        return float(Counter(expl_samples).most_common(1)[0][0])

    for m in _EXPLICIT_BPM_RE.finditer(xpj_stem):
        v = float(m.group(1) or m.group(2))
        if 55.0 <= v <= 200.0:
            return float(round(v, 2))

    loop_nums: List[float] = []
    for n in sample_names:
        stem = Path(n).stem
        if _KEYGROUP_NOTE_RE.search(stem):
            continue
        if _LOOP_HINT_RE.search(stem):
            for m in _TRAILING_NUM_RE.finditer(stem):
                iv = int(m.group(1))
                if 60 <= iv <= 185 and iv not in _BPM_FALSE_POS:
                    loop_nums.append(float(iv))
    if loop_nums:
        top, cnt = Counter(loop_nums).most_common(1)[0]
        if len(set(loop_nums)) == 1 or cnt >= 2:
            return float(top)
    return None


def _resolve_xpm_wav(folder: Path, pdata: Path, sf: str, sn: str) -> Optional[Path]:
    cands: List[str] = []
    if sf:
        cands.append(sf)
    if sn:
        cands.extend([sn, f"{sn}.wav", f"{sn}.WAV"])
    for c in cands:
        p1 = folder / c
        if p1.is_file() and p1.suffix.lower() == ".wav":
            return p1
        if pdata.is_dir():
            p2 = pdata / c
            if p2.is_file() and p2.suffix.lower() == ".wav":
                return p2
    return None


def _normalize_int_text(val: Optional[str], default: int = 0) -> int:
    try:
        if val is None or not val.strip():
            return default
        return int(round(float(val.strip())))
    except (TypeError, ValueError):
        return default


def _top_pack_name(card: Path, file_path: Path) -> Tuple[str, Optional[str]]:
    rel = file_path.resolve().relative_to(card.resolve())
    area = rel.parts[0]
    pack = rel.parts[1] if len(rel.parts) >= 2 and area == "Expansions" else None
    return area, pack


def _normalize_xpm(
    xpm_path: Path,
    card: Path,
    backup_root: Path,
    wav_cache: Dict[str, int],
    *,
    apply_chokes: bool,
    dry_run: bool,
) -> Dict[str, int]:
    res = {"updated": 0, "end_fixed": 0, "chokes_updated": 0, "errors": 0}
    if _is_forbidden_path(card, xpm_path):
        return res
    try:
        with xpm_path.open("rb") as fh:
            if fh.read(4) == b"RIFF":
                return res
        tree = ET.parse(str(xpm_path))
    except Exception:
        res["errors"] = 1
        return res

    root = tree.getroot()
    prog = root.find("Program")
    if prog is None:
        return res

    ptype = (prog.attrib.get("type") or "Drum").strip()
    folder = xpm_path.parent
    pdata = folder / f"{xpm_path.stem}_[ProjectData]"

    # Count WAV references across active layers to avoid overwriting genuine multi-pad chops
    file_use_count: Counter[str] = Counter()
    active_layers_meta: List[Tuple[ET.Element, str, str, Optional[Path]]] = []
    for lay in prog.findall(".//Instrument/Layers/Layer"):
        is_act = (lay.findtext("Active") or "").strip().lower() == "true"
        sf = (lay.findtext("SampleFile") or "").strip()
        sn = (lay.findtext("SampleName") or "").strip()
        if not is_act or (not sf and not sn):
            continue
        wp = _resolve_xpm_wav(folder, pdata, sf, sn)
        key = wp.name.lower() if wp is not None else (sf or sn).lower()
        file_use_count[key] += 1
        active_layers_meta.append((lay, key, sf or sn, wp))

    changed = False

    # 1. Repair truncated / placeholder SliceEnd on active & inactive layers
    for inst in prog.findall("./Instruments/Instrument"):
        for lay in inst.findall("./Layers/Layer"):
            is_act = (lay.findtext("Active") or "").strip().lower() == "true"
            sf = (lay.findtext("SampleFile") or "").strip()
            sn = (lay.findtext("SampleName") or "").strip()
            se_el = lay.find("SliceEnd")
            ss_el = lay.find("SliceStart")
            cur_se = _normalize_int_text(se_el.text if se_el is not None else None, 0)
            cur_ss = _normalize_int_text(ss_el.text if ss_el is not None else None, 0)

            if not is_act or (not sf and not sn):
                if se_el is not None and cur_se in PLACEHOLDER_ENDS:
                    se_el.text = "0"
                    changed = True
                    res["end_fixed"] += 1
                continue

            wp = _resolve_xpm_wav(folder, pdata, sf, sn)
            if wp is None:
                continue
            key = wp.name.lower()
            if file_use_count[key] > 1 or cur_ss != 0:
                continue
            n_frames = get_wav_frames(wp, wav_cache)
            if n_frames > 0 and (cur_se in PLACEHOLDER_ENDS or cur_se == 0 or cur_se > n_frames):
                if cur_se != n_frames and se_el is not None:
                    se_el.text = str(n_frames)
                    changed = True
                    res["end_fixed"] += 1

    # 2. Apply club_clean MuteGroup on Drum Programs in non-excluded Expansions
    if apply_chokes and ptype == "Drum":
        for inst in prog.findall("./Instruments/Instrument"):
            first_ref = None
            for lay in inst.findall("./Layers/Layer"):
                if (lay.findtext("Active") or "").strip().lower() == "true":
                    sf = (lay.findtext("SampleFile") or "").strip()
                    sn = (lay.findtext("SampleName") or "").strip()
                    if sf or sn:
                        first_ref = sf or sn
                        break
            if not first_ref:
                continue
            stype = hkb.detect_sound_type(first_ref)
            target_mg = int(hkb.mute_group_for_profile(stype, first_ref, profile="club_clean"))
            mg_el = inst.find("MuteGroup")
            cur_mg = _normalize_int_text(mg_el.text if mg_el is not None else None, 0)
            if mg_el is not None and cur_mg != target_mg:
                mg_el.text = str(target_mg)
                changed = True
                res["chokes_updated"] += 1

    if changed:
        res["updated"] = 1
        if not dry_run:
            _backup_once(card, backup_root, xpm_path)
            xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            _atomic_write_bytes(xpm_path, xml_bytes)
    return res


def _preserve_acvs_floats(data: Dict[str, Any]) -> None:
    if "masterTempo" in data:
        data["masterTempo"] = float(data["masterTempo"])
    for seq_entry in data.get("sequences") or []:
        sv = seq_entry.get("value")
        if isinstance(sv, dict) and "bpm" in sv:
            sv["bpm"] = float(sv["bpm"])
    for trk in data.get("tracks") or []:
        if "volume" in trk:
            trk["volume"] = float(trk["volume"])
        if "pan" in trk:
            trk["pan"] = float(trk["pan"])
        prog = trk.get("program") or {}
        if isinstance(prog.get("mixable"), dict):
            if "volume" in prog["mixable"]:
                prog["mixable"]["volume"] = float(prog["mixable"]["volume"])
            if "pan" in prog["mixable"]:
                prog["mixable"]["pan"] = float(prog["mixable"]["pan"])


def _normalize_xpj(
    xpj_path: Path,
    card: Path,
    backup_root: Path,
    wav_cache: Dict[str, int],
    *,
    allow_bpm: bool,
    apply_chokes: bool,
    dry_run: bool,
) -> Dict[str, int]:
    res = {"updated": 0, "end_fixed": 0, "bpm_fixed": 0, "chokes_updated": 0, "errors": 0}
    if _is_forbidden_path(card, xpj_path):
        return res

    try:
        raw = xpj_path.read_bytes()
        if raw[:2] != b"\x1f\x8b":
            return res
        txt = gzip.decompress(raw).decode("utf-8")
        jidx = txt.index("{")
        hdr = txt[:jidx]
        if not hdr.startswith("ACVS\n"):
            return res
        payload = json.loads(txt[jidx:])
    except Exception:
        res["errors"] = 1
        return res

    data = payload.get("data")
    if not isinstance(data, dict):
        return res

    pdata = xpj_path.parent / f"{xpj_path.stem}_[ProjectData]"
    changed = False
    sample_names: List[str] = []

    tracks = data.get("tracks") or []
    is_demo = "demo project" in xpj_path.stem.lower()

    # 1. Fix SliceInfo.End & collect sample names & normalize club_clean on Drum tracks
    for trk in tracks:
        prog = trk.get("program") or {}
        ptype = int(prog.get("type", 0))
        drum = prog.get("drum") or {}
        insts = drum.get("instruments") or []

        # Count sampleFile usage across active layers inside this track
        file_use_count: Counter[str] = Counter()
        for inst in insts:
            for lay in inst.get("layersv") or []:
                if not lay.get("active"):
                    continue
                sf = (lay.get("sampleFile") or "").strip()
                if sf:
                    file_use_count[sf.lower()] += 1
                    sample_names.append(sf)

        for inst in insts:
            first_sf: Optional[str] = None
            for lay in inst.get("layersv") or []:
                if not lay.get("active"):
                    continue
                sf = (lay.get("sampleFile") or "").strip()
                if not sf:
                    continue
                if first_sf is None:
                    first_sf = sf
                sinfo = lay.get("sliceInfo")
                if isinstance(sinfo, dict) and file_use_count[sf.lower()] == 1:
                    s_start = int(sinfo.get("Start") or 0)
                    s_end = int(sinfo.get("End") or 0)
                    if s_start == 0:
                        wp = pdata / sf
                        if not wp.is_file():
                            wp = xpj_path.parent / sf
                        if wp.is_file() and wp.suffix.lower() == ".wav":
                            nf = get_wav_frames(wp, wav_cache)
                            if nf > 0 and (s_end in PLACEHOLDER_ENDS or s_end == 0 or s_end > nf):
                                if s_end != nf:
                                    sinfo["End"] = int(nf)
                                    changed = True
                                    res["end_fixed"] += 1

            if apply_chokes and ptype == 0 and not is_demo and first_sf is not None:
                stype = hkb.detect_sound_type(first_sf)
                target_mg = int(hkb.mute_group_for_profile(stype, first_sf, profile="club_clean"))
                cur_mg = int(inst.get("whichMuteGroup") or 0)
                mix = inst.get("mixable")
                cur_mix_mg = int(mix.get("muteGroup") or 0) if isinstance(mix, dict) else target_mg
                if cur_mg != target_mg or cur_mix_mg != target_mg:
                    inst["whichMuteGroup"] = int(target_mg)
                    if isinstance(mix, dict):
                        mix["muteGroup"] = int(target_mg)
                    changed = True
                    res["chokes_updated"] += 1

    # Also gather sample paths from data['samples'] if any track missed them
    for s in data.get("samples") or []:
        sp = (s.get("path") or s.get("name") or "").strip()
        if sp and sp not in sample_names:
            sample_names.append(sp)

    # 2. Repair BPM if allow_bpm and project has zero MIDI events
    if allow_bpm:
        seqs = data.get("sequences") or []
        total_events = 0
        for s in seqs:
            sv = s.get("value") or {}
            for cmap in sv.get("trackClipMaps") or []:
                for clip in cmap or []:
                    evs = ((clip.get("value") or {}).get("eventList") or {}).get("events") or []
                    total_events += len(evs)
        if total_events == 0:
            inferred_bpm = extract_project_bpm(xpj_path.stem, sample_names)
            if inferred_bpm is not None:
                cur_m = float(data.get("masterTempo") or 0.0)
                cur_seq0 = float((seqs[0].get("value") or {}).get("bpm") or 0.0) if seqs else cur_m
                cur_eff = cur_seq0 if cur_seq0 > 0 else cur_m
                if abs(cur_eff - inferred_bpm) >= 1.0 or abs(cur_m - inferred_bpm) >= 1.0:
                    data["masterTempo"] = float(inferred_bpm)
                    data["masterTempoEnabled"] = True
                    for s in seqs:
                        sv = s.get("value")
                        if isinstance(sv, dict):
                            sv["bpm"] = float(inferred_bpm)
                            sv["tempoEnable"] = True
                    changed = True
                    res["bpm_fixed"] = 1

    if changed:
        res["updated"] = 1
        if not dry_run:
            _preserve_acvs_floats(data)
            _backup_once(card, backup_root, xpj_path)
            gz = gzip.compress((hdr + json.dumps(payload, indent=0)).encode("utf-8"), mtime=0)
            _atomic_write_bytes(xpj_path, gz)

    return res


def normalize_card(card_root: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    card = card_root.resolve()
    if not card.is_dir():
        raise FileNotFoundError(f"Card root not found: {card}")

    backup_root = card / "_RAW_SOURCE_ARCHIVES" / "pre_club_bpm_end_20261121"
    wav_cache: Dict[str, int] = {}

    stats: Dict[str, int] = {
        "xpm_scanned": 0,
        "xpm_updated": 0,
        "xpm_end_layers_fixed": 0,
        "xpm_chokes_updated": 0,
        "xpj_scanned": 0,
        "xpj_updated": 0,
        "xpj_end_layers_fixed": 0,
        "xpj_bpm_fixed": 0,
        "xpj_chokes_updated": 0,
        "errors": 0,
    }

    scan_dirs = [card / d for d in ("Expansions", "Custom_Kits") if (card / d).is_dir()]
    for sdir in scan_dirs:
        for root_str, dirs, files in os.walk(str(sdir)):
            dirs[:] = sorted(
                d
                for d in dirs
                if not d.startswith(".")
                and d not in FORBIDDEN_PARTS
                and not d.endswith(("_[ProjectData]", "_[TrackData]", "_[ProgramData]"))
            )
            cur_dir = Path(root_str)
            for fn in sorted(files):
                if fn.startswith("."):
                    continue
                fp = cur_dir / fn
                area, pack = _top_pack_name(card, fp)
                low = fn.lower()
                if low.endswith(".xpm"):
                    stats["xpm_scanned"] += 1
                    apply_chokes = area == "Expansions" and (pack not in CLUB_CLEAN_EXCLUDED_PACKS)
                    r = _normalize_xpm(
                        fp, card, backup_root, wav_cache, apply_chokes=apply_chokes, dry_run=dry_run
                    )
                    stats["xpm_updated"] += r["updated"]
                    stats["xpm_end_layers_fixed"] += r["end_fixed"]
                    stats["xpm_chokes_updated"] += r["chokes_updated"]
                    stats["errors"] += r["errors"]
                elif low.endswith(".xpj"):
                    stats["xpj_scanned"] += 1
                    allow_bpm = pack not in BPM_EXCLUDED_PACKS
                    apply_chokes = area == "Expansions" and (pack not in CLUB_CLEAN_EXCLUDED_PACKS)
                    r = _normalize_xpj(
                        fp,
                        card,
                        backup_root,
                        wav_cache,
                        allow_bpm=allow_bpm,
                        apply_chokes=apply_chokes,
                        dry_run=dry_run,
                    )
                    stats["xpj_updated"] += r["updated"]
                    stats["xpj_end_layers_fixed"] += r["end_fixed"]
                    stats["xpj_bpm_fixed"] += r["bpm_fixed"]
                    stats["xpj_chokes_updated"] += r["chokes_updated"]
                    stats["errors"] += r["errors"]

    return {
        "card": str(card),
        "mode": "DRY_RUN" if dry_run else "LIVE",
        "backup_dir": str(backup_root),
        "stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize SliceEnd, Loop BPM, and club_clean chokes on MPC SD Card")
    parser.add_argument("--card", default="/Volumes/MPC-SAMPL3", help="Mounted MPC SD card path")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and report without modifying files")
    args = parser.parse_args()

    result = normalize_card(Path(args.card), dry_run=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["stats"]["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
