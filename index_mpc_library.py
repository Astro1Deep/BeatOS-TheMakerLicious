#!/usr/bin/env python3
"""
Akai MPC Sample Universal Indexer & Database Generator
Motor portátil y universal de indexación de audio y proyectos MPC para la comunidad.
No requiere dependencias externas (usa exclusivamente la biblioteca estándar de Python 3).

Uso:
    python3 index_mpc_library.py
    python3 index_mpc_library.py --path "/Volumes/MiTarjetaMPC" --output "./SQLITE_DATABASE"
"""

from pathlib import Path
import os
import sys
sys.dont_write_bytecode = True
from beatos_paths import CATALOG_REL, database_path, data_dir as library_data_dir, write_catalog
from beatos_i18n import cli_failure, translate_text
import sqlite3
import json
import csv
import re
import gzip
import math
import struct
import wave
import array
import argparse
import contextlib
import html
import tempfile
from datetime import datetime
from xml.etree import ElementTree as ET
from collections import defaultdict

# ==============================================================================
# TAXONOMÍA Y REGLAS DE FORMAS DE SONIDO Y GÉNEROS UNIVERSALES
# ==============================================================================

SOUND_RULES = [
    ("KICK", ["kick", "kik", "bd", "bassdrum", "bass drum", "bombo", "sub kick", "acoustic kick", "808 kick"]),
    ("SNARE", ["snare", "snr", "sd", "rimshot", "cross stick", "sidestick", "caja", "tarola", "snare roll", "acoustic snare"]),
    ("CLAP", ["clap", "clp", "snap", "finger snap", "palma", "palmas", "handclap"]),
    ("HIHAT", ["hihat", "hi-hat", "hat", "hh", "openhh", "closedhh", "open hat", "closed hat", "open-hat", "closed-hat", "oh", "ch", "pedal hat"]),
    ("CYMBAL", ["crash", "ride", "cymbal", "splash", "china", "gong", "cymb"]),
    ("PERCUSSION", ["perc", "prc", "conga", "bongo", "cowbell", "woodblock", "foley", "tom", "organic", "agogo", "timbales", "clave", "claves", "cabasa", "triangle", "cajon", "djembe", "tabla", "guiro", "cuica", "chimes", "maraca", "shaker", "tambourine", "tamb", "rim"]),
    ("BASS_808", ["808", "sub", "bass", "subbass", "reese", "synthbass", "synth bass", "electric bass", "upright bass", "slap bass", "bassline", "sub-bass"]),
    ("KEYS_SYNTH", ["piano", "rhodes", "wurli", "wurlitzer", "clav", "clavinet", "synth", "lead", "pluck", "organ", "brass", "horn", "trumpet", "trombone", "sax", "strings", "violin", "cello", "chord", "stab", "keys", "pad", "arp", "music box", "guitar", "flute", "mallet", "bell"]),
    ("MELODIC_LOOP", ["melody", "arp loop", "keyslp", "voxlp", "synth loop", "guitar loop", "riff", "stem", "sample chop", "chops", "loop", "acoustic guitar", "electric guitar", "lick"]),
    ("DRUM_LOOP", ["break", "drum loop", "drumloop", "breaks", "breakbeat", "amen", "groove", "top loop", "perc loop", "drum track", "beat"]),
    ("VOCAL", ["vocal", "vox", "acapella", "chant", "adlib", "voices", "speech", "phrase", "acap", "singing", "spoken word", "vocal chop"]),
    ("FX", ["fx", "sfx", "riser", "sweep", "downlifter", "impact", "noise", "texture", "vinyl", "crackle", "tape", "space echo", "echo", "transition", "laser", "sub drop", "reverse", "whoosh"])
]

CAMELOT_MAP = {
    "B": "1B", "G#m": "1A", "Abm": "1A",
    "F#": "2B", "Gb": "2B", "D#m": "2A", "Ebm": "2A",
    "Db": "3B", "C#": "3B", "Bbm": "3A", "A#m": "3A",
    "Ab": "4B", "G#": "4B", "Fm": "4A",
    "Eb": "5B", "D#": "5B", "Cm": "5A",
    "Bb": "6B", "A#": "6B", "Gm": "6A",
    "F": "7B", "Dm": "7A",
    "C": "8B", "Am": "8A",
    "G": "9B", "Em": "9A",
    "D": "10B", "Bm": "10A",
    "A": "11B", "F#m": "11A", "Gbm": "11A",
    "E": "12B", "C#m": "12A", "Dbm": "12A"
}

BPM_REGEXES = [
    r'(\d{2,3})\s*(?:bpm|BPM)',
    r'(?:bpm|BPM)\s*(\d{2,3})',
    r'\[(\d{2,3})\]',
    r'[\s_\-](\d{2,3})[\s_\-]',
    r'([A-Ga-g][#b]?(?:m|maj|min|Maj|Min)?)(\d{2,3})'
]

def _sound_text(value):
    value = re.sub(r'([a-z])([A-Z])', r'\1 \2', value)
    return re.sub(r'[_\-]+', ' ', value).lower()


def _has_keyword(text, keyword):
    keyword = _sound_text(keyword)
    return bool(re.search(r'(?<![a-z])' + re.escape(keyword) + r'(?:s)?(?![a-z])', text))


def classify_sound_type(filename, parent_dir=""):
    # A filename outranks folders; broad collection/genre names are not instruments.
    def identify(value):
        text = _sound_text(value)
        loop = any(_has_keyword(text, k) for k in ('loop', 'lp', 'drumloop', 'keyslp', 'voxlp', 'breakbeat', 'break', 'breaks'))
        if _has_keyword(text, 'stem'):
            return 'STEM'
        if any(_has_keyword(text, k) for k in ('roll', 'fill')):
            return 'ROLL_FILL'
        for code, keywords in SOUND_RULES:
            if code in {'MELODIC_LOOP', 'DRUM_LOOP'}:
                continue
            if any(_has_keyword(text, kw) for kw in keywords):
                if loop and code in {'KICK','SNARE','CLAP','HIHAT','CYMBAL','PERCUSSION'}:
                    return 'DRUM_LOOP'
                if loop and code in {'BASS_808','KEYS_SYNTH'}:
                    return 'MELODIC_LOOP'
                return code
        if loop and any(_has_keyword(text, k) for k in ('drum', 'drumloop', 'break', 'breakbeat', 'top', 'amen')):
            return 'DRUM_LOOP'
        if loop and any(_has_keyword(text, k) for k in ('melody', 'melodic', 'music', 'riff')):
            return 'MELODIC_LOOP'
        return None

    found = identify(Path(filename).stem)
    if found:
        return found
    for part in reversed(Path(parent_dir).parts):
        text = _sound_text(part)
        # Only specific instrument folders; never infer from an entire ancestor path.
        exact = [(code, kw) for code, kws in SOUND_RULES for kw in kws
                 if text.strip(' 0123456789') in { _sound_text(kw), _sound_text(kw) + 's' }]
        if exact:
            return identify(part) or exact[0][0]
    return 'UNKNOWN'


def _probe_wav_health(fp):
    """Fast seek-only RIFF/WAV header audit (~0.05ms/file): returns (health, sr, ch, bps, has_slices, duration_sec)."""
    try:
        sz = os.path.getsize(fp)
        if sz < 44:
            return ('TRUNCATED', 0, 0, 0, 0, 0.0)
        with open(fp, 'rb') as fh:
            head = fh.read(12)
            if len(head) < 12:
                return ('TRUNCATED', 0, 0, 0, 0, 0.0)
            if head[:4] == b'FORM' and head[8:12] in (b'AIFF', b'AIFC'):
                return ('AIFF_IN_WAV', 0, 0, 0, 0, 0.0)
            if head[:4] != b'RIFF' or head[8:12] != b'WAVE':
                return ('NON_RIFF', 0, 0, 0, 0, 0.0)
            pos = 12
            sr = ch = bps = block_align = 0
            data_sz = 0
            has_fmt = has_data = False
            has_slices = 0
            odd_atem = False
            overflow = False
            while pos + 8 <= sz:
                fh.seek(pos)
                chdr = fh.read(8)
                if len(chdr) < 8:
                    break
                cid = chdr[:4]
                csz = struct.unpack('<I', chdr[4:8])[0]
                if pos + 8 + csz > sz:
                    overflow = True
                    break
                if cid == b'fmt ' and csz >= 16:
                    has_fmt = True
                    fb = fh.read(16)
                    if len(fb) == 16:
                        _af, ch, sr, _br, block_align, bps = struct.unpack('<HHIIHH', fb)
                elif cid == b'data':
                    has_data = True
                    data_sz = csz
                elif cid == b'atem':
                    has_slices = 1
                    if csz & 1:
                        odd_atem = True
                elif cid == b'slic':
                    has_slices = 1
                pos += 8 + csz + (csz & 1)
            dur = (data_sz / float(block_align * sr)) if (block_align and sr and data_sz) else 0.0
            if not has_fmt or not has_data:
                return ('MISSING_CHUNKS', sr, ch, bps, has_slices, dur)
            if odd_atem:
                return ('ODD_ATEM', sr, ch, bps, has_slices, dur)
            if overflow:
                return ('CHUNK_OVERFLOW', sr, ch, bps, has_slices, dur)
            return ('OK', sr, ch, bps, has_slices, dur)
    except OSError:
        return ('IO_ERROR', 0, 0, 0, 0, 0.0)


