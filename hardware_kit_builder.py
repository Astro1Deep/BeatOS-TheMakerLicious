#!/usr/bin/env python3
"""
Universal Hardware Kit Builder & Multi-Sampler Bridge (v3.5)
Soporta de forma nativa, estable y sin dependencias externas:
  1. Akai MPC Standalone (MPC One / Live / X / Studio):
     - Exportación de Programas (.xpm Drum Program) y Proyectos (.xpj)
     - Mapeo de 16 a 128 pads, Bancos A-H, capas de velocidad, afinación y choke groups.
  2. Native Instruments Maschine (MK3 / Plus / Mikro):
     - Mapeo de Grupos (WAV y mapa JSON)
     - Estructura de directorio estandarizada Samples/Group_A
  3. Roland SP-404MK2 & DOOM OS / SP-404A / SX:
     - Mapeo de Banco A (16 pads para MK2 / 12 pads para 404A)
     - Conversión a WAV 16-bit / 48kHz (MK2) y 16-bit / 44.1kHz (404A)
  4. Teenage Engineering Pocket Operator PO-33 K.O.! & PO-133:
     - Generador de 'Drum Reel' con pausas calibradas de 150ms para auto-slicing (Pads 9-16)
     - Presupuesto estricto de memoria (<= 40.0s de RAM de muestra)
     - Archivo de respaldos WAV originales con SHA-256; no decodifica datos del módem.
     - Escaneo, catalogación y generador de manifiesto de slices en JSON y TXT.
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# Directorio por defecto de backups de Pocket Operator
DEFAULT_PO_DIR = Path.home() / "Documents" / "PO- POCKET OPERATORS"
PO_IMPORT_LOCK = threading.Lock()


def po33_backup_dirs(root: str | Path) -> list[Path]:
    return [Path(root) / 'BeatOS/data/po33_backups', DEFAULT_PO_DIR,
            Path(root) / 'PO_BACKUPS', Path('/Volumes/MPCSMPL/PO_BACKUPS'),
            Path.home() / 'Music/Pocket_Operator_Backups']


def import_po33_backup(root: str | Path, filename: str, data: bytes, *, model: str | None = None, project: str | None = None) -> dict:
    """Archive original PCM WAV bytes without replacing any existing recording."""
    from po_backup_protocols import validate_model, safe_slug, write_sidecar
    enhanced = model is not None or project is not None
    model = validate_model(model or 'PO-33')
    project = project or Path(filename.replace('\\\\','/')).stem
    safe_slug(project)
    if not filename.lower().endswith('.wav') or not 44 <= len(data) <= 128 * 1024 * 1024:
        raise ValueError('Selecciona un WAV PCM de hasta 128 MiB')
    try:
        with wave.open(io.BytesIO(data), 'rb') as wav:
            if not 8000 <= wav.getframerate() <= 384000 or not 1 <= wav.getnchannels() <= 8:
                raise ValueError('Parámetros WAV no admitidos: usa PCM entre 8 y 384 kHz y de 1 a 8 canales')
            expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
            actual = 0
            while chunk := wav.readframes(65536):
                actual += len(chunk)
            if not expected or actual != expected:
                raise ValueError('WAV vacío o truncado; conserva y revisa la grabación original')
    except (wave.Error, EOFError) as error:
        raise ValueError('WAV PCM ilegible: ' + str(error)) from error
    digest = hashlib.sha256(data).hexdigest()
    name = re.sub(r'[^a-zA-Z0-9_-]+', '_', Path(filename.replace('\\', '/')).stem)[:60].strip('_') or 'PO33'
    if enhanced:
        name = safe_slug(project)
    if '_INCOMPLETO_' in filename.upper() and '_INCOMPLETO_' not in name.upper():
        name += '_INCOMPLETO_'
    library = Path(root).resolve()
    folder = library / 'BeatOS/data/po33_backups'
    if enhanced:
        folder = folder / model
    if not folder.resolve().is_relative_to(library):
        raise ValueError('Carpeta de respaldos fuera de la biblioteca')
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{name}_{digest}.wav'
    with PO_IMPORT_LOCK:
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise ValueError('Existe un enlace en el destino; no se ha sustituido')
            with target.open('rb') as existing:
                existing_digest = hashlib.file_digest(existing, 'sha256').hexdigest()
            if existing_digest != digest:
                raise ValueError('Existe otro archivo en el destino; no se ha sustituido')
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=folder, prefix='.po33-upload-', suffix='.tmp', delete=False) as output:
                    temporary = Path(output.name)
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    if enhanced:
        metadata = write_sidecar(target, model, project, source=filename)
    else:
        metadata = {'model': model, 'project': project}
    return {**inspect_po33_backup(target), 'model': metadata['model'], 'project': metadata['project'],
            'device_restore_verified': False, 'payload_verified': False}

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
    if any(k in f for k in ["cymbal", "ride", "crash"]):
        return "CYMBAL"
    if any(k in f for k in ["hat", "hh_", "hihat", "openhh", "closedhh"]):
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


def default_mute_group(sound_type: str) -> int:
    """Only like percussion families choke each other; all other pads stay free."""
    return {"KICK": 1, "HIHAT": 2, "SNARE": 3}.get(sound_type, 0)


def pad_mute_group(pad: dict) -> int:
    value = pad.get("mute_group", pad.get("muteGroup"))
    if value is None:
        kind = pad.get("sound_type", pad.get("soundType"))
        if not kind or kind == "SAMPLE":
            kind = detect_sound_type(pad.get("sample_file") or pad.get("source_path") or pad.get("sample_name", ""))
        value = default_mute_group(kind)
    value = int(value)
    if not 0 <= value <= 32:
        raise ValueError("Mute group must be between 0 and 32")
    return value


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
    root = Path(source_root or Path.cwd()).resolve()
    reference = Path(str(sample_ref).replace("\\", "/"))
    directories = [Path(d).resolve() for d in search_dirs if d and Path(d).is_dir()]
    def usable(candidate):
        return candidate.is_file() and candidate.resolve().is_relative_to(root)
    exact = [reference] if reference.is_absolute() else [d / reference for d in directories] + [root / reference]
    for candidate in exact:
        if usable(candidate):
            return candidate.resolve(), candidate.resolve().relative_to(root).as_posix()
    # Basename fallback must be unique: never substitute a different layer silently.
    name = reference.name
    for normalized in (False, True):
        matches = set()
        for directory in directories:
            for candidate in directory.rglob('*'):
                if (candidate.name == name if not normalized else _normalize_name(candidate.name) == _normalize_name(name)) and usable(candidate):
                    matches.add(candidate.resolve())
        if len(matches) == 1:
            match = matches.pop()
            return match, match.relative_to(root).as_posix()
        if matches:
            return None, ''
    return None, ''


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

        sample_name = ""
        sample_file = ""
        layers = [layer for layer in inst.findall(".//Layer") if layer.findtext("Active", "True").lower() != "false" and (layer.findtext("SampleName") or layer.findtext("SampleFile"))]
        for layer in layers:
            sn = layer.findtext("SampleName", "").strip()
            sf = layer.findtext("SampleFile", "").strip()
            if sf or sn:
                sample_name = sn
                sample_file = sf
                break

        if not sample_file and not sample_name:
            continue  # Pad sin muestra asignada: evitar pads fantasma vacíos

        target_ref = sample_file if sample_file else (
            sample_name if sample_name.lower().endswith(".wav") else f"{sample_name}.wav"
        )
        if target_ref == ".wav":
            continue

        found_path, rel_path = _resolve_sample_file(target_ref, search_dirs, root_p)
        actual_filename = found_path.name if found_path else target_ref
        actual_stem = found_path.stem if found_path else (sample_name or Path(target_ref).stem)
        stype = detect_sound_type(f"{actual_filename} {actual_stem} {sample_name}")

        pads[num] = {
            "pad_number": num,
            "sample_name": actual_stem,
            "sample_file": actual_filename,
            "full_path": str(found_path) if found_path else "",
            "rel_path": rel_path,
            "volume": vol,
            "pan": pan,
            "tune": tune_coarse,
            "mute_group": mute_group,
            "sound_type": stype,
            "missing": found_path is None,
            "layer_count": len(layers),
        }

    return {
        "program_name": prog_name,
        "program_type": prog_type,
        "format": "MPC_XPM",
        "file_path": str(xpm_p),
        "rel_path": xpm_p.relative_to(root_p).as_posix() if root_p in xpm_p.parents else xpm_p.name,
        "pads": pads,
    }


def parse_xpj_project(xpj_path: str | Path, source_root: Optional[str | Path] = None, track_index: Optional[int] = None) -> dict:
    """
    Extrae metadatos y lista de samples de un proyecto MPC .xpj (Gzip JSON),
    resolviendo de forma robusta la carpeta de datos y las rutas reales de los samples.
    """
    xpj_p = Path(xpj_path)
    root_p = Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else xpj_p.parent
    )

    with gzip.open(str(xpj_p), "rt", encoding="utf-8") as gz:
        content = gz.read()

    p_name = xpj_p.stem
    data_dir = _resolve_project_data_dir(xpj_p)

    payload = json.loads(content[content.index("{"):])
    data = payload.get("data", payload)
    tempo = float(data.get("masterTempo", data.get("tempo", 120.0)))
    key = data.get("key")
    samples = data.get("samples", [])
    search_dirs = ([data_dir] if data_dir else []) + [xpj_p.parent]
    pads = {}
    tracks = [{"index": i, "name": t.get("name") or f"Pista {i + 1}",
               "pad_count": len(t.get("program", {}).get("drum", {}).get("instruments", []))}
              for i, t in enumerate(data.get("tracks", [])) if t.get("program", {}).get("drum", {}).get("instruments")]
    if track_index is not None and track_index not in [t['index'] for t in tracks]:
        raise ValueError("La pista seleccionada no contiene un programa de batería")
    selected = track_index if track_index is not None else (tracks[0]['index'] if tracks else None)
    for i, track in enumerate(data.get("tracks", [])):
        if i != selected:
            continue
        instruments = track.get("program", {}).get("drum", {}).get("instruments", [])
        if not instruments:
            continue
        names = {sample.get("name"): sample.get("path", "")
                 for sample in samples + track.get("samples", [])}
        for idx, inst in enumerate(instruments[:128], start=1):
            layers = [layer for layer in inst.get("layersv", []) if layer.get("active", True) and (layer.get("sampleFile") or layer.get("sampleName"))]
            layer = layers[0] if layers else None
            if layer is None:
                continue
            sample = layer.get("sampleFile") or names.get(layer.get("sampleName")) or layer.get("sampleName")
            found, relative = _resolve_sample_file(sample, search_dirs, root_p)
            name = found.name if found else Path(sample).name
            kind = detect_sound_type(name)
            mix = inst.get("mixable", {})
            pads[idx] = {"pad_number": idx, "sample_name": layer.get("sampleName") or Path(name).stem,
                         "sample_file": name, "full_path": str(found) if found else sample,
                         "rel_path": relative, "volume": mix.get("volume", 0.707946),
                         "pan": mix.get("pan", 0.5), "tune": inst.get("coarseTune", 0),
                         "mute_group": inst.get("whichMuteGroup", default_mute_group(kind)), "sound_type": kind, "missing": found is None, "layer_count": len(layers)}
        break
    if not pads and not data.get("tracks"):
        # Legacy sample-pool projects have no instruments; retain stable pool order.
        for idx, sample in enumerate(samples[:16], start=1):
            path = sample.get("path", "")
            found, relative = _resolve_sample_file(path, search_dirs, root_p)
            name = found.name if found else Path(path).name
            kind = detect_sound_type(name)
            pads[idx] = {"pad_number": idx, "sample_name": Path(name).stem, "sample_file": name,
                         "full_path": str(found) if found else path, "rel_path": relative,
                         "volume": 0.707946, "pan": 0.5, "tune": 0,
                         "mute_group": default_mute_group(kind), "sound_type": kind}

    return {
        "project_name": p_name,
        "format": "MPC_XPJ",
        "file_path": str(xpj_p),
        "data_dir": str(data_dir) if data_dir else "",
        "tempo": tempo,
        "key": key,
        "tracks": tracks, "selected_track": selected,
        "total_samples": len(samples),
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

    if not exp_base.is_dir():
        return []
    exp_dir = (exp_base / expansion_name).resolve()
    if not exp_dir.is_relative_to(exp_base.resolve()):
        raise ValueError("Expansión fuera de la biblioteca")
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
                if 1 <= num <= 128:
                    for layer in inst.findall(".//Layer"):
                        sf = layer.findtext("SampleFile", "").strip()
                        sn = layer.findtext("SampleName", "").strip()
                        if sf or sn:
                            t_file = sf if sf else (sn if sn.lower().endswith(".wav") else f"{sn}.wav")
                            if t_file != ".wav":
                                samples.append(t_file)
                            break

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

def _find_mpc_template(filename: str, fallback_rel: str) -> Optional[Path]:
    """Busca la plantilla genuina de Akai MPC (.xpm o .xpj)."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "templates" / filename,
        here / "_INDEX_MPC_SAMPLE" / "templates" / filename,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _get_wav_frames(path_cand: Optional[str | Path]) -> int:
    """Devuelve el número total de frames de un archivo WAV, o 0 si no se puede leer."""
    if not path_cand:
        return 0
    p = Path(path_cand)
    if not p.is_file():
        return 0
    try:
        with wave.open(str(p), "rb") as wf:
            return wf.getnframes()
    except Exception:
        return 0


