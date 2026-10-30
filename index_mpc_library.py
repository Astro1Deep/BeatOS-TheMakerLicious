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
from beatos_paths import data_dir as library_data_dir, write_catalog
from beatos_i18n import translate_text
import sqlite3
import json
import csv
import re
import gzip
import math
import wave
import array
import argparse
import html
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


def classify_sample_format(filename, sound_type, parent_dir=""):
    text = _sound_text(Path(filename).stem + ' ' + Path(parent_dir).name)
    if _has_keyword(text, 'stem'):
        return 'STEM'
    if any(_has_keyword(text, k) for k in ('roll','fill')):
        return 'ROLL_FILL'
    if sound_type in {'DRUM_LOOP','MELODIC_LOOP'} or _has_keyword(text, 'loop') or _has_keyword(text, 'lp'):
        return 'LOOP'
    if 'one shot' in text or 'oneshot' in text or sound_type in {'KICK','SNARE','CLAP','HIHAT','CYMBAL','PERCUSSION'}:
        return 'ONE_SHOT'
    return 'UNSPECIFIED'


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

def extract_key(filename):
    text = Path(filename).stem.replace('♯','#').replace('♭','b')
    # A root note, an octave or a bank letter does not establish major/minor.
    match = re.search(r'(?<![A-Za-z0-9])([A-Ga-g])([#b]?)[ _-]*(major|minor|maj|min|m)(?=$|[^A-Za-z]|[0-9])', text, re.IGNORECASE)
    if match:
        root, accidental, mode = match.groups()
        key = root.upper() + accidental + ('m' if mode != 'M' and mode.lower() in {'m','min','minor'} else '')
        return (key, CAMELOT_MAP[key]) if key in CAMELOT_MAP else (None, None)
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
                elif width in {2,4}:
                    values = array.array('h' if width == 2 else 'i')
                    values.frombytes(data)
                    if sys.byteorder != 'little':
                        values.byteswap()
                else:
                    values = [int.from_bytes(data[i:i+3],'little',signed=True) for i in range(0,len(data),3)]
                squares += sum(v*v for v in values)
                values_count += len(values)
            if not values_count:
                return 'UNMEASURED'
            if not squares:
                return 'SILENT'
            dbfs = 10 * math.log10(squares / values_count / (2 ** (8*width-1))**2)
            return 'CHILL' if dbfs < -24 else ('GROOVE' if dbfs < -12 else 'BANGER')
    except (OSError, EOFError, wave.Error, ValueError, OverflowError):
        return 'UNMEASURED'