def classify_sample_format(filename, sound_type, parent_dir="", duration_sec=0.0):
    text = _sound_text(Path(filename).stem + ' ' + str(parent_dir).replace('/', ' '))
    if _has_keyword(text, 'stem'):
        return 'STEM'
    if any(_has_keyword(text, k) for k in ('roll', 'fill')):
        return 'ROLL_FILL'
    if '[previews]' in str(parent_dir).lower() or filename.lower().endswith('.xpm.wav'):
        return 'PREVIEW'
    if sound_type in {'DRUM_LOOP', 'MELODIC_LOOP'} or _has_keyword(text, 'loop') or _has_keyword(text, 'lp') or _has_keyword(text, 'breakbeat') or _has_keyword(text, 'breaks'):
        return 'LOOP'
    if 'one shot' in text or 'oneshot' in text or 'one_shot' in text or sound_type in {'KICK', 'SNARE', 'CLAP', 'HIHAT', 'CYMBAL', 'PERCUSSION'}:
        return 'ONE_SHOT'
    if duration_sec > 0.0:
        if duration_sec >= 2.4 and sound_type in {'KEYS_SYNTH', 'VOCAL', 'BASS_808', 'UNKNOWN', 'FX'}:
            return 'LOOP'
        if duration_sec <= 1.8:
            return 'ONE_SHOT'
    if sound_type in {'BASS_808', 'FX', 'VOCAL', 'KEYS_SYNTH'}:
        return 'ONE_SHOT'
    return 'UNSPECIFIED'


def _is_real_xpm_file(xpm_path):
    """Reject disguised WAV/RIFF audio files that carry a .xpm extension."""
    try:
        with open(xpm_path, 'rb') as fh:
            return fh.read(4) != b'RIFF'
    except OSError:
        return False


def _unescape_json_str(raw_s):
    if '\\' not in raw_s:
        return raw_s
    try:
        val = json.loads(f'"{raw_s}"')
        return val if isinstance(val, str) else raw_s
    except Exception:
        return raw_s


def _parse_xpj_project_file(xpj_path, base_dir, data_dir):
    """Parse both gzipped ACVS JSON and Akai Desktop XML .xpj project files cleanly."""
    tempo = 120.0
    key = None
    unique_paths = set()
    missing_count = 0
    parse_error = False
    proj_wavs = []

    try:
        with open(xpj_path, 'rb') as fh:
            magic = fh.read(2)
        if magic == b'\x1f\x8b':
            with gzip.open(xpj_path, 'rt', encoding='utf-8', errors='ignore') as gz:
                content = gz.read()
            m_key = re.search(r'"key"\s*:\s*"([^"]+)"', content)
            if m_key:
                key = _unescape_json_str(m_key.group(1))
            m_tempo = re.search(r'"(?:masterTempo|tempo)"\s*:\s*([0-9\.]+)', content)
            if m_tempo:
                tempo = float(m_tempo.group(1))
            unique_paths = {
                _unescape_json_str(p)
                for p in re.findall(r'"path"\s*:\s*"([^"]+)"', content)
                if p and not p.startswith('.')
            }
            if os.path.exists(data_dir):
                for p in unique_paths:
                    cand = os.path.join(data_dir, p)
                    if os.path.exists(cand):
                        if cand.lower().endswith('.wav') and os.path.isfile(cand):
                            proj_wavs.append(cand)
                    else:
                        missing_count += 1
            else:
                missing_count = len(unique_paths)
        else:
            with open(xpj_path, 'rt', encoding='utf-8', errors='ignore') as tf:
                content = tf.read()
            if not content.lstrip().startswith('<'):
                return tempo, key, unique_paths, missing_count, True, proj_wavs
            root_xml = ET.fromstring(content)
            bpm_txt = root_xml.findtext('.//BPM')
            if bpm_txt:
                try:
                    tempo = float(bpm_txt)
                except ValueError:
                    pass
            xml_key = root_xml.findtext('.//Key') or root_xml.findtext('.//MusicalKey')
            if xml_key:
                key = xml_key.strip()
            for f_el in root_xml.findall('.//FileList/File'):
                raw_f = (f_el.text or '').strip().replace('\\', '/')
                if not raw_f:
                    continue
                if raw_f.startswith('./'):
                    raw_f = raw_f[2:]
                unique_paths.add(raw_f)
                cand_base = os.path.join(base_dir, raw_f)
                cand_dd = os.path.join(data_dir, os.path.basename(raw_f)) if data_dir else ''
                hit = cand_base if os.path.exists(cand_base) else (cand_dd if cand_dd and os.path.exists(cand_dd) else None)
                if hit is None:
                    missing_count += 1
                elif hit.lower().endswith('.wav') and os.path.isfile(hit):
                    proj_wavs.append(hit)
    except Exception:
        parse_error = True

    if not parse_error and not proj_wavs and os.path.isdir(data_dir):
        proj_wavs = [
            os.path.join(data_dir, df)
            for df in sorted(os.listdir(data_dir))
            if df.lower().endswith('.wav') and not df.startswith('.')
        ]
    return tempo, key, unique_paths, missing_count, parse_error, proj_wavs


def extract_bpm(filename):
    for rx in BPM_REGEXES:
        m = re.search(rx, filename)
        if m:
            val = m.group(1) if m.lastindex == 1 else m.group(2) if m.lastindex >= 2 and m.group(2).isdigit() else None
            if val and val.isdigit():
                iv = int(val)
                if 55 <= iv <= 190:
                    return iv
    return None

def get_bpm_tier(bpm):
    if not bpm: return "UNSPECIFIED"
    if bpm < 85: return "DOWN_TEMPO"
    if bpm <= 98: return "BOOM_BAP_LOFI"
    if bpm <= 118: return "MID_TEMPO"
    if bpm <= 132: return "HOUSE_GARAGE"
    if bpm <= 155: return "TRAP_HALFTIME"
    return "DNB_JUNGLE"

_KIT_BUILDER_MOD = None
_KIT_BUILDER_TRIED = False


def _get_kit_builder():
    global _KIT_BUILDER_MOD, _KIT_BUILDER_TRIED
    if not _KIT_BUILDER_TRIED:
        _KIT_BUILDER_TRIED = True
        try:
            here = str(Path(__file__).resolve().parent)
            if here not in sys.path:
                sys.path.insert(0, here)
            import hardware_kit_builder as hkb
            _KIT_BUILDER_MOD = hkb
        except Exception:
            _KIT_BUILDER_MOD = None
    return _KIT_BUILDER_MOD


def _normalize_key_to_camelot(key_str):
    if not key_str:
        return None, None
    s = str(key_str).strip()
    if not s or s.lower() in ('percussion', 'percusion', 'atonal', 'none'):
        return (s if s.lower() in ('percussion', 'percusion') else None), None
    if s in CAMELOT_MAP:
        return s, CAMELOT_MAP[s]
    s_clean = s.replace('♯', '#').replace('♭', 'b')
    m = re.match(r'^([A-G](?:#|b)?)\s*(Major|Minor|Maj|Min|m)?$', s_clean, re.IGNORECASE)
    if m:
        root_n = m.group(1)[0].upper() + (m.group(1)[1:].lower() if len(m.group(1)) > 1 else '')
        mode_raw = (m.group(2) or '').lower()
        short_k = root_n + ('m' if mode_raw in ('m', 'min', 'minor') else '')
        if short_k in CAMELOT_MAP:
            return short_k, CAMELOT_MAP[short_k]
    return extract_key(s_clean)