def _set_xml_text(parent: ET.Element, tag: str, value: str) -> None:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = value


def export_mpc_program(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
    copy_samples: bool = False,
) -> str:
    """Genera un archivo XML .xpm completo y genuino para Akai MPC Standalone."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{kit_name}.xpm"

    if copy_samples:
        copied = {}
        for key, info in pads_data.items():
            pad_num = int(key)
            p_info = dict(info)
            src = p_info.get("source_path", "")
            if src and Path(src).is_file():
                name = f"PAD{pad_num:03d}_{Path(src).stem}.wav"
                _convert_audio(src, out_dir / name, mono=False)
                p_info.update(sample_file=name, sample_name=Path(name).stem, n_frames=_get_wav_frames(out_dir/name))
            copied[pad_num] = p_info
        pads_data = copied

    tpl = _find_mpc_template(
        "template_drum.xpm",
        "MPC-Sample/Programs/Astro1Deep_Kit_01/Astro1Deep_Kit_01.xpm",
    )
    if tpl is not None:
        tree = ET.parse(str(tpl))
        root = tree.getroot()
        prog = root.find("Program")
        _set_xml_text(prog, "ProgramName", kit_name)

        for inst in prog.findall("Instruments/Instrument"):
            pad_num = int(inst.get("number", "0"))
            p_info = pads_data.get(pad_num) or pads_data.get(str(pad_num)) or {}
            s_name = (p_info.get("sample_name") or "").strip()
            s_file = (
                p_info.get("sample_file")
                or p_info.get("sample_path")
                or p_info.get("source_path")
                or (f"{s_name}.wav" if s_name else "")
            )
            vol = float(p_info.get("volume", 0.707946))
            pan = float(p_info.get("pan", 0.500000))
            tune = int(p_info.get("tune", 0))
            mute = pad_mute_group(p_info)

            _set_xml_text(inst, "Volume", f"{vol:.6f}")
            _set_xml_text(inst, "Pan", f"{pan:.6f}")
            _set_xml_text(inst, "TuneCoarse", str(tune))
            _set_xml_text(inst, "TuneFine", "0")
            _set_xml_text(inst, "MuteGroup", str(mute))
            for target in inst:
                if re.fullmatch(r"MuteTarget[1-4]?", target.tag):
                    target.text = "0"

            layers = inst.findall("Layers/Layer")
            for lay in layers:
                _set_xml_text(lay, "Active", "False")
                _set_xml_text(lay, "SampleName", "")
                _set_xml_text(lay, "SampleFile", "")
                _set_xml_text(lay, "SliceIndex", "129")
                _set_xml_text(lay, "SliceStart", "0")
                _set_xml_text(lay, "SliceEnd", "0")
                _set_xml_text(lay, "SliceLoopStart", "0")

            if (s_file or s_name) and layers:
                file_name = (
                    Path(s_file).name
                    if s_file
                    else (f"{s_name}.wav" if not s_name.lower().endswith(".wav") else s_name)
                )
                name_stem = Path(file_name).stem
                wav_cand = out_dir / file_name
                if not wav_cand.is_file() and p_info.get("source_path"):
                    wav_cand = Path(p_info["source_path"])
                n_frames = _get_wav_frames(wav_cand)

                lay0 = layers[0]
                _set_xml_text(lay0, "Active", "True")
                _set_xml_text(lay0, "SampleName", name_stem)
                _set_xml_text(lay0, "SampleFile", file_name)
                _set_xml_text(lay0, "VelStart", "0")
                _set_xml_text(lay0, "VelEnd", "127")
                _set_xml_text(lay0, "SliceIndex", "129")
                _set_xml_text(lay0, "SliceStart", "0")
                _set_xml_text(lay0, "SliceEnd", str(n_frames))
                _set_xml_text(lay0, "SliceLoopStart", "0")

        ET.indent(tree, space="  ", level=0)
        tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
        return str(out_path)

    # Fallback si no existe plantilla en disco
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
        p_info = pads_data.get(pad_num) or pads_data.get(str(pad_num)) or {}
        s_name = (p_info.get("sample_name") or "").strip()
        s_file = (
            p_info.get("sample_file")
            or p_info.get("sample_path")
            or p_info.get("source_path")
            or (f"{s_name}.wav" if s_name else "")
        )
        vol = float(p_info.get("volume", 0.707946))
        pan = float(p_info.get("pan", 0.500000))
        tune = int(p_info.get("tune", 0))
        mute = pad_mute_group(p_info)

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
            if layer_idx == 1 and (s_file or s_name):
                file_name = Path(s_file).name if s_file else (f"{s_name}.wav" if not s_name.endswith(".wav") else s_name)
                name_stem = Path(file_name).stem
                ET.SubElement(layer, "Active").text = "True"
                ET.SubElement(layer, "SampleName").text = name_stem
                ET.SubElement(layer, "SampleFile").text = file_name
                ET.SubElement(layer, "SliceIndex").text = "129"
                ET.SubElement(layer, "VelStart").text = "0"
                ET.SubElement(layer, "VelEnd").text = "127"
            else:
                ET.SubElement(layer, "Active").text = "False"
                ET.SubElement(layer, "SampleName").text = ""
                ET.SubElement(layer, "SampleFile").text = ""
                ET.SubElement(layer, "SliceIndex").text = "129"
                ET.SubElement(layer, "VelStart").text = "0"
                ET.SubElement(layer, "VelEnd").text = "127"

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
    return str(out_path)


def _replace_template_kit_name(obj: Any, old_name: str, new_name: str) -> Any:
    if isinstance(obj, dict):
        return {
            (new_name if k == old_name else k): _replace_template_kit_name(v, old_name, new_name)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_replace_template_kit_name(i, old_name, new_name) for i in obj]
    if isinstance(obj, str) and obj == old_name:
        return new_name
    return obj


def export_mpc_project(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
    tempo: float = 120.0,
    key: str = "C",
) -> str:
    """Genera un proyecto MPC genuino (.xpj con cabecera ACVS) junto a su carpeta [ProjectData]."""
    base_dir = Path(output_dir) / kit_name
    base_dir.mkdir(parents=True, exist_ok=True)
    proj_data_dir = base_dir / f"{kit_name}_[ProjectData]"
    proj_data_dir.mkdir(parents=True, exist_ok=True)

    # Copiar muestras en [ProjectData]
    linked_samples: list[tuple[str, str, int]] = []
    seen_files: set[str] = set()
    normalized_pads = {}
    for pad_num in range(1, 129):
        p_info = pads_data.get(pad_num) or pads_data.get(str(pad_num)) or {}
        src = p_info.get("source_path", "")
        s_file = p_info.get("sample_file") or (Path(src).name if src else "")
        if src and os.path.exists(src):
            s_name = f"PAD{pad_num:03d}_{Path(src).stem}.wav"
            dest = proj_data_dir / s_name
            _convert_audio(src, dest, mono=False)
            s_stem = Path(s_name).stem
            n_frames = _get_wav_frames(dest)
            if s_name not in seen_files:
                seen_files.add(s_name)
                linked_samples.append((s_stem, s_name, n_frames))
            p_copy = dict(p_info)
            p_copy["sample_file"] = s_name
            p_copy["sample_name"] = s_stem
            p_copy["n_frames"] = n_frames
            normalized_pads[pad_num] = p_copy
        elif s_file and (proj_data_dir / s_file).is_file():
            dest = proj_data_dir / s_file
            s_stem = Path(s_file).stem
            n_frames = _get_wav_frames(dest)
            if s_file not in seen_files:
                seen_files.add(s_file)
                linked_samples.append((s_stem, s_file, n_frames))
            p_copy = dict(p_info)
            p_copy["sample_file"] = s_file
            p_copy["sample_name"] = s_stem
            p_copy["n_frames"] = n_frames
            normalized_pads[pad_num] = p_copy
        else:
            normalized_pads[pad_num] = p_info

    # Exportar el programa Drum .xpm genuino dentro de [ProjectData]
    export_mpc_program(kit_name, normalized_pads, proj_data_dir, copy_samples=False)

    xpj_path = base_dir / f"{kit_name}.xpj"
    tpl_xpj = _find_mpc_template(
        "template_project.xpj",
        "MPC-Sample/Programs/Astro1Deep_Kit_01/Astro1Deep_Kit_01.xpj",
    )
    if tpl_xpj is not None:
        raw_bytes = tpl_xpj.read_bytes()
        try:
            raw_bytes = gzip.decompress(raw_bytes)
        except OSError:
            pass
        raw_text = raw_bytes.decode("utf-8")
        json_idx = raw_text.index("{")
        header = raw_text[:json_idx]
        payload = json.loads(raw_text[json_idx:])
        payload = _replace_template_kit_name(payload, "Astro1Deep_Kit_01", kit_name)

        data = payload.get("data", {})
        key_str = key if " " in key else f"{key} Major"
        data["key"] = key_str
        data["masterTempo"] = float(tempo)

        for seq in data.get("sequences", []):
            if isinstance(seq, dict) and isinstance(seq.get("value"), dict):
                seq["value"]["bpm"] = float(tempo)

        data["samples"] = [
            {
                "version": 1,
                "name": s_stem,
                "path": s_file,
                "loadImpl": 0,
                "metadata": {
                    "tempo": 0.0,
                    "rootNote": 60,
                    "tune": 0.0,
                    "key": key_str,
                },
            }
            for s_stem, s_file, _ in linked_samples
        ]

        tracks = data.get("tracks", [])[:1]
        data["tracks"] = tracks
        if tracks:
            for t in tracks[1:]:
                if isinstance(t, dict) and "samples" in t:
                    t["samples"] = []
            tracks[0]["name"] = kit_name
            tracks[0]["samples"] = copy.deepcopy(data["samples"]) if "copy" in globals() else list(data["samples"])
            prog = tracks[0].get("program", {})
            prog["name"] = kit_name
            drum = prog.get("drum", {})
            insts = drum.get("instruments", [])
            for idx, inst in enumerate(insts):
                pad_num = idx + 1
                p_info = normalized_pads.get(pad_num, {})
                s_file = p_info.get("sample_file", "")
                s_stem = p_info.get("sample_name", "")
                n_frames = int(p_info.get("n_frames", 0))
                vol = float(p_info.get("volume", 0.707946))
                pan = float(p_info.get("pan", 0.500000))
                tune = int(p_info.get("tune", 0))
                mute = pad_mute_group(p_info)

                inst["coarseTune"] = tune
                inst["whichMuteGroup"] = mute
                if isinstance(inst.get("muteTargets"), dict):
                    inst["muteTargets"] = {k: 0 for k in inst["muteTargets"]}
                if isinstance(inst.get("mixable"), dict):
                    inst["mixable"]["volume"] = vol
                    inst["mixable"]["pan"] = pan

                layersv = inst.get("layersv", [])
                for lay in layersv:
                    lay["active"] = False
                    lay["sampleName"] = ""
                    lay["sampleFile"] = ""
                    if isinstance(lay.get("sliceInfo"), dict):
                        lay["sliceInfo"]["Start"] = 0
                        lay["sliceInfo"]["End"] = 0
                        lay["sliceInfo"]["LoopStart"] = 0

                if s_file and layersv:
                    lay0 = layersv[0]
                    lay0["active"] = True
                    lay0["sampleName"] = s_stem or Path(s_file).stem
                    lay0["sampleFile"] = s_file
                    lay0["sliceIndex"] = 129
                    if isinstance(lay0.get("sliceInfo"), dict):
                        lay0["sliceInfo"]["Start"] = 0
                        lay0["sliceInfo"]["End"] = n_frames
                        lay0["sliceInfo"]["LoopStart"] = 0

        out_content = header + json.dumps(payload, indent=0)
        with gzip.open(str(xpj_path), "wb") as gz:
            gz.write(out_content.encode("utf-8"))
        return str(xpj_path)

    header_fallback = "ACVS\n1.3.0.12\nSerialisableProjectData\njson\nLinux\n"
    project_dict = {
        "data": {
            "version": 28,
            "key": f"{key} Major",
            "masterTempo": float(tempo),
            "samples": [
                {"version": 1, "name": s_stem, "path": s_file, "loadImpl": 0}
                for s_stem, s_file, _ in linked_samples
            ],
        }
    }
    with gzip.open(str(xpj_path), "wb") as gz:
        gz.write((header_fallback + json.dumps(project_dict)).encode("utf-8"))

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
            _convert_audio(src_path, dest_file, mono=False, sample_rate=48000)
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
            _convert_audio(src_path, dest_file, mono=False)

    return str(kit_dir)


def export_ni_maschine_kit(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
) -> str:
    """
    Genera un paquete de Drum Kit para Native Instruments Maschine (WAV y mapa JSON; no genera .mxgrp nativo).
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

    for pad_num in sorted(pads_data):
        p_info = pads_data[pad_num]
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Sound_{pad_num:02d}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", s_name)
        dest_filename = f"A{pad_num:02d}_{clean_name}.wav"

        if src_path and Path(src_path).exists():
            _convert_audio(src_path, samples_dir / dest_filename, mono=False)

        manifest["sounds"].append({
            "slot": pad_num,
            "name": s_name,
            "file": f"Samples/Group_A/{dest_filename}",
            "tune": p_info.get("tune", 0),
            "pan": p_info.get("pan", 0.5),
            "volume": p_info.get("volume", 0.707946),
            "choke_group": pad_mute_group(p_info),
        })

    manifest_path = groups_dir / f"{kit_name}_Maschine_Map.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return str(base_dir)


