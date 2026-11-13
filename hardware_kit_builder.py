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
from typing import Any, Dict, List, Optional, Tuple, Union
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# Directorio por defecto de backups de Pocket Operator
DEFAULT_PO_DIR = Path.home() / "Documents" / "PO- POCKET OPERATORS"
PO_IMPORT_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Escalas musicales y utilidades melódicas / cromáticas para MPC Sample
# ---------------------------------------------------------------------------
SCALES: dict[str, list[int]] = {
    "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],            # Menor natural / Eólica
    "natural_minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic_minor": [0, 3, 5, 7, 10],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "blues": [0, 3, 5, 6, 7, 10],
}

NOTE_NAMES: list[str] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_NAME_MAP: dict[str, int] = {
    "C": 0, "B#": 0,
    "C#": 1, "DB": 1,
    "D": 2,
    "D#": 3, "EB": 3,
    "E": 4, "FB": 4,
    "F": 5, "E#": 5,
    "F#": 6, "GB": 6,
    "G": 7,
    "G#": 8, "AB": 8,
    "A": 9,
    "A#": 10, "BB": 10,
    "B": 11, "CB": 11,
}


def parse_note(note_str: str) -> tuple[int, int]:
    """Parsea una nota como 'C2', 'F#1', 'Eb3' en (pitch_class 0-11, octave)."""
    m = re.match(r"^([A-Ga-g][#b]?)(-?\d+)?$", str(note_str).strip())
    if not m:
        raise ValueError(f"Formato de nota inválido: '{note_str}'. Ejemplos válidos: 'C2', 'F#1', 'Eb3'")
    pitch_name = m.group(1).upper()
    octave = int(m.group(2)) if m.group(2) is not None else 2
    if pitch_name not in NOTE_NAME_MAP:
        raise ValueError(f"Nombre de nota desconocido: '{pitch_name}'")
    return NOTE_NAME_MAP[pitch_name], octave


def note_from_root_offset(root_pc: int, root_oct: int, semitone_offset: int) -> str:
    """Calcula el nombre de nota y octava resultantes a partir de la raíz y el offset en semitonos."""
    total_semitones = (root_oct * 12) + root_pc + semitone_offset
    final_oct = total_semitones // 12
    final_pc = total_semitones % 12
    return f"{NOTE_NAMES[final_pc]}{final_oct}"


def build_scale_offsets(
    scale_name: str,
    count: int = 16,
    start_octave: int = 0,
    clamp_range: tuple[int, int] = (-24, 24)
) -> list[int]:
    """
    Genera una lista de 'count' semitones correspondientes a la escala seleccionada.
    start_octave=0 comienza en 0 semitonos.
    start_octave=-1 comienza 1 octava abajo (-12 semitonos).
    Todos los offsets se aseguran dentro del rango de afinación del MPC (-24 a +24 semitonos).
    """
    scale_lower = scale_name.lower().strip()
    if scale_lower not in SCALES:
        valid = ", ".join(sorted(SCALES.keys()))
        raise ValueError(f"Escala desconocida: '{scale_name}'. Escalas disponibles: {valid}")

    intervals = SCALES[scale_lower]
    offsets: list[int] = []
    octave_shift = start_octave * 12

    for idx in range(count):
        octave = idx // len(intervals)
        note_idx = idx % len(intervals)
        semitone = (octave * 12) + intervals[note_idx] + octave_shift
        clamped = max(clamp_range[0], min(clamp_range[1], semitone))
        offsets.append(clamped)

    return offsets



