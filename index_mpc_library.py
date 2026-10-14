#!/usr/bin/env python3
"""
Akai MPC Sample Universal Indexer & Database Generator
Motor portátil y universal de indexación de audio y proyectos MPC para la comunidad.
No requiere dependencias externas (usa exclusivamente la biblioteca estándar de Python 3).

Uso:
    python3 index_mpc_library.py
    python3 index_mpc_library.py --path "/Volumes/MiTarjetaMPC" --output "./SQLITE_DATABASE"
"""

import os
import sys
import sqlite3
import json
import csv
import re
import gzip
import argparse
from datetime import datetime
from xml.etree import ElementTree as ET
from collections import defaultdict

# ==============================================================================
# TAXONOMÍA Y REGLAS DE FORMAS DE SONIDO Y GÉNEROS UNIVERSALES
# ==============================================================================

SOUND_RULES = [
    ("KICK", ["kick", "kik", "bd", "bassdrum", "bass drum", "bombo", "sub kick", "acoustic kick", "808 kick"]),
    ("SNARE", ["snare", "snr", "rimshot", "rim", "cross stick", "sidestick", "caja", "tarola", "snare roll", "acoustic snare"]),
    ("CLAP", ["clap", "clp", "snap", "finger snap", "palma", "palmas", "handclap"]),
    ("HIHAT", ["hihat", "hi-hat", "hat", "hh", "openhh", "closedhh", "open hat", "closed hat", "open-hat", "closed-hat", "oh", "ch", "pedal hat", "shaker", "tambourine", "tamb"]),
    ("CYMBAL", ["crash", "ride", "cymbal", "splash", "china", "gong", "cymb"]),
    ("PERCUSSION", ["perc", "prc", "conga", "bongo", "cowbell", "woodblock", "foley", "tom", "organic", "agogo", "timbales", "clave", "claves", "cabasa", "triangle", "cajon", "djembe", "tabla", "guiro", "cuica", "chimes", "maraca"]),
    ("BASS_808", ["808", "sub", "bass", "subbass", "reese", "synthbass", "synth bass", "electric bass", "upright bass", "slap bass", "bassline", "sub-bass"]),
    ("KEYS_SYNTH", ["piano", "rhodes", "wurli", "wurlitzer", "clav", "clavinet", "synth", "lead", "pluck", "organ", "brass", "horn", "trumpet", "trombone", "sax", "strings", "violin", "cello", "chord", "stab", "keys", "pad", "arp", "music box"]),
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

KEY_REGEXES = [
    r'[\s_\-]([A-G][#b]?(?:m|maj|min|Maj|Min)?)(?:[\s_\-]|\.|$)',
    r'(?:Key|key|KEY)[\s_\-]*([A-G][#b]?(?:m|maj|min)?)',
    r'([A-G][#b]?(?:m|maj|min|Maj|Min))\s*(?:1[0-9]{2}|[6-9][0-9])'
]

def classify_sound_type(filename, parent_dir=""):
    t = (filename + " " + parent_dir).lower()
    for code, keywords in SOUND_RULES:
        for kw in keywords:
            pattern = r'(?:\b|[\s\-_0-9])' + re.escape(kw) + r'(?:\b|[\s\-_0-9])'
            if re.search(pattern, t):
                return code
    if "kick" in t or "kik" in t: return "KICK"
    if "snr" in t or "snare" in t: return "SNARE"
    if "hat" in t: return "HIHAT"
    if "loop" in t: return "MELODIC_LOOP"
    if "drum" in t: return "DRUM_LOOP"
    if "chord" in t: return "KEYS_SYNTH"
    return "PERCUSSION"

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
    for rx in KEY_REGEXES:
        m = re.search(rx, filename)
        if m:
            k = m.group(1).strip()
            k = k.replace("Min", "m").replace("min", "m").replace("Maj", "").replace("maj", "").replace("Major", "").replace("minor", "m")
            if k in CAMELOT_MAP:
                return k, CAMELOT_MAP[k]
            base = k[0].upper() + (k[1] if len(k) > 1 and k[1] in '#b' else '')
            if base in CAMELOT_MAP:
                return base, CAMELOT_MAP[base]
    return None, None

def estimate_energy(sound_type, bpm_tier, macro_category, filename):
    t = (filename + " " + macro_category).lower()
    if sound_type in ["BASS_808"] and ("808" in t or "drill" in t or "trap" in t):
        return "BANGER"
    if bpm_tier in ["DNB_JUNGLE", "TRAP_HALFTIME"]:
        return "BANGER"
    if "lo-fi" in t or "lofi" in t or "ambient" in t or "chill" in t or bpm_tier == "DOWN_TEMPO":
        return "CHILL"
    if "boom bap" in t or "house" in t or "funk" in t or "groove" in t or bpm_tier in ["BOOM_BAP_LOFI", "HOUSE_GARAGE"]:
        return "GROOVE"
    return "GROOVE"

def main():
    parser = argparse.ArgumentParser(description="Indexador Universal de Samples y Proyectos para Akai MPC")
    parser.add_argument("--path", "-p", default=".", help="Ruta de la tarjeta SD, USB o carpeta de samples (por defecto: directorio actual)")
    parser.add_argument("--output", "-o", default="", help="Ruta de salida para la base de datos y catálogo (por defecto: [PATH]/SQLITE_DATABASE)")
    args = parser.parse_args()

    root_path = os.path.abspath(args.path)
    output_dir = os.path.abspath(args.output) if args.output else os.path.join(root_path, "SQLITE_DATABASE")
    os.makedirs(output_dir, exist_ok=True)

    db_path = os.path.join(output_dir, "mpc_sample.db")
    json_path = os.path.join(output_dir, "mpc_sample.json")
    csv_path = os.path.join(output_dir, "mpc_sample_resumen.csv")
    html_root_path = os.path.join(root_path, "catalogo_mpc_sample.html")
    html_sqlite_path = os.path.join(output_dir, "catalogo_mpc_sample.html")

    print("=" * 65)
    print("🎛️  AKAI MPC SAMPLE DATABASE & FINDER TOOLKIT")
    print("=" * 65)
    print(f"Ruta de Origen : {root_path}")
    print(f"Ruta de Salida : {output_dir}")
    print(f"Base de Datos  : {db_path}")

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
    conn.commit()

    # 1. Escanear Proyectos MPC (.xpj)
    print("\n🔍 1. Buscando y analizando proyectos MPC (.xpj)...")
    total_projects = 0
    projects_list = []
    for r, dirs, files in os.walk(root_path):
        if any(part.startswith('.') for part in r.split(os.sep)): continue
        for f in files:
            if f.endswith(".xpj") and not f.startswith('.'):
                xpj_path = os.path.join(r, f)
                p_name = f[:-4]
                data_dir = os.path.join(r, p_name + "_[ProjectData]")
                
                tempo = 120.0
                key = "C"
                missing_count = 0
                unique_paths = set()
                try:
                    with gzip.open(xpj_path, "rt", encoding="utf-8", errors="ignore") as gz:
                        content = gz.read()
                        m_key = re.search(r'\"key\"\s*:\s*\"([^\"]+)\"', content)
                        if m_key: key = m_key.group(1)
                        m_tempo = re.search(r'\"tempo\"\s*:\s*([0-9\.]+)', content)
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
                    pass
                
                status = "HEALTHY" if missing_count == 0 else "ATTENTION"
                sz_kb = round(os.path.getsize(xpj_path) / 1024, 2)
                cur.execute("""
                INSERT INTO projects (name, file_path, tempo, musical_key, sample_refs_count, missing_samples_count, status, size_kb)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (p_name, xpj_path, tempo, key, len(unique_paths), missing_count, status, sz_kb))
                total_projects += 1
                projects_list.append({"name": p_name, "tempo": round(tempo, 1), "key": key, "samples": len(unique_paths), "missing": missing_count, "status": status, "size_kb": sz_kb})
                print(f"  ✔ Proyecto: {p_name} | {round(tempo, 1)} BPM | Clave: {key} | Samples: {len(unique_paths)} | Estado: {status}")
    conn.commit()

    # 2. Escanear Expansiones Oficiales
    print("\n📦 2. Buscando Expansiones Oficiales MPC...")
    total_expansions = 0
    expansions_list = []
    for r, dirs, files in os.walk(root_path):
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
            expansions_list.append({"title": title, "mfg": mfg, "type": etype, "programs": p_count, "samples": s_count, "size_mb": sz_mb, "path": r})
            print(f"  ✔ Expansión: {title} ({mfg}) | {p_count} Programas | {s_count} Samples")
    conn.commit()

    # 3. Escanear Samples de Audio
    print("\n🔊 3. Escaneando y clasificando muestras de audio...")
    AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac"}
    batch = []
    total_samples = 0
    total_bytes = 0
    
    for r, dirs, files in os.walk(root_path):
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
                
                stype = classify_sound_type(f, r)
                bpm = extract_bpm(f)
                btier = get_bpm_tier(bpm)
                key, camelot = extract_key(f)
                energy = estimate_energy(stype, btier, macro, f)
                
                batch.append((f, stype, macro, sub, bpm, btier, key, camelot, energy, ext, sz_mb, fp, os.path.relpath(fp, root_path)))
                if len(batch) >= 1500:
                    cur.executemany("""
                    INSERT INTO samples (filename, sound_type, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, extension, size_mb, full_path, rel_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    conn.commit()
                    batch = []
                    sys.stdout.write(f"\r  Muestras indexadas: {total_samples:,}...")
                    sys.stdout.flush()

    if batch:
        cur.executemany("""
        INSERT INTO samples (filename, sound_type, macro_category, sub_pack, bpm, bpm_tier, musical_key, camelot, energy_level, extension, size_mb, full_path, rel_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        conn.commit()
    print(f"\n✔ Total muestras de audio: {total_samples:,} ({total_bytes / (1024**3):.2f} GB)")

    # 4. Generar CSV y JSON
    print("\n📊 4. Generando archivos de exportación...")
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
    print("\n🌐 5. Generando Catálogo Web HTML5 interactivo...")
    cur.execute("""
    SELECT filename, sound_type, macro_category, sub_pack, COALESCE(bpm, 0), COALESCE(musical_key, '-'), COALESCE(camelot, '-'), energy_level, size_mb, rel_path
    FROM samples
    ORDER BY RANDOM()
    LIMIT 15000
    """)
    catalog_records = cur.fetchall()
    records_json = json.dumps(catalog_records, ensure_ascii=False)
    metadata_json = json.dumps(json_payload, ensure_ascii=False)

    # Leer catalogo_universal.html como base
    universal_template_path = os.path.join(os.path.dirname(__file__), "catalogo_universal.html")
    if os.path.exists(universal_template_path):
        with open(universal_template_path, 'r', encoding='utf-8') as f:
            html_code = f.read()
        # Inyectar datos completos
        inject_script = f"<script>\nconst SAMPLES = {records_json};\nconst METADATA = {metadata_json};\n</script>\n"
        html_code = html_code.replace("<!-- DATA_PLACEHOLDER -->", inject_script)
    else:
        # Fallback inline minimal catalog
        html_code = f"<html><body><h1>MPC Sample Catalog</h1><script>const SAMPLES={records_json}; const METADATA={metadata_json};</script></body></html>"

    with open(html_root_path, 'w', encoding='utf-8') as f:
        f.write(html_code)
    with open(html_sqlite_path, 'w', encoding='utf-8') as f:
        f.write(html_code)

    print(f"✔ Catálogo en Raíz: {html_root_path}")
    print(f"✔ Catálogo en Carpeta SQLite: {html_sqlite_path}")
    print(f"✔ Base de Datos SQLite: {db_path}")
    print("\n🎉 Indexación completada con éxito. Ejecuta ./install.sh para explorar tu colección.")
    conn.close()

if __name__ == "__main__":
    main()