# ==============================================================================
# 3. TEENAGE ENGINEERING (PO-33 / PO-133 & EP-133 K.O. II) MODULE
# ==============================================================================

def export_ep133_ko2_kit(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
) -> tuple[str, str]:
    """
    Genera un paquete de Drum Kit estructurado para Teenage Engineering EP-133 K.O. II.
    Mapea hasta 16 pads con slots de sonido (001 a 016), grupos A y B, y genera:
    1. Carpeta con samples .wav listos para arrastrar al EP Sample Tool (teenage.engineering/apps/ep-sample-tool)
    2. Archivo meta.json con asignaciones de grupo, tecla, volumen, afinación y paneo.
    3. Archivo ZIP de transporte de muestras y mapa; no es un backup nativo del EP-133.
    4. Guía técnica README_EP133_KO_II.txt con instrucciones de importación paso a paso.
    
    Retorna: (ruta_directorio_kit, ruta_archivo_pak)
    """
    clean_kit_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", kit_name.strip()) or "EP133_Kit"
    kit_dir = Path(output_dir) / clean_kit_name
    sounds_dir = kit_dir / "sounds"
    sounds_dir.mkdir(parents=True, exist_ok=True)

    # Mapeo de teclas de hardware EP-133 (12 teclas por grupo: 1-9, ., 0, ENTER)
    ep_keys = [
        ("A", "1"), ("A", "2"), ("A", "3"),
        ("A", "4"), ("A", "5"), ("A", "6"),
        ("A", "7"), ("A", "8"), ("A", "9"),
        ("A", "."), ("A", "0"), ("A", "ENTER"),
        ("B", "1"), ("B", "2"), ("B", "3"), ("B", "4")
    ]

    manifest = {
        "version": 1,
        "device": "Teenage Engineering EP-133 K.O. II",
        "created_by": "BeatOS — The MakerLicious",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "package_name": clean_kit_name,
        "sample_count": 0,
        "sounds": []
    }

    copied_count = 0
    for pad_num in sorted(pads_data):
        p_info = pads_data[pad_num]
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Sound_{pad_num:02d}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", s_name)
        slot_filename = f"{pad_num:03d}_PAD{pad_num:02d}_{clean_name}.wav"
        dest_file = sounds_dir / slot_filename

        grp, key = ep_keys[pad_num - 1] if pad_num - 1 < len(ep_keys) else ("B", str(pad_num))

        if not src_path or not Path(src_path).is_file():
            raise ValueError(f"Muestra ausente en pad {pad_num}")
        # Sample Tool accepts stereo PCM; preserve its channels and original level.
        _convert_audio(src_path, dest_file, mono=False)
        copied_count += 1

        manifest["sounds"].append({
            "slot": pad_num,
            "name": s_name,
            "filename": f"sounds/{slot_filename}",
            "group": grp,
            "key": key,
            "tune": p_info.get("tune", 0),
            "pan": p_info.get("pan", 0.5),
            "volume": p_info.get("volume", 0.707946),
            "choke_group": pad_mute_group(p_info),
            "sound_type": p_info.get("sound_type", "SAMPLE"),
        })

    manifest["sample_count"] = copied_count

    meta_file = kit_dir / "meta.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    readme_es_content = f"""================================================================================