def render_catalog(template, records, metadata):
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
        title = esc(project.get('name', ''))
        raw_path = project.get('rel_path') or project.get('file_path') or ''
        path = esc(raw_path)
        tempo = esc(project.get('tempo'))
        count = esc(project.get('samples', project.get('sample_refs_count')))
        missing_value = project.get('missing', project.get('missing_samples_count'))
        missing = esc(missing_value)
        status = project.get('status', '')
        warning = bool(missing_value) or status in {'ERROR', 'ATTENTION'}
        label = 'Revisar referencias' if warning else ('Índice sin avisos' if status in {'INDEX_OK', 'HEALTHY', 'Lectura actual OK'} else 'Sin inspeccionar')
        kind = 'sessions' if 'projects' in [p.lower() for p in Path(raw_path).parts] else 'kits'
        category = 'Sesión MPC' if kind == 'sessions' else 'Kit / otro proyecto'
        project_cards.append(f'''<article class="card library-card" data-name="{title}" data-tempo="{tempo}" data-count="{count}" data-kind="{kind}" data-path="{path}" data-search="{title} {path}">
          <div class="library-card-heading"><span class="library-kind">{category}</span><span class="library-state {'warning' if warning else ''}">{label}</span></div>
          <h3>{title}</h3><dl><dt>Tempo</dt><dd>{tempo} BPM</dd><dt>Muestras referenciadas</dt><dd>{count}</dd><dt>Ausentes en el índice</dt><dd>{missing}</dd></dl>
          <details class="library-location"><summary>Ubicación del proyecto</summary><code>{path}</code></details>
          <div class="card-actions"><button type="button" class="po33-btn-secondary library-action primary" data-project="{title}" data-path="{path}" onclick="loadProjectToRack(this.dataset.project,this.dataset.path,null,this)">🎛️ Editar copia en rack</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="revealLibraryPath(this.dataset.path,this)">📁 Mostrar en Finder</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="copyLibraryPath(this.dataset.path)">📋 Copiar ruta</button></div></article>''')
    project_paths = [Path(p.get('rel_path') or p.get('file_path') or '') for p in projects]
    expansion_cards = []
    for expansion in expansions:
        title = esc(expansion.get('title', ''))
        path_value = expansion.get('path') or expansion.get('full_path') or ''
        path = esc(path_value)
        project_count = sum(p.is_relative_to(Path(path_value)) for p in project_paths) if path_value else 0
        folder = esc(Path(path_value).name if path_value else expansion.get('title',''))
        cover = expansion.get('cover_url', '')
        picture = f'<img src="{esc(cover)}" alt="Carátula {title}" loading="lazy">' if cover and not cover.startswith(('http:', 'https:', '//', 'data:')) else '<div class="library-cover-placeholder" aria-hidden="true">🎛️</div>'
        manufacturer = esc(expansion.get('mfg', expansion.get('manufacturer')))
        programs = esc(expansion.get('programs', expansion.get('programs_count')))
        samples = esc(expansion.get('samples', expansion.get('samples_count')))
        expansion_cards.append(f'''<article class="card library-card" data-name="{title}" data-count="{programs}" data-samples="{samples}" data-search="{title} {manufacturer} {path}">
          <div class="library-cover">{picture}</div><div class="library-card-heading"><span class="library-kind">Expansión MPC</span><span class="library-state">{programs} programas · {project_count} proyectos</span></div>
          <h3>{title}</h3><p class="library-manufacturer">{manufacturer}</p>
          <dl><dt>Samples</dt><dd>{samples}</dd><dt>Tamaño</dt><dd>{esc(expansion.get('size_mb'))} MB</dd></dl>
          <details class="library-location"><summary>Ubicación de la expansión</summary><code>{path}</code></details>
          <div class="card-actions"><button type="button" class="po33-btn-secondary library-action primary" data-expansion="{folder}" onclick="openExpansionBrowser(this.dataset.expansion)">🎛️ Ver programas</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" data-title="{title}" onclick="viewExpansionProjects(this.dataset.path,this.dataset.title)">📁 Ver proyectos ({project_count})</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" data-title="{title}" data-folder="{folder}" onclick="viewExpansionSamples(this.dataset.path,this.dataset.title,this.dataset.folder)">🔊 Explorar samples</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="revealLibraryPath(this.dataset.path,this)">📁 Mostrar en Finder</button>
          <button type="button" class="po33-btn-secondary library-action" data-path="{path}" onclick="copyLibraryPath(this.dataset.path)">📋 Copiar ruta</button></div></article>''')
    return rendered.replace('<!--PROJECT_CARDS-->', ''.join(project_cards)).replace(
        '<!--EXPANSION_CARDS-->', ''.join(expansion_cards))

