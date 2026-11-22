#!/usr/bin/env python3
"""Auditoría y corrección segura de BPMs e integridad de secuencias en MPC-Sample/Projects/*.xpj.

Reglas estrictas de hardware Akai MPC Sample (AC50 1.3.0.12):
- Mantiene la cabecera de 5 líneas ACVS/1.3.0.12 + gzip + floats con punto decimal.
- Crea respaldo único en `_RAW_SOURCE_ARCHIVES/pre_project_bpm_fix_20261122/` antes de tocar archivos.
- En proyectos CON eventos MIDI reales (sequencias grabadas del productor): NUNCA sobrescribe los tempos
  artísticos de sus secuencias; solo alinea `masterTempo` al BPM de la secuencia activa (`currentSequence`)
  cuando `masterTempoEnabled=False` y difieren, para coherencia al abrir o activar Master Tempo.
- En kits puros de 1 secuencia con 0 eventos MIDI estancados en 120/128 BPM: infiere el tempo real por
  etiquetas en muestras o estilo del nombre (Drill -> 140.0, BoomBap/HipHop/Jazz -> 90.0, DnB -> 174.0)
  y activa `masterTempoEnabled=True` + `seq.tempoEnable=True`.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

_BPM_HINT_RE = re.compile(r"(?:^|[\s_\-\(\[\.])(\d{2,3}(?:\.\d)?)\s*bpm(?![a-z0-9])", re.I)


def _preserve_floats(obj: Any) -> Any:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _preserve_floats(v)
            elif k in ("masterTempo", "bpm", "volume", "pan", "tune", "pitch", "tempo") and isinstance(v, int) and not isinstance(v, bool):
                obj[k] = float(v)
    elif isinstance(obj, list):
        for item in obj:
            _preserve_floats(item)
    return obj


def _infer_zero_event_kit_bpm(xpj_stem: str, sample_names: List[str], current_bpm: float) -> Optional[float]:
    stem_low = xpj_stem.lower()
    for txt in [xpj_stem] + sample_names:
        m = _BPM_HINT_RE.search(txt)
        if m:
            val = float(m.group(1))
            if 55.0 <= val <= 200.0:
                return round(val, 1)
    if current_bpm in (120.0, 128.0):
        if "drill" in stem_low:
            return 140.0
        if "dnb" in stem_low or "jungle" in stem_low:
            return 174.0
        if any(k in stem_low for k in ("boombap", "b0om", "hiphop", "hip_hop", "jahzzy", "jazz", "1974", "punch", "oroject")):
            return 90.0
        if any(k in stem_low for k in ("bolero", "oldies", "soul")):
            return 82.0
    return None


def fix_projects_bpm(card_root: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    card = card_root.resolve()
    proj_dir = card / "MPC-Sample" / "Projects"
    backup_root = card / "_RAW_SOURCE_ARCHIVES" / "pre_project_bpm_fix_20261122"
    stats: Dict[str, Any] = {
        "card": str(card),
        "mode": "DRY_RUN" if dry_run else "APPLIED",
        "scanned": 0,
        "updated": 0,
        "changes": [],
        "errors": 0,
    }
    if not proj_dir.is_dir():
        return stats

    for xpj in sorted(proj_dir.glob("*.xpj")):
        if xpj.name.startswith("._"):
            continue
        stats["scanned"] += 1
        try:
            raw = gzip.open(str(xpj), "rb").read()
            lines = raw.split(b"\n", 5)
            if len(lines) < 6 or not lines[0].startswith(b"ACVS"):
                continue
            hdr = b"\n".join(lines[:5]).decode("utf-8") + "\n"
            payload = json.loads(lines[5].decode("utf-8"))
            data = payload.get("data", {})
            seqs = data.get("sequences") or []
            evs = sum(
                len(((c.get("value") or {}).get("eventList") or {}).get("events") or [])
                for s in seqs
                for cm in ((s.get("value") or {}).get("trackClipMaps") or [])
                for c in (cm or [])
            )
            cur_key = data.get("currentSequence", 0)
            active_seq = next((s.get("value") for s in seqs if s.get("key") == cur_key), None)
            if active_seq is None and seqs:
                active_seq = seqs[0].get("value")
            cur_seq_bpm = float((active_seq or {}).get("bpm") or data.get("masterTempo") or 120.0)
            master_bpm = float(data.get("masterTempo") or cur_seq_bpm)
            master_en = bool(data.get("masterTempoEnabled", False))

            changed = False
            note = ""
            sample_names = [Path(str(s.get("path") or s.get("name") or "")).name for s in (data.get("samples") or [])]

            if evs == 0 and len(seqs) <= 1:
                inferred = _infer_zero_event_kit_bpm(xpj.stem, sample_names, cur_seq_bpm)
                target_bpm = inferred if inferred is not None else cur_seq_bpm
                if abs(master_bpm - target_bpm) >= 0.2 or abs(cur_seq_bpm - target_bpm) >= 0.2 or not master_en:
                    data["masterTempo"] = float(target_bpm)
                    data["masterTempoEnabled"] = True
                    for s in seqs:
                        sv = s.get("value")
                        if isinstance(sv, dict):
                            sv["bpm"] = float(target_bpm)
                            sv["tempoEnable"] = True
                    changed = True
                    note = f"0-ev kit: {master_bpm}/{cur_seq_bpm} -> {target_bpm} (masterTempoEnabled=True)"
            elif not master_en and active_seq is not None and abs(master_bpm - cur_seq_bpm) >= 1.0:
                data["masterTempo"] = float(cur_seq_bpm)
                changed = True
                note = f"seq-driven project: aligned masterTempo {master_bpm} -> {cur_seq_bpm} (active seq key={cur_key})"

            if changed:
                stats["updated"] += 1
                stats["changes"].append({"project": xpj.name, "detail": note})
                if not dry_run:
                    bkp = backup_root / xpj.name
                    if not bkp.exists():
                        bkp.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(xpj), str(bkp))
                    _preserve_floats(data)
                    out_gz = gzip.compress((hdr + json.dumps(payload, indent=0)).encode("utf-8"), mtime=0)
                    tmp = xpj.with_suffix(".xpj.tmp")
                    tmp.write_bytes(out_gz)
                    tmp.replace(xpj)
        except Exception as exc:
            stats["errors"] += 1
            stats["changes"].append({"project": xpj.name, "error": str(exc)})

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and fix BPM coherence in MPC-Sample/Projects/*.xpj")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    res = fix_projects_bpm(args.card, dry_run=args.dry_run)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