TEENAGE ENGINEERING EP-133 K.O. II — KIT DE SAMPLES (BeatOS The MakerLicious)
================================================================================
Kit: {clean_kit_name}
Total de Muestras: {copied_count} / 16

INSTRUCCIONES DE IMPORTACIÓN:
1. Conecta tu EP-133 K.O. II por USB-C a tu ordenador y enciéndelo.
2. Abre en Google Chrome o navegador compatible:
   https://teenage.engineering/apps/ep-sample-tool
3. Método A (Arrastrar y Soltar):
   - Abre la carpeta 'sounds/' y arrastra los archivos .wav directamente a los
     slots de sonido deseados (001 - 016).
4. El ZIP es un contenedor de transporte de BeatOS. Extráelo y carga los WAV.
   No lo restaures como backup nativo. Los grupos de choke del mapa son una
   referencia: configura las asignaciones en el hardware.

MAPEO DE PADS A TECLAS EP-133:
- Pad 01 -> Grupo A, Tecla 1
- Pad 02 -> Grupo A, Tecla 2
- Pad 03 -> Grupo A, Tecla 3
- Pad 04 -> Grupo A, Tecla 4
- Pad 05 -> Grupo A, Tecla 5
- Pad 06 -> Grupo A, Tecla 6
- Pad 07 -> Grupo A, Tecla 7
- Pad 08 -> Grupo A, Tecla 8
- Pad 09 -> Grupo A, Tecla 9
- Pad 10 -> Grupo A, Tecla . (punto)
- Pad 11 -> Grupo A, Tecla 0
- Pad 12 -> Grupo A, Tecla ENTER
- Pad 13 -> Grupo B, Tecla 1
- Pad 14 -> Grupo B, Tecla 2
- Pad 15 -> Grupo B, Tecla 3
- Pad 16 -> Grupo B, Tecla 4
================================================================================
"""
    readme_en_content = f"""================================================================================
