#!/usr/bin/env python3
"""Organización y depuración no destructiva de tarjetas MicroSD Akai MPC Sample (/Volumes/MPCSMPL).

Operaciones idempotentes con soporte `--dry-run`:
1. `MPC-Sample/Programs/`: mueve proyectos `.xpj` + `_[ProjectData]` únicos hacia `MPC-Sample/Projects/`
   y archiva duplicados redundantes de `.xpj` en `_RAW_SOURCE_ARCHIVES/organized_cleanup_20261122/`.
2. `Custom_Kits/`: separa carpetas/ZIPs de otros samplers (`NI_Maschine`, `Roland_SP404MK2`,
   `Roland_SP404A`, `Teenage_Engineering_EP133`, `Pocket_Operator_PO33`) hacia
   `Custom_Kits/_OTROS_SAMPLERS/<Hardware>/<KitName>/`, archiva `.command` sueltos y kits de prueba.
3. Raíz `/ASTRO1DEEP-SAMPLE.GEN`: mueve los WAVs limpios a `MPC-Sample/Samples/User/ASTRO1DEEP_SAMPLE_GEN/`.
4. `BACKUPS_SEGURIDAD/`: agrupa restos de prueba (`TEST_BEATOS_RETIRADO_*`, `sync_conflicts_*`) en `_HISTORICO_202611/`.

NUNCA toca `/autorun`, `/autorun-melodee-v0.4.0`, `/mpcqol.conf`, `/Melodee`, `/Expansions` ni `/BeatOS`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

OTHER_SAMPLER_DIRS = (
    "NI_Maschine",
    "Roland_SP404MK2",
    "Roland_SP404A",
    "Teenage_Engineering_EP133",
    "Pocket_Operator_PO33",
)
TEST_CUSTOM_KITS = (
    "Live_Bolero_Check_Chops",
    "Real_EP133_Kit",
    "33_C01_A1D_01_BoleroOrq_Bbm_43s_Chops",
)


def _move_target(src: Path, dst: Path, *, dry_run: bool, stats: Dict[str, Any], bucket: str) -> None:
    if not src.exists():
        return
    if dst.exists():
        # Si ya existe idéntico en destino, evitar colisiones agregando sufijo
        dst = dst.parent / f"{dst.stem}_dup{dst.suffix}"
    stats[bucket] = int(stats.get(bucket, 0)) + 1
    stats["actions"].append(f"{src} -> {dst}")
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def organize_card(card_root: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    card = card_root.resolve()
    if not card.is_dir():
        raise FileNotFoundError(f"Card root not found: {card}")

    archive_root = card / "_RAW_SOURCE_ARCHIVES" / "organized_cleanup_20261122"
    stats: Dict[str, Any] = {
        "card": str(card),
        "mode": "DRY_RUN" if dry_run else "APPLIED",
        "programs_xpj_moved_to_projects": 0,
        "programs_xpj_dups_archived": 0,
        "custom_kits_other_samplers_separated": 0,
        "legacy_commands_archived": 0,
        "test_kits_archived": 0,
        "root_samplegen_moved": 0,
        "backups_grouped": 0,
        "actions": [],
    }

    # 1. MPC-Sample/Programs vs MPC-Sample/Projects
    prog_dir = card / "MPC-Sample" / "Programs"
    proj_dir = card / "MPC-Sample" / "Projects"
    if prog_dir.is_dir() and proj_dir.is_dir():
        for xpj in sorted(prog_dir.rglob("*.xpj")):
            if xpj.name.startswith("._"):
                continue
            stem = xpj.stem
            pair_pd = xpj.parent / f"{stem}_[ProjectData]"
            in_projects = (proj_dir / xpj.name).exists()
            if not in_projects and xpj.parent == prog_dir:
                _move_target(xpj, proj_dir / xpj.name, dry_run=dry_run, stats=stats, bucket="programs_xpj_moved_to_projects")
                if pair_pd.is_dir():
                    _move_target(pair_pd, proj_dir / pair_pd.name, dry_run=dry_run, stats=stats, bucket="programs_xpj_moved_to_projects")
            else:
                dup_dst = archive_root / "Programs_xpj_duplicates" / xpj.relative_to(prog_dir)
                _move_target(xpj, dup_dst, dry_run=dry_run, stats=stats, bucket="programs_xpj_dups_archived")
                if pair_pd.is_dir():
                    pd_dst = archive_root / "Programs_xpj_duplicates" / pair_pd.relative_to(prog_dir)
                    _move_target(pair_pd, pd_dst, dry_run=dry_run, stats=stats, bucket="programs_xpj_dups_archived")

    # 2. Custom_Kits organization
    ck_dir = card / "Custom_Kits"
    if ck_dir.is_dir():
        for cmd in sorted(ck_dir.glob("*.command")):
            if cmd.name.startswith("._"):
                continue
            _move_target(cmd, archive_root / "legacy_commands" / cmd.name, dry_run=dry_run, stats=stats, bucket="legacy_commands_archived")

        for kit in sorted(ck_dir.iterdir()):
            if not kit.is_dir() or kit.name.startswith((".", "_")):
                continue
            if kit.name in TEST_CUSTOM_KITS:
                _move_target(kit, archive_root / "test_kits" / kit.name, dry_run=dry_run, stats=stats, bucket="test_kits_archived")
                continue
            for hw in OTHER_SAMPLER_DIRS:
                hw_dir = kit / hw
                if hw_dir.is_dir():
                    dest_hw = ck_dir / "_OTROS_SAMPLERS" / hw / kit.name
                    _move_target(hw_dir, dest_hw, dry_run=dry_run, stats=stats, bucket="custom_kits_other_samplers_separated")

    # 3. Root ASTRO1DEEP-SAMPLE.GEN -> MPC-Sample/Samples/User/ASTRO1DEEP_SAMPLE_GEN
    sg_dir = card / "ASTRO1DEEP-SAMPLE.GEN"
    if sg_dir.is_dir():
        dest_sg = card / "MPC-Sample" / "Samples" / "User" / "ASTRO1DEEP_SAMPLE_GEN"
        for f in sorted(sg_dir.iterdir()):
            if f.name.startswith("._"):
                continue
            if f.is_file():
                _move_target(f, dest_sg / f.name, dry_run=dry_run, stats=stats, bucket="root_samplegen_moved")
        if not dry_run:
            leftovers = [x for x in sg_dir.iterdir() if not x.name.startswith("._")]
            if not leftovers:
                shutil.rmtree(sg_dir, ignore_errors=True)

    # 4. BACKUPS_SEGURIDAD historical grouping
    bkp_dir = card / "BACKUPS_SEGURIDAD"
    if bkp_dir.is_dir():
        for sub in sorted(bkp_dir.iterdir()):
            if not sub.is_dir() or sub.name.startswith((".", "_")):
                continue
            if sub.name.startswith(("TEST_BEATOS_RETIRADO_", "sync_conflicts_")):
                _move_target(sub, bkp_dir / "_HISTORICO_202611" / sub.name, dry_run=dry_run, stats=stats, bucket="backups_grouped")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Organize and clean BeatOS MPC SD card layout")
    parser.add_argument("--card", type=Path, required=True, help="Mount path (e.g. /Volumes/MPCSMPL)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without moving files")
    args = parser.parse_args()
    res = organize_card(args.card, dry_run=args.dry_run)
    print(json.dumps({**res, "actions_count": len(res["actions"]), "actions": res["actions"][:40]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