def main():
    parser = argparse.ArgumentParser(description="Indexador Universal de Samples y Proyectos para Akai MPC")
    parser.add_argument("--path", "-p", default=".", help="Ruta de la tarjeta SD, USB o carpeta de samples (por defecto: directorio actual)")
    parser.add_argument("--output", "-o", default="", help="Ruta de salida para la base de datos y catálogo (por defecto: [PATH]/BeatOS/data)")
    parser.add_argument("--lang", choices=("es", "en"), default=os.environ.get("BEATOS_LANG", "es") if os.environ.get("BEATOS_LANG") in ("es", "en") else "es", help="Console language (es/en)")
    args = parser.parse_args()

    def emit(value):
        emit(translate_text(str(value), args.lang))

    root_path = os.path.abspath(args.path)
    if not Path(root_path).is_dir():
        parser.error("La biblioteca indicada no existe o no es una carpeta")
    output_dir = os.path.abspath(args.output) if args.output else str(library_data_dir(root_path))
    os.makedirs(output_dir, exist_ok=True)

    db_path = os.path.join(output_dir, "mpc_sample.db")
    json_path = os.path.join(output_dir, "mpc_sample.json")
    csv_path = os.path.join(output_dir, "mpc_sample_resumen.csv")
    html_root_path = os.path.join(root_path, "catalogo_mpc_sample.html")
    html_sqlite_path = os.path.join(root_path, "BeatOS", "data", "catalogo.html")

    emit("=" * 65)
    emit("🎛️  AKAI MPC SAMPLE DATABASE & FINDER TOOLKIT")
    emit("=" * 65)
    emit(f"Ruta de Origen : {root_path}")
    emit(f"Ruta de Salida : {output_dir}")
    emit(f"Base de Datos  : {db_path}")

    conn = sqlite3.connect(db_path)
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
    if 'sample_format' not in columns:
        cur.execute("ALTER TABLE samples ADD COLUMN sample_format TEXT DEFAULT 'ONE_SHOT'")
    conn.commit()
    cur.execute('BEGIN IMMEDIATE')
    for table in ('samples', 'projects', 'expansions', 'packs'):
        cur.execute(f'DELETE FROM {table}')

    # 1. Escanear Proyectos MPC (.xpj)
    emit("\n🔍 1. Buscando y analizando proyectos MPC (.xpj)...")
    total_projects = 0
    projects_list = []
    for r, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'BACKUPS_SEGURIDAD','backups_seguridad','templates','01_INSTALADORES','00_COMPARTIR_BEATOS'}]
        if Path(r) == Path(root_path):
            dirs[:] = [d for d in dirs if d not in {'BeatOS','SQLITE_DATABASE','_INDEX_MPC_SAMPLE','02_DOCUMENTACION','00_ABRIR_BEATOS'}]
        if any(part.startswith('.') for part in r.split(os.sep)): continue
        for f in files:
            if f.endswith(".xpj") and not f.startswith('.'):
                xpj_path = os.path.join(r, f)
                p_name = f[:-4]
                data_dir = os.path.join(r, p_name + "_[ProjectData]")
                
                tempo = 120.0
                key = None
                parse_error = False
                missing_count = 0
                unique_paths = set()
                try:
                    with gzip.open(xpj_path, "rt", encoding="utf-8", errors="ignore") as gz:
                        content = gz.read()
                        m_key = re.search(r'\"key\"\s*:\s*\"([^\"]+)\"', content)
                        if m_key: key = m_key.group(1)
                        m_tempo = re.search(r'\"(?:masterTempo|tempo)\"\s*:\s*([0-9\.]+)', content)
                        if m_tempo: tempo = float(m_tempo.group(1))
                        paths = re.findall(r'\"path\"\s*:\s*\"([^\"]+)\"', content)
                        unique_paths = set(p for p in paths if p and not p.startswith('.'))
                        if os.path.exists(data_dir):
                            for p in unique_paths:
                                if not os.path.exists(os.path.join(data_dir, p)):
                                    missing_count += 1
                        else:
                            missing_count = len(unique_paths)
                except Exception as e:
                    parse_error = True
                
                status = "ERROR" if parse_error else ("INDEX_OK" if missing_count == 0 else "ATTENTION")
                sz_kb = round(os.path.getsize(xpj_path) / 1024, 2)
                cur.execute("""
                INSERT INTO projects (name, file_path, tempo, musical_key, sample_refs_count, missing_samples_count, status, size_kb)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (p_name, xpj_path, tempo, key, len(unique_paths), missing_count, status, sz_kb))
                total_projects += 1
                projects_list.append({"name": p_name, "tempo": round(tempo, 1), "key": key, "samples": len(unique_paths), "missing": missing_count, "status": status, "size_kb": sz_kb, "rel_path": os.path.relpath(xpj_path, root_path)})
                emit(f"  ✔ Proyecto: {p_name} | {round(tempo, 1)} BPM | Clave: {key} | Samples: {len(unique_paths)} | Estado: {status}")

    # 2. Escanear Expansiones Oficiales
    emit("\n📦 2. Buscando Expansiones Oficiales MPC...")
    total_expansions = 0
    expansions_list = []
    for r, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'BACKUPS_SEGURIDAD','backups_seguridad','templates','01_INSTALADORES','00_COMPARTIR_BEATOS'}]
        if Path(r) == Path(root_path):
            dirs[:] = [d for d in dirs if d not in {'BeatOS','SQLITE_DATABASE','_INDEX_MPC_SAMPLE','02_DOCUMENTACION','00_ABRIR_BEATOS'}]
        if any(part.startswith('.') for part in r.split(os.sep)): continue
        if "Expansion.xml" in files:
            xml_path = os.path.join(r, "Expansion.xml")
            title = os.path.basename(r)
            mfg = "Akai/Third-Party"
            etype = "Expansion"
            cover_img = ""
            try:
                tree = ET.parse(xml_path)
                root_el = tree.getroot()
                title = root_el.findtext("title") or title
                mfg = root_el.findtext("manufacturer") or mfg
                etype = root_el.findtext("type") or etype
                cover_img = root_el.findtext("img") or ""
            except: pass
            
            p_count = 0
            s_count = 0
            sz_bytes = 0
            for er, _, efiles in os.walk(r):
                for ef in efiles:
                    if ef.startswith('.'): continue
                    ext = os.path.splitext(ef)[1].lower()
                    efp = os.path.join(er, ef)
                    try: sz_bytes += os.path.getsize(efp)
                    except: pass
                    if ext in ['.xpm', '.pgm', '.akp']: p_count += 1
                    elif ext in ['.wav', '.aif', '.mp3']: s_count += 1
            
            sz_mb = round(sz_bytes / (1024*1024), 2)
            cur.execute("""
            INSERT INTO expansions (title, identifier, manufacturer, exp_type, version, cover_image, programs_count, samples_count, size_mb, full_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, title.lower(), mfg, etype, "1.0", cover_img, p_count, s_count, sz_mb, r))
            total_expansions += 1
            expansions_list.append({"title": title, "mfg": mfg, "type": etype, "programs": p_count, "samples": s_count, "size_mb": sz_mb, "path": os.path.relpath(r, root_path), "cover_url": os.path.relpath(os.path.join(r, cover_img), root_path) if cover_img and os.path.isfile(os.path.join(r, cover_img)) else ""})
            emit(f"  ✔ Expansión: {title} ({mfg}) | {p_count} Programas | {s_count} Samples")

    # 3. Escanear Samples de Audio
    emit("\n🔊 3. Escaneando y clasificando muestras de audio...")
    AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac"}
    batch = []
    total_samples = 0
    total_bytes = 0
    
    for r, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'BACKUPS_SEGURIDAD','backups_seguridad','templates','01_INSTALADORES','00_COMPARTIR_BEATOS'}]
        if Path(r) == Path(root_path):
            dirs[:] = [d for d in dirs if d not in {'BeatOS','SQLITE_DATABASE','_INDEX_MPC_SAMPLE','02_DOCUMENTACION','00_ABRIR_BEATOS'}]
        if any(part.startswith('.') for part in r.split(os.sep)): continue
        if "_[ProjectData]" in r or ".git" in r: continue
        rel = os.path.relpath(r, root_path)
        parts = rel.split(os.sep) if rel != '.' else []
        macro = parts[0] if parts else "GENERAL"
        sub = parts[1] if len(parts) > 1 else (parts[0] if parts else "ROOT")
        
        for f in files:
            if f.startswith('.'): continue
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTS:
                fp = os.path.join(r, f)
                try: sz = os.path.getsize(fp)
                except: sz = 0
                sz_mb = round(sz / (1024*1024), 3)
                total_samples += 1
                total_bytes += sz
                
                stype = classify_sound_type(f, rel)
                sample_format = classify_sample_format(f, stype, rel)
                bpm = extract_bpm(f)
                btier = get_bpm_tier(bpm)
                key, camelot = extract_key(f)
                energy = measure_energy(fp)
                
                batch.append((f, stype, sample_format, macro, sub, bpm, btier, key, camelot, energy, ext, sz_mb, fp, os.path.relpath(fp, root_path)))
                if len(batch) >= 1500:
                    cur.executemany("""
                    INSERT INTO samples (filename, sound_type, sample_format, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, extension, size_mb, full_path, rel_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    batch = []
                    sys.stdout.write(f"\r  Muestras indexadas: {total_samples:,}...")
                    sys.stdout.flush()

    if batch:
        cur.executemany("""
        INSERT INTO samples (filename, sound_type, sample_format, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, extension, size_mb, full_path, rel_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
    emit(f"\n✔ Total muestras de audio: {total_samples:,} ({total_bytes / (1024**3):.2f} GB)")

    conn.commit()

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
    cur.execute("""
    SELECT filename, sound_type, sample_format, macro_category, sub_pack, COALESCE(bpm, 0), COALESCE(musical_key, '-'), COALESCE(camelot, '-'), energy_level, size_mb, rel_path, id
    FROM samples
    ORDER BY id
    """)
    catalog_records = cur.fetchall()
    records_json = json.dumps(catalog_records, ensure_ascii=False)
    metadata_json = json.dumps(json_payload, ensure_ascii=False)

    # Leer catalogo_universal.html como base
    universal_template_path = os.path.join(os.path.dirname(__file__), "templates", "catalogo.html")
    if os.path.exists(universal_template_path):
        with open(universal_template_path, 'r', encoding='utf-8') as f:
            html_code = f.read()
        html_code = render_catalog(html_code, catalog_records, json_payload)
    else:
        # Fallback inline minimal catalog
        html_code = f"<html><body><h1>MPC Sample Catalog</h1><script>const SAMPLES={records_json}; const METADATA={metadata_json};</script></body></html>"

    write_catalog(root_path, html_code)

    emit(f"✔ Catálogo en Raíz: {html_root_path}")
    emit(f"✔ Catálogo en Carpeta SQLite: {html_sqlite_path}")
    emit(f"✔ Base de Datos SQLite: {db_path}")
    emit("\n🎉 Indexación completada con éxito. Inicia BeatOS/ABRIR_BEATOS.command o el instalador de tu carpeta de código.")
    conn.close()

if __name__ == "__main__":
    main()