TEENAGE ENGINEERING EP-133 K.O. II — BEATOS SAMPLE KIT
================================================================================
Kit: {clean_kit_name}
Samples: {copied_count} / 16

IMPORT INSTRUCTIONS:
1. Connect EP-133 K.O. II to the computer with a USB-C data cable.
2. Open https://teenage.engineering/apps/ep-sample-tool in a compatible
   desktop browser and authorize the connected device.
3. Extract the BeatOS transport ZIP. Drag the WAV files from sounds/
   to the desired sound slots using the official Sample Tool.
4. Use meta.json as an assignment reference; its gain, pan, tuning and
   choke-group fields are not automatically restored to the hardware.
5. Audition all assigned keys and save changes through the device.
6. The ZIP is NOT a native EP-133 backup. Never use its backup-restore
   feature to install a BeatOS transport archive.

BEATOS PAD → EP-133 GROUP / KEY:
  01=A/1   02=A/2   03=A/3   04=A/4
  05=A/5   06=A/6   07=A/7   08=A/8
  09=A/9   10=A/.   11=A/0   12=A/ENTER
  13=B/1   14=B/2   15=B/3   16=B/4
================================================================================
"""
    with open(kit_dir / "README_EP133_KO_II.txt", "w", encoding="utf-8") as f:
        f.write(readme_en_content)
    with open(kit_dir / "README_EP133_KO_II_ES.txt", "w", encoding="utf-8") as f:
        f.write(readme_es_content)

    # ZIP de transporte de BeatOS; los backups nativos del fabricante tienen otro esquema.
    pak_file = kit_dir.parent / f"{clean_kit_name}_EP133.zip"
    with zipfile.ZipFile(pak_file, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(meta_file, arcname="meta.json")
        for s_file in sounds_dir.glob("*.wav"):
            if s_file.name.startswith("."):
                continue
            z.write(s_file, arcname=f"sounds/{s_file.name}")
        z.write(kit_dir / "README_EP133_KO_II.txt", arcname="README_EP133_KO_II.txt")
        z.write(kit_dir / "README_EP133_KO_II_ES.txt", arcname="README_EP133_KO_II_ES.txt")

    return str(kit_dir), str(pak_file)


def _convert_audio(source, destination=None, mono=True, tune=0, sample_rate=44100):
    """Decode/resample using FFmpeg; preserve compatible PCM without a dependency."""
    try:
        with wave.open(str(source), 'rb') as wav:
            if not tune and wav.getsampwidth() == 2 and wav.getframerate() == sample_rate and (wav.getnchannels() == 1 if mono else wav.getnchannels() in (1, 2)):
                raw = wav.readframes(wav.getnframes())
                if raw and len(raw) == wav.getnframes() * wav.getnchannels() * 2:
                    if destination:
                        shutil.copyfile(source, destination)
                        return
                    return list(struct.unpack(f'<{len(raw)//2}h', raw))
                # Malformed source headers must be decoded, never copied as valid WAV.

    except (wave.Error, EOFError):
        pass
    executable = shutil.which('ffmpeg')
    if not executable:
        raise ValueError("Esta conversión necesita FFmpeg. Instálalo o usa WAV PCM 16-bit/44.1kHz.")
    command = [executable, '-nostdin', '-v', 'error', '-i', str(source), '-map', '0:a:0', '-ar', str(sample_rate)]
    if mono:
        command += ['-ac', '1']
    if tune:
        command += ['-af', f'aresample=44100,asetrate={44100 * 2**(tune/12)},aresample=44100']
    command += ['-c:a', 'pcm_s16le']
    command += ['-f', 'wav', '-y', str(destination)] if destination else ['-f', 's16le', 'pipe:1']
    result = subprocess.run(command, capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError(f"No se pudo decodificar {Path(source).name}")
    if destination:
        with wave.open(str(destination), 'rb') as wav:
            if not wav.getnframes() or wav.getnchannels() not in (1, 2):
                raise ValueError("Se requiere audio mono o estéreo no vacío")
        return
    if not result.stdout:
        raise ValueError("Audio vacío")
    return list(struct.unpack(f'<{len(result.stdout)//2}h', result.stdout))


def _read_wav_mono_16bit_44k(file_path):
    return _convert_audio(file_path)


def export_po33_drum_reel(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
    gap_ms: int = 150,
    max_total_sec: float = 40.0,
) -> tuple[str, float, list[dict]]:
    """
    Genera un archivo WAV 'Drum Reel' de hasta 16 golpes espaciados por pausas de silencio (150ms)
    como ayuda al auto-slicing del PO-33; los cortes necesitan revisión en TRIM.
    Garantiza rigurosamente que la duración total nunca supere los 40.00 segundos de memoria física
    de la PO-33 aplicando recorte inteligente (Smart Trim) con fade-out a transitorios excesivos.
    Retorna (ruta_wav, duracion_segundos, lista_slices_con_timestamps).
    """
    if not math.isfinite(float(max_total_sec)) or not 1 <= float(max_total_sec) <= 40:
        raise ValueError("Presupuesto PO: entre 1 y 40 segundos")
    if not isinstance(gap_ms, int) or not 0 <= gap_ms <= 500:
        raise ValueError("Separación PO: entre 0 y 500 ms")
    if len(pads_data) * gap_ms / 1000 >= max_total_sec:
        raise ValueError("Las pausas ocupan todo el presupuesto; reduce su duración")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{kit_name}_PO33_AutoSlice_Reel.wav"

    sample_rate = 44100
    gap_samples = int(sample_rate * (gap_ms / 1000.0))
    zero_frame = struct.pack("<h", 0)

    # 1. Leer y decodificar cada pad activo con el lector universal multi-formato
    parsed_pads = []
    for pad_num in range(1, 17):
        p_info = pads_data.get(pad_num, {})
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Pad_{pad_num}")
        s_type = p_info.get("sound_type", "SAMPLE")

        if not src_path or not Path(src_path).exists():
            if pad_num in pads_data:
                raise ValueError(f"Muestra ausente en pad {pad_num}")
            continue

        try:
            mono_samples = _convert_audio(src_path, tune=float(p_info.get("tune", 0)))
            if not mono_samples:
                raise ValueError("Audio vacío")
            gain = float(p_info.get("volume", 0.707946))
            mono_samples = [max(-32768, min(32767, round(sample * gain))) for sample in mono_samples]

            parsed_pads.append({
                "pad_num": pad_num,
                "name": s_name,
                "type": s_type,
                "samples": mono_samples,
                "raw_dur": len(mono_samples) / sample_rate,
                "original_raw_dur": len(mono_samples) / sample_rate
            })
        except Exception as e:
            raise ValueError(f"No se pudo procesar pad {pad_num}: {e}") from e

    if not parsed_pads:
        with wave.open(str(out_file), "wb") as out_wf:
            out_wf.setnchannels(1)
            out_wf.setsampwidth(2)
            out_wf.setframerate(sample_rate)
            out_wf.writeframes(b"")
        return str(out_file), 0.0, []

    # 2. Control riguroso de presupuesto hardware (40.00 segundos máx)
    MAX_TOTAL_SEC = float(max_total_sec)
    num_pads = len(parsed_pads)
    total_gap_sec = num_pads * (gap_ms / 1000.0)
    max_audio_sec = MAX_TOTAL_SEC - total_gap_sec

    total_raw_audio_sec = sum(p["raw_dur"] for p in parsed_pads)
    is_trimmed = False

    # Si excede el presupuesto disponible de audio, calcular límite por corte (water-filling)
    if total_raw_audio_sec > max_audio_sec:
        is_trimmed = True
        low = 0.0
        high = max(p["raw_dur"] for p in parsed_pads)
        for _ in range(40):
            mid = (low + high) / 2.0
            cur_sum = sum(min(p["raw_dur"], mid) for p in parsed_pads)
            if cur_sum > max_audio_sec:
                high = mid
            else:
                low = mid
        cap_sec = low

        # Aplicar recorte y fade-out suave (50ms) a las muestras que sobrepasen el cap
        fade_len = int(0.050 * sample_rate)
        for p in parsed_pads:
            if p["raw_dur"] > cap_sec:
                max_frames = max(1, int(cap_sec * sample_rate))
                trimmed = p["samples"][:max_frames]
                actual_fade = min(fade_len, len(trimmed))
                for fi in range(actual_fade):
                    fade_factor = fi / float(max(1, actual_fade - 1))
                    idx = len(trimmed) - 1 - fi
                    trimmed[idx] = int(trimmed[idx] * fade_factor)
                p["samples"] = trimmed
                p["raw_dur"] = len(trimmed) / sample_rate

    # 3. Concatenar muestras intercalando los 150ms exactos de silencio
    collected_audio = bytearray()
    total_audio_frames = 0
    slices_meta = []

    for p in parsed_pads:
        pad_num = p["pad_num"]
        s_name = p["name"]
        s_type = p["type"]
        s_data = struct.pack(f"<{len(p['samples'])}h", *p["samples"])

        start_frame = total_audio_frames
        start_sec = start_frame / sample_rate

        collected_audio.extend(s_data)
        added_frames = len(p["samples"])
        total_audio_frames += added_frames

        end_frame = total_audio_frames
        end_sec = end_frame / sample_rate

        slices_meta.append({
            "slice_number": len(slices_meta) + 1,
            "source_pad": pad_num,
            "name": s_name,
            "type": s_type,
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "duration_sec": round(end_sec - start_sec, 3),
            "start_frame": start_frame,
            "end_frame": end_frame,
            "trimmed": is_trimmed and (end_sec - start_sec < p.get("original_raw_dur", end_sec - start_sec))
        })

        # Silencio exacto entre transitorios (Auto-Slice trigger)
        collected_audio.extend(zero_frame * gap_samples)
        total_audio_frames += gap_samples

    total_duration_sec = total_audio_frames / sample_rate

    # 4. Normalización a -0.5 dBFS para entrada limpia sin recorte
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

    # Escribir archivo WAV mono 16-bit 44.1kHz garantizado <= 40.00s
    with wave.open(str(out_file), "wb") as out_wf:
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(sample_rate)
        out_wf.writeframes(collected_audio)

    # Manifiesto JSON
    slice_json_path = out_dir / f"{kit_name}_PO33_Slices.json"
    with open(slice_json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "kit_name": kit_name,
                "total_duration_sec": round(total_duration_sec, 2),
                "ram_limit_sec": MAX_TOTAL_SEC,
                "gap_ms": gap_ms,
                "smart_trim_applied": is_trimmed,
                "budget_used_pct": round((total_duration_sec / MAX_TOTAL_SEC) * 100, 1),
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
Kit: {kit_name} | Duración: {total_duration_sec:.2f}s / {MAX_TOTAL_SEC:.2f}s presupuestados
Smart Trim Aplicado: {'SÍ (Ajustado al presupuesto elegido)' if is_trimmed else 'NO (Dentro del presupuesto)'}
========================================================================

1. Conecta un cable minijack 3.5mm estéreo desde la salida de tu Mac a la entrada LINE IN (izquierda) de la PO-33.
2. EN TU PO-33:
   - Mantén RECORD + un PAD DE BATERÍA (del 9 al 16) donde quieras alojar el kit.
   - La pantalla mostrará "IN" parpadeando o el nivel de entrada.
3. EN TU MAC:
   - Reproduce el archivo: '{out_file.name}'
   - Ajusta el nivel de salida según tu interfaz para evitar saturación; no hay un porcentaje universal.
4. RESULTADO:
   - Revisa y ajusta los 16 cortes en TRIM. Las pausas de 150ms son una ayuda, no garantizan detección perfecta.
   - ¡Listo para secuenciar con el botón WRITE!

Para volcado de BACKUP COMPLETO (duración variable; reemplaza muestras y patrones):
- Restaurar: Mantén WRITE + SOUND + RECORD y reproduce el audio módem FSK.
- Crear Backup: Mantén WRITE + SOUND y presiona PLAY para enviar audio hacia tu Mac.
========================================================================
"""
    guide_path.write_text(guide_text, encoding="utf-8")
    guide_en_path = out_dir / f"{kit_name}_PO33_Loading_Guide_EN.txt"
    guide_en_text = f"""========================================================================
TEENAGE ENGINEERING PO-33 / PO-133 — BEATOS AUDIO REEL LOADING GUIDE
Kit: {kit_name} | Reel: {total_duration_sec:.2f}s | Budget: {MAX_TOTAL_SEC:.2f}s
Smart trim: {'YES (shortened to fit the chosen budget)' if is_trimmed else 'NO (within chosen budget)'}
========================================================================

IMPORT PROCEDURE (AUDIO RECORDING, NOT MODEM RESTORE):
1. Connect the computer/audio interface line output to the PO-33 LINE IN.
2. On the PO-33, start sampling into the intended DRUM pad (9–16).
3. Play '{out_file.name}' at a safe level, avoiding clipping.
4. Check each detected slice and correct its boundaries using TRIM.
5. Audition the sounds and verify that the device has sufficient free memory.

The JSON slice positions are approximate; sample separation is not
guaranteed. BeatOS cannot read the PO's real remaining recording memory.
This WAV is NOT a full device backup and contains no verified FSK payload.

For the original hardware modem backup/restore workflow use your PO's
manufacturer documentation. Keep the original backup audio unmodified.
========================================================================
"""
    guide_en_path.write_text(guide_en_text, encoding="utf-8")

    return str(out_file), round(total_duration_sec, 2), slices_meta


