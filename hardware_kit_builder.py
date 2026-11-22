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

import array
import copy
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
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from xml.etree import ElementTree as ET

try:
    import mpc_compat as _mpc_compat
except Exception:
    _mpc_compat = None

logger = logging.getLogger(__name__)

# Directorio por defecto de backups de Pocket Operator y configuración de librería
DEFAULT_PO_DIR = Path.home() / "Documents" / "PO- POCKET OPERATORS"
PO_IMPORT_LOCK = threading.Lock()
PO_BACKUP_CONFIG_SCHEMA = 'beatos-po-library-config-v1'
_FORBIDDEN_PO_EXTERNAL_DIRS = (
    Path('/'), Path('/System'), Path('/usr'), Path('/bin'),
    Path('/sbin'), Path('/etc'), Path('/var'), Path('/private'),
    Path('/Library'), Path('/Volumes'),
)


def default_po_backup_dir(root: str | Path) -> Path:
    return Path(root) / 'BeatOS' / 'data' / 'po33_backups'


def po_backup_config_path(root: str | Path) -> Path:
    return Path(root) / 'BeatOS' / 'config' / 'po_backup_config.json'


def _is_temp_root_dir(root: str | Path) -> bool:
    try:
        return Path(root).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    except OSError:
        return False


def _validate_external_po_dir(raw_path: str, *, allow_create: bool = False) -> Path:
    if not isinstance(raw_path, str):
        raise ValueError('La ruta externa debe ser texto')
    cleaned = raw_path.strip()
    if not cleaned or '\x00' in cleaned or len(cleaned) > 512:
        raise ValueError('Indica una ruta absoluta válida para la librería externa')
    p = Path(cleaned).expanduser()
    if not p.is_absolute():
        raise ValueError('La ruta de la librería externa debe ser absoluta')
    if '..' in p.parts:
        raise ValueError('La ruta externa no puede contener segmentos ..')
    abs_norm = Path(os.path.abspath(str(p)))
    for forbidden in _FORBIDDEN_PO_EXTERNAL_DIRS:
        if abs_norm == forbidden:
            raise ValueError(f'No se puede usar {forbidden} como carpeta de backups')
    if p.exists():
        if p.is_symlink() or not p.is_dir():
            raise ValueError('La ruta externa debe ser un directorio real (sin enlaces simbólicos)')
        resolved = p.resolve()
    else:
        if len(abs_norm.parts) >= 3 and abs_norm.parts[1] == 'Volumes':
            vol_root = Path('/Volumes') / abs_norm.parts[2]
            if not vol_root.exists() or not vol_root.is_dir():
                raise ValueError(f'El volumen externo {vol_root} no está montado actualmente')
        if not allow_create:
            raise ValueError(f'La carpeta externa no existe: {abs_norm}')
        cur = abs_norm.parent
        while cur != cur.parent and not cur.exists():
            cur = cur.parent
        if not cur.exists() or cur.is_symlink() or cur in _FORBIDDEN_PO_EXTERNAL_DIRS:
            raise ValueError('El directorio padre de la ruta externa no es válido o no existe')
        p.mkdir(parents=True, exist_ok=True)
        resolved = p.resolve()
    for forbidden in _FORBIDDEN_PO_EXTERNAL_DIRS:
        if resolved == forbidden:
            raise ValueError(f'No se puede usar {forbidden} como carpeta de backups')
    if resolved in (Path('/System'), Path('/usr'), Path('/bin'), Path('/sbin'), Path('/etc')) or any(
        resolved.is_relative_to(sys_dir) for sys_dir in (Path('/System'), Path('/usr'), Path('/bin'), Path('/sbin'), Path('/etc'))
    ):
        raise ValueError('No se permite escribir backups dentro de directorios del sistema')
    return resolved


def load_po_backup_config(root: str | Path) -> dict:
    cfg = {
        'schema': PO_BACKUP_CONFIG_SCHEMA,
        'storage_mode': 'default',
        'external_dir': '',
        'scan_external_dirs': [],
        'include_default_in_scan': True,
        'include_legacy_dirs': True,
    }
    cfg_path = po_backup_config_path(root)
    if not cfg_path.is_file() or cfg_path.is_symlink():
        return cfg
    try:
        raw = json.loads(cfg_path.read_text(encoding='utf-8'))
        if not isinstance(raw, dict):
            return cfg
        mode = raw.get('storage_mode')
        if mode in ('default', 'external'):
            cfg['storage_mode'] = mode
        ext = raw.get('external_dir')
        if isinstance(ext, str):
            cfg['external_dir'] = ext.strip()[:512]
        extra = raw.get('scan_external_dirs')
        if isinstance(extra, list):
            cfg['scan_external_dirs'] = [str(x).strip()[:512] for x in extra[:8] if isinstance(x, str) and x.strip()]
        if isinstance(raw.get('include_default_in_scan'), bool):
            cfg['include_default_in_scan'] = raw['include_default_in_scan']
        if isinstance(raw.get('include_legacy_dirs'), bool):
            cfg['include_legacy_dirs'] = raw['include_legacy_dirs']
    except (OSError, ValueError, TypeError):
        return cfg
    return cfg


def get_po_backup_library_status(root: str | Path) -> dict:
    cfg = load_po_backup_config(root)
    def_dir = default_po_backup_dir(root)
    try:
        def_str = str(def_dir.resolve()) if def_dir.exists() else os.path.abspath(str(def_dir))
    except OSError:
        def_str = os.path.abspath(str(def_dir))

    ext_raw = cfg.get('external_dir', '')
    ext_available = False
    ext_writable = False
    ext_error = ''
    ext_resolved = ext_raw
    if ext_raw:
        try:
            ext_p = _validate_external_po_dir(ext_raw, allow_create=False)
            ext_available = True
            ext_resolved = str(ext_p)
            ext_writable = os.access(ext_p, os.W_OK)
            if not ext_writable:
                ext_error = 'Carpeta sin permisos de escritura'
        except ValueError as exc:
            ext_error = str(exc)

    mode = cfg.get('storage_mode', 'default')
    using_fallback = False
    active_write_dir = def_str
    if mode == 'external':
        if ext_available and ext_writable:
            active_write_dir = ext_resolved
        else:
            using_fallback = True
            active_write_dir = def_str

    scan_dirs = [str(p) for p in po33_backup_dirs(root)]
    return {
        **cfg,
        'default_dir': def_str,
        'external_dir': ext_raw,
        'external_resolved': ext_resolved,
        'external_configured': bool(ext_raw),
        'external_available': ext_available,
        'external_writable': ext_writable,
        'external_error': ext_error,
        'active_write_dir': active_write_dir,
        'using_fallback': using_fallback,
        'scan_dirs': scan_dirs,
    }


def save_po_backup_config(root: str | Path, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('Configuración de librería no válida')
    current = load_po_backup_config(root)
    mode = payload.get('storage_mode', current['storage_mode'])
    if mode not in ('default', 'external'):
        raise ValueError('storage_mode debe ser "default" o "external"')
    allow_create = bool(payload.get('create_if_missing', False))

    if 'external_dir' in payload:
        ext_raw = str(payload.get('external_dir') or '').strip()
        if ext_raw:
            ext_clean = str(_validate_external_po_dir(ext_raw, allow_create=allow_create))
        else:
            ext_clean = ''
    else:
        ext_clean = current['external_dir']

    if mode == 'external' and not ext_clean:
        raise ValueError('Configura una carpeta externa válida antes de activar el almacenamiento externo')

    if 'scan_external_dirs' in payload:
        raw_extra = payload.get('scan_external_dirs')
        if not isinstance(raw_extra, list):
            raise ValueError('scan_external_dirs debe ser una lista')
        clean_extra = []
        for entry in raw_extra[:8]:
            if isinstance(entry, str) and entry.strip():
                validated = str(_validate_external_po_dir(entry.strip(), allow_create=False))
                if validated != ext_clean and validated not in clean_extra:
                    clean_extra.append(validated)
    else:
        clean_extra = current['scan_external_dirs']

    inc_default = payload.get('include_default_in_scan', current['include_default_in_scan'])
    if not isinstance(inc_default, bool):
        raise ValueError('include_default_in_scan debe ser booleano')
    inc_legacy = payload.get('include_legacy_dirs', current['include_legacy_dirs'])
    if not isinstance(inc_legacy, bool):
        raise ValueError('include_legacy_dirs debe ser booleano')

    to_write = {
        'schema': PO_BACKUP_CONFIG_SCHEMA,
        'storage_mode': mode,
        'external_dir': ext_clean,
        'scan_external_dirs': clean_extra,
        'include_default_in_scan': inc_default,
        'include_legacy_dirs': inc_legacy,
        'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    cfg_path = po_backup_config_path(root)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(to_write, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cfg_path.parent, prefix='.po-lib-cfg-', delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, cfg_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return get_po_backup_library_status(root)


def po33_backup_dirs(root: str | Path) -> list[Path]:
    root_p = Path(root)
    is_temp = _is_temp_root_dir(root_p)
    cfg = load_po_backup_config(root_p)
    default_dir = root_p / 'BeatOS/data/po33_backups'

    candidates: list[Path] = []
    if cfg.get('storage_mode') != 'external' or cfg.get('include_default_in_scan', True):
        candidates.append(default_dir)

    ext_raw = cfg.get('external_dir', '')
    if ext_raw:
        try:
            candidates.append(_validate_external_po_dir(ext_raw, allow_create=False))
        except ValueError:
            pass

    for extra in cfg.get('scan_external_dirs', []):
        try:
            candidates.append(_validate_external_po_dir(extra, allow_create=False))
        except ValueError:
            pass

    if not candidates:
        candidates.append(default_dir)
    candidates.append(root_p / 'PO_BACKUPS')

    if not is_temp and cfg.get('include_legacy_dirs', True):
        candidates.extend([
            DEFAULT_PO_DIR,
            Path('/Volumes/MPCSMPL/PO_BACKUPS'),
            Path.home() / 'Music/Pocket_Operator_Backups',
        ])

    unique: list[Path] = []
    seen: set[Path] = set()
    for d in candidates:
        try:
            key = d.resolve()
        except OSError:
            key = d
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def import_po33_backup(root: str | Path, filename: str, data: bytes, *, model: str | None = None, project: str | None = None, storage: str | None = None) -> dict:
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
    cfg = load_po_backup_config(library)
    requested_storage = storage if storage in ('default', 'external') else cfg.get('storage_mode', 'default')
    storage_location = 'default'
    storage_fallback = False
    base_folder = library / 'BeatOS/data/po33_backups'

    if requested_storage == 'external':
        ext_raw = cfg.get('external_dir', '')
        ext_ok: Path | None = None
        if ext_raw:
            try:
                cand = _validate_external_po_dir(ext_raw, allow_create=False)
                if os.access(cand, os.W_OK):
                    ext_ok = cand
            except ValueError:
                ext_ok = None
        if ext_ok is not None:
            base_folder = ext_ok
            storage_location = 'external'
        elif storage == 'external':
            raise ValueError('La carpeta externa configurada no está disponible o no tiene permisos de escritura')
        else:
            storage_fallback = True

    folder = base_folder / model if enhanced else base_folder
    if storage_location == 'default':
        if not folder.resolve().is_relative_to(library):
            raise ValueError('Carpeta de respaldos fuera de la biblioteca')
    else:
        if folder.exists() and folder.is_symlink():
            raise ValueError('La subcarpeta de destino es un enlace simbólico')
    folder.mkdir(parents=True, exist_ok=True)
    if storage_location == 'external' and not folder.resolve().is_relative_to(base_folder.resolve()):
        raise ValueError('Carpeta de destino fuera de la ruta externa')

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
        metadata = {'model': model, 'project': project, 'notes': ''}
    return {
        **inspect_po33_backup(target),
        'model': metadata['model'],
        'project': metadata['project'],
        'notes': metadata.get('notes', ''),
        'storage_location': storage_location,
        'storage_root': str(base_folder.resolve()),
        'storage_fallback': storage_fallback,
        'device_restore_verified': False,
        'payload_verified': False,
    }

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


def default_pad_volume(sound_type: str, profile: str = "hierarchical_a") -> float:
    """Perfiles de volumen de pad para Akai MPC:
    - hierarchical_a (Opción A):
        - KICK / SNARE: -5.0 dB (0.562341) -> Transitorios principales y pegada limpia
        - TOM / BASS_808 / CLAP / CYMBAL / PERCUSSION / MELODIC_LOOP / KEYS_SYNTH: -6.0 dB (0.501187)
        - HIHAT / SHAKER: -7.5 dB (0.421697)
        - FX: -8.0 dB (0.398107)
    - uniform_b (Opción B): -6.0 dB (0.501187) uniforme en todos los pads.
    """
    if str(profile or "hierarchical_a").strip().lower() == "uniform_b":
        return 0.501187
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


def _compute_advanced_acoustic_metrics(
    left: List[float],
    right: List[float],
    fr: int,
    peak_dbfs: float,
    rms_active_dbfs: float,
) -> Dict[str, float]:
    """Calcula True Peak (4x oversampling), LUFS activo (BS.1770 K-weighting), ratio subsónico (<35 Hz) y correlación estéreo grave (<120 Hz)."""
    n_mono = len(left)
    if n_mono == 0:
        return {
            "true_peak_dbtp": -120.0,
            "lufs_active_est": -120.0,
            "subsonic_ratio_35hz": 0.0,
            "low_stereo_corr_120hz": 1.0,
        }

    # --- 1. Intento de alta precisión con numpy + scipy.signal ---
    try:
        import numpy as _np
        from scipy import signal as _sig

        l_arr = _np.asarray(left, dtype=_np.float64) / 32767.0
        has_r = bool(right) and len(right) == n_mono
        r_arr = (_np.asarray(right, dtype=_np.float64) / 32767.0) if has_r else None

        # True Peak 4x oversampling (ITU-R BS.1770)
        if n_mono >= 16:
            tp_l = float(_np.max(_np.abs(_sig.resample_poly(l_arr, 4, 1))))
            tp_r = float(_np.max(_np.abs(_sig.resample_poly(r_arr, 4, 1)))) if has_r else 0.0
            tp_lin = max(tp_l, tp_r, 10.0 ** (peak_dbfs / 20.0))
        else:
            tp_lin = 10.0 ** (peak_dbfs / 20.0)
        true_peak_dbtp = round(max(peak_dbfs, 20.0 * math.log10(max(1e-9, tp_lin))), 2)

        # BS.1770-4 K-weighting (pre-shelf +4 dB @ 1681.97 Hz + RLB HPF @ 38.14 Hz)
        # Coeficientes bilineales exactos adaptados a fs
        fs_f = float(max(8000, fr))
        # Stage 1: High-shelf (+3.999843853973347 dB, Q=0.7071752369554196, fc=1681.974450955533 Hz)
        vh = 10.0 ** (3.999843853973347 / 20.0)
        vb = vh ** 0.4996667741545416
        k_s = math.tan(math.pi * min(1681.974450955533, fs_f * 0.45) / fs_f)
        q_s = 0.7071752369554196
        a0_s = 1.0 + k_s / q_s + k_s * k_s
        b_s = _np.array([
            (vh + vb * k_s / q_s + k_s * k_s) / a0_s,
            2.0 * (k_s * k_s - vh) / a0_s,
            (vh - vb * k_s / q_s + k_s * k_s) / a0_s,
        ])
        a_s = _np.array([1.0, 2.0 * (k_s * k_s - 1.0) / a0_s, (1.0 - k_s / q_s + k_s * k_s) / a0_s])

        # Stage 2: RLB High-pass (fc=38.13547087602444 Hz, Q=0.5003270373238773)
        k_h = math.tan(math.pi * min(38.13547087602444, fs_f * 0.45) / fs_f)
        q_h = 0.5003270373238773
        a0_h = 1.0 + k_h / q_h + k_h * k_h
        b_h = _np.array([1.0 / a0_h, -2.0 / a0_h, 1.0 / a0_h])
        a_h = _np.array([1.0, 2.0 * (k_h * k_h - 1.0) / a0_h, (1.0 - k_h / q_h + k_h * k_h) / a0_h])

        lk = _sig.lfilter(b_h, a_h, _sig.lfilter(b_s, a_s, l_arr))
        rk = _sig.lfilter(b_h, a_h, _sig.lfilter(b_s, a_s, r_arr)) if has_r else None

        # Ventana activa (bloques de 10 ms sobre umbral activo)
        blk = max(16, int(round(fs_f * 0.01)))
        pw = (lk * lk + rk * rk) if has_r else (lk * lk)
        # Agrupar por bloques para ignorar colas de silencio en one-shots
        n_blks = max(1, n_mono // blk)
        trimmed = pw[: n_blks * blk].reshape(n_blks, blk)
        blk_ms = _np.mean(trimmed, axis=1)
        max_blk_ms = float(_np.max(blk_ms)) if blk_ms.size else 0.0
        active_mask = blk_ms > max(1e-7, max_blk_ms * 1e-4)
        mean_k_pw = float(_np.mean(blk_ms[active_mask])) if _np.any(active_mask) else float(_np.mean(pw))
        lufs_active_est = round(-0.691 + 10.0 * math.log10(max(1e-12, mean_k_pw)), 2)

        # Ratio subsónico < 35 Hz (Butterworth orden 2 sobre mezcla mono sin DC)
        mono_ac = (0.5 * (l_arr + r_arr) if has_r else l_arr)
        mono_ac = mono_ac - float(_np.mean(mono_ac))
        total_ac_e = float(_np.sum(mono_ac * mono_ac))
        subsonic_ratio_35hz = 0.0
        if total_ac_e > 1e-10 and n_mono >= 32:
            wn35 = min(0.95, 35.0 / (fs_f * 0.5))
            sos35 = _sig.butter(2, wn35, btype="low", output="sos")
            sub35 = _sig.sosfilt(sos35, mono_ac)
            subsonic_ratio_35hz = round(min(1.0, max(0.0, float(_np.sum(sub35 * sub35)) / total_ac_e)), 4)

        # Correlación estéreo en graves (< 120 Hz) para compatibilidad mono PA
        low_stereo_corr_120hz = 1.0
        if has_r and n_mono >= 32:
            wn120 = min(0.95, 120.0 / (fs_f * 0.5))
            sos120 = _sig.butter(2, wn120, btype="low", output="sos")
            l120 = _sig.sosfilt(sos120, l_arr - float(_np.mean(l_arr)))
            r120 = _sig.sosfilt(sos120, r_arr - float(_np.mean(r_arr)))
            el = float(_np.sum(l120 * l120))
            er = float(_np.sum(r120 * r120))
            denom = math.sqrt(el * er)
            # Solo evaluar correlación si existe energía grave real (>0.5% del total)
            if denom > 1e-10 and (el + er) > total_ac_e * 0.005:
                corr = float(_np.sum(l120 * r120)) / denom
                low_stereo_corr_120hz = round(max(-1.0, min(1.0, corr)), 3)

        return {
            "true_peak_dbtp": true_peak_dbtp,
            "lufs_active_est": lufs_active_est,
            "subsonic_ratio_35hz": subsonic_ratio_35hz,
            "low_stereo_corr_120hz": low_stereo_corr_120hz,
        }
    except Exception:
        pass

    # --- 2. Fallback conservador en Python puro (sin scipy/numpy) ---
    # Interpolación cúbica Hermite en muestras cercanas al pico para estimar ISP
    peak_lin = 10.0 ** (peak_dbfs / 20.0)
    max_interp = peak_lin
    thresh_lin = peak_lin * 0.72
    channels_list = [left, right] if (right and len(right) == n_mono) else [left]
    for ch in channels_list:
        for i in range(1, n_mono - 2):
            x1 = ch[i] / 32767.0
            if abs(x1) < thresh_lin:
                continue
            x0 = ch[i - 1] / 32767.0
            x2 = ch[i + 1] / 32767.0
            x3 = ch[i + 2] / 32767.0
            c0 = x1
            c1 = 0.5 * (x2 - x0)
            c2 = x0 - 2.5 * x1 + 2.0 * x2 - 0.5 * x3
            c3 = 0.5 * (x3 - x0) + 1.5 * (x1 - x2)
            for t in (0.25, 0.5, 0.75):
                val = abs(((c3 * t + c2) * t + c1) * t + c0)
                if val > max_interp:
                    max_interp = val
    # Margen conservador mínimo si el pico está muy caliente
    isp_guard = 0.25 if peak_dbfs > -2.5 else 0.10
    true_peak_dbtp = round(max(peak_dbfs + isp_guard, 20.0 * math.log10(max(1e-9, max_interp))), 2)

    # Estimación LUFS activa desde RMS activo (estéreo suma L+R = +3 dB sobre canal mono en BS.1770)
    stereo_offset = 2.3 if (right and len(right) == n_mono) else -0.691
    lufs_active_est = round(rms_active_dbfs + stereo_offset, 2)

    # Ratio subsónico < 35 Hz vía IIR 2 polos en cascada
    mean_l = sum(left) / n_mono
    alpha35 = min(0.95, (2.0 * math.pi * 35.0) / (float(fr) + 2.0 * math.pi * 35.0))
    lp1 = 0.0
    lp2 = 0.0
    sub_sq = 0.0
    tot_sq = 0.0
    for x in left:
        xc = x - mean_l
        tot_sq += xc * xc
        lp1 += alpha35 * (xc - lp1)
        lp2 += alpha35 * (lp1 - lp2)
        sub_sq += lp2 * lp2
    subsonic_ratio_35hz = round(min(1.0, max(0.0, sub_sq / tot_sq)), 4) if tot_sq > 1e-6 else 0.0

    # Correlación grave < 120 Hz
    low_stereo_corr_120hz = 1.0
    if right and len(right) == n_mono:
        mean_r = sum(right) / n_mono
        alpha120 = min(0.95, (2.0 * math.pi * 120.0) / (float(fr) + 2.0 * math.pi * 120.0))
        lpl = 0.0
        lpr = 0.0
        num = 0.0
        dl_s = 0.0
        dr_s = 0.0
        for i in range(n_mono):
            lpl += alpha120 * ((left[i] - mean_l) - lpl)
            lpr += alpha120 * ((right[i] - mean_r) - lpr)
            num += lpl * lpr
            dl_s += lpl * lpl
            dr_s += lpr * lpr
        denom = math.sqrt(dl_s * dr_s)
        if denom > 1e-6 and (dl_s + dr_s) > tot_sq * 0.005:
            low_stereo_corr_120hz = round(max(-1.0, min(1.0, num / denom)), 3)

    return {
        "true_peak_dbtp": true_peak_dbtp,
        "lufs_active_est": lufs_active_est,
        "subsonic_ratio_35hz": subsonic_ratio_35hz,
        "low_stereo_corr_120hz": low_stereo_corr_120hz,
    }


def analyze_sample_acoustics(wav_path: str | Path) -> Dict[str, Any]:
    """Analiza propiedades físico-acústicas reales de una muestra WAV (Pico, True Peak 4x, RMS activo, LUFS activo, Factor de Cresta, DC offset, subgraves <35Hz/<180Hz y correlación estéreo global/<120Hz)."""
    p = Path(wav_path)
    empty = {
        "valid": False,
        "peak_dbfs": -120.0,
        "true_peak_dbtp": -120.0,
        "rms_active_dbfs": -120.0,
        "lufs_active_est": -120.0,
        "crest_factor_db": 0.0,
        "dc_offset": 0.0,
        "low_energy_ratio": 0.0,
        "subsonic_ratio_35hz": 0.0,
        "stereo_correlation": 1.0,
        "low_stereo_corr_120hz": 1.0,
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

    adv = _compute_advanced_acoustic_metrics(left, right, fr, peak_dbfs, rms_active_dbfs)

    return {
        "valid": True,
        "peak_dbfs": peak_dbfs,
        "true_peak_dbtp": adv["true_peak_dbtp"],
        "rms_active_dbfs": rms_active_dbfs,
        "lufs_active_est": adv["lufs_active_est"],
        "crest_factor_db": crest_factor_db,
        "dc_offset": dc_offset,
        "low_energy_ratio": low_energy_ratio,
        "subsonic_ratio_35hz": adv["subsonic_ratio_35hz"],
        "stereo_correlation": stereo_correlation,
        "low_stereo_corr_120hz": adv["low_stereo_corr_120hz"],
        "duration_sec": duration_sec,
        "channels": n_ch,
        "sample_rate": fr,
        "clipping_risk": bool(peak_dbfs >= -0.75 or adv["true_peak_dbtp"] >= -0.75),
        "dc_offset_warning": bool(abs(dc_offset) >= 0.015),
        "overcompressed_risk": bool(0.0 < crest_factor_db < 7.0),
    }


# ==============================================================================
# MATRICES ENTERPRISE: STUDIO / PRE-MASTERING SAFE vs DIRECTO / PA + DUCKING MPC
# Basado en hardware AC50 (DAC AK4558), MPC Sample 1.3.0.12, SampQOL OS 0.2.0 y Melodee
# ==============================================================================

_STYLE_PROFILE_ALIASES: Dict[str, str] = {
    "boombap": "boombap",
    "boom_bap": "boombap",
    "hiphop": "boombap",
    "hip_hop": "boombap",
    "standard": "boombap",
    "lofi": "lofi",
    "lo_fi": "lofi",
    "chillhop": "lofi",
    "jazz_hop": "jazz_hop",
    "jazz": "jazz_hop",
    "dilla": "jazz_hop",
    "soul_vintage": "jazz_hop",
    "rnb_soul": "jazz_hop",
    "rnb": "jazz_hop",
    "drumless": "drumless",
    "bolero": "drumless",
    "oldies": "drumless",
    "ranchera": "drumless",
    "vals": "drumless",
    "bossa": "drumless",
    "cumbia_son": "afrobeats",
    "drill": "drill",
    "uk_drill": "drill",
    "ny_drill": "drill",
    "trap": "trap",
    "trap_808": "trap",
    "dnb": "dnb",
    "drum_and_bass": "dnb",
    "jungle": "dnb",
    "jungle_footwork": "dnb",
    "footwork": "dnb",
    "house_techno": "house_techno",
    "house": "house_techno",
    "techno": "house_techno",
    "uk_garage": "house_techno",
    "ukg": "house_techno",
    "afrobeats": "afrobeats",
    "baile_funk": "afrobeats",
    "reggaeton": "afrobeats",
}


def _resolve_mix_style_id(style_id: Optional[str]) -> str:
    raw = re.sub(r"[\s\-/]+", "_", str(style_id or "standard").strip().lower())
    return _STYLE_PROFILE_ALIASES.get(raw, "boombap")


def _normalize_mix_mode(mix_mode: Optional[str]) -> str:
    raw = str(mix_mode or "studio_mastering").strip().lower()
    if raw in ("live_pa", "live", "pa", "directo", "stage", "club"):
        return "live_pa"
    return "studio_mastering"


MIX_PROFILE_MATRICES: Dict[str, Dict[str, Any]] = {
    "boombap": {
        "label": "Boom Bap 90s",
        "bpm_range": [84, 96],
        "bpm_ref": 90.0,
        "studio_lufs_range": [-15.5, -14.5],
        "studio_min_crest_db": 10.0,
        "live_pa_lufs_range": [-9.5, -8.5],
        "live_pa_min_crest_db": 7.0,
        "sub_mono_hz": 100,
        "chop_hpf_hz": 105,
        "pa_subsonic_hpf_hz": 32,
        "studio_role_db": {
            "KICK": -5.0, "SNARE": -5.5, "CLAP": -6.0, "TOM": -6.0,
            "BASS_808": -6.5, "BASS": -6.5, "MELODIC_LOOP": -7.5,
            "KEYS_SYNTH": -7.5, "VOCAL": -6.5, "HIHAT": -9.0,
            "CYMBAL": -9.0, "PERCUSSION": -7.5, "FX": -10.0,
        },
        "live_pa_boost_db": 2.3,
    },
    "lofi": {
        "label": "Lo-Fi / Chillhop",
        "bpm_range": [70, 88],
        "bpm_ref": 80.0,
        "studio_lufs_range": [-16.5, -15.0],
        "studio_min_crest_db": 11.0,
        "live_pa_lufs_range": [-10.5, -9.0],
        "live_pa_min_crest_db": 8.0,
        "sub_mono_hz": 100,
        "chop_hpf_hz": 115,
        "pa_subsonic_hpf_hz": 32,
        "studio_role_db": {
            "KICK": -5.5, "SNARE": -6.5, "CLAP": -7.0, "TOM": -7.0,
            "BASS_808": -7.0, "BASS": -7.0, "MELODIC_LOOP": -6.0,
            "KEYS_SYNTH": -6.0, "VOCAL": -7.5, "HIHAT": -10.0,
            "CYMBAL": -10.0, "PERCUSSION": -8.5, "FX": -10.0,
        },
        "live_pa_boost_db": 2.0,
    },
    "jazz_hop": {
        "label": "Jazz-Hop / Dilla",
        "bpm_range": [82, 96],
        "bpm_ref": 88.0,
        "studio_lufs_range": [-16.0, -14.5],
        "studio_min_crest_db": 11.0,
        "live_pa_lufs_range": [-10.0, -9.0],
        "live_pa_min_crest_db": 8.0,
        "sub_mono_hz": 100,
        "chop_hpf_hz": 100,
        "pa_subsonic_hpf_hz": 30,
        "studio_role_db": {
            "KICK": -5.0, "SNARE": -6.0, "CLAP": -6.5, "TOM": -6.5,
            "BASS_808": -6.5, "BASS": -6.5, "MELODIC_LOOP": -6.5,
            "KEYS_SYNTH": -6.5, "VOCAL": -7.0, "HIHAT": -9.5,
            "CYMBAL": -9.5, "PERCUSSION": -8.0, "FX": -10.5,
        },
        "live_pa_boost_db": 2.1,
    },
    "drumless": {
        "label": "Drumless / Bolero / Oldies",
        "bpm_range": [68, 90],
        "bpm_ref": 78.0,
        "studio_lufs_range": [-17.0, -15.0],
        "studio_min_crest_db": 12.0,
        "live_pa_lufs_range": [-11.0, -9.5],
        "live_pa_min_crest_db": 9.0,
        "sub_mono_hz": 90,
        "chop_hpf_hz": 75,
        "pa_subsonic_hpf_hz": 35,
        "studio_role_db": {
            "KICK": -7.0, "SNARE": -7.5, "CLAP": -8.0, "TOM": -8.0,
            "BASS_808": -6.5, "BASS": -6.5, "MELODIC_LOOP": -5.0,
            "KEYS_SYNTH": -5.5, "VOCAL": -5.0, "HIHAT": -10.5,
            "CYMBAL": -10.5, "PERCUSSION": -8.5, "FX": -11.0,
        },
        "live_pa_boost_db": 1.8,
    },
    "drill": {
        "label": "UK / NY Drill",
        "bpm_range": [138, 146],
        "bpm_ref": 142.0,
        "studio_lufs_range": [-14.5, -13.5],
        "studio_min_crest_db": 8.5,
        "live_pa_lufs_range": [-8.5, -7.5],
        "live_pa_min_crest_db": 6.0,
        "sub_mono_hz": 120,
        "chop_hpf_hz": 145,
        "pa_subsonic_hpf_hz": 32,
        "studio_role_db": {
            "KICK": -4.8, "SNARE": -5.8, "CLAP": -6.0, "TOM": -6.5,
            "BASS_808": -4.8, "BASS": -5.0, "MELODIC_LOOP": -8.5,
            "KEYS_SYNTH": -8.5, "VOCAL": -6.0, "HIHAT": -8.0,
            "CYMBAL": -8.5, "PERCUSSION": -7.5, "FX": -10.0,
        },
        "live_pa_boost_db": 2.5,
    },
    "trap": {
        "label": "Trap / 808",
        "bpm_range": [125, 150],
        "bpm_ref": 140.0,
        "studio_lufs_range": [-14.5, -13.5],
        "studio_min_crest_db": 8.5,
        "live_pa_lufs_range": [-8.5, -7.5],
        "live_pa_min_crest_db": 6.0,
        "sub_mono_hz": 120,
        "chop_hpf_hz": 135,
        "pa_subsonic_hpf_hz": 32,
        "studio_role_db": {
            "KICK": -4.8, "SNARE": -5.5, "CLAP": -5.8, "TOM": -6.5,
            "BASS_808": -5.0, "BASS": -5.2, "MELODIC_LOOP": -8.0,
            "KEYS_SYNTH": -8.0, "VOCAL": -5.8, "HIHAT": -7.8,
            "CYMBAL": -8.5, "PERCUSSION": -7.5, "FX": -10.0,
        },
        "live_pa_boost_db": 2.5,
    },
    "dnb": {
        "label": "DnB / Jungle",
        "bpm_range": [168, 178],
        "bpm_ref": 174.0,
        "studio_lufs_range": [-14.5, -13.5],
        "studio_min_crest_db": 8.0,
        "live_pa_lufs_range": [-8.5, -7.5],
        "live_pa_min_crest_db": 6.0,
        "sub_mono_hz": 110,
        "chop_hpf_hz": 135,
        "pa_subsonic_hpf_hz": 34,
        "studio_role_db": {
            "KICK": -4.8, "SNARE": -5.0, "CLAP": -5.8, "TOM": -6.2,
            "BASS_808": -5.5, "BASS": -5.5, "MELODIC_LOOP": -8.5,
            "KEYS_SYNTH": -8.5, "VOCAL": -6.5, "HIHAT": -7.5,
            "CYMBAL": -7.8, "PERCUSSION": -7.2, "FX": -9.5,
        },
        "live_pa_boost_db": 2.5,
    },
    "house_techno": {
        "label": "House / UK Garage",
        "bpm_range": [122, 134],
        "bpm_ref": 128.0,
        "studio_lufs_range": [-15.0, -14.0],
        "studio_min_crest_db": 9.0,
        "live_pa_lufs_range": [-9.0, -8.0],
        "live_pa_min_crest_db": 6.5,
        "sub_mono_hz": 110,
        "chop_hpf_hz": 125,
        "pa_subsonic_hpf_hz": 32,
        "studio_role_db": {
            "KICK": -4.8, "SNARE": -6.2, "CLAP": -6.0, "TOM": -6.5,
            "BASS_808": -5.8, "BASS": -5.8, "MELODIC_LOOP": -7.5,
            "KEYS_SYNTH": -7.5, "VOCAL": -6.5, "HIHAT": -8.0,
            "CYMBAL": -8.5, "PERCUSSION": -7.5, "FX": -9.5,
        },
        "live_pa_boost_db": 2.4,
    },
    "afrobeats": {
        "label": "Afrobeats / Baile Funk",
        "bpm_range": [98, 132],
        "bpm_ref": 112.0,
        "studio_lufs_range": [-15.0, -14.0],
        "studio_min_crest_db": 9.0,
        "live_pa_lufs_range": [-9.0, -8.0],
        "live_pa_min_crest_db": 6.5,
        "sub_mono_hz": 110,
        "chop_hpf_hz": 120,
        "pa_subsonic_hpf_hz": 33,
        "studio_role_db": {
            "KICK": -4.8, "SNARE": -6.0, "CLAP": -6.0, "TOM": -6.2,
            "BASS_808": -5.8, "BASS": -5.8, "MELODIC_LOOP": -7.5,
            "KEYS_SYNTH": -7.5, "VOCAL": -5.8, "HIHAT": -7.8,
            "CYMBAL": -8.2, "PERCUSSION": -7.0, "FX": -10.0,
        },
        "live_pa_boost_db": 2.4,
    },
}

DUCKING_RECIPE_MATRICES: Dict[str, Dict[str, Any]] = {
    "boombap": {
        "syncopated_or_swung": False,
        "allow_pumper_straight": True,
        "key_mode": "kick_pad_pre_fader",
        "studio": {
            "attack_ms": 8.0, "release_div": "1/16", "release_scale": 0.80,
            "ratio": 3.5, "threshold_db": -10.0, "soft_knee_db": 3.0, "target_gr_db": [2.0, 4.0],
            "cc_amount_pct": 22, "cc_color": True, "cc_in_boost_db": 0.0,
            "pumper_speed": "1/8", "pumper_shape_pct": 20, "pumper_depth_pct": 25,
            "soft_clip_shape": "Tanh",
        },
        "live_pa": {
            "attack_ms": 4.5, "release_div": "1/16", "release_scale": 0.68,
            "ratio": 5.0, "threshold_db": -12.0, "soft_knee_db": 2.0, "target_gr_db": [4.0, 6.0],
            "cc_amount_pct": 40, "cc_color": True, "cc_in_boost_db": 3.0,
            "pumper_speed": "1/8", "pumper_shape_pct": 25, "pumper_depth_pct": 38,
            "soft_clip_shape": "Tanh",
        },
    },
    "lofi": {
        "syncopated_or_swung": False,
        "allow_pumper_straight": True,
        "key_mode": "kick_pad_pre_fader",
        "studio": {
            "attack_ms": 12.0, "release_div": "1/16", "release_scale": 0.95,
            "ratio": 3.5, "threshold_db": -11.0, "soft_knee_db": 5.0, "target_gr_db": [3.0, 5.0],
            "cc_amount_pct": 30, "cc_color": True, "cc_in_boost_db": 1.0,
            "pumper_speed": "1/4", "pumper_shape_pct": 25, "pumper_depth_pct": 32,
            "soft_clip_shape": "Sine",
        },
        "live_pa": {
            "attack_ms": 8.0, "release_div": "1/16", "release_scale": 0.82,
            "ratio": 4.5, "threshold_db": -13.0, "soft_knee_db": 4.0, "target_gr_db": [5.0, 7.0],
            "cc_amount_pct": 45, "cc_color": True, "cc_in_boost_db": 3.0,
            "pumper_speed": "1/4", "pumper_shape_pct": 30, "pumper_depth_pct": 42,
            "soft_clip_shape": "Tanh",
        },
    },
    "jazz_hop": {
        "syncopated_or_swung": True,
        "allow_pumper_straight": False,
        "key_mode": "kick_pad_pre_fader",
        "studio": {
            "attack_ms": 10.0, "release_div": "1/16", "release_scale": 0.90,
            "ratio": 3.5, "threshold_db": -10.0, "soft_knee_db": 6.0, "target_gr_db": [2.5, 4.0],
            "cc_amount_pct": 24, "cc_color": True, "cc_in_boost_db": 0.0,
            "pumper_speed": "1/4", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Sine",
        },
        "live_pa": {
            "attack_ms": 6.0, "release_div": "1/16", "release_scale": 0.78,
            "ratio": 4.5, "threshold_db": -12.0, "soft_knee_db": 4.0, "target_gr_db": [4.0, 6.0],
            "cc_amount_pct": 38, "cc_color": True, "cc_in_boost_db": 2.5,
            "pumper_speed": "1/4", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Tanh",
        },
    },
    "drumless": {
        "syncopated_or_swung": True,
        "allow_pumper_straight": False,
        "key_mode": "none_glue_only",
        "studio": {
            "attack_ms": 25.0, "release_div": "1/8", "release_scale": 0.65,
            "ratio": 1.8, "threshold_db": -6.0, "soft_knee_db": 8.0, "target_gr_db": [1.0, 2.0],
            "cc_amount_pct": 12, "cc_color": False, "cc_in_boost_db": 0.0,
            "pumper_speed": "1/4", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Sine",
        },
        "live_pa": {
            "attack_ms": 18.0, "release_div": "1/8", "release_scale": 0.55,
            "ratio": 2.2, "threshold_db": -8.0, "soft_knee_db": 6.0, "target_gr_db": [2.0, 3.0],
            "cc_amount_pct": 20, "cc_color": False, "cc_in_boost_db": 1.0,
            "pumper_speed": "1/4", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Sine",
        },
    },
    "drill": {
        "syncopated_or_swung": True,
        "allow_pumper_straight": False,
        "key_mode": "ghost_kick_vol0",
        "studio": {
            "attack_ms": 1.0, "release_div": "1/16", "release_scale": 0.65,
            "ratio": 7.0, "threshold_db": -14.0, "soft_knee_db": 0.0, "target_gr_db": [5.0, 7.0],
            "cc_amount_pct": 22, "cc_color": False, "cc_in_boost_db": 0.0,
            "pumper_speed": "1/16", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Tanh",
        },
        "live_pa": {
            "attack_ms": 0.5, "release_div": "1/16", "release_scale": 0.55,
            "ratio": 9.0, "threshold_db": -16.0, "soft_knee_db": 0.0, "target_gr_db": [6.0, 9.0],
            "cc_amount_pct": 35, "cc_color": False, "cc_in_boost_db": 2.5,
            "pumper_speed": "1/16", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Tanh",
        },
    },
    "trap": {
        "syncopated_or_swung": True,
        "allow_pumper_straight": False,
        "key_mode": "ghost_kick_vol0",
        "studio": {
            "attack_ms": 2.0, "release_div": "1/16", "release_scale": 0.72,
            "ratio": 6.0, "threshold_db": -13.0, "soft_knee_db": 1.0, "target_gr_db": [4.0, 6.0],
            "cc_amount_pct": 25, "cc_color": False, "cc_in_boost_db": 1.0,
            "pumper_speed": "1/16", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Parabolic",
        },
        "live_pa": {
            "attack_ms": 1.0, "release_div": "1/16", "release_scale": 0.62,
            "ratio": 8.5, "threshold_db": -16.0, "soft_knee_db": 0.0, "target_gr_db": [6.0, 8.0],
            "cc_amount_pct": 40, "cc_color": False, "cc_in_boost_db": 3.5,
            "pumper_speed": "1/16", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Parabolic",
        },
    },
    "dnb": {
        "syncopated_or_swung": True,
        "allow_pumper_straight": False,
        "key_mode": "kick_and_snare_bus12",
        "studio": {
            "attack_ms": 0.5, "release_div": "1/16", "release_scale": 0.58,
            "ratio": 8.0, "threshold_db": -14.0, "soft_knee_db": 0.0, "target_gr_db": [4.0, 6.0],
            "cc_amount_pct": 25, "cc_color": False, "cc_in_boost_db": 1.0,
            "pumper_speed": "1/16", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Tanh",
        },
        "live_pa": {
            "attack_ms": 0.3, "release_div": "1/16", "release_scale": 0.48,
            "ratio": 10.0, "threshold_db": -16.0, "soft_knee_db": 0.0, "target_gr_db": [6.0, 8.0],
            "cc_amount_pct": 40, "cc_color": False, "cc_in_boost_db": 3.5,
            "pumper_speed": "1/16", "pumper_shape_pct": 0, "pumper_depth_pct": 0,
            "soft_clip_shape": "Tanh",
        },
    },
    "house_techno": {
        "syncopated_or_swung": False,
        "allow_pumper_straight": True,
        "key_mode": "ghost_kick_vol0",
        "studio": {
            "attack_ms": 3.5, "release_div": "1/16", "release_scale": 0.95,
            "ratio": 5.0, "threshold_db": -12.0, "soft_knee_db": 2.0, "target_gr_db": [4.0, 6.0],
            "cc_amount_pct": 30, "cc_color": False, "cc_in_boost_db": 1.5,
            "pumper_speed": "1/4", "pumper_shape_pct": 25, "pumper_depth_pct": 52,
            "soft_clip_shape": "Tanh",
        },
        "live_pa": {
            "attack_ms": 2.0, "release_div": "1/16", "release_scale": 0.85,
            "ratio": 7.0, "threshold_db": -15.0, "soft_knee_db": 1.0, "target_gr_db": [6.0, 9.0],
            "cc_amount_pct": 48, "cc_color": True, "cc_in_boost_db": 4.0,
            "pumper_speed": "1/4", "pumper_shape_pct": 30, "pumper_depth_pct": 68,
            "soft_clip_shape": "Tanh",
        },
    },
    "afrobeats": {
        "syncopated_or_swung": False,
        "allow_pumper_straight": True,
        "key_mode": "kick_pad_pre_fader",
        "studio": {
            "attack_ms": 4.5, "release_div": "1/16", "release_scale": 0.82,
            "ratio": 4.5, "threshold_db": -11.0, "soft_knee_db": 3.0, "target_gr_db": [3.0, 5.0],
            "cc_amount_pct": 25, "cc_color": False, "cc_in_boost_db": 1.0,
            "pumper_speed": "1/8", "pumper_shape_pct": 20, "pumper_depth_pct": 30,
            "soft_clip_shape": "Tanh",
        },
        "live_pa": {
            "attack_ms": 2.5, "release_div": "1/16", "release_scale": 0.72,
            "ratio": 6.5, "threshold_db": -14.0, "soft_knee_db": 2.0, "target_gr_db": [5.0, 7.0],
            "cc_amount_pct": 40, "cc_color": False, "cc_in_boost_db": 3.0,
            "pumper_speed": "1/8", "pumper_shape_pct": 25, "pumper_depth_pct": 42,
            "soft_clip_shape": "Tanh",
        },
    },
}


def compute_profiled_pad_volume(
    sound_type: str,
    wav_path: Optional[str | Path] = None,
    *,
    mix_mode: str = "studio_mastering",
    style_id: str = "standard",
    bank_trim_db: float = 0.0,
) -> Dict[str, Any]:
    """Calcula el volumen óptimo de un pad según rol, acústica real, género y perfil (studio_mastering vs live_pa) con guarda anti-ISP AK4558."""
    stype = (sound_type or "PERCUSSION").strip().upper()
    mode = _normalize_mix_mode(mix_mode)
    canon_style = _resolve_mix_style_id(style_id)
    prof = MIX_PROFILE_MATRICES.get(canon_style, MIX_PROFILE_MATRICES["boombap"])
    trim_db = max(-3.0, min(3.0, float(bank_trim_db or 0.0)))

    # Si style_id es "standard" en studio_mastering, mantener compatibilidad exacta con target_map histórico
    if str(style_id or "standard").strip().lower() == "standard" and mode == "studio_mastering":
        base_target_db = {"KICK": -5.0, "SNARE": -5.0, "HIHAT": -7.5, "FX": -8.0}.get(stype, -6.0)
    else:
        role_map = prof["studio_role_db"]
        base_target_db = float(role_map.get(stype, -6.5))
        if mode == "live_pa":
            base_target_db += float(prof.get("live_pa_boost_db", 2.2))

    target_db = round(base_target_db + trim_db, 3)

    ac: Dict[str, Any] = {}
    if wav_path:
        ac = analyze_sample_acoustics(wav_path)

    if not ac.get("valid") or ac.get("peak_dbfs", -120.0) <= -60.0:
        min_db, max_db = (-12.0, -1.0) if mode == "studio_mastering" else (-11.0, -0.85)
        clamped_db = round(max(min_db, min(max_db, target_db)), 3)
        fallback_vol = round(10.0 ** (clamped_db / 20.0), 6)
        return {
            "volume": fallback_vol,
            "gain_db": clamped_db,
            "target_db": target_db,
            "peak_dbfs": float(ac.get("peak_dbfs", -120.0)),
            "true_peak_dbtp": float(ac.get("true_peak_dbtp", -120.0)),
            "rms_dbfs": float(ac.get("rms_active_dbfs", -120.0)),
            "lufs_active_est": float(ac.get("lufs_active_est", -120.0)),
            "crest_factor_db": float(ac.get("crest_factor_db", 0.0)),
            "low_energy_ratio": float(ac.get("low_energy_ratio", 0.0)),
            "subsonic_ratio_35hz": float(ac.get("subsonic_ratio_35hz", 0.0)),
            "stereo_correlation": float(ac.get("stereo_correlation", 1.0)),
            "low_stereo_corr_120hz": float(ac.get("low_stereo_corr_120hz", 1.0)),
            "mix_mode": mode,
            "style_id": canon_style,
            "bank_trim_db": round(trim_db, 2),
            "smart_applied": False,
        }

    peak_dbfs = float(ac["peak_dbfs"])
    true_peak_dbtp = float(ac.get("true_peak_dbtp", peak_dbfs))
    rms_dbfs = float(ac["rms_active_dbfs"])
    lufs_est = float(ac.get("lufs_active_est", rms_dbfs))
    crest_db = float(ac["crest_factor_db"])
    low_ratio = float(ac["low_energy_ratio"])
    sub35 = float(ac.get("subsonic_ratio_35hz", 0.0))
    low_corr = float(ac.get("low_stereo_corr_120hz", 1.0))
    duration_sec = float(ac["duration_sec"])

    effective_peak = max(-4.5, min(0.0, peak_dbfs))
    cf_thresh = 7.5 if mode == "studio_mastering" else float(prof.get("live_pa_min_crest_db", 6.5))
    cf_penalty = min(2.0, (cf_thresh - crest_db) * 0.35) if crest_db < cf_thresh else 0.0
    sub_penalty = 0.5 if (stype not in ("KICK",) and low_ratio > 0.70 and duration_sec > 0.35) else 0.0
    # Penalización adicional de seguridad en Directo PA si hay exceso subsónico < 35 Hz
    pa_subsonic_guard = min(1.5, (sub35 - 0.12) * 5.0) if (mode == "live_pa" and sub35 > 0.12) else 0.0

    raw_gain_db = target_db - effective_peak - cf_penalty - sub_penalty - pa_subsonic_guard

    # Techo anti-clipping AK4558: true_peak_dbtp + gain_db <= ceiling_dbtp
    tp_ceiling = -1.0 if mode == "studio_mastering" else -0.85
    if true_peak_dbtp > -12.0:
        max_safe_gain = tp_ceiling - true_peak_dbtp
        raw_gain_db = min(raw_gain_db, max_safe_gain)

    min_clamp = -12.0 if mode == "studio_mastering" else -11.5
    max_clamp = -1.0 if mode == "studio_mastering" else -0.85
    gain_db = round(max(min_clamp, min(max_clamp, raw_gain_db)), 3)
    linear_vol = round(max(0.05, min(0.95, 10.0 ** (gain_db / 20.0))), 6)

    return {
        "volume": linear_vol,
        "gain_db": gain_db,
        "target_db": target_db,
        "peak_dbfs": peak_dbfs,
        "true_peak_dbtp": true_peak_dbtp,
        "rms_dbfs": rms_dbfs,
        "lufs_active_est": lufs_est,
        "crest_factor_db": crest_db,
        "low_energy_ratio": low_ratio,
        "subsonic_ratio_35hz": sub35,
        "stereo_correlation": float(ac["stereo_correlation"]),
        "low_stereo_corr_120hz": low_corr,
        "mix_mode": mode,
        "style_id": canon_style,
        "bank_trim_db": round(trim_db, 2),
        "smart_applied": True,
    }


def compute_smart_pad_volume(sound_type: str, wav_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Wrapper retrocompatible de ganancia inteligente BeatOS v4.0 (Studio / Pre-Mastering Safe estándar)."""
    return compute_profiled_pad_volume(
        sound_type,
        wav_path,
        mix_mode="studio_mastering",
        style_id="standard",
        bank_trim_db=0.0,
    )


def build_mpc_ducking_recipe(
    style_id: str = "standard",
    bpm: float = 90.0,
    *,
    mix_mode: str = "studio_mastering",
    has_kick: bool = True,
    has_bass: bool = False,
    has_melodic: bool = False,
    swing_pct: float = 50.0,
    sampqol_active: bool = True,
) -> Dict[str, Any]:
    """Genera receta cuantitativa de Compresión/Ducking para Akai MPC Sample (Stock 1.3.0.12, SampQOL OS 0.2.0 y Melodee)."""
    canon_style = _resolve_mix_style_id(style_id)
    mode = _normalize_mix_mode(mix_mode)
    bpm_val = max(30.0, min(300.0, float(bpm or MIX_PROFILE_MATRICES[canon_style]["bpm_ref"])))
    swing_val = float(swing_pct if swing_pct is not None else 50.0)

    mix_prof = MIX_PROFILE_MATRICES[canon_style]
    duck_prof = DUCKING_RECIPE_MATRICES[canon_style]
    cfg = duck_prof["live_pa" if mode == "live_pa" else "studio"]

    rel_1_4 = round(60000.0 / bpm_val, 1)
    rel_1_8 = round(30000.0 / bpm_val, 1)
    rel_1_16 = round(15000.0 / bpm_val, 1)
    rel_1_32 = round(7500.0 / bpm_val, 1)

    div_ms = {"1/4": rel_1_4, "1/8": rel_1_8, "1/16": rel_1_16, "1/32": rel_1_32}.get(cfg["release_div"], rel_1_16)
    opt_release_ms = round(max(30.0, min(280.0, (div_ms - cfg["attack_ms"]) * cfg["release_scale"])), 1)

    # Regla anti-Pumper en grooves con swing/síncopa o sin kick
    is_swung = swing_val >= 54.0
    pumper_allowed = bool(has_kick and duck_prof["allow_pumper_straight"] and not is_swung)
    pumper_warning = ""
    if not has_kick or canon_style == "drumless":
        pumper_warning = "Sin kick ancla o estilo drumless: desactivar Pumper y usar compresión bus suave (1.5:1–2.2:1)."
    elif duck_prof["syncopated_or_swung"] or is_swung:
        pumper_warning = (
            f"PROHIBIDO usar Knob FX Pumper en {mix_prof['label']} (swing {swing_val:.0f}% / ritmo sincopado): "
            "el LFO fijo bombea fuera del golpe real. Usar SampQOL Mother Ducker (pre-fader / Ghost Kick) o Melodee Sidechain."
        )

    if not has_kick or canon_style == "drumless":
        recommended_engine = "sampqol_air_compressor_glue" if sampqol_active else "mpc_stock_color_comp_gentle"
    elif sampqol_active:
        recommended_engine = "sampqol_mother_ducker"
    elif pumper_allowed:
        recommended_engine = "mpc_knob_fx_pumper_exclude_kick"
    else:
        recommended_engine = "melodee_sidechain_or_mpc_color_comp"

    # Control de seguridad AK4558: evitar Color=On + In Boost > +6 dB
    cc_in_boost = min(5.0, float(cfg["cc_in_boost_db"]))
    cc_color = bool(cfg["cc_color"])
    if mode == "live_pa" and cc_color and cc_in_boost > 4.0:
        cc_in_boost = 4.0

    # Escala Melodee MasterComp (0..100 log -> 0.1..150ms attack, 3..300ms release)
    mel_atk_val = int(round(max(0.0, min(100.0, 100.0 * math.log(max(0.1, cfg["attack_ms"]) / 0.1) / math.log(1500.0)))))
    mel_rel_val = int(round(max(0.0, min(100.0, 100.0 * math.log(max(3.0, opt_release_ms) / 3.0) / math.log(100.0)))))
    mel_amt_val = int(round(max(10.0, min(85.0, 22.0 + cfg["ratio"] * 5.5)))) if has_kick and canon_style != "drumless" else 20

    targets_desc = []
    if has_bass:
        targets_desc.append("Submix 2 (Bass/808)")
    if has_melodic:
        targets_desc.append("Submix 3 (Melodic/Chops)")
    if not targets_desc:
        targets_desc.append("Pads Melódicos / Bajo")

    return {
        "style_id": canon_style,
        "style_label": mix_prof["label"],
        "bpm": round(bpm_val, 2),
        "mix_mode": mode,
        "release_1_16_ms": rel_1_16,
        "release_1_8_ms": rel_1_8,
        "release_1_32_ms": rel_1_32,
        "optimal_release_ms": opt_release_ms,
        "pumper_allowed": pumper_allowed,
        "pumper_warning": pumper_warning,
        "recommended_engine": recommended_engine,
        "mpc_stock_color_comp": {
            "shortcut": "SHIFT + PAD 5",
            "enabled": True if (mode == "live_pa" or cfg["cc_amount_pct"] >= 15) else False,
            "color": cc_color,
            "attack_ms": round(max(0.1, min(150.0, cfg["attack_ms"] * 1.5)), 1),
            "release_ms": round(max(3.0, min(300.0, opt_release_ms)), 1),
            "amount_pct": int(cfg["cc_amount_pct"]),
            "in_boost_db": cc_in_boost,
            "auto_makeup": True,
            "note": "Auto Make-Up activo en stock; no superar In Boost +4 dB con COLOR On para proteger DAC AK4558.",
        },
        "mpc_knob_fx_pumper": {
            "shortcut": "SHIFT + KNOB FX -> Pumper (apagar pad Kick en FX Select)",
            "allowed": pumper_allowed,
            "speed": cfg["pumper_speed"],
            "shape_pct": int(cfg["pumper_shape_pct"]) if pumper_allowed else 0,
            "depth_pct": int(cfg["pumper_depth_pct"]) if pumper_allowed else 0,
            "attack_pct": 5 if pumper_allowed else 0,
            "hold_pct": 10 if pumper_allowed else 0,
            "release_pct": 35 if pumper_allowed else 0,
            "exclude_pads": ["KICK"],
            "warning": pumper_warning,
        },
        "sampqol_mother_ducker": {
            "shortcut": "PAD FX -> Insert Dynamics -> Mother Ducker Input (Key) / Mother Ducker (Target)",
            "enabled": bool(has_kick and canon_style != "drumless"),
            "bus": 1,
            "key_mode": duck_prof["key_mode"],
            "key_tip": (
                "Ghost Kick en pad dedicado a Vol 0 (pre-fader en SampQOL 0.2.0)"
                if duck_prof["key_mode"] == "ghost_kick_vol0"
                else "Mother Ducker Input directo en pad Kick (pre-fader)"
            ),
            "targets": targets_desc,
            "threshold_db": float(cfg["threshold_db"]),
            "ratio": float(cfg["ratio"]),
            "attack_ms": float(cfg["attack_ms"]),
            "release_ms": opt_release_ms,
            "soft_knee_db": float(cfg["soft_knee_db"]),
            "target_gr_db": cfg["target_gr_db"],
            "auto_makeup": False,
        },
        "melodee_sidechain": {
            "shortcut": "SHIFT + PAD 5 -> B1 SIDECHAIN (elegir pad Kick)",
            "enabled": bool(has_kick and canon_style != "drumless"),
            "key_mode": "kick_pad",
            "attack_knob_0_100": mel_atk_val,
            "attack_ms": float(cfg["attack_ms"]),
            "release_knob_0_100": mel_rel_val,
            "release_ms": opt_release_ms,
            "amount_pct": mel_amt_val,
            "in_boost_db": 0 if mode == "studio_mastering" else 3,
            "color": cc_color,
            "auto_makeup": False,
        },
        "pa_safety_chain": {
            "dac_codec": "AK4558",
            "true_peak_ceiling_dbtp": -1.0,
            "max_allowed_dbtp": -0.8,
            "subsonic_hpf_hz": int(mix_prof["pa_subsonic_hpf_hz"] if mode == "live_pa" else 24),
            "sub_mono_below_hz": int(120 if mode == "live_pa" else mix_prof["sub_mono_hz"]),
            "chop_hpf_hz": int(mix_prof["chop_hpf_hz"]),
            "sampqol_stereo_width_low_pct": 0,
            "soft_clipper": {
                "enabled": mode == "live_pa",
                "shape": cfg["soft_clip_shape"],
                "true_peak": True,
                "post_lvl_db": -1.0,
            },
            "limiter_ceiling_db": -1.0,
            "target_lufs_range": mix_prof["live_pa_lufs_range" if mode == "live_pa" else "studio_lufs_range"],
            "min_crest_db": mix_prof["live_pa_min_crest_db" if mode == "live_pa" else "studio_min_crest_db"],
            "max_bank_lufs_delta_lu": 1.0 if mode == "live_pa" else 1.5,
        },
    }


def analyze_multibank_coherence(
    pad_reports: List[Dict[str, Any]],
    *,
    mix_mode: str = "studio_mastering",
    style_id: str = "standard",
    bpm: float = 90.0,
    sampqol_active: bool = True,
    root_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Auditoría acústica y armónica en 3 niveles: Pad -> Banco (A–H) -> Coherencia Global A–H + Receta Master/Ducking."""
    mode = _normalize_mix_mode(mix_mode)
    canon_style = _resolve_mix_style_id(style_id)
    mix_prof = MIX_PROFILE_MATRICES[canon_style]
    root_path = Path(root_dir) if root_dir else None

    bank_letters = "ABCDEFGH"
    enriched_pads: List[Dict[str, Any]] = []
    by_bank: Dict[str, List[Dict[str, Any]]] = {}

    has_kick = False
    has_bass = False
    has_melodic = False
    sub_mono_risk_pads: List[int] = []
    subsonic_pa_risk_pads: List[int] = []

    for idx, raw_pad in enumerate(pad_reports or []):
        if not isinstance(raw_pad, dict):
            continue
        p = dict(raw_pad)
        pad_num = int(p.get("pad", p.get("pad_number", idx + 1)) or (idx + 1))
        b_idx = max(0, min(7, (pad_num - 1) // 16))
        bank_lbl = str(p.get("bank") or bank_letters[b_idx]).upper()[:1]
        if bank_lbl not in bank_letters:
            bank_lbl = bank_letters[b_idx]

        stype = str(p.get("sound_type") or p.get("role") or detect_sound_type(str(p.get("sample_name") or p.get("name") or ""))).upper()
        if stype == "KICK":
            has_kick = True
        elif stype in ("BASS_808", "BASS"):
            has_bass = True
        elif stype in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL", "CHOP", "LOOP"):
            has_melodic = True

        # Resolver ruta WAV si faltan métricas acústicas
        wav_cand: Optional[Path] = None
        if p.get("source_path") and Path(str(p["source_path"])).is_file():
            wav_cand = Path(str(p["source_path"]))
        elif root_path and p.get("rel_path"):
            cand = root_path / str(p["rel_path"]).lstrip("/")
            if cand.is_file():
                wav_cand = cand

        if wav_cand and ("true_peak_dbtp" not in p or "lufs_active_est" not in p or "subsonic_ratio_35hz" not in p):
            ac = analyze_sample_acoustics(wav_cand)
            if ac.get("valid"):
                for k, v in ac.items():
                    p.setdefault(k, v)

        peak_dbfs = float(p.get("peak_dbfs", -6.0) if p.get("peak_dbfs") is not None else -6.0)
        true_peak = float(p.get("true_peak_dbtp", peak_dbfs) if p.get("true_peak_dbtp") is not None else peak_dbfs)
        rms_dbfs = float(p.get("rms_active_dbfs", p.get("rms_dbfs", -18.0)) if (p.get("rms_active_dbfs") is not None or p.get("rms_dbfs") is not None) else -18.0)
        lufs_est = float(p.get("lufs_active_est", rms_dbfs - 0.69) if p.get("lufs_active_est") is not None else rms_dbfs - 0.69)
        crest_db = float(p.get("crest_factor_db", p.get("crest_db", max(0.0, peak_dbfs - rms_dbfs))))
        sub_ratio = float(p.get("low_energy_ratio", p.get("sub_ratio", 0.0)) or 0.0)
        sub35 = float(p.get("subsonic_ratio_35hz", 0.0) or 0.0)
        low_corr = float(p.get("low_stereo_corr_120hz", p.get("stereo_correlation", 1.0)) if p.get("low_stereo_corr_120hz") is not None else 1.0)
        channels = int(p.get("channels", 1) or 1)
        cur_vol = float(p.get("volume", 0.707946) or 0.707946)
        vol_db = 20.0 * math.log10(max(1e-4, cur_vol))

        # Alertas nivel pad
        alerts: List[str] = list(p.get("alerts") or [])
        if (true_peak >= -0.8 or peak_dbfs >= -0.75) and "clipping_risk" not in alerts:
            alerts.append("clipping_risk")
        if abs(float(p.get("dc_offset", 0.0) or 0.0)) >= 0.015 and "dc_offset" not in alerts:
            alerts.append("dc_offset")
        if 0.0 < crest_db < 7.0 and "overcompressed" not in alerts:
            alerts.append("overcompressed")
        if sub35 >= 0.12:
            if "subsonic_pa_risk" not in alerts:
                alerts.append("subsonic_pa_risk")
            subsonic_pa_risk_pads.append(pad_num)
        if channels >= 2 and low_corr < 0.75 and (sub_ratio >= 0.25 or stype in ("KICK", "BASS_808", "BASS", "MELODIC_LOOP")):
            if "low_stereo_mono_risk" not in alerts:
                alerts.append("low_stereo_mono_risk")
            sub_mono_risk_pads.append(pad_num)

        # Recomendación Studio base (Live se refinará con bank_trim_db tras Nivel 3)
        studio_rec = compute_profiled_pad_volume(
            stype, wav_cand, mix_mode="studio_mastering", style_id=canon_style, bank_trim_db=0.0
        )
        live_rec_init = compute_profiled_pad_volume(
            stype, wav_cand, mix_mode="live_pa", style_id=canon_style, bank_trim_db=0.0
        )

        # Normalizar tonalidad si existe
        key_raw = str(p.get("key") or p.get("musical_key") or "").strip()
        kinfo = parse_musical_key_info(key_raw) if key_raw else None

        p.update({
            "pad": pad_num,
            "bank": bank_lbl,
            "sound_type": stype,
            "peak_dbfs": round(peak_dbfs, 2),
            "true_peak_dbtp": round(true_peak, 2),
            "rms_active_dbfs": round(rms_dbfs, 2),
            "lufs_active_est": round(lufs_est, 2),
            "effective_lufs_at_vol": round(lufs_est + vol_db, 2),
            "crest_factor_db": round(crest_db, 2),
            "sub_ratio": round(sub_ratio, 3),
            "subsonic_ratio_35hz": round(sub35, 4),
            "low_stereo_corr_120hz": round(low_corr, 3),
            "key": kinfo["key"] if kinfo else (key_raw or ""),
            "camelot": kinfo["camelot"] if kinfo else str(p.get("camelot") or ""),
            "alerts": alerts,
            "recommended_volume_studio": studio_rec["volume"],
            "recommended_volume_live": live_rec_init["volume"],
            "_wav_cand": wav_cand,
        })
        enriched_pads.append(p)
        by_bank.setdefault(bank_lbl, []).append(p)

    # --- Nivel 2: Agregación por Banco (A–H) ---
    banks_summary: List[Dict[str, Any]] = []
    bank_lufs_map: Dict[str, float] = {}
    bank_key_map: Dict[str, Dict[str, Any]] = {}

    for b_lbl in [b for b in bank_letters if b in by_bank]:
        bpads = by_bank[b_lbl]
        roles: Dict[str, int] = {}
        key_votes: Dict[str, float] = {}
        rms_vals: List[float] = []
        lufs_vals: List[float] = []
        peaks: List[float] = []
        tpeaks: List[float] = []
        crests: List[float] = []
        subs: List[float] = []

        drum_cnt = 0
        mel_cnt = 0
        bass_cnt = 0
        vox_fx_cnt = 0
        kicks_in_bank = 0
        bass_in_bank = 0
        snares_in_bank = 0
        claps_in_bank = 0

        for bp in bpads:
            st = bp["sound_type"]
            roles[st] = roles.get(st, 0) + 1
            if st in ("KICK", "SNARE", "CLAP", "TOM", "HIHAT", "CYMBAL", "PERCUSSION"):
                drum_cnt += 1
            if st in ("MELODIC_LOOP", "KEYS_SYNTH", "CHOP", "LOOP"):
                mel_cnt += 1
            if st in ("BASS_808", "BASS"):
                bass_cnt += 1
            if st in ("VOCAL", "FX"):
                vox_fx_cnt += 1
            if st == "KICK":
                kicks_in_bank += 1
            if st in ("BASS_808", "BASS"):
                bass_in_bank += 1
            if st == "SNARE":
                snares_in_bank += 1
            if st == "CLAP":
                claps_in_bank += 1

            rms_vals.append(bp["rms_active_dbfs"])
            lufs_vals.append(bp["effective_lufs_at_vol"])
            peaks.append(bp["peak_dbfs"])
            tpeaks.append(bp["true_peak_dbtp"])
            crests.append(bp["crest_factor_db"])
            subs.append(bp["sub_ratio"])

            if bp.get("key"):
                ki = parse_musical_key_info(bp["key"])
                if ki:
                    weight = 2.0 if st in ("MELODIC_LOOP", "KEYS_SYNTH", "BASS_808", "BASS") else 1.0
                    key_votes[ki["key"]] = key_votes.get(ki["key"], 0.0) + weight

        n_b = len(bpads)
        if drum_cnt >= max(mel_cnt, bass_cnt, vox_fx_cnt) and drum_cnt >= n_b * 0.5:
            dom_role = "DRUMS"
        elif mel_cnt >= max(drum_cnt, bass_cnt, vox_fx_cnt) and mel_cnt >= n_b * 0.4:
            dom_role = "CHOPS_MELODIC"
        elif bass_cnt >= max(drum_cnt, mel_cnt, vox_fx_cnt) and bass_cnt >= n_b * 0.4:
            dom_role = "BASS_808"
        elif vox_fx_cnt >= n_b * 0.5:
            dom_role = "VOCALS_FX"
        else:
            dom_role = "MIXED"

        dom_key = "Percussion / Atonal"
        dom_cam = ""
        if key_votes:
            dom_key = max(key_votes.items(), key=lambda kv: kv[1])[0]
            ki_dom = parse_musical_key_info(dom_key)
            if ki_dom:
                dom_cam = ki_dom.get("camelot", "")
                bank_key_map[b_lbl] = ki_dom

        # Sonoridad representativa del banco (promedio energético en dB)
        avg_rms = round(sum(rms_vals) / n_b, 2)
        sorted_lufs = sorted(lufs_vals)
        # Promedio del percentil superior (elementos protagonistas del banco) para no diluir por hats/FX suaves
        top_slice = sorted_lufs[max(0, len(sorted_lufs) // 3):] or sorted_lufs
        bank_lufs_est = round(sum(top_slice) / len(top_slice), 2)
        bank_lufs_map[b_lbl] = bank_lufs_est

        phase_warnings: List[str] = []
        if kicks_in_bank > 0 and bass_in_bank > 0:
            phase_warnings.append(
                f"Banco {b_lbl}: Kick + Bass/808 coexisten — verificar mono <{mix_prof['sub_mono_hz']} Hz y sidechain Mother Ducker."
            )
        if snares_in_bank > 0 and claps_in_bank > 0:
            phase_warnings.append(
                f"Banco {b_lbl}: Snare + Clap activos — micro-offset 5–12 ms en Clap evita cancelación de fase en medios."
            )
        low_corr_bad = [bp["pad"] for bp in bpads if "low_stereo_mono_risk" in bp["alerts"]]
        if low_corr_bad:
            phase_warnings.append(
                f"Banco {b_lbl}: pads {low_corr_bad} con correlación grave <120 Hz baja (riesgo cancelación PA mono)."
            )

        banks_summary.append({
            "bank": b_lbl,
            "pad_count": n_b,
            "dominant_role": dom_role,
            "dominant_key": dom_key,
            "camelot": dom_cam,
            "bank_lufs_est": bank_lufs_est,
            "avg_rms_dbfs": avg_rms,
            "max_peak_dbfs": round(max(peaks), 2),
            "bank_max_true_peak_dbtp": round(max(tpeaks), 2),
            "crest_avg_db": round(sum(crests) / n_b, 2),
            "sub_ratio_avg": round(sum(subs) / n_b, 3),
            "roles": roles,
            "intra_bank_phase_warnings": phase_warnings,
            "bank_trim_db": 0.0,
        })

    # --- Nivel 3: Coherencia Global A–H ---
    active_banks = [b["bank"] for b in banks_summary]
    if bank_lufs_map:
        s_vals = sorted(bank_lufs_map.values())
        mid = len(s_vals) // 2
        median_bank_lufs = round(s_vals[mid] if len(s_vals) % 2 == 1 else 0.5 * (s_vals[mid - 1] + s_vals[mid]), 2)
        bank_rms_spread_db = round(max(s_vals) - min(s_vals), 2) if len(s_vals) > 1 else 0.0
    else:
        median_bank_lufs = -16.0
        bank_rms_spread_db = 0.0

    # Trims por banco (clamp ±3.0 dB) para convergencia ΔLUFS ≤ ±1.0 LU entre bancos A–H
    bank_trims_db: Dict[str, float] = {}
    for b_entry in banks_summary:
        b_lbl = b_entry["bank"]
        delta = median_bank_lufs - b_entry["bank_lufs_est"]
        trim = 0.0 if abs(delta) <= 1.0 else round(max(-3.0, min(3.0, delta)), 2)
        bank_trims_db[b_lbl] = trim
        b_entry["bank_trim_db"] = trim

    # Refinar outliers y recommended_volume_live con bank_trim_db aplicado
    pad_outliers: List[Dict[str, Any]] = []
    for p in enriched_pads:
        b_lbl = p["bank"]
        b_trim = bank_trims_db.get(b_lbl, 0.0)
        wav_cand = p.pop("_wav_cand", None)
        if b_trim != 0.0:
            live_rec = compute_profiled_pad_volume(
                p["sound_type"], wav_cand, mix_mode="live_pa", style_id=canon_style, bank_trim_db=b_trim
            )
            p["recommended_volume_live"] = live_rec["volume"]

        b_entry = next((b for b in banks_summary if b["bank"] == b_lbl), None)
        b_avg_rms = b_entry["avg_rms_dbfs"] if b_entry else p["rms_active_dbfs"]
        rms_dev = abs(p["rms_active_dbfs"] - b_avg_rms)
        is_outlier = bool(rms_dev > 3.5 or p["alerts"])
        p["is_outlier"] = is_outlier
        if is_outlier:
            pad_outliers.append({
                "pad": p["pad"],
                "bank": b_lbl,
                "sample_name": p.get("sample_name") or p.get("name") or f"Pad {p['pad']}",
                "sound_type": p["sound_type"],
                "alerts": list(p["alerts"]),
                "rms_deviation_db": round(rms_dev, 2),
                "true_peak_dbtp": p["true_peak_dbtp"],
                "recommended_volume_studio": p["recommended_volume_studio"],
                "recommended_volume_live": p["recommended_volume_live"],
            })

    # Choques Camelot entre bancos tonales
    camelot_clashes_between_banks: List[Dict[str, Any]] = []
    tonal_banks = sorted(bank_key_map.keys())
    for i in range(len(tonal_banks)):
        for j in range(i + 1, len(tonal_banks)):
            ba, bb = tonal_banks[i], tonal_banks[j]
            ka, kb = bank_key_map[ba], bank_key_map[bb]
            score, lbl = camelot_compatibility_score(ka["key"], kb["key"])
            if score < 0.60:
                semi_fix, target_role = compute_pitch_shift_to_compatible_key(kb["pitch_class"], ka["pitch_class"])
                camelot_clashes_between_banks.append({
                    "bank_a": ba,
                    "key_a": ka["key"],
                    "camelot_a": ka.get("camelot", ""),
                    "bank_b": bb,
                    "key_b": kb["key"],
                    "camelot_b": kb.get("camelot", ""),
                    "score": round(score, 2),
                    "label": lbl,
                    "semitone_fix": semi_fix,
                    "target_relation": target_role,
                })

    ducking_recipe = build_mpc_ducking_recipe(
        style_id=canon_style,
        bpm=bpm,
        mix_mode=mode,
        has_kick=has_kick,
        has_bass=has_bass,
        has_melodic=has_melodic,
        sampqol_active=sampqol_active,
    )

    worst_tp = max((b["bank_max_true_peak_dbtp"] for b in banks_summary), default=-6.0)
    master_bus_plan = {
        "mix_mode": mode,
        "style_id": canon_style,
        "style_label": mix_prof["label"],
        "target_lufs_range": mix_prof["live_pa_lufs_range" if mode == "live_pa" else "studio_lufs_range"],
        "true_peak_ceiling_dbtp": -1.0,
        "max_allowed_dbtp": -0.8,
        "subsonic_hpf_hz": int(mix_prof["pa_subsonic_hpf_hz"] if mode == "live_pa" else 24),
        "sub_mono_below_hz": int(120 if mode == "live_pa" else mix_prof["sub_mono_hz"]),
        "chop_hpf_hz": int(mix_prof["chop_hpf_hz"]),
        "estimated_worst_case_peak_dbtp": round(worst_tp, 2),
        "mixer_volume_xpj": 0.7943282347242815 if mode == "live_pa" else 0.7079457640647888,
        "output_volume_xpj": 0.8912509381337456 if mode == "live_pa" else 0.7079457640647888,
        "bank_uniformity_ok": bool(bank_rms_spread_db <= (2.0 if mode == "live_pa" else 3.0)),
        "recommended_action": (
            "Aplicar trims por banco A–H y techo -1.0 dBTP (Soft Clipper / Limiter) antes del directo PA."
            if mode == "live_pa"
            else "Mantener headroom de bus -6..-3 dBFS, sin brickwall en master y conservar snapshot Studio."
        ),
    }

    global_coherence = {
        "active_banks": active_banks,
        "median_bank_lufs": median_bank_lufs,
        "bank_rms_spread_db": bank_rms_spread_db,
        "bank_trims_db": bank_trims_db,
        "camelot_clashes_between_banks": camelot_clashes_between_banks,
        "sub_mono_risk_pads": sorted(set(sub_mono_risk_pads)),
        "subsonic_pa_risk_pads": sorted(set(subsonic_pa_risk_pads)),
    }

    return {
        "mix_mode": mode,
        "style_id": canon_style,
        "bpm": round(float(bpm or mix_prof["bpm_ref"]), 2),
        "pads": enriched_pads,
        "pad_outliers": pad_outliers,
        "banks_summary": banks_summary,
        "active_banks": active_banks,
        "median_bank_lufs": median_bank_lufs,
        "bank_rms_spread_db": bank_rms_spread_db,
        "bank_trims_db": bank_trims_db,
        "camelot_clashes_between_banks": camelot_clashes_between_banks,
        "sub_mono_risk_pads": sorted(set(sub_mono_risk_pads)),
        "subsonic_pa_risk_pads": sorted(set(subsonic_pa_risk_pads)),
        "global_coherence": global_coherence,
        "master_bus_plan": master_bus_plan,
        "ducking_recipe": ducking_recipe,
    }


def measure_wav_loudness_report(wav_path: str | Path) -> Dict[str, Any]:
    """Mide sonoridad integrada EBU R128 (LUFS-I, True Peak dBTP, LRA) y métricas PA/Studio de un bounce WAV/AIFF/FLAC."""
    p = Path(wav_path).resolve()
    if not p.is_file() or p.suffix.lower() not in (".wav", ".aif", ".aiff", ".flac"):
        raise ValueError("Selecciona un archivo de audio válido (.wav, .aif, .aiff, .flac).")

    ac = analyze_sample_acoustics(p)
    peak_dbfs = float(ac.get("peak_dbfs", -120.0))
    crest_db = float(ac.get("crest_factor_db", 0.0))
    sub35 = float(ac.get("subsonic_ratio_35hz", 0.0))
    low_corr = float(ac.get("low_stereo_corr_120hz", 1.0))

    lufs_i: Optional[float] = None
    tp_dbtp: Optional[float] = None
    lra_lu: Optional[float] = None
    engine = "dsp_bs1770_fallback"

    ff = shutil.which("ffmpeg")
    if ff:
        try:
            run = subprocess.run(
                [
                    ff, "-nostdin", "-hide_banner", "-nostats",
                    "-i", str(p),
                    "-map", "0:a:0",
                    "-af", "loudnorm=print_format=json",
                    "-f", "null", "-",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            match = re.search(r'\{\s*"input_i"[^}]+\}\s*$', run.stderr)
            if run.returncode == 0 and match:
                data = json.loads(match.group())
                raw_i = float(data["input_i"])
                raw_tp = float(data["input_tp"])
                raw_lra = float(data["input_lra"])
                if math.isfinite(raw_i) and raw_i > -90.0:
                    lufs_i = round(raw_i, 2)
                if math.isfinite(raw_tp) and raw_tp > -90.0:
                    tp_dbtp = round(raw_tp, 2)
                if math.isfinite(raw_lra) and raw_lra >= 0.0:
                    lra_lu = round(raw_lra, 2)
                engine = "ffmpeg_ebur128"
        except Exception:
            pass

    if lufs_i is None:
        lufs_i = round(float(ac.get("lufs_active_est", -120.0)), 2)
    if tp_dbtp is None:
        tp_dbtp = round(float(ac.get("true_peak_dbtp", peak_dbfs)), 2)
    if lra_lu is None:
        lra_lu = round(max(0.0, min(20.0, crest_db * 0.45)), 2)

    warnings: List[str] = []
    if tp_dbtp > -0.8:
        warnings.append(f"True Peak {tp_dbtp} dBTP excede el margen anti-ISP del DAC AK4558 (objetivo <= -1.0 dBTP).")
    elif tp_dbtp > -1.0:
        warnings.append(f"True Peak {tp_dbtp} dBTP justo en límite PA (-0.8 dBTP); para pre-mastering bajar a <= -1.0 dBTP.")
    if lufs_i > -7.5:
        warnings.append(f"Sonoridad integrada muy alta ({lufs_i} LUFS): riesgo de aplastamiento dinámico en PA.")
    elif lufs_i < -20.0:
        warnings.append(f"Sonoridad integrada baja ({lufs_i} LUFS): revisar ganancia de bus antes de directo.")
    if 0.0 < crest_db < 6.5:
        warnings.append(f"Crest Factor bajo ({crest_db} dB): transientes muy comprimidos.")
    if sub35 >= 0.12:
        warnings.append(f"Energía subsónica <35 Hz elevada ({round(sub35 * 100, 1)}%): aplicar HPF 30–35 Hz para proteger subwoofers PA.")
    if low_corr < 0.75:
        warnings.append(f"Correlación estéreo <120 Hz baja ({low_corr}): sumar subgraves a mono (AIR Stereo Width Low=0%).")

    studio_ready = bool(tp_dbtp <= -1.0 and -20.0 <= lufs_i <= -12.5 and (crest_db == 0.0 or crest_db >= 8.0))
    live_pa_ready = bool(tp_dbtp <= -0.8 and -12.5 <= lufs_i <= -7.0 and sub35 < 0.15 and low_corr >= 0.70)

    return {
        "lufs_integrated": lufs_i,
        "true_peak_dbtp": tp_dbtp,
        "lra_lu": lra_lu,
        "peak_dbfs": round(peak_dbfs, 2),
        "crest_db": round(crest_db, 2),
        "subsonic_ratio_35hz": round(sub35, 4),
        "low_stereo_corr_120hz": round(low_corr, 3),
        "studio_ready": studio_ready,
        "live_pa_ready": live_pa_ready,
        "warnings": warnings,
        "measurement_engine": engine,
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
        "id": "drumless",
        "style": "Drumless / Micro-Chop Loop (Alchemist Style)",
        "bpm": 78.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "drumless",
        "target_adaptation": "drumless_alchemist",
        "keywords": ["drumless", "alchemist", "griselda", "roc marciano", "micro chop", "microchop"],
    },
    {
        "id": "bolero",
        "style": "Bolero / Canción Melódica → Lo-Fi & Boom Bap",
        "bpm": 84.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "bolero",
        "target_adaptation": "lofi_hiphop",
        "keywords": ["bolero", "requinto", "bolero vals", "balada", "romantica", "romántica", "panchos", "manzanero", "gatica", "jaramillo", "trio romantico", "trío romántico"],
    },
    {
        "id": "bossa_samba",
        "style": "Bossa Nova / Samba-Jazz → Lo-Fi & Jazz-Hop",
        "bpm": 84.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "bossa",
        "target_adaptation": "lofi_hiphop",
        "keywords": ["bossa nova", "bossa", "samba jazz", "mpb", "partido alto", "ipanema", "jobim", "gilberto"],
    },
    {
        "id": "cumbia_son",
        "style": "Son Cubano / Cumbia / Guajira → Latin Boom Bap",
        "bpm": 88.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "cumbia_son",
        "target_adaptation": "boombap_classic",
        "keywords": ["son cubano", "guajira", "guaracha", "montuno", "tumbao", "cumbia", "chicha", "descarga", "clave", "tres cubano"],
    },
    {
        "id": "tango_vals",
        "style": "Tango / Vals Criollo / Milonga → Cinematic Boom Bap",
        "bpm": 82.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "tango",
        "target_adaptation": "lofi_hiphop",
        "keywords": ["tango", "milonga", "bandoneon", "bandoneón", "piazzolla", "vals criollo", "vals peruano"],
    },
    {
        "id": "psych_library",
        "style": "70s Library / Psych Rock / Cinematic → Abstract Boom Bap",
        "bpm": 86.0,
        "mute_profile": "real_drums",
        "crate_digging_style": "psych_library",
        "target_adaptation": "boombap_classic",
        "keywords": ["library music", "psych", "psychedelic", "mellotron", "ostinato", "cinematic", "soundtrack", "italo library", "vintage synth"],
    },
    {
        "id": "oldies",
        "style": "Oldies / Doo-Wop / Lowrider Sweet Soul (12/8) → Lo-Fi & Boom Bap",
        "bpm": 84.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "oldies",
        "target_adaptation": "lofi_hiphop",
        "keywords": ["oldies", "doo wop", "doo-wop", "doowop", "lowrider", "chicano soul", "sweet soul", "50s soul", "60s soul", "girl group", "wall of sound", "12/8", "vintage oldies", "classic oldies"],
    },
    {
        "id": "soul_vintage",
        "style": "Vintage Soul / Motown / Neo-Soul → Boom Bap & Lo-Fi",
        "bpm": 86.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "soul",
        "target_adaptation": "soul_boombap",
        "keywords": ["vintage soul", "northern soul", "philly soul", "motown", "stax", "soul ballad", "slow jam", "soulful", "gospel", "rhodes", "wurlitzer", "wurli", "neo soul", "neosoul", "soul"],
    },
    {
        "id": "rnb_soul",
        "style": "R&B / Neo-Soul",
        "bpm": 92.0,
        "mute_profile": "jazz_funk",
        "keywords": ["trap soul", "trapsoul", "rare vibrations", "r&b", "rnb", "r_b_", "vibes drum"],
    },
    {
        "id": "jazz_hop",
        "style": "Jazz / Bossa Nova / Cool Jazz → Jazz-Hop & Lo-Fi",
        "bpm": 88.0,
        "mute_profile": "jazz_funk",
        "crate_digging_style": "jazz",
        "target_adaptation": "jazz_hiphop",
        "keywords": ["jazz hop", "jazzhop", "jazz lofi", "cool jazz", "latin jazz", "bebop", "hard bop", "jazz waltz", "upright bass", "contrabajo", "double bass", "blue note", "nujabes", "jazz"],
    },
    {
        "id": "funk_jazz",
        "style": "Funk / Jazz / Breaks",
        "bpm": 110.0,
        "mute_profile": "jazz_funk",
        "keywords": ["funk", "disco", "live break", "chopped breaks", "breakbeat", "break"],
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
    """Detecta el estilo musical (incluyendo Bolero, Soul, Jazz, Bossa, Tango, Cumbia/Son y géneros underground) y recomienda BPM y Choke/Mute."""
    extra = ""
    actual_bpm: Optional[float] = None
    if isinstance(bpm, (list, tuple)):
        extra = " " + " ".join(str(x) for x in bpm)
    elif bpm is not None:
        actual_bpm = float(bpm)
    if sample_names:
        extra += " " + " ".join(str(x) for x in sample_names)
    if extra and str(path_or_text).strip():
        primary = detect_musical_style(path_or_text, bpm=actual_bpm, sample_names=None)
        if primary.get("id") != "standard":
            return primary
    raw_low = (str(path_or_text) + extra).lower()
    low_sp = re.sub(r"[_-]+", " ", raw_low)
    low = f"{raw_low} {low_sp}"

    # Casos prioritarios compuestos y adaptaciones de muestreo (Crate-Digging -> Hip-Hop / Lo-Fi)
    has_hiphop_target = any(k in low for k in ["lofi", "lo-fi", "hip hop", "hiphop", "hip-hop", "boom bap", "boombap", "chillhop"])
    if any(k in low for k in ["drumless", "alchemist", "griselda", "roc marciano", "micro chop", "microchop"]):
        return {
            "id": "drumless",
            "style": "Drumless / Micro-Chop Loop (Alchemist Style)",
            "label": "Drumless / Micro-Chop Loop (Alchemist Style)",
            "bpm": float(actual_bpm or 78.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "drumless",
            "target_adaptation": "drumless_alchemist",
        }
    if any(k in low for k in ["bolero", "requinto", "bolero vals", "manzanero", "panchos", "gatica", "jaramillo"]):
        return {
            "id": "bolero",
            "style": "Bolero / Canción Melódica → Hip-Hop & Lo-Fi",
            "label": "Bolero / Canción Melódica → Hip-Hop & Lo-Fi",
            "bpm": float(actual_bpm or 84.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "bolero",
            "target_adaptation": "lofi_hiphop" if has_hiphop_target else "bolero_boombap",
        }
    if "trap soul" in low or "trapsoul" in low:
        return {
            "id": "rnb_soul",
            "style": "Trap Soul / R&B",
            "label": "Trap Soul / R&B",
            "bpm": float(actual_bpm or 92.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "soul",
            "target_adaptation": "trap_soul",
        }
    if "marco polo" in low:
        return {
            "id": "boombap",
            "style": "Boom Bap / East Coast",
            "label": "Boom Bap / East Coast",
            "bpm": float(actual_bpm or 90.0),
            "mute_profile": "real_drums",
            "crate_digging_style": "boombap",
            "target_adaptation": "boombap",
        }
    if "jazz" in low and ("bossa" in low or has_hiphop_target) and "cookin soul" not in low:
        return {
            "id": "jazz_hop",
            "style": "Jazz / Bossa → Hip-Hop & Lo-Fi",
            "label": "Jazz / Bossa → Hip-Hop & Lo-Fi",
            "bpm": float(actual_bpm or 86.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "jazz",
            "target_adaptation": "jazz_hiphop",
        }
    if any(k in low for k in ["bossa nova", "bossa", "samba jazz", "mpb", "partido alto", "ipanema", "jobim", "gilberto"]):
        return {
            "id": "bossa_samba",
            "style": "Bossa Nova / Samba-Jazz → Lo-Fi & Jazz-Hop",
            "label": "Bossa Nova / Samba-Jazz → Lo-Fi & Jazz-Hop",
            "bpm": float(actual_bpm or 84.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "bossa",
            "target_adaptation": "lofi_hiphop",
        }
    if any(k in low for k in ["son cubano", "guajira", "guaracha", "montuno", "tumbao", "cumbia", "chicha", "descarga", "tres cubano"]):
        return {
            "id": "cumbia_son",
            "style": "Son Cubano / Cumbia / Guajira → Latin Boom Bap",
            "label": "Son Cubano / Cumbia / Guajira → Latin Boom Bap",
            "bpm": float(actual_bpm or 88.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "cumbia_son",
            "target_adaptation": "boombap_classic",
        }
    if any(k in low for k in ["tango", "milonga", "bandoneon", "bandoneón", "piazzolla", "vals criollo", "vals peruano"]):
        return {
            "id": "tango_vals",
            "style": "Tango / Vals Criollo / Milonga → Cinematic Boom Bap",
            "label": "Tango / Vals Criollo / Milonga → Cinematic Boom Bap",
            "bpm": float(actual_bpm or 82.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "tango",
            "target_adaptation": "lofi_hiphop",
        }
    if any(k in low for k in ["oldies", "doo wop", "doo-wop", "doowop", "lowrider", "chicano soul", "sweet soul", "50s soul", "60s soul", "girl group", "wall of sound", "12/8"]):
        return {
            "id": "oldies",
            "style": "Oldies / Doo-Wop / Lowrider Sweet Soul (12/8) → Lo-Fi & Boom Bap",
            "label": "Oldies / Doo-Wop / Lowrider Sweet Soul (12/8) → Lo-Fi & Boom Bap",
            "bpm": float(actual_bpm or 84.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "oldies",
            "target_adaptation": "lofi_hiphop",
        }
    if (
        any(k in low for k in ["soul", "motown", "stax", "rhodes", "wurlitzer", "wurli", "neo soul", "neosoul"])
        and "cookin soul" not in low
        and (has_hiphop_target or any(k in low for k in ["vintage", "motown", "ballad", "slow jam", "gospel", "rhodes", "wurlitzer", "neo soul"]))
    ):
        return {
            "id": "soul_vintage",
            "style": "Soul / Neo-Soul → Hip-Hop & Lo-Fi",
            "label": "Soul / Neo-Soul → Hip-Hop & Lo-Fi",
            "bpm": float(actual_bpm or 86.0),
            "mute_profile": "jazz_funk",
            "crate_digging_style": "soul",
            "target_adaptation": "soul_boombap",
        }

    for rule in UNDERGROUND_GENRE_RULES:
        if any(k in low for k in rule["keywords"]):
            return {
                "id": rule["id"],
                "style": rule["style"],
                "label": rule["style"],
                "bpm": float(actual_bpm) if actual_bpm else float(rule["bpm"]),
                "mute_profile": rule["mute_profile"],
                "crate_digging_style": rule.get("crate_digging_style", ""),
                "target_adaptation": rule.get("target_adaptation", ""),
            }
    if actual_bpm:
        b = float(actual_bpm)
        if 64 <= b < 80:
            return {"id": "lofi", "style": "Slow Soul / Bolero / Lo-Fi Chill", "label": "Slow Soul / Bolero / Lo-Fi Chill", "bpm": b, "mute_profile": "jazz_funk", "crate_digging_style": "lofi", "target_adaptation": "lofi_hiphop"}
        if 80 <= b <= 96:
            return {"id": "boombap", "style": "Boom Bap / Hip-Hop", "label": "Boom Bap / Hip-Hop", "bpm": b, "mute_profile": "real_drums", "crate_digging_style": "boombap", "target_adaptation": "boombap"}
        if 127 <= b <= 135:
            return {"id": "uk_garage", "style": "UK Garage / 2-Step / Baile Funk", "label": "UK Garage / 2-Step / Baile Funk", "bpm": b, "mute_profile": "real_drums", "crate_digging_style": "", "target_adaptation": ""}
        if 138 <= b <= 146:
            return {"id": "drill", "style": "Drill / Grime / Dubstep / Trap 140", "label": "Drill / Grime / Dubstep / Trap 140", "bpm": b, "mute_profile": "club_clean", "crate_digging_style": "", "target_adaptation": ""}
        if 158 <= b <= 168:
            return {"id": "jungle_footwork", "style": "Jungle / Footwork", "label": "Jungle / Footwork", "bpm": b, "mute_profile": "real_drums", "crate_digging_style": "", "target_adaptation": ""}
        if b >= 169:
            return {"id": "dnb", "style": "Drum & Bass", "label": "Drum & Bass", "bpm": b, "mute_profile": "real_drums", "crate_digging_style": "", "target_adaptation": ""}
    return {"id": "standard", "style": "Hip-Hop / Electrónica", "label": "Hip-Hop / Electrónica", "bpm": float(actual_bpm or 120.0), "mute_profile": "real_drums", "crate_digging_style": "", "target_adaptation": ""}


_STYLE_RULE_BY_ID: Dict[str, Dict[str, Any]] = {r["id"]: r for r in UNDERGROUND_GENRE_RULES}
_SHORT_BOUNDARY_KEYWORDS = {
    "drill", "trap", "soul", "jazz", "funk", "afro", "club", "lofi", "break", "808",
    "house", "dnb", "grime", "eski", "juke", "ukg", "rnb", "edm", "bossa", "tango",
    "psych", "vals", "mpb", "juls", "decap", "wiley", "rinse", "clave", "premo", "dilla",
}
_SLOW_MID_GENRE_IDS = {
    "lofi", "boombap", "jazz_hop", "drumless", "soul_vintage", "oldies",
    "bolero", "bossa_samba", "cumbia_son", "tango_vals", "rnb_soul", "psych_library",
}
_FAST_CLUB_GENRE_IDS = {"drill", "grime", "dubstep", "dnb", "jungle_footwork", "house_techno", "baile_funk", "uk_garage"}
_SUB_DRIVEN_GENRE_IDS = {"drill", "trap", "dubstep", "baile_funk"}
_WARM_VINTAGE_GENRE_IDS = {"lofi", "boombap", "jazz_hop", "oldies", "bolero", "soul_vintage", "drumless", "bossa_samba", "tango_vals", "psych_library"}
_SWING_ORGANIC_GENRE_IDS = {"lofi", "jazz_hop", "boombap", "drumless", "soul_vintage", "oldies", "bolero", "bossa_samba", "rnb_soul", "funk_jazz"}


def _style_keyword_hit(norm_text: str, kw: str) -> bool:
    kw_low = kw.lower().strip()
    if not kw_low:
        return False
    if kw_low in _SHORT_BOUNDARY_KEYWORDS or len(kw_low) <= 4:
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(kw_low) + r"(?![a-z0-9])", norm_text))
    return kw_low in norm_text


def _normalize_style_text(text: str) -> str:
    raw = str(text or "").lower()
    sp = re.sub(r"[_\-\./\(\)\[\]]+", " ", raw)
    return f" {raw} {sp} "


def detect_kit_style_weighted(
    kit_name: str = "",
    pad_reports: Optional[List[Dict[str, Any]]] = None,
    *,
    bpm: Optional[float] = None,
    sub_heavy_count: int = 0,
    rhythm_analysis: Optional[Dict[str, Any]] = None,
    fallback_text: str = "",
) -> Dict[str, Any]:
    """
    Clasificador multimodal ponderado de estilo musical para kits completos:
      - Prioriza muestras melódicas/armónicas principales (KEYS_SYNTH, MELODIC_LOOP, VOCAL, STEM, >=1.2s) con peso 5.0x–6.5x.
      - Pondera el consenso de drums/one-shots evitando que 1 hi-hat aislado (ej. Ocean_Drill) secuestre un kit Lo-Fi/Boom Bap.
      - Cruza coherencia DSP real: BPM efectivo, timbre espectral PCM (Sub/Mid/Air), conteo de subs 808 y Swing/Rubato.
      - Devuelve confianza calibrada (0.55–0.97), estilos secundarios compatibles y evidencia explicable.
    """
    scores: Dict[str, float] = {r["id"]: 0.0 for r in UNDERGROUND_GENRE_RULES}
    lexical_scores: Dict[str, float] = {r["id"]: 0.0 for r in UNDERGROUND_GENRE_RULES}
    utility_accum: Dict[str, float] = {r["id"]: 0.0 for r in UNDERGROUND_GENRE_RULES}
    reasons: Dict[str, List[str]] = {r["id"]: [] for r in UNDERGROUND_GENRE_RULES}
    melodic_anchors: List[Tuple[int, float, str]] = []

    def _add_lexical(text: str, weight: float, source_tag: str, *, is_utility: bool = False, is_melodic: bool = False, is_bass_dry: bool = False) -> None:
        norm = _normalize_style_text(text)
        if not norm.strip():
            return
        # Evitar que "cookin soul" dispare soul_vintage en lugar de boombap
        has_cookin = "cookin soul" in norm
        for rule in UNDERGROUND_GENRE_RULES:
            rid = rule["id"]
            if rid == "soul_vintage" and has_cookin:
                continue
            matched_kws = [kw for kw in rule["keywords"] if _style_keyword_hit(norm, kw)]
            if not matched_kws:
                continue
            # Un único tag genérico "808" en un bajo sin sub-cola larga no debe forzar Trap moderno
            if rid == "trap" and matched_kws == ["808"] and is_bass_dry:
                eff_w = min(0.4, weight * 0.3)
            else:
                # Bonus por frases multi-palabra más específicas (ej. "lo-fi", "boom bap", "uk drill")
                specificity = 1.2 if any((" " in kw or "-" in kw) for kw in matched_kws) else 1.0
                eff_w = weight * specificity
            if is_utility:
                room = max(0.0, 1.6 - utility_accum[rid])
                eff_w = min(eff_w, room)
                utility_accum[rid] += eff_w
            if eff_w > 0.0:
                scores[rid] += eff_w
                lexical_scores[rid] += eff_w
                if len(reasons[rid]) < 4:
                    reasons[rid].append(f"{source_tag} ({matched_kws[0]})")

        # Señales armónicas/tímbricas en muestras melódicas principales (Piano/Rhodes/Guitar/Chord + Lo-Fi/Jazz/BoomBap)
        if is_melodic:
            has_lofi_cue = any(k in norm for k in ("lofi", "lo fi", "lo-fi", "chillhop", "dusty", "vinyl", "tape"))
            has_jazz_keys = any(k in norm for k in ("piano", "rhodes", "wurlitzer", "wurli", "epiano", "sax", "trumpet", "horn", "upright", "chord", "jazz"))
            has_mpc_vintage = any(k in norm for k in ("mpc3k", "mpc2000", "sp1200", "sp404", "classic", "vintage", "oldschool"))
            if has_lofi_cue and has_jazz_keys:
                scores["lofi"] += 2.2
                lexical_scores["lofi"] += 2.2
                scores["jazz_hop"] += 2.6
                lexical_scores["jazz_hop"] += 2.6
                if len(reasons["jazz_hop"]) < 4:
                    reasons["jazz_hop"].append(f"{source_tag} (piano/keys lo-fi)")
            elif has_jazz_keys:
                scores["jazz_hop"] += 1.4
                lexical_scores["jazz_hop"] += 1.4
                scores["lofi"] += 1.0
                lexical_scores["lofi"] += 1.0
            if has_mpc_vintage:
                scores["boombap"] += 1.2
                lexical_scores["boombap"] += 1.2
        elif any(k in norm for k in ("mpc3k", "mpc2000", "sp1200", "sp 1200")):
            scores["boombap"] += 0.9
            lexical_scores["boombap"] += 0.9

    # 1) Nombre del kit (peso alto si contiene género explícito, ignorando genéricos)
    if kit_name:
        _add_lexical(kit_name, 3.5, "nombre del kit")

    # 2) Votación ponderada por rol musical de cada pad
    pads = pad_reports or []
    for pr in pads:
        if not isinstance(pr, dict):
            continue
        sname = str(pr.get("sample_name") or "").strip()
        rel_p = str(pr.get("rel_path") or "").strip()
        # Evitar doble peso del nombre de expansión en cada pad: usar solo nombre de muestra + carpeta inmediata
        parent_hint = Path(rel_p).parent.name if rel_p else ""
        if parent_hint.endswith("_[ProjectData]") or parent_hint == kit_name:
            parent_hint = ""
        pad_text = f"{sname} {parent_hint}".strip()
        if not pad_text:
            continue

        stype = str(pr.get("sound_type") or "").upper()
        arole = str(pr.get("acoustic_role") or stype).upper()
        dur = float(pr.get("duration_sec") or 0.0)
        low_r = float(pr.get("low_energy_ratio") or 0.0)

        is_melodic_pad = stype in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL", "STEM") or (
            dur >= 1.2 and stype not in ("KICK", "SNARE", "CLAP", "HIHAT", "CYMBAL", "TOM", "DRUM_LOOP", "FX")
        )
        if is_melodic_pad:
            mel_w = 5.0 + (1.5 if (dur >= 1.8 or stype in ("MELODIC_LOOP", "KEYS_SYNTH")) else 0.0)
            mel_prio = 2 if stype in ("KEYS_SYNTH", "MELODIC_LOOP") else 1
            melodic_anchors.append((mel_prio, dur, sname or Path(rel_p).stem))
            _add_lexical(pad_text, mel_w, f"sample principal PAD {pr.get('pad', '?')}", is_melodic=True)
        elif stype == "DRUM_LOOP":
            _add_lexical(pad_text, 2.5, f"drum loop PAD {pr.get('pad', '?')}")
        elif stype == "BASS_808" or arole == "BASS_808":
            is_dry_bass = (sub_heavy_count == 0 and low_r < 0.62)
            _add_lexical(pad_text, 1.5, f"bajo PAD {pr.get('pad', '?')}", is_bass_dry=is_dry_bass)
        elif stype in ("KICK", "SNARE", "CLAP"):
            _add_lexical(pad_text, 1.25, f"drum PAD {pr.get('pad', '?')}")
        else:
            _add_lexical(pad_text, 0.65, f"percusión/hat PAD {pr.get('pad', '?')}", is_utility=True)

    # 3) Coherencia DSP real (BPM efectivo, timbre PCM, conteo sub-808, swing/rubato)
    ra = rhythm_analysis if isinstance(rhythm_analysis, dict) else {}
    eff_bpm: Optional[float] = None
    for cand_b in (ra.get("effective_source_bpm"), ra.get("source_bpm"), bpm):
        if cand_b is not None:
            try:
                fb = float(cand_b)
                if 50.0 <= fb <= 200.0 and abs(fb - 120.0) > 0.25:
                    eff_bpm = fb
                    break
            except (TypeError, ValueError):
                pass
    if eff_bpm is None and bpm is not None:
        try:
            fb = float(bpm)
            if 50.0 <= fb <= 200.0:
                eff_bpm = fb
        except (TypeError, ValueError):
            eff_bpm = None

    evidence_dsp: List[str] = []
    if eff_bpm is not None:
        if 66.0 <= eff_bpm <= 98.0:
            evidence_dsp.append(f"tempo {eff_bpm:.0f} BPM (rango Hip-Hop/Lo-Fi/Boom Bap)")
            for rid in _SLOW_MID_GENRE_IDS:
                if rid in scores:
                    scores[rid] += 2.2 if lexical_scores[rid] > 0 else 0.9
            for rid in _FAST_CLUB_GENRE_IDS:
                if rid in scores:
                    scores[rid] -= 2.8
            # Afinación fina dentro de 66-98 BPM
            if 70.0 <= eff_bpm <= 87.0:
                scores["lofi"] += 0.6
                scores["jazz_hop"] += 0.5
                scores["drumless"] += 0.4
            elif 86.0 <= eff_bpm <= 96.0:
                scores["boombap"] += 0.6
                scores["lofi"] += 0.4
                scores["jazz_hop"] += 0.4
        elif 135.0 <= eff_bpm <= 148.0:
            evidence_dsp.append(f"tempo {eff_bpm:.0f} BPM (rango Drill/Trap/140)")
            for rid in ("drill", "trap", "grime", "dubstep"):
                scores[rid] += 2.0 if lexical_scores[rid] > 0 else 0.8
            for rid in ("lofi", "drumless", "bolero", "oldies"):
                scores[rid] -= 1.6
        elif 160.0 <= eff_bpm <= 182.0:
            evidence_dsp.append(f"tempo {eff_bpm:.0f} BPM (rango DnB/Jungle)")
            for rid in ("dnb", "jungle_footwork"):
                scores[rid] += 2.5 if lexical_scores[rid] > 0 else 1.2
        elif 118.0 <= eff_bpm <= 135.0:
            evidence_dsp.append(f"tempo {eff_bpm:.0f} BPM (rango House/Garage)")
            for rid in ("house_techno", "uk_garage", "baile_funk"):
                scores[rid] += 1.6 if lexical_scores[rid] > 0 else 0.7

    timbre_prof = str(ra.get("timbre_profile") or "")
    sub_ratio = float(ra.get("sub_energy_ratio") or 0.0)
    mid_ratio = float(ra.get("mid_warmth_ratio") or 0.0)
    if timbre_prof == "vintage_oldies" or (mid_ratio >= 0.65 and sub_ratio <= 0.18):
        evidence_dsp.append("timbre cálido vintage (medios dominantes, bajo sub)")
        for rid in _WARM_VINTAGE_GENRE_IDS:
            if rid in scores:
                scores[rid] += 2.2 if lexical_scores[rid] > 0 else 0.7
        for rid in ("drill", "trap", "dubstep", "dnb", "house_techno"):
            scores[rid] -= 2.2
    elif timbre_prof == "sub_heavy_modern" or sub_ratio >= 0.35:
        evidence_dsp.append("timbre moderno sub-grave")
        for rid in _SUB_DRIVEN_GENRE_IDS:
            scores[rid] += 1.8 if lexical_scores[rid] > 0 else 0.6

    if sub_heavy_count == 0:
        evidence_dsp.append("0 pads sub-808 pesados")
        for rid in _SUB_DRIVEN_GENRE_IDS:
            scores[rid] -= 2.2
    elif sub_heavy_count >= 2:
        evidence_dsp.append(f"{sub_heavy_count} pads sub-808 pesados")
        for rid in ("drill", "trap", "dubstep", "baile_funk", "amapiano"):
            scores[rid] += 1.8 if lexical_scores[rid] > 0 else 0.6

    swing_pct = float(ra.get("swing_pct") or 50.0)
    rubato_idx = float(ra.get("rubato_index") or 0.0)
    if swing_pct >= 56.0 or rubato_idx >= 0.25:
        evidence_dsp.append(f"swing {swing_pct:.1f}% / rubato {rubato_idx:.2f}")
        for rid in _SWING_ORGANIC_GENRE_IDS:
            if rid in scores:
                scores[rid] += 1.8 if lexical_scores[rid] > 0 else 0.6
        for rid in ("drill", "house_techno", "dnb"):
            scores[rid] -= 1.4

    ranked = sorted(scores.items(), key=lambda kv: (kv[1], lexical_scores[kv[0]]), reverse=True)
    best_id, best_score = ranked[0]
    second_id, second_score = ranked[1] if len(ranked) > 1 else ("standard", 0.0)

    if best_score < 1.2:
        fb = detect_musical_style(kit_name or fallback_text, bpm=eff_bpm)
        fb["confidence"] = 0.62 if fb.get("id") != "standard" else 0.55
        fb["secondary_styles"] = []
        fb["style_evidence"] = "Clasificación por respaldo heurístico (sin muestra melódica dominante)"
        return fb

    rule = _STYLE_RULE_BY_ID[best_id]
    margin = max(0.0, best_score - max(0.0, second_score))
    norm_strength = min(1.0, best_score / 12.0)
    margin_factor = min(1.0, margin / 4.5)
    confidence = round(min(0.97, max(0.58, 0.58 + 0.24 * norm_strength + 0.15 * margin_factor)), 2)

    # Top 3 estilos alternativos compatibles con puntuación positiva
    secondary: List[Dict[str, Any]] = []
    for alt_id, alt_sc in ranked[1:]:
        if alt_sc < 1.0 or len(secondary) >= 3:
            continue
        alt_rule = _STYLE_RULE_BY_ID[alt_id]
        secondary.append({
            "id": alt_id,
            "style": alt_rule["style"],
            "bpm": float(alt_rule["bpm"]),
            "score": round(alt_sc, 2),
        })

    ev_parts: List[str] = []
    if melodic_anchors:
        melodic_anchors.sort(key=lambda t: (t[0], t[1]), reverse=True)
        ev_parts.append(f"ancla melódica: {melodic_anchors[0][2][:42]}")
    if reasons[best_id]:
        ev_parts.append("pistas: " + ", ".join(reasons[best_id][:2]))
    if evidence_dsp:
        ev_parts.append("DSP: " + ", ".join(evidence_dsp[:3]))

    out = {
        "id": best_id,
        "style": rule["style"],
        "label": rule["style"],
        "bpm": float(eff_bpm) if eff_bpm else float(rule["bpm"]),
        "mute_profile": rule["mute_profile"],
        "crate_digging_style": rule.get("crate_digging_style", ""),
        "target_adaptation": rule.get("target_adaptation", ""),
        "confidence": confidence,
        "score": round(best_score, 2),
        "secondary_styles": secondary,
        "style_evidence": " · ".join(ev_parts) if ev_parts else "Consenso ponderado de pads y acústica DSP",
    }
    return out


def infer_kit_bpm(path_or_name: str | Path, fallback: float = 120.0) -> float:
    """Infiere el BPM real de un kit o proyecto por nombre explícito, muestras internas o estilo/artista."""
    full_str = str(path_or_name)
    low = full_str.lower()
    p: Optional[Path] = None
    is_existing_path = False
    if "\n" not in full_str and len(full_str) <= 1024:
        try:
            cand_p = Path(full_str)
            if all(len(part.encode("utf-8", errors="ignore")) <= 255 for part in cand_p.parts):
                is_existing_path = cand_p.exists()
                p = cand_p
        except OSError:
            is_existing_path = False
    stem = p.stem if p is not None else Path(full_str[:240]).stem

    m = re.search(r"(?:^|[\s_-])(6\d|[7-9]\d|1[0-8]\d)\s*bpm(?![a-z])", stem, re.I)
    if not m:
        m = re.search(r"(?:^|[\s_\-/])(6\d|[7-9]\d|1[0-8]\d)\s*bpm(?![a-z])", full_str, re.I)
    if m:
        return float(m.group(1))
    m_brack = re.search(r"\[(\d{2,3}(?:\.\d+)?)\]", stem) or re.search(r"\[(\d{2,3}(?:\.\d+)?)\]", full_str)
    if m_brack:
        b_val = float(m_brack.group(1))
        if 55.0 <= b_val <= 200.0:
            return b_val
    m2 = re.search(r"[\s_-](6\d|[7-9]\d|1[0-8]\d)$", stem)
    if m2 and int(m2.group(1)) not in (808, 909, 303, 140):
        return float(m2.group(1))

    if p is not None:
        try:
            proj_cand = p.parent / f"{stem}_[ProjectData]"
            if proj_cand.is_dir():
                search_dir = proj_cand
            elif is_existing_path:
                search_dir = p if p.is_dir() else p.parent
            else:
                search_dir = None
            if search_dir is not None and search_dir.is_dir():
                brack_votes: List[float] = []
                explicit_votes: List[float] = []
                for w in sorted(search_dir.glob("*.[wW][aA][vV]")):
                    if w.name.startswith("._"):
                        continue
                    for mb in re.finditer(r"\[(\d{2,3}(?:\.\d+)?)\]", w.stem):
                        bv = float(mb.group(1))
                        if 55.0 <= bv <= 200.0:
                            brack_votes.append(round(bv, 2))
                    mw = re.search(r"(?:^|[\s_-])(6\d|[7-9]\d|1[0-8]\d)\s*bpm(?![a-z])", w.stem, re.I)
                    if not mw:
                        mw = re.search(r"bpm_[a-z0-9_]*?_(6\d|[7-9]\d|1[0-8]\d)_", w.stem, re.I)
                    if mw:
                        val = float(mw.group(1))
                        if 55.0 <= val <= 200.0:
                            explicit_votes.append(val)
                if brack_votes:
                    return float(Counter(brack_votes).most_common(1)[0][0])
                if explicit_votes:
                    return float(Counter(explicit_votes).most_common(1)[0][0])
        except OSError:
            pass

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
    if any(k in low for k in ["oldies", "doo wop", "doo-wop", "doowop", "lowrider", "chicano soul", "sweet soul", "12/8"]):
        return 84.0
    if any(k in low for k in ["bolero", "requinto", "trío romántico", "trio romantico", "trio los panchos"]):
        return 84.0
    if any(k in low for k in ["tango", "bandoneon", "bandoneón", "vals criollo", "vals", "waltz", "valse", "milonga", "3/4"]):
        return 82.0
    if any(k in low for k in ["drumless", "alchemist", "roc marciano", "griselda", "conductor williams", "abstract loop"]):
        return 78.0
    if any(k in low for k in ["lofi faded", "very sick beats", "lofi", "lo-fi", "chillhop"]):
        return 90.0 if "marco polo" in low else 84.0
    if any(k in low for k in ["cookin soul", "marco polo", "just blaze", "ocean boom bap", "boombap", "boom bap", "bodega", "deli drum", "east coast", "borough chops", "backyard jams"]):
        return 90.0
    if any(k in low for k in ["jazz hop", "jazzhop", "jazz lofi", "blue note", "cool jazz", "nujabes"]) or ("jazz" in low and "bossa" in low):
        return 86.0
    if any(k in low for k in ["bossa", "bossa nova", "samba", "mpb", "jobim", "tropicalia", "joao gilberto"]):
        return 84.0
    if any(k in low for k in ["cumbia", "son cubano", "guajira", "chicha", "descarga", "salsa vintage", "mambo", "boogaloo"]):
        return 88.0
    if any(k in low for k in ["library music", "kpm", "de wolfe", "psych", "giallo", "ennio", "morricone", "mellotron", "soundtrack", "score"]):
        return 86.0
    if any(k in low for k in ["juls", "afrobeats", "afro"]):
        return 102.0
    if any(k in low for k in ["moombahton", "reggaeton", "reggaetón", "dembow", "dancehall", "latin", "island"]):
        return 100.0
    if any(k in low for k in ["rare vibrations", "r&b", "rnb", "r_b_", "soul", "vibes drum", "motown", "rhodes", "wurlitzer"]):
        return 86.0 if any(k in low for k in ["vintage", "motown", "ballad", "lofi"]) else 92.0
    if any(k in low for k in ["jazz", "funk", "disco", "live break", "chopped breaks", "break"]):
        return 88.0 if "jazz" in low and "funk" not in low else 110.0
    if any(k in low for k in ["aquarius earth", "deephouse", "deep house", "futurehouse", "future house", "house", "edm", "club", "tech"]):
        return 122.0 if "aquarius earth" in low else 124.0
    if "rhythm lab" in low or "amen break" in low:
        return 172.0
    if "test press" in low:
        return 174.0
    if "dubbed vocals" in low:
        return 140.0
    if "zenhiser" in low and ("lofi" in low or "lo-fi" in low):
        return 82.0
    if "araabmuzik" in low:
        return 134.0
    if "80s nostalgia" in low or "80's nostaligia" in low:
        return 110.0
    if "classic drum machines" in low or "samples from mars" in low:
        return 120.0
    if any(k in low for k in ["scott storch", "real horns", "serato studio", "vocal destiny"]):
        return 96.0
    if any(k in low for k in ["dj khalil", "borough chops", "backyard jams"]):
        return 90.0
    if "f9 instruments" in low:
        return 118.0
    if "artist signature kits" in low:
        return 92.0
    if any(k in low for k in ["astro1deep", "boombap", "hiphop", "hip-hop"]):
        return 90.0
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

    def usable(candidate: Path) -> bool:
        try:
            return (
                not candidate.name.startswith("._")
                and candidate.is_file()
                and candidate.resolve().is_relative_to(root)
            )
        except OSError:
            return False

    exact = [reference] if reference.is_absolute() else [d / reference for d in directories] + [root / reference]
    for candidate in exact:
        if usable(candidate):
            return candidate.resolve(), candidate.resolve().relative_to(root).as_posix()
        try:
            parent_dir = candidate.parent
            if parent_dir.is_dir() and parent_dir.resolve().is_relative_to(root):
                target_low = candidate.name.lower()
                for child in parent_dir.iterdir():
                    if child.name.lower() == target_low and usable(child):
                        return child.resolve(), child.resolve().relative_to(root).as_posix()
        except OSError:
            pass

    # Basename fallback must be unique within the highest-priority search directory.
    name = reference.name
    for directory in directories:
        dir_is_proj_data = directory.name.endswith(("_[ProjectData]", "_ProjectData"))
        for normalized in (False, True):
            matches = set()
            for candidate in directory.rglob('*'):
                if (candidate.name == name if not normalized else _normalize_name(candidate.name) == _normalize_name(name)) and usable(candidate):
                    matches.add(candidate.resolve())
            if len(matches) == 1:
                match = matches.pop()
                return match, match.relative_to(root).as_posix()
            if len(matches) > 1 and not dir_is_proj_data:
                non_proj_matches = {
                    m for m in matches
                    if not any(pt.endswith(("_[ProjectData]", "_ProjectData")) for pt in m.relative_to(directory).parts)
                }
                if len(non_proj_matches) == 1:
                    match = non_proj_matches.pop()
                    return match, match.relative_to(root).as_posix()
            if matches:
                return None, ''
    return None, ''


def parse_xpm_program(xpm_path: str | Path, source_root: Optional[str | Path] = None) -> dict:
    """
    Extrae instrumentos, samples vinculados, volumen, pan y afinación de un .xpm de MPC,
    resolviendo las rutas relativas exactas a las muestras de audio en disco.
    """
    xpm_p = Path(xpm_path).resolve()
    root_p = (Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else xpm_p.parent
    )).resolve()

    tree = ET.parse(str(xpm_p))
    root = tree.getroot()
    prog_elem = root.find("Program")
    prog_name = (
        prog_elem.findtext("ProgramName", xpm_p.stem)
        if prog_elem is not None
        else xpm_p.stem
    )
    prog_type = prog_elem.get("type", "Drum") if prog_elem is not None else "Drum"

    # Directorios de búsqueda para muestras (priorizando [ProjectData] propio antes de la expansión)
    search_dirs: List[Path] = []
    data_dir = _resolve_project_data_dir(xpm_p)
    if data_dir and data_dir.is_dir():
        search_dirs.append(data_dir)
    if xpm_p.parent.is_dir():
        search_dirs.append(xpm_p.parent)
    # Si está dentro de una expansión, agregar la raíz de la expansión
    for parent_cand in xpm_p.parents:
        if parent_cand.parent.name == "Expansions" or (parent_cand / "Expansion.xml").is_file():
            if parent_cand not in search_dirs:
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
        tune_fine = int(inst.findtext("TuneFine", "0") or 0)
        one_shot_txt = (inst.findtext("OneShot", "True") or "True").strip().lower()
        trigger_mode = "oneshot" if one_shot_txt != "false" else "noteon"
        mono_txt = (inst.findtext("Mono", "True") or "True").strip().lower()
        monophonic = mono_txt != "false"
        simult1 = int(inst.findtext("SimultTarget1", "0") or 0)
        pad_link = (simult1 - 35) if 36 <= simult1 <= 51 else 0
        submix = 0
        route_el = inst.find("AudioRoute")
        if route_el is not None:
            ar_type = int(route_el.findtext("AudioRoute", "0") or 0)
            ar_sub = int(route_el.findtext("AudioRouteSubIndex", "0") or 0)
            if ar_type == 1:
                submix = ar_sub + 1

        sample_name = ""
        sample_file = ""
        first_layer = None
        layers = [layer for layer in inst.findall(".//Layer") if layer.findtext("Active", "True").lower() != "false" and (layer.findtext("SampleName") or layer.findtext("SampleFile"))]
        for layer in layers:
            sn = layer.findtext("SampleName", "")
            sf = layer.findtext("SampleFile", "")
            # Spaces are part of the filename; only discard whitespace-only fields.
            sn = sn if sn.strip() else ""
            sf = sf if sf.strip() else ""
            if sf or sn:
                sample_name = sn
                sample_file = sf
                first_layer = layer
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
        root_note = int(first_layer.findtext("RootNote", "0") or 0) if first_layer is not None else 0
        key_track = (first_layer.findtext("KeyTrack", "False") or "False").strip().lower() == "true" if first_layer is not None else False
        direction = int(first_layer.findtext("Direction", "0") or 0) if first_layer is not None else 0
        reverse = direction == 1
        loop_mode = 1 if first_layer is not None and (
            (first_layer.findtext("Loop", "False") or "False").strip().lower() == "true"
            or int(first_layer.findtext("SliceLoop", "0") or 0) > 0
        ) else 0

        pads[num] = {
            "pad_number": num,
            "sample_name": actual_stem,
            "sample_file": actual_filename,
            "full_path": str(found_path) if found_path else "",
            "rel_path": rel_path,
            "volume": vol,
            "pan": pan,
            "tune": tune_coarse,
            "fine_tune": tune_fine,
            "trigger_mode": trigger_mode,
            "monophonic": monophonic,
            "root_note": root_note,
            "key_track": key_track,
            "reverse": reverse,
            "loop_mode": loop_mode,
            "pad_link": pad_link,
            "submix": submix,
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
    card_root = (Path(source_root) if source_root else (
        Path("/Volumes/MPCSMPL") if Path("/Volumes/MPCSMPL").is_dir() else Path.cwd()
    )).resolve()
    exp_base = Path(expansions_root).resolve() if expansions_root else card_root / "Expansions"

    cache_key = f"{expansion_name}::{str(card_root)}::{str(exp_base)}"
    if cache_key in _EXPANSION_KITS_CACHE:
        return _EXPANSION_KITS_CACHE[cache_key]

    card_resolved = card_root.resolve()
    rel_candidate = (card_resolved / expansion_name).resolve()
    exp_dir = None
    if rel_candidate.is_relative_to(card_resolved) and rel_candidate.is_dir() and rel_candidate != card_resolved:
        exp_dir = rel_candidate
    elif exp_base.is_dir():
        direct_candidate = (exp_base / expansion_name).resolve()
        if not direct_candidate.is_relative_to(exp_base.resolve()):
            raise ValueError("Expansión fuera de la biblioteca")
        if direct_candidate.is_dir():
            exp_dir = direct_candidate
        else:
            norm_exp = _normalize_name(Path(expansion_name).name)
            for cand in exp_base.iterdir():
                if cand.is_dir() and _normalize_name(cand.name) == norm_exp:
                    exp_dir = cand
                    break

    if not exp_dir or not exp_dir.is_dir():
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
            with open(x, "rb") as xfh:
                if xfh.read(4) == b"RIFF":
                    continue
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
    """Devuelve el número total de frames PCM de un archivo WAV (con fallback RIFF chunk), o 0 si no es válido."""
    if not path_cand:
        return 0
    p = Path(path_cand)
    if not p.is_file():
        return 0
    try:
        with wave.open(str(p), "rb") as wf:
            return int(wf.getnframes() or 0)
    except Exception:
        pass
    try:
        data = p.read_bytes()
        if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return 0
        block_align = 0
        data_size = 0
        offset = 12
        while offset + 8 <= len(data):
            cid = data[offset : offset + 4]
            csize = struct.unpack_from("<I", data, offset + 4)[0]
            bstart = offset + 8
            if cid == b"fmt " and bstart + 16 <= len(data):
                block_align = struct.unpack_from("<H", data, bstart + 12)[0]
            elif cid == b"data":
                data_size = min(csize, len(data) - bstart)
            offset = bstart + csize + (csize & 1)
        if block_align > 0 and data_size > 0:
            return data_size // block_align
    except Exception:
        pass
    return 0


def _resolve_midi_root_note(val: Any, default: int = 0) -> int:
    """Convierte nota textual (ej. 'C3', 'F#2') o número MIDI en entero [0, 127]."""
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return max(0, min(127, int(round(val))))
    text = str(val).strip()
    if not text:
        return default
    if re.fullmatch(r"-?\d+", text):
        return max(0, min(127, int(text)))
    try:
        pc, octv = parse_note(text)
        return max(0, min(127, (octv + 1) * 12 + pc))
    except ValueError:
        return default


def _extract_extended_pad_params(p_info: Dict[str, Any], default_submix: int = 0) -> Dict[str, Any]:
    """Extrae y normaliza los parámetros extendidos de un pad para `.xpm` y `.xpj`."""
    raw_fine = p_info.get("fine_tune", p_info.get("fineTune", 0))
    fine_tune = max(-90, min(90, int(round(float(raw_fine or 0)))))
    trigger_raw = p_info.get("trigger_mode", p_info.get("triggerMode"))
    if trigger_raw is None and "playMode" in p_info:
        trigger_raw = p_info.get("playMode")
    trigger_str = str(trigger_raw or "oneshot").strip().lower()
    is_oneshot = trigger_str not in ("noteon", "note_on", "gate", "2", "false")
    reverse = bool(p_info.get("reverse", False) or int(p_info.get("direction", 0) or 0) == 1)
    loop_mode = 1 if bool(p_info.get("loop", p_info.get("loop_mode", p_info.get("loopMode", 0)))) else 0
    sample_offset = max(0, int(p_info.get("sample_offset", p_info.get("offset", 0)) or 0))
    root_note = _resolve_midi_root_note(p_info.get("root_note", p_info.get("rootNote", 0)), default=0)
    raw_kt = p_info.get("key_track", p_info.get("keyTrack", p_info.get("keyTrackEnable")))
    key_track = bool(raw_kt) if raw_kt is not None else (root_note > 0)
    raw_link = int(p_info.get("pad_link", p_info.get("padLink", 0)) or 0)
    pad_link = raw_link if 1 <= raw_link <= 128 else 0
    simult_midi = (35 + pad_link) if pad_link else 0
    raw_submix = p_info.get("submix")
    if raw_submix is None or raw_submix == "":
        submix = int(default_submix)
    elif str(raw_submix).strip().lower() == "main":
        submix = 9
    else:
        submix = max(0, min(9, int(raw_submix)))
    tail_length = max(0.0, min(1.0, float(p_info.get("tail_length", p_info.get("tailLength", 0.0)) or 0.0)))
    return {
        "fine_tune": fine_tune,
        "is_oneshot": is_oneshot,
        "reverse": reverse,
        "loop_mode": loop_mode,
        "sample_offset": sample_offset,
        "root_note": root_note,
        "key_track": key_track,
        "pad_link": pad_link,
        "simult_midi": simult_midi,
        "submix": submix,
        "tail_length": tail_length,
        "monophonic": bool(p_info.get("monophonic", True)),
    }


def _set_xml_text(parent: ET.Element, tag: str, value: str) -> None:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = value


def _mpc_pad_wav_name(pad_num: int, pad_info: dict, source: str | Path) -> str:
    stem = str(pad_info.get("pad_sample_name") or Path(source).stem)
    # The display name may already include one or more WAV extensions.
    while stem.lower().endswith(".wav"):
        stem = stem[:-4]
    if not stem.strip():
        stem = Path(source).stem
    if "/" in stem or "\\" in stem:
        raise ValueError(f"Pad {pad_num}: nombre de muestra no válido")
    return f"PAD{pad_num:03d}_{stem}.wav"


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
                name = _mpc_pad_wav_name(pad_num, p_info, src)
                _convert_audio(src, out_dir / name, mono=False)
                p_info.update(sample_file=name, sample_name=Path(name).stem, n_frames=_get_wav_frames(out_dir/name))
            elif src or p_info.get("sample_file") or p_info.get("sample_path") or p_info.get("sample_name"):
                raise ValueError(f"Pad {pad_num}: muestra asignada no disponible: {src or p_info.get('sample_file') or p_info.get('sample_name')}")
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
        pp_el = prog.find("ProgramPads")
        if pp_el is not None and pp_el.text and pp_el.text.strip().startswith("{"):
            try:
                pp_obj = json.loads(pp_el.text)
                if isinstance(pp_obj, dict) and isinstance(pp_obj.get("ProgramPads"), dict):
                    _apply_program_pads_colors(pp_obj["ProgramPads"], pads_data)
                    pp_el.text = json.dumps(pp_obj, indent=4)
            except Exception:
                pass

        for inst in prog.findall("Instruments/Instrument"):
            pad_num = int(inst.get("number", "0"))
            p_info = pads_data.get(pad_num) or pads_data.get(str(pad_num)) or {}
            s_name = p_info.get("sample_name") or ""
            s_file = (
                p_info.get("sample_file")
                or p_info.get("sample_path")
                or p_info.get("source_path")
                or (f"{s_name}.wav" if s_name else "")
            )
            stype = p_info.get("sound_type") or detect_sound_type(s_name or s_file)
            raw_vol = p_info.get("volume")
            vol_locked = bool(p_info.get("volume_locked"))
            vol = (
                float(raw_vol)
                if raw_vol is not None and (not math.isfinite(float(raw_vol)) or vol_locked or abs(float(raw_vol) - 0.707946) >= 1e-5)
                else default_pad_volume(stype)
            )
            pan = float(p_info.get("pan", 0.500000))
            tune = max(-24, min(24, int(p_info.get("tune", 0))))
            mute = pad_mute_group(p_info)
            ext = _extract_extended_pad_params(p_info)

            _set_xml_text(inst, "Volume", f"{vol:.6f}")
            _set_xml_text(inst, "Pan", f"{pan:.6f}")
            _set_xml_text(inst, "TuneCoarse", str(tune))
            _set_xml_text(inst, "TuneFine", str(ext["fine_tune"]))
            _set_xml_text(inst, "MuteGroup", str(mute))
            _set_xml_text(inst, "OneShot", "True" if ext["is_oneshot"] else "False")
            _set_xml_text(inst, "SimultTarget1", str(ext["simult_midi"]))
            ar = inst.find("AudioRoute")
            if ar is not None:
                sub = ext["submix"]
                if sub == 0:
                    _set_xml_text(ar, "AudioRoute", "0")
                    _set_xml_text(ar, "AudioRouteSubIndex", "0")
                elif 1 <= sub <= 8:
                    _set_xml_text(ar, "AudioRoute", "1")
                    _set_xml_text(ar, "AudioRouteSubIndex", str(sub - 1))
                else:
                    _set_xml_text(ar, "AudioRoute", "2")
                    _set_xml_text(ar, "AudioRouteSubIndex", "0")

            if "monophonic" in p_info:
                _set_xml_text(inst, "Mono", "True" if ext["monophonic"] else "False")
                _set_xml_text(inst, "Polyphony", "1" if ext["monophonic"] else "8")
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
                _set_xml_text(lay, "TuneCoarse", "0")
                _set_xml_text(lay, "TuneFine", "0")
                _set_xml_text(lay, "RootNote", "0")
                _set_xml_text(lay, "KeyTrack", "False")
                _set_xml_text(lay, "Direction", "0")
                _set_xml_text(lay, "Offset", "0")
                _set_xml_text(lay, "Loop", "False")
                _set_xml_text(lay, "SliceLoop", "0")

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
                _set_xml_text(lay0, "TuneCoarse", str(tune))
                _set_xml_text(lay0, "TuneFine", str(ext["fine_tune"]))
                _set_xml_text(lay0, "RootNote", str(ext["root_note"]))
                _set_xml_text(lay0, "KeyTrack", "True" if ext["key_track"] else "False")
                _set_xml_text(lay0, "Direction", "1" if ext["reverse"] else "0")
                _set_xml_text(lay0, "Offset", str(ext["sample_offset"]))
                _set_xml_text(lay0, "Loop", "True" if ext["loop_mode"] == 1 else "False")
                _set_xml_text(lay0, "SliceLoop", str(ext["loop_mode"]))

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
        s_name = p_info.get("sample_name") or ""
        s_file = (
            p_info.get("sample_file")
            or p_info.get("sample_path")
            or p_info.get("source_path")
            or (f"{s_name}.wav" if s_name else "")
        )
        vol = float(p_info.get("volume", 0.707946))
        pan = float(p_info.get("pan", 0.500000))
        tune = max(-24, min(24, int(p_info.get("tune", 0))))
        mute = pad_mute_group(p_info)
        ext = _extract_extended_pad_params(p_info)

        inst = ET.SubElement(instruments, "Instrument", number=str(pad_num))
        ET.SubElement(inst, "Volume").text = f"{vol:.6f}"
        ET.SubElement(inst, "Pan").text = f"{pan:.6f}"
        ET.SubElement(inst, "TuneCoarse").text = str(int(tune))
        ET.SubElement(inst, "TuneFine").text = str(ext["fine_tune"])
        ET.SubElement(inst, "Mono").text = "True" if ext["monophonic"] else "False"
        ET.SubElement(inst, "Polyphony").text = "1" if ext["monophonic"] else "8"
        ET.SubElement(inst, "MuteGroup").text = str(int(mute))
        ET.SubElement(inst, "MuteTarget").text = "0"
        ET.SubElement(inst, "SimultTarget1").text = str(ext["simult_midi"])
        ET.SubElement(inst, "OneShot").text = "True" if ext["is_oneshot"] else "False"
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
                ET.SubElement(layer, "TuneCoarse").text = str(int(tune))
                ET.SubElement(layer, "TuneFine").text = str(ext["fine_tune"])
                ET.SubElement(layer, "RootNote").text = str(ext["root_note"])
                ET.SubElement(layer, "KeyTrack").text = "True" if ext["key_track"] else "False"
                ET.SubElement(layer, "Direction").text = "1" if ext["reverse"] else "0"
                ET.SubElement(layer, "Offset").text = str(ext["sample_offset"])
                ET.SubElement(layer, "Loop").text = "True" if ext["loop_mode"] == 1 else "False"
                ET.SubElement(layer, "SliceLoop").text = str(ext["loop_mode"])
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


def _reset_xpj_instrument_slot(inst: Dict[str, Any]) -> None:
    """Limpia un slot de instrumento en una pista clonada sin perder campos internos del firmware."""
    inst["coarseTune"] = 0
    inst["fineTune"] = 0
    inst["whichMuteGroup"] = 0
    if isinstance(inst.get("simultPlayTargets"), dict):
        inst["simultPlayTargets"] = {k: 0 for k in inst["simultPlayTargets"]}
    for lay in inst.get("layersv", []):
        lay["active"] = False
        lay["sampleName"] = ""
        lay["sampleFile"] = ""
        if isinstance(lay.get("sliceInfo"), dict):
            lay["sliceInfo"]["Start"] = 0
            lay["sliceInfo"]["End"] = 0
            lay["sliceInfo"]["LoopStart"] = 0


def _resolve_pad_submix_for_route_mode(sound_type: str, audio_route_mode: str) -> int:
    """Resuelve el submix por defecto (0=Track, 1..8=Submix 1..8, 9=Main) según audio_route_mode."""
    mode = str(audio_route_mode or "track").strip().lower()
    if mode == "submix1":
        return 1
    if mode == "main":
        return 9
    if mode == "submix_split":
        st = str(sound_type or "PERCUSSION").strip().upper()
        if st in ("KICK", "SNARE", "CLAP", "TOM", "HIHAT", "CYMBAL", "PERCUSSION"):
            return 1
        if st in ("BASS_808", "BASS"):
            return 2
        if st in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL", "CHOP", "LOOP"):
            return 3
        return 0
    return 0


def _effective_mpc_project_name(kit_name: str, mpc_options: Optional[dict] = None) -> str:
    """Calcula el nombre efectivo del proyecto .xpj aplicando sufijo _LIVE en modo live_pa cuando corresponde."""
    opts = mpc_options if isinstance(mpc_options, dict) else {}
    mix_mode = _normalize_mix_mode(opts.get("mix_mode"))
    append_suffix = opts.get("append_mode_suffix")
    if append_suffix is None:
        append_suffix = (mix_mode == "live_pa")
    if mix_mode == "live_pa" and bool(append_suffix) and not str(kit_name).endswith("_LIVE"):
        return f"{kit_name}_LIVE"
    return str(kit_name)


def export_mpc_project(
    kit_name: str,
    pads_data: dict,
    output_dir: str | Path,
    tempo: float = 120.0,
    key: str = "C",
    mpc_options: Optional[dict] = None,
) -> str:
    """Genera un proyecto MPC genuino (.xpj con cabecera ACVS) junto a su carpeta [ProjectData]."""
    opts = mpc_options if isinstance(mpc_options, dict) else {}
    gain_profile = str(opts.get("gain_profile") or "smart_pcm").strip().lower()
    force_gain_profile = bool(opts.get("force_gain_profile", False))
    audio_route_mode = str(opts.get("audio_route_mode") or "track").strip().lower()
    multitrack_mode = str(opts.get("multitrack_mode") or "single").strip().lower()
    auto_tune_808 = bool(opts.get("auto_tune_808", False))
    mix_mode = _normalize_mix_mode(opts.get("mix_mode"))
    style_id = str(opts.get("style_id") or "standard").strip().lower()
    bank_trims_opt = opts.get("bank_trims_db") if isinstance(opts.get("bank_trims_db"), dict) else {}
    effective_kit_name = _effective_mpc_project_name(kit_name, opts)

    base_dir = Path(output_dir) / effective_kit_name
    base_dir.mkdir(parents=True, exist_ok=True)
    proj_data_dir = base_dir / f"{effective_kit_name}_[ProjectData]"
    proj_data_dir.mkdir(parents=True, exist_ok=True)

    # Copiar muestras en [ProjectData] y aplicar calibración/afinación previa compartida con .xpm/.xpj
    linked_samples: list[tuple[str, str, int, int]] = []
    seen_files: set[str] = set()
    normalized_pads: Dict[int, Dict[str, Any]] = {}
    bank_letters = "ABCDEFGH"
    for pad_num in range(1, 129):
        p_info = pads_data.get(pad_num) or pads_data.get(str(pad_num)) or {}
        src = p_info.get("source_path", "")
        s_file = p_info.get("sample_file") or (Path(src).name if src else "")
        dest: Optional[Path] = None
        if src and Path(src).is_file():
            s_name = _mpc_pad_wav_name(pad_num, p_info, src)
            dest = proj_data_dir / s_name
            _convert_audio(src, dest, mono=False)
        elif src:
            raise ValueError(f"Pad {pad_num}: muestra asignada no disponible: {src}")
        elif s_file and (proj_data_dir / s_file).is_file():
            dest = proj_data_dir / s_file
            s_name = s_file
        else:
            # Metadata-only templates remain supported; an explicit unavailable source is not.
            normalized_pads[pad_num] = dict(p_info)
            continue

        s_stem = Path(s_name).stem
        n_frames = _get_wav_frames(dest)
        p_copy = dict(p_info)
        p_copy["sample_file"] = s_name
        p_copy["sample_name"] = s_stem
        p_copy["n_frames"] = n_frames

        stype = str(p_copy.get("sound_type") or detect_sound_type(s_stem or s_name)).upper()
        p_copy["sound_type"] = stype

        pad_default_submix = _resolve_pad_submix_for_route_mode(stype, audio_route_mode)
        if ("submix" not in p_copy or p_copy.get("submix") in (None, "")) and pad_default_submix != 0:
            p_copy["submix"] = pad_default_submix

        raw_vol = p_copy.get("volume")
        vol_locked = bool(p_copy.get("volume_locked"))
        is_default_vol = (not vol_locked) and (raw_vol is None or (math.isfinite(float(raw_vol)) and abs(float(raw_vol) - 0.707946) < 1e-5))
        b_lbl = bank_letters[max(0, min(7, (pad_num - 1) // 16))]
        b_trim = float(bank_trims_opt.get(b_lbl, 0.0) or 0.0)

        if gain_profile != "manual" and not vol_locked and (force_gain_profile or is_default_vol):
            if gain_profile == "hierarchical_a":
                p_copy["volume"] = default_pad_volume(stype, "hierarchical_a")
            elif gain_profile == "uniform_b":
                p_copy["volume"] = default_pad_volume(stype, "uniform_b")
            else:
                p_copy["volume"] = compute_profiled_pad_volume(
                    stype,
                    dest,
                    mix_mode=mix_mode,
                    style_id=style_id,
                    bank_trim_db=b_trim,
                )["volume"]

        if auto_tune_808 and stype in ("BASS_808", "BASS", "KEYS_SYNTH") and dest.is_file():
            try:
                pinfo = detect_sample_pitch_and_key(dest)
                if float(pinfo.get("f0_hz") or 0.0) > 0.0:
                    if not p_copy.get("root_note") and pinfo.get("midi_note"):
                        p_copy["root_note"] = int(pinfo["midi_note"])
                        p_copy.setdefault("key_track", True)
                    if not int(p_copy.get("fine_tune", p_copy.get("fineTune", 0)) or 0):
                        cents = int(round(float(pinfo.get("cents_offset") or 0)))
                        p_copy["fine_tune"] = max(-90, min(90, -cents))
            except Exception:
                pass

        ext_pad = _extract_extended_pad_params(p_copy, default_submix=pad_default_submix)
        sample_root = ext_pad["root_note"] if ext_pad["root_note"] > 0 else 60
        if s_name not in seen_files:
            seen_files.add(s_name)
            linked_samples.append((s_stem, s_name, n_frames, sample_root))
        normalized_pads[pad_num] = p_copy

    # Exportar el programa Drum .xpm genuino dentro de [ProjectData]
    export_mpc_program(effective_kit_name, normalized_pads, proj_data_dir, copy_samples=False)

    # Ganancias de bus diferenciadas y estrictamente float (invariante ACVS 1.3.0.12)
    mixer_vol_target = 0.7943282347242815 if mix_mode == "live_pa" else 0.7079457640647888
    output_vol_target = 0.8912509381337456 if mix_mode == "live_pa" else 0.7079457640647888
    track_vol_target = 0.7943282347242815 if mix_mode == "live_pa" else 0.7079457640647888

    # Sidecar no intrusivo fuera de [ProjectData] con receta de mezcla/ducking y coherencia A–H
    try:
        report_pads = []
        for p_num, p_val in sorted(normalized_pads.items()):
            sf = p_val.get("sample_file")
            if not sf:
                continue
            rp = dict(p_val)
            rp["pad"] = p_num
            rp["source_path"] = str(proj_data_dir / sf)
            report_pads.append(rp)
        coherence = analyze_multibank_coherence(
            report_pads,
            mix_mode=mix_mode,
            style_id=style_id,
            bpm=float(tempo),
            sampqol_active=True,
        )
        sidecar_payload = {
            "schema": "beatos-mix-report-v1",
            "kit_name": kit_name,
            "effective_kit_name": effective_kit_name,
            "mix_mode": mix_mode,
            "style_id": coherence["style_id"],
            "tempo": float(tempo),
            "key": key,
            "audio_route_mode": audio_route_mode,
            "master_bus_volumes": {
                "mixer_volume": float(mixer_vol_target),
                "output_volume": float(output_vol_target),
                "track_volume": float(track_vol_target),
            },
            "active_banks": coherence["active_banks"],
            "banks_summary": coherence["banks_summary"],
            "bank_trims_db": coherence["bank_trims_db"],
            "global_coherence": coherence["global_coherence"],
            "master_bus_plan": coherence["master_bus_plan"],
            "ducking_recipe": coherence["ducking_recipe"],
        }
        sidecar_path = base_dir / f"{effective_kit_name}_beatos_mix_report.json"
        sidecar_path.write_text(json.dumps(sidecar_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as _rep_err:
        logger.warning("Mix report sidecar skipped for %s: %s", effective_kit_name, _rep_err)

    xpj_path = base_dir / f"{effective_kit_name}.xpj"
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
        payload = _replace_template_kit_name(payload, "Astro1Deep_Kit_01", effective_kit_name)

        data = payload.get("data", {})
        key_str = key if " " in key else f"{key} Major"
        if _mpc_compat is not None:
            key_str = _mpc_compat.normalize_key(key_str)
        data["key"] = key_str
        data["masterTempo"] = float(tempo)
        data["masterTempoEnabled"] = True
        data["currentSequence"] = 0

        for seq in data.get("sequences", []):
            if isinstance(seq, dict) and isinstance(seq.get("value"), dict):
                seq["value"]["bpm"] = float(tempo)
                seq["value"]["tempoEnable"] = True

        deduped_samples: List[Dict[str, Any]] = []
        seen_sample_keys = set()
        for s_stem, s_file, _, sample_root in linked_samples:
            skey = (s_stem, s_file)
            if skey in seen_sample_keys:
                continue
            seen_sample_keys.add(skey)
            deduped_samples.append({
                "version": 1,
                "name": s_stem,
                "path": s_file,
                "loadImpl": 0,
                "metadata": {
                    "tempo": 0.0,
                    "rootNote": int(sample_root),
                    "tune": 0.0,
                    "key": key_str,
                },
            })
        data["samples"] = deduped_samples

        # Preservar intactos plugin.state e inserts de mixer; ajustar solo volúmenes escalares float
        mixer_obj = data.get("mixer")
        if isinstance(mixer_obj, dict):
            mixer_obj["volume"] = float(mixer_vol_target)
            outs = mixer_obj.get("outputs")
            if isinstance(outs, list) and outs and isinstance(outs[0], dict):
                out_mix = outs[0].get("mixable")
                if isinstance(out_mix, dict):
                    out_mix["volume"] = float(output_vol_target)

        tracks = data.get("tracks", [])[:1]
        data["tracks"] = tracks
        orig_track0_name = tracks[0].get("name") if tracks else None
        if tracks:
            tracks[0]["name"] = effective_kit_name
            tracks[0]["volume"] = float(track_vol_target)
            tracks[0]["samples"] = copy.deepcopy(data["samples"])
            prog = tracks[0].get("program", {})
            prog["name"] = effective_kit_name
            if isinstance(prog.get("programPads"), dict):
                _apply_program_pads_colors(prog["programPads"], normalized_pads)
            if isinstance(prog.get("mixable"), dict):
                prog["mixable"]["volume"] = float(track_vol_target)
            drum = prog.get("drum", {})
            insts = drum.get("instruments", [])
            for idx, inst in enumerate(insts):
                pad_num = idx + 1
                p_info = normalized_pads.get(pad_num, {})
                s_file = p_info.get("sample_file", "")
                s_stem = p_info.get("sample_name", "")
                n_frames = int(p_info.get("n_frames", 0))
                inferred_type = p_info.get("sound_type") or detect_sound_type(s_stem or s_file)
                if "volume" in p_info and p_info["volume"] is not None:
                    vol = float(p_info["volume"])
                else:
                    vol = float(default_pad_volume(inferred_type))
                pan = float(p_info.get("pan", 0.500000))
                tune = max(-24, min(24, int(p_info.get("tune", 0))))
                mute = pad_mute_group(p_info)
                pad_def_sub = _resolve_pad_submix_for_route_mode(inferred_type, audio_route_mode)
                ext = _extract_extended_pad_params(p_info, default_submix=pad_def_sub)

                inst["coarseTune"] = tune
                inst["fineTune"] = ext["fine_tune"]
                inst["triggerMode"] = 0 if ext["is_oneshot"] else 2
                inst["whichMuteGroup"] = mute
                inst["monophonic"] = ext["monophonic"]
                inst["polyphony"] = 1 if ext["monophonic"] else 8
                if isinstance(inst.get("simultPlayTargets"), dict):
                    inst["simultPlayTargets"] = {
                        "value0": ext["simult_midi"],
                        "value1": 0,
                        "value2": 0,
                        "value3": 0,
                    }
                if isinstance(inst.get("muteTargets"), dict):
                    inst["muteTargets"] = {k: 0 for k in inst["muteTargets"]}
                if isinstance(inst.get("mixable"), dict):
                    inst["mixable"]["volume"] = float(vol)
                    inst["mixable"]["pan"] = float(pan)
                    inst["mixable"]["muteGroup"] = mute
                    if isinstance(inst["mixable"].get("audioRoute"), dict):
                        sub = ext["submix"]
                        if sub == 0:
                            inst["mixable"]["audioRoute"]["destination"] = 0
                            inst["mixable"]["audioRoute"]["audioRouteSubIndex"] = 0
                        elif 1 <= sub <= 8:
                            inst["mixable"]["audioRoute"]["destination"] = 1
                            inst["mixable"]["audioRoute"]["audioRouteSubIndex"] = sub - 1
                        else:
                            inst["mixable"]["audioRoute"]["destination"] = 2
                            inst["mixable"]["audioRoute"]["audioRouteSubIndex"] = 0

                layersv = inst.get("layersv", [])
                for lay in layersv:
                    lay["active"] = False
                    lay["sampleName"] = ""
                    lay["sampleFile"] = ""
                    lay["coarseTune"] = 0
                    lay["fineTune"] = 0
                    lay["rootNote"] = 0
                    lay["keyTrackEnable"] = False
                    lay["direction"] = 0
                    lay["offset"] = 0
                    lay["loop"] = False
                    lay["loopMode"] = 0
                    if isinstance(lay.get("volume"), dict):
                        lay["volume"]["gainCoefficient"] = 1.0
                        lay["volume"]["controlValue"] = 1.0
                    if isinstance(lay.get("sliceInfo"), dict):
                        lay["sliceInfo"]["Start"] = 0
                        lay["sliceInfo"]["End"] = 0
                        lay["sliceInfo"]["LoopStart"] = 0
                        lay["sliceInfo"]["LoopMode"] = 0
                        lay["sliceInfo"]["TailLength"] = 0.0

                if (s_file or s_stem) and layersv:
                    file_name = s_file or (f"{s_stem}.wav" if not s_stem.endswith(".wav") else s_stem)
                    stem_name = s_stem or Path(file_name).stem
                    lay0 = layersv[0]
                    lay0["active"] = True
                    lay0["sampleName"] = stem_name
                    lay0["sampleFile"] = file_name
                    lay0["sliceIndex"] = 129
                    lay0["coarseTune"] = tune
                    lay0["fineTune"] = ext["fine_tune"]
                    lay0["pitch"] = float(tune)
                    lay0["rootNote"] = ext["root_note"]
                    lay0["keyTrackEnable"] = ext["key_track"]
                    lay0["direction"] = 1 if ext["reverse"] else 0
                    lay0["offset"] = ext["sample_offset"]
                    lay0["loop"] = bool(ext["loop_mode"] == 1)
                    lay0["loopMode"] = ext["loop_mode"]
                    if isinstance(lay0.get("volume"), dict):
                        lay0["volume"]["gainCoefficient"] = 1.0
                        lay0["volume"]["controlValue"] = 1.0
                    if isinstance(lay0.get("sliceInfo"), dict):
                        lay0["sliceInfo"]["Start"] = 0
                        lay0["sliceInfo"]["End"] = n_frames
                        lay0["sliceInfo"]["LoopStart"] = 0
                        lay0["sliceInfo"]["LoopMode"] = ext["loop_mode"]
                        lay0["sliceInfo"]["TailLength"] = float(ext["tail_length"])

            if multitrack_mode == "role_split_4":
                base_track = copy.deepcopy(tracks[0])
                bus_specs = [
                    (f"{effective_kit_name} Drums", {"KICK", "SNARE", "CLAP", "TOM"}),
                    (f"{effective_kit_name} Hats & Perc", {"HIHAT", "CYMBAL", "PERCUSSION"}),
                    (f"{effective_kit_name} Bass 808", {"BASS_808", "BASS"}),
                    (f"{effective_kit_name} Melodic & FX", None),
                ]
                assigned_pads: set[int] = set()
                split_tracks: List[Dict[str, Any]] = []
                for bus_name, role_set in bus_specs:
                    bus_pad_nums: set[int] = set()
                    used_files: set[str] = set()
                    for pad_num, p_info in normalized_pads.items():
                        s_file_p = p_info.get("sample_file", "")
                        if not s_file_p:
                            continue
                        st_p = str(p_info.get("sound_type") or "PERCUSSION").upper()
                        in_bus = (pad_num not in assigned_pads) if role_set is None else (st_p in role_set)
                        if in_bus:
                            bus_pad_nums.add(pad_num)
                            assigned_pads.add(pad_num)
                            used_files.add(s_file_p)
                    if not bus_pad_nums and split_tracks:
                        continue
                    trk_clone = copy.deepcopy(base_track)
                    trk_clone["name"] = bus_name
                    trk_clone["volume"] = float(track_vol_target)
                    trk_clone["samples"] = [s for s in data["samples"] if s.get("path") in used_files]
                    t_prog = trk_clone.get("program", {})
                    t_prog["name"] = bus_name
                    t_insts = t_prog.get("drum", {}).get("instruments", [])
                    for idx, inst in enumerate(t_insts):
                        if (idx + 1) not in bus_pad_nums:
                            _reset_xpj_instrument_slot(inst)
                    split_tracks.append(trk_clone)
                if split_tracks:
                    data["tracks"] = split_tracks

        if _mpc_compat is not None and data.get("tracks"):
            try:
                kit_track_names = [t["name"] for t in data["tracks"] if t.get("name")]
                _mpc_compat.restore_mixer_tracks(data)
                _mpc_compat.reconcile_generated_clips(
                    data,
                    source_name=orig_track0_name,
                    new_names=tuple(kit_track_names),
                )
            except Exception as _compat_err:
                logger.warning("mpc_compat post-process skipped for %s: %s", effective_kit_name, _compat_err)

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
                for s_stem, s_file, _n_frames, _sample_root in linked_samples
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


def _master_pcm_float32_anti_clip(
    channels_f32: List[Any],
    sample_rate: int = 44100,
    *,
    target_peak_dbfs: float = -0.80,
    apply_hpf_24hz: bool = True,
    only_attenuate_above_ceiling: bool = True,
    fade_in_ms: float = 0.0,
    fade_out_ms: float = 0.0,
) -> List[int]:
    """
    Aplica la cadena de mastering seguro BeatOS sobre audio float32 [-1.0, +1.0]:
      1) HPF Butterworth orden 2 fase cero a 24 Hz (elimina DC/rumble sin desfasar transientes).
      2) Escalado lineal uniforme conjunto (L/R) al techo -0.80 dBFS para evitar clipping AAC/MP4.
      3) Micro-fades coseno opcionales en entrada y salida.
      4) Dither triangular TPDF (±1 LSB) antes de cuantizar a PCM 16-bit firmado.
    """
    if not channels_f32:
        return []
    n_ch = len(channels_f32)
    n_frames = min(len(ch) for ch in channels_f32)
    if n_frames <= 0:
        return []

    ceiling = 10.0 ** (float(target_peak_dbfs) / 20.0)

    try:
        import numpy as np

        proc: List[Any] = [np.asarray(ch[:n_frames], dtype=np.float64) for ch in channels_f32]
        if apply_hpf_24hz:
            proc = [ch - float(np.mean(ch)) for ch in proc]
            if n_frames >= 24:
                try:
                    from scipy.signal import butter, sosfiltfilt

                    sos = butter(2, 24.0, btype="highpass", fs=float(sample_rate), output="sos")
                    proc = [sosfiltfilt(sos, ch) for ch in proc]
                    proc = [ch - float(np.mean(ch)) for ch in proc]
                except Exception:
                    pass

        peak = max(float(np.max(np.abs(ch))) for ch in proc)
        if peak > 1e-9 and (peak > ceiling or not only_attenuate_above_ceiling):
            scale = ceiling / peak
            proc = [ch * scale for ch in proc]

        if fade_in_ms > 0.0:
            fi_n = min(n_frames // 2, int(round((fade_in_ms / 1000.0) * sample_rate)))
            if fi_n > 1:
                win_in = 0.5 * (1.0 - np.cos(np.pi * np.arange(fi_n, dtype=np.float64) / float(fi_n)))
                for ch in proc:
                    ch[:fi_n] *= win_in
        if fade_out_ms > 0.0:
            fo_n = min(n_frames // 2, int(round((fade_out_ms / 1000.0) * sample_rate)))
            if fo_n > 1:
                win_out = 0.5 * (1.0 - np.cos(np.pi * np.arange(fo_n, dtype=np.float64) / float(fo_n)))[::-1]
                for ch in proc:
                    ch[-fo_n:] *= win_out

        rng = np.random.default_rng(1337)
        lsb = 1.0 / 32768.0
        int_chs = []
        for ch in proc:
            tpdf = (rng.random(n_frames) + rng.random(n_frames) - 1.0) * lsb
            q = np.rint(np.clip(ch + tpdf, -1.0, 1.0) * 32767.0).clip(-32768, 32767).astype(np.int64)
            int_chs.append(q)

        if n_ch == 1:
            return int_chs[0].tolist()
        inter = np.empty(n_frames * n_ch, dtype=np.int64)
        for ci, q in enumerate(int_chs):
            inter[ci::n_ch] = q
        return inter.tolist()
    except ImportError:
        pass

    # Fallback determinista en Python puro si numpy no está presente
    proc_py: List[List[float]] = []
    for ch in channels_f32:
        vals = [float(x) for x in ch[:n_frames]]
        if apply_hpf_24hz and vals:
            mean_v = sum(vals) / len(vals)
            vals = [v - mean_v for v in vals]
        proc_py.append(vals)

    peak = max((max(abs(v) for v in ch) if ch else 0.0) for ch in proc_py)
    if peak > 1e-9 and (peak > ceiling or not only_attenuate_above_ceiling):
        scale = ceiling / peak
        proc_py = [[v * scale for v in ch] for ch in proc_py]

    if fade_in_ms > 0.0:
        fi_n = min(n_frames // 2, int(round((fade_in_ms / 1000.0) * sample_rate)))
        if fi_n > 1:
            for i in range(fi_n):
                w = 0.5 * (1.0 - math.cos(math.pi * i / float(fi_n)))
                for ch in proc_py:
                    ch[i] *= w
    if fade_out_ms > 0.0:
        fo_n = min(n_frames // 2, int(round((fade_out_ms / 1000.0) * sample_rate)))
        if fo_n > 1:
            for i in range(fo_n):
                w = 0.5 * (1.0 - math.cos(math.pi * i / float(fo_n)))
                for ch in proc_py:
                    ch[-(i + 1)] *= w

    out: List[int] = []
    for i in range(n_frames):
        for ch in proc_py:
            val = int(round(max(-1.0, min(1.0, ch[i])) * 32767.0))
            out.append(max(-32768, min(32767, val)))
    return out


def _convert_audio(source, destination=None, mono=True, tune=0, sample_rate=44100):
    """Decode/resample using FFmpeg float32 + anti-clipping (-0.80 dBFS, 24Hz HPF, TPDF) or preserve clean 16/44.1 WAV."""
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
    executable = None
    try:
        import beatos_runtime  # type: ignore
        executable = beatos_runtime.resolve_ffmpeg_path(Path(__file__).resolve().parent)
    except Exception:
        executable = None
    if not executable:
        executable = shutil.which('ffmpeg')
    if not executable:
        raise ValueError("Esta conversión necesita FFmpeg. Instálalo o usa WAV PCM 16-bit/44.1kHz.")
    command = [executable, '-nostdin', '-v', 'error', '-i', str(source), '-map', '0:a:0', '-ar', str(sample_rate)]
    if mono:
        command += ['-ac', '1']
    if tune:
        command += ['-af', f'aresample=44100,asetrate={44100 * 2**(tune/12)},aresample=44100']
    # Decodificar siempre a float32 para preservar picos >0 dBFS en AAC/MP4 antes de normalizar
    command += ['-c:a', 'pcm_f32le', '-f', 'wav', 'pipe:1']
    result = subprocess.run(command, capture_output=True, timeout=120)
    if result.returncode or not result.stdout or len(result.stdout) < 44:
        raise ValueError(f"No se pudo decodificar {Path(source).name}")

    blob = result.stdout
    n_ch = None
    data_bytes = b""
    if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
        pos = 12
        while pos + 8 <= len(blob):
            cid = blob[pos : pos + 4]
            csize = struct.unpack("<I", blob[pos + 4 : pos + 8])[0]
            payload_start = pos + 8
            if cid == b"fmt " and csize >= 16 and payload_start + 4 <= len(blob):
                n_ch = struct.unpack("<H", blob[payload_start + 2 : payload_start + 4])[0]
                pos = payload_start + csize + (csize & 1)
            elif cid == b"data":
                data_bytes = blob[payload_start:]
                break
            else:
                pos = payload_start + csize + (csize & 1)
    if n_ch not in (1, 2) or (mono and n_ch != 1):
        raise ValueError(f"Formato de canales no admitido: {n_ch}; requiere mono o estéreo")
    usable = (len(data_bytes) // (4 * n_ch)) * (4 * n_ch)
    if usable <= 0:
        raise ValueError("Audio vacío")
    data_bytes = data_bytes[:usable]

    try:
        import numpy as np
        arr = np.frombuffer(data_bytes, dtype="<f4")
        ch_list = [arr[ci::n_ch] for ci in range(n_ch)]
    except ImportError:
        all_f = struct.unpack(f"<{usable // 4}f", data_bytes)
        ch_list = [all_f[ci::n_ch] for ci in range(n_ch)]

    pcm16 = _master_pcm_float32_anti_clip(
        ch_list,
        sample_rate=sample_rate,
        target_peak_dbfs=-0.80,
        apply_hpf_24hz=True,
        only_attenuate_above_ceiling=True,
    )
    if not pcm16:
        raise ValueError("Audio vacío")

    if destination:
        dest_p = Path(destination)
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dest_p), 'wb') as wf:
            wf.setnchannels(n_ch)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"<{len(pcm16)}h", *pcm16))
        with wave.open(str(dest_p), 'rb') as wav:
            if not wav.getnframes() or wav.getnchannels() not in (1, 2):
                raise ValueError("Se requiere audio mono o estéreo no vacío")
        return
    return pcm16


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


def _scan_pcm16_wav_metrics(wf: wave.Wave_read, n_ch: int, n_frames: int, fr: int) -> dict:
    """Escanea todo el WAV PCM 16-bit en bloques acotados sin limitar el análisis a 4s."""
    peak_l = 0
    peak_r = 0
    sum_sq_l = 0.0
    sum_sq_r = 0.0
    sum_l = 0.0
    sum_r = 0.0
    sum_lr = 0.0
    clipped_samples = 0
    max_abs_diff = 0
    first_sig_frame: int | None = None
    last_sig_frame: int | None = None

    try:
        import numpy as _np  # type: ignore
    except ImportError:
        _np = None

    wf.rewind()
    frame_cursor = 0
    chunk_frames = 262144
    sig_thresh = 350

    while frame_cursor < n_frames:
        to_read = min(chunk_frames, n_frames - frame_cursor)
        raw = wf.readframes(to_read)
        if not raw:
            break
        actual_frames = len(raw) // (2 * n_ch)
        if actual_frames <= 0:
            break
        raw = raw[:actual_frames * 2 * n_ch]

        if _np is not None:
            arr = _np.frombuffer(raw, dtype='<i2').reshape(actual_frames, n_ch).astype(_np.float64)
            L = arr[:, 0]
            R = arr[:, 1] if n_ch == 2 else L
            absL = _np.abs(L)
            absR = _np.abs(R) if n_ch == 2 else absL
            pL = int(absL.max())
            pR = int(absR.max()) if n_ch == 2 else pL
            if pL > peak_l:
                peak_l = pL
            if pR > peak_r:
                peak_r = pR
            sum_l += float(L.sum())
            sum_sq_l += float(_np.dot(L, L))
            clipped_samples += int((absL >= 32760).sum())
            if n_ch == 2:
                sum_r += float(R.sum())
                sum_sq_r += float(_np.dot(R, R))
                sum_lr += float(_np.dot(L, R))
                clipped_samples += int((absR >= 32760).sum())
                d = int(_np.abs(L - R).max())
                if d > max_abs_diff:
                    max_abs_diff = d
                active_mask = (absL > sig_thresh) | (absR > sig_thresh)
            else:
                active_mask = absL > sig_thresh
            if bool(active_mask.any()):
                nz = _np.flatnonzero(active_mask)
                f_idx = frame_cursor + int(nz[0])
                l_idx = frame_cursor + int(nz[-1])
                if first_sig_frame is None:
                    first_sig_frame = f_idx
                last_sig_frame = l_idx
        else:
            samples = array.array('h')
            samples.frombytes(raw)
            if sys.byteorder != 'little':
                samples.byteswap()
            if n_ch == 2:
                Ls = samples[0::2]
                Rs = samples[1::2]
                for idx in range(actual_frames):
                    lv = Ls[idx]
                    rv = Rs[idx]
                    al = -lv if lv < 0 else lv
                    ar = -rv if rv < 0 else rv
                    if al > peak_l:
                        peak_l = al
                    if ar > peak_r:
                        peak_r = ar
                    if al >= 32760:
                        clipped_samples += 1
                    if ar >= 32760:
                        clipped_samples += 1
                    sum_l += lv
                    sum_r += rv
                    sum_sq_l += lv * lv
                    sum_sq_r += rv * rv
                    sum_lr += lv * rv
                    diff = lv - rv
                    adiff = -diff if diff < 0 else diff
                    if adiff > max_abs_diff:
                        max_abs_diff = adiff
                    if al > sig_thresh or ar > sig_thresh:
                        g_idx = frame_cursor + idx
                        if first_sig_frame is None:
                            first_sig_frame = g_idx
                        last_sig_frame = g_idx
            else:
                for idx, lv in enumerate(samples):
                    al = -lv if lv < 0 else lv
                    if al > peak_l:
                        peak_l = al
                    if al >= 32760:
                        clipped_samples += 1
                    sum_l += lv
                    sum_sq_l += lv * lv
                    if al > sig_thresh:
                        g_idx = frame_cursor + idx
                        if first_sig_frame is None:
                            first_sig_frame = g_idx
                        last_sig_frame = g_idx

        frame_cursor += actual_frames

    total_frames = max(1, frame_cursor)
    peak_val = max(peak_l, peak_r) if n_ch == 2 else peak_l
    peak_dbfs = round(20 * math.log10(peak_val / 32767.0), 2) if peak_val > 0 else -999.0
    peak_l_dbfs = round(20 * math.log10(peak_l / 32767.0), 2) if peak_l > 0 else -999.0
    peak_r_dbfs = round(20 * math.log10(peak_r / 32767.0), 2) if peak_r > 0 else -999.0

    total_samples = total_frames * n_ch
    mean_sq_total = (sum_sq_l + (sum_sq_r if n_ch == 2 else 0.0)) / max(1, total_samples)
    rms_dbfs = round(20 * math.log10(math.sqrt(mean_sq_total) / 32767.0), 2) if mean_sq_total > 0 else -999.0
    mean_sq_l = sum_sq_l / total_frames
    mean_sq_r = sum_sq_r / total_frames if n_ch == 2 else mean_sq_l
    rms_l_dbfs = round(20 * math.log10(math.sqrt(mean_sq_l) / 32767.0), 2) if mean_sq_l > 0 else -999.0
    rms_r_dbfs = round(20 * math.log10(math.sqrt(mean_sq_r) / 32767.0), 2) if mean_sq_r > 0 else -999.0
    dc_offset = round((sum_l + (sum_r if n_ch == 2 else 0.0)) / max(1, total_samples), 2)

    stereo_diff_ratio = round(max_abs_diff / max(1, peak_val), 4) if n_ch == 2 else 0.0
    stereo_correlation: float | None = None
    if n_ch == 2 and total_frames > 1:
        ml = sum_l / total_frames
        mr = sum_r / total_frames
        var_l = (sum_sq_l / total_frames) - ml * ml
        var_r = (sum_sq_r / total_frames) - mr * mr
        if var_l > 1e-6 and var_r > 1e-6:
            cov = (sum_lr / total_frames) - ml * mr
            stereo_correlation = round(max(-1.0, min(1.0, cov / math.sqrt(var_l * var_r))), 4)

    is_silent = (peak_val == 0) or (peak_dbfs < -65.0)
    is_dual_mono = bool(
        (not is_silent)
        and n_ch == 2
        and (
            stereo_diff_ratio < 0.02
            or (
                stereo_correlation is not None
                and stereo_correlation > 0.985
                and abs(peak_l - peak_r) / max(1, peak_val) < 0.05
            )
        )
    )
    signal_start_sec = round(first_sig_frame / fr, 2) if first_sig_frame is not None else None
    signal_end_sec = round(last_sig_frame / fr, 2) if last_sig_frame is not None else None
    signal_duration_sec = (
        round(max(0.0, signal_end_sec - signal_start_sec), 2)
        if (signal_start_sec is not None and signal_end_sec is not None)
        else 0.0
    )

    return {
        'peak_val': peak_val,
        'peak_l': peak_l,
        'peak_r': peak_r,
        'peak_dbfs': peak_dbfs,
        'peak_l_dbfs': peak_l_dbfs,
        'peak_r_dbfs': peak_r_dbfs,
        'rms_dbfs': rms_dbfs,
        'rms_l_dbfs': rms_l_dbfs,
        'rms_r_dbfs': rms_r_dbfs,
        'dc_offset': dc_offset,
        'clipped_samples': clipped_samples,
        'is_silent': is_silent,
        'is_dual_mono': is_dual_mono,
        'stereo_diff_ratio': stereo_diff_ratio,
        'stereo_correlation': stereo_correlation,
        'signal_start_sec': signal_start_sec,
        'signal_end_sec': signal_end_sec,
        'signal_duration_sec': signal_duration_sec,
    }


def inspect_po33_backup(wav_path: str | Path) -> dict:
    """
    Inspect complete WAV PCM structure and full-file L/R stereo DSP telemetry;
    never certify PO-33 modem packets without the CRC verifier.
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
            duration = n_frames / fr if fr else 0.0

            complete = False
            if n_frames:
                wf.setpos(n_frames - 1)
                complete = len(wf.readframes(1)) == n_ch * sw and not wf.readframes(1)

            is_stereo = n_ch == 2
            is_16bit = sw == 2
            audio_compatible = complete and is_stereo and is_16bit and fr in (44100, 48000)

            if is_16bit and n_frames > 0 and n_ch in (1, 2):
                metrics = _scan_pcm16_wav_metrics(wf, n_ch, n_frames, fr)
            else:
                metrics = {
                    'peak_val': 0,
                    'peak_dbfs': -999.0, 'peak_l_dbfs': -999.0, 'peak_r_dbfs': -999.0,
                    'rms_dbfs': -999.0, 'rms_l_dbfs': -999.0, 'rms_r_dbfs': -999.0,
                    'dc_offset': 0.0, 'clipped_samples': 0,
                    'is_silent': True, 'is_dual_mono': False,
                    'stereo_diff_ratio': 0.0, 'stereo_correlation': None,
                    'signal_start_sec': None, 'signal_end_sec': None, 'signal_duration_sec': 0.0,
                }

        peak_val = metrics['peak_val']
        has_clipping = peak_val >= 32760
        is_too_quiet = (not metrics['is_silent']) and (metrics['peak_dbfs'] < -25.0)
        signal_usable = bool(audio_compatible and not metrics['is_silent'] and not metrics['is_dual_mono'])

        status = "AUDIO_COMPATIBLE_NOT_DECODED"
        if not audio_compatible:
            status = "UNSUPPORTED_OR_INCOMPLETE_AUDIO"
        elif metrics['is_silent']:
            status = "WARNING_SILENT_RECORDING"
        elif metrics['is_dual_mono']:
            status = "WARNING_MONO_DUPLICATED"
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
            "inspection_scope": "Estructura WAV y telemetría DSP estéreo L/R completa; no verifica paquetes CRC del módem",
            "filename": p.name,
            "path": str(p),
            "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            "duration_sec": round(duration, 3),
            "channels": n_ch,
            "sample_rate": fr,
            "bit_depth": sw * 8,
            "peak_dbfs": metrics['peak_dbfs'],
            "peak_l_dbfs": metrics['peak_l_dbfs'],
            "peak_r_dbfs": metrics['peak_r_dbfs'],
            "rms_dbfs": metrics['rms_dbfs'],
            "rms_l_dbfs": metrics['rms_l_dbfs'],
            "rms_r_dbfs": metrics['rms_r_dbfs'],
            "dc_offset": metrics['dc_offset'],
            "clipped_samples": metrics['clipped_samples'],
            "clipping": has_clipping,
            "is_silent": metrics['is_silent'],
            "is_dual_mono": metrics['is_dual_mono'],
            "signal_usable": signal_usable,
            "stereo_diff_ratio": metrics['stereo_diff_ratio'],
            "stereo_correlation": metrics['stereo_correlation'],
            "signal_start_sec": metrics['signal_start_sec'],
            "signal_end_sec": metrics['signal_end_sec'],
            "signal_duration_sec": metrics['signal_duration_sec'],
            "status": status,
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def scan_po33_backups(search_dirs: Optional[list[str | Path]] = None, cache: Optional[dict] = None, *, root: str | Path | None = None) -> list[dict]:
    """
    Escanea directorios en busca de backups Pocket Operator y devuelve el catálogo ordenado.
    """
    if search_dirs is None:
        if root is not None:
            search_dirs = po33_backup_dirs(root)
        else:
            search_dirs = [
                DEFAULT_PO_DIR,
                Path('/Volumes/MPCSMPL/PO_BACKUPS'),
                Path.home() / "Music" / "Pocket_Operator_Backups",
            ]

    default_res: Path | None = None
    ext_roots: list[Path] = []
    if root is not None:
        try:
            default_res = default_po_backup_dir(root).resolve()
        except OSError:
            default_res = None
        cfg = load_po_backup_config(root)
        for cand_str in [cfg.get('external_dir', ''), *(cfg.get('scan_external_dirs') or [])]:
            if cand_str:
                try:
                    ext_roots.append(_validate_external_po_dir(cand_str, allow_create=False))
                except ValueError:
                    pass

    results = []
    seen_paths = set()
    cache = {} if cache is None else cache

    for d in search_dirs:
        p_dir = Path(d)
        if not p_dir.exists() or p_dir.is_symlink():
            continue
        p_dir_res = p_dir.resolve()
        for wav in p_dir.rglob('*'):
            if not wav.is_file() or wav.is_symlink() or wav.suffix.lower() != '.wav' or any(part.startswith('.') for part in wav.relative_to(p_dir).parts):
                continue
            wav = wav.resolve()
            if not wav.is_relative_to(p_dir_res) or wav in seen_paths:
                continue
            seen_paths.add(wav)
            stat = wav.stat()
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, 2)
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
            info['notes'] = metadata.get('notes', '') if metadata else ''
            info['device_restore_verified'] = False
            info['payload_verified'] = False
            info['verification_status'] = metadata.get('verification_status', 'AUDIO_ARCHIVED_NOT_DECODED') if metadata else 'LEGACY_UNCLASSIFIED_AUDIO'
            info["filename"] = wav.name
            info["path"] = str(wav.resolve())
            info["storage_root"] = str(p_dir_res)
            info["mtime_iso"] = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat()
            if default_res is not None and wav.is_relative_to(default_res):
                info["storage_location"] = "default"
            elif any(wav.is_relative_to(er) for er in ext_roots):
                info["storage_location"] = "external"
            else:
                info["storage_location"] = "legacy"
            results.append(info)

    for stale in cache.keys() - seen_paths:
        del cache[stale]
    return sorted(results, key=lambda x: x.get("filename", ""))


def _resolve_managed_po_backup(root: str | Path, file_path: str | Path) -> Path:
    raw = str(file_path or '').strip()
    if not raw or '\x00' in raw:
        raise ValueError('Missing backup file')
    requested = Path(raw)
    if requested.is_symlink():
        raise ValueError('Symlinked backups are not supported')
    roots = [p.resolve() for p in po33_backup_dirs(root)]
    candidate = (requested if requested.is_absolute() else roots[0] / requested).resolve()
    if not candidate.is_file() or candidate.is_symlink() or candidate.suffix.lower() != '.wav':
        raise ValueError('Archivo WAV de respaldo no encontrado')
    if not any(candidate.is_relative_to(r) for r in roots):
        raise ValueError('Backup outside the library')
    return candidate


def copy_po_backup_to_target(root: str | Path, file_path: str | Path, destination_mode: str) -> dict:
    """Copia bit-a-bit un backup WAV (y su .po.json) entre la librería de BeatOS y la externa."""
    from po_backup_protocols import read_sidecar, write_sidecar
    if destination_mode not in ('default', 'external'):
        raise ValueError('Destino no válido: usa "default" o "external"')
    src = _resolve_managed_po_backup(root, file_path)
    if destination_mode == 'default':
        dest_root = default_po_backup_dir(root)
        dest_root.mkdir(parents=True, exist_ok=True)
        dest_root = dest_root.resolve()
        if not dest_root.is_relative_to(Path(root).resolve()):
            raise ValueError('Carpeta de respaldos fuera de la biblioteca')
    else:
        cfg = load_po_backup_config(root)
        ext_raw = cfg.get('external_dir', '')
        if not ext_raw:
            raise ValueError('No hay carpeta externa configurada para copiar el backup')
        dest_root = _validate_external_po_dir(ext_raw, allow_create=False)
        if not os.access(dest_root, os.W_OK):
            raise ValueError('La carpeta externa no tiene permisos de escritura')

    with src.open('rb') as sf:
        src_digest = hashlib.file_digest(sf, 'sha256').hexdigest()
    meta = read_sidecar(src, src_digest)
    model_sub = meta['model'] if meta else None
    target_dir = (dest_root / model_sub) if model_sub else dest_root
    if target_dir.exists() and target_dir.is_symlink():
        raise ValueError('La subcarpeta destino es un enlace simbólico')
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target_dir.resolve().is_relative_to(dest_root):
        raise ValueError('Destino fuera de la raíz permitida')

    target = target_dir / src.name
    with PO_IMPORT_LOCK:
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise ValueError('Existe un enlace en el destino; no se ha sustituido')
            with target.open('rb') as ef:
                existing_digest = hashlib.file_digest(ef, 'sha256').hexdigest()
            if existing_digest != src_digest:
                raise ValueError('Existe otro archivo diferente con el mismo nombre en destino')
        else:
            temporary = None
            try:
                with src.open('rb') as sf, tempfile.NamedTemporaryFile(
                    dir=target_dir, prefix='.po-copy-', suffix='.tmp', delete=False
                ) as out:
                    temporary = Path(out.name)
                    shutil.copyfileobj(sf, out, length=64 * 1024)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    with target.open('rb') as tf:
        copied_digest = hashlib.file_digest(tf, 'sha256').hexdigest()
    if copied_digest != src_digest:
        raise ValueError('Error de integridad al copiar el WAV al destino')

    if meta:
        write_sidecar(
            target,
            meta['model'],
            meta['project'],
            source=meta.get('source_filename') or src.name,
            notes=meta.get('notes', ''),
        )
    info = inspect_po33_backup(target)
    return {
        **info,
        'model': meta['model'] if meta else 'UNSPECIFIED',
        'project': meta['project'] if meta else target.stem,
        'notes': meta.get('notes', '') if meta else '',
        'storage_location': destination_mode,
        'storage_root': str(dest_root),
    }


def update_po_backup_metadata(root: str | Path, file_path: str | Path, *, project: str | None = None, notes: str | None = None) -> dict:
    """Actualiza nombre de proyecto/notas en `.po.json` sin alterar el WAV original."""
    from po_backup_protocols import update_sidecar_metadata
    target = _resolve_managed_po_backup(root, file_path)
    meta = update_sidecar_metadata(target, project=project, notes=notes)
    info = inspect_po33_backup(target)
    return {
        **info,
        'model': meta['model'],
        'project': meta['project'],
        'notes': meta.get('notes', ''),
        'device_restore_verified': False,
        'payload_verified': False,
    }


def delete_po_backup(root: str | Path, file_path: str | Path) -> dict:
    """Elimina un respaldo WAV gestionado y su metadato lateral `.po.json`."""
    target = _resolve_managed_po_backup(root, file_path)
    sidecar = target.with_suffix('.po.json')
    sidecar_deleted = False
    with PO_IMPORT_LOCK:
        target.unlink()
        if sidecar.exists() and not sidecar.is_symlink() and sidecar.is_file():
            sidecar.unlink()
            sidecar_deleted = True
    return {'deleted': True, 'path': str(target), 'sidecar_deleted': sidecar_deleted}


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

def _normalize_pads_input(
    pads: Any,
    source_root: Path,
    gain_profile: str = "smart_pcm",
) -> Dict[int, Dict[str, Any]]:
    """Normaliza una lista o diccionario de pads del Rack al esquema interno indexado por número de pad."""
    pads_dict: Dict[int, Dict[str, Any]] = {}
    if isinstance(pads, list):
        for item in pads:
            if not isinstance(item, dict):
                continue
            pad_num = int(item.get("pad", item.get("pad_number", 0)))
            if pad_num <= 0:
                continue
            if pad_num in pads_dict:
                raise ValueError("Pad duplicado")
            rel_path = item.get("rel_path", item.get("relPath", ""))
            src_path = item.get("source_path", "")
            if not src_path and rel_path:
                src_path = str(source_root / str(rel_path).lstrip("/"))

            raw_sname = (item.get("sample_name") or item.get("sampleName") or "").strip()
            fallback_stem = Path(rel_path or src_path).stem if (rel_path or src_path) else ""
            stype = item.get("sound_type", item.get("soundType", "")) or detect_sound_type(raw_sname or fallback_stem or src_path)
            raw_vol = item.get("volume")
            vol_locked = bool(item.get("volume_locked"))
            if raw_vol is not None and (not math.isfinite(float(raw_vol)) or vol_locked or abs(float(raw_vol) - 0.707946) >= 1e-5):
                vol_val = float(raw_vol)
            elif gain_profile == "uniform_b":
                vol_val = default_pad_volume(stype, "uniform_b")
            else:
                vol_val = default_pad_volume(stype, "hierarchical_a")
            pad_entry: Dict[str, Any] = {
                "pad_number": pad_num,
                "sample_name": raw_sname or fallback_stem,
                "pad_sample_name": item.get("pad_sample_name", ""),
                "sample_file": Path(src_path or rel_path).name if (src_path or rel_path) else "",
                "sound_type": stype,
                "source_path": src_path,
                "volume": vol_val,
                "volume_locked": vol_locked,
                "pan": float(item.get("pan", 0.5)),
                "tune": int(item.get("tune", 0)),
                "mute_group": pad_mute_group(item),
                "monophonic": item.get("monophonic", True),
            }
            for ext_key in (
                "fine_tune", "fineTune", "root_note", "rootNote",
                "key_track", "keyTrack", "keyTrackEnable",
                "trigger_mode", "triggerMode", "playMode",
                "reverse", "direction", "loop", "loop_mode", "loopMode",
                "tail_length", "tailLength", "sample_offset", "offset",
                "pad_link", "padLink", "submix", "volume_locked",
            ):
                if ext_key in item and item[ext_key] is not None:
                    pad_entry[ext_key] = item[ext_key]
            pads_dict[pad_num] = pad_entry
    elif isinstance(pads, dict):
        for k, v in pads.items():
            if not isinstance(v, dict):
                continue
            pad_num = int(k)
            entry = dict(v)
            rel_val = entry.get("rel_path") or entry.get("relPath") or ""
            if not entry.get("source_path") and rel_val:
                entry["source_path"] = str(source_root / str(rel_val).lstrip("/"))
            entry.setdefault("pad_number", pad_num)
            pads_dict[pad_num] = entry
    return pads_dict


def create_kit(
    kit_name: str,
    pads: list[dict] | dict,
    target: str = "universal",
    source_root: Optional[str | Path] = None,
    output_base_dir: Optional[str | Path] = None,
    tempo: float = 120.0,
    po_options: Optional[dict] = None,
    mpc_options: Optional[dict] = None,
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

    opts = mpc_options if isinstance(mpc_options, dict) else {}
    gain_profile = str(opts.get("gain_profile") or "smart_pcm").strip().lower()

    pads_dict = _normalize_pads_input(pads, source_root, gain_profile=gain_profile)

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
    effective_mpc_name = _effective_mpc_project_name(clean_kit_name, opts)
    if target_lower in ('universal', 'mpc') and opts.get('install_to_mpc_projects'):
        projects = source_root / 'MPC-Sample' / 'Projects'
        if (projects / f'{effective_mpc_name}.xpj').exists() or (projects / f'{effective_mpc_name}_[ProjectData]').exists():
            raise FileExistsError('Ya existe el proyecto MPC o su carpeta de muestras. Elige otro nombre para conservar el original.')
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
            proj_path = export_mpc_project(clean_kit_name, pads_dict, mpc_dir, tempo=tempo, mpc_options=opts)
            prog_path = export_mpc_program(clean_kit_name, pads_dict, mpc_dir, copy_samples=True)
            mpc_info: Dict[str, Any] = {
                "project_path": proj_path,
                "program_path_root": prog_path,
            }
            if opts.get("install_to_mpc_projects"):
                projects_root = source_root / "MPC-Sample" / "Projects"
                projects_root.mkdir(parents=True, exist_ok=True)
                src_xpj = Path(proj_path)
                installed_name = src_xpj.stem
                src_pdata = src_xpj.parent / f"{installed_name}_[ProjectData]"
                dst_xpj = projects_root / f"{installed_name}.xpj"
                dst_pdata = projects_root / f"{installed_name}_[ProjectData]"
                if dst_xpj.exists() or dst_pdata.exists():
                    raise FileExistsError('Ya existe el proyecto MPC o su carpeta de muestras. Elige otro nombre.')
                # Never replace an existing data directory, and publish the project only after its samples.
                if not src_pdata.is_dir():
                    raise ValueError('Falta la carpeta de muestras del proyecto MPC')
                shutil.copytree(src_pdata, dst_pdata)
                with dst_xpj.open('xb') as dst, src_xpj.open('rb') as src:
                    shutil.copyfileobj(src, dst)
                mpc_info["installed_project_path"] = str(dst_xpj)
            targets_result["mpc"] = mpc_info

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
    """Genera una carátula PNG real de 320x320 px (estilo vinilo + pads MPC) sin dependencias externas."""
    import zlib
    import hashlib

    seed_bytes = hashlib.sha256(f"{title}|{manufacturer}".encode("utf-8", errors="ignore")).digest()
    palettes = (
        ((16, 12, 10), (34, 24, 18), (224, 168, 68), (242, 92, 42)),     # Warm Vinyl Gold / Bolero
        ((12, 16, 28), (22, 32, 54), (56, 189, 248), (250, 204, 21)),    # Cyan Synthwave
        ((18, 12, 26), (34, 20, 48), (168, 85, 247), (34, 211, 238)),    # Arcane Purple / Po-20
        ((14, 22, 18), (24, 42, 34), (52, 211, 153), (245, 158, 11)),    # Jungle Emerald
        ((24, 14, 16), (48, 22, 26), (239, 68, 68), (251, 191, 36)),     # MPC Classic Red
    )
    low_t = f"{title} {manufacturer}".lower()
    if any(k in low_t for k in ("bolero", "ranchera", "astro1deep", "vinyl", "lofi", "oldies", "soul")):
        p_idx = 0
    elif any(k in low_t for k in ("dnb", "amen", "jungle", "dub", "test press")):
        p_idx = 3
    elif any(k in low_t for k in ("araab", "trap", "mpc", "boombap")):
        p_idx = 4
    else:
        p_idx = seed_bytes[0] % len(palettes)
    bg0, bg1, ac0, ac1 = palettes[p_idx]

    w = h = 320
    cx, cy = w * 0.5, h * 0.44
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        dy = y - cy
        in_bottom_strip = 248 <= y <= 298
        pad_r = (y - 252) // 11 if in_bottom_strip else -1
        pad_y_in = (y - 252) % 11 if in_bottom_strip else 99
        for x in range(w):
            dx = x - cx
            dist = math.sqrt(dx * dx + dy * dy)
            t = max(0.0, min(1.0, 1.0 - dist / 220.0))
            r = int(bg0[0] * (1.0 - t) + bg1[0] * t)
            g = int(bg0[1] * (1.0 - t) + bg1[1] * t)
            b = int(bg0[2] * (1.0 - t) + bg1[2] * t)

            # Borde exterior sutil + esquinas redondeadas
            if x < 4 or x >= w - 4 or y < 4 or y >= h - 4:
                r, g, b = ac0[0], ac0[1], ac0[2]
            elif 8 <= x <= w - 9 and 8 <= y <= h - 9 and (x < 10 or x >= w - 10 or y < 10 or y >= h - 10):
                r = int(r * 0.65 + ac1[0] * 0.35)
                g = int(g * 0.65 + ac1[1] * 0.35)
                b = int(b * 0.65 + ac1[2] * 0.35)
            # Disco de vinilo concéntrico
            elif 26.0 <= dist <= 112.0:
                groove = 0.72 + 0.28 * math.sin(dist * 0.95)
                sheen = max(0.0, 1.0 - abs(abs(dx) - abs(dy)) / 42.0) * 0.22
                r = min(255, int(14 * groove + ac0[0] * sheen))
                g = min(255, int(14 * groove + ac0[1] * sheen))
                b = min(255, int(16 * groove + ac0[2] * sheen))
            elif 12.0 <= dist < 26.0:
                r, g, b = ac0[0], ac0[1], ac0[2]
            elif dist < 6.0:
                r, g, b = 12, 12, 14
            # Grilla inferior de 16 pads (4x4 iluminados)
            elif in_bottom_strip and 24 <= x <= 110 and 0 <= pad_r < 4 and pad_y_in < 8:
                pad_c = (x - 24) // 22
                pad_x_in = (x - 24) % 22
                if 0 <= pad_c < 4 and pad_x_in < 18:
                    bit = (pad_r * 4 + pad_c + seed_bytes[1]) % 5
                    use_col = ac1 if bit == 0 else (ac0 if bit <= 2 else (72, 78, 92))
                    r, g, b = use_col[0], use_col[1], use_col[2]
            # Barras de forma de onda decorativa a la derecha de los pads
            elif 250 <= y <= 296 and 126 <= x <= 296 and ((x - 126) % 7 < 4):
                bar_idx = (x - 126) // 7
                bar_h = 8 + ((seed_bytes[bar_idx % len(seed_bytes)] * 17 + bar_idx * 13) % 34)
                if abs(y - 273) <= bar_h // 2:
                    use_w = ac0 if bar_idx % 3 else ac1
                    r, g, b = use_w[0], use_w[1], use_w[2]

            rows.append(max(0, min(255, r)))
            rows.append(max(0, min(255, g)))
            rows.append(max(0, min(255, b)))

    def _chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(rows), level=6)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


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
        r_name = (re.sub(r"[^a-zA-Z0-9_\-\s]", "", (rack_kit_name or f"{clean_mfg}_Rack_Kit").strip()).strip() or f"{clean_mfg}_Rack_Kit")[:60]
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
                src_raw = pinfo.get("source_path") or ""
                if not src_raw:
                    continue
                src = Path(src_raw)
                if not src.is_file():
                    continue
                dest_name = f"{pad_num:02d} {src.stem[:100]} ({r_name[:60]}).wav"
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
            if local_pads:
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
            if pad_idx < 1 or pad_idx > 128:
                continue
            fp = pinfo.get("full_path") or ""
            if not fp or not Path(fp).is_file():
                continue
            src = Path(fp)
            base_name = f"{src.stem[:110]}{src.suffix}"
            dest_name = base_name if re.match(r"^\d{2}\s", base_name) else f"{pad_idx:02d} {base_name}"
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

    rel_exp = exp_dir.relative_to(root).as_posix()
    total_samples = sum(int(k.get("pads", 0)) for k in exported_kits)
    return {
        "success": True,
        "title": clean_title,
        "manufacturer": clean_mfg,
        "artist_subfolder": clean_sub,
        "expansion_path": rel_exp,
        "expansion_rel_path": rel_exp,
        "artwork": f"{rel_exp}/{art_name}",
        "zip_download_path": zip_rel,
        "zip_rel_path": zip_rel,
        "kits_count": len(exported_kits),
        "kit_count": len(exported_kits),
        "sample_count": total_samples,
        "kits": exported_kits,
    }


def _is_valid_image_bytes(raw: bytes) -> Optional[str]:
    if not raw or len(raw) < 16:
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if raw[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    return None


def update_expansion_metadata(
    expansion_path: str | Path,
    title: Optional[str] = None,
    manufacturer: Optional[str] = None,
    description: Optional[str] = None,
    cover_bytes: Optional[bytes] = None,
    cover_filename: str = "",
    regenerate_cover: bool = False,
    rename_folder: bool = False,
    source_root: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    Edita de forma segura el título, fabricante, descripción y carátula (imagen PNG/JPG/WebP o portada
    temática regenerada) de una expansión MPC en `Expansions/<Pack>/Expansion.xml`.
    Opcionalmente renombra la carpeta física sin romper referencias relativas internas.
    """
    root = Path(source_root).resolve() if source_root else (
        Path("/Volumes/MPCSMPL").resolve() if Path("/Volumes/MPCSMPL").is_dir() else Path.cwd().resolve()
    )
    exp_base = (root / "Expansions").resolve()
    raw_rel = str(expansion_path or "").strip().lstrip("/")
    if not raw_rel:
        raise ValueError("Ruta de expansión obligatoria.")
    cand = (root / raw_rel).resolve()
    if not cand.is_dir() or not cand.is_relative_to(exp_base) or cand == exp_base:
        raise ValueError("Ruta de expansión fuera del directorio Expansions")

    old_rel = cand.relative_to(root).as_posix()
    xml_path = cand / "Expansion.xml"
    if xml_path.is_file():
        try:
            tree = ET.parse(str(xml_path))
            xml_root = tree.getroot()
        except ET.ParseError:
            xml_root = ET.Element("expansion", version="2.0.0.1")
    else:
        xml_root = ET.Element("expansion", version="2.0.0.1")

    def _set_el(tag: str, val: str) -> ET.Element:
        el = xml_root.find(tag)
        if el is None:
            el = ET.SubElement(xml_root, tag)
        el.text = val
        return el

    cur_title = (xml_root.findtext("title") or cand.name).strip()
    cur_mfg = (xml_root.findtext("manufacturer") or "Astro1Deep").strip()
    cur_desc = (xml_root.findtext("description") or "").strip()
    cur_img = (xml_root.findtext("img") or "").strip()

    new_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", (title if title is not None else cur_title).strip()).strip(".")
    if not new_title:
        raise ValueError("El título de la expansión es obligatorio.")
    new_mfg = (manufacturer if manufacturer is not None else cur_mfg).strip() or cur_mfg or "Astro1Deep"
    new_desc = (description if description is not None else cur_desc).strip()

    new_img = cur_img
    if cover_bytes:
        det_ext = _is_valid_image_bytes(cover_bytes)
        if not det_ext:
            raise ValueError("Imagen no válida: sube un PNG, JPG o WebP real.")
        art_name = f"Artwork{det_ext}"
        (cand / art_name).write_bytes(cover_bytes)
        if cur_img and cur_img != art_name and (cand / cur_img).is_file() and cur_img.lower().startswith("artwork."):
            (cand / cur_img).unlink(missing_ok=True)
        new_img = art_name
    elif regenerate_cover or not cur_img or not (cand / cur_img).is_file() or (cand / cur_img).stat().st_size <= 512:
        art_name = "Artwork.png"
        (cand / art_name).write_bytes(_generate_default_expansion_svg_png(new_title, new_mfg))
        if cur_img and cur_img != art_name and (cand / cur_img).is_file() and cur_img.lower().startswith("artwork."):
            (cand / cur_img).unlink(missing_ok=True)
        new_img = art_name

    if xml_root.find("identifier") is None:
        slug_id = re.sub(r"[^a-z0-9]+", ".", f"{new_mfg}.{new_title}".lower()).strip(".") or "custom"
        _set_el("identifier", f"com.beatos.expansion.{slug_id}")
    if xml_root.find("version") is None:
        _set_el("version", "1.0.0")
    if xml_root.find("type") is None:
        _set_el("type", "drum")
    _set_el("title", new_title)
    _set_el("manufacturer", new_mfg)
    _set_el("img", new_img)
    if description is not None or xml_root.find("description") is not None:
        _set_el("description", new_desc)

    xml_tree = ET.ElementTree(xml_root)
    ET.indent(xml_tree, space="   ", level=0)
    xml_tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)

    final_dir = cand
    if rename_folder and new_title != cand.name:
        target_dir = (exp_base / new_title).resolve()
        if not target_dir.is_relative_to(exp_base) or target_dir == exp_base:
            raise ValueError("Ruta de expansión fuera del directorio Expansions")
        if target_dir.exists() and target_dir != cand:
            raise ValueError(f"Ya existe una expansión llamada '{new_title}'.")
        cand.rename(target_dir)
        final_dir = target_dir

    clear_expansion_kits_cache()
    final_rel = final_dir.relative_to(root).as_posix()
    return {
        "success": True,
        "old_path": old_rel,
        "expansion_path": final_rel,
        "expansion_rel_path": final_rel,
        "title": new_title,
        "manufacturer": new_mfg,
        "description": new_desc,
        "img": new_img,
        "cover_url": f"{final_rel}/{new_img}" if new_img else "",
        "renamed_folder": final_rel != old_rel,
    }


_NOTE_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTE_NAME_TO_PC = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4,
    "f": 5, "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9,
    "a#": 10, "bb": 10, "b": 11,
}
_KRUMHANSL_KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_KRUMHANSL_MAJ = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KRUMHANSL_MIN = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_KEY_TO_CAMELOT = {
    "B Maj": "1B", "G# Min": "1A", "Ab Min": "1A",
    "F# Maj": "2B", "Gb Maj": "2B", "D# Min": "2A", "Eb Min": "2A",
    "C# Maj": "3B", "Db Maj": "3B", "Bb Min": "3A", "A# Min": "3A",
    "Ab Maj": "4B", "G# Maj": "4B", "F Min": "4A",
    "Eb Maj": "5B", "D# Maj": "5B", "C Min": "5A",
    "Bb Maj": "6B", "A# Maj": "6B", "G Min": "6A",
    "F Maj": "7B", "D Min": "7A",
    "C Maj": "8B", "A Min": "8A",
    "G Maj": "9B", "E Min": "9A",
    "D Maj": "10B", "B Min": "10A",
    "A Maj": "11B", "F# Min": "11A", "Gb Min": "11A",
    "E Maj": "12B", "C# Min": "12A", "Db Min": "12A",
}

_CAMELOT_REGEX = re.compile(r"^([1-9]|1[0-2])([AB])$", re.IGNORECASE)


def parse_musical_key_info(key_str: str) -> Optional[Dict[str, Any]]:
    """Convierte una cadena de tonalidad ('C Min', 'Ab Maj', 'Am', '8A') en {key, pitch_class, mode, camelot}."""
    raw = str(key_str or "").strip()
    if not raw or raw.lower() in ("percussion", "atonal", "none", "unknown", "percusión / atonal"):
        return None
    m_cam = _CAMELOT_REGEX.match(raw)
    if m_cam:
        cam = f"{int(m_cam.group(1))}{m_cam.group(2).upper()}"
        for k_name, c_val in _KEY_TO_CAMELOT.items():
            if c_val == cam:
                root_p, mode_p = k_name.split()
                return {
                    "key": k_name,
                    "note_root": root_p,
                    "mode": mode_p,
                    "pitch_class": _NOTE_NAME_TO_PC.get(root_p.lower()),
                    "camelot": cam,
                }
    m = re.match(r"^\s*([A-Ga-g])([#b♯♭]?)\s*(major|minor|maj|min|m)?\s*$", raw, re.I)
    if not m:
        return None
    root_ch, acc_ch, mode_raw = m.groups()
    acc_norm = acc_ch.replace("♯", "#").replace("♭", "b").lower()
    pc = _NOTE_NAME_TO_PC.get((root_ch.upper() + acc_norm).lower())
    if pc is None:
        return None
    canon_root = _KRUMHANSL_KEYS[pc]
    if mode_raw:
        is_min = (mode_raw != "M") and mode_raw.lower() in ("m", "min", "minor")
        mode_lbl = "Min" if is_min else "Maj"
    else:
        mode_lbl = "Min"
    key_full = f"{canon_root} {mode_lbl}"
    return {
        "key": key_full,
        "note_root": canon_root,
        "mode": mode_lbl,
        "pitch_class": pc,
        "camelot": _KEY_TO_CAMELOT.get(key_full, ""),
    }


def camelot_compatibility_score(key_a: str, key_b: str) -> tuple[float, str]:
    """Evalúa afinidad armónica entre dos tonalidades según rueda Camelot (0.0..1.0 + etiqueta)."""
    pa = parse_musical_key_info(key_a)
    pb = parse_musical_key_info(key_b)
    if not pa or not pb:
        return 0.5, "Sin tonalidad fija"
    if pa["key"] == pb["key"]:
        return 1.0, f"Misma tonalidad ({pa['camelot']})"
    ca, cb = pa.get("camelot") or "", pb.get("camelot") or ""
    ma, mb = _CAMELOT_REGEX.match(ca), _CAMELOT_REGEX.match(cb)
    if not ma or not mb:
        dist_pc = min((pa["pitch_class"] - pb["pitch_class"]) % 12, (pb["pitch_class"] - pa["pitch_class"]) % 12)
        return (0.85, "Quinta justa") if dist_pc == 5 else (0.35, "Tonalidad distante")
    na, la = int(ma.group(1)), ma.group(2)
    nb, lb = int(mb.group(1)), mb.group(2)
    wheel_dist = min((na - nb) % 12, (nb - na) % 12)
    if na == nb and la != lb:
        return 0.94, f"Relativa Maj/Min ({ca} ↔ {cb})"
    if wheel_dist == 1 and la == lb:
        return 0.88, f"Quinta/Cuarta armónica ({ca} ↔ {cb})"
    if wheel_dist == 2 and la == lb:
        return 0.68, f"Salto energético +2 ({ca} → {cb})"
    if wheel_dist == 1 and la != lb:
        return 0.62, f"Diagonal dominante ({ca} ↔ {cb})"
    return 0.18, f"Choque armónico ({pa['key']} vs {pb['key']})"


def compute_pitch_shift_to_compatible_key(src_pc: int, target_pc: int) -> tuple[int, str]:
    """Calcula el menor desplazamiento en semitonos [-6..+6] para cuadrar tónica o quinta con la tonalidad ancla."""
    unison_diff = (int(target_pc) - int(src_pc)) % 12
    if unison_diff > 6:
        unison_diff -= 12
    fifth_pc = (int(target_pc) + 7) % 12
    fifth_diff = (fifth_pc - int(src_pc)) % 12
    if fifth_diff > 6:
        fifth_diff -= 12
    if abs(unison_diff) <= abs(fifth_diff) + 1:
        return int(unison_diff), "tónica"
    return int(fifth_diff), "quinta justa"


def _pearson_corr(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n == 0:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den > 1e-12 else 0.0


def _goertzel_power(buf: List[float], sr: int, freq: float) -> float:
    w = 2.0 * math.pi * freq / sr
    coeff = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for x in buf:
        s0 = x + coeff * s1 - s2
        s2, s1 = s1, s0
    return max(0.0, s2 * s2 + s1 * s1 - coeff * s1 * s2)


def _extract_explicit_key_from_name(stem: str) -> Optional[Dict[str, Any]]:
    """Extrae tonalidad o nota explícita de un nombre de archivo evitando falsos positivos en letras sueltas."""
    s = str(stem or "").replace("♯", "#").replace("♭", "b")
    m_mode = re.search(
        r"(?<![A-Za-z0-9])([A-Ga-g])([#b]?)[ _\-]*(major|minor|maj|min|m)(?=$|[^A-Za-z]|[0-9])",
        s,
        re.IGNORECASE,
    )
    if m_mode:
        root, acc, mode = m_mode.groups()
        root_norm = root.upper() + acc.lower()
        pc = _NOTE_NAME_TO_PC.get(root_norm.lower())
        is_minor = (mode != "M") and mode.lower() in ("m", "min", "minor")
        canon_root = _KRUMHANSL_KEYS[pc] if pc is not None else root_norm
        key_full = f"{canon_root} {'Min' if is_minor else 'Maj'}"
        return {
            "key": key_full,
            "note_root": canon_root,
            "mode": "Min" if is_minor else "Maj",
            "pitch_class": pc,
            "camelot": _KEY_TO_CAMELOT.get(key_full),
        }
    m_note = re.search(r"(?i)(?:^|[ _\-\(\[])(?:key[ _\-]*)?([A-G])([#b]?)(?:[0-8])(?![A-Za-z0-9])", s)
    if not m_note:
        m_note = re.search(r"(?i)(?:^|[ _\-\(\[])key[ _\-]+([A-G])([#b]?)(?=$|[\s_\-\)\]])", s)
    if m_note:
        root_norm = m_note.group(1).upper() + m_note.group(2).lower()
        pc = _NOTE_NAME_TO_PC.get(root_norm.lower())
        canon_root = _KRUMHANSL_KEYS[pc] if pc is not None else root_norm
        return {"key": None, "note_root": canon_root, "mode": None, "pitch_class": pc, "camelot": None}
    return None


def analyze_audio_musical_metadata(
    wav_path: str | Path,
    sound_type_hint: str = "",
    duration_hint: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Analiza BPM y Key Root reales de un archivo WAV de forma rápida y segura:
      - En loops melódicos / frases largas (>= 0.90s): cromagrama Goertzel + correlación Krumhansl (24 tonalidades).
      - En bajos/808s/kicks tonales: autocorrelación con umbral estricto para evitar falsos C en percusión seca.
      - En loops (>= 1.25s): estima BPM real mediante envolvente de onsets/RMS.
    """
    p = Path(wav_path)
    stype = str(sound_type_hint or detect_sound_type(p.name)).upper()
    if stype == "MELODY_LOOP":
        stype = "MELODIC_LOOP"
    fn_key_info = _extract_explicit_key_from_name(p.stem)
    fn_bpm = _extract_explicit_bpm_from_text(p.stem)
    low_stem = p.stem.lower()
    explicit_perc_tokens = ("perc", "conga", "bongo", "rim", "cowbell", "shaker", "maraca", "tamb", "clave", "cabasa", "wood", "guiro")
    explicit_melodic_tokens = (
        "melod", "loop", "chord", "piano", "guitar", "bolero", "ranchera", "soul", "jazz",
        "string", "brass", "horn", "organ", "theme", "vinyl", "song", "phrase", "music",
        "vox", "vocal", "chop", "pad", "flute", "sax", "rhodes", "synth", "harp", "violin",
    )

    try:
        with wave.open(str(p), "rb") as w:
            sr = w.getframerate() or 44100
            n_ch = w.getnchannels()
            sw = w.getsampwidth()
            n_frames = w.getnframes()
            dur_sec = n_frames / float(sr) if sr > 0 else 0.0
            if sw == 2 and n_ch in (1, 2) and n_frames >= 1024:
                # Leer hasta 18 segundos para análisis ágil y fiel
                read_frames = min(n_frames, sr * 18)
                raw = w.readframes(read_frames)
                unpacked = struct.unpack(f"<{len(raw) // 2}h", raw)
                if n_ch == 2:
                    pcm = [0.5 * (unpacked[i] + unpacked[i + 1]) for i in range(0, len(unpacked) - 1, 2)]
                else:
                    pcm = [float(x) for x in unpacked]
            else:
                pcm = []
    except Exception:
        pcm = []
        sr = 44100
        dur_sec = float(duration_hint or 0.0)

    if not pcm:
        try:
            raw_s = _convert_audio(p, mono=True, sample_rate=44100)
            pcm = [float(x) for x in raw_s[: 44100 * 18]]
            sr = 44100
            dur_sec = len(raw_s) / 44100.0
        except Exception:
            pcm = []

    # Promover muestras largas no-batería (fallback PERCUSSION) si tienen rasgos o duración de loop/frase
    if not sound_type_hint and stype == "PERCUSSION" and dur_sec >= 1.35:
        if any(tok in low_stem for tok in explicit_melodic_tokens) or (
            dur_sec >= 2.2 and not any(tok in low_stem for tok in explicit_perc_tokens)
        ):
            stype = "MELODIC_LOOP"

    is_percussive_non_tonal = stype in ("SNARE", "CLAP", "HIHAT", "CYMBAL", "PERCUSSION", "FX", "ROLL_FILL")

    res: Dict[str, Any] = {
        "duration_sec": round(dur_sec, 3),
        "bpm": int(round(fn_bpm)) if fn_bpm else None,
        "bpm_confidence": 0.9 if fn_bpm else 0.0,
        "key": fn_key_info["key"] if fn_key_info and fn_key_info.get("key") else None,
        "note_root": fn_key_info["note_root"] if fn_key_info else None,
        "mode": fn_key_info["mode"] if fn_key_info else None,
        "pitch_class": fn_key_info["pitch_class"] if fn_key_info else None,
        "camelot": fn_key_info["camelot"] if fn_key_info else None,
        "key_confidence": 0.85 if (fn_key_info and fn_key_info.get("key")) else (0.45 if fn_key_info else 0.0),
        "f0_hz": 0.0,
        "cents_offset": 0,
        "is_tonal_content": False,
    }
    if not pcm or len(pcm) < 2048:
        return res

    # 1. Estimación rápida de BPM en loops / muestras >= 1.25s si no venía explícito
    if dur_sec >= 1.25 and res["bpm"] is None:
        # Envolvente RMS a ~100 Hz
        step = max(1, sr // 100)
        env = []
        prev_rms = 0.0
        for pos in range(0, len(pcm) - step, step):
            seg = pcm[pos : pos + step]
            rms = math.sqrt(sum(x * x for x in seg) / len(seg))
            env.append(max(0.0, rms - prev_rms * 0.85))
            prev_rms = rms
        if len(env) >= 80:
            rate_env = sr / float(step)
            best_bpm, best_ac, second_ac = 0, -1.0, -1.0
            ac_scores: Dict[int, float] = {}
            for cand_bpm in range(62, 181):
                lag = int(round((60.0 / cand_bpm) * rate_env))
                n_overlap = len(env) - lag
                if lag <= 5 or n_overlap < 25 or lag >= len(env) // 2:
                    continue
                s = sum(env[k] * env[k + lag] for k in range(n_overlap)) / float(n_overlap)
                # Ligero refuerzo a octavas métricas comunes 72..145
                if 70 <= cand_bpm <= 145:
                    s *= 1.08
                ac_scores[cand_bpm] = s
                if s > best_ac:
                    best_ac, best_bpm = s, cand_bpm
            mean_ac = (sum(ac_scores.values()) / max(1, len(ac_scores))) or 1.0
            conf_bpm = min(0.95, max(0.0, (best_ac / mean_ac - 1.0) * 0.45)) if best_ac > 0 else 0.0
            if best_bpm and conf_bpm >= 0.22:
                # Si el pico cae en doble tiempo (>150) y su mitad (>=70) retiene >=88% de fuerza, preferir pulso fundamental
                half_b = int(round(best_bpm / 2.0))
                if best_bpm > 150 and half_b in ac_scores and ac_scores[half_b] >= best_ac * 0.88:
                    best_bpm = half_b
                res["bpm"] = int(best_bpm)
                res["bpm_confidence"] = round(conf_bpm, 2)

    # 2. Nunca inventar tonalidad sobre percusión no-tonal ni drum_loops puros sin nombre melódico
    if is_percussive_non_tonal or (stype == "DRUM_LOOP" and not fn_key_info):
        if stype in ("SNARE", "CLAP", "HIHAT", "CYMBAL", "PERCUSSION", "FX", "ROLL_FILL"):
            res["key"] = None
            res["pitch_class"] = None
            res["note_root"] = None
            res["camelot"] = None
            res["key_confidence"] = 0.0
        return res

    # 3. Análisis armónico multi-ventana (Cromagrama + Krumhansl) para muestras largas/melódicas >= 0.90s
    if dur_sec >= 0.90 and stype in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL", "STEM", "UNKNOWN", "BASS_808"):
        decim = max(1, sr // 11025)
        dsr = sr // decim
        arr = [pcm[i] / 32768.0 for i in range(0, len(pcm), decim)]
        wl = 2048
        if len(arr) >= wl:
            step_w = max(wl // 2, (len(arr) - wl) // 12)
            chroma_sum = [0.0] * 12
            used_wins = 0
            for wi in range(12):
                pos = wi * step_w
                if pos + wl > len(arr):
                    break
                seg = [arr[pos + k] * (0.5 - 0.5 * math.cos(2.0 * math.pi * k / (wl - 1))) for k in range(wl)]
                rms = math.sqrt(sum(x * x for x in seg) / wl)
                if rms < 0.012:
                    continue
                used_wins += 1
                for pc in range(12):
                    p_val = 0.0
                    for octv, wgt in ((2, 1.3), (3, 1.2), (4, 1.0), (5, 0.7)):
                        f = 440.0 * (2.0 ** (((octv + 1) * 12 + pc - 69) / 12.0))
                        p_val += wgt * math.sqrt(_goertzel_power(seg, dsr, f))
                    chroma_sum[pc] += p_val
            if used_wins >= 2 and sum(chroma_sum) > 1e-6:
                best_k, best_r, best_pc = "C Maj", -2.0, 0
                for r_idx in range(12):
                    rot = [chroma_sum[(r_idx + i) % 12] for i in range(12)]
                    rmaj = _pearson_corr(rot, _KRUMHANSL_MAJ)
                    rmin = _pearson_corr(rot, _KRUMHANSL_MIN)
                    if rmaj > best_r:
                        best_r, best_k, best_pc = rmaj, f"{_KRUMHANSL_KEYS[r_idx]} Maj", r_idx
                    if rmin > best_r:
                        best_r, best_k, best_pc = rmin, f"{_KRUMHANSL_KEYS[r_idx]} Min", r_idx
                # Exigir correlación tonal sólida >= 0.54 (si el archivo traía key en nombre, conservarla salvo mismatch enorme)
                if best_r >= 0.54 and (res["key"] is None or res["key_confidence"] < 0.85):
                    canon_root, mode_lbl = best_k.split()
                    res["key"] = best_k
                    res["note_root"] = canon_root
                    res["mode"] = mode_lbl
                    res["pitch_class"] = best_pc
                    res["camelot"] = _KEY_TO_CAMELOT.get(best_k)
                    res["key_confidence"] = round(min(0.98, best_r), 2)
                    res["is_tonal_content"] = True

    # 4. Autocorrelación normalizada para f0 en bajos / 808s / kicks tonales / frases monofónicas
    if stype in ("BASS_808", "KICK", "KEYS_SYNTH") or (not res["is_tonal_content"] and not is_percussive_non_tonal and stype != "DRUM_LOOP"):
        start_idx = min(int(0.025 * sr), len(pcm) // 4)
        win_len = min(8192, len(pcm) - start_idx)
        if win_len >= 1024:
            seg = list(pcm[start_idx : start_idx + win_len])
            mean_v = sum(seg) / len(seg)
            seg = [x - mean_v for x in seg]
            min_lag = max(2, int(sr / 520.0))
            max_lag = min(len(seg) // 2, int(sr / 30.0))
            best_lag, best_corr = min_lag, -1.0
            corrs: Dict[int, float] = {}
            n_cmp = min(2048, len(seg) - max_lag)
            if n_cmp >= 256:
                e_base = sum(seg[i] * seg[i] for i in range(n_cmp))
                if e_base > 1e-3:
                    def _norm_ac(lag_v: int) -> float:
                        e_lag = sum(seg[i + lag_v] * seg[i + lag_v] for i in range(n_cmp))
                        denom_e = math.sqrt(e_base * e_lag)
                        if denom_e <= 1e-6:
                            return 0.0
                        return sum(seg[i] * seg[i + lag_v] for i in range(n_cmp)) / denom_e

                    min_periodic = 0.68 if stype == "KICK" else 0.50
                    hi_step1_end = min(max_lag, 360)
                    for lag in range(min_lag, hi_step1_end + 1):
                        c = _norm_ac(lag)
                        corrs[lag] = c
                        if c > best_corr:
                            best_corr, best_lag = c, lag
                    if hi_step1_end < max_lag:
                        start_low = hi_step1_end + 1
                        if (start_low - hi_step1_end) == 0:
                            start_low += 1
                        for lag in range(start_low, max_lag + 1, 2):
                            c = _norm_ac(lag)
                            corrs[lag] = c
                            if c > best_corr:
                                best_corr, best_lag = c, lag

                    # Regla McLeod/YIN: elegir el primer pico fundamental prominente para no caer en subarmónicos (2T..10T)
                    if best_corr >= min_periodic and len(corrs) >= 3:
                        peak_thr = max(min_periodic, best_corr * 0.94)
                        lags_scanned = sorted(corrs.keys())
                        for li in range(1, len(lags_scanned) - 1):
                            lg = lags_scanned[li]
                            cv = corrs[lg]
                            if cv >= peak_thr and cv >= corrs[lags_scanned[li - 1]] and cv >= corrs[lags_scanned[li + 1]]:
                                best_lag, best_corr = lg, cv
                                break

                    for lag in range(max(min_lag, best_lag - 3), min(max_lag, best_lag + 3) + 1):
                        if lag not in corrs:
                            corrs[lag] = _norm_ac(lag)
                        if corrs[lag] > best_corr:
                            best_corr, best_lag = corrs[lag], lag
                    refined_lag = float(best_lag)
                    if min_lag < best_lag < max_lag:
                        y_m1, y_0, y_p1 = corrs.get(best_lag - 1, best_corr), best_corr, corrs.get(best_lag + 1, best_corr)
                        denom = y_m1 - 2.0 * y_0 + y_p1
                        if abs(denom) > 1e-9:
                            refined_lag = best_lag + 0.5 * (y_m1 - y_p1) / denom
                    f0_hz = sr / refined_lag if refined_lag > 0 else 0.0
                    if f0_hz > 0 and best_corr >= min_periodic and (dur_sec >= 0.17 or stype != "KICK"):
                        midi_float = 69.0 + 12.0 * math.log2(f0_hz / 440.0)
                        midi_round = int(round(midi_float))
                        cents_offset = int(round((midi_float - midi_round) * 100))
                        pc = midi_round % 12
                        res["f0_hz"] = round(f0_hz, 2)
                        res["cents_offset"] = cents_offset
                        res["midi_note"] = midi_round
                        if res["pitch_class"] is None:
                            res["pitch_class"] = pc
                            res["note_root"] = _KRUMHANSL_KEYS[pc]
                            res["key_confidence"] = round(min(0.95, best_corr), 2)
                        res["is_tonal_content"] = True

    return res


def detect_sample_pitch_and_key(wav_path: str | Path) -> Dict[str, Any]:
    """
    Detecta frecuencia fundamental (f0), nota raíz (pitch_class 0..11), tonalidad armónica
    (para loops/muestras >= 0.9s), deriva de afinación A440 (cents) y Camelot.
    """
    p = Path(wav_path)
    meta = analyze_audio_musical_metadata(p)
    f0 = float(meta.get("f0_hz") or 0.0)
    pc = meta.get("pitch_class")
    midi_note = meta.get("midi_note")
    f0_pc = (int(midi_note) % 12) if (f0 > 0.0 and midi_note is not None) else pc
    note_label = ""
    if f0 > 0 and midi_note is not None and f0_pc is not None:
        octv = (int(midi_note) // 12) - 1
        note_label = f"{_NOTE_NAMES_SHARP[int(midi_note) % 12]}{octv}"
    elif meta.get("note_root"):
        note_label = str(meta["note_root"])

    cents_offset = int(meta.get("cents_offset") or 0)
    tuning_drift = cents_offset
    dur_sec = float(meta.get("duration_sec") or 0.0)
    # Medir deriva vintage A440 en loops/frases largas cuando librosa esté disponible
    if dur_sec >= 2.0 and meta.get("is_tonal_content") and not cents_offset:
        try:
            import numpy as np
            import librosa

            with wave.open(str(p), "rb") as w:
                sr_w = w.getframerate() or 44100
                nch_w = w.getnchannels()
                sw_w = w.getsampwidth()
                nf_w = w.getnframes()
                if sw_w == 2 and nch_w in (1, 2) and nf_w > sr_w * 2:
                    raw = w.readframes(min(nf_w, sr_w * 10))
                    arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                    if nch_w == 2:
                        arr = 0.5 * (arr[0::2] + arr[1::2])
                    t_est = float(librosa.estimate_tuning(y=arr, sr=sr_w, bins_per_octave=36))
                    tuning_drift = int(round(t_est * 100.0))
        except Exception:
            pass

    return {
        "f0_hz": f0,
        "note": note_label,
        "note_root": meta.get("note_root") or "",
        "key": meta.get("key") or "",
        "camelot": meta.get("camelot") or "",
        "midi_note": midi_note or ((60 + int(f0_pc)) if f0_pc is not None else None),
        "pitch_class": pc,
        "f0_pitch_class": f0_pc,
        "cents_offset": cents_offset,
        "tuning_cents_drift": tuning_drift,
        "confidence": float(meta.get("key_confidence") or 0.0),
    }


def analyze_kit_key_and_bpm(
    kit_name: str,
    sample_paths: List[str | Path],
    project_tempo: Optional[float] = None,
    project_key: Optional[str] = None,
    expansion_hint: str = "",
    meta_cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Determina la Key Root, BPM y estilo musical real de un kit o proyecto con jerarquía estricta:
      1) Referencia primaria: loops melódicos, frases largas, sintes y muestras más largas (>= 0.9s / >= 1.25s).
      2) Confirmación secundaria: 808s y kicks tonales reales verifican o refuerzan la tónica (sin inventar C Major en batería pura).
      3) Fallback inteligente: en kits puros de batería sin loops largos, asigna Key='Percussion' y BPM del estilo musical real.
    """
    resolved_files: List[tuple[Path, str, float]] = []
    for sp in sample_paths:
        cp = Path(sp)
        if not cp.is_file() or cp.name.startswith("._") or cp.suffix.lower() != ".wav":
            continue
        try:
            with wave.open(str(cp), "rb") as w:
                sr = w.getframerate() or 44100
                dur = w.getnframes() / float(sr)
        except Exception:
            dur = 0.0
        stype = detect_sound_type(cp.name)
        # Muestras >= 1.35s no marcadas como one-shot percusivo se promueven si tienen aspecto o duración de loop/frase
        low_n = cp.stem.lower()
        perc_only = ("perc", "conga", "bongo", "rim", "cowbell", "shaker", "maraca", "tamb", "clave", "cabasa", "wood", "guiro")
        if dur >= 1.35 and stype in ("PERCUSSION", "KEYS_SYNTH", "UNKNOWN") and (
            any(t in low_n for t in ("loop", "melod", "chord", "riff", "bolero", "ranchera", "soul", "jazz", "piano", "guitar", "string", "brass", "horn", "organ", "theme", "vinyl", "song", "phrase", "music", "vox", "chop", "flute", "sax"))
            or (dur >= 2.2 and not any(t in low_n for t in perc_only))
        ):
            stype = "MELODIC_LOOP"
        resolved_files.append((cp, stype, dur))

    def _get_meta(cp: Path, stype: str, dur: float) -> Dict[str, Any]:
        if meta_cache is not None:
            try:
                st = cp.stat()
                ckey = f"{cp.as_posix()}|{st.st_size}|{int(st.st_mtime)}"
                if ckey in meta_cache:
                    return meta_cache[ckey]
                m = analyze_audio_musical_metadata(cp, sound_type_hint=stype, duration_hint=dur)
                meta_cache[ckey] = m
                return m
            except Exception:
                pass
        return analyze_audio_musical_metadata(cp, sound_type_hint=stype, duration_hint=dur)

    # Separar por niveles de prioridad
    melodic_cands = [
        (cp, stype, dur) for cp, stype, dur in resolved_files
        if stype in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL", "STEM") or (dur >= 1.8 and stype == "PERCUSSION" and not any(t in cp.stem.lower() for t in perc_only))
    ]
    melodic_cands.sort(key=lambda t: (1 if t[1] == "MELODIC_LOOP" else 0, t[2]), reverse=True)

    drum_loop_cands = [
        (cp, stype, dur) for cp, stype, dur in resolved_files
        if (stype == "DRUM_LOOP" or dur >= 1.25) and (cp, stype, dur) not in melodic_cands
    ]
    drum_loop_cands.sort(key=lambda t: t[2], reverse=True)

    bass_cands = [(cp, stype, dur) for cp, stype, dur in resolved_files if stype == "BASS_808"]
    kick_cands = [(cp, stype, dur) for cp, stype, dur in resolved_files if stype == "KICK"]

    # --- 1) BPM JERÁRQUICO (loops más largos primero -> tags -> estilo/género, nunca 120 ciego) ---
    bpm_votes: Dict[int, float] = {}
    bpm_source = ""
    for cp, stype, dur in (melodic_cands + drum_loop_cands)[:10]:
        if dur < 1.2:
            continue
        m = _get_meta(cp, stype, dur)
        if m.get("bpm"):
            wgt = max(1.0, dur) * float(m.get("bpm_confidence") or 0.5)
            b_int = int(m["bpm"])
            bpm_votes[b_int] = bpm_votes.get(b_int, 0.0) + wgt
            if not bpm_source:
                bpm_source = "loop_audio" if m.get("bpm_confidence", 0) < 0.85 else "loop_tag"

    chosen_bpm: Optional[float] = None
    if bpm_votes:
        chosen_bpm = float(max(bpm_votes.items(), key=lambda kv: kv[1])[0])

    title_text = f"{kit_name} {expansion_hint}".strip()
    sample_stems = [cp.stem for cp, _, _ in resolved_files[:20]]
    context_text = f"{title_text} " + " ".join(sample_stems)
    if resolved_files:
        synth_pads = [
            {"pad": i + 1, "sample_name": cp.stem, "rel_path": str(cp), "sound_type": st, "duration_sec": dur}
            for i, (cp, st, dur) in enumerate(resolved_files[:32])
        ]
        style_info = detect_kit_style_weighted(
            kit_name=title_text,
            pad_reports=synth_pads,
            bpm=chosen_bpm,
            fallback_text=context_text,
        )
    else:
        style_info = detect_musical_style(title_text or context_text, bpm=chosen_bpm, sample_names=sample_stems if title_text else None)
    genre_style = style_info.get("style") or "Hip-Hop / Electrónica"

    if chosen_bpm is None:
        exp_bpm = _extract_explicit_bpm_from_text(kit_name) or _extract_explicit_bpm_from_text(expansion_hint)
        if exp_bpm:
            chosen_bpm = float(exp_bpm)
            bpm_source = "kit_name"
        else:
            inferred_g_bpm = infer_kit_bpm(context_text, fallback=0.0)
            if project_tempo and abs(float(project_tempo) - 120.0) > 0.5:
                chosen_bpm = float(project_tempo)
                bpm_source = "project_tempo"
            elif inferred_g_bpm > 0.0:
                chosen_bpm = float(inferred_g_bpm)
                bpm_source = "genre_inference"
            else:
                chosen_bpm = float(project_tempo or 92.0)
                bpm_source = "style_default"

    style_id = style_info.get("id", "standard")
    _slow_mid_styles = {
        "boombap", "lofi", "oldies", "bolero", "soul_vintage", "jazz_hop",
        "bossa_samba", "cumbia_son", "tango_vals", "drumless", "rnb_soul",
        "reggaeton_dancehall", "afrobeats", "psych_library",
    }
    if style_id in _slow_mid_styles:
        if chosen_bpm >= 148.0:
            chosen_bpm = round(chosen_bpm * 0.5, 1)
        elif chosen_bpm < 64.0:
            chosen_bpm = round(chosen_bpm * 2.0, 1)
    elif style_id in ("dnb", "jungle_footwork"):
        if chosen_bpm < 115.0:
            chosen_bpm = round(chosen_bpm * 2.0, 1)
    elif chosen_bpm < 62.0:
        chosen_bpm = round(chosen_bpm * 2.0, 1)

    # --- 2) KEY ROOT JERÁRQUICA (loops melódicos primero -> confirmación 808/kick -> Percussion si atonal) ---
    pc_scores: Dict[int, float] = {}
    key_labels: Dict[int, str] = {}
    melodic_pcs: set[int] = set()

    for cp, stype, dur in melodic_cands[:12]:
        m = _get_meta(cp, stype, dur)
        pc = m.get("pitch_class")
        conf = float(m.get("key_confidence") or 0.0)
        if pc is not None and conf >= 0.45:
            wgt = conf * (1.5 + min(3.0, dur / 4.0))
            pc_scores[int(pc)] = pc_scores.get(int(pc), 0.0) + wgt
            melodic_pcs.add(int(pc))
            if m.get("key"):
                key_labels[int(pc)] = str(m["key"])

    # Confirmación secundaria con 808 / Kicks tonales
    confirmed_by_drums = False
    drum_bass_pcs: List[tuple[int, float, str, Optional[str]]] = []
    for cp, stype, dur in (bass_cands[:6] + kick_cands[:6]):
        m = _get_meta(cp, stype, dur)
        pc = m.get("pitch_class")
        conf = float(m.get("key_confidence") or 0.0)
        min_req = 0.48 if stype == "BASS_808" else 0.62
        if pc is not None and conf >= min_req:
            drum_bass_pcs.append((int(pc), conf, stype, m.get("key")))

    chosen_key: Optional[str] = None
    key_source = "atonal_drums"
    if pc_scores:
        best_pc = max(pc_scores.items(), key=lambda kv: kv[1])[0]
        for d_pc, d_conf, _, _ in drum_bass_pcs:
            if (d_pc - best_pc) % 12 in (0, 7):
                confirmed_by_drums = True
                break
        chosen_key = key_labels.get(best_pc) or f"{_KRUMHANSL_KEYS[best_pc]} {'Min' if any(x in genre_style.lower() for x in ('trap','drill','boombap','lofi','bolero')) else 'Maj'}"
        key_source = "melodic_loop"
    else:
        # Sin loops melódicos: solo si hay 808 o kick muy tonal (>= 0.64 o 808 >= 0.55)
        strong_808 = [t for t in drum_bass_pcs if (t[2] == "BASS_808" and t[1] >= 0.52) or t[1] >= 0.66]
        if strong_808:
            best_d = max(strong_808, key=lambda t: t[1])
            chosen_key = best_d[3] or f"{_KRUMHANSL_KEYS[best_d[0]]} Min"
            key_source = "808_tonal"
            confirmed_by_drums = True
        elif project_key and str(project_key).strip() not in ("", "C Major", "C") and any(t in context_text.lower() for t in ("synth", "keys", "chord", "melod")):
            chosen_key = str(project_key).strip()
            key_source = "project_explicit"
        else:
            chosen_key = "Percussion"
            key_source = "atonal_drums"

    return {
        "bpm": round(float(chosen_bpm), 1),
        "bpm_source": bpm_source,
        "musical_key": chosen_key,
        "key_source": key_source,
        "confirmed_by_drums": confirmed_by_drums,
        "genre_style": genre_style,
        "melodic_samples_count": len(melodic_cands),
        "total_wavs": len(resolved_files),
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


def _extract_explicit_bpm_from_text(text: str) -> Optional[float]:
    """Extrae un BPM numérico explícito (ej. '78 BPM', '[156]', '_92bpm', '_90BPM001') sin aplicar reglas de género."""
    if not text:
        return None
    s = str(text)
    m = re.search(r"(?:^|[\s_\-/])(5\d|[6-9]\d|1[0-8]\d)\s*bpm(?![a-z])", s, re.I)
    if m:
        val = float(m.group(1))
        if 55.0 <= val <= 190.0:
            return val
    m_brack = re.search(r"\[(\d{2,3}(?:\.\d+)?)\]", s)
    if m_brack:
        val = float(m_brack.group(1))
        if 55.0 <= val <= 200.0:
            return val
    stem = Path(s[:240]).stem
    m2 = re.search(r"[\s_-](5\d|[6-9]\d|1[0-8]\d)$", stem)
    if m2 and int(m2.group(1)) not in (808, 909, 303, 140):
        val = float(m2.group(1))
        if 55.0 <= val <= 190.0:
            return val
    return None


def _compute_hiphop_adaptation_profile(
    mode_id: str,
    label: str,
    eff_source_bpm: float,
    target_bpm: float,
    half_time_applied: bool = False,
) -> Dict[str, Any]:
    """Calcula stretch_ratio, semitonos y estrategia Warp vs Repitch estilo vinilo/SP-1200."""
    src_b = max(30.0, float(eff_source_bpm))
    stretch_ratio = max(0.55, min(1.85, float(target_bpm) / src_b))
    raw_semi = 12.0 * math.log2(stretch_ratio)
    clamped_semi = max(-7.0, min(7.0, raw_semi))
    repitch_semitones = int(round(clamped_semi))
    repitch_fine_cents = int(round((clamped_semi - repitch_semitones) * 100))
    if repitch_fine_cents >= 50:
        repitch_semitones += 1
        repitch_fine_cents -= 100
    elif repitch_fine_cents <= -50:
        repitch_semitones -= 1
        repitch_fine_cents += 100
    exact_delta = repitch_semitones + (repitch_fine_cents / 100.0)
    vinyl_repitch_bpm = round(src_b * (2.0 ** (exact_delta / 12.0)), 1)
    formant_warning = abs(raw_semi) >= 4.5
    return {
        "id": mode_id,
        "label": label,
        "target_bpm": round(float(target_bpm), 1),
        "stretch_ratio": round(stretch_ratio, 4),
        "repitch_semitones": repitch_semitones,
        "repitch_fine_tune_cents": repitch_fine_cents,
        "vinyl_repitch_bpm": vinyl_repitch_bpm,
        "formant_warning": formant_warning,
        "recommended_mode": "mpc_warp_0st" if formant_warning else "vinyl_repitch_or_warp",
        "half_time_applied": bool(half_time_applied),
    }


def _analyze_spectral_timbre(
    samples: List[int],
    sr: int,
    norm_e: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Calcula perfil tímbrico en 4 sub-bandas, crest factor, centroide ZCR, presencia de batería y consejos EQ."""
    if not samples or sr <= 0:
        return {
            "sub_energy_ratio": 0.0,
            "low_mid_mud_ratio": 0.0,
            "mid_warmth_ratio": 0.0,
            "high_air_ratio": 0.0,
            "sustain_index": 0.0,
            "crest_db": 0.0,
            "centroid_hz": 0.0,
            "drum_presence_score": 0.0,
            "is_drumless": False,
            "timbre_profile": "balanced_organic",
            "timbre_label": "Orgánico Equilibrado",
            "mix_eq_advice": [],
        }
    seg = samples[: min(len(samples), sr * 6)]
    fs = float(max(8000, sr))
    a_sub = math.exp(-2.0 * math.pi * 175.0 / fs)
    a_mud = math.exp(-2.0 * math.pi * 420.0 / fs)
    a_mid = math.exp(-2.0 * math.pi * 2800.0 / fs)
    # Doble polo en cascada para aislamiento más limpio entre sub-grave y medios
    lp_sub1 = lp_sub2 = 0.0
    lp_mud1 = lp_mud2 = 0.0
    lp_mid = 0.0
    sub_e = mud_e = mid_e = high_e = tot_sq = peak_abs = 0.0
    zc_cnt = 0
    prev_x = 0.0
    for idx_s, s in enumerate(seg):
        x = float(s) / 32768.0
        ax = abs(x)
        if ax > peak_abs:
            peak_abs = ax
        tot_sq += x * x
        if idx_s > 0 and ((prev_x >= 0.0) != (x >= 0.0)):
            zc_cnt += 1
        prev_x = x
        lp_sub1 = (1.0 - a_sub) * x + a_sub * lp_sub1
        lp_sub2 = (1.0 - a_sub) * lp_sub1 + a_sub * lp_sub2
        lp_mud1 = (1.0 - a_mud) * x + a_mud * lp_mud1
        lp_mud2 = (1.0 - a_mud) * lp_mud1 + a_mud * lp_mud2
        lp_mid = (1.0 - a_mid) * x + a_mid * lp_mid
        mud_band = lp_mud2 - lp_sub2
        mid_band = lp_mid - lp_sub2
        high_band = x - lp_mid
        sub_e += lp_sub2 * lp_sub2
        mud_e += mud_band * mud_band
        mid_e += mid_band * mid_band
        high_e += high_band * high_band

    tot_e = max(1e-9, sub_e + mid_e + high_e)
    sub_ratio = round(sub_e / tot_e, 3)
    mud_ratio = round(mud_e / tot_e, 3)
    mid_ratio = round(mid_e / tot_e, 3)
    high_ratio = round(high_e / tot_e, 3)
    rms_all = math.sqrt(tot_sq / float(max(1, len(seg))))
    crest_db = round(20.0 * math.log10(max(1e-6, peak_abs) / max(1e-6, rms_all)), 1) if rms_all > 1e-6 else 0.0
    centroid_hz = round((zc_cnt * fs) / (2.0 * float(max(1, len(seg)))), 1)

    if norm_e:
        sustain_idx = round(sum(1 for e in norm_e if e >= 0.22) / float(len(norm_e)), 3)
        spike_diffs = [max(0.0, norm_e[i] - norm_e[i - 1]) for i in range(1, len(norm_e))]
        strong_transients = sum(1 for d in spike_diffs if d >= 0.22)
        trans_density = min(1.0, strong_transients / float(max(4, len(norm_e) * 0.06)))
        drum_presence_score = round(min(1.0, max(0.0, 0.55 * trans_density + 0.30 * min(1.0, high_ratio / 0.28) + 0.15 * min(1.0, crest_db / 16.0))), 2)
    else:
        sustain_idx = 0.25
        drum_presence_score = round(min(1.0, 0.5 * min(1.0, high_ratio / 0.28) + 0.5 * min(1.0, crest_db / 18.0)), 2)

    is_drumless = bool(drum_presence_score < 0.24 and sustain_idx >= 0.22)

    if mid_ratio >= 0.58 and sub_ratio <= 0.22 and high_ratio <= 0.16:
        prof = "vintage_oldies"
        label = "Cinta Vintage 50s/60s (Oldies / Medios Cálidos)"
    elif mid_ratio >= 0.55 and high_ratio <= 0.14:
        prof = "warm_analog"
        label = "Calidez Vinilo / Cuerdas & Rhodes"
    elif high_ratio >= 0.25:
        prof = "bright_percussive"
        label = "Brillante / Percusivo & Aire"
    elif sub_ratio >= 0.42:
        prof = "sub_warm"
        label = "Profundo / Sub-Warmth & Contrabajo"
    else:
        prof = "balanced_organic"
        label = "Orgánico Equilibrado"

    eq_tips: List[str] = []
    if sub_ratio >= 0.28:
        eq_tips.append("HPF 2-Polos a 110–130 Hz en los chops para no enmascarar Kick/808")
    elif sub_ratio <= 0.08:
        eq_tips.append("Poca energía subgrave (<175 Hz): admite Kick + 808 gordos sin HPF agresivo")
    if mud_ratio >= 0.46:
        eq_tips.append("Recorte suave -2.5 dB @ 280 Hz para limpiar cuerpo/caja de resonancia")
    if high_ratio <= 0.07:
        eq_tips.append("Timbre oscuro vintage: suma hi-hats nítidos (>7 kHz) sin sobrecomprimir la muestra")
    elif high_ratio >= 0.28:
        eq_tips.append("Alto brillo/charles (>2.8 kHz): LPF suave ~9–11 kHz si choca con tus hats")
    if crest_db >= 14.5:
        eq_tips.append(f"Dinámica amplia ({crest_db:.1f} dB crest): soft-clip/compresor 2:1 en bus")

    return {
        "sub_energy_ratio": sub_ratio,
        "low_mid_mud_ratio": mud_ratio,
        "mid_warmth_ratio": mid_ratio,
        "high_air_ratio": high_ratio,
        "sustain_index": sustain_idx,
        "crest_db": crest_db,
        "centroid_hz": centroid_hz,
        "drum_presence_score": drum_presence_score,
        "is_drumless": is_drumless,
        "timbre_profile": prof,
        "timbre_label": label,
        "mix_eq_advice": eq_tips,
    }


def _build_harmonic_transposition_info(
    wav_p: Path,
    repitch_semitones: int,
) -> Dict[str, Any]:
    """Detecta tonalidad original y calcula por separado la tonalidad transpuesta (Key/Camelot) y la nota F0 tras repitch."""
    if not wav_p.is_file():
        return {
            "original_note": "",
            "original_root": "",
            "original_key": "",
            "original_camelot": "",
            "transposed_key": "",
            "transposed_camelot": "",
            "transposed_note": "",
            "transposed_root": "",
            "pitch_class": None,
            "f0_hz": 0.0,
            "cents_offset": 0,
            "tuning_cents_drift": 0,
            "confidence": 0.0,
        }
    try:
        pinfo = detect_sample_pitch_and_key(wav_p)
    except Exception:
        pinfo = {}

    orig_key = str(pinfo.get("key") or "").strip()
    orig_camelot = str(pinfo.get("camelot") or "").strip()
    trans_key = ""
    trans_camelot = ""
    key_pc = pinfo.get("pitch_class")
    if orig_key:
        kinfo = parse_musical_key_info(orig_key)
        if kinfo and kinfo.get("pitch_class") is not None:
            k_pc = int(kinfo["pitch_class"])
            k_mode = kinfo.get("mode") or "Maj"
            tk_pc = (k_pc + int(repitch_semitones)) % 12
            trans_key = f"{_NOTE_NAMES_SHARP[tk_pc]} {k_mode}"
            trans_camelot = (parse_musical_key_info(trans_key) or {}).get("camelot") or ""

    f0_val = float(pinfo.get("f0_hz") or 0.0)
    midi_orig = pinfo.get("midi_note")
    orig_note = str(pinfo.get("note") or "")
    orig_root = str(pinfo.get("note_root") or orig_note or "")

    # Transponer nota F0 únicamente usando su MIDI real (nunca mezclando pitch_class de clave con octava de F0)
    trans_root = ""
    trans_note = ""
    if f0_val > 0.0 and midi_orig is not None:
        trans_midi = int(midi_orig) + int(repitch_semitones)
        tn_pc = trans_midi % 12
        trans_root = _NOTE_NAMES_SHARP[tn_pc]
        trans_oct = (trans_midi // 12) - 1
        trans_note = f"{trans_root}{trans_oct}"
    elif trans_key:
        trans_root = trans_key.split()[0]
        trans_note = trans_key
    elif key_pc is not None:
        tn_pc = (int(key_pc) + int(repitch_semitones)) % 12
        trans_root = _NOTE_NAMES_SHARP[tn_pc]
        trans_note = trans_root

    return {
        "original_note": orig_note or orig_root,
        "original_root": orig_root,
        "original_key": orig_key,
        "original_camelot": orig_camelot,
        "transposed_key": trans_key,
        "transposed_camelot": trans_camelot,
        "transposed_note": trans_note or trans_root,
        "transposed_root": trans_root,
        "pitch_class": key_pc,
        "f0_hz": f0_val,
        "cents_offset": int(pinfo.get("cents_offset") or 0),
        "tuning_cents_drift": int(pinfo.get("tuning_cents_drift", pinfo.get("cents_offset") or 0)),
        "confidence": pinfo.get("confidence", 0.0),
    }


def _build_adaptation_profiles_and_sequencer(
    eff_source_bpm: float,
    half_time_applied: bool,
    effective_style_id: str,
    time_sig: str,
    swing_pct: float,
    sub_ratio: float,
    adapt_mode: str,
    is_rubato: bool = False,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Genera 4 perfiles comparativos (Lo-Fi, Boom Bap, Dilla, Drumless) y la guía 1/16 de MPC."""
    profile_defs = [
        ("lofi_chill", "Lo-Fi / Chillhop (82 BPM)", 82.0),
        ("boombap_classic", "Boom Bap 90s (90 BPM)", 90.0),
        ("dilla_jazzhop", "Jazz-Hop / Dilla (86 BPM)", 86.0),
        ("drumless_alchemist", "Drumless / Alchemist (78 BPM)", 78.0),
    ]
    profiles = [
        _compute_hiphop_adaptation_profile(pid, plabel, eff_source_bpm, pbpm, half_time_applied)
        for pid, plabel, pbpm in profile_defs
    ]

    if effective_style_id == "bolero":
        kick_steps = [1, 4, 11]
    elif effective_style_id == "oldies":
        kick_steps = [1, 4, 9, 11]
    elif effective_style_id in ("cumbia_son",):
        kick_steps = [1, 4, 9, 12]
    elif effective_style_id in ("drumless",) or adapt_mode == "drumless_alchemist":
        kick_steps = [1, 10]
    elif effective_style_id in ("jazz_hop", "bossa_samba") or adapt_mode == "dilla_jazzhop":
        kick_steps = [1, 8, 11]
    else:
        kick_steps = [1, 3, 9, 11]

    if is_rubato or effective_style_id == "drumless" or adapt_mode == "drumless_alchemist":
        hat_steps = [1, 5, 9, 13]
        tip = "Rubato / Fraseo Libre: desactiva Warp largo en los pads; dispara frases cortadas (M6) en pasos 1 y 9."
    elif time_sig == "12/8":
        hat_steps = [1, 3, 5, 7, 9, 11, 13, 15]
        tip = "Compás 12/8 (Oldies / Doo-Wop): programa bombos en pasos 1, 4, 9, 11, swing ~60–64% y chops cada 3 corcheas (pasos 1, 5, 9, 13)."
    elif time_sig in ("3/4", "6/8"):
        hat_steps = [1, 3, 5, 7, 9, 11, 13, 15]
        tip = "Compás ternario puenteado a 4/4: dispara 4 chops por compás (pasos 1, 5, 9, 13) con swing en hats."
    else:
        hat_steps = [1, 3, 5, 7, 9, 11, 13, 15]
        tip = "Paso 1/16 MPC: ajusta swing en charles y filtra graves en los chops para dejar espacio al sub."

    swing_floor = 58.0 if effective_style_id == "oldies" else (54.0 if effective_style_id == "bolero" else 50.0)
    seq_swing = round(max(50.0, min(67.0, max(swing_floor, swing_pct))), 1)
    hpf_cut = 125 if sub_ratio >= 0.28 else (105 if sub_ratio >= 0.18 else 85)
    sequencer_guide = {
        "grid": "1/16",
        "swing_pct": seq_swing,
        "kick_steps": kick_steps,
        "snare_steps": [5, 13],
        "hat_steps": hat_steps,
        "chop_trigger_steps": [1, 5, 9, 13] if time_sig in ("3/4", "6/8", "12/8") else [1, 4, 9, 13],
        "highpass_hz_cut": hpf_cut,
        "humanize_ms": 14 if is_rubato or effective_style_id in ("bolero", "jazz_hop", "drumless") else 7,
        "tip": tip,
    }
    return profiles, sequencer_guide


def analyze_rhythmic_pattern_and_hiphop_adaptation(
    wav_path: str | Path,
    style_hint: str = "",
    target_bpm_hint: Optional[float] = None,
    preloaded_samples: Optional[List[int]] = None,
    preloaded_sr: int = 44100,
    adapt_mode: str = "auto",
) -> Dict[str, Any]:
    """
    Analiza el patrón rítmico, compás (4/4, 3/4, 6/8, 5/4), clave latina/swing, timbre espectral
    en 3 bandas, tonalidad original y calcula múltiples perfiles de adaptación a Hip-Hop / Lo-Fi.
    """
    wav_p = Path(wav_path)
    combined_hint = f"{wav_p.name} {style_hint}".strip()
    low_hint = combined_hint.lower()
    style_info = detect_musical_style(combined_hint)
    style_id = style_info.get("id", "standard")
    norm_adapt_mode = str(adapt_mode or "auto").strip().lower()
    if norm_adapt_mode not in ("auto", "lofi_chill", "boombap_classic", "dilla_jazzhop", "drumless_alchemist"):
        norm_adapt_mode = "auto"

    # Extraer posible BPM objetivo pedido en el prompt (ej. "Bolero a Lo-Fi 84")
    resolved_target_bpm: Optional[float] = None
    if target_bpm_hint is not None:
        try:
            tb = float(target_bpm_hint)
            if 55.0 <= tb <= 185.0:
                resolved_target_bpm = tb
        except (TypeError, ValueError):
            resolved_target_bpm = None
    if resolved_target_bpm is None and style_hint:
        m_prompt_bpm = re.search(r"\b(6\d|[7-9]\d|1[0-4]\d)(?:\s*bpm)?\b", str(style_hint), re.I)
        if m_prompt_bpm:
            cand_tb = float(m_prompt_bpm.group(1))
            if 65.0 <= cand_tb <= 115.0:
                resolved_target_bpm = cand_tb

    samples: List[int] = []
    sr = int(preloaded_sr or 44100)
    if preloaded_samples is not None:
        max_raw = min(len(preloaded_samples), sr * 24)
        if sr >= 40000:
            samples = list(preloaded_samples[:max_raw:2])
            sr = sr // 2
        else:
            samples = list(preloaded_samples[:max_raw])
    else:
        try:
            raw_samples = _convert_audio(wav_p, mono=True, sample_rate=44100)
            max_raw = min(len(raw_samples), 44100 * 24)
            samples = raw_samples[:max_raw:2]
            sr = 22050
        except Exception:
            samples = []

    duration_sec = round(len(samples) / float(max(1, sr)), 3)
    explicit_file_bpm = _extract_explicit_bpm_from_text(wav_p.stem) or _extract_explicit_bpm_from_text(wav_p.name)

    # Envolvente de energía en ventanas de 10 ms (~100 Hz)
    hop = max(64, int(round(sr * 0.010)))
    hop_sec = hop / float(max(1, sr))
    energies: List[float] = []
    if len(samples) >= hop * 8:
        for pos in range(0, len(samples) - hop, hop):
            chunk = samples[pos : pos + hop]
            energies.append(sum(abs(x) for x in chunk) / float(hop))

    max_e = max(energies) if energies else 0.0
    norm_e = [e / max_e for e in energies] if max_e > 1e-6 else []
    spectral = _analyze_spectral_timbre(samples, sr, norm_e=norm_e)

    mode_bpm_map = {
        "lofi_chill": (82.0, "Hip-Hop / Lo-Fi"),
        "boombap_classic": (90.0, "Boom Bap 90s"),
        "dilla_jazzhop": (86.0, "Jazz-Hop / Dilla"),
        "drumless_alchemist": (78.0, "Drumless / Abstract Hip-Hop"),
    }

    if len(energies) < 25 or max_e <= 1e-6:
        fallback_bpm = float(explicit_file_bpm or style_info.get("bpm") or 84.0)
        eff_src = round(fallback_bpm / 2.0, 1) if fallback_bpm >= 132.0 else fallback_bpm
        half_applied = bool(fallback_bpm >= 132.0)
        if norm_adapt_mode in mode_bpm_map:
            tgt, target_style = mode_bpm_map[norm_adapt_mode]
        else:
            tgt = float(resolved_target_bpm or (84.0 if style_id in ("bolero", "bossa_samba", "oldies") else (78.0 if style_id == "drumless" else 86.0)))
            target_style = "Hip-Hop / Lo-Fi"
        fb_ts = "12/8" if (re.search(r"(?:^|[\W_])12[/_\-]8(?:$|[\W_])", low_hint) or any(k in low_hint for k in ["doo wop", "doo-wop", "doowop"])) else "4/4"
        main_prof = _compute_hiphop_adaptation_profile(norm_adapt_mode, target_style, eff_src, tgt, half_applied)
        harmonic_info = _build_harmonic_transposition_info(wav_p, main_prof["repitch_semitones"])
        profiles, seq_guide = _build_adaptation_profiles_and_sequencer(
            eff_src, half_applied, style_id, fb_ts, 60.0 if style_id == "oldies" else 50.0, spectral["sub_energy_ratio"], norm_adapt_mode
        )
        return {
            "rhythm_analysis": {
                "source_bpm": round(fallback_bpm, 1),
                "effective_source_bpm": round(eff_src, 1),
                "time_signature": fb_ts,
                "groove_pattern": "Fraseo melódico / One-Shot",
                "clave_pattern": "Fraseo Libre / One-Shot",
                "swing_pct": 50.0,
                "rubato_index": 0.0,
                "onset_count": 0,
                "duration_sec": duration_sec,
                "acoustic_style_id": style_id,
                **spectral,
            },
            "hiphop_adaptation": {
                "target_style": target_style,
                "adapt_mode": norm_adapt_mode,
                "target_bpm": main_prof["target_bpm"],
                "stretch_ratio": main_prof["stretch_ratio"],
                "repitch_semitones": main_prof["repitch_semitones"],
                "repitch_fine_tune_cents": main_prof["repitch_fine_tune_cents"],
                "half_time_applied": half_applied,
                "recommended_chop_mode": "transients",
                "harmonic_info": harmonic_info,
                "adaptation_profiles": profiles,
                "sequencer_guide": seq_guide,
                "meter_bridge_note": "Muestra corta o sostenida: dispara desde los pads en compás 4/4 y ajusta al tempo Lo-Fi.",
            },
        }

    # Flujo de ataques positivos normalizado
    flux: List[float] = [0.0]
    for i in range(1, len(norm_e)):
        diff = norm_e[i] - norm_e[i - 1]
        flux.append(diff if diff > 0.0 else 0.0)

    n_flux = len(flux)
    flux_energy = sum(f * f for f in flux) + 1e-9

    def _acf(lag_hops: int) -> float:
        if lag_hops <= 0 or lag_hops >= n_flux - 2:
            return 0.0
        s = 0.0
        limit = n_flux - lag_hops
        for idx in range(limit):
            s += flux[idx] * flux[idx + lag_hops]
        norm = flux_energy * (limit / float(n_flux))
        return s / max(1e-9, norm)

    # Peak-picking de transientes reales (distancia mínima ~80 ms)
    min_ioi_hops = max(6, int(round(0.080 / hop_sec)))
    mean_flux = sum(flux) / float(n_flux)
    onset_hops: List[int] = []
    for i in range(1, n_flux - 1):
        w_lo = max(0, i - 12)
        w_hi = min(n_flux, i + 12)
        local_avg = sum(flux[w_lo:w_hi]) / float(max(1, w_hi - w_lo))
        thresh = max(mean_flux * 1.15, local_avg * 1.45, 0.025)
        if flux[i] >= thresh and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]:
            if not onset_hops or (i - onset_hops[-1]) >= min_ioi_hops:
                onset_hops.append(i)

    # Estimación de tempo por autocorrelación de la envolvente de flujo (58..172 BPM)
    if style_id in ("bolero", "tango_vals", "bossa_samba"):
        preferred_center, preferred_sigma = 82.0, 24.0
    elif style_id == "oldies":
        preferred_center, preferred_sigma = 78.0, 24.0
    elif style_id in ("soul_vintage", "drumless"):
        preferred_center, preferred_sigma = 84.0, 26.0
    elif style_id in ("jazz_hop", "cumbia_son", "psych_library"):
        preferred_center, preferred_sigma = 92.0, 30.0
    else:
        preferred_center, preferred_sigma = 96.0, 38.0

    best_bpm = preferred_center
    best_score = -1.0
    for cand_bpm in range(58, 173):
        lag = int(round(60.0 / (cand_bpm * hop_sec)))
        if lag < 20 or lag >= n_flux - 4:
            continue
        c1 = _acf(lag)
        c2 = _acf(lag * 2) if (lag * 2) < n_flux - 4 else c1 * 0.5
        c_half = _acf(lag // 2) if (lag // 2) >= 12 else 0.0
        prior = math.exp(-0.5 * ((cand_bpm - preferred_center) / preferred_sigma) ** 2)
        score = (c1 + 0.55 * c2 + 0.18 * c_half) * (0.72 + 0.28 * prior)
        if score > best_score:
            best_score = score
            best_bpm = float(cand_bpm)

    iois_sec = [(onset_hops[k] - onset_hops[k - 1]) * hop_sec for k in range(1, len(onset_hops))]
    if explicit_file_bpm is not None:
        source_bpm = float(explicit_file_bpm)
    elif best_score > 0.05:
        source_bpm = float(best_bpm)
        if len(iois_sec) >= 4:
            sorted_iois = sorted(iois_sec)
            med_ioi = sorted_iois[len(sorted_iois) // 2]
            if med_ioi > 0.25:
                ioi_bpm = 60.0 / med_ioi
                while ioi_bpm > 155.0:
                    ioi_bpm /= 2.0
                while ioi_bpm < 58.0:
                    ioi_bpm *= 2.0
                if abs(ioi_bpm - source_bpm) <= 3.5:
                    source_bpm = round(ioi_bpm, 1)
    elif iois_sec:
        med_ioi = sorted(iois_sec)[len(iois_sec) // 2]
        source_bpm = 60.0 / max(0.35, min(1.05, med_ioi))
    else:
        source_bpm = float(style_info.get("bpm") or 84.0)

    source_bpm = max(56.0, min(180.0, round(source_bpm, 1)))
    beat_lag_f = 60.0 / (source_bpm * hop_sec)
    beat_lag = max(18, int(round(beat_lag_f)))

    def _acf_peak(center_lag: float, radius: int = 3) -> float:
        base = int(round(center_lag))
        vals = [_acf(base + d) for d in range(-radius, radius + 1) if (base + d) > 0]
        return max(vals) if vals else 0.0

    # Correlación centrada por pulso (3/4, 4/4, 5/4) alineada a la fase real del beat
    best_phase = 0
    best_phase_energy = -1.0
    n_est_beats = max(1, int(n_flux / beat_lag_f))
    for ph in range(beat_lag):
        tot_ph = 0.0
        for bk in range(n_est_beats):
            c = int(round(ph + bk * beat_lag_f))
            if 0 <= c < n_flux - 3:
                tot_ph += sum(flux[max(0, c - 3) : min(n_flux, c + 4)])
        if tot_ph > best_phase_energy:
            best_phase_energy = tot_ph
            best_phase = ph

    b_vals: List[float] = []
    bk = 0
    while True:
        c = int(round(best_phase + bk * beat_lag_f))
        if c >= n_flux - 3:
            break
        b_vals.append(sum(flux[max(0, c - 3) : min(n_flux, c + 4)]))
        bk += 1

    def _bcorr(period: int) -> float:
        if len(b_vals) <= period + 1:
            return 0.0
        mean_b = sum(b_vals) / float(len(b_vals))
        cb = [v - mean_b for v in b_vals]
        lim = len(cb) - period
        num = sum(cb[i] * cb[i + period] for i in range(lim))
        el = sum(cb[i] * cb[i] for i in range(lim))
        er = sum(cb[i + period] * cb[i + period] for i in range(lim))
        denom = math.sqrt(el * er)
        return (num / denom) if denom > 1e-9 else 0.0

    bcorr3 = _bcorr(3)
    bcorr4 = _bcorr(4)
    bcorr5 = _bcorr(5)
    acf_tri = 0.5 * (
        _acf_peak(max(6.0, beat_lag_f / 3.0), radius=2)
        + _acf_peak(max(12.0, 2.0 * beat_lag_f / 3.0), radius=2)
    )
    acf_bin = _acf_peak(max(8.0, beat_lag_f / 2.0), radius=2)

    if "5/4" in low_hint or "take five" in low_hint:
        time_sig = "5/4"
    elif any(k in low_hint for k in ["3/4", "vals", "waltz", "valse"]):
        time_sig = "3/4"
    elif re.search(r"(?:^|[\W_])12[/_\-]8(?:$|[\W_])", low_hint) or any(k in low_hint for k in ["doo wop", "doo-wop", "doowop"]):
        time_sig = "12/8"
    elif "6/8" in low_hint:
        time_sig = "6/8"
    elif "4/4" in low_hint:
        time_sig = "4/4"
    elif bcorr3 > 0.12 and bcorr3 > bcorr4 + 0.12 and bcorr3 >= bcorr5:
        if style_id != "tango_vals" and source_bpm <= 76.0 and (acf_tri >= acf_bin * 0.90 or style_id == "soul_vintage" or "ballad" in low_hint):
            time_sig = "6/8"
        else:
            time_sig = "3/4"
    elif bcorr5 > 0.22 and bcorr5 > bcorr4 + 0.14 and bcorr5 > bcorr3 + 0.10:
        time_sig = "5/4"
    elif acf_tri > acf_bin * 1.12 and source_bpm <= 92.0 and style_id == "oldies":
        time_sig = "12/8"
    elif acf_tri > acf_bin * 1.18 and bcorr4 >= bcorr3 and source_bpm <= 86.0 and spectral["mid_warmth_ratio"] >= 0.52:
        time_sig = "12/8"
    elif acf_tri > acf_bin * 1.15 and source_bpm <= 84.0 and (style_id in ("soul_vintage", "bolero") or "ballad" in low_hint):
        time_sig = "6/8"
    else:
        time_sig = "4/4"

    # Cálculo de Swing % (subdivisión binaria 0.50 vs tresillo 0.66) + energía síncopa Tresillo (0.75)
    swing_hits = 0.0
    straight_hits = 0.0
    tresillo_hits = 0.0
    total_onset_flux = 0.0
    for idx in onset_hops:
        phase = ((idx - best_phase) % beat_lag_f) / beat_lag_f
        w = flux[idx]
        total_onset_flux += w
        if 0.43 <= phase <= 0.55:
            straight_hits += w
        elif 0.57 <= phase <= 0.72:
            swing_hits += w
        elif 0.72 < phase <= 0.84:
            tresillo_hits += w

    if (swing_hits + straight_hits) > 1e-6:
        swing_frac = swing_hits / (swing_hits + straight_hits)
        swing_pct = round(50.0 + swing_frac * 16.7, 1)
    elif style_id == "oldies" or time_sig == "12/8":
        swing_pct = 60.0
    elif style_id in ("jazz_hop", "soul_vintage"):
        swing_pct = 57.5
    elif style_id in ("bossa_samba",):
        swing_pct = 55.0
    else:
        swing_pct = 52.0 if style_id in ("bolero", "cumbia_son") else 50.0

    # Índice de Rubato / Expresividad humana (variación de IOI respecto al pulso)
    rubato_index = 0.0
    if len(iois_sec) >= 4:
        beat_sec = 60.0 / source_bpm
        norm_devs = [abs(ioi - round(max(0.25, ioi / beat_sec) * 2.0) * (beat_sec * 0.5)) / beat_sec for ioi in iois_sec]
        avg_dev = sum(norm_devs) / float(len(norm_devs))
        rubato_index = round(min(1.0, max(0.0, avg_dev * 2.2)), 2)
    is_rubato = bool(rubato_index >= 0.26)
    tempo_confidence = round(min(0.98, max(0.20, 0.88 if explicit_file_bpm is not None else min(0.95, 0.35 + max(0.0, best_score) * 1.1))), 2)
    meter_margin = max(abs(bcorr3 - bcorr4), abs(bcorr5 - bcorr4), (acf_tri / max(1e-6, acf_bin)) - 1.0)
    meter_confidence = round(min(0.96, max(0.45, 0.58 + meter_margin * 0.85)), 2)

    # Clasificación acústica automática si el nombre de archivo es genérico ("standard")
    effective_style_id = style_id
    if effective_style_id == "standard":
        if time_sig == "3/4":
            effective_style_id = "tango_vals"
        elif time_sig == "12/8":
            effective_style_id = "oldies"
        elif time_sig == "6/8":
            effective_style_id = "soul_vintage"
        elif spectral.get("is_drumless") or (rubato_index >= 0.28 and spectral["sustain_index"] >= 0.32 and len(onset_hops) < max(4, int(duration_sec * 1.6))):
            effective_style_id = "drumless"
        elif swing_pct >= 57.5 and spectral["high_air_ratio"] >= 0.16:
            effective_style_id = "jazz_hop"
        elif spectral["mid_warmth_ratio"] >= 0.55 and spectral["sustain_index"] >= 0.28:
            effective_style_id = "soul_vintage" if swing_pct >= 54.5 else "bolero"

    # Detección de Clave / Cadencia Rítmica dominante
    if time_sig == "3/4":
        clave_pattern = "Vals / Ternario (1-2-3)"
    elif time_sig == "12/8":
        clave_pattern = "Arpegio Tresillo 12/8 (Doo-Wop / Lowrider Oldies)"
    elif time_sig == "6/8":
        clave_pattern = "Compuesto 6/8 (2 grupos de 3 corcheas)"
    elif time_sig == "5/4":
        clave_pattern = "Irregular 5/4 (3+2)"
    elif effective_style_id == "bossa_samba":
        clave_pattern = "Clave Bossa / Samba (3-2 / Partido Alto)"
    elif effective_style_id == "cumbia_son":
        clave_pattern = "Clave Son / Cumbia (3-2 & Contratiempo)"
    elif effective_style_id == "bolero" or (
        total_onset_flux > 1e-6 and tresillo_hits > straight_hits * 1.15 and tresillo_hits >= total_onset_flux * 0.15
    ):
        clave_pattern = "Tresillo / Cinquillo Cubano (3:3:2)"
    elif effective_style_id == "oldies":
        clave_pattern = "Backbeat Shuffle / Motown 60s (2 y 4)"
    elif effective_style_id == "jazz_hop" or (swing_pct >= 57.5 and spectral["high_air_ratio"] >= 0.12):
        clave_pattern = "Jazz Ride / Triplet Swing"
    elif effective_style_id == "drumless" or (rubato_index >= 0.28 and len(onset_hops) <= max(4, int(duration_sec * 1.8))):
        clave_pattern = "Fraseo Libre / Drumless Rubato"
    else:
        clave_pattern = "Backbeat 2 y 4 (4/4)"

    # Descripción del patrón rítmico detectado
    if effective_style_id == "bolero":
        if time_sig == "3/4":
            groove_pattern = "Bolero-Vals / Vals Criollo (3/4)"
        elif swing_pct >= 57.0:
            groove_pattern = "Bolero con Tresillo / Cinquillo Cadencioso"
        else:
            groove_pattern = "Bolero Clásico (Requinto / Cinquillo 4/4)"
    elif effective_style_id == "tango_vals":
        groove_pattern = "Vals Criollo / Jazz Waltz (3/4)" if time_sig == "3/4" else "Tango / Milonga Marcato (4/4)"
    elif effective_style_id == "bossa_samba":
        groove_pattern = "Bossa Nova / Clave Sincopada (4/4)"
    elif effective_style_id == "cumbia_son":
        groove_pattern = "Cumbia / Son Montuno (Contratiempo)"
    elif effective_style_id == "drumless":
        groove_pattern = "Drumless Soul / Abstract Phrase (Sin Percusión)"
    elif effective_style_id == "psych_library":
        groove_pattern = "Psych / Library Score Groove (Cinematográfico)"
    elif effective_style_id == "oldies":
        if time_sig == "12/8":
            groove_pattern = "Doo-Wop / Sweet Soul Ballad (12/8 Tresillos)"
        elif swing_pct >= 56.5:
            groove_pattern = "60s Oldies / Backbeat Shuffle Vintage"
        else:
            groove_pattern = "Lowrider Oldies / 50s–60s Classic (4/4)"
    elif effective_style_id == "soul_vintage":
        if time_sig == "6/8":
            groove_pattern = "Slow Soul Ballad / Gospel Feel (6/8)"
        elif swing_pct >= 57.0:
            groove_pattern = "Soul Groove con Swing Vintage"
        else:
            groove_pattern = "Soul Backbeat 2 y 4 (4/4)"
    elif effective_style_id == "jazz_hop":
        if time_sig == "3/4":
            groove_pattern = "Jazz Waltz (3/4)"
        elif "bossa" in low_hint:
            groove_pattern = "Bossa Nova / Clave Sincopada (4/4)"
        elif swing_pct >= 57.0:
            groove_pattern = "Jazz Swing / Ride Triplet Feel"
        else:
            groove_pattern = "Cool Jazz / Chord Phrasing (4/4)"
    else:
        if time_sig == "3/4":
            groove_pattern = "Patrón Ternario / Vals (3/4)"
        elif time_sig == "6/8":
            groove_pattern = "Compás Compuesto / Slow Ballad (6/8)"
        elif time_sig == "5/4":
            groove_pattern = "Compás Irregular (5/4)"
        elif swing_pct >= 57.0:
            groove_pattern = "Groove con Swing / Shuffle"
        else:
            groove_pattern = "Pulso Cuaternario Directo (4/4)"

    # Cálculo de Adaptación a Hip-Hop / Boom Bap / Lo-Fi
    eff_source_bpm = source_bpm
    half_time_applied = False
    if source_bpm >= 132.0:
        eff_source_bpm = round(source_bpm / 2.0, 1)
        half_time_applied = True

    want_boombap = any(k in low_hint for k in ["boom bap", "boombap", "hip hop", "hip-hop", "hiphop", "dilla", "premo", "east coast"])
    want_lofi = any(k in low_hint for k in ["lofi", "lo-fi", "chillhop", "nujabes", "dusty"]) or effective_style_id in ("bolero", "bossa_samba", "oldies")

    if norm_adapt_mode in mode_bpm_map:
        target_bpm, target_style = mode_bpm_map[norm_adapt_mode]
    else:
        if resolved_target_bpm is not None:
            target_bpm = float(resolved_target_bpm)
        elif effective_style_id in ("bolero", "bossa_samba"):
            target_bpm = 84.0 if (eff_source_bpm >= 74.0 or want_boombap) else 80.0
        elif effective_style_id == "oldies":
            target_bpm = 88.0 if want_boombap else 84.0
        elif effective_style_id == "drumless":
            target_bpm = 78.0
        elif effective_style_id == "tango_vals":
            target_bpm = 82.0
        elif effective_style_id in ("cumbia_son", "soul_vintage", "jazz_hop"):
            if effective_style_id == "cumbia_son":
                target_bpm = 88.0
            elif effective_style_id == "soul_vintage":
                target_bpm = 88.0 if want_boombap else 85.0
            else:
                target_bpm = 88.0 if want_boombap else 86.0
        elif effective_style_id == "psych_library":
            target_bpm = 86.0
        else:
            target_bpm = 86.0 if want_lofi else (90.0 if want_boombap else round(max(78.0, min(94.0, eff_source_bpm)), 1))
        target_style = "Boom Bap / Hip-Hop" if (want_boombap and not want_lofi) else ("Hip-Hop / Lo-Fi" if want_lofi else "Boom Bap & Lo-Fi")

    main_profile = _compute_hiphop_adaptation_profile(
        norm_adapt_mode, target_style, eff_source_bpm, target_bpm, half_time_applied
    )
    stretch_ratio = main_profile["stretch_ratio"]
    repitch_semitones = main_profile["repitch_semitones"]
    repitch_fine_cents = main_profile["repitch_fine_tune_cents"]

    if time_sig in ("3/4", "6/8", "12/8"):
        recommended_chop_mode = "phrase_3_4_to_4_4"
    elif rubato_index >= 0.25 or effective_style_id == "drumless":
        recommended_chop_mode = "transients"
    elif effective_style_id in ("bossa_samba", "psych_library") or len(onset_hops) < 6:
        recommended_chop_mode = "bar_grid"
    else:
        recommended_chop_mode = "transients"

    harmonic_info = _build_harmonic_transposition_info(wav_p, repitch_semitones)
    adaptation_profiles, sequencer_guide = _build_adaptation_profiles_and_sequencer(
        eff_source_bpm,
        half_time_applied,
        effective_style_id,
        time_sig,
        swing_pct,
        spectral["sub_energy_ratio"],
        norm_adapt_mode,
        is_rubato=is_rubato,
    )
    if is_rubato or effective_style_id == "drumless":
        stretch_strategy = "phrase_slices_no_warp"
    elif main_profile.get("formant_warning"):
        stretch_strategy = "mpc_warp_elastique"
    else:
        stretch_strategy = "vinyl_repitch_or_warp"

    # Guía práctica para encajar el compás y patrón en el beat Hip-Hop / Lo-Fi
    if time_sig == "3/4":
        meter_bridge_note = (
            "Compás 3/4 detectado: usa Auto-Chop Puente 3/4→4/4 para cortar frases de 3+1 golpes "
            "y cuadrar 4 tiempos Boom Bap / Lo-Fi sin romper la cadencia."
        )
    elif time_sig == "12/8":
        meter_bridge_note = (
            "Compás 12/8 (Doo-Wop / Lowrider Oldies): agrupa cada pulso en 3 corcheas con Puente 3/4→4/4 "
            f"para cuadrar 4 tiempos Hip-Hop/Lo-Fi con swing {swing_pct:.0f}% (ajusta {repitch_semitones:+d} st o Stretch x{stretch_ratio:.3f})."
        )
    elif time_sig == "6/8":
        meter_bridge_note = (
            "Compás 6/8 (Soul/Balada lenta): programa los hi-hats Lo-Fi con swing de tresillos (~62–66%) "
            "o usa Puente 3/4→4/4 cada 3 corcheas para encajar el fraseo."
        )
    elif time_sig == "5/4":
        meter_bridge_note = (
            "Compás 5/4 detectado: divide la frase 3+2 tiempos en chops M6 para re-dispararla sobre rejilla 4/4."
        )
    elif is_rubato:
        meter_bridge_note = (
            f"Rubato humano detectado (índice {rubato_index:.2f}): evita Time Stretch largo sobre el archivo completo; "
            "trocea frases largas M6 y dispara en tiempo 1 y 3."
        )
    elif effective_style_id == "oldies":
        meter_bridge_note = (
            f"Oldies / Sweet Soul {time_sig}: trocea frases de guitarra/coros en Mute Group M6, "
            f"filtra graves <{sequencer_guide['highpass_hz_cut']} Hz y adapta a {target_bpm:.0f} BPM (Stretch x{stretch_ratio:.3f})."
        )
    elif effective_style_id == "drumless":
        meter_bridge_note = (
            f"Fraseo libre/Drumless (rubato {rubato_index:.2f}): trocea en 16 pads por frases/transientes (M6) "
            "y deja los acordes respirar sobre bombos suaves en pasos 1 y 10."
        )
    elif effective_style_id == "bolero":
        meter_bridge_note = (
            "Bolero 4/4: el tresillo/cinquillo de requinto encaja natural sobre bombos Boom Bap/Lo-Fi suaves "
            f"con swing {swing_pct:.0f}% (ajusta {repitch_semitones:+d} st o Time Stretch x{stretch_ratio:.3f})."
        )
    elif effective_style_id in ("bossa_samba", "cumbia_son"):
        meter_bridge_note = (
            f"{clave_pattern}: alinea los chops con el acento síncopado y filtra graves <{sequencer_guide['highpass_hz_cut']} Hz."
        )
    elif effective_style_id == "jazz_hop":
        meter_bridge_note = (
            f"Jazz {time_sig} con swing {swing_pct:.0f}%: aplica el mismo porcentaje de swing en el secuenciador "
            "y filtra graves <110 Hz en los chops para dejar espacio al sub/contrabajo Hip-Hop."
        )
    else:
        meter_bridge_note = (
            f"Adaptación lista a {target_bpm:.0f} BPM ({target_style}): repitch {repitch_semitones:+d} st "
            f"({repitch_fine_cents:+d} c) o Time Stretch x{stretch_ratio:.3f}."
        )
    if main_profile.get("formant_warning"):
        meter_bridge_note += f" (Salto {repitch_semitones:+d} st amplio: prefiere MPC Warp 0 st para conservar timbre vocal/cuerdas)."

    return {
        "rhythm_analysis": {
            "source_bpm": round(source_bpm, 1),
            "effective_source_bpm": round(eff_source_bpm, 1),
            "time_signature": time_sig,
            "groove_pattern": groove_pattern,
            "clave_pattern": clave_pattern,
            "swing_pct": round(swing_pct, 1),
            "rubato_index": round(rubato_index, 2),
            "is_rubato": is_rubato,
            "tempo_confidence": tempo_confidence,
            "meter_confidence": meter_confidence,
            "onset_count": len(onset_hops),
            "duration_sec": duration_sec,
            "acoustic_style_id": effective_style_id,
            **spectral,
        },
        "hiphop_adaptation": {
            "target_style": target_style,
            "adapt_mode": norm_adapt_mode,
            "target_bpm": round(target_bpm, 1),
            "stretch_ratio": round(stretch_ratio, 4),
            "repitch_semitones": repitch_semitones,
            "repitch_fine_tune_cents": repitch_fine_cents,
            "vinyl_repitch_bpm": main_profile["vinyl_repitch_bpm"],
            "formant_warning": main_profile["formant_warning"],
            "stretch_strategy": stretch_strategy,
            "half_time_applied": half_time_applied,
            "recommended_chop_mode": recommended_chop_mode,
            "harmonic_info": harmonic_info,
            "adaptation_profiles": adaptation_profiles,
            "sequencer_guide": sequencer_guide,
            "meter_bridge_note": meter_bridge_note,
        },
    }


def _extract_mir_beats_chords_and_mmr(
    samples_i16: List[int],
    sr: int,
    active_start: int,
    active_end: int,
    *,
    max_slices: int = 48,
    mode_3bank: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Motor MIR BeatOS (HPSS + tuning CQT + 0.45*perc/0.30*bass/0.25*HCDF + FFT ACF 62-118 BPM
    + compás lag 3/4 + fase Tiempo 1 φ* + 24 tríadas + selección MMR 16 zonas sin redundancia).
    Devuelve spans [(start_f, end_f, bank, role, chord), ...] o None si se usa fallback ligero.
    """
    active_frames = active_end - active_start
    if active_frames < sr * 4:
        return None
    try:
        import numpy as np
        import librosa
        from scipy.signal import butter, sosfiltfilt, medfilt
    except Exception:
        return None

    try:
        y_act = np.asarray(samples_i16[active_start:active_end], dtype=np.float32) / 32768.0
        if len(y_act) < sr * 4:
            return None

        hop = 256
        y_harm, y_perc = librosa.effects.hpss(y_act, margin=2.0)
        tuning = float(librosa.estimate_tuning(y=y_harm, sr=sr, bins_per_octave=36))
        chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr, hop_length=hop, bins_per_octave=36, tuning=tuning)

        perc_onset = librosa.onset.onset_strength(y=y_perc, sr=sr, hop_length=hop)
        sos_lp = butter(2, 220.0, btype="lowpass", fs=float(sr), output="sos")
        y_bass = sosfiltfilt(sos_lp, y_act).astype(np.float32)
        bass_onset = librosa.onset.onset_strength(y=y_bass, sr=sr, hop_length=hop)

        ch_sm = medfilt(chroma, kernel_size=(1, 5)) if chroma.shape[1] >= 7 else chroma
        hcdf = np.zeros(chroma.shape[1], dtype=np.float64)
        if chroma.shape[1] > 1:
            hcdf[1:] = np.linalg.norm(np.diff(ch_sm, axis=1), axis=0)

        def _norm01(v: Any) -> Any:
            v = np.asarray(v, dtype=np.float64)
            mn, mx = float(np.min(v)), float(np.max(v))
            return (v - mn) / (mx - mn + 1e-9)

        n_fr = min(len(perc_onset), len(bass_onset), len(hcdf))
        if n_fr < 40:
            return None
        comb_onset = 0.45 * _norm01(perc_onset[:n_fr]) + 0.30 * _norm01(bass_onset[:n_fr]) + 0.25 * _norm01(hcdf[:n_fr])

        # Autocorrelación FFT insesgada de media cero en rango 62..118 BPM
        centered = comb_onset - float(np.mean(comb_onset))
        fft_len = 1 << int(np.ceil(np.log2(2 * n_fr)))
        ac_full = np.fft.irfft(np.abs(np.fft.rfft(centered, n=fft_len)) ** 2)[:n_fr]
        denom_unb = np.arange(n_fr, 0, -1, dtype=np.float64)
        acf = ac_full / np.maximum(1.0, denom_unb)

        fr_rate = sr / float(hop)
        bpm_grid = np.arange(62.0, 118.1, 0.25)
        best_bpm = 84.0
        best_score = -1e9
        for cand_b in bpm_grid:
            lag_f = (60.0 / float(cand_b)) * fr_rate
            l_lo = int(np.floor(lag_f))
            l_hi = min(n_fr - 2, l_lo + 1)
            if l_lo < 5 or l_lo >= n_fr - 2:
                continue
            frac = lag_f - l_lo
            val = (1.0 - frac) * acf[l_lo] + frac * acf[l_hi]
            if 2 * l_lo < n_fr:
                val += 0.35 * acf[min(n_fr - 1, 2 * l_lo)]
            if val > best_score:
                best_score = float(val)
                best_bpm = float(cand_b)

        _, beat_frames = librosa.beat.beat_track(onset_envelope=comb_onset, sr=sr, hop_length=hop, bpm=best_bpm, tightness=120)
        beat_frames = np.asarray(beat_frames, dtype=int)
        if len(beat_frames) < 8:
            beat_s_est = int(round((60.0 / best_bpm) * fr_rate))
            beat_frames = np.arange(0, n_fr - 1, max(8, beat_s_est), dtype=int)
        if len(beat_frames) < 6:
            return None

        # Detección de compás lag=3 vs lag=4 y fase del Tiempo 1 φ*
        rms_h = librosa.feature.rms(y=y_harm, hop_length=hop)[0]
        bass_rms = librosa.feature.rms(y=y_bass, hop_length=hop)[0]
        b_hcdf = np.array([float(np.max(hcdf[max(0, b - 1) : min(n_fr, b + 2)])) for b in beat_frames])
        b_bass = np.array([float(np.mean(bass_rms[max(0, b - 1) : min(len(bass_rms), b + 3)])) for b in beat_frames])
        b_rms = np.array([float(np.mean(rms_h[max(0, b - 1) : min(len(rms_h), b + 3)])) for b in beat_frames])
        b_jump = np.maximum(0.0, np.diff(b_rms, prepend=b_rms[0]))
        metric_sig = 0.55 * _norm01(b_hcdf) + 0.45 * _norm01(b_bass)

        def _lag_corr(sig: Any, lg: int) -> float:
            if len(sig) <= lg + 2:
                return 0.0
            a, b = sig[:-lg] - np.mean(sig[:-lg]), sig[lg:] - np.mean(sig[lg:])
            den = float(np.linalg.norm(a) * np.linalg.norm(b))
            return float(np.dot(a, b) / den) if den > 1e-9 else 0.0

        m_beats = 3 if _lag_corr(metric_sig, 3) > _lag_corr(metric_sig, 4) * 1.06 else 4
        phase_scores = []
        sig_p = 0.55 * _norm01(b_hcdf) + 0.35 * _norm01(b_bass) + 0.10 * _norm01(b_jump)
        for ph in range(m_beats):
            phase_scores.append(float(np.mean(sig_p[ph::m_beats])) if len(sig_p[ph::m_beats]) else 0.0)
        best_phase = int(np.argmax(phase_scores))

        # 24 plantillas de tríadas mayores/menores
        triad_names: List[str] = []
        triad_mat: List[Any] = []
        for root_i, r_name in enumerate(_NOTE_NAMES_SHARP):
            maj_v = np.zeros(12, dtype=np.float64)
            maj_v[[root_i, (root_i + 4) % 12, (root_i + 7) % 12]] = [1.0, 0.85, 0.9]
            triad_mat.append(maj_v / np.linalg.norm(maj_v))
            triad_names.append(r_name)
            min_v = np.zeros(12, dtype=np.float64)
            min_v[[root_i, (root_i + 3) % 12, (root_i + 7) % 12]] = [1.0, 0.85, 0.9]
            triad_mat.append(min_v / np.linalg.norm(min_v))
            triad_names.append(f"{r_name}m")
        t_stack = np.vstack(triad_mat)

        mfcc = librosa.feature.mfcc(y=y_act, sr=sr, n_mfcc=13, hop_length=hop)
        beat_chords: List[str] = []
        beat_feats: List[Any] = []
        for idx_b, bf in enumerate(beat_frames):
            bf_hi = beat_frames[idx_b + 1] if idx_b + 1 < len(beat_frames) else min(chroma.shape[1], bf + max(8, int(round((60.0 / best_bpm) * fr_rate))))
            bf_hi = max(bf + 1, min(chroma.shape[1], bf_hi))
            c_vec = np.mean(chroma[:, bf:bf_hi], axis=1)
            c_norm = c_vec / (float(np.linalg.norm(c_vec)) + 1e-9)
            best_t = int(np.argmax(t_stack @ c_norm))
            beat_chords.append(triad_names[best_t])
            m_vec = np.mean(mfcc[:, bf : min(mfcc.shape[1], bf_hi)], axis=1)
            fv = np.concatenate([c_norm, m_vec / (float(np.linalg.norm(m_vec)) + 1e-9)])
            beat_feats.append(fv / (float(np.linalg.norm(fv)) + 1e-9))

        def _mmr_select(candidates: List[Dict[str, Any]], target_k: int) -> List[Dict[str, Any]]:
            if not candidates:
                return []
            if len(candidates) <= target_k:
                return candidates
            total_samps = max(1, active_frames)
            zones = 16
            chosen: List[Dict[str, Any]] = []
            used_idx: set[int] = set()
            # Pase 1: cobertura de 16 zonas cronológicas con diversidad coseno <= 0.94
            for zi in range(zones):
                if len(chosen) >= target_k:
                    break
                z_lo = zi * (total_samps / float(zones))
                z_hi = (zi + 1) * (total_samps / float(zones))
                best_i = None
                best_sc = -1e9
                for ci, cand in enumerate(candidates):
                    if ci in used_idx or not (z_lo <= cand["rel_start"] < z_hi):
                        continue
                    if chosen:
                        max_sim = max(float(np.dot(cand["feat"], ch["feat"])) for ch in chosen)
                        if max_sim > 0.94:
                            continue
                    else:
                        max_sim = 0.0
                    sc = cand["score"] - 0.35 * max_sim
                    if sc > best_sc:
                        best_sc = sc
                        best_i = ci
                if best_i is not None:
                    chosen.append(candidates[best_i])
                    used_idx.add(best_i)
            # Pase 2: completar hasta target_k relajando coseno si es necesario
            while len(chosen) < target_k:
                best_i = None
                best_sc = -1e9
                for ci, cand in enumerate(candidates):
                    if ci in used_idx:
                        continue
                    if chosen and any(abs(cand["rel_start"] - ch["rel_start"]) < int(0.35 * sr) for ch in chosen):
                        continue
                    max_sim = max((float(np.dot(cand["feat"], ch["feat"])) for ch in chosen), default=0.0)
                    sc = cand["score"] - 0.25 * max_sim
                    if sc > best_sc:
                        best_sc = sc
                        best_i = ci
                if best_i is None:
                    break
                chosen.append(candidates[best_i])
                used_idx.add(best_i)
            chosen.sort(key=lambda c: c["rel_start"])
            return chosen

        def _build_bank_candidates(beat_step: int, dur_beats: float, bank_lbl: str, role_lbl: str) -> List[Dict[str, Any]]:
            cands: List[Dict[str, Any]] = []
            max_dur_samp = int(10.0 * sr)
            min_dur_samp = int(0.55 * sr)
            for bi in range(best_phase, max(best_phase + 1, len(beat_frames) - 1), max(1, beat_step)):
                s_rel = int(beat_frames[bi] * hop)
                end_bi = bi + int(round(dur_beats))
                if end_bi < len(beat_frames):
                    e_rel = int(beat_frames[end_bi] * hop)
                else:
                    e_rel = min(active_frames, s_rel + int(round((60.0 / best_bpm) * dur_beats * sr)))
                e_rel = min(active_frames, max(s_rel + min_dur_samp, min(e_rel, s_rel + max_dur_samp)))
                if (e_rel - s_rel) < min_dur_samp or s_rel >= active_frames - min_dur_samp:
                    continue
                seg_f = y_act[s_rel:e_rel]
                rms_s = float(np.sqrt(np.mean(seg_f * seg_f)))
                if rms_s < 0.01:
                    continue
                sc = float(sig_p[bi]) + 0.4 * float(b_hcdf[bi])
                cands.append({
                    "rel_start": s_rel,
                    "rel_end": e_rel,
                    "bank": bank_lbl,
                    "role": role_lbl,
                    "chord": beat_chords[bi] if bi < len(beat_chords) else "",
                    "feat": beat_feats[bi],
                    "score": sc,
                })
            return cands

        spans: List[Dict[str, Any]] = []
        if mode_3bank:
            per_bank = max(4, min(16, max_slices // 3))
            cands_a = _build_bank_candidates(m_beats, float(m_beats), "A", f"Frase {m_beats}/4")
            cands_b = _build_bank_candidates(max(1, min(2, m_beats)), 2.0, "B", "Chop 2 Tiempos")
            turn_beats = 2.5 if m_beats == 3 else 3.0
            cands_c = _build_bank_candidates(max(1, m_beats - 1), turn_beats, "C", f"Hook / Turnaround {turn_beats:g}t")
            spans.extend(_mmr_select(cands_a, per_bank))
            spans.extend(_mmr_select(cands_b, per_bank))
            spans.extend(_mmr_select(cands_c, max(0, max_slices - len(spans))))
            # Si una canción es muy corta para completar los 3 bancos, completar subdividiendo segmentos largos
            if len(spans) < min(max_slices, 48):
                # Garantizar orden por banco A -> B -> C y añadir subdivisiones limpias si faltaran
                existing_keys = {(s["bank"], s["rel_start"]) for s in spans}
                for bk, dbts, rlbl in (("A", float(m_beats), f"Frase {m_beats}/4"), ("B", 2.0, "Chop 2 Tiempos"), ("C", turn_beats, f"Hook / Turnaround {turn_beats:g}t")):
                    bk_cur = [s for s in spans if s["bank"] == bk]
                    need = 16 - len(bk_cur)
                    if need <= 0 or len(spans) >= max_slices:
                        continue
                    extra_pool = _build_bank_candidates(1, dbts, bk, rlbl)
                    for item in extra_pool:
                        if len(bk_cur) >= 16 or len(spans) >= max_slices:
                            break
                        if (bk, item["rel_start"]) not in existing_keys:
                            spans.append(item)
                            bk_cur.append(item)
                            existing_keys.add((bk, item["rel_start"]))
        else:
            cands = _build_bank_candidates(max(1, m_beats // 2 if len(beat_frames) < max_slices * m_beats else m_beats), float(m_beats), "A", f"Frase {m_beats}/4")
            spans = _mmr_select(cands, max_slices)

        if not spans:
            return None

        return {
            "mir_engine": "librosa_hpss_hcdf_mmr",
            "bpm": round(best_bpm, 1),
            "time_signature": f"{m_beats}/4",
            "downbeat_phase": best_phase,
            "tuning_cents": int(round(tuning * 100.0)),
            "spans": [
                {
                    "start_f": active_start + int(s["rel_start"]),
                    "end_f": active_start + int(s["rel_end"]),
                    "bank": s["bank"],
                    "role": s["role"],
                    "chord": s["chord"],
                }
                for s in spans
            ],
        }
    except Exception:
        return None


def autochop_sample_to_16_pads(
    source_audio: str | Path,
    output_root: str | Path,
    max_slices: int = 16,
    kit_name: Optional[str] = None,
    style_hint: str = "",
    target_bpm: Optional[float] = None,
    chop_mode: str = "auto",
    adapt_mode: str = "auto",
) -> Dict[str, Any]:
    """
    Corta automáticamente un Loop, Bolero, Soul, Jazz o Breakbeat en hasta 16 o 48 pads (3 Bancos A/B/C MMR)
    mediante transientes, rejilla, puente 3/4→4/4 o motor MIR completo (HPSS+HCDF+downbeat φ*+MMR), con ajuste a
    cruces por cero (±5 ms), HPF 24Hz, techo anti-clipping -0.80 dBFS, micro-fades coseno (2ms/8ms) y dither TPDF.
    """
    src_p = Path(source_audio).resolve()
    root_p = Path(output_root).resolve()
    if not src_p.is_file():
        raise FileNotFoundError(f"Muestra no encontrada: {src_p}")

    max_slices = max(2, min(48, int(max_slices)))
    samples = _convert_audio(src_p, mono=True, sample_rate=44100)
    sr = 44100
    total_frames = len(samples)
    if total_frames < sr // 4:
        raise ValueError("La muestra es demasiado corta para dividirla en múltiples cortes.")

    clean_stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", (kit_name or src_p.stem)).strip("_") or "Chop_Kit"
    chop_dir = root_p / "Custom_Kits" / f"{clean_stem}_Chops" / "slices"
    chop_dir.mkdir(parents=True, exist_ok=True)

    rhythm_info = analyze_rhythmic_pattern_and_hiphop_adaptation(
        src_p,
        style_hint=style_hint,
        target_bpm_hint=target_bpm,
        preloaded_samples=samples,
        preloaded_sr=sr,
        adapt_mode=adapt_mode,
    )
    rhythm = rhythm_info["rhythm_analysis"]
    adaptation = rhythm_info["hiphop_adaptation"]
    eff_bpm = float(rhythm.get("effective_source_bpm") or rhythm.get("source_bpm") or 84.0)
    style_info = detect_musical_style(f"{src_p.name} {style_hint}")

    norm_chop_mode = str(chop_mode or "auto").strip().lower()
    if norm_chop_mode not in ("auto", "phrases", "phrase_3_4_to_4_4", "bar_grid", "transients", "mmr_3bank_48"):
        norm_chop_mode = "auto"

    # Detectar tipo musical antes de elegir estrategia para evitar cortes microscópicos en Boleros / canciones largas
    low_src = f"{src_p.name} {style_hint}".lower()
    is_melodic = (
        style_info.get("id") in ("bolero", "oldies", "soul_vintage", "jazz_hop", "lofi", "rnb_soul", "drumless", "bossa_samba", "cumbia_son", "tango_vals", "psych_library")
        or rhythm.get("acoustic_style_id") in ("bolero", "oldies", "soul_vintage", "jazz_hop", "drumless", "tango_vals")
        or any(k in low_src for k in ["loop", "guitar", "requinto", "piano", "rhodes", "wurli", "sax", "horn", "strings", "vocal", "chord", "bolero", "ranchera", "oldies", "doowop", "doo-wop", "lowrider", "soul", "jazz", "bossa", "tango", "cumbia", "vals", "bandoneon", "melod", "mono"])
    )

    # 1. Calcular envolvente de flujo de energía (hop = 441 muestras = 10 ms)
    hop = 441
    energies: List[float] = []
    for pos in range(0, total_frames - hop, hop):
        chunk = samples[pos : pos + hop]
        energies.append(sum(abs(x) for x in chunk) / hop)

    peak_rms = max(energies) if energies else 0.0
    sil_thr = max(60.0, peak_rms * 0.03)
    active_start = 0
    active_end = total_frames
    if len(energies) > 20 and peak_rms > 0.0:
        first_act = next((idx for idx, e in enumerate(energies) if e >= sil_thr), 0) * hop
        last_act = (len(energies) - 1 - next((idx for idx, e in enumerate(reversed(energies)) if e >= sil_thr), 0)) * hop + hop
        if first_act > int(0.45 * sr) and (last_act - first_act) >= int(1.2 * sr):
            active_start = max(0, first_act - int(0.02 * sr))
        if last_act > active_start + int(1.2 * sr):
            active_end = min(total_frames, last_act + int(0.15 * sr))

    active_span = max(sr // 2, active_end - active_start)
    dur_sec_total = total_frames / float(sr)

    if norm_chop_mode == "mmr_3bank_48":
        applied_chop_mode = "mmr_3bank_48"
        if max_slices <= 16:
            max_slices = 48
    elif norm_chop_mode == "auto":
        if is_melodic and (dur_sec_total >= 14.0 or (rhythm.get("time_signature") in ("4/4", "5/4") and dur_sec_total >= 8.0)):
            applied_chop_mode = "phrases"
        else:
            applied_chop_mode = str(adaptation.get("recommended_chop_mode") or "transients")
    else:
        applied_chop_mode = norm_chop_mode

    mir_result: Optional[Dict[str, Any]] = None
    if applied_chop_mode == "mmr_3bank_48" or (applied_chop_mode == "phrases" and dur_sec_total >= 10.0 and is_melodic):
        mir_result = _extract_mir_beats_chords_and_mmr(
            samples,
            sr,
            active_start,
            active_end,
            max_slices=max_slices,
            mode_3bank=(applied_chop_mode == "mmr_3bank_48"),
        )

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

    slice_specs: List[Dict[str, Any]] = []
    min_mir_spans = min(max_slices, 12) if applied_chop_mode == "mmr_3bank_48" else max_slices
    if mir_result and len(mir_result.get("spans") or []) >= min_mir_spans:
        for sp in mir_result["spans"][:max_slices]:
            s_f = _snap_zero_crossing(int(sp["start_f"]))
            e_f = _snap_zero_crossing(min(active_end, int(sp["end_f"])))
            if e_f > s_f + sr // 5:
                slice_specs.append({
                    "start_f": s_f,
                    "end_f": e_f,
                    "bank": sp.get("bank", "A"),
                    "role": sp.get("role", "Frase MIR"),
                    "chord": sp.get("chord", ""),
                })

    if applied_chop_mode == "mmr_3bank_48" and len(slice_specs) < max_slices:
        # Completar hasta max_slices repartiendo 3 bancos A/B/C deterministas si audio es corto o monocorde
        beat_f = max(sr // 4, int(round((60.0 / max(45.0, eff_bpm)) * sr)))
        bar_beats = 3 if rhythm.get("time_signature") in ("3/4", "6/8") else 4
        bank_defs = (
            ("A", float(bar_beats), f"Frase {bar_beats}/4"),
            ("B", 2.0, "Chop 2 Tiempos"),
            ("C", 2.5 if bar_beats == 3 else 3.0, "Hook / Turnaround"),
        )
        per_bk = max(4, min(16, max_slices // 3))
        for b_idx, (bk_name, bk_beats, bk_role) in enumerate(bank_defs):
            cur_bk = [s for s in slice_specs if s["bank"] == bk_name]
            need_bk = per_bk - len(cur_bk)
            if need_bk <= 0:
                continue
            step_span = max(sr // 2, int(active_span / float(max(1, need_bk))))
            win_samp = max(int(0.55 * sr), min(int(10.0 * sr), int(round(bk_beats * beat_f))))
            for zi in range(need_bk):
                if len(slice_specs) >= max_slices:
                    break
                raw_s = active_start + int(zi * step_span)
                if raw_s + int(0.45 * sr) >= active_end:
                    raw_s = max(active_start, active_end - win_samp)
                s_f = _snap_zero_crossing(raw_s)
                e_f = _snap_zero_crossing(min(active_end, s_f + win_samp))
                if e_f > s_f + sr // 4:
                    slice_specs.append({
                        "start_f": s_f,
                        "end_f": e_f,
                        "bank": bk_name,
                        "role": bk_role,
                        "chord": "",
                    })
        slice_specs = slice_specs[:max_slices]

    if not slice_specs:
        beat_frames = int(round((60.0 / max(45.0, eff_bpm)) * sr))
        flux: List[tuple[float, int]] = []
        if applied_chop_mode in ("phrases", "mmr_3bank_48") or (applied_chop_mode == "transients" and is_melodic and dur_sec_total >= 14.0):
            min_dist_frames = max(int(0.75 * sr), int((active_span / float(max_slices)) * 0.55))
            min_tail_frames = min_dist_frames
        elif applied_chop_mode in ("phrase_3_4_to_4_4", "bar_grid"):
            min_dist_frames = max(int(0.18 * sr), min(int(0.45 * sr), int(beat_frames * 0.35)))
            min_tail_frames = max(min_dist_frames, int(0.24 * sr))
        else:
            min_dist_frames = max(int(0.09 * sr), int(active_span // (max_slices * 2.5)))
            min_tail_frames = max(min_dist_frames, int(0.16 * sr))

        for i in range(1, len(energies) - 1):
            diff = energies[i] - energies[i - 1]
            if diff > 0 and diff >= energies[i - 1] * 0.25 and diff > energies[i + 1] - energies[i]:
                f_pos = i * hop
                if active_start <= f_pos <= active_end - min_tail_frames:
                    flux.append((diff, f_pos))

        flux.sort(key=lambda t: t[0], reverse=True)
        flux_by_frame = {f_pos: score for score, f_pos in flux}
        nudge_win = max(1, int((0.18 if applied_chop_mode == "phrases" else 0.035) * sr))

        def _nudge_to_flux(target_f: int, win_override: Optional[int] = None) -> int:
            w_lim = win_override if win_override is not None else nudge_win
            best_cand = target_f
            best_sc = -1.0
            for cand_pos, sc in flux_by_frame.items():
                if abs(cand_pos - target_f) <= w_lim and cand_pos <= active_end - min_tail_frames and sc > best_sc:
                    best_sc = sc
                    best_cand = cand_pos
            return best_cand

        onset_frames = [active_start]
        if applied_chop_mode in ("phrases", "mmr_3bank_48") or (applied_chop_mode in ("phrase_3_4_to_4_4", "bar_grid") and dur_sec_total >= max(14.0, (max_slices * 2.5 * 60.0) / max(45.0, eff_bpm))):
            zone_w = active_span / float(max_slices)
            bar_beats = 3.0 if rhythm.get("time_signature") in ("3/4", "6/8") else 4.0
            bar_frames = max(beat_frames, int(round(beat_frames * bar_beats)))
            for zi in range(1, max_slices):
                raw_pos = active_start + int(round(zi * zone_w))
                if beat_frames >= sr // 4 and zone_w >= bar_frames * 0.65:
                    rel_bars = max(1, int(round((raw_pos - active_start) / float(bar_frames))))
                    q_pos = active_start + rel_bars * bar_frames
                    if abs(q_pos - raw_pos) <= zone_w * 0.42:
                        raw_pos = q_pos
                if raw_pos >= active_end - min_tail_frames:
                    continue
                cand = _nudge_to_flux(raw_pos, win_override=max(nudge_win, int(zone_w * 0.25)))
                cand = max(active_start + min_dist_frames, min(active_end - min_tail_frames, cand))
                if cand <= active_end - min_tail_frames and all(abs(cand - existing) >= min_dist_frames for existing in onset_frames):
                    onset_frames.append(cand)
        elif applied_chop_mode == "phrase_3_4_to_4_4" and beat_frames >= sr // 4:
            is_12_8 = rhythm.get("time_signature") == "12/8"
            bar_len = 4.0 if is_12_8 else 3.0
            if is_12_8:
                use_triplets = (active_span / float(max(1, beat_frames))) < (max_slices * 0.85)
                bar_offsets: tuple[float, ...] = (
                    (0.0, 0.667, 1.0, 1.667, 2.0, 2.667, 3.0, 3.667) if use_triplets else (0.0, 1.0, 2.0, 3.0)
                )
            else:
                bar_offsets = (0.0, 1.0, 2.0, 2.5)
            bar_idx = 0
            while len(onset_frames) < max_slices:
                bar_base = bar_idx * bar_len
                added_in_bar = False
                for beat_off in bar_offsets:
                    if len(onset_frames) >= max_slices:
                        break
                    abs_beats = bar_base + beat_off
                    if abs_beats <= 0.05:
                        continue
                    target_f = active_start + int(round(abs_beats * beat_frames))
                    if target_f >= active_end - min_tail_frames:
                        continue
                    cand = _nudge_to_flux(target_f)
                    if cand <= active_end - min_tail_frames and all(abs(cand - existing) >= min_dist_frames for existing in onset_frames):
                        onset_frames.append(cand)
                        added_in_bar = True
                if active_start + (bar_base + bar_len) * beat_frames >= active_end - min_tail_frames and not added_in_bar:
                    break
                bar_idx += 1
                if bar_idx > 32:
                    break
        elif applied_chop_mode == "bar_grid" and beat_frames >= sr // 4:
            use_half = (active_span / float(beat_frames)) < (max_slices * 0.85)
            grid_step = max(min_dist_frames, beat_frames // (2 if use_half else 1))
            g = active_start + grid_step
            while g < active_end - min_tail_frames and len(onset_frames) < max_slices:
                cand = _nudge_to_flux(g)
                if cand <= active_end - min_tail_frames and all(abs(cand - existing) >= min_dist_frames for existing in onset_frames):
                    onset_frames.append(cand)
                g += grid_step
        else:
            if dur_sec_total >= 4.0:
                zone_w = active_span / float(max_slices)
                for zi in range(1, max_slices):
                    z_lo = active_start + int(zi * zone_w)
                    z_hi = min(active_end - min_tail_frames, active_start + int((zi + 1) * zone_w))
                    if z_hi <= z_lo:
                        continue
                    zone_hits = [(sc, fp) for sc, fp in flux if z_lo <= fp < z_hi]
                    if zone_hits:
                        cand = zone_hits[0][1]
                        if cand <= active_end - min_tail_frames and all(abs(cand - existing) >= min_dist_frames for existing in onset_frames):
                            onset_frames.append(cand)
            for _, f_pos in flux:
                if len(onset_frames) >= max_slices:
                    break
                if f_pos <= active_end - min_tail_frames and all(abs(f_pos - existing) >= min_dist_frames for existing in onset_frames):
                    onset_frames.append(f_pos)

        if applied_chop_mode != "phrases":
            for _, f_pos in flux:
                if len(onset_frames) >= max_slices:
                    break
                if f_pos <= active_end - min_tail_frames and all(abs(f_pos - existing) >= min_dist_frames for existing in onset_frames):
                    onset_frames.append(f_pos)

            if len(onset_frames) < max_slices and eff_bpm >= 45.0:
                subdiv = 3 if rhythm.get("time_signature") in ("3/4", "6/8", "12/8") else 2
                grid_step = max(min_dist_frames, beat_frames // subdiv)
                g = active_start + grid_step
                while g < active_end - min_tail_frames and len(onset_frames) < max_slices:
                    best_cand = _nudge_to_flux(g)
                    if best_cand <= active_end - min_tail_frames and all(abs(best_cand - existing) >= min_dist_frames for existing in onset_frames):
                        onset_frames.append(best_cand)
                    g += grid_step

        onset_frames.sort()
        while len(onset_frames) < max_slices:
            gaps = [
                ((onset_frames[i + 1] if i + 1 < len(onset_frames) else active_end) - onset_frames[i], i)
                for i in range(len(onset_frames))
            ]
            max_gap, idx = max(gaps, key=lambda g: g[0])
            if max_gap < max(int(0.08 * sr), min_dist_frames * 2):
                break
            mid_frame = onset_frames[idx] + max_gap // 2
            if mid_frame <= active_end - min_tail_frames and (active_end - mid_frame) >= min_tail_frames:
                onset_frames.insert(idx + 1, mid_frame)
            else:
                break

        snapped = [_snap_zero_crossing(active_start)] + [_snap_zero_crossing(f) for f in onset_frames[1:]]
        snapped = sorted(set(f for f in snapped if f < active_end - min(sr // 8, min_tail_frames)))[:max_slices]
        if not snapped:
            snapped = [_snap_zero_crossing(active_start)]

        max_pad_frames = int(10.0 * sr) if (applied_chop_mode == "phrases" or dur_sec_total >= 30.0) else total_frames
        chord_list = [s.get("chord", "") for s in (mir_result or {}).get("spans", [])]
        for idx, start_f in enumerate(snapped):
            next_f = snapped[idx + 1] if idx + 1 < len(snapped) else active_end
            end_f = _snap_zero_crossing(min(next_f, start_f + max_pad_frames))
            if end_f <= start_f:
                end_f = min(next_f, start_f + max_pad_frames)
            if applied_chop_mode == "phrases":
                role_cycle = ("Intro / Phrase", "Chord / Melody", "Hook / Theme", "Bridge / Turnaround")
                slice_role = role_cycle[idx % 4]
            elif applied_chop_mode == "phrase_3_4_to_4_4":
                role_cycle = ("Downbeat (Tiempo 1)", "Chord / Phrase (Tiempo 2)", "Chord / Phrase (Tiempo 3)", "Pickup (2.5 → 4)")
                slice_role = role_cycle[idx % 4]
            elif applied_chop_mode == "bar_grid":
                slice_role = "Downbeat" if (idx % 4 == 0) else ("Backbeat / Phrase" if (idx % 4 == 2) else "Syncopation")
            else:
                dur_s = (end_f - start_f) / float(sr)
                slice_role = "Downbeat" if idx == 0 else ("Chord / Phrase" if dur_s >= 0.40 else ("Pickup" if idx % 4 == 3 else "Syncopation"))
            slice_specs.append({
                "start_f": start_f,
                "end_f": end_f,
                "bank": ("A", "B", "C")[min(2, idx // 16)],
                "role": slice_role,
                "chord": chord_list[idx] if idx < len(chord_list) else "",
            })

    slice_sound_type = "MELODIC_LOOP" if is_melodic else "PERCUSSION"
    apply_tune = int(adaptation.get("repitch_semitones", 0)) if abs(int(adaptation.get("repitch_semitones", 0))) <= 5 else 0
    apply_fine = int(adaptation.get("repitch_fine_tune_cents", 0)) if apply_tune != 0 or abs(int(adaptation.get("repitch_fine_tune_cents", 0))) >= 8 else 0

    # 3. Exportar cada slice con mastering anti-clipping (-0.80 dBFS, HPF 24Hz, micro-fades coseno 2ms/8ms, TPDF dither)
    pads_out: List[Dict[str, Any]] = []
    detected_chords_summary: List[str] = []
    for idx, spec in enumerate(slice_specs):
        start_f = int(spec["start_f"])
        end_f = int(spec["end_f"])
        raw_seg = samples[start_f:end_f]
        if len(raw_seg) < 64:
            continue
        f32_seg = [x / 32768.0 for x in raw_seg]
        slice_pcm = _master_pcm_float32_anti_clip(
            [f32_seg],
            sample_rate=sr,
            target_peak_dbfs=-0.80,
            apply_hpf_24hz=True,
            only_attenuate_above_ceiling=True,
            fade_in_ms=2.0,
            fade_out_ms=8.0,
        )
        if not slice_pcm:
            continue

        pad_num = len(pads_out) + 1
        dur_slice = round(len(slice_pcm) / float(sr), 3)
        chord_lbl = str(spec.get("chord") or "").strip()
        if chord_lbl:
            detected_chords_summary.append(chord_lbl)
        slice_role = str(spec.get("role") or "Chop")
        if chord_lbl and f"[{chord_lbl}]" not in slice_role:
            slice_role = f"{slice_role} [{chord_lbl}]"

        slice_name = f"{clean_stem}_Slice_{pad_num:02d}.wav"
        slice_path = chop_dir / slice_name
        raw_bytes = struct.pack(f"<{len(slice_pcm)}h", *slice_pcm)
        with wave.open(str(slice_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(raw_bytes)

        smart_vol_meta = compute_smart_pad_volume(slice_sound_type, slice_path)
        smart_vol = smart_vol_meta["volume"]
        rel_slice = slice_path.relative_to(root_p).as_posix()
        pads_out.append({
            "pad": pad_num,
            "bank": spec.get("bank", ("A", "B", "C")[min(2, (pad_num - 1) // 16)]),
            "rel_path": rel_slice,
            "filename": slice_name,
            "sound_type": slice_sound_type,
            "slice_role": slice_role,
            "detected_chord": chord_lbl,
            "duration_sec": dur_slice,
            "mute_group": 6,  # Grupo 6: Slicer / Chop monofónico (cada slice corta al anterior)
            "volume": smart_vol,
            "rms_dbfs": smart_vol_meta.get("rms_dbfs", -12.0),
            "peak_dbfs": smart_vol_meta.get("peak_dbfs", -1.0),
            "recommended_trigger_mode": "noteon" if (is_melodic and dur_slice >= 0.55) else "oneshot",
            "pan": 0.5,
            "tune": apply_tune,
            "fine_tune": apply_fine,
        })

    return {
        "success": True,
        "kit_name": f"{clean_stem}_Chops",
        "source_sample": src_p.name,
        "slices_count": len(pads_out),
        "applied_chop_mode": applied_chop_mode,
        "mir_engine": (mir_result or {}).get("mir_engine", "envelope_zero_crossing"),
        "downbeat_phase": (mir_result or {}).get("downbeat_phase", 0),
        "detected_chords": detected_chords_summary[:16],
        "chop_folder": chop_dir.relative_to(root_p).as_posix(),
        "recommended_bpm": adaptation["target_bpm"],
        "recommended_mute_profile": "jazz_funk" if is_melodic else style_info.get("mute_profile", "real_drums"),
        "rhythm_analysis": rhythm,
        "hiphop_adaptation": adaptation,
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
                ctune = inst.get("coarseTune")
                if isinstance(ctune, (int, float)) and not isinstance(ctune, bool):
                    inst["coarseTune"] = max(-24, min(24, int(round(ctune))))
                if layersv and isinstance(layersv[0], dict):
                    lay0 = layersv[0]
                    lvol = lay0.get("volume")
                    if isinstance(lvol, dict):
                        lvol["gainCoefficient"] = 1.0
                        lvol["controlValue"] = 1.0
                    sinfo = lay0.get("sliceInfo")
                    if isinstance(sinfo, dict) and wav_cand is not None:
                        cur_end = int(sinfo.get("End", 0) or 0)
                        if cur_end <= 0:
                            n_frames = _get_wav_frames(wav_cand)
                            if n_frames > 0:
                                if sinfo.get("Start") is None:
                                    sinfo["Start"] = 0
                                sinfo["End"] = n_frames
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


# ==============================================================================
# 5. INTEGRACIÓN BEATOS RACK <-> MPCTK ESCALAS & SAMPQOL OS (mpcqol.conf)
# ==============================================================================

SAMPQOL_CONF_SCHEMA: List[Dict[str, Any]] = [
    {"key": "zerosnap", "label": "Snap to Zero Crossing", "values": {0: "Stock", 1: "Always"}, "default": 1, "group": "SAMPLE"},
    {"key": "linkslices", "label": "Link Slices Default", "values": {0: "Off", 1: "On"}, "default": 1, "group": "SAMPLE"},
    {"key": "chopwarn", "label": "Chop Threshold Warn", "values": {0: "After Edits", 1: "Always"}, "default": 0, "group": "SAMPLE"},
    {"key": "thrmax", "label": "Threshold Max Slices", "values": {0: "16", 1: "32", 2: "64", 3: "128"}, "default": 2, "group": "SAMPLE"},
    {"key": "askerasepad", "label": "Ask Before Erase Pad", "values": {0: "Off", 1: "On"}, "default": 1, "group": "SAMPLE"},
    {"key": "killeq", "label": "Pad EQ / Kill EQ Engine", "values": {0: "Off", 1: "On"}, "default": 1, "group": "SAMPLE"},
    {"key": "keysdefault", "label": "MIDI Keyboard Plays", "values": {0: "All Pads", 1: "Selected Pad"}, "default": 1, "group": "SAMPLE"},
    {"key": "keyschops", "label": "MIDI Keys on Chop Pad", "values": {0: "Slices", 1: "Pitch"}, "default": 0, "group": "SAMPLE"},
    {"key": "mutetype", "label": "Mute Type (5ms Fade)", "values": {0: "Audio (Instant+Fade)", 1: "Event (Notes)"}, "default": 0, "group": "SEQUENCE"},
    {"key": "monitor", "label": "CPU/RAM & Clip Monitor", "values": {0: "Off", 1: "On (Always)", 2: "Warn Only"}, "default": 2, "group": "SYSTEM"},
    {"key": "knobvalues", "label": "Show Knob Values", "values": {0: "Stock", 1: "Always"}, "default": 1, "group": "SYSTEM"},
    {"key": "padfxfixed", "label": "Pad FX Routing", "values": {0: "Stock", 1: "Fixed"}, "default": 1, "group": "FX"},
    {"key": "xpmix", "label": "Export Mixdown", "values": {0: "Off", 1: "On"}, "default": 1, "group": "EXPORT"},
    {"key": "xpstems", "label": "Export Individual Stems", "values": {0: "Off", 1: "On"}, "default": 1, "group": "EXPORT"},
    {"key": "xpmfx", "label": "Export Master FX", "values": {0: "Off", 1: "On"}, "default": 1, "group": "EXPORT"},
    {"key": "xptail", "label": "Export Audio Tail", "values": {0: "0s", 1: "1s", 2: "2s", 3: "4s"}, "default": 2, "group": "EXPORT"},
    {"key": "xpbpm", "label": "Append BPM to Exports", "values": {0: "Off", 1: "Mix Only", 2: "Mix + Stems"}, "default": 2, "group": "EXPORT"},
    {"key": "rstail", "label": "Resample Tail", "values": {0: "0s", 1: "1s", 2: "2s", 3: "4s"}, "default": 2, "group": "SAMPLE"},
    # Hardware / Bridge keys present in real SampQOL v0.2.0 /mpcqol.conf
    {"key": "screenlevel", "label": "Screen Brightness Level", "values": {1: "1 (Dim)", 2: "2", 3: "3 (Med)", 4: "4", 5: "5", 6: "6 (Max)"}, "default": 3, "group": "SYSTEM"},
    {"key": "padlevel", "label": "Pad Sensitivity Level", "values": {1: "1 (Lightest)", 2: "2", 3: "3 (Med)", 4: "4", 5: "5", 6: "6 (Hardest)"}, "default": 3, "group": "SYSTEM"},
    {"key": "follow", "label": "Follow Playhead", "values": {0: "Off", 1: "Page", 2: "Step"}, "default": 0, "group": "SEQUENCE"},
    {"key": "rearusb", "label": "Audio Input Route", "values": {0: "Rear Line Inputs", 1: "USB Audio"}, "default": 0, "group": "SAMPLE"},
    {"key": "resamplekfx", "label": "Resample Knob FX", "values": {0: "Off", 1: "On"}, "default": 0, "group": "FX"},
    {"key": "resamplepfx", "label": "Resample Pad FX", "values": {0: "Off", 1: "On"}, "default": 0, "group": "FX"},
    {"key": "scale", "label": "Scale Mode Default", "values": {0: "Off", 1: "On"}, "default": 1, "group": "SEQUENCE"},
    {"key": "scalekey", "label": "Scale Root Note (0=C..11=B)", "values": {i: n for i, n in enumerate(["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"])}, "default": 6, "group": "SEQUENCE"},
    {"key": "scaletype", "label": "Scale Type Index", "values": {i: f"Scale {i}" for i in range(0, 12)}, "default": 2, "group": "SEQUENCE"},
    {"key": "tunerpad7", "label": "Pad 7 Chromatic Tuner Shortcut", "values": {0: "Off", 1: "On"}, "default": 0, "group": "SYSTEM"},
]

SAMPQOL_PRESETS: Dict[str, Dict[str, int]] = {
    "beatos_master": {
        "zerosnap": 1, "linkslices": 1, "chopwarn": 0, "thrmax": 2, "askerasepad": 1,
        "killeq": 1, "keysdefault": 1, "mutetype": 0, "monitor": 2, "knobvalues": 1,
        "padfxfixed": 1, "xpmix": 1, "xpstems": 1, "xpmfx": 1, "xptail": 2, "xpbpm": 2, "rstail": 2,
    },
    "live_performance": {
        "zerosnap": 1, "linkslices": 1, "chopwarn": 0, "thrmax": 2, "askerasepad": 1,
        "killeq": 1, "keysdefault": 1, "mutetype": 0, "monitor": 1, "knobvalues": 1,
        "padfxfixed": 1,
    },
    "stock_defaults": {
        "zerosnap": 0, "linkslices": 1, "chopwarn": 0, "thrmax": 0, "askerasepad": 0,
        "killeq": 1, "keysdefault": 1, "mutetype": 0, "monitor": 0, "knobvalues": 0,
        "padfxfixed": 0, "xpmix": 1, "xpstems": 0, "xpmfx": 1, "xptail": 0, "xpbpm": 0, "rstail": 0,
    },
}


def build_rack_scale_bank(
    sample_path: str | Path,
    scale: str = "minor",
    target_root_note: str = "C2",
    source_root_note: Optional[str] = None,
    start_octave: int = 0,
    bank_index: int = 0,
    monophonic: bool = True,
    auto_detect_pitch: bool = True,
    source_root: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    Expande una muestra única sobre los 16 pads de un banco del BeatOS Rack siguiendo una escala
    musical (MPC-Sample-Toolkit style), compensando automáticamente su pitch original y cents.
    """
    sample_file = Path(sample_path).resolve()
    if not sample_file.is_file():
        raise FileNotFoundError(f"Muestra de audio no encontrada: {sample_path}")

    pitch_info: Dict[str, Any] = {}
    if auto_detect_pitch:
        try:
            pitch_info = detect_sample_pitch_and_key(sample_file)
        except Exception:
            pitch_info = {}

    tgt_pc, tgt_oct = parse_note(target_root_note)
    tgt_midi = (tgt_oct + 1) * 12 + tgt_pc

    src_midi: Optional[int] = None
    if source_root_note and str(source_root_note).strip():
        s_pc, s_oct = parse_note(source_root_note)
        src_midi = (s_oct + 1) * 12 + s_pc
    elif pitch_info.get("midi_note"):
        src_midi = int(pitch_info["midi_note"])
    else:
        src_midi = tgt_midi

    base_shift = tgt_midi - src_midi
    cents_offset = int(round(float(pitch_info.get("cents_offset") or 0))) if auto_detect_pitch else 0
    fine_corr = max(-90, min(90, -cents_offset)) if float(pitch_info.get("f0_hz") or 0.0) > 0.0 else 0

    offsets = build_scale_offsets(scale, count=16, start_octave=int(start_octave), clamp_range=(-48, 48))
    stype = "BASS_808" if monophonic else "KEYS_SYNTH"
    smart_vol = compute_smart_pad_volume(stype, sample_file)["volume"]
    bank_idx = max(0, min(7, int(bank_index)))

    rel_path = ""
    if source_root:
        try:
            rel_path = sample_file.relative_to(Path(source_root).resolve()).as_posix()
        except ValueError:
            rel_path = ""

    pads_out: List[Dict[str, Any]] = []
    for idx, step_semi in enumerate(offsets):
        slot = idx + 1
        total_tune = max(-24, min(24, int(base_shift + step_semi)))
        note_label = note_from_root_offset(tgt_pc, tgt_oct, step_semi)
        pads_out.append({
            "pad": bank_idx * 16 + slot,
            "slot": slot,
            "note_label": note_label,
            "rel_path": rel_path,
            "source_path": str(sample_file),
            "filename": sample_file.name,
            "sound_type": stype,
            "volume": smart_vol,
            "pan": 0.5,
            "tune": total_tune,
            "fine_tune": fine_corr,
            "root_note": int(max(0, min(127, src_midi))),
            "key_track": True,
            "trigger_mode": "noteon" if monophonic else "oneshot",
            "monophonic": bool(monophonic),
            "mute_group": 3 if monophonic else 0,
            "tail_length": 0.05 if monophonic else 0.0,
        })

    return {
        "success": True,
        "scale": scale,
        "target_root_note": target_root_note,
        "start_octave": int(start_octave),
        "bank_index": bank_idx,
        "source_midi_note": src_midi,
        "fine_tune_correction": fine_corr,
        "detected_pitch": pitch_info,
        "pads": pads_out,
    }


def read_mpcqol_conf(source_root: str | Path) -> Dict[str, Any]:
    """Lee `/mpcqol.conf` y detecta si SampQOL OS está instalado en la tarjeta SD (solo lectura)."""
    root_p = Path(source_root)
    conf_path = root_p / "mpcqol.conf"
    autorun_so = root_p / "autorun" / "mpcqol.so"
    values: Dict[str, str] = {}
    if conf_path.is_file():
        for raw_line in conf_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()

    settings_view = []
    for item in SAMPQOL_CONF_SCHEMA:
        key = item["key"]
        raw_val = values.get(key, str(item["default"]))
        try:
            int_val = int(raw_val)
        except ValueError:
            int_val = item["default"]
        settings_view.append({
            "key": key,
            "label": item["label"],
            "group": item["group"],
            "value": int_val,
            "value_label": item["values"].get(int_val, str(int_val)),
            "choices": item["values"],
            "default": item["default"],
        })

    return {
        "success": True,
        "sampqol_detected": autorun_so.is_file(),
        "conf_exists": conf_path.is_file(),
        "conf_path": str(conf_path),
        "backup_exists": (root_p / "mpcqol.conf.bak-beatos").is_file(),
        "raw_values": values,
        "schema": settings_view,
        "presets": list(SAMPQOL_PRESETS.keys()),
        "preset_map": SAMPQOL_PRESETS,
    }


def update_mpcqol_conf(
    source_root: str | Path,
    updates: Optional[Dict[str, Any]] = None,
    preset: Optional[str] = None,
) -> Dict[str, Any]:
    """Actualiza `/mpcqol.conf` con backup `.bak-beatos`, conservando comentarios y claves existentes."""
    root_p = Path(source_root)
    conf_path = root_p / "mpcqol.conf"
    backup_path = root_p / "mpcqol.conf.bak-beatos"

    if conf_path.is_file() and not backup_path.is_file():
        shutil.copy2(conf_path, backup_path)

    valid_keys = {item["key"]: item for item in SAMPQOL_CONF_SCHEMA}
    pending: Dict[str, int] = {}
    if preset:
        preset_key = str(preset).strip().lower()
        if preset_key not in SAMPQOL_PRESETS:
            raise ValueError(f"Preset mpcqol.conf desconocido: {preset}")
        pending.update(SAMPQOL_PRESETS[preset_key])
    if updates is not None and not isinstance(updates, dict):
        raise ValueError("El parámetro 'settings' debe ser un objeto JSON")
    if isinstance(updates, dict):
        for k, v in updates.items():
            if k not in valid_keys:
                continue
            if isinstance(v, bool):
                raise ValueError(f"Valor inválido {v} para {k} (permitidos: {list(valid_keys[k]['values'].keys())})")
            iv = int(v)
            allowed = valid_keys[k]["values"]
            if iv not in allowed:
                raise ValueError(f"Valor inválido {iv} para {k} (permitidos: {list(allowed.keys())})")
            pending[k] = iv

    existing_lines = (
        conf_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if conf_path.is_file()
        else []
    )
    out_lines: List[str] = []
    seen_keys: set[str] = set()
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out_lines.append(raw_line)
            continue
        k, _ = stripped.split("=", 1)
        k_clean = k.strip()
        if k_clean in pending:
            out_lines.append(f"{k_clean}={pending[k_clean]}")
            seen_keys.add(k_clean)
        else:
            out_lines.append(raw_line)

    for k_clean, iv in pending.items():
        if k_clean not in seen_keys:
            out_lines.append(f"{k_clean}={iv}")

    tmp_path = root_p / ".mpcqol.conf.tmp"
    tmp_path.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    os.replace(tmp_path, conf_path)

    res = read_mpcqol_conf(root_p)
    res["updated_keys"] = sorted(pending.keys())
    res["applied_preset"] = preset or ""
    return res


# ==============================================================================
# 6. INTEGRACIÓN BEATOS <-> MELODEE v0.4.0 (Melodee/settings + Estado Boot)
# ==============================================================================

MELODEE_SETTINGS_SCHEMA: List[Dict[str, Any]] = [
    # SYSTEM & SCREEN
    {"key": "features", "label": "UI Mode (Basic / Full)", "values": {0: "Basic", 1: "Full (v0.4.0 Default)"}, "default": 1, "group": "SYSTEM"},
    {"key": "palette", "label": "Screen Palette", "values": {0: "NIGHT", 1: "DAY", 2: "CONTRAST", 3: "SUNSET", 4: "OCEAN", 5: "NEON", 6: "CANDY", 7: "LO-FI", 8: "LCD"}, "default": 0, "group": "SCREEN"},
    {"key": "font", "label": "Screen Typeface", "values": {0: "Rubik", 1: "Inter Tight", 2: "Atkinson", 3: "Space Grotesk", 4: "IBM Plex", 5: "Manrope", 6: "Melodee Pixel", 7: "VT323"}, "default": 0, "group": "SCREEN"},
    {"key": "screen", "label": "Screen Brightness", "values": {v: f"{v}%" for v in range(20, 101, 10)}, "range": (20, 100), "default": 100, "group": "SCREEN"},
    {"key": "place_bar", "label": "Place Bar Position", "values": {0: "Top", 1: "Bottom"}, "default": 0, "group": "SCREEN"},
    {"key": "screen_mirror", "label": "USB Screen Mirror", "values": {0: "Off", 1: "On (USB Webcam)"}, "default": 0, "group": "SCREEN"},
    {"key": "mirror_size", "label": "Mirror Resolution", "values": {0: "320 × 240", 1: "640 × 480", 2: "1280 × 720", 3: "1280 × 960 (Sharpest)"}, "default": 3, "group": "SCREEN"},
    {"key": "mirror_fps", "label": "Mirror Frame Rate", "values": {30: "30 fps", 60: "60 fps"}, "default": 30, "group": "SCREEN"},
    # PADS
    {"key": "pad_response", "label": "Pad Response Curve", "values": {0: "Soft", 1: "Medium", 2: "Hard", 3: "Full Level (127)"}, "default": 1, "group": "PADS"},
    {"key": "response_before", "label": "Response Before Full Level", "values": {0: "Soft", 1: "Medium", 2: "Hard"}, "default": 1, "group": "PADS"},
    {"key": "pressure", "label": "Pad Pressure (Aftertouch)", "values": {0: "Off", 1: "On"}, "default": 1, "group": "PADS"},
    {"key": "repeat_pressure", "label": "Note Repeat Velocity", "values": {0: "Strike", 1: "Pressure"}, "default": 0, "group": "PADS"},
    {"key": "pad_lights", "label": "Pad Lights Mode", "values": {0: "Track Colours", 1: "White", 2: "Off"}, "default": 0, "group": "PADS"},
    {"key": "pad_fade", "label": "Pad Light Fade", "values": {0: "60 ms", 1: "100 ms", 2: "150 ms", 3: "250 ms"}, "default": 1, "group": "PADS"},
    {"key": "tap_light", "label": "Tap Tempo Beat Flash", "values": {0: "Off", 1: "On"}, "default": 1, "group": "PADS"},
    # SEQ & CHOP (v0.4.0)
    {"key": "rec_quantize", "label": "Rec Quantize (Shift+Pad10)", "values": {0: "Off", 1: "On (Pattern Q)"}, "default": 1, "group": "SEQ"},
    {"key": "count_in", "label": "Metronome Count-In", "values": {0: "Off", 1: "On (1 Bar)"}, "default": 0, "group": "SEQ"},
    {"key": "click", "label": "Metronome Mode", "values": {0: "Off", 1: "On", 2: "Rec Only"}, "default": 0, "group": "SEQ"},
    {"key": "click_level", "label": "Metronome Level", "values": {v: f"{v}%" for v in range(0, 101, 10)}, "range": (0, 100), "default": 40, "group": "SEQ"},
    {"key": "seq_follow", "label": "Step/Roll Playhead Follow", "values": {0: "Off", 1: "Page", 2: "Step"}, "default": 0, "group": "SEQ"},
    {"key": "double_copies", "label": "Double Seq Behaviour", "values": {0: "Empty", 1: "Copy Notes"}, "default": 1, "group": "SEQ"},
    {"key": "capture_bars", "label": "Capture MIDI Length", "values": {0: "Auto", 1: "1 bar", 2: "2 bars", 4: "4 bars", 8: "8 bars", 16: "16 bars", 32: "32 bars"}, "default": 0, "group": "SEQ"},
    {"key": "capture_quantize", "label": "Capture MIDI Quantize", "values": {0: "As Played", 1: "1/16", 2: "1/8"}, "default": 1, "group": "SEQ"},
    {"key": "slice_play", "label": "Chop TO PADS Playback", "values": {0: "Poly", 1: "Mono (Mute Group)", 2: "Thru (To Region End)"}, "default": 0, "group": "SEQ"},
    {"key": "stems_best", "label": "Stems Quality (B2 BEST)", "values": {0: "Fast (11 kHz · 1 Pass)", 1: "BEST (16 kHz · 2 Passes)"}, "default": 1, "group": "SEQ"},
    {"key": "preview", "label": "Sample Browser Preview", "values": {0: "Off", 1: "On (Auto-Preview)"}, "default": 0, "group": "SEQ"},
    # KNOBS
    {"key": "knob_takeover", "label": "Knobs Takeover", "values": {0: "Pickup", 1: "Scaled", 2: "Instant"}, "default": 1, "group": "KNOBS"},
    {"key": "knob_fx_takeover", "label": "Knob FX Takeover", "values": {0: "Pickup", 1: "Scaled", 2: "Instant"}, "default": 1, "group": "KNOBS"},
    {"key": "fader_takeover", "label": "Fader Takeover", "values": {0: "Pickup", 1: "Scaled", 2: "Instant"}, "default": 0, "group": "KNOBS"},
    # AUDIO
    {"key": "audio_rate", "label": "Audio Sample Rate", "values": {44100: "44.1 kHz", 48000: "48 kHz", 96000: "96 kHz"}, "default": 44100, "group": "AUDIO"},
    {"key": "audio_periods", "label": "Audio Buffer Periods", "values": {2: "256 frames (2×128)", 3: "384 frames (3×128)", 4: "512 frames (4×128)", 6: "768 frames (6×128)", 8: "1024 frames (8×128)"}, "default": 3, "group": "AUDIO"},
    # SAMPLING
    {"key": "input_source", "label": "Sampling Input Source", "values": {0: "Mic", 1: "Rear L+R", 2: "Rear L", 3: "Rear R", 4: "Resample (Mix)", 5: "USB L+R", 6: "USB L", 7: "USB R", 8: "Track"}, "default": 1, "group": "SAMPLING"},
    {"key": "monitor", "label": "Input Monitor", "values": {0: "Off", 1: "Auto (Record Page)", 2: "On"}, "default": 1, "group": "SAMPLING"},
    {"key": "monitor_before_mic", "label": "Monitor Before Mic Auto-Mute", "values": {-1: "Unset (-1)", 0: "Off", 1: "Auto", 2: "On"}, "range": (-1, 2), "default": -1, "group": "SAMPLING"},
    {"key": "threshold", "label": "Record Threshold", "values": {v: ("At Once (-96 dB)" if v == -96 else f"{v} dB") for v in (-96, -60, -48, -40, -30, -24, -18, -12, -6, 0)}, "range": (-96, 0), "default": -30, "group": "SAMPLING"},
    {"key": "rec_length", "label": "Record Length", "values": {0: "Free", 1: "Seq", 2: "1 bar", 3: "2 bars", 5: "4 bars", 9: "8 bars", 17: "16 bars"}, "range": (0, 17), "default": 0, "group": "SAMPLING"},
    {"key": "rec_fx", "label": "Record Knob FX", "values": {0: "Off", 1: "On"}, "default": 0, "group": "SAMPLING"},
    {"key": "rec_gain", "label": "Sampling Input Gain", "values": {v: ("0 dB" if v == 0 else f"{v:+d} dB") for v in (-12, -6, 0, 3, 6, 12, 18, 24)}, "range": (-12, 24), "default": 0, "group": "SAMPLING"},
    {"key": "input_track", "label": "Internal Sampling Track", "values": {i: f"Track {i + 1}" for i in range(16)}, "default": 0, "group": "SAMPLING"},
    {"key": "input_tap", "label": "Internal Track Tap", "values": {0: "Pre-FX (Engine Alone)", 1: "Post-FX (Strip & Chain)"}, "default": 1, "group": "SAMPLING"},
    {"key": "recall_grab", "label": "Audio Recall Grab", "values": {0: "Last Phrase", 1: "First Sound", 2: "Whole 25 s"}, "default": 0, "group": "SAMPLING"},
    {"key": "recall_gap", "label": "Audio Recall Quiet Gap", "values": {0: "0.5 s", 1: "1.0 s", 2: "2.0 s", 3: "4.0 s"}, "default": 1, "group": "SAMPLING"},
    {"key": "recall_trim", "label": "Audio Recall Trim End", "values": {0: "Off", 1: "On"}, "default": 1, "group": "SAMPLING"},
    {"key": "auto_end", "label": "Free Take Auto End", "values": {0: "Off", 1: "Synths & Resample", 2: "All Sources"}, "default": 1, "group": "SAMPLING"},
    {"key": "auto_end_after", "label": "Auto End Silence Time", "values": {0: "0.5 s", 1: "1.0 s", 2: "1.5 s", 3: "3.0 s"}, "default": 2, "group": "SAMPLING"},
    {"key": "silence_db", "label": "Auto End Silence Floor", "values": {-48: "-48 dB", -60: "-60 dB", -72: "-72 dB"}, "default": -60, "group": "SAMPLING"},
    # MIDI
    {"key": "midi_port", "label": "Default MIDI Port", "values": {0: "External (1/8\" Jacks)", 1: "USB (USB-C / Host)"}, "default": 0, "group": "MIDI"},
    {"key": "midi_in_channel", "label": "MIDI In Channel", "values": {0: "All", **{c: f"Ch {c}" for c in range(1, 17)}}, "default": 0, "group": "MIDI"},
    {"key": "midi_out_channel", "label": "MIDI Out Channel", "values": {c: f"Ch {c}" for c in range(1, 17)}, "default": 1, "group": "MIDI"},
    {"key": "pad_midi_in", "label": "MIDI Notes Play Pads", "values": {0: "Off", 1: "On"}, "default": 1, "group": "MIDI"},
    {"key": "pad_midi_out", "label": "Pads Send MIDI Out", "values": {0: "Never", 1: "Always", 2: "Empty Pads Only"}, "default": 0, "group": "MIDI"},
    {"key": "midi_sync_in", "label": "MIDI Sync In", "values": {0: "Off", 1: "MIDI Clock", 2: "MTC"}, "default": 0, "group": "MIDI"},
    {"key": "midi_sync_out", "label": "MIDI Sync Out", "values": {0: "Off", 1: "MIDI Clock", 2: "MTC"}, "default": 0, "group": "MIDI"},
    {"key": "midi_thru", "label": "MIDI Thru", "values": {0: "Off", 1: "On"}, "default": 0, "group": "MIDI"},
    {"key": "program_change", "label": "Program Change Pattern", "values": {0: "Off", 1: "On"}, "default": 0, "group": "MIDI"},
    {"key": "cv_out", "label": "CV Clock Out (SYNC OUT)", "values": {0: "Off", 1: "On"}, "default": 0, "group": "MIDI"},
    {"key": "cv_base", "label": "CV Clock Base", "values": {1: "1", 2: "2 (Volca / PO Base)", **{b: str(b) for b in range(3, 9)}}, "range": (1, 8), "default": 2, "group": "MIDI"},
    {"key": "cv_division", "label": "CV Clock Division", "values": {1: "×1 (2 PPQN w/ Base 2)", 2: "×2", 3: "×3", 4: "×4", 6: "×6", 12: "×12 (24 PPQN)", 24: "×24 (48 PPQN)"}, "range": (1, 24), "default": 1, "group": "MIDI"},
    {"key": "remote_channel", "label": "Remote Control Channel", "values": {0: "Off", **{c: f"Ch {c}" for c in range(1, 17)}}, "default": 0, "group": "MIDI"},
    {"key": "remote_track_cc", "label": "Remote Track Select CC", "values": {0: "Off", **{cc: f"CC {cc}" for cc in (102, 103, 104, 105, 110, 111)}}, "range": (0, 127), "default": 102, "group": "MIDI"},
    {"key": "remote_pattern_cc", "label": "Remote Pattern Select CC", "values": {0: "Off", **{cc: f"CC {cc}" for cc in (102, 103, 104, 105, 110, 111)}}, "range": (0, 127), "default": 103, "group": "MIDI"},
    {"key": "remote_scene_cc", "label": "Remote Scene Select CC", "values": {0: "Off", **{cc: f"CC {cc}" for cc in (102, 103, 104, 105, 110, 111)}}, "range": (0, 127), "default": 104, "group": "MIDI"},
]

MELODEE_PRESETS: Dict[str, Dict[str, int]] = {
    "live_performance": {
        "features": 1, "pad_response": 1, "pressure": 1, "pad_lights": 0,
        "rec_quantize": 1, "slice_play": 1, "stems_best": 0, "preview": 0,
        "knob_takeover": 1, "knob_fx_takeover": 1, "fader_takeover": 0,
        "audio_rate": 44100, "audio_periods": 3, "screen": 90, "screen_mirror": 0,
    },
    "studio_hq": {
        "features": 1, "palette": 0, "pad_response": 1, "pressure": 1,
        "rec_quantize": 1, "slice_play": 1, "stems_best": 1, "preview": 1,
        "knob_takeover": 1, "knob_fx_takeover": 1, "fader_takeover": 0,
        "audio_rate": 48000, "audio_periods": 4, "screen": 100,
    },
    "streaming_mirror": {
        "features": 1, "palette": 0, "font": 0, "place_bar": 0,
        "screen": 100, "screen_mirror": 1, "mirror_size": 3, "mirror_fps": 60,
        "pad_lights": 0, "tap_light": 1,
    },
    "factory_defaults": {
        item["key"]: int(item["default"]) for item in MELODEE_SETTINGS_SCHEMA
    },
}

_MELODEE_PRESERVED_KEYS = ("start", "last", "lessons")


def _scan_melodee_plugins_summary(plugins_root: Path) -> List[Dict[str, str]]:
    """Lista plugins instalados en Melodee/Plugins leyendo metadatos VST3/VST2/CLAP/LV2."""
    if not plugins_root.is_dir():
        return []
    found: List[Dict[str, str]] = []
    for entry in sorted(plugins_root.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            meta = entry / "plugin-meta.xml"
            if meta.is_file():
                pname = entry.name
                pkind = "Plugin"
                try:
                    root_el = ET.parse(meta).getroot()
                    pl = root_el if root_el.tag == "PLUGIN" else root_el.find("PLUGIN")
                    if pl is not None:
                        pname = pl.get("name") or pname
                        inst = pl.get("isInstrument")
                        if inst == "1":
                            pkind = "Instrument"
                        elif inst == "0":
                            pkind = "Effect"
                except Exception:
                    pass
                found.append({"name": pname, "format": "OpenMPC/VST2", "kind": pkind, "folder": entry.name})
                continue
            vst3s = sorted([d for d in entry.rglob("*.vst3") if d.is_dir() and not d.name.startswith(".")])
            if vst3s:
                found.append({"name": vst3s[0].stem, "format": "VST3", "kind": "Plugin", "folder": entry.name})
                continue
            claps = sorted([f for f in entry.rglob("*.clap") if f.is_file() and not f.name.startswith(".")])
            if claps:
                found.append({"name": claps[0].stem, "format": "CLAP", "kind": "Plugin", "folder": entry.name})
                continue
            lv2s = sorted([d for d in entry.rglob("*.lv2") if d.is_dir() and not d.name.startswith(".")])
            if lv2s:
                found.append({"name": lv2s[0].stem, "format": "LV2", "kind": "Plugin", "folder": entry.name})
                continue
            found.append({"name": entry.name, "format": "Folder", "kind": "Plugin", "folder": entry.name})
        elif entry.suffix.lower() in (".so", ".clap"):
            found.append({"name": entry.stem, "format": entry.suffix.lstrip(".").upper(), "kind": "Plugin", "folder": entry.name})
    return found


def detect_mpc_boot_status(source_root: str | Path) -> Dict[str, Any]:
    """Inspecciona en solo lectura qué sistema está activo en `/autorun` y carpetas de Melodee."""
    root_p = Path(source_root)
    autorun_dir = root_p / "autorun"
    melodee_dir = autorun_dir / "melodee"
    melodee_version = ""
    version_file = melodee_dir / "VERSION"
    if version_file.is_file():
        melodee_version = version_file.read_text(encoding="utf-8", errors="ignore").strip()
    melodee_boot = (melodee_dir / "sample-base").is_file() or (melodee_dir / "app").is_file()
    sampqol_boot = (autorun_dir / "mpcqol.so").is_file()

    if melodee_boot and not sampqol_boot:
        active_boot = "melodee"
    elif sampqol_boot and not melodee_boot:
        active_boot = "sampqol"
    elif melodee_boot and sampqol_boot:
        active_boot = "dual_autorun"
    else:
        active_boot = "stock"

    m_root = root_p / "Melodee"
    mldp_files = sorted([p for p in (m_root / "Projects").rglob("*.mldp") if p.is_file() and not p.name.startswith(".")]) if (m_root / "Projects").is_dir() else []
    projects_count = len(mldp_files)
    plugins_list = _scan_melodee_plugins_summary(m_root / "Plugins")
    plugins_count = len(plugins_list)
    crashes_count = sum(1 for p in (m_root / "Crashes").glob("crash-*.txt") if p.is_file()) if (m_root / "Crashes").is_dir() else 0
    cache_bytes = sum(p.stat().st_size for p in (m_root / "Cache").rglob("*") if p.is_file() and not p.name.startswith(".")) if (m_root / "Cache").is_dir() else 0
    mixdowns_count = sum(1 for p in (m_root / "Mixdowns").rglob("*.wav") if p.is_file() and not p.name.startswith(".")) if (m_root / "Mixdowns").is_dir() else 0
    stems_count = sum(1 for p in (m_root / "Stems").rglob("*.wav") if p.is_file() and not p.name.startswith(".")) if (m_root / "Stems").is_dir() else 0
    sysex_count = sum(1 for p in (m_root / "SysEx").rglob("*.syx") if p.is_file() and not p.name.startswith(".")) if (m_root / "SysEx").is_dir() else 0
    banks_count = sum(1 for p in (m_root / "Samples" / "Banks").glob("*.mldb") if p.is_file() and not p.name.startswith(".")) if (m_root / "Samples" / "Banks").is_dir() else 0
    melodee_exp_count = sum(1 for p in (m_root / "Samples" / "Expansions").iterdir() if p.is_dir() and not p.name.startswith(".")) if (m_root / "Samples" / "Expansions").is_dir() else 0

    melodee_projects = [f"/media/sd/{p.relative_to(root_p).as_posix()}" for p in mldp_files[:60]]
    xpj_candidates: List[str] = []
    for cand_dir in (root_p / "MPC-Sample" / "Projects", root_p / "Custom_Kits"):
        if cand_dir.is_dir():
            for xp in sorted(cand_dir.rglob("*.xpj")):
                if not xp.name.startswith(".") and "_[ProjectData]" not in xp.parts:
                    xpj_candidates.append(f"/media/sd/{xp.relative_to(root_p).as_posix()}")
                    if len(xpj_candidates) >= 40:
                        break

    return {
        "active_boot": active_boot,
        "melodee_detected": melodee_boot,
        "melodee_version": melodee_version,
        "sampqol_detected": sampqol_boot,
        "melodee_dir_exists": m_root.is_dir(),
        "projects_count": projects_count,
        "plugins_count": plugins_count,
        "plugins_list": plugins_list,
        "crashes_count": crashes_count,
        "cache_mb": round(cache_bytes / (1024 * 1024), 2),
        "mixdowns_count": mixdowns_count,
        "stems_count": stems_count,
        "sysex_count": sysex_count,
        "banks_count": banks_count,
        "melodee_expansions_count": melodee_exp_count,
        "melodee_projects": melodee_projects,
        "xpj_projects": xpj_candidates,
    }


def _validate_melodee_setting(item: Dict[str, Any], raw_value: Any) -> int:
    key = item["key"]
    if isinstance(raw_value, bool):
        allowed_desc = f"{item['range'][0]}..{item['range'][1]}" if "range" in item else str(list(item["values"].keys()))
        raise ValueError(f"Valor inválido {raw_value} para {key} (permitidos: {allowed_desc})")
    iv = int(raw_value)
    if "range" in item:
        lo, hi = item["range"]
        if iv < lo or iv > hi:
            raise ValueError(f"Valor inválido {iv} para {key} (permitidos: {lo}..{hi})")
        return iv
    allowed = item["values"]
    if iv not in allowed:
        raise ValueError(f"Valor inválido {iv} para {key} (permitidos: {list(allowed.keys())})")
    return iv


def read_melodee_settings(source_root: str | Path) -> Dict[str, Any]:
    """Lee `Melodee/settings` y el estado del bootloader/ecosistema Melodee v0.4.0 (solo lectura)."""
    root_p = Path(source_root)
    melodee_dir = root_p / "Melodee"
    conf_path = melodee_dir / "settings"
    raw_lines: Dict[str, str] = {}
    if conf_path.is_file():
        for raw_line in conf_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            raw_lines[k.strip()] = v.strip()

    settings_view = []
    raw_int_values: Dict[str, int] = {}
    for item in MELODEE_SETTINGS_SCHEMA:
        key = item["key"]
        raw_val = raw_lines.get(key)
        if raw_val is None:
            int_val = int(item["default"])
        else:
            try:
                int_val = int(raw_val)
            except ValueError:
                int_val = int(item["default"])
        choices = dict(item["values"])
        if int_val not in choices and "range" in item:
            lo, hi = item["range"]
            if lo <= int_val <= hi:
                choices[int_val] = str(int_val)
        raw_int_values[key] = int_val
        settings_view.append({
            "key": key,
            "label": item["label"],
            "group": item["group"],
            "value": int_val,
            "value_label": choices.get(int_val, str(int_val)),
            "choices": choices,
            "default": item["default"],
        })

    boot = detect_mpc_boot_status(root_p)
    return {
        "success": True,
        **boot,
        "conf_exists": conf_path.is_file(),
        "conf_path": str(conf_path),
        "backup_exists": (melodee_dir / "settings.bak-beatos").is_file(),
        "start_project": raw_lines.get("start", ""),
        "last_project": raw_lines.get("last", ""),
        "raw_values": raw_int_values,
        "schema": settings_view,
        "presets": list(MELODEE_PRESETS.keys()),
        "preset_map": MELODEE_PRESETS,
    }


def _translate_sampqol_to_melodee(qol_raw: Dict[str, str]) -> Dict[str, int]:
    """Convierte ajustes equivalentes de SampQOL-OS (/mpcqol.conf) a Melodee/settings."""
    mapped: Dict[str, int] = {}
    if "screenlevel" in qol_raw:
        try:
            lvl = max(1, min(6, int(qol_raw["screenlevel"])))
            mapped["screen"] = {1: 30, 2: 50, 3: 60, 4: 70, 5: 90, 6: 100}[lvl]
        except ValueError:
            pass
    if "padlevel" in qol_raw:
        try:
            plvl = max(1, min(6, int(qol_raw["padlevel"])))
            mapped["pad_response"] = 0 if plvl >= 5 else (1 if plvl >= 3 else 2)
        except ValueError:
            pass
    if "monitor" in qol_raw:
        try:
            mon = int(qol_raw["monitor"])
            mapped["monitor"] = 2 if mon == 1 else (1 if mon == 2 else 0)
        except ValueError:
            pass
    if "follow" in qol_raw:
        try:
            mapped["seq_follow"] = max(0, min(2, int(qol_raw["follow"])))
        except ValueError:
            pass
    if "rearusb" in qol_raw:
        try:
            mapped["input_source"] = 5 if int(qol_raw["rearusb"]) == 1 else 1
        except ValueError:
            pass
    if "resamplekfx" in qol_raw or "resamplepfx" in qol_raw:
        try:
            rk = int(qol_raw.get("resamplekfx", 0))
            rp = int(qol_raw.get("resamplepfx", 0))
            mapped["rec_fx"] = 1 if (rk or rp) else 0
        except ValueError:
            pass
    return mapped


def _translate_melodee_to_sampqol(md_raw: Dict[str, int]) -> Dict[str, int]:
    """Convierte ajustes equivalentes de Melodee/settings a SampQOL-OS (/mpcqol.conf)."""
    mapped: Dict[str, int] = {}
    if "screen" in md_raw:
        pct = max(20, min(100, int(md_raw["screen"])))
        mapped["screenlevel"] = 1 if pct <= 35 else (2 if pct <= 55 else (3 if pct <= 65 else (4 if pct <= 75 else (5 if pct <= 95 else 6))))
    if "pad_response" in md_raw:
        pr = int(md_raw["pad_response"])
        if pr == 0:
            mapped["padlevel"] = 5
        elif pr == 1:
            mapped["padlevel"] = 3
        elif pr == 2:
            mapped["padlevel"] = 1
    if "monitor" in md_raw:
        mval = int(md_raw["monitor"])
        mapped["monitor"] = 1 if mval == 2 else (2 if mval == 1 else 0)
    if "seq_follow" in md_raw:
        mapped["follow"] = max(0, min(2, int(md_raw["seq_follow"])))
    if "input_source" in md_raw:
        src = int(md_raw["input_source"])
        if src in (1, 2, 3):
            mapped["rearusb"] = 0
        elif src in (5, 6, 7):
            mapped["rearusb"] = 1
    if "rec_fx" in md_raw:
        rfx = 1 if int(md_raw["rec_fx"]) else 0
        mapped["resamplekfx"] = rfx
        mapped["resamplepfx"] = rfx
    return mapped


def ensure_melodee_folder_tree(source_root: str | Path) -> List[str]:
    """Asegura la jerarquía oficial completa de /Melodee/ sin alterar archivos ni /autorun."""
    root_p = Path(source_root)
    subdirs = [
        "Melodee/Projects",
        "Melodee/Samples/Recorded",
        "Melodee/Samples/Edits",
        "Melodee/Samples/Banks",
        "Melodee/Samples/Expansions",
        "Melodee/Samples/Keygroups",
        "Melodee/Samples/Stems",
        "Melodee/Progressions",
        "Melodee/Mixdowns",
        "Melodee/Stems",
        "Melodee/MIDI",
        "Melodee/SysEx",
        "Melodee/Sounds",
        "Melodee/Plugins",
        "Melodee/Plugin Data/Neural Amp Modeler/Models",
        "Melodee/Plugin Data/Neural Amp Modeler/IRs",
    ]
    created: List[str] = []
    for rel in subdirs:
        p = root_p / rel
        if not p.is_dir():
            p.mkdir(parents=True, exist_ok=True)
            created.append(rel)
    return created


def update_melodee_settings(
    source_root: str | Path,
    updates: Optional[Dict[str, Any]] = None,
    preset: Optional[str] = None,
    start_project: Optional[str] = None,
    action: Optional[str] = None,
) -> Dict[str, Any]:
    """Actualiza `Melodee/settings` con backup `.bak-beatos`, gestiona `start=` y sincronización dual con SampQOL-OS."""
    root_p = Path(source_root)
    melodee_dir = root_p / "Melodee"
    melodee_dir.mkdir(parents=True, exist_ok=True)
    conf_path = melodee_dir / "settings"
    backup_path = melodee_dir / "settings.bak-beatos"

    action_msg = ""
    action_clean = str(action).strip().lower() if action else ""
    if action_clean == "init_melodee_tree":
        created = ensure_melodee_folder_tree(root_p)
        res = read_melodee_settings(root_p)
        res["action"] = action_clean
        res["created_folders"] = created
        res["message"] = f"Estructura Melodee verificada ({len(created)} carpetas creadas)."
        return res
    elif action_clean == "clear_cache":
        cache_dir = melodee_dir / "Cache"
        removed = 0
        if cache_dir.is_dir():
            for cf in cache_dir.iterdir():
                if cf.is_file() and cf.suffix.lower() in (".f32", ".wav") and not cf.name.startswith("."):
                    cf.unlink(missing_ok=True)
                    removed += 1
        res = read_melodee_settings(root_p)
        res["action"] = action_clean
        res["removed_cache_files"] = removed
        res["message"] = f"Caché temporal de Melodee limpiada ({removed} archivos)."
        return res

    if conf_path.is_file() and not backup_path.is_file():
        shutil.copy2(conf_path, backup_path)

    valid_keys = {item["key"]: item for item in MELODEE_SETTINGS_SCHEMA}
    pending: Dict[str, int] = {}
    if action_clean == "sync_from_sampqol":
        qol = read_mpcqol_conf(root_p)
        pending.update(_translate_sampqol_to_melodee(qol.get("raw_values", {})))
        action_msg = f"Equivalencias importadas desde SampQOL-OS ({len(pending)} claves)."
    if preset:
        preset_key = str(preset).strip().lower()
        if preset_key not in MELODEE_PRESETS:
            raise ValueError(f"Preset Melodee desconocido: {preset}")
        pending.update(MELODEE_PRESETS[preset_key])
    if updates is not None and not isinstance(updates, dict):
        raise ValueError("El parámetro 'settings' debe ser un objeto JSON")
    if isinstance(updates, dict):
        for k, v in updates.items():
            if k not in valid_keys:
                continue
            pending[k] = _validate_melodee_setting(valid_keys[k], v)

    if "knob_takeover" in pending:
        pending["pickup"] = 1 if pending["knob_takeover"] != 2 else 0  # compatibilidad builds previos

    normalized_start: Optional[str] = None
    if start_project is not None:
        sp = str(start_project).strip().replace("\r", "").replace("\n", "")
        if sp and not (sp.endswith(".mldp") or sp.endswith(".xpj")):
            raise ValueError("El proyecto de arranque 'start_project' debe terminar en .mldp o .xpj")
        normalized_start = sp

    existing_lines = (
        conf_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if conf_path.is_file()
        else []
    )
    out_lines: List[str] = []
    seen_keys: set[str] = set()
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out_lines.append(raw_line)
            continue
        k, _ = stripped.split("=", 1)
        k_clean = k.strip()
        if k_clean == "start" and normalized_start is not None:
            if normalized_start:
                out_lines.append(f"start={normalized_start}")
            seen_keys.add("start")
        elif k_clean in _MELODEE_PRESERVED_KEYS or k_clean.startswith("favourites"):
            out_lines.append(raw_line)
            seen_keys.add(k_clean)
        elif k_clean in pending:
            out_lines.append(f"{k_clean}={pending[k_clean]}")
            seen_keys.add(k_clean)
        else:
            out_lines.append(raw_line)

    if normalized_start and "start" not in seen_keys:
        out_lines.insert(0, f"start={normalized_start}")
        seen_keys.add("start")

    for k_clean, iv in pending.items():
        if k_clean not in seen_keys:
            out_lines.append(f"{k_clean}={iv}")

    tmp_path = melodee_dir / ".settings.tmp"
    tmp_path.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    os.replace(tmp_path, conf_path)

    synced_qol_keys: List[str] = []
    if action_clean == "sync_to_sampqol":
        cur_md = read_melodee_settings(root_p).get("raw_values", {})
        qol_updates = _translate_melodee_to_sampqol(cur_md)
        if qol_updates:
            qol_res = update_mpcqol_conf(root_p, updates=qol_updates)
            synced_qol_keys = qol_res.get("updated_keys", [])
        action_msg = f"Equivalencias aplicadas a SampQOL-OS ({len(synced_qol_keys)} claves en mpcqol.conf)."

    res = read_melodee_settings(root_p)
    res["updated_keys"] = sorted(pending.keys())
    res["applied_preset"] = preset or ""
    if action_clean:
        res["action"] = action_clean
        res["message"] = action_msg
        if synced_qol_keys:
            res["synced_sampqol_keys"] = synced_qol_keys
    return res


_MPC_ROLE_PAD_COLORS: Dict[str, int] = {
    "KICK": 0xE62E2E,          # Rojo cálido
    "SNARE": 0xE6B800,         # Ámbar / Dorado
    "CLAP": 0xE6B800,
    "RIM": 0xFF8C00,
    "TOM": 0xFF6B35,
    "HIHAT": 0x00B8D4,         # Cian
    "CYMBAL": 0x00B8D4,
    "PERCUSSION": 0x26C6DA,
    "BASS_808": 0x9B30FF,      # Violeta subgrave
    "BASS": 0x9B30FF,
    "MELODIC_LOOP": 0x16C65A,  # Verde esmeralda
    "KEYS_SYNTH": 0x16C65A,
    "CHOP": 0x16C65A,
    "LOOP": 0x16C65A,
    "VOCAL": 0xE040FB,         # Magenta
    "FX": 0xFF4081,
}


def _pad_color_for_role(sound_type: str) -> int:
    """Devuelve color RGB 24-bit entero compatible con AC50/SampQOL/Melodee según rol acústico."""
    st = str(sound_type or "").strip().upper()
    if st in _MPC_ROLE_PAD_COLORS:
        return _MPC_ROLE_PAD_COLORS[st]
    for key, color in _MPC_ROLE_PAD_COLORS.items():
        if key in st:
            return color
    return 0x4C8DFF


def _apply_program_pads_colors(program_pads: Dict[str, Any], pads_map: Dict[Any, Any]) -> None:
    """Rellena programPads.Universal=False, Type=5 y colores por pad 0..127 sin romper el esquema AC50."""
    if not isinstance(program_pads, dict) or not isinstance(pads_map, dict):
        return
    pads_dict = program_pads.get("pads")
    if not isinstance(pads_dict, dict):
        pads_dict = {f"value{i}": 0 for i in range(128)}
        program_pads["pads"] = pads_dict
    program_pads["Universal"] = {"value0": False}
    program_pads["Type"] = {"value0": 5}
    program_pads.setdefault("universalPad", 0x229ED0)
    for i in range(128):
        p_info = pads_map.get(i + 1) or pads_map.get(str(i + 1)) or {}
        has_sample = bool(
            isinstance(p_info, dict)
            and (p_info.get("sample_file") or p_info.get("sample_name") or p_info.get("sample_path") or p_info.get("source_path"))
        )
        if not has_sample:
            pads_dict[f"value{i}"] = 0
            continue
        custom_col = p_info.get("pad_color")
        if isinstance(custom_col, int) and 0 <= custom_col <= 0xFFFFFF:
            pads_dict[f"value{i}"] = custom_col
        else:
            st = p_info.get("sound_type") or detect_sound_type(
                str(p_info.get("sample_name") or p_info.get("sample_file") or "")
            )
            pads_dict[f"value{i}"] = _pad_color_for_role(st)


def bjorklund_steps(pulses: int, steps: int, rotation: int = 0) -> List[bool]:
    """Algoritmo exacto de Bjorklund E(k,n) para ritmos euclidianos (mpc-sample-kit)."""
    if not isinstance(steps, int) or steps <= 0:
        raise ValueError("Parámetro steps debe ser un entero positivo.")
    p = max(0, min(int(pulses), steps))
    if p == 0:
        return [False] * steps
    if p == steps:
        return [True] * steps
    a: List[List[bool]] = [[True] for _ in range(p)]
    b: List[List[bool]] = [[False] for _ in range(steps - p)]
    while len(b) > 1:
        m = min(len(a), len(b))
        merged = [a[i] + b[i] for i in range(m)]
        rem = a[m:] if len(a) > m else b[m:]
        a = merged
        b = rem
    seq = [cell for grp in (a + b) for cell in grp]
    if seq and rotation:
        rot = rotation % len(seq)
        seq = seq[rot:] + seq[:rot]
    return seq


def generate_euclidean_mpc_pattern(
    style: str = "boombap",
    bpm: Optional[float] = None,
    bars: int = 2,
    swing: Optional[float] = None,
    swing_unit: Optional[int] = None,
    humanize_ms: Optional[float] = None,
    limb_spread: float = 0.25,
    conformity: float = 0.80,
    seed: int = 1337,
) -> Dict[str, Any]:
    """Genera patrones MIDI algorítmicos para MPC Sample (Bjorklund + swing time-warp + limbSpread)."""
    import random as _rnd

    bars_i = int(bars)
    if bars_i < 1 or bars_i > 16:
        raise ValueError("Número de compases fuera de rango (1–16).")

    presets: Dict[str, Dict[str, Any]] = {
        "boombap": {"bpm": 90.0, "swing": 0.18, "swing_unit": 1, "hum": 6.0, "meter": "4/4", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 4, "steps": 16, "rot": 0, "accent": 116, "hit": 94},
            {"role": "SNARE", "pad": 2, "note": 38, "pulses": 2, "steps": 16, "rot": 12, "accent": 112, "hit": 92},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 8, "steps": 16, "rot": 0, "accent": 96, "hit": 74},
            {"role": "PERCUSSION", "pad": 5, "note": 40, "pulses": 3, "steps": 16, "rot": 5, "accent": 82, "hit": 58},
        ]},
        "lofi_hiphop": {"bpm": 80.0, "swing": 0.22, "swing_unit": 1, "hum": 8.5, "meter": "4/4", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 3, "steps": 16, "rot": 0, "accent": 108, "hit": 86},
            {"role": "SNARE", "pad": 2, "note": 38, "pulses": 2, "steps": 16, "rot": 12, "accent": 104, "hit": 84},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 7, "steps": 16, "rot": 0, "accent": 84, "hit": 62},
        ]},
        "jazz_hop": {"bpm": 88.0, "swing": 0.33, "swing_unit": 2, "hum": 7.5, "meter": "4/4", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 4, "steps": 16, "rot": 0, "accent": 106, "hit": 84},
            {"role": "SNARE", "pad": 2, "note": 38, "pulses": 3, "steps": 16, "rot": 12, "accent": 98, "hit": 64},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 10, "steps": 16, "rot": 0, "accent": 92, "hit": 68},
        ]},
        "oldies": {"bpm": 74.0, "swing": 0.33, "swing_unit": 2, "hum": 6.5, "meter": "12/8", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 2, "steps": 12, "rot": 0, "accent": 104, "hit": 86},
            {"role": "SNARE", "pad": 2, "note": 38, "pulses": 2, "steps": 12, "rot": 9, "accent": 102, "hit": 80},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 12, "steps": 12, "rot": 0, "accent": 88, "hit": 56},
        ]},
        "bolero": {"bpm": 82.0, "swing": 0.14, "swing_unit": 2, "hum": 7.0, "meter": "4/4", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 3, "steps": 16, "rot": 0, "accent": 100, "hit": 82},
            {"role": "PERCUSSION", "pad": 5, "note": 40, "pulses": 5, "steps": 16, "rot": 0, "accent": 94, "hit": 70},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 8, "steps": 16, "rot": 0, "accent": 84, "hit": 60},
        ]},
        "drill": {"bpm": 142.0, "swing": 0.08, "swing_unit": 1, "hum": 3.5, "meter": "4/4", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 3, "steps": 16, "rot": 0, "accent": 122, "hit": 102},
            {"role": "SNARE", "pad": 2, "note": 38, "pulses": 2, "steps": 16, "rot": 10, "accent": 118, "hit": 98},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 9, "steps": 16, "rot": 0, "accent": 100, "hit": 72},
        ]},
        "trap": {"bpm": 140.0, "swing": 0.06, "swing_unit": 1, "hum": 3.0, "meter": "4/4", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 4, "steps": 16, "rot": 0, "accent": 120, "hit": 100},
            {"role": "SNARE", "pad": 2, "note": 38, "pulses": 2, "steps": 16, "rot": 8, "accent": 116, "hit": 96},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 11, "steps": 16, "rot": 0, "accent": 96, "hit": 68},
        ]},
        "house": {"bpm": 126.0, "swing": 0.16, "swing_unit": 1, "hum": 4.0, "meter": "4/4", "voices": [
            {"role": "KICK", "pad": 1, "note": 36, "pulses": 4, "steps": 16, "rot": 0, "accent": 118, "hit": 108},
            {"role": "CLAP", "pad": 2, "note": 38, "pulses": 2, "steps": 16, "rot": 12, "accent": 112, "hit": 98},
            {"role": "HIHAT", "pad": 3, "note": 42, "pulses": 4, "steps": 16, "rot": 14, "accent": 102, "hit": 84},
        ]},
    }
    st_clean = str(style or "boombap").strip().lower().replace("-", "_").replace(" ", "_")
    spec = presets.get(st_clean) or presets["boombap"]
    eff_bpm = max(40.0, min(260.0, float(bpm if bpm is not None else spec["bpm"])))
    eff_swing = max(0.0, min(0.5, float(swing if swing is not None else spec["swing"])))
    eff_unit = int(swing_unit if swing_unit in (1, 2) else spec["swing_unit"])
    eff_hum = max(0.0, min(25.0, float(humanize_ms if humanize_ms is not None else spec["hum"])))
    eff_spread = max(0.0, min(1.0, float(limb_spread)))
    eff_conf = max(0.0, min(1.0, float(conformity)))
    rng_gen = _rnd.Random(int(seed))

    steps_per_bar = spec["voices"][0]["steps"]
    total_steps = steps_per_bar * bars_i
    step_ms = (60000.0 / eff_bpm) * (4.0 / steps_per_bar)

    def _metric_weight(idx: int) -> float:
        pos = idx % steps_per_bar
        if pos == 0:
            return 1.0
        lvl = 0
        v = pos
        while v % 2 == 0:
            lvl += 1
            v //= 2
        max_lvl = math.log2(max(2, steps_per_bar))
        return 0.35 + 0.55 * (lvl / max_lvl)

    shared_step_jitter = [(rng_gen.uniform(-1.0, 1.0) * eff_hum * (1.0 - eff_spread)) for _ in range(total_steps)]
    tracks_out: List[Dict[str, Any]] = []
    midi_events: List[Dict[str, Any]] = []

    for v in spec["voices"]:
        base_bar = bjorklund_steps(v["pulses"], steps_per_bar, v["rot"])
        bar_chars = []
        velocities: List[int] = []
        for s_idx in range(total_steps):
            on = base_bar[s_idx % steps_per_bar]
            if not on:
                velocities.append(0)
                if s_idx < steps_per_bar:
                    bar_chars.append(".")
                continue
            mw = _metric_weight(s_idx)
            roll = rng_gen.random()
            if mw < 1.0 and roll >= eff_conf:
                mw = max(0.0, min(1.0, 0.45 + (1.0 - mw) * 0.75))
            raw_vel = v["accent"] if mw >= 0.72 else v["hit"]
            vel = max(1, min(127, int(round(raw_vel * (0.55 + 0.45 * mw)))))
            velocities.append(vel)
            if s_idx < steps_per_bar:
                bar_chars.append("x" if vel >= 100 else ("o" if vel >= 72 else "s"))

            # Swing time-warp según swingUnit (1 = 16ths, 2 = 8ths)
            pair_size = 2 * eff_unit
            in_pair = s_idx % pair_size
            pair_start = (s_idx - in_pair) * step_ms
            if in_pair < eff_unit:
                warped_ms = pair_start + in_pair * step_ms * (1.0 + eff_swing)
            else:
                warped_ms = pair_start + eff_unit * step_ms * (1.0 + eff_swing) + (in_pair - eff_unit) * step_ms * (1.0 - eff_swing)

            limb_off = rng_gen.uniform(-1.0, 1.0) * eff_hum * eff_spread
            at_ms = max(0.0, round(warped_ms + shared_step_jitter[s_idx] + limb_off, 2))
            midi_events.append({
                "bar": (s_idx // steps_per_bar) + 1,
                "step": (s_idx % steps_per_bar) + 1,
                "pad": v["pad"],
                "role": v["role"],
                "channel": 1,
                "midi_note": v["note"],
                "velocity": vel,
                "time_ms": at_ms,
            })

        tracks_out.append({
            "role": v["role"],
            "pad": v["pad"],
            "midi_note": v["note"],
            "channel": 1,
            "euclidean": f"E({v['pulses']},{steps_per_bar})",
            "pattern_1bar": "".join(bar_chars),
            "velocities": velocities,
        })

    midi_events.sort(key=lambda ev: (ev["time_ms"], ev["midi_note"]))
    return {
        "success": True,
        "style": st_clean,
        "bpm": round(eff_bpm, 2),
        "meter": spec["meter"],
        "bars": bars_i,
        "steps_per_bar": steps_per_bar,
        "swing": round(eff_swing, 3),
        "swing_unit": eff_unit,
        "humanize_ms": round(eff_hum, 2),
        "limb_spread": round(eff_spread, 3),
        "conformity": round(eff_conf, 3),
        "tracks": tracks_out,
        "midi_events_count": len(midi_events),
        "midi_events": midi_events,
        "hardware_notes": [
            "USB-MIDI en MPC Sample: activar SHIFT + PAD 8 (MIDI CONFIG) -> MIDI Port -> USB.",
            "Filtrar Soft-Thru Echo en listeners USB-MIDI para evitar bucles de retorno.",
            "Exclusividad MIDI vs Disk Mode: SHIFT + PAD 16 desconecta endpoints MIDI hasta expulsar la SD.",
        ],
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