def po33_backup_dirs(root: str | Path) -> list[Path]:
    root_p = Path(root)
    local_dirs = [root_p / 'BeatOS/data/po33_backups', root_p / 'PO_BACKUPS']
    try:
        if root_p.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
            return local_dirs
    except OSError:
        pass
    return [root_p / 'BeatOS/data/po33_backups', DEFAULT_PO_DIR,
            root_p / 'PO_BACKUPS', Path('/Volumes/MPCSMPL/PO_BACKUPS'),
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
    if any(k in f for k in ["tom", "flr", "floor_tom", "floortom", "lowtom", "midtom", "hitom", "racktom"]):
        return "TOM"
    if any(k in f for k in ["cymbal", "ride", "crash", "splash", "china"]):
        return "CYMBAL"
    if any(k in f for k in ["hat", "hh_", "hihat", "openhh", "closedhh", "shaker", "maraca"]):
        return "HIHAT"
    if any(k in f for k in ["bass", "808", "sub", "subbass", "reese"]):
        return "BASS_808"
    if any(k in f for k in ["perc", "conga", "bongo", "rim", "cowbell", "timbale", "wood"]):
        return "PERCUSSION"
    if any(k in f for k in ["vox", "vocal", "chant", "acapella"]):
        return "VOCAL"
    if any(k in f for k in ["synth", "key", "piano", "chord", "rhodes", "pad", "lead", "arp", "pluck"]):
        return "KEYS_SYNTH"
    if any(k in f for k in ["fx", "sweep", "riser", "downlifter", "hit", "impact", "noise", "laser"]):
        return "FX"
    if any(k in f for k in ["loop", "break", "groove", "chop", "slice"]):
        return "MELODIC_LOOP"
    return "PERCUSSION"


def default_mute_group(sound_type: str) -> int:
    """Core punch instruments (Kicks, Snares, Toms) choke in Group 1 to prevent master clipping."""
    return {"KICK": 1, "SNARE": 1, "TOM": 1, "HIHAT": 2, "BASS_808": 3}.get(sound_type, 0)


def default_pad_volume(sound_type: str) -> float:
    """Opción A: Jerarquía Acústica Headroom para Akai MPC
    - KICK / SNARE: -5.0 dB (0.562341) -> Transitorios principales y pegada limpia
    - TOM / BASS_808 / CLAP / CYMBAL / PERCUSSION / MELODIC_LOOP / KEYS_SYNTH: -6.0 dB (0.501187) -> Control de subgraves y cuerpo
    - HIHAT / SHAKER: -7.5 dB (0.421697) -> Techo agudo suave y natural, sin estridencia
    - FX: -8.0 dB (0.398107) -> Texturas y transiciones de fondo
    """
    levels = {
        "KICK": 0.562341,
        "SNARE": 0.562341,
        "TOM": 0.501187,
        "BASS_808": 0.501187,
        "CLAP": 0.501187,
        "CYMBAL": 0.501187,
        "PERCUSSION": 0.501187,
        "MELODIC_LOOP": 0.501187,
        "KEYS_SYNTH": 0.501187,
        "HIHAT": 0.421697,
        "FX": 0.398107,
    }
    return levels.get(sound_type, 0.501187)


def _sniff_wav_header(wav_path: Path) -> Tuple[int, int]:
    """Lee (channels, sample_rate) desde la cabecera RIFF fmt aunque no sea PCM 16-bit."""
    try:
        with open(wav_path, "rb") as f:
            head = f.read(64)
        idx = head.find(b"fmt ")
        if idx != -1 and idx + 16 <= len(head):
            n_ch, sr = struct.unpack_from("<HI", head, idx + 10)
            return max(1, int(n_ch)), max(8000, int(sr))
    except Exception:
        pass
    return 1, 44100


def analyze_sample_acoustics(wav_path: str | Path) -> Dict[str, Any]:
    """Analiza propiedades físico-acústicas reales de una muestra WAV (Pico, RMS activo, Factor de Cresta, DC offset, subgraves y correlación estéreo)."""
    p = Path(wav_path)
    empty = {
        "valid": False,
        "peak_dbfs": -120.0,
        "rms_active_dbfs": -120.0,
        "crest_factor_db": 0.0,
        "dc_offset": 0.0,
        "low_energy_ratio": 0.0,
        "stereo_correlation": 1.0,
        "duration_sec": 0.0,
        "channels": 1,
        "sample_rate": 44100,
    }
    if not p.is_file():
        return empty

    samples: list[int] | tuple[int, ...] = []
    n_ch = 1
    fr = 44100
    duration_sec = 0.0
    used_wave = False

    try:
        with wave.open(str(p), "rb") as wf:
            n_ch = max(1, wf.getnchannels())
            sw = wf.getsampwidth()
            fr = wf.getframerate() or 44100
            n_frames = wf.getnframes()
            duration_sec = round(n_frames / float(fr), 3) if fr else 0.0
            if sw == 2 and n_frames > 0:
                read_n = min(n_frames, int(fr * 2.5), 110250)
                raw = wf.readframes(read_n)
                total_short = len(raw) // 2
                if total_short > 0:
                    samples = struct.unpack(f"<{total_short}h", raw[: total_short * 2])
                    used_wave = True
    except (wave.Error, EOFError):
        pass
    except Exception:
        return empty

    if not used_wave:
        try:
            sniff_ch, _ = _sniff_wav_header(p)
            conv = _convert_audio(p, mono=False, sample_rate=44100)
            if conv:
                n_ch = sniff_ch if (len(conv) % sniff_ch == 0) else 1
                fr = 44100
                max_elems = 110250 * n_ch
                samples = conv[:max_elems]
                if duration_sec == 0.0:
                    duration_sec = round((len(conv) / float(n_ch)) / 44100.0, 3)
        except Exception:
            return empty

    if not samples or len(samples) < max(1, n_ch):
        return empty

    if n_ch >= 2:
        left = [float(x) for x in samples[0::n_ch]]
        right = [float(x) for x in samples[1::n_ch]]
        n_mono = min(len(left), len(right))
        left = left[:n_mono]
        right = right[:n_mono]
    else:
        left = [float(x) for x in samples]
        right = []
        n_mono = len(left)

    if n_mono == 0:
        return empty

    peak_abs = max(abs(x) for x in samples)
    if peak_abs <= 0:
        res = dict(empty)
        res.update({"valid": True, "duration_sec": duration_sec, "channels": n_ch, "sample_rate": fr})
        return res

    peak_dbfs = round(20.0 * math.log10(peak_abs / 32767.0), 2)
    dc_offset = round((sum(samples) / len(samples)) / 32767.0, 5)

    # RMS activo en bloques de 10 ms (~441 muestras) para ignorar colas de silencio en one-shots
    block_size = max(16, int(round(fr * 0.01)))
    active_thresh = max(32.0, float(peak_abs) * 0.01)
    active_sq_sum = 0.0
    active_frames = 0
    total_sq_sum = 0.0

    for start in range(0, n_mono, block_size):
        end = min(n_mono, start + block_size)
        blk_len = end - start
        if right:
            blk_sq = 0.5 * (
                sum(left[k] * left[k] for k in range(start, end))
                + sum(right[k] * right[k] for k in range(start, end))
            )
        else:
            blk_sq = sum(left[k] * left[k] for k in range(start, end))
        total_sq_sum += blk_sq
        blk_rms = math.sqrt(blk_sq / blk_len)
        if blk_rms > active_thresh:
            active_sq_sum += blk_sq
            active_frames += blk_len

    if active_frames == 0:
        rms_active = math.sqrt(total_sq_sum / n_mono)
    else:
        rms_active = math.sqrt(active_sq_sum / active_frames)

    rms_active_dbfs = round(20.0 * math.log10(max(1e-9, rms_active) / 32767.0), 2)
    crest_factor_db = round(max(0.0, peak_dbfs - rms_active_dbfs), 2)

    # Filtro paso bajo IIR de 1er orden (~180 Hz) sin DC para medir energía subgrave
    mean_l = sum(left) / n_mono
    alpha = min(0.95, (2.0 * math.pi * 180.0) / (float(fr) + 2.0 * math.pi * 180.0))
    lp = 0.0
    lp_sq = 0.0
    ac_sq = 0.0
    for x in left:
        xc = x - mean_l
        ac_sq += xc * xc
        lp = lp + alpha * (xc - lp)
        lp_sq += lp * lp
    low_energy_ratio = round(lp_sq / ac_sq, 3) if ac_sq > 1e-6 else 0.0

    stereo_correlation = 1.0
    if right:
        mean_r = sum(right) / n_mono
        num = 0.0
        den_l = 0.0
        den_r = 0.0
        for i in range(n_mono):
            dl = left[i] - mean_l
            dr = right[i] - mean_r
            num += dl * dr
            den_l += dl * dl
            den_r += dr * dr
        denom = math.sqrt(den_l * den_r)
        if denom > 1e-6:
            stereo_correlation = round(max(-1.0, min(1.0, num / denom)), 3)

    return {
        "valid": True,
        "peak_dbfs": peak_dbfs,
        "rms_active_dbfs": rms_active_dbfs,
        "crest_factor_db": crest_factor_db,
        "dc_offset": dc_offset,
        "low_energy_ratio": low_energy_ratio,
        "stereo_correlation": stereo_correlation,
        "duration_sec": duration_sec,
        "channels": n_ch,
        "sample_rate": fr,
    }


def compute_smart_pad_volume(sound_type: str, wav_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Calcula la ganancia inteligente BeatOS v4.0 combinando Jerarquía Opción A + compensación de pico y densidad RMS."""
    stype = (sound_type or "PERCUSSION").strip().upper()
    target_map = {
        "KICK": -5.0,
        "SNARE": -5.0,
        "HIHAT": -7.5,
        "FX": -8.0,
    }
    target_db = target_map.get(stype, -6.0)
    fallback_vol = default_pad_volume(stype)

    ac: Dict[str, Any] = {}
    if wav_path:
        ac = analyze_sample_acoustics(wav_path)

    if not ac.get("valid") or ac.get("peak_dbfs", -120.0) <= -60.0:
        return {
            "volume": fallback_vol,
            "gain_db": target_db,
            "target_db": target_db,
            "peak_dbfs": ac.get("peak_dbfs", -120.0),
            "rms_dbfs": ac.get("rms_active_dbfs", -120.0),
            "crest_factor_db": ac.get("crest_factor_db", 0.0),
            "low_energy_ratio": ac.get("low_energy_ratio", 0.0),
            "stereo_correlation": ac.get("stereo_correlation", 1.0),
            "smart_applied": False,
        }

    peak_dbfs = float(ac["peak_dbfs"])
    crest_db = float(ac["crest_factor_db"])
    low_ratio = float(ac["low_energy_ratio"])
    duration_sec = float(ac["duration_sec"])

    effective_peak = max(-4.5, min(0.0, peak_dbfs))
    cf_penalty = min(2.0, (7.5 - crest_db) * 0.35) if crest_db < 7.5 else 0.0
    sub_penalty = 0.5 if (stype not in ("KICK",) and low_ratio > 0.70 and duration_sec > 0.35) else 0.0

    gain_db = round(max(-12.0, min(-1.0, target_db - effective_peak - cf_penalty - sub_penalty)), 3)
    linear_vol = round(10.0 ** (gain_db / 20.0), 6)

    return {
        "volume": linear_vol,
        "gain_db": gain_db,
        "target_db": target_db,
        "peak_dbfs": peak_dbfs,
        "rms_dbfs": float(ac["rms_active_dbfs"]),
        "crest_factor_db": crest_db,
        "low_energy_ratio": low_ratio,
        "stereo_correlation": float(ac["stereo_correlation"]),
        "smart_applied": True,
    }


MUTE_PROFILES: Dict[str, Dict[str, Any]] = {
    "punch_clean": {
        "id": "punch_clean",
        "name_es": "🥊 Punch & Clean Master (Kick/Snare/Tom=1 · Hat Cl/Op=2 · 808=3 · Clap=Libre)",
        "name_en": "🥊 Punch & Clean Master (Kick/Snare/Tom=1 · Hat Cl/Op=2 · 808=3 · Clap=Free)",
        "description_es": "Kicks, Snares y Toms comparten corte mutuo (Grupo 1) eliminando colas residuales en graves y medios-graves para evitar saturación y clips en el máster. Charles en Grupo 2, 808 en Grupo 3 y Claps/Platos libres.",
    },
    "real_drums": {
        "id": "real_drums",
        "name_es": "🥁 Batería Real / Acústica (Kick/Tom=1 · Hat Cl/Op=2 · Snare=3 · Clap=Libre)",
        "name_en": "🥁 Real Drum Kit / Acoustic (Kick/Tom=1 · Hat Cl/Op=2 · Snare=3 · Clap=Free)",
        "description_es": "Los Open Hats se cortan al golpear un Closed/Pedal Hat (Grupo 2), Kicks y Toms comparten corte de subgraves (Grupo 1), las cajas principales se cortan entre sí (Grupo 3) para evitar clip, y los Claps/Cymbals quedan libres (0) para poder apilar capas.",
    },
    "club_clean": {
        "id": "club_clean",
        "name_es": "🔊 Club / Sub-Clean 808 (+ 808/Sub=4 · Toms=5)",
        "name_en": "🔊 Club / Sub-Clean 808 (+ 808/Sub=4 · Toms=5)",
        "description_es": "Ideal para Drill, Trap, Grime, Dubstep y Baile Funk: añade corte monofónico en colas de 808/Subbass (Grupo 4) y separa Toms en su propio grupo (Grupo 5).",
    },
    "jazz_funk": {
        "id": "jazz_funk",
        "name_es": "🎷 Jazz / Funk / Breakbeat Acústico (Solo Hi-Hats Open/Closed=2)",
        "name_en": "🎷 Acoustic Jazz / Funk / Breakbeat (Hi-Hats Open/Closed=2 Only)",
        "description_es": "Solo el charles (Closed/Open/Pedal Hat en Grupo 2) actúa con pedal mecánico real; bombo, caja (ghost notes) y platos resuenan libremente sin cortarse.",
    },
    "free_poly": {
        "id": "free_poly",
        "name_es": "🔓 Libre / Polifónico Total (Todos en OFF / 0)",
        "name_en": "🔓 Free / Full Polyphonic (All OFF / 0)",
        "description_es": "Desactiva todos los grupos de corte (MuteGroup = 0) para permitir colas superpuestas sin restricción.",
    },
}


def mute_group_for_profile(sound_type: str, sample_name: str = "", profile: str = "punch_clean") -> int:
    """Calcula el grupo de muteo coherente según la acústica y el perfil musical elegido."""
    prof = (profile or "punch_clean").strip().lower()
    st = (sound_type or "").strip().upper()
    low_name = (sample_name or "").lower()
    is_tom = bool(re.search(r"(?:^|[\s_\-.])(?:tom|flr|floor\s*tom)(?:[\s_\-.0-9]|$)", low_name)) or st == "TOM"

    if prof == "free_poly":
        return 0
    if prof == "jazz_funk":
        return 2 if st == "HIHAT" else 0
    if prof == "club_clean":
        if is_tom or st == "TOM":
            return 5
        if st in ("KICK", "SNARE"):
            return 1
        if st == "HIHAT":
            return 2
        if st == "BASS_808":
            return 4
        return 0
    if prof == "real_drums":
        if is_tom or st == "KICK":
            return 1
        if st == "HIHAT":
            return 2
        if st == "SNARE":
            return 3
        if st == "BASS_808":
            return 4
        return 0
    # Default: punch_clean (Kick, Snare, Tom = 1, Hat = 2, 808 = 3)
    if is_tom or st in ("KICK", "SNARE", "TOM"):
        return 1
    if st == "HIHAT":
        return 2
    if st == "BASS_808":
        return 3
    # CLAP, CYMBAL, PERCUSSION, KEYS_SYNTH, VOCAL, FX stay 0 so they layer naturally
    return 0


def compute_kit_mute_groups(pads_dict: Dict[int, dict], profile: str = "punch_clean") -> Dict[int, int]:
    """Devuelve el mapa {pad_num: mute_group} aplicando coherencia del kit (no asigna grupo si solo hay 1 pad en ese grupo, salvo 808/Hat)."""
    raw_groups: Dict[int, int] = {}
    counts: Dict[int, int] = {}
    for p_num, p_info in pads_dict.items():
        sname = p_info.get("sample_name") or p_info.get("sample_file") or ""
        stype = p_info.get("sound_type") or p_info.get("soundType") or detect_sound_type(sname)
        if stype == "SAMPLE":
            stype = detect_sound_type(sname)
        mg = mute_group_for_profile(stype, sname, profile=profile)
        raw_groups[int(p_num)] = mg
        if mg > 0:
            counts[mg] = counts.get(mg, 0) + 1
    return raw_groups


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


UNDERGROUND_GENRE_RULES: List[Dict[str, Any]] = [
    {
        "id": "baile_funk",
        "style": "Baile Funk / Favela",
        "bpm": 130.0,
        "mute_profile": "club_clean",
        "keywords": ["baile funk", "funk carioca", "favela", "mandelao", "mandelão", "tamborzao", "tamborzão", "montagem", "brega funk", "macumba", "brazilian funk", "rio funk", "berimbau funk"],
    },
    {
        "id": "drill",
        "style": "UK / NY Drill",
        "bpm": 142.0,
        "mute_profile": "club_clean",
        "keywords": ["uk drill", "ny drill", "bk drill", "chicago drill", "ocean drill", "drill", "sliding 808", "glide 808"],
    },
    {
        "id": "grime",
        "style": "Grime / Eski 140",
        "bpm": 140.0,
        "mute_profile": "club_clean",
        "keywords": ["grime", "eski", "eskibeat", "bow e3", "wiley", "rinse"],
    },
    {
        "id": "uk_garage",
        "style": "UK Garage / 2-Step",
        "bpm": 132.0,
        "mute_profile": "real_drums",
        "keywords": ["uk garage", "ukg", "2-step", "2step", "two-step", "two step", "speed garage", "4x4 garage", "shuffled garage"],
    },
    {
        "id": "dubstep",
        "style": "Dubstep / Deep 140",
        "bpm": 140.0,
        "mute_profile": "club_clean",
        "keywords": ["dubstep", "deep 140", "140 bass", "riddim", "halfstep", "wobble"],
    },
    {
        "id": "jungle_footwork",
        "style": "Jungle / Footwork / Juke",
        "bpm": 165.0,
        "mute_profile": "real_drums",
        "keywords": ["footwork", "juke", "jungle", "amen break", "ragga jungle", "breakcore"],
    },
    {
        "id": "dnb",
        "style": "Drum & Bass",
        "bpm": 174.0,
        "mute_profile": "real_drums",
        "keywords": ["drum & bass", "drum___bass", "drum and bass", "dnb", "neurofunk", "liquid dnb", "jump up"],
    },
    {
        "id": "amapiano",
        "style": "Amapiano",
        "bpm": 112.0,
        "mute_profile": "club_clean",
        "keywords": ["amapiano", "log drum", "logdrum", "bacardi"],
    },
    {
        "id": "afrobeats",
        "style": "Afrobeats",
        "bpm": 102.0,
        "mute_profile": "real_drums",
        "keywords": ["juls", "afrobeats", "afrobeat", "afro swing", "afroswing", "afro"],
    },
    {
        "id": "reggaeton_dancehall",
        "style": "Reggaetón / Dancehall",
        "bpm": 100.0,
        "mute_profile": "club_clean",
        "keywords": ["dembow", "reggaeton", "reggaetón", "moombahton", "dancehall", "perreo", "island"],
    },
    {
        "id": "trap",
        "style": "Trap / 808",
        "bpm": 140.0,
        "mute_profile": "club_clean",
        "keywords": ["ocean trap", "trap-kit", "decap", "sub trap", "dirty south", "phonk", "trap", "808"],
    },
    {
        "id": "lofi",
        "style": "Lo-Fi Hip Hop / Chillhop",
        "bpm": 84.0,
        "mute_profile": "jazz_funk",
        "keywords": ["lofi faded", "very sick beats", "lofi", "lo-fi", "chillhop", "dusty", "vinyl"],
    },
    {
        "id": "boombap",
        "style": "Boom Bap / East Coast",
        "bpm": 90.0,
        "mute_profile": "real_drums",
        "keywords": ["cookin soul", "marco polo", "just blaze", "ocean boom bap", "boombap", "boom bap", "bodega", "deli drum", "east coast", "borough chops", "backyard jams", "dilla", "pete rock", "premo"],
    },
    {
        "id": "rnb_soul",
        "style": "R&B / Neo-Soul",
        "bpm": 92.0,
        "mute_profile": "jazz_funk",
        "keywords": ["trap soul", "trapsoul", "rare vibrations", "r&b", "rnb", "r_b_", "neo soul", "soul", "vibes drum"],
    },
    {
        "id": "funk_jazz",
        "style": "Funk / Jazz / Breaks",
        "bpm": 110.0,
        "mute_profile": "jazz_funk",
        "keywords": ["jazz", "funk", "disco", "live break", "chopped breaks", "breakbeat", "break"],
    },
    {
        "id": "house_techno",
        "style": "House / UK Bass / Club",
        "bpm": 124.0,
        "mute_profile": "real_drums",
        "keywords": ["deephouse", "deep house", "futurehouse", "future house", "tech house", "house", "techno", "electro", "edm", "club"],
    },
]


def detect_musical_style(
    path_or_text: str | Path,
    bpm: Optional[float | List[str]] = None,
    sample_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Detecta el estilo musical (incluyendo géneros underground) y recomienda BPM y perfil de Choke/Mute."""
    extra = ""
    actual_bpm: Optional[float] = None
    if isinstance(bpm, (list, tuple)):
        extra = " " + " ".join(str(x) for x in bpm)
    elif bpm is not None:
        actual_bpm = float(bpm)
    if sample_names:
        extra += " " + " ".join(str(x) for x in sample_names)
    low = (str(path_or_text) + extra).lower()
    # Casos prioritarios compuestos
    if "trap soul" in low or "trapsoul" in low:
        return {"id": "rnb_soul", "style": "Trap Soul / R&B", "label": "Trap Soul / R&B", "bpm": 92.0, "mute_profile": "jazz_funk"}
    if "marco polo" in low:
        return {"id": "boombap", "style": "Boom Bap / East Coast", "label": "Boom Bap / East Coast", "bpm": 90.0, "mute_profile": "real_drums"}
    for rule in UNDERGROUND_GENRE_RULES:
        if any(k in low for k in rule["keywords"]):
            return {
                "id": rule["id"],
                "style": rule["style"],
                "label": rule["style"],
                "bpm": float(actual_bpm) if actual_bpm else float(rule["bpm"]),
                "mute_profile": rule["mute_profile"],
            }
    if actual_bpm:
        b = float(actual_bpm)
        if 127 <= b <= 135:
            return {"id": "uk_garage", "style": "UK Garage / 2-Step / Baile Funk", "label": "UK Garage / 2-Step / Baile Funk", "bpm": b, "mute_profile": "real_drums"}
        if 138 <= b <= 146:
            return {"id": "drill", "style": "Drill / Grime / Dubstep / Trap 140", "label": "Drill / Grime / Dubstep / Trap 140", "bpm": b, "mute_profile": "club_clean"}
        if 158 <= b <= 168:
            return {"id": "jungle_footwork", "style": "Jungle / Footwork", "label": "Jungle / Footwork", "bpm": b, "mute_profile": "real_drums"}
        if b >= 169:
            return {"id": "dnb", "style": "Drum & Bass", "label": "Drum & Bass", "bpm": b, "mute_profile": "real_drums"}
        if 80 <= b <= 96:
            return {"id": "boombap", "style": "Boom Bap / Hip-Hop", "label": "Boom Bap / Hip-Hop", "bpm": b, "mute_profile": "real_drums"}
    return {"id": "standard", "style": "Hip-Hop / Electrónica", "label": "Hip-Hop / Electrónica", "bpm": float(actual_bpm or 120.0), "mute_profile": "real_drums"}


def infer_kit_bpm(path_or_name: str | Path, fallback: float = 120.0) -> float:
    """Infiere el BPM real de un kit o proyecto por nombre explícito, muestras internas o estilo/artista."""
    p = Path(str(path_or_name))
    stem = p.stem
    full_str = str(p)
    low = full_str.lower()

    m = re.search(r"(?:^|[\s_-])(6\d|[7-9]\d|1[0-8]\d)\s*bpm\b", stem, re.I)
    if m:
        return float(m.group(1))
    m2 = re.search(r"[\s_-](6\d|[7-9]\d|1[0-8]\d)$", stem)
    if m2 and int(m2.group(1)) not in (808, 909, 303, 140):
        return float(m2.group(1))

    if p.exists():
        search_dir = (p.parent / f"{stem}_[ProjectData]") if (p.parent / f"{stem}_[ProjectData]").is_dir() else (p if p.is_dir() else p.parent)
        if search_dir.is_dir():
            for w in sorted(search_dir.glob("*.[wW][aA][vV]")):
                if w.name.startswith("._"):
                    continue
                mw = re.search(r"(?:^|[\s_-])(6\d|[7-9]\d|1[0-8]\d)\s*bpm\b", w.stem, re.I)
                if not mw:
                    mw = re.search(r"bpm_[a-z0-9_]*?_(6\d|[7-9]\d|1[0-8]\d)_", w.stem, re.I)
                if mw:
                    val = float(mw.group(1))
                    if 60.0 <= val <= 185.0:
                        return val

    if any(k in low for k in ["baile funk", "funk carioca", "favela", "mandelao", "mandelão", "tamborzao", "tamborzão", "montagem", "brega funk"]):
        return 130.0
    if any(k in low for k in ["uk garage", "ukg", "2-step", "2step", "two-step", "two step", "speed garage"]):
        return 132.0
    if any(k in low for k in ["footwork", "juke", "amen break", "breakcore"]):
        return 165.0
    if any(k in low for k in ["drum & bass", "drum___bass", "dnb", "jungle"]):
        return 174.0
    if any(k in low for k in ["ocean drill", "uk drill", "ny drill", "drill"]):
        return 142.0
    if any(k in low for k in ["dubstep", "grime", "eski", "deep 140", "riddim"]):
        return 140.0
    if any(k in low for k in ["amapiano", "log drum", "logdrum"]):
        return 112.0
    if any(k in low for k in ["ocean trap", "trap-kit", "decap", "808", "sub trap", "trap"]):
        return 92.0 if ("trap soul" in low or "trapsoul" in low) else 140.0
    if any(k in low for k in ["lofi faded", "very sick beats", "lofi"]):
        return 90.0 if "marco polo" in low else 84.0
    if any(k in low for k in ["cookin soul", "marco polo", "just blaze", "ocean boom bap", "boombap", "boom bap", "bodega", "deli drum", "east coast", "borough chops", "backyard jams"]):
        return 90.0
    if any(k in low for k in ["juls", "afrobeats", "afro"]):
        return 102.0
    if any(k in low for k in ["moombahton", "reggaeton", "reggaetón", "dembow", "dancehall", "latin", "island"]):
        return 100.0
    if any(k in low for k in ["rare vibrations", "r&b", "rnb", "r_b_", "soul", "vibes drum"]):
        return 92.0
    if any(k in low for k in ["funk", "disco", "live break", "chopped breaks", "break"]):
        return 110.0
    if any(k in low for k in ["deephouse", "deep house", "futurehouse", "future house", "house", "edm", "club", "tech"]):
        return 124.0
    if "real horns" in low:
        return 96.0
    if "f9 instruments" in low:
        return 120.0
    if "artist signature kits" in low:
        return 92.0
    if "serato studio" in low:
        return 96.0
    return float(fallback)


def extract_expansion_hierarchy(target_path: Path, exp_dir: Path, kit_name: str = "") -> dict:
    """Extrae la carpeta de artista/colección y subcategoría real de un kit o proyecto dentro de una expansión."""
    name = (kit_name or target_path.stem).strip()
    low_name = name.lower()
    try:
        rel_parts = [
            pt for pt in target_path.parent.relative_to(exp_dir).parts
            if not pt.endswith("_[ProjectData]") and not pt.endswith("_ProjectData")
        ]
    except ValueError:
        rel_parts = []

    if rel_parts and _normalize_name(rel_parts[-1]) == _normalize_name(target_path.stem):
        rel_parts.pop()

    artist = ""
    folder_group = " / ".join(rel_parts) if rel_parts else ""

    if rel_parts and rel_parts[0] == "Artist Signature Kits":
        if "'s " in name:
            artist = name.split("'s ")[0].strip()
        elif "’s " in name:
            artist = name.split("’s ")[0].strip()
        elif " - " in name:
            artist = name.split(" - ")[0].strip()
        elif any(k in low_name for k in ["msxii", "bodega", "deli", "subway"]):
            artist = "MSXII Sound Design"
        elif any(k in low_name for k in ["controllerise"]):
            artist = "Controllerise Lo-Fi"
        elif any(k in low_name for k in ["tracklib", "south bronx", "back pack", "live break", "house techno"]):
            artist = "Tracklib"
        elif any(k in low_name for k in ["decap", "knocking"]):
            artist = "DECAP"
        elif any(k in low_name for k in ["just blaze"]):
            artist = "Just Blaze"
        elif any(k in low_name for k in ["very sick"]):
            artist = "Very Sick Beats"
        elif any(k in low_name for k in ["juls"]):
            artist = "Juls"
        elif any(k in low_name for k in ["bullton", "bemular", "neronga", "alien baltan"]):
            artist = "Cookin Soul"
        elif any(k in low_name for k in ["honda fist", "dragon knuckle"]):
            artist = "Martial Beats"
        elif any(k in low_name for k in ["90s grunge", "grunge"]):
            artist = "90s Grunge Lab"
        elif any(k in low_name for k in ["beats & chill", "lofi", "faded"]):
            artist = "Chill Lo-Fi Collective"
        elif any(k in low_name for k in ["uk drill", "drill"]):
            artist = "Drill Signature"
        elif any(k in low_name for k in ["trap", "modern trap", "classic trap"]):
            artist = "Trap Signature"
        else:
            artist = "Signature Producer"
        folder_group = f"Artist Signature Kits · {artist}"
    elif rel_parts:
        top = rel_parts[0]
        if " - " in top:
            artist = top.split(" - ")[0].strip()
        elif top not in ("Core", "Instruments", "Drums", "Bonus_Loops_&_Shots"):
            artist = top
        elif top == "Core":
            artist = "Akai Core Library"
        elif top.startswith("Bonus"):
            artist = "Serato Bonus"

    if not folder_group:
        m_prefix = re.match(r"^(Trap|BoomBap|DanceHall|Urban|Pop|DeepHouse|FutureHouse|EDM|Funk|Soul|RnB|R&B|LoFi|Drill|House|Inst)[-_](?:Kit|Lead|Bass|Piano|Synth|Pad|Pluck|Guitar|Strings|Brass)?", name, re.I)
        if m_prefix:
            raw_p = m_prefix.group(1)
            folder_group = "Instruments" if raw_p.lower() == "inst" else f"{raw_p} Kits"
        else:
            folder_group = exp_dir.name

    sub_cat = f"{folder_group} · {artist}" if (artist and artist.lower() not in folder_group.lower()) else folder_group
    is_instrument = any(pt.lower() == "instruments" for pt in rel_parts) or name.lower().startswith("inst-")
    top_pack = rel_parts[0] if rel_parts else exp_dir.name
    return {
        "sub_category": sub_cat or exp_dir.name,
        "folder_group": folder_group or exp_dir.name,
        "pack_name": top_pack,
        "artist": artist,
        "is_instrument": is_instrument,
    }


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
        "tempo": infer_kit_bpm(xpm_p),
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


_EXPANSION_KITS_CACHE: Dict[str, List[Dict[str, Any]]] = {}

def clear_expansion_kits_cache(expansion_name: Optional[str] = None) -> None:
    """Limpia la caché en memoria de programas de expansiones."""
    global _EXPANSION_KITS_CACHE
    if expansion_name:
        for k in list(_EXPANSION_KITS_CACHE.keys()):
            if k.startswith(f"{expansion_name}::") or k == expansion_name:
                _EXPANSION_KITS_CACHE.pop(k, None)
    else:
        _EXPANSION_KITS_CACHE.clear()

def list_expansion_kits(
    expansion_name: str,
    expansions_root: Optional[str | Path] = None,
    source_root: Optional[str | Path] = None,
) -> List[Dict[str, Any]]:
    """
    Escanea y devuelve la lista completa de programas (.xpm) pertenecientes a una expansión oficial,
    con metadatos como tipo de kit, cantidad de pads y primer sample de prueba.
    Usa caché en memoria para respuestas ultra-rápidas en el navegador.
    """
    card_root = Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else Path.cwd()
    )
    exp_base = Path(expansions_root) if expansions_root else card_root / "Expansions"

    cache_key = f"{expansion_name}::{str(card_root)}::{str(exp_base)}"
    if cache_key in _EXPANSION_KITS_CACHE:
        return _EXPANSION_KITS_CACHE[cache_key]

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
        # Ignorar archivos ocultos, de preview o duplicados dentro de _[ProjectData]
        if any(
            part.startswith(".")
            or "[Previews]" in part
            or part.endswith("_[ProjectData]")
            or part.endswith("_ProjectData")
            for part in x.parts
        ):
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

            hier = extract_expansion_hierarchy(x, exp_dir, p_name)
            xpj_cand = x.with_suffix(".xpj")
            kit_bpm = infer_kit_bpm(xpj_cand if xpj_cand.is_file() else x)
            kits.append({
                "name": p_name,
                "filename": x.name,
                "rel_path": rel_to_card,
                "program_type": p_type,
                "pad_count": len(samples),
                "first_sample": samples[0] if samples else "",
                "first_sample_rel": first_sample_rel,
                "sub_category": hier["sub_category"],
                "folder_group": hier["folder_group"],
                "pack_name": hier.get("pack_name", ""),
                "artist": hier["artist"],
                "is_instrument": hier["is_instrument"],
                "tempo": kit_bpm,
            })
        except Exception as e:
            logger.debug(f"Error parseando {x.name}: {e}")
            continue

    # Ordenar alfabéticamente por nombre de kit
    kits.sort(key=lambda k: k["name"].lower())
    _EXPANSION_KITS_CACHE[cache_key] = kits
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
                stem = p_info.get("pad_sample_name") or Path(src).stem
                name = f"PAD{pad_num:03d}_{stem}.wav"
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
            stype = p_info.get("sound_type") or detect_sound_type(s_name or s_file)
            raw_vol = p_info.get("volume")
            vol = float(raw_vol) if raw_vol is not None and raw_vol != 0.707946 else default_pad_volume(stype)
            pan = float(p_info.get("pan", 0.500000))
            tune = int(p_info.get("tune", 0))
            mute = pad_mute_group(p_info)

            _set_xml_text(inst, "Volume", f"{vol:.6f}")
            _set_xml_text(inst, "Pan", f"{pan:.6f}")
            _set_xml_text(inst, "TuneCoarse", str(tune))
            _set_xml_text(inst, "TuneFine", "0")
            _set_xml_text(inst, "MuteGroup", str(mute))
            if "monophonic" in p_info:
                _set_xml_text(inst, "Mono", "True" if p_info["monophonic"] else "False")
                _set_xml_text(inst, "Polyphony", "1" if p_info["monophonic"] else "8")
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
            stem = p_info.get("pad_sample_name") or Path(src).stem
            s_name = f"PAD{pad_num:03d}_{stem}.wav"
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

        mixer_obj = data.get("mixer")
        if isinstance(mixer_obj, dict):
            cur_mvol = mixer_obj.get("volume")
            if cur_mvol is None or cur_mvol > 0.707946:
                mixer_obj["volume"] = 0.7079457640647888
            outs = mixer_obj.get("outputs")
            if isinstance(outs, list) and outs and isinstance(outs[0], dict):
                out_mix = outs[0].get("mixable")
                if isinstance(out_mix, dict) and (out_mix.get("volume") is None or out_mix.get("volume") > 0.794328):
                    out_mix["volume"] = 0.7079457640647888

        tracks = data.get("tracks", [])[:1]
        data["tracks"] = tracks
        if tracks:
            for t in tracks[1:]:
                if isinstance(t, dict) and "samples" in t:
                    t["samples"] = []
            tracks[0]["name"] = kit_name
            tracks[0]["volume"] = 0.7079457640647888
            tracks[0]["samples"] = copy.deepcopy(data["samples"]) if "copy" in globals() else list(data["samples"])
            prog = tracks[0].get("program", {})
            prog["name"] = kit_name
            if isinstance(prog.get("mixable"), dict):
                prog["mixable"]["volume"] = 0.7079457640647888
            drum = prog.get("drum", {})
            insts = drum.get("instruments", [])
            for idx, inst in enumerate(insts):
                pad_num = idx + 1
                p_info = normalized_pads.get(pad_num, {})
                s_file = p_info.get("sample_file", "")
                s_stem = p_info.get("sample_name", "")
                n_frames = int(p_info.get("n_frames", 0))
                if "volume" in p_info and p_info["volume"] is not None:
                    vol = float(p_info["volume"])
                else:
                    inferred_type = p_info.get("sound_type") or detect_sound_type(s_stem or s_file)
                    vol = default_pad_volume(inferred_type)
                pan = float(p_info.get("pan", 0.500000))
                tune = int(p_info.get("tune", 0))
                mute = pad_mute_group(p_info)

                inst["coarseTune"] = tune
                inst["whichMuteGroup"] = mute
                if "monophonic" in p_info:
                    inst["monophonic"] = bool(p_info["monophonic"])
                    inst["polyphony"] = 1 if p_info["monophonic"] else 8
                if isinstance(inst.get("muteTargets"), dict):
                    inst["muteTargets"] = {k: 0 for k in inst["muteTargets"]}
                if isinstance(inst.get("mixable"), dict):
                    inst["mixable"]["volume"] = vol
                    inst["mixable"]["pan"] = pan
                    inst["mixable"]["muteGroup"] = mute
                    if isinstance(inst["mixable"].get("audioRoute"), dict):
                        inst["mixable"]["audioRoute"]["destination"] = 0
                        inst["mixable"]["audioRoute"]["audioRouteSubIndex"] = 0

                layersv = inst.get("layersv", [])
                for lay in layersv:
                    lay["active"] = False
                    lay["sampleName"] = ""
                    lay["sampleFile"] = ""
                    if isinstance(lay.get("sliceInfo"), dict):
                        lay["sliceInfo"]["Start"] = 0
                        lay["sliceInfo"]["End"] = 0
                        lay["sliceInfo"]["LoopStart"] = 0

                if (s_file or s_stem) and layersv:
                    file_name = s_file or (f"{s_stem}.wav" if not s_stem.endswith(".wav") else s_stem)
                    stem_name = s_stem or Path(file_name).stem
                    lay0 = layersv[0]
                    lay0["active"] = True
                    lay0["sampleName"] = stem_name
                    lay0["sampleFile"] = file_name
                    lay0["sliceIndex"] = 129
                    lay0["coarseTune"] = tune
                    lay0["pitch"] = float(tune)
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
    Mapea hasta 10 Bancos (A a J, 16 pads por banco = 160 pads).
    """
    kit_dir = Path(output_dir) / kit_name
    kit_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"kit_name": kit_name, "hardware": "Roland SP-404MK2", "pads": []}
    for pad_num in range(1, 161):
        p_info = pads_data.get(pad_num) or pads_data.get(str(pad_num)) or {}
        src_path = p_info.get("source_path", "")
        if not src_path or not Path(src_path).exists():
            continue
        bank_idx = (pad_num - 1) // 16
        bank_letter = chr(65 + bank_idx)
        slot_in_bank = ((pad_num - 1) % 16) + 1
        s_name = p_info.get("sample_name", f"Pad_{pad_num:02d}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", s_name)
        if bank_idx == 0:
            dest_filename = f"PAD_{pad_num:02d}_{clean_name}.wav"
        else:
            dest_filename = f"BANK_{bank_letter}_PAD_{slot_in_bank:02d}_{clean_name}.wav"
        dest_file = kit_dir / dest_filename

        _convert_audio(src_path, dest_file, mono=False, sample_rate=48000)
        manifest["pads"].append({
            "pad": pad_num,
            "bank": bank_letter,
            "bank_pad": f"{bank_letter}{slot_in_bank:02d}",
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
    Genera carpeta para Roland SP-404A / SX (10 bancos A–J, 12 pads por banco: A01..A12 a J01..J12).
    """
    kit_dir = Path(output_dir) / kit_name
    kit_dir.mkdir(parents=True, exist_ok=True)

    for bank_idx in range(10):
        bank_letter = chr(65 + bank_idx)
        for slot in range(1, 13):
            pad_num = bank_idx * 16 + slot
            p_info = pads_data.get(pad_num) or pads_data.get(str(pad_num)) or {}
            src_path = p_info.get("source_path", "")
            dest_filename = f"{bank_letter}{slot:02d}.wav"
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
    Genera un paquete de Drum Kit para Native Instruments Maschine (hasta 8 Grupos A–H x 16 pads = 128 pads).
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

    for raw_key in sorted(pads_data, key=lambda k: int(k)):
        pad_num = int(raw_key)
        if not 1 <= pad_num <= 128:
            continue
        p_info = pads_data[raw_key]
        src_path = p_info.get("source_path", "")
        bank_idx = (pad_num - 1) // 16
        bank_letter = chr(65 + bank_idx)
        slot_in_bank = ((pad_num - 1) % 16) + 1
        grp_dir = base_dir / "Samples" / f"Group_{bank_letter}"
        grp_dir.mkdir(parents=True, exist_ok=True)

        s_name = p_info.get("sample_name", f"Sound_{pad_num:02d}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", s_name)
        dest_filename = f"{bank_letter}{slot_in_bank:02d}_{clean_name}.wav"

        if src_path and Path(src_path).exists():
            _convert_audio(src_path, grp_dir / dest_filename, mono=False)

        manifest["sounds"].append({
            "slot": pad_num,
            "group": f"Group_{bank_letter}",
            "pad_in_group": slot_in_bank,
            "name": s_name,
            "file": f"Samples/Group_{bank_letter}/{dest_filename}",
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
    Mapea hasta 48 sonidos sobre las 12 teclas de los grupos A–D y genera:
    1. Carpeta con samples .wav listos para arrastrar al EP Sample Tool (teenage.engineering/apps/ep-sample-tool)
    2. Archivo meta.json con asignaciones de grupo, tecla, volumen, afinación y paneo.
    3. Archivo ZIP de transporte de muestras y mapa; no es un backup nativo del EP-133.
    4. Guía técnica README_EP133_KO_II.txt con instrucciones de importación paso a paso.
    
    Retorna: (ruta_directorio_kit, ruta_archivo_pak)
    """
    clean_kit_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", kit_name.strip()) or "EP133_Kit"
    kit_dir = Path(output_dir) / clean_kit_name
    sounds_dir = kit_dir / "sounds"

    # Mapeo de teclas de hardware EP-133 (12 teclas por grupo: 1-9, ., 0, ENTER en Grupos A, B, C, D)
    base_group_keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "ENTER"]
    ep_keys = [
        (grp, k)
        for grp in ("A", "B", "C", "D")
        for k in base_group_keys
    ]
    if any(not 1 <= int(number) <= len(ep_keys) for number in pads_data):
        raise ValueError('EP-133: el mapa de un kit admite 4 grupos de 12 sonidos (48 en total)')
    sounds_dir.mkdir(parents=True, exist_ok=True)

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
    for raw_key in sorted(pads_data, key=lambda k: int(k)):
        pad_num = int(raw_key)
        p_info = pads_data[raw_key]
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Sound_{pad_num:02d}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", s_name)
        slot_filename = f"{pad_num:03d}_PAD{pad_num:02d}_{clean_name}.wav"
        dest_file = sounds_dir / slot_filename

        grp, key = ep_keys[pad_num - 1]

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
Total de Muestras: {copied_count} / 48

INSTRUCCIONES DE IMPORTACIÓN:
1. Conecta tu EP-133 K.O. II por USB-C a tu ordenador y enciéndelo.
2. Abre en Google Chrome o navegador compatible:
   https://teenage.engineering/apps/ep-sample-tool
3. Método A (Arrastrar y Soltar):
   - Abre la carpeta 'sounds/' y arrastra los archivos .wav directamente a los
     slots de sonido deseados.
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
- Pads 17–24: Grupo B, teclas 5–ENTER; 25–36: Grupo C; 37–48: Grupo D.
================================================================================
"""
    readme_en_content = f"""================================================================================
TEENAGE ENGINEERING EP-133 K.O. II — BEATOS SAMPLE KIT
================================================================================
Kit: {clean_kit_name}
Samples: {copied_count} / 48

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
  17–24=B/5–ENTER   25–36=Group C   37–48=Group D
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
    po_candidate_keys = [k for k in sorted(pads_data, key=lambda x: int(x)) if 1 <= int(k) <= 16]
    if not po_candidate_keys:
        po_candidate_keys = sorted(pads_data, key=lambda x: int(x))[:16]
    if len(po_candidate_keys) * gap_ms / 1000 >= max_total_sec:
        raise ValueError("Las pausas ocupan todo el presupuesto; reduce su duración")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{kit_name}_PO33_AutoSlice_Reel.wav"

    sample_rate = 44100
    gap_samples = int(sample_rate * (gap_ms / 1000.0))
    zero_frame = struct.pack("<h", 0)

    # 1. Leer y decodificar cada pad activo con el lector universal multi-formato (hasta 16 slices PO-33)
    parsed_pads = []
    for raw_k in po_candidate_keys:
        pad_num = int(raw_k)
        p_info = pads_data.get(raw_k, {})
        src_path = p_info.get("source_path", "")
        s_name = p_info.get("sample_name", f"Pad_{pad_num}")
        s_type = p_info.get("sound_type", "SAMPLE")

        if not src_path or not Path(src_path).exists():
            if raw_k in pads_data:
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


def _ascii_stem(name: str, max_len: int, prefix: str = "") -> str:
    """Genera un stem ASCII en mayúsculas seguro para sistemas de archivos FAT16/DOS de MPC vintage."""
    raw = re.sub(r"[^A-Za-z0-9_-]", "", (name or "").upper())
    if prefix:
        avail = max(1, max_len - len(prefix))
        return (prefix + raw[:avail])[:max_len]
    return (raw or "SAMPLE")[:max_len]


def export_mpc1000_pgm_kit(
    kit_name: str,
    pads_data: Dict[int, dict],
    output_dir: str | Path,
) -> Path:
    """
    Exporta un kit binario nativo `.PGM` (10,756 bytes) + WAV 16-bit 44.1 kHz
    compatible con Akai MPC1000, MPC2500, MPC500 y JJOS (Standard / OS2XL / OS3).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pgm_stem = _ascii_stem(kit_name, 16)
    pgm_path = out_dir / f"{pgm_stem}.PGM"

    # Layout binario exacto MPC1000 PGM 1.00 (0x2A04 = 10,756 bytes)
    buf = bytearray(10756)
    buf[0:24] = b"\x04\x2a\x00\x00MPC1000 PGM 1.00\x00\x00\x00\x00"

    used_stems: set[str] = set()
    exported_wavs: List[str] = []

    for pad_idx in range(64):
        pad_num = pad_idx + 1
        off = 0x18 + pad_idx * 0xA4
        # Valores por defecto del bloque de instrumento Akai MPC1000/2500 (4 capas x 24 bytes + envolvente/filtro/mixer)
        for layer_idx in range(4):
            loff = off + layer_idx * 0x18
            buf[loff + 0x11] = 100   # Layer Level = 100
            buf[loff + 0x14] = 127   # Velocity High = 127
        buf[off + 0x67] = 100        # Env Sustain / Decay base
        buf[off + 0x6F] = 100        # Filter1 Freq = 100
        buf[off + 0x77] = 100        # Filter2 Freq = 100
        buf[off + 0x8F] = 100        # Pad Mixer Level = 100
        buf[off + 0x90] = 50         # Pad Mixer Pan = 50 (Center)
        buf[off + 0x91] = 100        # Send / Output Level = 100

        pad_info = pads_data.get(pad_num)
        if not pad_info:
            continue
        src_str = pad_info.get("source_path") or pad_info.get("sample_path") or pad_info.get("abs_path") or ""
        if not src_str or not Path(src_str).is_file():
            continue

        base_name = pad_info.get("sample_name") or Path(src_str).stem
        stem = _ascii_stem(base_name, 16, prefix=f"P{pad_num:02d}_")
        while stem in used_stems:
            stem = _ascii_stem(f"{stem}_{pad_num}", 16)
        used_stems.add(stem)

        wav_dest = out_dir / f"{stem}.WAV"
        _convert_audio(Path(src_str), wav_dest, sample_rate=44100, mono=False)
        exported_wavs.append(wav_dest.name)

        # Layer 1 Sample Name (16 bytes ASCII padded with 0x00)
        stem_bytes = stem.encode("ascii", errors="ignore")[:16]
        buf[off:off + len(stem_bytes)] = stem_bytes

        # Layer 1 Level (0..100), Tune (signed int16 cents at +0x0F), Pan (0..100 at +0x90)
        vol = max(0.0, min(1.0, float(pad_info.get("volume", 0.85))))
        pan = max(0.0, min(1.0, float(pad_info.get("pan", 0.5))))
        tune_semi = max(-36, min(36, int(pad_info.get("tune", 0))))
        mute_grp = pad_mute_group(pad_info)

        buf[off + 0x11] = max(1, min(100, int(round(vol * 100))))
        buf[off + 0x8F] = max(1, min(100, int(round(vol * 100))))
        buf[off + 0x90] = max(0, min(100, int(round(pan * 100))))
        # Tune in MPC1000 is signed 16-bit little-endian at +0x0E..0x0F (semitones * 100 or fine/coarse)
        struct.pack_into("<h", buf, off + 0x0E, int(tune_semi * 100))
        # Voice Overlap (0=POLY, 1=MONO) at +0x62, Mute Group (0..32) at +0x63
        buf[off + 0x62] = 1 if mute_grp > 0 else 0
        buf[off + 0x63] = max(0, min(32, mute_grp))

    # Mapa de notas MIDI para los 64 pads (35..98) en offset 0x2918
    for i in range(64):
        buf[0x2918 + i] = 35 + i
    # Parámetros globales de programa al final del archivo (sliders/master level)
    buf[0x2958] = 0x01
    buf[0x2959] = 0x06
    buf[0x295D] = 0x64
    buf[0x2963] = 0x64
    buf[0x2969] = 0x64
    buf[0x29F8] = 0x40
    buf[0x29FC] = 0x40

    pgm_path.write_bytes(bytes(buf))

    readme_en = (
        f"====================================================================\n"
        f"AKAI MPC1000 / MPC2500 / MPC500 / JJOS — BINARY KIT (.PGM)\n"
        f"Kit: {pgm_stem} | Pads exported: {len(exported_wavs)}\n"
        f"====================================================================\n\n"
        f"IMPORT INSTRUCTIONS (CompactFlash / SD / Internal HDD / USB):\n"
        f"1. Copy this entire folder to your CompactFlash / SD card or HDD.\n"
        f"2. On your MPC1000 / MPC2500 / MPC500, press MODE + PAD 2 (LOAD).\n"
        f"3. Select '{pgm_path.name}' and press DO IT (F6) — Akai OS / JJOS will\n"
        f"   automatically load the program and all 16-bit 44.1 kHz WAV samples.\n"
    )
    (out_dir / "README_MPC1000_2500.txt").write_text(readme_en, encoding="utf-8")
    return pgm_path


def export_mpc2000xl_pgm_kit(
    kit_name: str,
    pads_data: Dict[int, dict],
    output_dir: str | Path,
) -> Path:
    """
    Exporta un kit binario nativo `.PGM` (2,308 bytes) + WAV 16-bit 44.1 kHz con nombres DOS 8.3
    compatible con Akai MPC2000 y MPC2000XL (Floppy / Zip / SCSI / CF / SDHxC).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pgm_stem = _ascii_stem(kit_name, 8)
    pgm_path = out_dir / f"{pgm_stem}.PGM"

    # En MPC2000XL los samples usan nombres cortos DOS 8.3 (<= 8 chars) para compatibilidad total con MPC2000 Clásica y XL
    sample_names: List[str] = []
    pad_to_sample_idx: Dict[int, int] = {}
    pad_mute_groups: Dict[int, int] = {}
    used_stems: set[str] = set()

    for pad_num in range(1, 65):
        pad_info = pads_data.get(pad_num) or pads_data.get(str(pad_num))
        if not pad_info:
            continue
        src_str = pad_info.get("source_path") or pad_info.get("sample_path") or pad_info.get("abs_path") or ""
        if not src_str or not Path(src_str).is_file():
            continue

        base_name = pad_info.get("sample_name") or Path(src_str).stem
        stem = _ascii_stem(base_name, 8, prefix=f"P{pad_num:02d}")
        while stem in used_stems:
            stem = _ascii_stem(f"P{pad_num:02d}S{len(sample_names)+1}", 8)
        used_stems.add(stem)

        wav_dest = out_dir / f"{stem}.WAV"
        _convert_audio(Path(src_str), wav_dest, sample_rate=44100, mono=False)

        s_idx = len(sample_names)
        sample_names.append(stem)
        pad_to_sample_idx[pad_num] = s_idx
        pad_mute_groups[pad_num] = pad_mute_group(pad_info)

    # Mapa estándar de notas MIDI de los 64 pads del MPC2000XL (Bank A..D)
    pad_to_midi = [
        37, 36, 42, 82, 40, 38, 46, 44, 48, 47, 45, 43, 49, 55, 51, 53,
        54, 69, 81, 80, 65, 66, 76, 77, 56, 62, 63, 64, 73, 74, 71, 39,
        52, 57, 58, 59, 60, 61, 67, 68, 70, 72, 75, 78, 79, 35, 41, 50,
        83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98,
    ]
    midi_to_pad = {midi_note: idx + 1 for idx, midi_note in enumerate(pad_to_midi)}

    # Construir estructura binaria exacta según especificación Akai MPC2000/2000XL (2,291 + 17*N bytes)
    out = bytearray()
    # 1. Header (5 bytes): 07 04 <num_samples:uint16> 00
    out.extend(struct.pack("<BBHB", 0x07, 0x04, len(sample_names), 0x00))
    # 2. N bloques de nombre de sample (17 bytes cada uno: 16s + 0x00)
    for i in range(len(sample_names)):
        sname = sample_names[i].encode("ascii", errors="ignore")[:16]
        out.extend(struct.pack("<16sB", sname, 0x00))
    # 3. Marcador 0x1E 0x00 + Nombre de programa (16 bytes) + programsettings (16 bytes)
    out.extend(b"\x1e\x00")
    out.extend(struct.pack("<16s", pgm_stem.encode("ascii", errors="ignore")[:16]))
    out.extend(bytes([1, 0, 12, 1, 99, 0, 1, 12, 0, 99, 0, 88, 35, 0, 43, 0]))

    # 4. 64 bloques de notas MIDI (35..98), cada uno de 25 bytes (1 byte sample_idx + 24 bytes padsettings)
    base_pad_settings = [0, 0, 25, 0, 0, 0, 34, 34, 0, 0, 0, 5, 0, 0, 50, 0, 0, 0, 100, 0, 0, 0, 0, 100]
    mixer_entries = bytearray([0x06])

    for midi_note in range(35, 99):
        p_num = midi_to_pad.get(midi_note, 0)
        s_idx = pad_to_sample_idx.get(p_num, 255)
        pset = list(base_pad_settings)
        vol_byte = 100
        pan_byte = 50

        if p_num in pads_data and s_idx != 255:
            p_info = pads_data[p_num]
            tune_semi = max(-36, min(36, int(p_info.get("tune", 0))))
            tune_lo, tune_hi = struct.unpack("<BB", struct.pack("<h", int(tune_semi * 10)))
            pset[8] = tune_lo
            pset[9] = tune_hi
            vol_byte = max(1, min(100, int(round(float(p_info.get("volume", 0.85)) * 100))))
            pan_byte = max(0, min(100, int(round(float(p_info.get("pan", 0.5)) * 100))))
            pset[18] = vol_byte

            # En MPC2000XL el choke/mute se codifica en pset[6] y pset[7] con hasta 2 notas MIDI (35..98, 34=OFF)
            mg = pad_mute_groups.get(p_num, 0)
            if mg > 0:
                pset[0] = 1  # Voice Overlap = MONO
                peers = [
                    pad_to_midi[other_pad - 1]
                    for other_pad, other_mg in sorted(pad_mute_groups.items())
                    if other_mg == mg and other_pad != p_num and 1 <= other_pad <= 64
                ]
                if len(peers) >= 1:
                    pset[6] = peers[0]
                if len(peers) >= 2:
                    pset[7] = peers[1]

        out.append(s_idx & 0xFF)
        out.extend(bytes(pset))
        # Mixer entry (6 bytes per note: Pan, Level, Output, SendLevel, etc.)
        mixer_entries.extend(bytes([pan_byte, vol_byte, 0x00, 0x00, 0x64, 0x00]))

    # 5. Mixer block (1 + 64*6 = 385 bytes)
    out.extend(mixer_entries)
    # 6. Pad-to-MIDI table (3 + 64 = 67 bytes)
    out.extend(b"\x00\x40\x00")
    out.extend(bytes(pad_to_midi))
    # 7. Hardware trailer (200 bytes -> total 2,308 bytes)
    trailer = (
        [6] + [0] * 64 + [64, 0]
        + list(range(64))
        + [0, 35, 64, 0, 100] + [0] * 63 + [100]
    )
    out.extend(bytes(trailer))
    assert len(out) == 2291 + 17 * len(sample_names), f"MPC2000XL PGM size mismatch: {len(out)}"

    pgm_path.write_bytes(bytes(out))

    readme_en = (
        f"====================================================================\n"
        f"AKAI MPC2000 / MPC2000XL — VINTAGE BINARY KIT (.PGM + DOS 8.3 WAV)\n"
        f"Kit: {pgm_stem}.PGM | Samples: {len(sample_names)} (16-bit / 44.1 kHz)\n"
        f"====================================================================\n\n"
        f"IMPORT INSTRUCTIONS (CF Card / SD-to-SCSI / Floppy Emulator / Zip):\n"
        f"1. All WAV files use strict 8-character DOS 8.3 names and 16-bit 44.1 kHz\n"
        f"   PCM headers required by Akai MPC2000 / MPC2000XL OS 1.20.\n"
        f"2. Copy this folder to your CF/SD/Zip disk.\n"
        f"3. Press SHIFT + 3 (LOAD), select '{pgm_path.name}', and press DO IT (F6).\n"
    )
    (out_dir / "README_MPC2000XL.txt").write_text(readme_en, encoding="utf-8")
    return pgm_path


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
    Genera kits optimizados para MPC (Modern & Legacy 1000/2500/2000XL), Maschine, SP-404MK2, SP-404A, EP-133 o PO-33.
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
            stype = item.get("sound_type", item.get("soundType", "")) or detect_sound_type(raw_sname or fallback_stem or src_path)
            raw_vol = item.get("volume")
            vol_val = float(raw_vol) if raw_vol is not None and raw_vol != 0.707946 else default_pad_volume(stype)
            pads_dict[pad_num] = {
                "pad_number": pad_num,
                "sample_name": raw_sname or fallback_stem,
                "pad_sample_name": item.get("pad_sample_name", ""),
                "sample_file": Path(src_path or rel_path).name if (src_path or rel_path) else "",
                "sound_type": stype,
                "source_path": src_path,
                "volume": vol_val,
                "pan": float(item.get("pan", 0.5)),
                "tune": int(item.get("tune", 0)),
                "mute_group": pad_mute_group(item),
                "monophonic": item.get("monophonic", True),
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
    valid_targets = {
        'universal','mpc','mpc1000','mpc2500','mpc2000xl','mpc2000','mpc_legacy',
        'maschine','sp404mk2','sp404a','po33','po-33','pocket_operator','ep133','ep-133','ko2','ko-ii','ko_ii'
    }
    if target_lower not in valid_targets:
        raise ValueError("Destino de exportación no reconocido")
    target_max_pads = {
        'universal': 128,
        'mpc': 128,
        'mpc1000': 64,
        'mpc2500': 64,
        'mpc2000xl': 64,
        'mpc2000': 64,
        'mpc_legacy': 64,
        'maschine': 128,
        'sp404mk2': 160,
        'sp404a': 160,
        'ep133': 48,
        'ep-133': 48,
        'ko2': 48,
        'ko-ii': 48,
        'ko_ii': 48,
        'po33': 16,
        'po-33': 16,
        'pocket_operator': 16,
    }.get(target_lower, 128)
    if not pads_dict or any(not 1 <= n <= target_max_pads for n in pads_dict):
        raise ValueError(f"El destino '{target}' admite pads 1 a {target_max_pads}; selecciona un destino específico para más bancos")
    sp404a_omitted = [number for number in sorted(pads_dict) if (number - 1) % 16 >= 12]
    if target_lower == 'sp404a' and sp404a_omitted:
        raise ValueError('SP-404A/SX: cada banco tiene 12 pads; mueve los sonidos de las posiciones 13–16 antes de exportar')
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
    warnings = []

    def supported_pads(destination, allowed):
        selected = {number: pad for number, pad in pads_dict.items() if number in allowed}
        omitted = sorted(pads_dict.keys() - selected.keys())
        if omitted:
            warnings.append({'target': destination, 'omitted_pads': omitted})
        return selected

    try:
        # 1. Akai MPC (Modern Standalone: Live / One / X / Key / Beats)
        if target_lower in ("universal", "mpc"):
            mpc_dir = output_base_dir / "Akai_MPC"
            mpc_dir.mkdir(parents=True, exist_ok=True)
            proj_path = export_mpc_project(clean_kit_name, pads_dict, mpc_dir, tempo=tempo)
            prog_path = export_mpc_program(clean_kit_name, pads_dict, mpc_dir, copy_samples=True)
            targets_result["mpc"] = {
                "project_path": proj_path,
                "program_path_root": prog_path,
            }

        # 1b. Akai MPC 1000 / 2500 / 500 / JJOS (.PGM 10,756 bytes + WAV 16/44.1)
        if target_lower in ("universal", "mpc1000", "mpc2500", "mpc_legacy") and (mpc1k_pads := supported_pads('mpc1000', range(1, 65))):
            mpc1k_dir = output_base_dir / "Akai_MPC1000_2500"
            pgm1k_path = export_mpc1000_pgm_kit(clean_kit_name, mpc1k_pads, mpc1k_dir)
            targets_result["mpc1000"] = {
                "pgm_path": str(pgm1k_path),
                "folder": str(mpc1k_dir),
            }

        # 1c. Akai MPC 2000 / 2000XL (.PGM 2,308 bytes + WAV DOS 8.3 16/44.1)
        if target_lower in ("universal", "mpc2000xl", "mpc2000", "mpc_legacy") and (mpc2k_pads := supported_pads('mpc2000xl', range(1, 65))):
            mpc2k_dir = output_base_dir / "Akai_MPC2000XL"
            pgm2k_path = export_mpc2000xl_pgm_kit(clean_kit_name, mpc2k_pads, mpc2k_dir)
            targets_result["mpc2000xl"] = {
                "pgm_path": str(pgm2k_path),
                "folder": str(mpc2k_dir),
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
        if target_lower in ("universal", "sp404a") and (sp_a_pads := supported_pads('sp404a', {n for n in pads_dict if (n-1) % 16 < 12})):
            sp_a_dir = output_base_dir / "Roland_SP404A"
            a_path = export_sp404a_kit(clean_kit_name, sp_a_pads, sp_a_dir)
            targets_result["sp404a"] = {"folder": a_path}

        # 5. Teenage Engineering Pocket Operator PO-33 / PO-133
        if target_lower in ("universal", "po33", "po-33", "pocket_operator") and (po_pads := supported_pads('po33', sorted(pads_dict)[:16])):
            po_dir = output_base_dir / "Pocket_Operator_PO33"
            reel_wav, duration, slices = export_po33_drum_reel(
                clean_kit_name, po_pads, po_dir, **(po_options or {})
            )
            targets_result["po33"] = {
                "reel_wav": reel_wav,
                "duration_sec": duration,
                "ram_limit_sec": (po_options or {}).get("max_total_sec",40.0),
                "slices_count": len(slices),
            }

        # 6. Teenage Engineering EP-133 K.O. II
        if target_lower in ("universal", "ep133", "ep-133", "ko2", "ko-ii", "ko_ii") and (ep_pads := supported_pads('ep133', range(1, 49))):
            ep_dir = output_base_dir / "Teenage_Engineering_EP133"
            ep_dir.mkdir(parents=True, exist_ok=True)
            ep_folder, ep_pak = export_ep133_ko2_kit(clean_kit_name, ep_pads, ep_dir)
            targets_result["ep133"] = {
                "folder": ep_folder,
                "pak_package": ep_pak,
                "slots_count": len(ep_pads),
            }

        return {
            "success": True,
            "kit_name": clean_kit_name,
            "target": target,
            "kit_path": str(output_base_dir),
            "samples_count": len(pads_dict),
            "targets": targets_result,
            "warnings": warnings,
            "message": f"Kit '{clean_kit_name}' generado exitosamente para destino '{target}'.",
        }
    except Exception:
        try:
            shutil.rmtree(output_base_dir)
        except OSError as cleanup_error:
            logger.warning("No se pudo retirar el kit incompleto %s: %s", output_base_dir, cleanup_error)
        raise



def create_chromatic_kit(
    sample_path: str | Path,
    kit_name: str,
    scale: str = "minor",
    root_note: str = "C2",
    start_octave: int = 0,
    monophonic: bool = True,
    target: str = "universal",
    source_root: Optional[str | Path] = None,
    output_base_dir: Optional[str | Path] = None,
    tempo: float = 120.0,
) -> dict:
    """
    Crea un instrumento melódico o bajo cromático de 16 pads afinados sobre la escala seleccionada
    a partir de una única muestra de audio one-shot.
    Apto para 808s, bajos sintetizados, leads, plucks o instrumentos acústicos.
    """
    sample_file = Path(sample_path).resolve()
    if not sample_file.is_file():
        raise FileNotFoundError(f"Muestra de audio no encontrada: {sample_path}")

    clean_kit_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", kit_name.strip()) or "Chromatic_Instrument"

    # Determinar source_root y output_base_dir de forma segura
    mpc_root = Path("/Volumes/MPCSMPL")
    if source_root is None:
        if mpc_root.is_dir() and sample_file.is_relative_to(mpc_root):
            source_root = mpc_root
        elif sample_file.is_relative_to(Path.cwd().resolve()):
            source_root = Path.cwd().resolve()
        else:
            source_root = sample_file.parent
    else:
        source_root = Path(source_root).resolve()

    if output_base_dir is None:
        output_base_dir = source_root / "Custom_Kits"

    root_pc, root_oct = parse_note(root_note)
    offsets = build_scale_offsets(scale, count=16, start_octave=start_octave)

    pads_list: list[dict] = []
    sound_type = "BASS" if monophonic else "MELODIC"
    mute_group = 1 if monophonic else 0

    for idx, tune in enumerate(offsets):
        pad_num = idx + 1
        note_label = note_from_root_offset(root_pc, root_oct, tune)
        pad_sample_name = f"{clean_kit_name}_{note_label}"

        pads_list.append({
            "pad_number": pad_num,
            "pad": pad_num,
            "sample_name": pad_sample_name,
            "pad_sample_name": pad_sample_name,
            "source_path": str(sample_file),
            "volume": default_pad_volume("BASS_808" if monophonic else "KEYS_SYNTH"),
            "pan": 0.5,
            "tune": tune,
            "mute_group": mute_group,
            "monophonic": monophonic,
            "sound_type": sound_type,
        })

    key_str = f"{NOTE_NAMES[root_pc]} {scale.capitalize()}"
    res = create_kit(
        kit_name=clean_kit_name,
        pads=pads_list,
        target=target,
        source_root=source_root,
        output_base_dir=output_base_dir,
        tempo=tempo,
    )
    res["scale"] = scale
    res["root_note"] = root_note
    res["start_octave"] = start_octave
    res["monophonic"] = monophonic
    res["musical_key"] = key_str
    return res


def list_exportable_user_kits(source_root: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    """Lista los kits y proyectos propios de Custom_Kits y MPC-Sample/Projects para empaquetar en una Expansión MPC."""
    root = Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else Path.cwd()
    )
    items: List[Dict[str, Any]] = []
    seen_stems: set[str] = set()

    # 1. Custom_Kits/*/Akai_MPC/*.xpm o *.xpj
    ck_root = root / "Custom_Kits"
    if ck_root.is_dir():
        for kit_dir in sorted(ck_root.iterdir()):
            if not kit_dir.is_dir() or kit_dir.name.startswith("."):
                continue
            mpc_dir = kit_dir / "Akai_MPC"
            search_root = mpc_dir if mpc_dir.is_dir() else kit_dir
            xpjs = [p for p in search_root.rglob("*.xpj") if not p.name.startswith("._")]
            xpms = [p for p in search_root.rglob("*.xpm") if not p.name.startswith("._") and "_[ProjectData]" not in str(p)]
            ref = xpjs[0] if xpjs else (xpms[0] if xpms else None)
            if ref:
                rel = ref.relative_to(root).as_posix()
                pdata_dir = _resolve_project_data_dir(ref) if ref.suffix.lower() == ".xpj" else ref.parent
                wav_count = len([w for w in (pdata_dir or ref.parent).glob("*.[wW][aA][vV]") if not w.name.startswith("._")]) if (pdata_dir or ref.parent).is_dir() else 16
                items.append({
                    "name": kit_dir.name,
                    "rel_path": rel,
                    "source": "Custom_Kits",
                    "folder": "Custom_Kits",
                    "pad_count": wav_count or 16,
                    "tempo": infer_kit_bpm(ref),
                })
                seen_stems.add(kit_dir.name.lower())

    # 2. MPC-Sample/Projects/*.xpj
    proj_root = root / "MPC-Sample" / "Projects"
    if proj_root.is_dir():
        for xpj in sorted(proj_root.glob("*.xpj")):
            if xpj.name.startswith("._") or xpj.stem.lower() in seen_stems:
                continue
            pdata_dir = _resolve_project_data_dir(xpj)
            wav_count = len([w for w in pdata_dir.glob("*.[wW][aA][vV]") if not w.name.startswith("._")]) if pdata_dir and pdata_dir.is_dir() else 16
            items.append({
                "name": xpj.stem,
                "rel_path": xpj.relative_to(root).as_posix(),
                "source": "Projects",
                "folder": "MPC-Sample/Projects",
                "pad_count": wav_count or 16,
                "tempo": infer_kit_bpm(xpj),
            })
            seen_stems.add(xpj.stem.lower())

    return items


def _generate_default_expansion_svg_png(title: str, manufacturer: str) -> bytes:
    """Genera un PNG válido minimalista 1x1 (o placeholder) si el usuario no sube foto."""
    # PNG 1x1 dark cyan pixel fallback
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\xf8\xff"
        b"\x9f\x01\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def create_custom_expansion(
    title: str,
    manufacturer: str = "Astro1Deep",
    description: str = "",
    artist_subfolder: str = "",
    cover_bytes: Optional[bytes] = None,
    cover_filename: str = "Artwork.png",
    selected_kit_paths: Optional[List[str]] = None,
    rack_pads: Optional[Any] = None,
    rack_kit_name: str = "",
    rack_tempo: float = 90.0,
    source_root: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    Construye una Expansión Oficial Akai MPC completa en Expansions/<Título>/ con:
      - Expansion.xml (contrato oficial v2.0.0.1 de Akai MPC)
      - Carátula / Fotografía (Artwork.png / .jpg)
      - Subcarpeta dedicada por Artista / Colección
      - Programas .xpm (982 KB), Proyectos .xpj (con BPM real) y carpetas _[ProjectData]
      - Carpeta [Previews]/ con preescuchas WAV de cada kit
      - Paquete compartible .xpansion.zip en Custom_Kits/<Slug>_Expansion.zip
    """
    root = Path(source_root).resolve() if source_root else (
        Path("/Volumes/MPCSMPL").resolve() if Path("/Volumes/MPCSMPL").is_dir() else Path.cwd().resolve()
    )
    clean_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", (title or "").strip()).strip(".")
    if not clean_title:
        raise ValueError("El título de la expansión es obligatorio.")
    clean_mfg = (manufacturer or "Astro1Deep").strip() or "Astro1Deep"
    clean_sub = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", (artist_subfolder or clean_mfg).strip()).strip(".") or clean_mfg

    exp_root = root / "Expansions"
    exp_root.mkdir(parents=True, exist_ok=True)
    exp_dir = (exp_root / clean_title).resolve()
    if not exp_dir.is_relative_to(exp_root.resolve()):
        raise ValueError("Ruta de expansión fuera del directorio Expansions")

    exp_dir.mkdir(parents=True, exist_ok=True)
    previews_dir = exp_dir / "[Previews]"
    previews_dir.mkdir(parents=True, exist_ok=True)
    artist_dir = exp_dir / clean_sub
    artist_dir.mkdir(parents=True, exist_ok=True)

    # 1. Guardar carátula / fotografía
    ext = Path(cover_filename or "Artwork.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    art_name = f"Artwork{ext}"
    art_path = exp_dir / art_name
    if cover_bytes and len(cover_bytes) >= 16:
        art_path.write_bytes(cover_bytes)
    elif not art_path.is_file():
        art_path.write_bytes(_generate_default_expansion_svg_png(clean_title, clean_mfg))

    # 2. Procesar kits incluidos (Rack actual y/o kits seleccionados de la biblioteca)
    exported_kits: List[Dict[str, Any]] = []

    if rack_pads:
        r_name = re.sub(r"[^a-zA-Z0-9_\-\s]", "", (rack_kit_name or f"{clean_mfg}_Rack_Kit").strip()).strip() or f"{clean_mfg}_Rack_Kit"
        pads_dict = _normalize_pads_input(rack_pads, root)
        if pads_dict:
            kit_leaf = artist_dir / r_name
            kit_leaf.mkdir(parents=True, exist_ok=True)
            bpm_val = float(rack_tempo) if rack_tempo and 40.0 <= float(rack_tempo) <= 240.0 else infer_kit_bpm(r_name, 90.0)
            # Copiar WAVs a la carpeta del kit y a _[ProjectData]
            proj_data = kit_leaf / f"{r_name}_[ProjectData]"
            proj_data.mkdir(parents=True, exist_ok=True)
            local_pads = {}
            first_wav_src = None
            for pad_num, pinfo in sorted(pads_dict.items()):
                src = Path(pinfo["source_path"])
                dest_name = f"{pad_num:02d} {src.stem} ({r_name}).wav"
                dest_wav = kit_leaf / dest_name
                _convert_audio(src, dest_wav, mono=False)
                shutil.copy2(dest_wav, proj_data / dest_name)
                if first_wav_src is None:
                    first_wav_src = dest_wav
                p_copy = dict(pinfo)
                p_copy["source_path"] = str(dest_wav)
                p_copy["sample_file"] = dest_name
                p_copy["sample_name"] = Path(dest_name).stem
                local_pads[pad_num] = p_copy
            export_mpc_program(r_name, local_pads, kit_leaf, copy_samples=False)
            export_mpc_project(r_name, local_pads, artist_dir, tempo=bpm_val)
            # Eliminar .xpm duplicado dentro de _[ProjectData] para no duplicar el conteo de programas
            (proj_data / f"{r_name}.xpm").unlink(missing_ok=True)
            if first_wav_src and first_wav_src.is_file():
                shutil.copy2(first_wav_src, previews_dir / f"{r_name}.wav")
            exported_kits.append({"name": r_name, "artist_folder": clean_sub, "pads": len(local_pads), "tempo": bpm_val})

    for rel_kit in (selected_kit_paths or []):
        cand = (root / str(rel_kit).lstrip("/")).resolve()
        if not cand.is_relative_to(root) or not cand.exists():
            continue
        parsed = None
        if cand.suffix.lower() == ".xpj":
            parsed = parse_xpj_project(cand, root)
            k_name = parsed.get("project_name") or cand.stem
            k_bpm = float(parsed.get("tempo") or infer_kit_bpm(cand, 90.0))
        elif cand.suffix.lower() == ".xpm":
            parsed = parse_xpm_program(cand, root)
            k_name = parsed.get("program_name") or cand.stem
            k_bpm = float(parsed.get("tempo") or infer_kit_bpm(cand, 90.0))
        if not parsed or not parsed.get("pads"):
            continue
        clean_k = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", k_name).strip() or cand.stem
        kit_leaf = artist_dir / clean_k
        kit_leaf.mkdir(parents=True, exist_ok=True)
        proj_data = kit_leaf / f"{clean_k}_[ProjectData]"
        proj_data.mkdir(parents=True, exist_ok=True)
        local_pads = {}
        first_wav_src = None
        for pad_num, pinfo in sorted(parsed["pads"].items()):
            pad_idx = int(pad_num)
            if pad_idx < 1 or pad_idx > 16:
                continue
            fp = pinfo.get("full_path") or ""
            if not fp or not Path(fp).is_file():
                continue
            src = Path(fp)
            dest_name = src.name if re.match(r"^\d{2}\s", src.name) else f"{pad_idx:02d} {src.name}"
            dest_wav = kit_leaf / dest_name
            if not dest_wav.is_file():
                shutil.copy2(src, dest_wav)
            if not (proj_data / dest_name).is_file():
                shutil.copy2(dest_wav, proj_data / dest_name)
            if first_wav_src is None:
                first_wav_src = dest_wav
            local_pads[pad_idx] = {
                "source_path": str(dest_wav),
                "sample_file": dest_name,
                "sample_name": Path(dest_name).stem,
                "volume": float(pinfo.get("volume") if pinfo.get("volume") is not None and pinfo.get("volume") != 0.707946 else default_pad_volume(pinfo.get("sound_type", "PERCUSSION"))),
                "pan": float(pinfo.get("pan", 0.5)),
                "tune": int(pinfo.get("tune", 0)),
                "mute_group": int(pinfo.get("mute_group", 0)),
                "sound_type": pinfo.get("sound_type", "PERCUSSION"),
            }
        if local_pads:
            export_mpc_program(clean_k, local_pads, kit_leaf, copy_samples=False)
            export_mpc_project(clean_k, local_pads, artist_dir, tempo=k_bpm)
            (proj_data / f"{clean_k}.xpm").unlink(missing_ok=True)
            if first_wav_src and first_wav_src.is_file():
                shutil.copy2(first_wav_src, previews_dir / f"{clean_k}.wav")
            exported_kits.append({"name": clean_k, "artist_folder": clean_sub, "pads": len(local_pads), "tempo": k_bpm})

    if not exported_kits:
        raise ValueError("Selecciona al menos un kit/proyecto con muestras válidas o carga muestras en el Rack de 16 pads.")

    # 3. Escribir manifiesto oficial Akai Expansion.xml
    slug_id = re.sub(r"[^a-z0-9]+", ".", f"{clean_mfg}.{clean_title}".lower()).strip(".")
    desc_text = (description or f"Expansión oficial de Drum Racks y proyectos MPC creada por {clean_mfg} en BeatOS.").strip()
    xml_root = ET.Element("expansion", version="2.0.0.1")
    ET.SubElement(xml_root, "local")
    ET.SubElement(xml_root, "identifier").text = f"com.beatos.expansion.{slug_id}"
    ET.SubElement(xml_root, "title").text = clean_title
    ET.SubElement(xml_root, "manufacturer").text = clean_mfg
    ET.SubElement(xml_root, "version").text = "1.0.0"
    ET.SubElement(xml_root, "type").text = "drum"
    ET.SubElement(xml_root, "priority").text = "50"
    ET.SubElement(xml_root, "img").text = art_name
    ET.SubElement(xml_root, "description").text = desc_text
    xml_tree = ET.ElementTree(xml_root)
    ET.indent(xml_tree, space="   ", level=0)
    xml_tree.write(str(exp_dir / "Expansion.xml"), encoding="utf-8", xml_declaration=True)

    # 4. Generar archivo comprimido compartible (.xpansion.zip) en Custom_Kits/
    ck_root = root / "Custom_Kits"
    ck_root.mkdir(parents=True, exist_ok=True)
    zip_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", clean_title).strip("_") or "Custom_Expansion"
    zip_rel = f"Custom_Kits/{zip_slug}_MPC_Expansion.zip"
    zip_path = root / zip_rel
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for file_p in sorted(exp_dir.rglob("*")):
            if file_p.is_file() and not file_p.name.startswith("._"):
                arcname = f"{clean_title}/{file_p.relative_to(exp_dir).as_posix()}"
                zf.write(str(file_p), arcname=arcname)

    return {
        "success": True,
        "title": clean_title,
        "manufacturer": clean_mfg,
        "artist_subfolder": clean_sub,
        "expansion_path": exp_dir.relative_to(root).as_posix(),
        "artwork": f"{exp_dir.relative_to(root).as_posix()}/{art_name}",
        "zip_download_path": zip_rel,
        "kits_count": len(exported_kits),
        "kits": exported_kits,
    }


_NOTE_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTE_NAME_TO_PC = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4,
    "f": 5, "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9,
    "a#": 10, "bb": 10, "b": 11,
}


def detect_sample_pitch_and_key(wav_path: str | Path) -> Dict[str, Any]:
    """
    Detecta la frecuencia fundamental (f0 en Hz), nota musical (C..B), pitch_class (0..11)
    y desviación en cents (-50..+50) mediante autocorrelación con interpolación parabólica
    sobre la cola tonal del sample (ideal para 808s, bajos, sintes y loops).
    """
    p = Path(wav_path)
    # Intentar extraer nota explícita del nombre como referencia secundaria
    m_fn = re.search(r"(?:^|[\s_\-\(\[])([A-Ga-g][#b]?)(?:m|min|maj|major|minor)?(?:[\s_\-\)\]\.]|$)", p.stem)
    fn_note = m_fn.group(1).capitalize() if m_fn else None
    fn_pc = _NOTE_NAME_TO_PC.get(fn_note.lower()) if fn_note else None

    try:
        samples = _convert_audio(p, mono=True, sample_rate=44100)
    except Exception:
        samples = []

    if not samples or len(samples) < 2048:
        return {
            "f0_hz": 0.0,
            "note": fn_note or "",
            "pitch_class": fn_pc,
            "cents_offset": 0,
            "confidence": 0.4 if fn_note else 0.0,
        }

    sr = 44100
    # Saltar los primeros 25 ms del clic de ataque para medir el cuerpo tonal del 808/bajo
    start_idx = min(int(0.025 * sr), len(samples) // 4)
    win_len = min(8192, len(samples) - start_idx)
    seg = [float(x) for x in samples[start_idx : start_idx + win_len]]
    mean_v = sum(seg) / max(1, len(seg))
    seg = [x - mean_v for x in seg]
    energy0 = sum(x * x for x in seg)
    if energy0 <= 1e-6:
        return {"f0_hz": 0.0, "note": fn_note or "", "pitch_class": fn_pc, "cents_offset": 0, "confidence": 0.0}

    # Rango de búsqueda: 30 Hz (lag=1470) a 520 Hz (lag=84)
    min_lag = max(2, int(sr / 520.0))
    max_lag = min(len(seg) // 2, int(sr / 30.0))
    best_lag = min_lag
    best_corr = -1.0
    corrs: Dict[int, float] = {}

    # Búsqueda en paso grueso de 2 muestras y refinamiento local
    for lag in range(min_lag, max_lag + 1, 2):
        n = min(2048, len(seg) - lag)
        s_ab = 0.0
        for i in range(n):
            s_ab += seg[i] * seg[i + lag]
        c = s_ab / energy0
        corrs[lag] = c
        if c > best_corr:
            best_corr = c
            best_lag = lag

    for lag in range(max(min_lag, best_lag - 3), min(max_lag, best_lag + 3) + 1):
        if lag not in corrs:
            n = min(2048, len(seg) - lag)
            corrs[lag] = sum(seg[i] * seg[i + lag] for i in range(n)) / energy0
        if corrs[lag] > best_corr:
            best_corr = corrs[lag]
            best_lag = lag

    # Interpolación parabólica para precisión sub-muestra
    refined_lag = float(best_lag)
    if min_lag < best_lag < max_lag:
        y_m1 = corrs.get(best_lag - 1, best_corr)
        y_0 = best_corr
        y_p1 = corrs.get(best_lag + 1, best_corr)
        denom = y_m1 - 2.0 * y_0 + y_p1
        if abs(denom) > 1e-9:
            refined_lag = best_lag + 0.5 * (y_m1 - y_p1) / denom

    f0_hz = sr / refined_lag if refined_lag > 0 else 0.0
    if f0_hz <= 0 or best_corr < 0.18:
        return {
            "f0_hz": 0.0,
            "note": fn_note or "",
            "pitch_class": fn_pc,
            "cents_offset": 0,
            "confidence": 0.45 if fn_note else 0.0,
        }

    midi_float = 69.0 + 12.0 * math.log2(f0_hz / 440.0)
    midi_round = int(round(midi_float))
    cents_offset = int(round((midi_float - midi_round) * 100))
    pc = midi_round % 12
    octave = (midi_round // 12) - 1
    note_name = f"{_NOTE_NAMES_SHARP[pc]}{octave}"
    return {
        "f0_hz": round(f0_hz, 2),
        "note": note_name,
        "note_root": _NOTE_NAMES_SHARP[pc],
        "pitch_class": pc,
        "cents_offset": cents_offset,
        "confidence": round(min(0.99, max(0.3, best_corr)), 2),
    }


def detect_transient_phase_conflict(wav_a: str | Path, wav_b: str | Path) -> Dict[str, Any]:
    """
    Calcula la correlación de fase en los primeros 50 ms entre dos muestras
    (ej. Kick + 808 o Snare + Clap) para detectar cancelación destructiva de polaridad.
    """
    try:
        sa = _convert_audio(wav_a, mono=True, sample_rate=44100)[:2205]
        sb = _convert_audio(wav_b, mono=True, sample_rate=44100)[:2205]
    except Exception:
        return {"correlation": 0.0, "phase_conflict": False}

    n = min(len(sa), len(sb))
    if n < 256:
        return {"correlation": 0.0, "phase_conflict": False}

    ea = math.sqrt(sum(float(x) * float(x) for x in sa[:n]))
    eb = math.sqrt(sum(float(x) * float(x) for x in sb[:n]))
    if ea <= 1e-6 or eb <= 1e-6:
        return {"correlation": 0.0, "phase_conflict": False}

    dot = sum(float(sa[i]) * float(sb[i]) for i in range(n))
    corr = dot / (ea * eb)
    return {
        "correlation": round(corr, 3),
        "phase_conflict": bool(corr < -0.25),
    }


def autochop_sample_to_16_pads(
    source_audio: str | Path,
    output_root: str | Path,
    max_slices: int = 16,
    kit_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Corta automáticamente un Loop o Breakbeat en hasta 16 pads por detección de transientes
    con ajuste exacto a cruces por cero (Zero-Crossing Snap) y micro-fade de 2 ms sin clics.
    """
    src_p = Path(source_audio).resolve()
    root_p = Path(output_root).resolve()
    if not src_p.is_file():
        raise FileNotFoundError(f"Muestra no encontrada: {src_p}")

    max_slices = max(2, min(16, int(max_slices)))
    samples = _convert_audio(src_p, mono=True, sample_rate=44100)
    sr = 44100
    total_frames = len(samples)
    if total_frames < sr // 4:
        raise ValueError("La muestra es demasiado corta para dividirla en múltiples cortes.")

    clean_stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", (kit_name or src_p.stem)).strip("_") or "Chop_Kit"
    chop_dir = root_p / "Custom_Kits" / f"{clean_stem}_Chops" / "slices"
    chop_dir.mkdir(parents=True, exist_ok=True)

    # 1. Calcular envolvente de flujo de energía (hop = 441 muestras = 10 ms)
    hop = 441
    energies: List[float] = []
    for pos in range(0, total_frames - hop, hop):
        chunk = samples[pos : pos + hop]
        energies.append(sum(abs(x) for x in chunk) / hop)

    flux: List[tuple[float, int]] = []
    min_dist_frames = max(int(0.09 * sr), total_frames // (max_slices * 3))
    for i in range(1, len(energies) - 1):
        diff = energies[i] - energies[i - 1]
        if diff > 0 and diff >= energies[i - 1] * 0.25 and diff > energies[i + 1] - energies[i]:
            flux.append((diff, i * hop))

    flux.sort(key=lambda t: t[0], reverse=True)
    onset_frames = [0]
    for _, f_pos in flux:
        if len(onset_frames) >= max_slices:
            break
        if all(abs(f_pos - existing) >= min_dist_frames for existing in onset_frames):
            onset_frames.append(f_pos)

    onset_frames.sort()
    # Si hay menos de max_slices transientes claros, subdividir el segmento más largo o usar rejilla rítmica
    while len(onset_frames) < max_slices:
        # Buscar el intervalo más largo y partirlo por la mitad
        gaps = [
            ((onset_frames[i + 1] if i + 1 < len(onset_frames) else total_frames) - onset_frames[i], i)
            for i in range(len(onset_frames))
        ]
        max_gap, idx = max(gaps, key=lambda g: g[0])
        if max_gap < int(0.08 * sr):
            break
        mid_frame = onset_frames[idx] + max_gap // 2
        onset_frames.insert(idx + 1, mid_frame)

    # 2. Ajustar cada punto de corte al cruce por cero más cercano (+/- 220 muestras = 5 ms)
    def _snap_zero_crossing(frame_idx: int) -> int:
        if frame_idx <= 0:
            return 0
        if frame_idx >= total_frames - 1:
            return total_frames
        best = frame_idx
        best_val = abs(samples[frame_idx])
        lo = max(1, frame_idx - 220)
        hi = min(total_frames - 2, frame_idx + 220)
        for k in range(lo, hi + 1):
            if (samples[k - 1] <= 0 <= samples[k]) or (samples[k - 1] >= 0 >= samples[k]):
                return k
            if abs(samples[k]) < best_val:
                best_val = abs(samples[k])
                best = k
        return best

    snapped = [0] + [_snap_zero_crossing(f) for f in onset_frames[1:]]
    snapped = sorted(set(snapped))[:max_slices]

    # 3. Exportar cada slice como WAV 16-bit 44.1 kHz con micro-fade de 2 ms al final
    fade_samples = min(88, sr // 500)
    pads_out: List[Dict[str, Any]] = []
    for idx, start_f in enumerate(snapped):
        end_f = snapped[idx + 1] if idx + 1 < len(snapped) else total_frames
        slice_pcm = list(samples[start_f:end_f])
        if not slice_pcm:
            continue
        if len(slice_pcm) > fade_samples * 2:
            for fi in range(fade_samples):
                scale = fi / float(fade_samples)
                slice_pcm[-(fi + 1)] = int(slice_pcm[-(fi + 1)] * scale)

        pad_num = idx + 1
        slice_name = f"{clean_stem}_Slice_{pad_num:02d}.wav"
        slice_path = chop_dir / slice_name
        raw_bytes = struct.pack(f"<{len(slice_pcm)}h", *slice_pcm)
        with wave.open(str(slice_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(raw_bytes)

        rel_slice = slice_path.relative_to(root_p).as_posix()
        pads_out.append({
            "pad": pad_num,
            "rel_path": rel_slice,
            "filename": slice_name,
            "sound_type": "MELODIC_LOOP" if "loop" in src_p.name.lower() else "PERCUSSION",
            "duration_sec": round(len(slice_pcm) / float(sr), 3),
            "mute_group": 6,  # Grupo 6: Slicer / Chop monofónico (cada slice corta al anterior)
            "volume": 0.501187,
            "pan": 0.5,
            "tune": 0,
        })

    return {
        "success": True,
        "kit_name": f"{clean_stem}_Chops",
        "source_sample": src_p.name,
        "slices_count": len(pads_out),
        "chop_folder": chop_dir.relative_to(root_p).as_posix(),
        "pads": pads_out,
    }


def calibrate_xpm(
    xpm_path: Union[str, Path],
    backup: bool = True,
    smart_acoustics: bool = True,
) -> int:
    """Calibra un archivo .xpm según la jerarquía Opción A + análisis acústico PCM y punch_clean choke."""
    xpm_path = Path(xpm_path)
    try:
        tree = ET.parse(xpm_path)
    except Exception:
        return 0
    root = tree.getroot()
    instruments = root.findall(".//Instrument")
    if not instruments:
        return 0
    if backup:
        bak = xpm_path.with_suffix(xpm_path.suffix + ".bak-calib")
        if not bak.exists():
            shutil.copy2(xpm_path, bak)
    modified = 0
    for inst in instruments:
        layers = inst.findall("Layers/Layer")
        sname = ""
        sfile = ""
        for lay in layers:
            sname = (lay.findtext("SampleName") or "").strip()
            sfile = (lay.findtext("SampleFile") or "").strip()
            if sname or sfile:
                break
        name_for_detect = sname or sfile
        if name_for_detect:
            kind = detect_sound_type(name_for_detect)
            wav_cand: Optional[Path] = None
            if smart_acoustics:
                cand_names = [sfile]
                if sname:
                    cand_names.append(sname if sname.lower().endswith(".wav") else f"{sname}.wav")
                for cname in cand_names:
                    if cname:
                        p_cand = xpm_path.parent / Path(cname).name
                        if p_cand.is_file():
                            wav_cand = p_cand
                            break
            if smart_acoustics and wav_cand is not None:
                target_vol = compute_smart_pad_volume(kind, wav_cand)["volume"]
            else:
                target_vol = default_pad_volume(kind)
            current_mute = int(inst.findtext("MuteGroup", "0"))
            # Preserve user custom chop mute groups (> 3)
            target_mute = current_mute if current_mute > 3 else default_mute_group(kind)
            _set_xml_text(inst, "Volume", f"{target_vol:.6f}")
            _set_xml_text(inst, "MuteGroup", str(target_mute))
            modified += 1
        else:
            _set_xml_text(inst, "Volume", "0.501187")
    tree.write(xpm_path, encoding="utf-8", xml_declaration=True)
    return modified


def calibrate_xpj(
    xpj_path: Union[str, Path],
    backup: bool = True,
    smart_acoustics: bool = True,
) -> int:
    """Calibra un archivo .xpj (GZIP JSON): Gain Staging en 4 etapas, análisis acústico PCM y AudioRoute SampQOL."""
    xpj_path = Path(xpj_path)
    try:
        raw = xpj_path.read_bytes()
        data = gzip.decompress(raw)
    except Exception:
        return 0
    lines = data.split(b"\n", 5)
    if len(lines) < 6:
        return 0
    header = b"\n".join(lines[:5]) + b"\n"
    try:
        obj = json.loads(lines[5].decode("utf-8"))
    except Exception:
        return 0

    if backup:
        bak = xpj_path.with_suffix(xpj_path.suffix + ".bak-calib")
        if not bak.exists():
            shutil.copy2(xpj_path, bak)

    modified = 0
    data_dict = obj.get("data", {})
    pdata_dir = _resolve_project_data_dir(xpj_path) if smart_acoustics else None

    # Etapa 4 y análisis de Submixes personalizados
    custom_submix_indices: set[int] = set()
    mixer_dict = data_dict.get("mixer")
    if isinstance(mixer_dict, dict):
        cur_mix_vol = mixer_dict.get("volume", 1.0)
        if cur_mix_vol is None or cur_mix_vol > 0.707946:
            mixer_dict["volume"] = 0.7079457640647888
        outputs = mixer_dict.get("outputs")
        if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
            out_mix = outputs[0].get("mixable")
            if isinstance(out_mix, dict):
                cur_out_vol = out_mix.get("volume")
                if cur_out_vol is None or cur_out_vol > 0.794328:
                    out_mix["volume"] = 0.7079457640647888
        submixes = mixer_dict.get("submixes")
        if isinstance(submixes, list):
            for s_idx, sm in enumerate(submixes):
                if not isinstance(sm, dict):
                    continue
                sm_mix = sm.get("mixable", {})
                sm_ins = sm_mix.get("inserts", {})
                fx_list = sm_ins.get("effects", []) if sm_ins.get("insertsEnabled", True) else []
                active_fx = [e for e in fx_list if isinstance(e, dict) and e.get("enable", True)]
                # Preservar submix solo si tiene >1 inserto en Submix 1 o algún inserto activo en Submix 2..8
                if (s_idx == 0 and len(active_fx) > 1) or (s_idx > 0 and len(active_fx) > 0):
                    custom_submix_indices.add(s_idx)

    tracks = data_dict.get("tracks", [])
    for track in tracks:
        if not isinstance(track, dict):
            continue
        cur_tvol = track.get("volume")
        if cur_tvol is None or cur_tvol < 0.50 or cur_tvol > 0.80:
            track["volume"] = 0.7079457640647888
        prog_obj = track.get("program")
        if isinstance(prog_obj, dict) and isinstance(prog_obj.get("mixable"), dict):
            cur_pvol = prog_obj["mixable"].get("volume")
            if cur_pvol is None or cur_pvol < 0.50 or cur_pvol > 0.80:
                prog_obj["mixable"]["volume"] = 0.7079457640647888

        drum = track.get("program", {}).get("drum") if isinstance(track.get("program"), dict) else None
        if not drum or not isinstance(drum, dict):
            continue
        instruments = drum.get("instruments", [])
        for inst in instruments:
            if not isinstance(inst, dict):
                continue
            layersv = inst.get("layersv", [])
            sname = ""
            sfile = ""
            if layersv and isinstance(layersv, list) and len(layersv) > 0 and isinstance(layersv[0], dict):
                sname = (layersv[0].get("sampleName") or "").strip()
                sfile = (layersv[0].get("sampleFile") or "").strip()
            name_for_detect = sname or sfile
            mixable = inst.get("mixable")
            if isinstance(mixable, dict):
                ar = mixable.get("audioRoute")
                if isinstance(ar, dict):
                    dest = ar.get("destination", 0)
                    sub_idx = ar.get("audioRouteSubIndex", 0)
                    if not (dest == 1 and sub_idx in custom_submix_indices):
                        ar["destination"] = 0
                        ar["audioRouteSubIndex"] = 0

            if name_for_detect:
                kind = detect_sound_type(name_for_detect)
                wav_cand: Optional[Path] = None
                if smart_acoustics:
                    search_dirs = [d for d in (pdata_dir, xpj_path.parent) if d is not None]
                    cand_names = [sfile]
                    if sname:
                        cand_names.append(sname if sname.lower().endswith(".wav") else f"{sname}.wav")
                    for sdir in search_dirs:
                        for cname in cand_names:
                            if cname:
                                cand = sdir / Path(cname).name
                                if cand.is_file():
                                    wav_cand = cand
                                    break
                        if wav_cand is not None:
                            break
                if smart_acoustics and wav_cand is not None:
                    target_vol = compute_smart_pad_volume(kind, wav_cand)["volume"]
                else:
                    target_vol = default_pad_volume(kind)
                cur_mute = inst.get("whichMuteGroup", 0)
                target_mute = cur_mute if cur_mute > 3 else default_mute_group(kind)
                if isinstance(mixable, dict):
                    mixable["volume"] = target_vol
                    mixable["muteGroup"] = target_mute
                inst["whichMuteGroup"] = target_mute
                modified += 1

    new_json_bytes = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    new_payload = header + new_json_bytes
    xpj_path.write_bytes(gzip.compress(new_payload))
    return modified


def calibrate_library_projects(
    root_path: Path,
    backup: bool = True,
    smart_acoustics: bool = True,
) -> Dict[str, Any]:
    """Escanea y recalibra todos los proyectos y programas de la biblioteca."""
    root_p = Path(root_path).resolve()
    xpm_count = 0
    xpj_count = 0
    pads_calibrated = 0

    # 1. Calibrar todos los .xpm fuera de Expansions y BeatOS/templates
    for xpm in root_p.rglob("*.xpm"):
        if "Expansions" in xpm.parts or "templates" in xpm.parts or xpm.name.endswith(".bak-calib.xpm"):
            continue
        pads_mod = calibrate_xpm(xpm, backup=backup, smart_acoustics=smart_acoustics)
        if pads_mod > 0:
            xpm_count += 1
            pads_calibrated += pads_mod

    # 2. Calibrar todos los .xpj fuera de Expansions y BeatOS/templates
    for xpj in root_p.rglob("*.xpj"):
        if "Expansions" in xpj.parts or "templates" in xpj.parts or xpj.name.endswith(".bak-calib.xpj"):
            continue
        pads_mod = calibrate_xpj(xpj, backup=backup, smart_acoustics=smart_acoustics)
        if pads_mod > 0:
            xpj_count += 1
            pads_calibrated += pads_mod

    return {
        "success": True,
        "root": str(root_p),
        "xpm_calibrated": xpm_count,
        "xpj_calibrated": xpj_count,
        "total_pads_updated": pads_calibrated,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        import argparse
        import base64
        parser = argparse.ArgumentParser(description="BeatOS hardware kit builder")
        commands = parser.add_subparsers(dest="command", required=True)
        create = commands.add_parser("create")
        create.add_argument("--name", required=True)
        create.add_argument("--target", default="universal", choices=["universal", "mpc", "mpc1000", "mpc2500", "mpc2000xl", "mpc2000", "mpc_legacy", "maschine", "sp404mk2", "sp404a", "po33", "ep133"])
        create.add_argument("--b64", required=True)
        create.add_argument("--root", type=Path, required=True)

        chromatic = commands.add_parser("chromatic", help="Crea un instrumento melódico/cromático de 16 pads afinados")
        chromatic.add_argument("--sample", required=True, type=Path, help="Ruta al archivo WAV one-shot")
        chromatic.add_argument("--name", required=True, help="Nombre del kit o instrumento")
        chromatic.add_argument("--scale", default="minor", choices=list(SCALES.keys()), help="Escala musical")
        chromatic.add_argument("--root-note", default="C2", help="Nota base del sample (ej. C2, F#1)")
        chromatic.add_argument("--start-octave", default=0, type=int, help="Offset de octava inicial (ej. -1, 0, 1)")
        chromatic.add_argument("--polyphonic", action="store_true", help="Desactiva mute groups (polifónico)")
        chromatic.add_argument("--target", default="universal", choices=["universal", "mpc", "mpc1000", "mpc2500", "mpc2000xl", "mpc2000", "mpc_legacy", "maschine", "sp404mk2", "sp404a", "po33", "ep133"])
        chromatic.add_argument("--root", type=Path, default=None, help="Directorio raíz de biblioteca")
        chromatic.add_argument("--out", type=Path, default=None, help="Directorio de salida para Custom_Kits")
        chromatic.add_argument("--tempo", type=float, default=120.0, help="Tempo BPM")

        calibrate = commands.add_parser("calibrate", help="Recalibra ganancia y mute groups de proyectos existentes a Opción A")
        calibrate.add_argument("--path", required=True, type=Path, help="Ruta a la tarjeta o directorio de proyectos")
        calibrate.add_argument("--no-backup", action="store_true", help="Omitir creación de copias .bak-calib")

        args = parser.parse_args()
        if args.command == "create":
            pads = json.loads(base64.b64decode(args.b64, validate=True))
            if not args.root.is_dir():
                parser.error("La biblioteca no existe")
            result = create_kit(args.name, pads, target=args.target, source_root=args.root)
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)
        elif args.command == "chromatic":
            result = create_chromatic_kit(
                sample_path=args.sample,
                kit_name=args.name,
                scale=args.scale,
                root_note=args.root_note,
                start_octave=args.start_octave,
                monophonic=not args.polyphonic,
                target=args.target,
                source_root=args.root,
                output_base_dir=args.out,
                tempo=args.tempo,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(0)
        elif args.command == "calibrate":
            result = calibrate_library_projects(args.path, backup=not args.no_backup)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(0)
    print("=================================================================")
    print("Universal Hardware Kit Builder & Multi-Sampler Bridge v3.5 cargado")
    print(f"Directorio de Backups PO-33 detectado: {DEFAULT_PO_DIR}")
    backups = scan_po33_backups([DEFAULT_PO_DIR])
    print(f"Backups PO-33 encontrados: {len(backups)}")
    for b in backups:
        print(f"  • {b['filename']} ({b['duration_sec']}s, {b['channels']}ch, {b['status']})")
    print("=================================================================")