def verify_po33_backup_wav(wav_path: str | Path) -> dict:
    """Compatibility alias: inspect audio only, never certify modem payload."""
    return inspect_po33_backup(wav_path)


def inspect_po33_backup(wav_path: str | Path) -> dict:
    """
    Inspect WAV structure and initial levels; never certify PO-33 modem data.
    """
    p = Path(wav_path)
    if not p.exists() or not p.is_file():
        return {"valid": False, "error": f"Archivo no encontrado: {wav_path}"}

    try:
        if p.stat().st_size > 128 * 1024 * 1024:
            return {'valid': False, 'error': 'El límite de inspección es 128 MiB; el original sigue disponible para descargar'}
        with wave.open(str(p), "rb") as wf:
            n_ch = wf.getnchannels()
            sw = wf.getsampwidth()
            fr = wf.getframerate()
            n_frames = wf.getnframes()
            duration = n_frames / fr

            # Leer una porción representativa para análisis de amplitud y señal
            sample_frames_to_read = min(n_frames, fr * 4, 48000 * 4) if n_ch == 2 and sw == 2 else 0
            raw_sample = wf.readframes(sample_frames_to_read)
            complete = False
            if n_frames:
                wf.setpos(n_frames - 1)
                complete = len(wf.readframes(1)) == n_ch * sw and not wf.readframes(1)
        is_stereo = n_ch == 2
        is_16bit = sw == 2
        audio_compatible = complete and is_stereo and is_16bit and fr in (44100, 48000)

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

        status = "AUDIO_COMPATIBLE_NOT_DECODED"
        if not audio_compatible:
            status = "UNSUPPORTED_OR_INCOMPLETE_AUDIO"
        elif has_clipping:
            status = "WARNING_CLIPPING_DETECTED"
        elif is_too_quiet:
            status = "WARNING_SIGNAL_TOO_QUIET"

        with p.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        return {
            "valid": False,
            "audio_compatible": audio_compatible,
            "wav_complete": complete,
            "capture_interrupted": '_INCOMPLETO_' in p.name.upper(),
            "sha256": digest,
            "payload_verified": False,
            "inspection_scope": "Estructura WAV y amplitud inicial (hasta 4s y 192000 frames); no verifica datos del módem",
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


def scan_po33_backups(search_dirs: Optional[list[str | Path]] = None, cache: Optional[dict] = None) -> list[dict]:
    """
    Escanea directorios en busca de backups PO-33 y devuelve el catálogo ordenado.
    """
    if search_dirs is None:
        search_dirs = [
            DEFAULT_PO_DIR,
            Path('/Volumes/MPCSMPL/PO_BACKUPS'),
            Path.home() / "Music" / "Pocket_Operator_Backups",
        ]

    results = []
    seen_paths = set()
    cache = {} if cache is None else cache

    for d in search_dirs:
        p_dir = Path(d)
        if not p_dir.exists():
            continue
        for wav in p_dir.rglob('*'):
            if not wav.is_file() or wav.suffix.lower() != '.wav' or any(part.startswith('.') for part in wav.relative_to(p_dir).parts):
                continue
            wav = wav.resolve()
            if not wav.is_relative_to(p_dir.resolve()) or wav in seen_paths:
                continue
            seen_paths.add(wav)
            stat = wav.stat()
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            previous = cache.get(wav)
            if previous and previous[0] == signature:
                info = dict(previous[1])
            else:
                info = inspect_po33_backup(wav)
                cache[wav] = (signature, dict(info))
            from po_backup_protocols import read_sidecar
            metadata = read_sidecar(wav, info.get('sha256', ''))
            info['model'] = metadata['model'] if metadata else 'UNSPECIFIED'
            info['project'] = metadata['project'] if metadata else wav.stem
            info['device_restore_verified'] = False
            info['payload_verified'] = False
            info['verification_status'] = metadata.get('verification_status', 'AUDIO_ARCHIVED_NOT_DECODED') if metadata else 'LEGACY_UNCLASSIFIED_AUDIO'
            info["filename"] = wav.name
            info["path"] = str(wav.resolve())
            results.append(info)

    for stale in cache.keys() - seen_paths:
        del cache[stale]
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
    tempo: float = 120.0,
    po_options: Optional[dict] = None,
) -> dict:
    """
    Función maestra llamada por la API web (/api/create_kit) o por línea de comandos.
    Genera kits optimizados para MPC, Maschine, SP-404MK2, SP-404A o PO-33.
    """
    clean_kit_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", kit_name.strip()) or "Custom_Beatmaker_Kit"

    if source_root is None:
        source_root = Path.cwd()
    else:
        source_root = Path(source_root)

    if output_base_dir is None:
        output_base_dir = source_root / "Custom_Kits" / clean_kit_name
    else:
        output_base_dir = Path(output_base_dir) / clean_kit_name


    if output_base_dir.exists():
        raise FileExistsError("Ya existe un kit con ese nombre. Elige otro para conservar el original.")

    # Normalizar pads_data en un diccionario de 1 a 16 (o más)
    pads_dict = {}
    if isinstance(pads, list):
        for item in pads:
            pad_num = int(item.get("pad", item.get("pad_number", 0)))
            if pad_num in pads_dict:
                raise ValueError("Pad duplicado")
            rel_path = item.get("rel_path", item.get("relPath", ""))
            src_path = item.get("source_path", "")
            if not src_path and rel_path:
                src_path = str(source_root / rel_path)

            raw_sname = (item.get("sample_name") or item.get("sampleName") or "").strip()
            fallback_stem = Path(rel_path or src_path).stem if (rel_path or src_path) else ""
            pads_dict[pad_num] = {
                "pad_number": pad_num,
                "sample_name": raw_sname or fallback_stem,
                "sample_file": Path(src_path or rel_path).name if (src_path or rel_path) else "",
                "sound_type": item.get("sound_type", item.get("soundType", "SAMPLE")),
                "source_path": src_path,
                "volume": float(item.get("volume", 0.707946)),
                "pan": float(item.get("pan", 0.5)),
                "tune": int(item.get("tune", 0)),
                "mute_group": pad_mute_group(item),
            }
    elif isinstance(pads, dict):
        for k, v in pads.items():
            pad_num = int(k)
            pads_dict[pad_num] = dict(v)
            if not pads_dict[pad_num].get("source_path") and pads_dict[pad_num].get("rel_path"):
                pads_dict[pad_num]["source_path"] = str(
                    source_root / pads_dict[pad_num]["rel_path"]
                )

    tempo = float(tempo)
    if not math.isfinite(tempo) or not 30 <= tempo <= 300:
        raise ValueError("Tempo fuera de rango (30–300 BPM)")
    target_lower = target.lower()
    if target_lower not in {'universal','mpc','maschine','sp404mk2','sp404a','po33','po-33','pocket_operator','ep133','ep-133','ko2','ko-ii','ko_ii'}:
        raise ValueError("Destino de exportación no reconocido")
    if not pads_dict or any(not 1 <= n <= 16 for n in pads_dict):
        raise ValueError("El rack admite pads 1 a 16 y necesita al menos una muestra")
    for number, pad in pads_dict.items():
        source = Path(pad.get('source_path', '')).resolve()
        if not source.is_relative_to(source_root.resolve()) or not source.is_file():
            raise ValueError(f"Pad {number}: muestra ausente o fuera de la biblioteca")
        for key, low, high, default in [('volume',0,1,0.707946),('pan',0,1,0.5),('tune',-36,36,0)]:
            value = float(pad.get(key, default))
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Pad {number}: {key} fuera de rango")
        pad_mute_group(pad)
    # Atomic reservation prevents concurrent exports overwriting one another.
    if output_base_dir.exists():
        raise FileExistsError("Ya existe un kit con ese nombre. Elige otro para conservar el original.")
    output_base_dir.mkdir(parents=True, exist_ok=False)
    targets_result = {}

    try:
        # 1. Akai MPC
        if target_lower in ("universal", "mpc"):
            mpc_dir = output_base_dir / "Akai_MPC"
            mpc_dir.mkdir(parents=True, exist_ok=True)
            proj_path = export_mpc_project(clean_kit_name, pads_dict, mpc_dir, tempo=tempo)
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
                clean_kit_name, pads_dict, po_dir, **(po_options or {})
            )
            targets_result["po33"] = {
                "reel_wav": reel_wav,
                "duration_sec": duration,
                "ram_limit_sec": (po_options or {}).get("max_total_sec",40.0),
                "slices_count": len(slices),
            }

        # 6. Teenage Engineering EP-133 K.O. II
        if target_lower in ("universal", "ep133", "ep-133", "ko2", "ko-ii", "ko_ii"):
            ep_dir = output_base_dir / "Teenage_Engineering_EP133"
            ep_dir.mkdir(parents=True, exist_ok=True)
            ep_folder, ep_pak = export_ep133_ko2_kit(clean_kit_name, pads_dict, ep_dir)
            targets_result["ep133"] = {
                "folder": ep_folder,
                "pak_package": ep_pak,
                "slots_count": len(pads_dict),
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
    except Exception:
        try:
            shutil.rmtree(output_base_dir)
        except OSError as cleanup_error:
            logger.warning("No se pudo retirar el kit incompleto %s: %s", output_base_dir, cleanup_error)
        raise



if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        import argparse
        import base64
        parser = argparse.ArgumentParser(description="BeatOS hardware kit builder")
        commands = parser.add_subparsers(dest="command", required=True)
        create = commands.add_parser("create")
        create.add_argument("--name", required=True)
        create.add_argument("--target", default="universal", choices=["universal", "mpc", "maschine", "sp404mk2", "sp404a", "po33", "ep133"])
        create.add_argument("--b64", required=True)
        create.add_argument("--root", type=Path, required=True)
        args = parser.parse_args()
        pads = json.loads(base64.b64decode(args.b64, validate=True))
        if not args.root.is_dir():
            parser.error("La biblioteca no existe")
        result = create_kit(args.name, pads, target=args.target, source_root=args.root)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)
    print("=================================================================")
    print("Universal Hardware Kit Builder & Multi-Sampler Bridge v3.5 cargado")
    print(f"Directorio de Backups PO-33 detectado: {DEFAULT_PO_DIR}")
    backups = scan_po33_backups([DEFAULT_PO_DIR])
    print(f"Backups PO-33 encontrados: {len(backups)}")
    for b in backups:
        print(f"  • {b['filename']} ({b['duration_sec']}s, {b['channels']}ch, {b['status']})")
    print("=================================================================")