_PERC_NON_TONAL_TYPES = {'KICK', 'SNARE', 'CLAP', 'HIHAT', 'CYMBAL', 'PERCUSSION', 'FX', 'ROLL_FILL'}


def extract_key(filename, sound_type=None):
    text = Path(filename).stem.replace('♯','#').replace('♭','b')
    # A root note, an octave or a bank letter does not establish major/minor.
    match = re.search(r'(?<![A-Za-z0-9])([A-Ga-g])([#b]?)[ _-]*(major|minor|maj|min|m)(?=$|[^A-Za-z]|[0-9])', text, re.IGNORECASE)
    if match:
        root, accidental, mode = match.groups()
        key = root.upper() + accidental + ('m' if mode != 'M' and mode.lower() in {'m','min','minor'} else '')
        return (key, CAMELOT_MAP[key]) if key in CAMELOT_MAP else (None, None)
    # Never invent note-only key tags like "C1" on dry drum / percussion one-shots
    if sound_type and str(sound_type).upper() in _PERC_NON_TONAL_TYPES:
        return None, None
    match = re.search(r'(?i)(?:^|[ _-])key[ _-]*([a-g])([#b]?)(?![a-z])',text)
    if not match:
        match = re.search(r'(?<![A-Za-z0-9])([A-G])([#b]?)[0-8](?![A-Za-z0-9])', text)
    if match:
        return match[1].upper() + match[2] + ' (nota)', None
    return None, None


