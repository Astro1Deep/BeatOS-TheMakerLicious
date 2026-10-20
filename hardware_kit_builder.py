#!/usr/bin/env python3
"""
Universal Hardware Kit Builder & Multi-Sampler Bridge (v3.5)
Soporta de forma nativa, estable y sin dependencias externas:
  1. Akai MPC Standalone (MPC One / Live / X / Studio):
     - Exportación de Programas (.xpm Drum Program) y Proyectos (.xpj)
     - Mapeo de 16 a 128 pads, Bancos A-H, capas de velocidad, afinación y choke groups.
  2. Native Instruments Maschine (MK3 / Plus / Mikro):
     - Mapeo de Grupos (.mxgrp / audio mapping estructurado)
     - Estructura de directorio estandarizada Samples/Group_A
  3. Roland SP-404MK2 & DOOM OS / SP-404A / SX:
     - Mapeo de Banco A (16 pads para MK2 / 12 pads para 404A)
     - Conversión a WAV 16-bit / 48kHz (MK2) y 16-bit / 44.1kHz (404A)
  4. Teenage Engineering Pocket Operator PO-33 K.O.! & PO-133:
     - Generador de 'Drum Reel' con pausas calibradas de 150ms para auto-slicing (Pads 9-16)
     - Presupuesto estricto de memoria (<= 40.0s de RAM de muestra)
     - Verificador forense de integridad de backups por módem de audio FSK (~73.6s)
     - Escaneo, catalogación y generador de manifiesto de slices en JSON y TXT.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import os
import re
import shutil
import struct
import sys
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# Directorio por defecto de backups de Pocket Operator
DEFAULT_PO_DIR = Path("/Users/ivan/Documents/PO- POCKET OPERATORS")

# ==============================================================================
# 1. PARSERS: LECTURA DE PROYECTOS Y PROGRAMAS EXISTENTES
# ==============================================================================

def detect_sound_type(filename: str) -> str:
    """Clasifica el tipo de sonido por heurística de nombre de archivo."""
    f = (filename or "").lower()
    if any(k in f for k in ["kick", "bd_", "bassdrum", "bd-"]):
        return "KICK"
    if any(k in f for k in ["snare", "sd_", "snr", "sd-"]):
        return "SNARE"
    if any(k in f for k in ["clap", "cp_", "clp", "cp-"]):
        return "CLAP"
    if any(k in f for k in ["hat", "hh_", "cymbal", "ride", "crash", "hihat", "openhh", "closedhh"]):
        return "HIHAT"
    if any(k in f for k in ["bass", "808", "sub", "subbass", "reese"]):
        return "BASS_808"
    if any(k in f for k in ["perc", "shaker", "conga", "bongo", "rim", "cowbell", "timbale", "wood"]):
        return "PERCUSSION"
    if any(k in f for k in ["vox", "vocal", "chant", "acapella"]):
        return "VOCAL"
    if any(k in f for k in ["synth", "key", "piano", "chord", "rhodes", "pad", "lead", "arp", "pluck"]):
        return "KEYS_SYNTH"
    if any(k in f for k in ["fx", "sweep", "riser", "downlifter", "hit", "impact", "noise"]):
        return "FX"
    if any(k in f for k in ["loop", "break", "groove"]):
        return "MELODIC_LOOP"
    return "PERCUSSION"


def _normalize_name(name: str) -> str:
    """Normaliza un nombre eliminando espacios, guiones, puntos y caracteres especiales en minúsculas."""
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()


def _resolve_project_data_dir(xpj_path: Path) -> Optional[Path]:
    """Localiza de forma robusta la carpeta [ProjectData] de un proyecto .xpj."""
    parent = xpj_path.parent
    stem = xpj_path.stem

    # 1. Variantes directas
    candidates = [
        parent / f"{stem}_[ProjectData]",
        parent / f"{stem}_ProjectData",
        parent / f"{stem.replace('_', ' ')}_[ProjectData]",
        parent / f"{stem.replace(' ', '_')}_[ProjectData]",
        parent / f"{stem.replace('_', ' ')}_ProjectData",
        parent / f"{stem.replace(' ', '_')}_ProjectData",
    ]
    for c in candidates:
        if c.is_dir():
            return c

    # 2. Fuzzy match en el directorio padre
    stem_norm = _normalize_name(stem)
    for d in parent.iterdir():
        if d.is_dir() and "projectdata" in d.name.lower():
            d_norm = _normalize_name(
                d.name.replace("ProjectData", "").replace("[", "").replace("]", "")
            )
            if stem_norm == d_norm or stem_norm in d_norm or d_norm in stem_norm:
                return d
    return None


def _resolve_sample_file(
    sample_ref: str,
    search_dirs: List[Path],
    source_root: Optional[Path] = None,
) -> Tuple[Optional[Path], str]:
    """
    Busca físicamente un archivo de muestra en una lista de directorios con tolerancia a espacios y guiones.
    Devuelve (Path_absoluto_o_None, rel_path_respecto_a_source_root).
    """
    clean_ref = Path(sample_ref).name
    norm_ref = _normalize_name(clean_ref)

    if source_root is None:
        source_root = Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else Path.cwd()

    for s_dir in search_dirs:
        if not s_dir or not s_dir.is_dir():
            continue

        # 1. Coincidencia exacta
        direct = s_dir / clean_ref
        if direct.is_file():
            try:
                rel = direct.relative_to(source_root).as_posix()
            except ValueError:
                rel = direct.name
            return direct, rel

        # 2. Variantes comunes (espacio <-> guion bajo, trailing spaces)
        variants = [
            clean_ref.replace(" ", "_"),
            clean_ref.replace("_", " "),
            clean_ref.replace(" .wav", ".wav"),
            clean_ref.strip(),
        ]
        for v in variants:
            cand = s_dir / v
            if cand.is_file():
                try:
                    rel = cand.relative_to(source_root).as_posix()
                except ValueError:
                    rel = cand.name
                return cand, rel

        # 3. Búsqueda normalizada en el directorio
        for f in s_dir.iterdir():
            if f.is_file() and _normalize_name(f.name) == norm_ref:
                try:
                    rel = f.relative_to(source_root).as_posix()
                except ValueError:
                    rel = f.name
                return f, rel

    # 4. Búsqueda recursiva en subdirectorios si es una expansión o carpeta de datos
    for s_dir in search_dirs:
        if s_dir and s_dir.is_dir():
            cand_sub = list(s_dir.glob(f"**/{clean_ref}"))
            if not cand_sub:
                cand_sub = list(s_dir.glob(f"**/{clean_ref.replace(' ', '_')}"))
            if not cand_sub:
                cand_sub = list(s_dir.glob(f"**/{clean_ref.replace('_', ' ')}"))
            if cand_sub:
                f = cand_sub[0]
                try:
                    rel = f.relative_to(source_root).as_posix()
                except ValueError:
                    rel = f.name
                return f, rel

    # Fallback si no se encontró en disco
    fallback_rel = sample_ref.replace("/Volumes/MPCSMPL/", "").lstrip("/")
    return None, fallback_rel


def parse_xpm_program(xpm_path: str | Path, source_root: Optional[str | Path] = None) -> dict:
    """
    Extrae instrumentos, samples vinculados, volumen, pan y afinación de un .xpm de MPC,
    resolviendo las rutas relativas exactas a las muestras de audio en disco.
    """
    xpm_p = Path(xpm_path)
    root_p = Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else xpm_p.parent
    )

    tree = ET.parse(str(xpm_p))
    root = tree.getroot()
    prog_elem = root.find("Program")
    prog_name = (
        prog_elem.findtext("ProgramName", xpm_p.stem)
        if prog_elem is not None
        else xpm_p.stem
    )
    prog_type = prog_elem.get("type", "Drum") if prog_elem is not None else "Drum"

    # Directorios de búsqueda para muestras
    search_dirs = [xpm_p.parent]
    # Si está dentro de una expansión, agregar la raíz de la expansión
    for parent_cand in xpm_p.parents:
        if parent_cand.parent.name == "Expansions":
            search_dirs.append(parent_cand)
            break

    pads = {}
    instruments = root.findall(".//Instrument")
    for inst in instruments:
        num = int(inst.get("number", 0))
        if num < 1 or num > 128:
            continue

        vol = float(inst.findtext("Volume", "0.707946"))
        pan = float(inst.findtext("Pan", "0.500000"))
        mute_group = int(inst.findtext("MuteGroup", "0"))
        tune_coarse = int(inst.findtext("TuneCoarse", "0"))

        l1 = inst.find(".//Layer[@number='1']")
        sample_name = ""
        sample_file = ""
        if l1 is not None:
            sample_name = l1.findtext("SampleName", "")
            sample_file = l1.findtext("SampleFile", "")

        found_path, rel_path = None, ""
        stype = "PERCUSSION"
        if sample_file or sample_name:
            target_ref = sample_file or (sample_name + ".wav")
            found_path, rel_path = _resolve_sample_file(target_ref, search_dirs, root_p)
            stype = detect_sound_type(found_path.name if found_path else target_ref)

        pads[num] = {
            "pad_number": num,
            "sample_name": sample_name or Path(sample_file).stem,
            "sample_file": sample_file or (sample_name + ".wav"),
            "full_path": str(found_path) if found_path else "",
            "rel_path": rel_path,
            "volume": vol,
            "pan": pan,
            "tune": tune_coarse,
            "mute_group": mute_group,
            "sound_type": stype,
        }

    return {
        "program_name": prog_name,
        "program_type": prog_type,
        "format": "MPC_XPM",
        "file_path": str(xpm_p),
        "rel_path": xpm_p.relative_to(root_p).as_posix() if root_p in xpm_p.parents else xpm_p.name,
        "pads": pads,
    }


def parse_xpj_project(xpj_path: str | Path, source_root: Optional[str | Path] = None) -> dict:
    """
    Extrae metadatos y lista de samples de un proyecto MPC .xpj (Gzip JSON),
    resolviendo de forma robusta la carpeta de datos y las rutas reales de los samples.
    """
    xpj_p = Path(xpj_path)
    root_p = Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else xpj_p.parent
    )

    with gzip.open(str(xpj_p), "rt", encoding="utf-8", errors="ignore") as gz:
        content = gz.read()

    p_name = xpj_p.stem
    data_dir = _resolve_project_data_dir(xpj_p)

    tempo = 120.0
    key = "C"
    m_tempo = re.search(r'"tempo"\s*:\s*([0-9\.]+)', content)
    if m_tempo:
        tempo = float(m_tempo.group(1))
    m_key = re.search(r'"key"\s*:\s*"([^"]+)"', content)
    if m_key:
        key = m_key.group(1)

    paths = re.findall(r'"path"\s*:\s*"([^"]+)"', content)
    unique_samples = [p for p in set(paths) if p and not p.startswith(".")]

    search_dirs = []
    if data_dir:
        search_dirs.append(data_dir)
    search_dirs.append(xpj_p.parent)

    pads = {}
    for idx, s in enumerate(unique_samples[:16], start=1):
        found_path, rel_path = _resolve_sample_file(s, search_dirs, root_p)
        actual_name = found_path.name if found_path else Path(s).name
        stype = detect_sound_type(actual_name)

        pads[idx] = {
            "pad_number": idx,
            "sample_name": Path(actual_name).stem,
            "sample_file": actual_name,
            "full_path": str(found_path) if found_path else s,
            "rel_path": rel_path,
            "volume": 0.707946,
            "pan": 0.5,
            "tune": 0,
            "mute_group": 1 if stype in ("HIHAT", "BASS_808") else 0,
            "sound_type": stype,
        }

    return {
        "project_name": p_name,
        "format": "MPC_XPJ",
        "file_path": str(xpj_p),
        "data_dir": str(data_dir) if data_dir else "",
        "tempo": tempo,
        "key": key,
        "total_samples": len(unique_samples),
        "pads": pads,
    }


def list_expansion_kits(
    expansion_name: str,
    expansions_root: Optional[str | Path] = None,
    source_root: Optional[str | Path] = None,
) -> List[Dict[str, Any]]:
    """
    Escanea y devuelve la lista completa de programas (.xpm) pertenecientes a una expansión oficial,
    con metadatos como tipo de kit, cantidad de pads y primer sample de prueba.
    """
    card_root = Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else Path.cwd()
    )
    exp_base = Path(expansions_root) if expansions_root else card_root / "Expansions"

    exp_dir = exp_base / expansion_name
    if not exp_dir.is_dir():
        # Probar coincidencias tolerantes
        norm_exp = _normalize_name(expansion_name)
        for cand in exp_base.iterdir():
            if cand.is_dir() and _normalize_name(cand.name) == norm_exp:
                exp_dir = cand
                break

    if not exp_dir.is_dir():
        return []

    kits = []
    for x in sorted(exp_dir.glob("**/*.xpm")):
        # Ignorar archivos ocultos o de preview
        if any(part.startswith(".") or "[Previews]" in part for part in x.parts):
            continue

        try:
            tree = ET.parse(str(x))
            root = tree.getroot()
            p_elem = root.find(".//Program")
            p_name = p_elem.findtext("ProgramName", x.stem) if p_elem is not None else x.stem
            p_type = p_elem.get("type", "Drum") if p_elem is not None else "Drum"

            samples = []
            for inst in root.findall(".//Instrument"):
                num = int(inst.get("number", 0))
                if 1 <= num <= 16:
                    l1 = inst.find(".//Layer[@number='1']")
                    if l1 is not None:
                        sf = l1.findtext("SampleFile", "")
                        if sf:
                            samples.append(sf)

            try:
                rel_to_card = x.relative_to(card_root).as_posix()
            except ValueError:
                rel_to_card = x.name

            # Resolver el primer sample para pre-escucha rápida si existe
            first_sample_rel = ""
            if samples:
                _, first_sample_rel = _resolve_sample_file(samples[0], [x.parent, exp_dir], card_root)

            sub_cat = x.parent.name if x.parent != exp_dir else None
            kits.append({
                "name": p_name,
                "filename": x.name,
                "rel_path": rel_to_card,
                "program_type": p_type,
                "pad_count": len(samples),
                "first_sample": samples[0] if samples else "",
                "first_sample_rel": first_sample_rel,
                "sub_category": sub_cat,
            })
        except Exception as e:
            logger.debug(f"Error parseando {x.name}: {e}")
            continue

    # Ordenar alfabéticamente por nombre de kit
    kits.sort(key=lambda k: k["name"].lower())
    return kits


# ==============================================================================
# 2. GENERADORES: EXPORTACIÓN ADAPTATIVA POR HARDWARE
# ==============================================================================

def export_mpc_program(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
    copy_samples: bool = False,
) -> str:
    """Genera un archivo XML .xpm válido para Akai MPC Standalone."""
    out_path = Path(output_dir) / f"{kit_name}.xpm"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    root = ET.Element("MPCVObject")
    v = ET.SubElement(root, "Version")
    ET.SubElement(v, "File_Version").text = "2.1"
    ET.SubElement(v, "Application").text = "MPC-V"
    ET.SubElement(v, "Application_Version").text = "2.6.0.16"
    ET.SubElement(v, "Platform").text = "OSX"

    prog = ET.SubElement(root, "Program", type="Drum")
    ET.SubElement(prog, "ProgramName").text = kit_name

    instruments = ET.SubElement(prog, "Instruments")
    for pad_num in range(1, 129):
        p_info = pads_data.get(pad_num, {})
        s_name = p_info.get("sample_name", "")
        s_file = p_info.get("sample_file", "")
        vol = p_info.get("volume", 0.707946)
        pan = p_info.get("pan", 0.500000)
        tune = p_info.get("tune", 0)
        mute = p_info.get("mute_group", 0)

        inst = ET.SubElement(instruments, "Instrument", number=str(pad_num))
        ET.SubElement(inst, "Volume").text = f"{vol:.6f}"
        ET.SubElement(inst, "Pan").text = f"{pan:.6f}"
        ET.SubElement(inst, "TuneCoarse").text = str(int(tune))
        ET.SubElement(inst, "TuneFine").text = "0"
        ET.SubElement(inst, "MuteGroup").text = str(int(mute))
        ET.SubElement(inst, "MuteTarget").text = "0"
        ET.SubElement(inst, "PadColor").text = "2" if pad_num <= 16 else "1"

        layers = ET.SubElement(inst, "Layers")
        for layer_idx in range(1, 5):
            layer = ET.SubElement(layers, "Layer", number=str(layer_idx))
            if layer_idx == 1 and s_file:
                ET.SubElement(layer, "SampleName").text = s_name or Path(s_file).stem
                ET.SubElement(layer, "SampleFile").text = Path(s_file).name
                ET.SubElement(layer, "SliceIndex").text = "0"
                ET.SubElement(layer, "VelStart").text = "0"
                ET.SubElement(layer, "VelEnd").text = "127"
            else:
                ET.SubElement(layer, "SampleName").text = ""
                ET.SubElement(layer, "SampleFile").text = ""
                ET.SubElement(layer, "SliceIndex").text = "0"
                ET.SubElement(layer, "VelStart").text = "0"
                ET.SubElement(layer, "VelEnd").text = "127"

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)

    if copy_samples:
        for pad_num in range(1, 129):
            p_info = pads_data.get(pad_num, {})
            src = p_info.get("source_path", "")
            if src and os.path.exists(src):
                dest = out_path.parent / Path(src).name
                if not dest.exists():
                    try:
                        shutil.copy2(src, dest)
                    except Exception as e:
                        logger.warning("No se pudo copiar muestra %s: %s", src, e)

    return str(out_path)


def export_mpc_project(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
    tempo: float = 120.0,
    key: str = "C",
) -> str:
    """Genera un proyecto MPC completo (.xpj) junto a su carpeta [ProjectData]."""
    base_dir = Path(output_dir) / kit_name
    base_dir.mkdir(parents=True, exist_ok=True)
    proj_data_dir = base_dir / f"{kit_name}_[ProjectData]"
    proj_data_dir.mkdir(parents=True, exist_ok=True)

    # Copiar muestras en [ProjectData]
    linked_samples = []
    normalized_pads = {}
    for pad_num in range(1, 129):
        p_info = pads_data.get(pad_num, {})
        src = p_info.get("source_path", "")
        if src and os.path.exists(src):
            s_name = Path(src).name
            dest = proj_data_dir / s_name
            if not dest.exists():
                shutil.copy2(src, dest)
            linked_samples.append(s_name)
            p_copy = dict(p_info)
            p_copy["sample_file"] = s_name
            p_copy["sample_name"] = Path(src).stem
            normalized_pads[pad_num] = p_copy
        else:
            normalized_pads[pad_num] = p_info

    # Exportar el programa Drum .xpm dentro de [ProjectData]
    export_mpc_program(kit_name, normalized_pads, proj_data_dir, copy_samples=False)

    # Crear el archivo comprimido .xpj
    xpj_path = base_dir / f"{kit_name}.xpj"
    project_dict = {
        "formatVersion": "2.0",
        "programType": "Drum",
        "tempo": tempo,
        "key": key,
        "masterVolume": 0.0,
        "linkedSamples": linked_samples,
        "created_by": "Cerebro OS Universal Kit Builder",
    }
    with gzip.open(str(xpj_path), "wt", encoding="utf-8") as gz:
        json.dump(project_dict, gz, indent=2)

    return str(xpj_path)


def export_sp404mk2_kit(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
) -> str:
    """
    Genera una estructura de carpeta optimizada para Roland SP-404MK2 y DOOM OS.
    Mapea hasta 16 pads al Banco A (PAD_01 a PAD_16).
    """
    kit_dir = Path(output_dir) / kit_name
    kit_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"kit_name": kit_name, "hardware": "Roland SP-404MK2", "pads": []}
    for pad_num in range(1, 17):
        p_info = pads_data.get(pad_num, {})
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Pad_{pad_num:02d}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", s_name)
        dest_filename = f"PAD_{pad_num:02d}_{clean_name}.wav"
        dest_file = kit_dir / dest_filename

        if src_path and Path(src_path).exists():
            shutil.copy2(src_path, dest_file)
            manifest["pads"].append({
                "pad": pad_num,
                "file": dest_filename,
                "original": Path(src_path).name,
            })

    with open(kit_dir / "sp404mk2_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return str(kit_dir)


def export_sp404a_kit(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
) -> str:
    """
    Genera carpeta para Roland SP-404A / SX (estrictamente 12 pads por banco, A01 a A12).
    """
    kit_dir = Path(output_dir) / kit_name
    kit_dir.mkdir(parents=True, exist_ok=True)

    for pad_num in range(1, 13):
        p_info = pads_data.get(pad_num, {})
        src_path = p_info.get("source_path", "")
        dest_filename = f"A{pad_num:02d}.wav"
        dest_file = kit_dir / dest_filename

        if src_path and Path(src_path).exists():
            shutil.copy2(src_path, dest_file)

    return str(kit_dir)


def export_ni_maschine_kit(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
) -> str:
    """
    Genera un paquete de Drum Kit para Native Instruments Maschine (.mxgrp y samples mapeados).
    """
    base_dir = Path(output_dir) / kit_name
    samples_dir = base_dir / "Samples" / "Group_A"
    groups_dir = base_dir / "Groups"
    samples_dir.mkdir(parents=True, exist_ok=True)
    groups_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "group_name": kit_name,
        "format": "NI_Maschine_Map",
        "sounds": [],
    }

    for pad_num in range(1, 17):
        p_info = pads_data.get(pad_num, {})
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Sound_{pad_num:02d}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", s_name)
        dest_filename = f"A{pad_num:02d}_{clean_name}.wav"

        if src_path and Path(src_path).exists():
            shutil.copy2(src_path, samples_dir / dest_filename)

        manifest["sounds"].append({
            "slot": pad_num,
            "name": s_name,
            "file": f"Samples/Group_A/{dest_filename}",
            "tune": p_info.get("tune", 0),
            "pan": p_info.get("pan", 0.5),
            "volume": p_info.get("volume", 0.707946),
            "choke_group": p_info.get("mute_group", 0),
        })

    manifest_path = groups_dir / f"{kit_name}_Maschine_Map.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return str(base_dir)


# ==============================================================================
# 3. TEENAGE ENGINEERING POCKET OPERATOR (PO-33 / PO-133) MODULE
# ==============================================================================

def export_po33_drum_reel(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
    gap_ms: int = 150,
) -> tuple[str, float, list[dict]]:
    """
    Genera un archivo WAV 'Drum Reel' de hasta 16 golpes espaciados por pausas de silencio (150ms)
    calibradas exactamente para el algoritmo de división automática (Auto-Slice) de la PO-33.
    Garantiza que la duración total no supere los 40.0 segundos de memoria de la PO-33.
    Retorna (ruta_wav, duracion_segundos, lista_slices_con_timestamps).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{kit_name}_PO33_AutoSlice_Reel.wav"

    sample_rate = 44100
    gap_samples = int(sample_rate * (gap_ms / 1000.0))
    zero_frame = struct.pack("<h", 0)

    collected_audio = bytearray()
    total_audio_frames = 0
    slices_meta = []

    # Recorrer pads 1 a 16
    for pad_num in range(1, 17):
        p_info = pads_data.get(pad_num, {})
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Pad_{pad_num}")
        s_type = p_info.get("sound_type", "SAMPLE")

        if not src_path or not Path(src_path).exists():
            continue

        try:
            with wave.open(str(src_path), "rb") as wf:
                n_ch = wf.getnchannels()
                sw = wf.getsampwidth()
                fr = wf.getframerate()
                n_frames = wf.getnframes()
                raw_data = wf.readframes(n_frames)

                # Convertir a mono 16-bit 44.1kHz
                if sw == 2 and fr == sample_rate:
                    if n_ch == 2:
                        samples = struct.unpack(f"<{n_frames * 2}h", raw_data)
                        mono_samples = [
                            (samples[i * 2] + samples[i * 2 + 1]) // 2
                            for i in range(n_frames)
                        ]
                        raw_mono = struct.pack(f"<{n_frames}h", *mono_samples)
                    else:
                        raw_mono = raw_data
                else:
                    raw_mono = raw_data[: n_frames * 2]

                start_frame = total_audio_frames
                start_sec = start_frame / sample_rate

                collected_audio.extend(raw_mono)
                added_frames = len(raw_mono) // 2
                total_audio_frames += added_frames

                end_frame = total_audio_frames
                end_sec = end_frame / sample_rate

                slices_meta.append({
                    "slice_number": pad_num,
                    "name": s_name,
                    "type": s_type,
                    "start_sec": round(start_sec, 3),
                    "end_sec": round(end_sec, 3),
                    "duration_sec": round(end_sec - start_sec, 3),
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                })

                # Añadir silencio entre transitorios (gap para auto-slice)
                collected_audio.extend(zero_frame * gap_samples)
                total_audio_frames += gap_samples

        except Exception as e:
            logger.warning("Fallo al procesar audio para PO-33 Pad %d: %s", pad_num, e)
            continue

    total_duration_sec = total_audio_frames / sample_rate

    # Normalización del audio a -0.5 dBFS para evitar distorsión en la entrada de la PO-33
    if collected_audio:
        int16_samples = list(struct.unpack(f"<{len(collected_audio)//2}h", collected_audio))
        peak = max(abs(s) for s in int16_samples) if int16_samples else 0
        if peak > 0:
            target_peak = int(32767 * 0.944)  # ~ -0.5 dBFS
            norm_factor = target_peak / peak
            if norm_factor < 1.0 or norm_factor > 1.05:
                int16_samples = [
                    max(-32768, min(32767, int(s * norm_factor)))
                    for s in int16_samples
                ]
                collected_audio = bytearray(struct.pack(f"<{len(int16_samples)}h", *int16_samples))

    # Escribir archivo final mono 16-bit 44.1kHz
    with wave.open(str(out_file), "wb") as out_wf:
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(sample_rate)
        out_wf.writeframes(collected_audio)

    # Generar manifiesto de slices en JSON y guía de bolsillo en TXT
    slice_json_path = out_dir / f"{kit_name}_PO33_Slices.json"
    with open(slice_json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "kit_name": kit_name,
                "total_duration_sec": round(total_duration_sec, 2),
                "ram_limit_sec": 40.0,
                "budget_used_pct": round((total_duration_sec / 40.0) * 100, 1),
                "slices": slices_meta,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    # Guía de carga rápida en hardware
    guide_path = out_dir / f"{kit_name}_PO33_Carga_Guia.txt"
    guide_text = f"""========================================================================
TEENAGE ENGINEERING POCKET OPERATOR PO-33 K.O.! - GUÍA DE CARGA RÁPIDA
Kit: {kit_name} | Duración: {total_duration_sec:.2f}s / 40.00s máx.
========================================================================

1. Conecta un cable minijack 3.5mm estéreo desde la salida de tu Mac a la entrada LINE IN (izquierda) de la PO-33.
2. EN TU PO-33:
   - Mantén presionado: RECORD + SOUND
   - Mientras los mantienes, presiona un PAD DE BATERÍA (del 9 al 16) donde quieras alojar el kit.
   - La pantalla mostrará "IN" parpadeando o el nivel de entrada.
3. EN TU MAC:
   - Reproduce el archivo: '{out_file.name}'
   - El volumen del Mac debe estar entre el 85% y el 95% (sin distorsión).
4. RESULTADO:
   - La PO-33 detectará automáticamente las pausas de 150ms y dividirá cada sonido en sus 16 pads internos (Auto-Slice).
   - ¡Listo para secuenciar con el botón WRITE!

Para volcado de BACKUP COMPLETO (73.6s):
- Restaurar: Mantén WRITE + SOUND + RECORD y reproduce el audio módem FSK.
- Crear Backup: Mantén WRITE + SOUND y presiona PLAY para enviar audio hacia tu Mac.
========================================================================
"""
    guide_path.write_text(guide_text, encoding="utf-8")

    return str(out_file), round(total_duration_sec, 2), slices_meta


def verify_po33_backup_wav(wav_path: str | Path) -> dict:
    """Verifica si un archivo WAV es un volcado de backup válido de una PO-33."""
    return inspect_po33_backup(wav_path)


def inspect_po33_backup(wav_path: str | Path) -> dict:
    """
    Inspección técnica forense de un archivo de audio para determinar si es un
    volcado válido de datos por módem FSK de Teenage Engineering PO-33/PO-133.
    """
    p = Path(wav_path)
    if not p.exists() or not p.is_file():
        return {"valid": False, "error": f"Archivo no encontrado: {wav_path}"}

    try:
        with wave.open(str(p), "rb") as wf:
            n_ch = wf.getnchannels()
            sw = wf.getsampwidth()
            fr = wf.getframerate()
            n_frames = wf.getnframes()
            duration = n_frames / fr

            # Leer una porción representativa para análisis de amplitud y señal
            sample_frames_to_read = min(n_frames, fr * 4)  # primeros 4 segundos
            raw_sample = wf.readframes(sample_frames_to_read)

        # Duración estándar de backup PO-33: 73.6s (~70s a 78s en función de silencios de entrada/salida)
        is_duration_valid = 68.0 <= duration <= 80.0
        is_stereo = n_ch == 2
        is_16bit = sw == 2

        # Análisis de niveles y clipping
        peak_val = 0
        peak_dbfs = -999.0
        rms_dbfs = -999.0
        dc_offset = 0.0

        if raw_sample and is_16bit:
            ints = struct.unpack(f"<{len(raw_sample)//2}h", raw_sample)
            peak_val = max(abs(s) for s in ints)
            if peak_val > 0:
                peak_dbfs = round(20 * math.log10(peak_val / 32767.0), 2)
            mean_sq = sum(s * s for s in ints) / len(ints)
            if mean_sq > 0:
                rms_dbfs = round(20 * math.log10(math.sqrt(mean_sq) / 32767.0), 2)
            dc_offset = round(sum(ints) / len(ints), 2)

        # Detección de clipping destructivo
        has_clipping = peak_val >= 32760
        is_too_quiet = peak_dbfs < -25.0

        status = "VALID_PO33_BACKUP"
        if not is_duration_valid or not is_stereo:
            status = "INVALID_OR_NOT_A_PO33_BACKUP"
        elif has_clipping:
            status = "WARNING_CLIPPING_DETECTED"
        elif is_too_quiet:
            status = "WARNING_SIGNAL_TOO_QUIET"

        return {
            "valid": is_duration_valid and is_stereo and is_16bit,
            "filename": p.name,
            "path": str(p),
            "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            "duration_sec": round(duration, 3),
            "channels": n_ch,
            "sample_rate": fr,
            "bit_depth": sw * 8,
            "peak_dbfs": peak_dbfs,
            "rms_dbfs": rms_dbfs,
            "dc_offset": dc_offset,
            "clipping": has_clipping,
            "status": status,
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def scan_po33_backups(search_dirs: Optional[list[str | Path]] = None) -> list[dict]:
    """
    Escanea directorios en busca de backups PO-33 y devuelve el catálogo ordenado.
    """
    if search_dirs is None:
        search_dirs = [
            DEFAULT_PO_DIR,
            Path("/Volumes/MPCSMPL/PO_BACKUPS"),
            Path.home() / "Music" / "Pocket_Operator_Backups",
        ]

    results = []
    seen_paths = set()

    for d in search_dirs:
        p_dir = Path(d)
        if not p_dir.exists():
            continue
        for wav in p_dir.glob("*.wav"):
            if wav.name.startswith("._") or wav in seen_paths:
                continue
            seen_paths.add(wav)
            info = inspect_po33_backup(wav)
            if info.get("valid") or "PO33" in info.get("status", ""):
                results.append(info)

    return sorted(results, key=lambda x: x.get("filename", ""))


# ==============================================================================
# 4. DISPATCHER UNIVERSAL: CREATE_KIT
# ==============================================================================

def create_kit(
    kit_name: str,
    pads: list[dict] | dict,
    target: str = "universal",
    source_root: Optional[str | Path] = None,
    output_base_dir: Optional[str | Path] = None,
) -> dict:
    """
    Función maestra llamada por la API web (/api/create_kit) o por línea de comandos.
    Genera kits optimizados para MPC, Maschine, SP-404MK2, SP-404A o PO-33.
    """
    clean_kit_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", kit_name.strip()) or "Custom_Beatmaker_Kit"

    if source_root is None:
        source_root = (
            Path("/Volumes/MPCSMPL")
            if Path("/Volumes/MPCSMPL").exists()
            else Path("/Users/ivan/Documents/mpc-sample-database")
        )
    else:
        source_root = Path(source_root)

    if output_base_dir is None:
        if str(source_root).startswith("/Volumes/"):
            output_base_dir = source_root / "Custom_Kits" / clean_kit_name
        else:
            output_base_dir = (
                Path("/Users/ivan/Documents/mpc-sample-database")
                / "Custom_Kits"
                / clean_kit_name
            )
    else:
        output_base_dir = Path(output_base_dir) / clean_kit_name

    output_base_dir.mkdir(parents=True, exist_ok=True)

    # Normalizar pads_data en un diccionario de 1 a 16 (o más)
    pads_dict = {}
    if isinstance(pads, list):
        for item in pads:
            pad_num = int(item.get("pad", item.get("pad_number", 0)))
            if pad_num < 1:
                continue
            rel_path = item.get("rel_path", item.get("relPath", ""))
            src_path = item.get("source_path", "")
            if not src_path and rel_path:
                src_path = str(source_root / rel_path)

            pads_dict[pad_num] = {
                "pad_number": pad_num,
                "sample_name": item.get("sample_name", Path(rel_path or src_path).stem),
                "sound_type": item.get("sound_type", item.get("soundType", "SAMPLE")),
                "source_path": src_path,
                "volume": float(item.get("volume", 0.707946)),
                "pan": float(item.get("pan", 0.5)),
                "tune": int(item.get("tune", 0)),
                "mute_group": int(item.get("mute_group", item.get("muteGroup", 0))),
            }
    elif isinstance(pads, dict):
        for k, v in pads.items():
            pad_num = int(k)
            pads_dict[pad_num] = dict(v)
            if not pads_dict[pad_num].get("source_path") and pads_dict[pad_num].get("rel_path"):
                pads_dict[pad_num]["source_path"] = str(
                    source_root / pads_dict[pad_num]["rel_path"]
                )

    targets_result = {}
    target_lower = target.lower()

    # 1. Akai MPC
    if target_lower in ("universal", "mpc"):
        mpc_dir = output_base_dir / "Akai_MPC"
        mpc_dir.mkdir(parents=True, exist_ok=True)
        proj_path = export_mpc_project(clean_kit_name, pads_dict, mpc_dir)
        prog_path = export_mpc_program(clean_kit_name, pads_dict, mpc_dir, copy_samples=True)
        targets_result["mpc"] = {
            "project_path": proj_path,
            "program_path_root": prog_path,
        }

    # 2. Native Instruments Maschine
    if target_lower in ("universal", "maschine"):
        maschine_dir = output_base_dir / "NI_Maschine"
        masch_path = export_ni_maschine_kit(clean_kit_name, pads_dict, maschine_dir)
        targets_result["maschine"] = {"bundle_path": masch_path}

    # 3. Roland SP-404MK2 & DOOM OS
    if target_lower in ("universal", "sp404mk2"):
        sp_mk2_dir = output_base_dir / "Roland_SP404MK2"
        mk2_path = export_sp404mk2_kit(clean_kit_name, pads_dict, sp_mk2_dir)
        targets_result["sp404mk2"] = {"import_folder": mk2_path}

    # 4. Roland SP-404A / SX
    if target_lower in ("universal", "sp404a"):
        sp_a_dir = output_base_dir / "Roland_SP404A"
        a_path = export_sp404a_kit(clean_kit_name, pads_dict, sp_a_dir)
        targets_result["sp404a"] = {"folder": a_path}

    # 5. Teenage Engineering Pocket Operator PO-33 / PO-133
    if target_lower in ("universal", "po33", "po-33", "pocket_operator"):
        po_dir = output_base_dir / "Pocket_Operator_PO33"
        reel_wav, duration, slices = export_po33_drum_reel(
            clean_kit_name, pads_dict, po_dir, gap_ms=150
        )
        targets_result["po33"] = {
            "reel_wav": reel_wav,
            "duration_sec": duration,
            "ram_limit_sec": 40.0,
            "slices_count": len(slices),
        }

    return {
        "success": True,
        "kit_name": clean_kit_name,
        "target": target,
        "kit_path": str(output_base_dir),
        "samples_count": len(pads_dict),
        "targets": targets_result,
        "message": f"Kit '{clean_kit_name}' generado exitosamente para destino '{target}'.",
    }


if __name__ == "__main__":
    print("=================================================================")
    print("Universal Hardware Kit Builder & Multi-Sampler Bridge v3.5 cargado")
    print(f"Directorio de Backups PO-33 detectado: {DEFAULT_PO_DIR}")
    backups = scan_po33_backups([DEFAULT_PO_DIR])
    print(f"Backups PO-33 encontrados: {len(backups)}")
    for b in backups:
        print(f"  • {b['filename']} ({b['duration_sec']}s, {b['channels']}ch, {b['status']})")
    print("=================================================================")
