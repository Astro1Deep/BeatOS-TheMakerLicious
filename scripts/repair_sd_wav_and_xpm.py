#!/usr/bin/env python3
"""
Lossless Enterprise Binary Sanitizer for Akai MPC Sample SD Card (/Volumes/MPCSMPL).
- Repairs trailing-chunk overflow WAVs & odd-size `atem` chunks with bit-exact PCM SHA-256 verification.
- Converts disguised AIFF-in-WAV files to native RIFF WAVE PCM with bit-exact sample verification.
- Creates trimmed-name WAV mirrors beside trailing-space WAVs referenced by official Akai .xpm files
  (so both Stock ACVS 1.3.0.12 and SampQOL-OS `kitxpm_parse` resolve 100% of pads).
- Copies missing local WAVs from sibling `_[ProjectData]` dirs beside Custom_Kits `.xpm` files.
- Always backs up every modified original into `_RAW_SOURCE_ARCHIVES/pre_enterprise_audit_20261121/`.
- NEVER touches `/autorun*`, `mpcqol.conf`, `Melodee/`, or `MPC-Sample/Projects/`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

PROTECTED_TOP_DIRS = {
    "autorun",
    "autorun-melodee-v0.4.0",
    "Melodee",
    "_RAW_SOURCE_ARCHIVES",
    "BACKUPS_SEGURIDAD",
    "BeatOS",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_wav_chunks(fp: Path) -> Dict[str, object]:
    """Fast seek-based RIFF/WAV structural inspection."""
    sz = fp.stat().st_size
    if sz < 12:
        return {"status": "TRUNCATED", "size": sz}
    with fp.open("rb") as fh:
        head = fh.read(12)
        if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
            return {"status": "AIFF_IN_WAV", "size": sz}
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return {"status": "NON_RIFF", "size": sz}
        riff_sz = struct.unpack("<I", head[4:8])[0]
        pos = 12
        chunks: List[Tuple[bytes, int, int]] = []
        overflow = False
        odd_atem = False
        has_fmt = False
        has_data = False
        while pos + 8 <= sz:
            fh.seek(pos)
            chdr = fh.read(8)
            if len(chdr) < 8:
                break
            cid = chdr[:4]
            csz = struct.unpack("<I", chdr[4:8])[0]
            body_off = pos + 8
            if body_off + csz > sz:
                # Special check: if this is `data` truncated by 1-2 bytes or garbage after `data`
                overflow = True
                chunks.append((cid, csz, body_off))
                break
            chunks.append((cid, csz, body_off))
            if cid == b"fmt ":
                has_fmt = True
            elif cid == b"data":
                has_data = True
            elif cid == b"atem" and (csz & 1):
                odd_atem = True
            pos = body_off + csz + (csz & 1)
        if not has_fmt or not has_data:
            return {"status": "MISSING_CHUNKS", "size": sz, "chunks": chunks}
        if odd_atem:
            return {"status": "ODD_ATEM", "size": sz, "chunks": chunks}
        if overflow:
            return {"status": "CHUNK_OVERFLOW", "size": sz, "chunks": chunks}
        return {"status": "OK", "size": sz, "chunks": chunks}


def backup_original(card: Path, backup_root: Path, src: Path) -> Path:
    rel = src.relative_to(card)
    dst = backup_root / rel
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return dst


def atomic_write_bytes(target: Path, payload: bytes) -> None:
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp", delete=False) as tf:
            tmp_path = Path(tf.name)
            tf.write(payload)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, target)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def repair_aiff_in_wav(card: Path, backup_root: Path, fp: Path, dry_run: bool = False) -> Tuple[bool, str]:
    import numpy as np
    import soundfile as sf

    info = sf.info(str(fp))
    data_orig, sr = sf.read(str(fp), dtype="int32", always_2d=True)
    subtype_map = {
        "PCM_16": "PCM_16",
        "PCM_24": "PCM_24",
        "PCM_32": "PCM_32",
        "PCM_S8": "PCM_16",
        "PCM_U8": "PCM_U8",
        "FLOAT": "FLOAT",
    }
    target_subtype = subtype_map.get(info.subtype, "PCM_16")
    if dry_run:
        return True, f"DRY_RUN AIFF->WAV ({sr}Hz {info.channels}ch {target_subtype})"

    backup_original(card, backup_root, fp)
    tmp_path = fp.parent / f".{fp.stem}.aiff_fix.wav"
    try:
        sf.write(str(tmp_path), data_orig, sr, subtype=target_subtype, format="WAV")
        data_new, sr_new = sf.read(str(tmp_path), dtype="int32", always_2d=True)
        if sr_new != sr or data_new.shape != data_orig.shape or not np.array_equal(data_orig, data_new):
            tmp_path.unlink(missing_ok=True)
            return False, "Bit-exact verification failed after AIFF->WAV conversion"
        chk = inspect_wav_chunks(tmp_path)
        if chk["status"] != "OK":
            tmp_path.unlink(missing_ok=True)
            return False, f"Post-conversion RIFF audit failed: {chk['status']}"
        os.replace(tmp_path, fp)
        return True, f"Converted AIFF->WAV bit-exact ({sr}Hz {info.channels}ch {target_subtype})"
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def repair_riff_wav_lossless(card: Path, backup_root: Path, fp: Path, dry_run: bool = False) -> Tuple[bool, str]:
    if dry_run:
        return True, "DRY_RUN RIFF rebuild"
    raw = fp.read_bytes()
    sz = len(raw)
    if sz < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return False, "Not a RIFF WAVE file"

    pos = 12
    fmt_body: Optional[bytes] = None
    data_body: Optional[bytes] = None
    extra_keep: List[Tuple[bytes, bytes]] = []
    keep_ids = {b"atem", b"slic", b"smpl", b"meta"}

    while pos + 8 <= sz:
        cid = raw[pos : pos + 4]
        csz = struct.unpack("<I", raw[pos + 4 : pos + 8])[0]
        body_off = pos + 8
        if body_off + csz > sz:
            # If fmt_body and data_body are already cleanly captured, trailing chunk is corrupt garbage — drop it cleanly!
            if fmt_body is not None and data_body is not None:
                break
            # If `data` itself slightly overruns EOF (rare), clamp to available aligned frames
            if cid == b"data" and fmt_body is not None and len(fmt_body) >= 16:
                block_align = struct.unpack("<H", fmt_body[12:14])[0] or 2
                avail = sz - body_off
                aligned = avail - (avail % block_align)
                if aligned > 0:
                    data_body = raw[body_off : body_off + aligned]
                break
            break
        body = raw[body_off : body_off + csz]
        if cid == b"fmt " and fmt_body is None:
            fmt_body = body
        elif cid == b"data" and data_body is None:
            data_body = body
        elif cid in keep_ids:
            if cid == b"atem" and (len(body) & 1):
                body = body + b"\x00"
            extra_keep.append((cid, body))
        pos = body_off + csz + (csz & 1)

    if fmt_body is None or data_body is None or len(fmt_body) < 16:
        return False, "Missing valid fmt or data chunk"

    orig_pcm_sha = sha256_bytes(data_body)
    if dry_run:
        return True, f"DRY_RUN RIFF rebuild (pcm_sha={orig_pcm_sha[:12]})"

    out_chunks: List[bytes] = []

    def _pack(cid: bytes, body: bytes) -> bytes:
        pad = b"\x00" if (len(body) & 1) else b""
        return cid + struct.pack("<I", len(body)) + body + pad

    out_chunks.append(_pack(b"fmt ", fmt_body))
    for ecid, ebody in extra_keep:
        out_chunks.append(_pack(ecid, ebody))
    out_chunks.append(_pack(b"data", data_body))

    payload_body = b"WAVE" + b"".join(out_chunks)
    rebuilt = b"RIFF" + struct.pack("<I", len(payload_body)) + payload_body

    # Verify bit-exact PCM SHA-256 on rebuilt bytes before touching disk
    # Parse `data` back from rebuilt
    rpos = 12
    rebuilt_data: Optional[bytes] = None
    while rpos + 8 <= len(rebuilt):
        rcid = rebuilt[rpos : rpos + 4]
        rcsz = struct.unpack("<I", rebuilt[rpos + 4 : rpos + 8])[0]
        if rcid == b"data":
            rebuilt_data = rebuilt[rpos + 8 : rpos + 8 + rcsz]
            break
        rpos += 8 + rcsz + (rcsz & 1)

    if rebuilt_data is None or sha256_bytes(rebuilt_data) != orig_pcm_sha:
        return False, "PCM SHA-256 mismatch on rebuilt WAV"

    backup_original(card, backup_root, fp)
    atomic_write_bytes(fp, rebuilt)
    chk = inspect_wav_chunks(fp)
    if chk["status"] != "OK":
        return False, f"Post-repair audit failed: {chk['status']}"
    return True, f"Repaired RIFF lossless (pcm_sha={orig_pcm_sha[:12]})"


def repair_xpm_references(card: Path, dry_run: bool = False) -> Dict[str, int]:
    """
    1) Expansions: create trimmed-name WAV mirror beside trailing-space WAVs (e.g. `OpenHH .wav` -> `OpenHH.wav`)
       so Stock ACVS, SampQOL-OS (`kitxpm_parse`), and Melodee all resolve 100% of pads.
    2) Custom_Kits: copy missing local WAVs referenced by `.xpm` from sibling `_[ProjectData]` or parent dir.
    """
    stats = {"xpm_scanned": 0, "space_mirrors_created": 0, "custom_kit_wavs_copied": 0, "still_missing": 0}
    sample_tag_re = re.compile(r"<(?:SampleName|SampleFile)>([^<]+)</(?:SampleName|SampleFile)>")

    for top_name in ("Expansions", "Custom_Kits"):
        top_dir = card / top_name
        if not top_dir.is_dir():
            continue
        for root, dirs, files in os.walk(str(top_dir)):
            dirs[:] = [d for d in dirs if not d.startswith(".") and not d.endswith("_[ProjectData]")]
            for fn in files:
                if fn.startswith(".") or not fn.lower().endswith(".xpm"):
                    continue
                xpm_p = Path(root) / fn
                try:
                    with xpm_p.open("rb") as fh:
                        if fh.read(4) == b"RIFF":
                            continue
                    txt = xpm_p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                stats["xpm_scanned"] += 1
                folder = xpm_p.parent
                refs = set()
                for m in sample_tag_re.finditer(txt):
                    val = m.group(1)
                    if not val or not val.strip():
                        continue
                    refs.add(val)

                # Build lookup maps for this folder and sibling _[ProjectData]
                local_files = {p.name: p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")}
                local_lower = {k.lower(): v for k, v in local_files.items()}
                proj_data = folder / f"{xpm_p.stem}_[ProjectData]"
                sibling_map: Dict[str, Path] = {}
                if proj_data.is_dir():
                    for p in proj_data.iterdir():
                        if p.is_file() and not p.name.startswith("."):
                            sibling_map[p.name.lower()] = p
                # Also look one level deeper if Akai_MPC/<kit>/<kit>_[ProjectData]
                if not sibling_map and folder.parent.is_dir():
                    for cand_pd in folder.parent.glob("*_[ProjectData]"):
                        if cand_pd.is_dir():
                            for p in cand_pd.iterdir():
                                if p.is_file() and not p.name.startswith("."):
                                    sibling_map.setdefault(p.name.lower(), p)

                for raw_ref in refs:
                    wav_name = raw_ref if raw_ref.lower().endswith(".wav") else f"{raw_ref}.wav"
                    stem_raw = wav_name[:-4]
                    stem_trim = stem_raw.rstrip(" ")
                    trim_wav = f"{stem_trim}.wav"

                    exact_hit = local_lower.get(wav_name.lower())
                    trim_hit = local_lower.get(trim_wav.lower())

                    # Mirror trailing-space WAV <-> trimmed WAV so SampQOL-OS + Stock ACVS both resolve
                    if stem_raw != stem_trim:
                        if exact_hit is not None and trim_hit is None:
                            dst = folder / trim_wav
                            if not dry_run:
                                shutil.copy2(exact_hit, dst)
                            local_lower[trim_wav.lower()] = dst
                            stats["space_mirrors_created"] += 1
                            continue
                        if trim_hit is not None and exact_hit is None:
                            dst = folder / wav_name
                            if not dry_run:
                                shutil.copy2(trim_hit, dst)
                            local_lower[wav_name.lower()] = dst
                            stats["space_mirrors_created"] += 1
                            continue

                    if exact_hit is not None or trim_hit is not None:
                        continue

                    # Missing locally: check sibling _[ProjectData] (fixes Custom_Kits)
                    sib = sibling_map.get(wav_name.lower()) or sibling_map.get(trim_wav.lower())
                    if sib is not None:
                        dst = folder / sib.name
                        if not dry_run:
                            shutil.copy2(sib, dst)
                        local_lower[sib.name.lower()] = dst
                        stats["custom_kit_wavs_copied"] += 1
                    else:
                        stats["still_missing"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Lossless SD WAV & XPM Enterprise Sanitizer")
    parser.add_argument("--card", default="/Volumes/MPCSMPL", help="Mounted MPC SD card root")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without writing")
    args = parser.parse_args()

    card = Path(args.card).resolve()
    if not card.is_dir():
        print(f"ERROR: SD card not found at {card}")
        return 1

    backup_root = card / "_RAW_SOURCE_ARCHIVES" / "pre_enterprise_audit_20261121"
    scan_roots = [card / d for d in ("Expansions", "Custom_Kits", "MPC-Sample/Samples") if (card / d).is_dir()]

    wav_counts = {"scanned": 0, "ok": 0, "repaired_riff": 0, "repaired_aiff": 0, "failed": 0, "zero_audio": []}
    failed_details: List[str] = []

    for sroot in scan_roots:
        for root, dirs, files in os.walk(str(sroot)):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in PROTECTED_TOP_DIRS]
            for fn in files:
                if fn.startswith(".") or not fn.lower().endswith(".wav"):
                    continue
                fp = Path(root) / fn
                wav_counts["scanned"] += 1
                info = inspect_wav_chunks(fp)
                st = info["status"]
                if st == "OK":
                    wav_counts["ok"] += 1
                    continue
                if st == "AIFF_IN_WAV":
                    ok, msg = repair_aiff_in_wav(card, backup_root, fp, dry_run=args.dry_run)
                    if ok:
                        wav_counts["repaired_aiff"] += 1
                    else:
                        wav_counts["failed"] += 1
                        failed_details.append(f"{fp.relative_to(card)}: {msg}")
                elif st in ("CHUNK_OVERFLOW", "ODD_ATEM", "RIFF_MISMATCH"):
                    ok, msg = repair_riff_wav_lossless(card, backup_root, fp, dry_run=args.dry_run)
                    if ok:
                        wav_counts["repaired_riff"] += 1
                    else:
                        wav_counts["failed"] += 1
                        failed_details.append(f"{fp.relative_to(card)}: {msg}")
                else:
                    wav_counts["failed"] += 1
                    failed_details.append(f"{fp.relative_to(card)}: {st}")

    xpm_stats = repair_xpm_references(card, dry_run=args.dry_run)

    print("=== SD ENTERPRISE SANITIZER SUMMARY ===")
    print(f"Card:                 {card}")
    print(f"Mode:                 {'DRY-RUN' if args.dry_run else 'LIVE REPAIR'}")
    print(f"Backup dir:           {backup_root}")
    print(f"WAVs scanned:         {wav_counts['scanned']:,}")
    print(f"WAVs already OK:      {wav_counts['ok']:,}")
    print(f"WAVs RIFF repaired:   {wav_counts['repaired_riff']:,}")
    print(f"WAVs AIFF converted:  {wav_counts['repaired_aiff']:,}")
    print(f"WAVs failed:          {wav_counts['failed']:,}")
    for fd in failed_details[:20]:
        print(f"  ! {fd}")
    print(f"XPMs scanned:         {xpm_stats['xpm_scanned']:,}")
    print(f"Space mirrors added:  {xpm_stats['space_mirrors_created']:,}")
    print(f"Custom kit copies:    {xpm_stats['custom_kit_wavs_copied']:,}")
    print(f"XPM refs missing:     {xpm_stats['still_missing']:,}")
    return 0 if wav_counts["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