def measure_energy(path):
    """Bounded PCM RMS estimate; not genre, integrated loudness or musical intensity."""
    try:
        with wave.open(str(path), 'rb') as audio:
            width, channels, count = audio.getsampwidth(), audio.getnchannels(), audio.getnframes()
            if width not in {1,2,3,4} or not count or not 1 <= channels <= 8:
                return 'UNMEASURED'
            window = min(count, 4096)
            positions = sorted({0, max(0,(count-window)//2), max(0,count-window)})
            squares = 0
            values_count = 0
            for position in positions:
                audio.setpos(position)
                data = audio.readframes(window)
                if len(data) % width:
                    return 'UNMEASURED'
                if width == 1:
                    values = [v-128 for v in data]
                    squares += sum(v*v for v in values)
                    values_count += len(values)
                elif width in {2,4}:
                    values = array.array('h' if width == 2 else 'i')
                    values.frombytes(data)
                    if sys.byteorder != 'little':
                        values.byteswap()
                    squares += sum(v*v for v in values)
                    values_count += len(values)
                else:
                    mv = memoryview(data)
                    n_samp = len(mv) // 3
                    raw16 = bytearray(n_samp * 2)
                    raw16[0::2] = mv[1::3]
                    raw16[1::2] = mv[2::3]
                    values = array.array('h')
                    values.frombytes(raw16)
                    if sys.byteorder != 'little':
                        values.byteswap()
                    sq = sum(v * v for v in values) * 65536
                    if sq == 0 and any(mv):
                        sq = 1
                    squares += sq
                    values_count += n_samp
            if not values_count:
                return 'UNMEASURED'
            if not squares:
                return 'SILENT'
            dbfs = 10 * math.log10(squares / values_count / (2 ** (8*width-1))**2)
            return 'CHILL' if dbfs < -24 else ('GROOVE' if dbfs < -12 else 'BANGER')
    except (OSError, EOFError, wave.Error, ValueError, OverflowError):
        return 'UNMEASURED'


def render_expansion_card_html(expansion, project_paths=()):
    esc = lambda value: html.escape(str(value if value is not None else '—'), quote=True)
    title = esc(expansion.get('title', ''))
    path_value = expansion.get('path') or expansion.get('full_path') or ''
    path = esc(path_value)
    project_count = sum(p.is_relative_to(Path(path_value)) for p in project_paths) if path_value else 0
    folder = esc(Path(path_value).name if path_value else expansion.get('title', ''))
    cover = expansion.get('cover_url', '')
    picture = f'<img src="{esc(cover)}" alt="Carátula {title}" loading="lazy">' if cover and not cover.startswith(('http:', 'https:', '//', 'data:')) else '<div class="library-cover-placeholder" aria-hidden="true">🎛️</div>'
    manufacturer = esc(expansion.get('mfg', expansion.get('manufacturer')))
    programs = esc(expansion.get('programs', expansion.get('programs_count')))
    samples = esc(expansion.get('samples', expansion.get('samples_count')))
    extra_meta = ''
    if expansion.get('genre_style') or expansion.get('typical_bpm') or expansion.get('dominant_key'):
        bpm_txt = f"{esc(expansion.get('typical_bpm'))} BPM" if expansion.get('typical_bpm') else '—'
        key_txt = esc(expansion.get('dominant_key') or 'Percussion')
        genre_txt = esc(expansion.get('genre_style') or '')
        extra_meta = (
            f'<dt>Estilo / Tempo</dt><dd>{genre_txt} · {bpm_txt}</dd>'
            f'<dt>Key Root</dt><dd>{key_txt}</dd>'
        )
    return f'''<article class="card library-card" data-name="{title}" data-path="{path}" data-count="{programs}" data-samples="{samples}" data-search="{title} {manufacturer} {esc(expansion.get("genre_style", ""))} {esc(expansion.get("dominant_key", ""))} {path}">
          <div class="library-cover">{picture}</div><div class="library-card-heading"><span class="library-kind">Expansión MPC</span><span class="library-state">{programs} programas · {project_count} proyectos</span></div>
          <h3 translate="no">{title}</h3><p class="library-manufacturer" translate="no">{manufacturer}</p>
          <dl><dt>Samples</dt><dd>{samples}</dd><dt>Tamaño</dt><dd>{esc(expansion.get('size_mb'))} MB</dd>{extra_meta}</dl>
          <details class="library-location"><summary>Ubicación de la expansión</summary><code>{path}</code></details>
          <div class="card-actions"><button type="button" class="po33-btn-secondary library-action primary" data-expansion="{folder}" data-path="{path}" data-title="{title}" onclick="openExpansionBrowser(this.dataset.expansion,this.dataset.path,this.dataset.title)">🎛️ Ver programas</button>
          <button type="button" class="po33-btn-secondary library-action" data-expansion="{folder}" data-path="{path}" data-title="{title}" onclick="quickLoadExpansionFirstKit(this.dataset.expansion,this,this.dataset.path,this.dataset.title)">⚡ Cargar kit al rack</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" data-title="{title}" onclick="viewExpansionProjects(this.dataset.path,this.dataset.title)">📁 Ver proyectos ({project_count})</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" data-title="{title}" data-folder="{folder}" onclick="viewExpansionSamples(this.dataset.path,this.dataset.title,this.dataset.folder)">🔊 Explorar samples</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" data-title="{title}" data-mfg="{manufacturer}" data-cover="{esc(cover)}" data-desc="{esc(expansion.get('desc', ''))}" onclick="openEditExpansionModal(this.dataset.path,this.dataset.title,this.dataset.mfg,this.dataset.cover,this.dataset.desc)">✏️ Editar pack / portada</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="revealLibraryPath(this.dataset.path,this)">📁 Mostrar en Finder</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="copyLibraryPath(this.dataset.path)">📋 Copiar ruta</button></div></article>'''


def render_catalog(template, records, metadata, root_path=None):
    marker = re.search(r'const SAMPLES\s*=\s*', template)
    if not marker:
        raise ValueError('La plantilla no declara SAMPLES')
    _, end = json.JSONDecoder().raw_decode(template[marker.end():])
    safe_records = json.dumps(records, ensure_ascii=False).replace('<', '\\u003c')
    rendered = template[:marker.end()] + safe_records + template[marker.end() + end:]
    projects = metadata.get('projects', [])
    expansions = metadata.get('expansions', [])
    values = {'__SAMPLE_COUNT__': f'{len(records):,}',
              '__VOLUME_GB__': f'{sum(float(row[9] or 0) for row in records) / 1024:.2f} GB',
              '__PROJECT_COUNT__': str(len(projects)), '__EXPANSION_COUNT__': str(len(expansions))}
    for key, value in values.items():
        rendered = rendered.replace(key, value)
    esc = lambda value: html.escape(str(value if value is not None else '—'), quote=True)
    labels = {'UNKNOWN':'Sin identificar','UNSPECIFIED':'Sin identificar','UNMEASURED':'Sin medir',
              'SILENT':'Silencio medido','CHILL':'Baja · RMS','GROOVE':'Media · RMS','BANGER':'Alta · RMS'}
    for column, marker in [(2,'FORMAT'),(1,'TYPE'),(3,'MACRO'),(8,'ENERGY')]:
        counts = defaultdict(int)
        for row in records:
            counts[row[column] or 'UNSPECIFIED'] += 1
        stats = ''.join(f'<p>{esc(labels.get(k,k))}: <strong>{v:,}</strong></p>'
                        for k,v in sorted(counts.items(),key=lambda item:(-item[1],item[0])))
        rendered = rendered.replace('__STAT_' + marker + '__', stats or '<p>Biblioteca vacía</p>')
    bpm_counts = defaultdict(int)
    for row in records:
        bpm_counts[get_bpm_tier(row[5])] += 1
    rendered = rendered.replace('__STAT_BPM__',''.join(f'<p>{esc(k)}: <strong>{v:,}</strong></p>' for k,v in sorted(bpm_counts.items())) or '<p>Biblioteca vacía</p>')

    project_cards = []
    for project in projects:
        raw_title = str(project.get('name', ''))
        title = esc(raw_title)
        raw_path = project.get('rel_path') or project.get('file_path') or ''
        path = esc(raw_path)
        tempo = esc(project.get('tempo'))
        count = esc(project.get('samples', project.get('sample_refs_count')))
        missing_value = project.get('missing', project.get('missing_samples_count'))
        missing = esc(missing_value)
        status = project.get('status', '')
        warning = bool(missing_value) or status in {'ERROR', 'ATTENTION'}
        label = 'Revisar referencias' if warning else ('Índice sin avisos' if status in {'INDEX_OK', 'HEALTHY', 'Lectura actual OK'} else 'Sin inspeccionar')
        full_parts = list(Path(raw_path).parts)
        low_parts = [pt.lower() for pt in full_parts]
        if 'expansions' in low_parts:
            idx = low_parts.index('expansions')
            parts = full_parts[idx:]
        elif 'projects' in low_parts:
            idx = low_parts.index('projects')
            parts = full_parts[idx:]
        elif 'custom_kits' in low_parts:
            idx = low_parts.index('custom_kits')
            parts = full_parts[idx:]
        elif root_path:
            try:
                parts = list(Path(raw_path).relative_to(root_path).parts)
            except (ValueError, TypeError):
                parts = full_parts
        else:
            parts = full_parts
        kind = 'sessions' if 'projects' in [p.lower() for p in parts] else 'kits'
        category = 'Sesión MPC' if kind == 'sessions' else 'Kit / otro proyecto'
        # Extraer Artista / Subcarpeta dentro de la expansión o colección
        group_name = ''
        artist_name = ''
        if len(parts) >= 3 and parts[0].lower() == 'expansions':
            exp_name = parts[1]
            sub_parts = [pt for pt in parts[2:-1] if not pt.endswith('_[ProjectData]') and not pt.endswith('_ProjectData')]
            if sub_parts and re.sub(r'[^a-z0-9]', '', sub_parts[-1].lower()) == re.sub(r'[^a-z0-9]', '', Path(raw_path).stem.lower()):
                sub_parts.pop()
            if sub_parts:
                top_folder = sub_parts[0]
                if top_folder == 'Artist Signature Kits':
                    low_t = raw_title.lower()
                    art = ""
                    if "'s " in raw_title: art = raw_title.split("'s ")[0].strip()
                    elif "’s " in raw_title: art = raw_title.split("’s ")[0].strip()
                    elif " - " in raw_title: art = raw_title.split(" - ")[0].strip()
                    elif any(k in low_t for k in ["msxii", "bodega", "deli", "subway"]): art = "MSXII Sound Design"
                    elif "controllerise" in low_t: art = "Controllerise Lo-Fi"
                    elif any(k in low_t for k in ["tracklib", "south bronx", "back pack", "live break", "house techno"]): art = "Tracklib"
                    elif any(k in low_t for k in ["decap", "knocking"]): art = "DECAP"
                    elif "just blaze" in low_t: art = "Just Blaze"
                    elif "very sick" in low_t: art = "Very Sick Beats"
                    elif "juls" in low_t: art = "Juls"
                    elif any(k in low_t for k in ["bullton", "bemular", "neronga", "alien baltan"]): art = "Cookin Soul"
                    elif any(k in low_t for k in ["honda fist", "dragon knuckle"]): art = "Martial Beats"
                    elif any(k in low_t for k in ["90s grunge", "grunge"]): art = "90s Grunge Lab"
                    elif any(k in low_t for k in ["beats & chill", "lofi", "faded"]): art = "Chill Lo-Fi Collective"
                    elif any(k in low_t for k in ["uk drill", "drill"]): art = "Drill Signature"
                    elif any(k in low_t for k in ["trap", "modern trap", "classic trap"]): art = "Trap Signature"
                    else: art = "Signature Producer"
                    artist_name = art
                    group_name = f"Artist Signature Kits · {art}"
                else:
                    if " - " in top_folder:
                        artist_name = top_folder.split(" - ")[0].strip()
                    elif top_folder not in ("Core", "Instruments", "Drums", "Bonus_Loops_&_Shots"):
                        artist_name = top_folder
                    elif top_folder == "Core":
                        artist_name = "Akai Core Library"
                    group_name = ' / '.join(sub_parts)
            else:
                m_pref = re.match(r"^(Trap|BoomBap|DanceHall|Urban|Pop|DeepHouse|FutureHouse|EDM|Funk|Soul|RnB|R&B|LoFi|Drill|House|Inst)[-_]", raw_title, re.I)
                group_name = f"{exp_name} · {m_pref.group(1)} Kits" if m_pref else exp_name
        elif len(parts) >= 2:
            group_name = parts[0]
        group_esc = esc(group_name) if group_name else ''
        art_esc = esc(artist_name) if artist_name else ''
        group_html = f'<p class="library-manufacturer" translate="no">🎭 {group_esc}</p>' if group_esc else ''
        project_cards.append(f'''<article class="card library-card" data-name="{title}" data-tempo="{tempo}" data-count="{count}" data-kind="{kind}" data-group="{group_esc}" data-artist="{art_esc}" data-path="{path}" data-search="{title} {group_esc} {art_esc} {path}">
          <div class="library-card-heading"><span class="library-kind">{category}</span><span class="library-state {'warning' if warning else ''}">{label}</span></div>
          <h3 translate="no">{title}</h3>{group_html}<dl><dt>Tempo</dt><dd>{tempo} BPM</dd><dt>Muestras referenciadas</dt><dd>{count}</dd><dt>Ausentes en el índice</dt><dd>{missing}</dd></dl>
          <details class="library-location"><summary>Ubicación del proyecto</summary><code>{path}</code></details>
          <div class="card-actions"><button type="button" class="po33-btn-secondary library-action primary" data-project="{title}" data-path="{path}" onclick="loadProjectToRack(this.dataset.project,this.dataset.path,null,this)">🎛️ Editar copia en rack</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="revealLibraryPath(this.dataset.path,this)">📁 Mostrar en Finder</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="copyLibraryPath(this.dataset.path)">📋 Copiar ruta</button></div></article>''')
    project_paths = [Path(p.get('rel_path') or p.get('file_path') or '') for p in projects]
    expansion_cards = [render_expansion_card_html(expansion, project_paths) for expansion in expansions]
    return rendered.replace('<!--PROJECT_CARDS-->', ''.join(project_cards)).replace(
        '<!--EXPANSION_CARDS-->', ''.join(expansion_cards))

CATALOG_QUERY = """SELECT filename, sound_type, sample_format, macro_category,
    sub_pack, COALESCE(bpm, 0), COALESCE(musical_key, '-'), COALESCE(camelot, '-'),
    energy_level, size_mb, rel_path, id FROM samples ORDER BY id"""


def restore_empty_catalog(root, template_path=None):
    """Recover an installed blank preview from its existing index, without reindexing."""
    root = Path(root).resolve()
    catalog = root / CATALOG_REL
    if catalog.is_file():
        text = catalog.read_text(encoding='utf-8')
        marker = re.search(r'const SAMPLES\s*=\s*', text)
        if not marker or json.JSONDecoder().raw_decode(text[marker.end():])[0] != []:
            return False
    database = database_path(root)
    metadata_file = database.parent / 'mpc_sample.json'
    if not database.is_file() or not metadata_file.is_file():
        return False
    with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        records = connection.execute(CATALOG_QUERY).fetchall()
        if not records:
            return False
        metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
        if (not isinstance(metadata, dict)
                or not isinstance(metadata.get('projects'), list)
                or not isinstance(metadata.get('expansions'), list)
                or metadata.get('total_samples') != len(records)
                or len(metadata.get('projects', [])) != connection.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
                or len(metadata.get('expansions', [])) != connection.execute('SELECT COUNT(*) FROM expansions').fetchone()[0]):
            raise ValueError('Catalog recovery requires matching database and metadata; existing files were preserved')
    template = Path(template_path) if template_path else Path(__file__).parent / 'templates/catalogo.html'
    html_out = render_catalog(template.read_text(encoding='utf-8'), records, metadata, root_path=str(root))
    write_catalog(root, html_out)
    return True


_EXPANSION_PROGRAM_EXTS = {'.xpm', '.pgm', '.akp', '.xty', '.xtd', '.xpj'}
_EXPANSION_AUDIO_EXTS = {'.wav', '.aif', '.aiff', '.flac', '.mp3'}


def _scan_expansion_metrics(exp_dir):
    """Cuenta programas únicos y muestras (con fallback a _[ProjectData]) de una expansión."""
    program_keys = set()
    outer_samples = 0
    inner_samples = 0
    total_bytes = 0
    wav_cands = []

    for er, _, efiles in os.walk(str(exp_dir)):
        in_proj_data = '_[ProjectData]' in er or '_ProjectData' in er or '_[TrackData]' in er
        for ef in efiles:
            if ef.startswith('.'):
                continue
            ext = os.path.splitext(ef)[1].lower()
            efp = os.path.join(er, ef)
            try:
                fsz = os.path.getsize(efp)
            except OSError:
                fsz = 0
            total_bytes += fsz
            if ext in _EXPANSION_PROGRAM_EXTS and not in_proj_data:
                if ext != '.xpm' or _is_real_xpm_file(efp):
                    program_keys.add((er, os.path.splitext(ef)[0].lower()))
            elif ext in _EXPANSION_AUDIO_EXTS:
                if in_proj_data:
                    inner_samples += 1
                else:
                    outer_samples += 1
            if ext == '.wav' and fsz >= 16000:
                low_ef = ef.lower()
                prio = 2 if (any(k in low_ef for k in ('loop', 'melod', 'chord', 'bolero', 'soul', 'jazz', 'piano', 'guitar', 'synth', 'vocal', 'vox')) or fsz >= 160000) else 0
                wav_cands.append((prio, 0 if in_proj_data else 1, fsz, efp))

    return len(program_keys), (outer_samples if outer_samples > 0 else inner_samples), total_bytes, wav_cands


def sync_expansion_into_catalog(root_path, exp_dir, template_path=None, old_exp_path=None):
    """Registra o actualiza de inmediato una expansión en SQLite, JSON y catálogo HTML sin esperar reindexación total."""
    root = Path(root_path).resolve()
    exp_p = Path(exp_dir).resolve()
    if not exp_p.is_dir() or not exp_p.is_relative_to(root):
        return None
    xml_path = exp_p / 'Expansion.xml'
    title = exp_p.name
    mfg = 'Astro1Deep'
    etype = 'drum'
    cover_img = ''
    exp_desc = ''
    if xml_path.is_file():
        try:
            tree = ET.parse(str(xml_path))
            root_el = tree.getroot()
            title = root_el.findtext('title') or title
            mfg = root_el.findtext('manufacturer') or mfg
            etype = root_el.findtext('type') or etype
            cover_img = root_el.findtext('img') or ''
            exp_desc = root_el.findtext('description') or ''
        except Exception:
            pass

    p_count, s_count, sz_bytes, wav_cands = _scan_expansion_metrics(exp_p)
    AUDIO_EXTS = _EXPANSION_AUDIO_EXTS
    sample_rows = []
    new_projects = []

    for er, _, efiles in os.walk(str(exp_p)):
        in_proj_data = '_[ProjectData]' in er or '_ProjectData' in er or '_[TrackData]' in er
        if in_proj_data:
            continue
        for ef in efiles:
            if ef.startswith('.'):
                continue
            ext = os.path.splitext(ef)[1].lower()
            efp = os.path.join(er, ef)
            try:
                fsize = os.path.getsize(efp)
            except OSError:
                fsize = 0
            if ext in AUDIO_EXTS:
                rel_p = os.path.relpath(efp, str(root)).replace('\\', '/')
                rel_dir = os.path.relpath(er, str(root)).replace('\\', '/')
                parts = rel_dir.split('/')
                macro = parts[0] if parts else 'Expansions'
                sub = parts[1] if len(parts) > 1 else exp_p.name
                stype = classify_sound_type(ef, rel_dir)
                sfmt = classify_sample_format(ef, stype, rel_dir)
                bpm = extract_bpm(ef)
                btier = get_bpm_tier(bpm)
                mkey, camelot = extract_key(ef, sound_type=stype)
                energy = measure_energy(efp)
                sample_rows.append((ef, stype, sfmt, macro, sub, bpm, btier, mkey, camelot, energy, ext, round(fsize / (1024 * 1024), 3), efp, rel_p))
            elif ext == '.xpj':
                p_name = ef[:-4]
                data_dir = os.path.join(er, p_name + '_[ProjectData]')
                if not os.path.exists(data_dir):
                    alt_dir = os.path.join(er, p_name, p_name + '_[ProjectData]')
                    if os.path.exists(alt_dir):
                        data_dir = alt_dir
                tempo, key, unique_paths, missing_count, parse_error, proj_wavs = _parse_xpj_project_file(efp, er, data_dir)
                kit_mod = _get_kit_builder()
                if not parse_error and kit_mod and hasattr(kit_mod, 'analyze_kit_key_and_bpm'):
                    km = kit_mod.analyze_kit_key_and_bpm(
                        p_name,
                        proj_wavs,
                        project_tempo=tempo,
                        project_key=key,
                        expansion_hint=os.path.relpath(efp, str(root)),
                    )
                    tempo = km.get('bpm') or tempo
                    key = km.get('musical_key') or key
                status = 'ERROR' if parse_error else ('INDEX_OK' if missing_count == 0 else 'ATTENTION')
                sz_kb = round(fsize / 1024, 2)
                new_projects.append({
                    'name': p_name,
                    'file_path': efp,
                    'rel_path': os.path.relpath(efp, str(root)).replace('\\', '/'),
                    'tempo': round(tempo, 1),
                    'key': key,
                    'samples': len(unique_paths),
                    'missing': missing_count,
                    'status': status,
                    'size_kb': sz_kb,
                })

    sz_mb = round(sz_bytes / (1024 * 1024), 2)
    exp_rel = exp_p.relative_to(root).as_posix()
    cover_rel = (exp_p / cover_img).relative_to(root).as_posix() if cover_img and (exp_p / cover_img).is_file() else ''
    exp_entry = {
        'title': title,
        'mfg': mfg,
        'type': etype,
        'programs': p_count,
        'samples': s_count,
        'size_mb': sz_mb,
        'path': exp_rel,
        'cover_url': cover_rel,
        'desc': exp_desc,
    }
    kit_mod = _get_kit_builder()
    if kit_mod and hasattr(kit_mod, 'analyze_kit_key_and_bpm'):
        exp_wavs = sorted(
            [sr[12] for sr in sample_rows if sr[10] == '.wav' and os.path.getsize(sr[12]) >= 16000],
            key=lambda p: os.path.getsize(p),
            reverse=True,
        )[:20]
        if not exp_wavs and wav_cands:
            wav_cands.sort(reverse=True)
            exp_wavs = [t[3] for t in wav_cands[:20]]
        if exp_wavs:
            emeta = kit_mod.analyze_kit_key_and_bpm(title, exp_wavs, expansion_hint=f"{title} {mfg}")
            exp_entry['genre_style'] = emeta.get('genre_style', '')
            exp_entry['typical_bpm'] = emeta.get('bpm')
            exp_entry['dominant_key'] = emeta.get('musical_key')

    old_exp_p = Path(old_exp_path).resolve() if old_exp_path else None
    old_rel = None
    if old_exp_p and old_exp_p.is_relative_to(root) and old_exp_p != exp_p:
        old_rel = old_exp_p.relative_to(root).as_posix()

    proj_paths = [Path(p['rel_path']) for p in new_projects]

    database = database_path(root)
    metadata_file = database.parent / 'mpc_sample.json'
    if database.is_file() and metadata_file.is_file():
        conn = sqlite3.connect(str(database))
        try:
            cur = conn.cursor()
            cur.execute('DELETE FROM expansions WHERE full_path = ? OR title = ?', (str(exp_p), title))
            if old_exp_p and old_exp_p != exp_p:
                cur.execute('DELETE FROM expansions WHERE full_path = ?', (str(old_exp_p),))
                cur.execute('DELETE FROM projects WHERE file_path LIKE ?', (str(old_exp_p) + '/%',))
                cur.execute('DELETE FROM samples WHERE full_path LIKE ?', (str(old_exp_p) + '/%',))
            cur.execute(
                'INSERT INTO expansions (title, identifier, manufacturer, exp_type, version, cover_image, programs_count, samples_count, size_mb, full_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (title, title.lower(), mfg, etype, '1.0', cover_img, p_count, s_count, sz_mb, str(exp_p)),
            )
            for np in new_projects:
                cur.execute('DELETE FROM projects WHERE file_path = ?', (np['file_path'],))
                cur.execute(
                    'INSERT INTO projects (name, file_path, tempo, musical_key, sample_refs_count, missing_samples_count, status, size_kb) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (np['name'], np['file_path'], np['tempo'], np['key'], np['samples'], np['missing'], np['status'], np['size_kb']),
                )
            for sr in sample_rows:
                exists = cur.execute('SELECT 1 FROM samples WHERE rel_path = ? LIMIT 1', (sr[13],)).fetchone()
                if not exists:
                    cur.execute(
                        'INSERT INTO samples (filename, sound_type, sample_format, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, extension, size_mb, full_path, rel_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        sr,
                    )
            conn.commit()
            records = cur.execute(CATALOG_QUERY).fetchall()
        finally:
            conn.close()

        metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
        exps = [
            e for e in metadata.get('expansions', [])
            if e.get('path') not in (exp_rel, old_rel) and e.get('title') != title
        ]
        exps.append(exp_entry)
        new_proj_rels = {p['rel_path'] for p in new_projects}
        projs = [
            p for p in metadata.get('projects', [])
            if p.get('rel_path') not in new_proj_rels
            and not (old_rel and str(p.get('rel_path') or '').startswith(old_rel + '/'))
        ]
        projs.extend({k: v for k, v in p.items() if k != 'file_path'} for p in new_projects)
        metadata['expansions'] = exps
        metadata['projects'] = projs
        metadata['total_expansions'] = len(exps)
        metadata['total_projects'] = len(projs)
        metadata['total_samples'] = len(records)
        metadata_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
        proj_paths = [Path(p.get('rel_path') or p.get('file_path') or '') for p in projs]

        tpl = Path(template_path) if template_path and Path(template_path).is_file() else Path(__file__).parent / 'templates/catalogo.html'
        if tpl.is_file():
            rendered_html = render_catalog(tpl.read_text(encoding='utf-8'), records, metadata, root_path=str(root))
            write_catalog(root, rendered_html)

    card_html = render_expansion_card_html(exp_entry, proj_paths)
    return {'expansion': exp_entry, 'card_html': card_html, 'projects_added': len(new_projects)}


def _atomic_write_json(path: Path, data) -> None:
    """Persist JSON cache files atomically via temp file + fsync + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.stem}-", delete=False) as tf:
            tmp_path = Path(tf.name)
            tf.write(encoded)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Indexador Universal de Samples y Proyectos para Akai MPC")
    parser.add_argument("--path", "-p", default=".", help="Ruta de la tarjeta SD, USB o carpeta de samples (por defecto: directorio actual)")
    parser.add_argument("--output", "-o", default="", help="Ruta de salida para la base de datos y catálogo (por defecto: [PATH]/BeatOS/data)")
    parser.add_argument("--lang", choices=("es", "en"), default=os.environ.get("BEATOS_LANG", "en") if os.environ.get("BEATOS_LANG") in ("es", "en") else "en", help="Console language (es/en)")
    args = parser.parse_args()

    def emit(value):
        print(translate_text(str(value), args.lang))

    root_path = os.path.abspath(args.path)
    if not Path(root_path).is_dir():
        parser.error(translate_text("La biblioteca indicada no existe o no es una carpeta", args.lang))
    try:
        index_library(args, root_path, emit)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, cli_failure("No se pudo indexar la biblioteca.", error, args.lang) + "\n")


def index_library(args, root_path, emit):
    output_dir = os.path.abspath(args.output) if args.output else str(library_data_dir(root_path))
    os.makedirs(output_dir, exist_ok=True)

    db_path = os.path.join(output_dir, "mpc_sample.db")
    json_path = os.path.join(output_dir, "mpc_sample.json")
    csv_path = os.path.join(output_dir, "mpc_sample_resumen.csv")
    html_sqlite_path = os.path.join(root_path, "BeatOS", "data", "catalogo.html")

    emit("=" * 65)
    emit("🎛️  BEATOS — UNIVERSAL BEATMAKER STATION & CATALOG")
    emit("=" * 65)
    emit(f"Ruta de Origen : {root_path}")
    emit(f"Ruta de Salida : {output_dir}")
    emit(f"Base de Datos  : {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")

        schema_file = os.path.join(os.path.dirname(__file__), "schema.sql")
        if os.path.exists(schema_file):
            with open(schema_file, 'r', encoding='utf-8') as f:
                cur.executescript(f.read())
        else:
            cur.executescript("""
            CREATE TABLE IF NOT EXISTS sound_categories (code TEXT PRIMARY KEY, name TEXT NOT NULL, icon TEXT);
            CREATE TABLE IF NOT EXISTS expansions (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, identifier TEXT, manufacturer TEXT, exp_type TEXT, version TEXT, cover_image TEXT, programs_count INTEGER DEFAULT 0, samples_count INTEGER DEFAULT 0, size_mb REAL DEFAULT 0.0, full_path TEXT);
            CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, file_path TEXT NOT NULL, tempo REAL, musical_key TEXT, sample_refs_count INTEGER DEFAULT 0, missing_samples_count INTEGER DEFAULT 0, status TEXT, size_kb REAL DEFAULT 0.0);
            CREATE TABLE IF NOT EXISTS packs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, macro_category TEXT, samples_count INTEGER DEFAULT 0, size_mb REAL DEFAULT 0.0, full_path TEXT);
            CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, sound_type TEXT NOT NULL, macro_category TEXT, sub_pack TEXT, bpm INTEGER, bpm_tier TEXT, musical_key TEXT, camelot TEXT, energy_level TEXT, extension TEXT, size_mb REAL DEFAULT 0.0, full_path TEXT, rel_path TEXT);
            """)
        columns = {row[1] for row in cur.execute('PRAGMA table_info(samples)')}
        for col_name, col_def in (
            ('sample_format', "TEXT DEFAULT 'ONE_SHOT'"),
            ('wav_health', "TEXT DEFAULT 'OK'"),
            ('sample_rate', "INTEGER DEFAULT 0"),
            ('channels', "INTEGER DEFAULT 0"),
            ('bits_per_sample', "INTEGER DEFAULT 0"),
            ('has_slices', "INTEGER DEFAULT 0"),
        ):
            if col_name not in columns:
                cur.execute(f"ALTER TABLE samples ADD COLUMN {col_name} {col_def}")
        for idx_sql in (
            "CREATE INDEX IF NOT EXISTS idx_sample_rel_path ON samples(rel_path);",
            "CREATE INDEX IF NOT EXISTS idx_sample_sub_pack ON samples(sub_pack);",
            "CREATE INDEX IF NOT EXISTS idx_sample_format ON samples(sample_format);",
            "CREATE INDEX IF NOT EXISTS idx_sample_wav_health ON samples(wav_health);",
        ):
            cur.execute(idx_sql)
        try:
            cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS samples_fts USING fts5(
                filename, sound_type, macro_category, sub_pack, musical_key, rel_path,
                content='samples', content_rowid='id'
            );
            """)
        except sqlite3.OperationalError:
            pass
        conn.commit()
        cur.execute('BEGIN IMMEDIATE')
        for table in ('samples', 'projects', 'expansions', 'packs'):
            cur.execute(f'DELETE FROM {table}')

        kit_mod = _get_kit_builder()
        cache_path = Path(output_dir) / "audio_meta_cache.json"
        audio_meta_cache = {}
        if cache_path.is_file():
            try:
                loaded_c = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded_c, dict):
                    audio_meta_cache = loaded_c
            except Exception:
                audio_meta_cache = {}

        energy_cache_path = Path(output_dir) / "energy_meta_cache.json"
        energy_meta_cache = {}
        if energy_cache_path.is_file():
            try:
                loaded_e = json.loads(energy_cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded_e, dict):
                    energy_meta_cache = loaded_e
            except Exception:
                energy_meta_cache = {}

        def _cached_audio_meta(wav_fp, stype_hint, fsz, mtime_int):
            if not kit_mod or not hasattr(kit_mod, "analyze_audio_musical_metadata"):
                return None
            ck = f"{wav_fp}|{fsz}|{mtime_int}"
            if ck in audio_meta_cache:
                return audio_meta_cache[ck]
            m = kit_mod.analyze_audio_musical_metadata(wav_fp, sound_type_hint=stype_hint)
            audio_meta_cache[ck] = m
            return m

        _SKIP_DIRS_ALWAYS = {'BACKUPS_SEGURIDAD','backups_seguridad','templates','01_INSTALADORES','00_COMPARTIR_BEATOS','_PC_MAC_INSTALLERS','_RAW_SOURCE_ARCHIVES'}
        _SKIP_ROOT_DIRS = {'BeatOS','SQLITE_DATABASE','_INDEX_MPC_SAMPLE','02_DOCUMENTACION','00_ABRIR_BEATOS'}
        _SKIP_MELODEE_INTERNAL = {'Plugins', 'Plugin Data', 'Cache', 'Crashes'}
        AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac"}

        # Recorrido único de árbol de archivos para proyectos, expansiones y audio
        xpj_entries = []
        expansion_dirs = []
        audio_entries = []
        root_p = Path(root_path)
        for r, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in _SKIP_DIRS_ALWAYS]
            rp = Path(r)
            if rp == root_p:
                dirs[:] = [d for d in dirs if d not in _SKIP_ROOT_DIRS]
            elif rp.name == 'Melodee' and rp.parent == root_p:
                dirs[:] = [d for d in dirs if d not in _SKIP_MELODEE_INTERNAL]
            if any(part.startswith('.') for part in r.split(os.sep)):
                continue
            for f in files:
                if f.endswith(".xpj") and not f.startswith('.'):
                    xpj_entries.append((r, f))
            if "Expansion.xml" in files:
                expansion_dirs.append(r)
            if "_[ProjectData]" not in r and ".git" not in r:
                audio_files = [f for f in files if not f.startswith('.') and os.path.splitext(f)[1].lower() in AUDIO_EXTS]
                if audio_files:
                    audio_entries.append((r, audio_files))

        # 1. Escanear Proyectos MPC (.xpj)
        emit("\n🔍 1. Buscando y analizando proyectos MPC (.xpj)...")
        total_projects = 0
        projects_list = []
        for r, f in xpj_entries:
            xpj_path = os.path.join(r, f)
            p_name = f[:-4]
            data_dir = os.path.join(r, p_name + "_[ProjectData]")
            if not os.path.exists(data_dir):
                alt_dir = os.path.join(r, p_name, p_name + "_[ProjectData]")
                if os.path.exists(alt_dir):
                    data_dir = alt_dir

            tempo, key, unique_paths, missing_count, parse_error, proj_wavs = _parse_xpj_project_file(xpj_path, r, data_dir)

            if not parse_error and kit_mod and hasattr(kit_mod, "analyze_kit_key_and_bpm"):
                exp_rel_hint = os.path.relpath(xpj_path, root_path)
                kmeta = kit_mod.analyze_kit_key_and_bpm(
                    p_name,
                    proj_wavs,
                    project_tempo=tempo,
                    project_key=key,
                    expansion_hint=exp_rel_hint,
                    meta_cache=audio_meta_cache,
                )
                if kmeta.get("bpm"):
                    tempo = float(kmeta["bpm"])
                if kmeta.get("musical_key"):
                    key = kmeta["musical_key"]

            status = "ERROR" if parse_error else ("INDEX_OK" if missing_count == 0 else "ATTENTION")
            sz_kb = round(os.path.getsize(xpj_path) / 1024, 2)
            cur.execute("""
            INSERT INTO projects (name, file_path, tempo, musical_key, sample_refs_count, missing_samples_count, status, size_kb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (p_name, xpj_path, tempo, key, len(unique_paths), missing_count, status, sz_kb))
            total_projects += 1
            projects_list.append({"name": p_name, "tempo": round(tempo, 1), "key": key, "samples": len(unique_paths), "missing": missing_count, "status": status, "size_kb": sz_kb, "rel_path": os.path.relpath(xpj_path, root_path)})
            if args.lang == "en":
                emit(f"  ✔ Project: {p_name} | {round(tempo, 1)} BPM | Key: {key} | Samples: {len(unique_paths)} | Status: {status}")
            else:
                emit(f"  ✔ Proyecto: {p_name} | {round(tempo, 1)} BPM | Clave: {key} | Samples: {len(unique_paths)} | Estado: {status}")

        # 2. Escanear Expansiones Oficiales
        emit("\n📦 2. Buscando Expansiones Oficiales MPC...")
        total_expansions = 0
        expansions_list = []
        for r in expansion_dirs:
            xml_path = os.path.join(r, "Expansion.xml")
            title = os.path.basename(r)
            mfg = "Akai/Third-Party"
            etype = "Expansion"
            cover_img = ""
            exp_desc = ""
            try:
                tree = ET.parse(xml_path)
                root_el = tree.getroot()
                title = root_el.findtext("title") or title
                mfg = root_el.findtext("manufacturer") or mfg
                etype = root_el.findtext("type") or etype
                cover_img = root_el.findtext("img") or ""
                exp_desc = root_el.findtext("description") or ""
            except (ET.ParseError, OSError):
                pass

            p_count, s_count, sz_bytes, wav_cands = _scan_expansion_metrics(r)

            exp_meta = {}
            if kit_mod and hasattr(kit_mod, "analyze_kit_key_and_bpm"):
                wav_cands.sort(reverse=True)
                rep_wavs = [t[3] for t in wav_cands[:20]]
                exp_meta = kit_mod.analyze_kit_key_and_bpm(
                    title,
                    rep_wavs,
                    expansion_hint=f"{title} {mfg}",
                    meta_cache=audio_meta_cache,
                )

            sz_mb = round(sz_bytes / (1024*1024), 2)
            cur.execute("""
            INSERT INTO expansions (title, identifier, manufacturer, exp_type, version, cover_image, programs_count, samples_count, size_mb, full_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, title.lower(), mfg, etype, "1.0", cover_img, p_count, s_count, sz_mb, r))
            total_expansions += 1
            exp_dict = {
                "title": title, "mfg": mfg, "type": etype, "programs": p_count, "samples": s_count,
                "size_mb": sz_mb, "path": os.path.relpath(r, root_path),
                "cover_url": os.path.relpath(os.path.join(r, cover_img), root_path) if cover_img and os.path.isfile(os.path.join(r, cover_img)) else "",
                "desc": exp_desc,
            }
            if exp_meta:
                exp_dict["genre_style"] = exp_meta.get("genre_style", "")
                exp_dict["typical_bpm"] = exp_meta.get("bpm")
                exp_dict["dominant_key"] = exp_meta.get("musical_key")
            expansions_list.append(exp_dict)
            if args.lang == "en":
                emit(f"  ✔ Expansion: {title} ({mfg}) | {p_count} Programs | {s_count} Samples")
            else:
                emit(f"  ✔ Expansión: {title} ({mfg}) | {p_count} Programas | {s_count} Samples")

        # 3. Escanear Samples de Audio
        emit("\n🔊 3. Escaneando y clasificando muestras de audio...")
        batch = []
        total_samples = 0
        total_bytes = 0
        seen_energy_keys = set()

        for r, files in audio_entries:
            rel = os.path.relpath(r, root_path)
            parts = rel.split(os.sep) if rel != '.' else []
            macro = parts[0] if parts else "GENERAL"
            sub = parts[1] if len(parts) > 1 else (parts[0] if parts else "ROOT")

            for f in files:
                ext = os.path.splitext(f)[1].lower()
                fp = os.path.join(r, f)
                try:
                    st_f = os.stat(fp)
                    sz = st_f.st_size
                    mtime_i = int(st_f.st_mtime)
                except Exception:
                    sz = 0
                    mtime_i = 0
                sz_mb = round(sz / (1024*1024), 3)
                total_samples += 1
                total_bytes += sz

                wav_health, sr_val, ch_val, bps_val, has_slices_val, dur_sec = (
                    _probe_wav_health(fp) if ext == ".wav" else ("NON_WAV", 0, 0, 0, 0, 0.0)
                )
                stype = classify_sound_type(f, rel)
                sample_format = classify_sample_format(f, stype, rel, duration_sec=dur_sec)
                bpm = extract_bpm(f)
                key, camelot = extract_key(f, sound_type=stype)

                # Análisis acústico jerárquico en WAVs largos/melódicos (>= ~1.5s) sin sobrescribir etiquetas fiables
                if (
                    kit_mod
                    and ext == ".wav"
                    and wav_health == "OK"
                    and sz >= 130000
                    and stype in ("MELODIC_LOOP", "DRUM_LOOP", "KEYS_SYNTH", "BASS_808", "VOCAL")
                    and (bpm is None or (key is None and stype != "DRUM_LOOP"))
                ):
                    ameta = _cached_audio_meta(fp, stype, sz, mtime_i)
                    if isinstance(ameta, dict):
                        if bpm is None and ameta.get("bpm"):
                            ab = int(ameta["bpm"])
                            if 55 <= ab <= 190:
                                bpm = ab
                        if key is None and stype != "DRUM_LOOP":
                            raw_k = ameta.get("key")
                            if raw_k:
                                norm_k, norm_cam = _normalize_key_to_camelot(raw_k)
                                if norm_k:
                                    key, camelot = norm_k, norm_cam
                            elif ameta.get("note_root") and float(ameta.get("key_confidence") or 0.0) >= 0.48:
                                key = f"{ameta['note_root']} (nota)"
                                camelot = None

                btier = get_bpm_tier(bpm)
                ek = f"{fp}|{sz}|{mtime_i}"
                seen_energy_keys.add(ek)
                energy = energy_meta_cache.get(ek)
                if energy is None:
                    energy = measure_energy(fp)
                    energy_meta_cache[ek] = energy

                batch.append((
                    f, stype, sample_format, macro, sub, bpm, btier, key, camelot, energy,
                    ext, sz_mb, fp, os.path.relpath(fp, root_path),
                    wav_health, sr_val, ch_val, bps_val, has_slices_val,
                ))
                if len(batch) >= 1500:
                    cur.executemany("""
                    INSERT INTO samples (filename, sound_type, sample_format, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, extension, size_mb, full_path, rel_path, wav_health, sample_rate, channels, bits_per_sample, has_slices)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    batch = []
                    sys.stdout.write(f"\r  Muestras indexadas: {total_samples:,}...")
                    sys.stdout.flush()

        if batch:
            cur.executemany("""
            INSERT INTO samples (filename, sound_type, sample_format, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, extension, size_mb, full_path, rel_path, wav_health, sample_rate, channels, bits_per_sample, has_slices)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
        emit(f"\n✔ Total muestras de audio: {total_samples:,} ({total_bytes / (1024**3):.2f} GB)")

        # Poblar tabla packs agregada desde samples + reconstruir índice FTS5
        cur.execute("""
        INSERT INTO packs (name, macro_category, samples_count, size_mb, full_path)
        SELECT COALESCE(sub_pack, 'ROOT'), COALESCE(macro_category, 'GENERAL'),
               COUNT(*), ROUND(SUM(COALESCE(size_mb, 0.0)), 2),
               MIN(full_path)
        FROM samples
        GROUP BY macro_category, sub_pack
        ORDER BY COUNT(*) DESC
        """)
        try:
            cur.execute("INSERT INTO samples_fts(samples_fts) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        energy_meta_cache = {k: energy_meta_cache[k] for k in seen_energy_keys if k in energy_meta_cache}
        try:
            _atomic_write_json(cache_path, audio_meta_cache)
            _atomic_write_json(energy_cache_path, energy_meta_cache)
        except Exception:
            pass

        # 4. Generar CSV y JSON
        emit("\n📊 4. Generando archivos de exportación...")
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Nombre", "Tipo_Sonido", "Categoria", "Pack", "BPM", "Rango_BPM", "Clave", "Camelot", "Energia", "Tam_MB", "Ruta_Relativa"])
            cur.execute("SELECT id, filename, sound_type, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, size_mb, rel_path FROM samples")
            writer.writerows(cur.fetchall())

        cur.execute("SELECT sound_type, count(*) FROM samples GROUP BY sound_type ORDER BY count(*) DESC")
        stypes = dict(cur.fetchall())
        cur.execute("SELECT energy_level, count(*) FROM samples GROUP BY energy_level")
        energies = dict(cur.fetchall())

        json_payload = {
            "generated_at": datetime.now().isoformat(),
            "total_samples": total_samples,
            "total_size_gb": round(total_bytes / (1024**3), 2),
            "total_projects": total_projects,
            "total_expansions": total_expansions,
            "sound_types": stypes,
            "energy_distribution": energies,
            "projects": projects_list,
            "expansions": expansions_list
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_payload, f, indent=2, ensure_ascii=False)

        # 5. Generar Catálogo HTML5
        emit("\n🌐 5. Generando Catálogo Web HTML5 interactivo...")
        cur.execute(CATALOG_QUERY)
        catalog_records = cur.fetchall()
        records_json = json.dumps(catalog_records, ensure_ascii=False)
        metadata_json = json.dumps(json_payload, ensure_ascii=False)

        # Leer catalogo_universal.html como base
        universal_template_path = os.path.join(os.path.dirname(__file__), "templates", "catalogo.html")
        if os.path.exists(universal_template_path):
            with open(universal_template_path, 'r', encoding='utf-8') as f:
                html_code = f.read()
            html_code = render_catalog(html_code, catalog_records, json_payload, root_path=root_path)
        else:
            # Fallback inline minimal catalog
            html_code = f"<html><body><h1>MPC Sample Catalog</h1><script>const SAMPLES={records_json}; const METADATA={metadata_json};</script></body></html>"

        write_catalog(root_path, html_code)

        emit(f"✔ Catálogo BeatOS (Raíz): {os.path.join(root_path, 'catalogo_beatos.html')}")
        emit(f"✔ Catálogo Universal de Discos (Raíz): {os.path.join(root_path, 'catalogo_universal.html')}")
        emit(f"✔ Catálogo Central BeatOS: {html_sqlite_path}")
        emit(f"✔ Base de Datos SQLite: {db_path}")
        emit("\n🎉 Indexación completada con éxito. Inicia BeatOS/ABRIR_BEATOS.command o el instalador de tu carpeta de código.")
    finally:
        try:
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.execute("PRAGMA journal_mode=DELETE;")
        except sqlite3.Error:
            pass
        conn.close()

if __name__ == "__main__":
    main()
