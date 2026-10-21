#!/usr/bin/env python3
"""
Audit All Expansions - Herramienta Forense de Auditoría para BeatOS
Escanea rigurosamente todos los programas (.xpm) de las 9 expansiones oficiales,
verificando la integridad de asignación de pads, resolución física de muestras en disco,
ausencia de pads fantasma y concordancia de metadatos.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

# Asegurar import de hardware_kit_builder
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import hardware_kit_builder as hkb

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ExpansionAuditor")

def run_expansion_audit(
    root_dir: str | Path = "/Volumes/MPCSMPL",
    output_report: str | Path = None,
) -> Dict[str, Any]:
    card_root = Path(root_dir)
    expansions_dir = card_root / "Expansions"

    if not expansions_dir.is_dir():
        logger.error(f"❌ Directorio de expansiones no encontrado: {expansions_dir}")
        return {"success": False, "error": f"Directory not found: {expansions_dir}"}

    exp_folders = [d for d in sorted(expansions_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    logger.info(f"🔍 Iniciando auditoría forense sobre {len(exp_folders)} expansiones oficiales...")

    overall_stats = {
        "total_expansions": len(exp_folders),
        "total_programs": 0,
        "total_assigned_pads": 0,
        "total_resolved_samples": 0,
        "total_missing_samples": 0,
        "total_ghost_pads_prevented": 0,
        "expansions": {},
    }

    all_missing_records = []

    for exp_folder in exp_folders:
        exp_name = exp_folder.name
        xpms = sorted(exp_folder.glob("**/*.xpm"))
        # Filtrar temporales o previews
        xpms = [x for x in xpms if not any(p.startswith(".") or "[Previews]" in p for p in x.parts)]

        exp_stat = {
            "folder": exp_name,
            "program_count": len(xpms),
            "assigned_pads": 0,
            "resolved_samples": 0,
            "missing_samples": 0,
            "programs_with_missing": 0,
            "programs": [],
        }

        for xpm_file in xpms:
            prog_data = hkb.parse_xpm_program(xpm_file, source_root=card_root)
            prog_name = prog_data.get("program_name", xpm_file.stem)
            pads = prog_data.get("pads", {})

            prog_stat = {
                "name": prog_name,
                "file": xpm_file.name,
                "rel_path": prog_data.get("rel_path", ""),
                "type": prog_data.get("program_type", "Drum"),
                "assigned_pads_count": len(pads),
                "resolved_count": 0,
                "missing_count": 0,
                "missing_pads": [],
            }

            for pnum, pinfo in pads.items():
                s_file = pinfo.get("sample_file", "")
                s_name = pinfo.get("sample_name", "")

                # Verificación estricta de pads fantasma
                if s_file == ".wav" or (not s_file and not s_name):
                    overall_stats["total_ghost_pads_prevented"] += 1
                    continue

                exp_stat["assigned_pads"] += 1
                overall_stats["total_assigned_pads"] += 1

                full_p = pinfo.get("full_path")
                if full_p and Path(full_p).is_file():
                    exp_stat["resolved_samples"] += 1
                    prog_stat["resolved_count"] += 1
                    overall_stats["total_resolved_samples"] += 1
                else:
                    exp_stat["missing_samples"] += 1
                    prog_stat["missing_count"] += 1
                    overall_stats["total_missing_samples"] += 1
                    missing_entry = {
                        "expansion": exp_name,
                        "program": prog_name,
                        "xpm_file": xpm_file.name,
                        "pad": pnum,
                        "sample_file": s_file,
                        "rel_path": pinfo.get("rel_path", ""),
                    }
                    prog_stat["missing_pads"].append(missing_entry)
                    all_missing_records.append(missing_entry)

            if prog_stat["missing_count"] > 0:
                exp_stat["programs_with_missing"] += 1

            exp_stat["programs"].append(prog_stat)

        overall_stats["total_programs"] += exp_stat["program_count"]
        overall_stats["expansions"][exp_name] = exp_stat

        status_icon = "✔" if exp_stat["missing_samples"] == 0 else "⚠️"
        pct = (
            (exp_stat["resolved_samples"] / exp_stat["assigned_pads"] * 100)
            if exp_stat["assigned_pads"] > 0
            else 100.0
        )
        logger.info(
            f" {status_icon} [{exp_name}]: {exp_stat['program_count']} programas | "
            f"{exp_stat['assigned_pads']} pads asignados | {exp_stat['resolved_samples']} resueltos ({pct:.1f}%) | "
            f"{exp_stat['missing_samples']} faltantes"
        )

    # Resumen General
    pct_total = (
        (overall_stats["total_resolved_samples"] / overall_stats["total_assigned_pads"] * 100)
        if overall_stats["total_assigned_pads"] > 0
        else 100.0
    )
    logger.info("=" * 70)
    logger.info("📊 RESUMEN AUDITORÍA GLOBAL DE EXPANSIONES:")
    logger.info(f" • Total de Expansiones: {overall_stats['total_expansions']}")
    logger.info(f" • Total de Programas .xpm: {overall_stats['total_programs']}")
    logger.info(f" • Total de Pads Asignados Reales: {overall_stats['total_assigned_pads']}")
    logger.info(f" • Muestras Resueltas en Disco: {overall_stats['total_resolved_samples']} ({pct_total:.2f}%)")
    logger.info(f" • Muestras Faltantes: {overall_stats['total_missing_samples']}")
    logger.info("=" * 70)

    if output_report:
        out_p = Path(output_report)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(overall_stats, f, indent=2, ensure_ascii=False)
        logger.info(f"📄 Reporte forense guardado en: {out_p}")

    return overall_stats

if __name__ == "__main__":
    rep_path = BASE_DIR / "expansion_audit_report.json"
    run_expansion_audit(output_report=rep_path)
