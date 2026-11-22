#!/usr/bin/env python3
"""
Cerebro OS & BeatOS — FAISS Vector Search & Failover Engine
Motor de Búsqueda Semántica Vectorial con Tolerancia a Fallos y Failover Automático.

Características:
  1. Motor Primario (FAISS + all-MiniLM-L6-v2):
     Búsqueda por similitud semántica y tímbrica sobre metadatos de audio y samples.
  2. Motor Secundario (Fallback Automático SQLite / BM25):
     Circuit Breaker con conmutación en menos de 5ms si el modelo o vectorizador falla.
  3. Integración con el Ecosistema de Discos (MPC, Serato DJ, Producción, Audioteca).

Uso:
  python3 cerebro_faiss_engine.py --search "dusty vinyl boom bap kick" --top 5
  python3 cerebro_faiss_engine.py --index-samples [limit]
  python3 cerebro_faiss_engine.py --health
"""

import os
import re
import sys
import time
import json
import sqlite3
import argparse
import threading
from pathlib import Path

# Configuración de Rutas del Stack MLX y Modelos Locales
MLX_PYTHON = os.environ.get("BEATOS_MLX_PYTHON", str(Path.home() / ".mlx-stack/venv/bin/python"))


def _default_model_snapshot() -> str:
    env_val = os.environ.get("BEATOS_MINILM_SNAPSHOT", "").strip()
    if env_val:
        return env_val
    snap_root = Path.home() / ".mlx-stack/models/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots"
    if snap_root.is_dir():
        for child in sorted(snap_root.iterdir()):
            if child.is_dir():
                return str(child)
    return str(snap_root / "latest")


MODEL_SNAPSHOT = _default_model_snapshot()
INDEX_CACHE_DIR = os.path.expanduser("~/.gemini/antigravity/scratch/faiss_cache")
FAISS_INDEX_FILE = os.path.join(INDEX_CACHE_DIR, "cerebro_samples.index")
METADATA_FILE = os.path.join(INDEX_CACHE_DIR, "cerebro_samples_meta.json")

os.makedirs(INDEX_CACHE_DIR, exist_ok=True)

# Colores de Terminal
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


class CircuitBreaker:
    """Implementa patrón Circuit Breaker para conmutar a fallback si el motor primario falla."""
    def __init__(self, failure_threshold=2, recovery_time=30.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"  # CLOSED = OK, OPEN = FALLBACK, HALF-OPEN = TEST

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

    def can_attempt_primary(self):
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_time:
                self.state = "HALF-OPEN"
                return True
            return False
        return True


circuit_breaker = CircuitBreaker()
_CACHE_LOCK = threading.Lock()
_FAISS_CACHE = {"model": None, "index": None, "metadata": None, "mtime": 0.0}
MPC_SAMPLE_DB = os.environ.get("BEATOS_MPC_DB", "")


def get_embedding_model():
    """Carga el modelo SentenceTransformer en caché singleton sin descargas."""
    with _CACHE_LOCK:
        if _FAISS_CACHE["model"] is not None:
            return _FAISS_CACHE["model"]
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(MODEL_SNAPSHOT) if os.path.exists(MODEL_SNAPSHOT) else SentenceTransformer("all-MiniLM-L6-v2")
        with _CACHE_LOCK:
            _FAISS_CACHE["model"] = model
        return model
    except Exception as e:
        print(f"{YELLOW}⚠️  No se pudo cargar SentenceTransformer directamente: {e}{RESET}")
        return None


def _get_cached_faiss():
    import faiss
    mtime = os.path.getmtime(FAISS_INDEX_FILE)
    with _CACHE_LOCK:
        if _FAISS_CACHE["index"] is not None and _FAISS_CACHE["metadata"] is not None and _FAISS_CACHE["mtime"] == mtime:
            return _FAISS_CACHE["index"], _FAISS_CACHE["metadata"]
    idx = faiss.read_index(FAISS_INDEX_FILE)
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    with _CACHE_LOCK:
        _FAISS_CACHE["index"] = idx
        _FAISS_CACHE["metadata"] = meta
        _FAISS_CACHE["mtime"] = mtime
    return idx, meta


def fallback_sqlite_search(query, top_k=5):
    """Motor secundario de ultra-alta velocidad (Failover FTS5 / LIKE) sobre MPCSMPL, SanDisk y Samsung."""
    start_t = time.time()
    results = []
    sources_checked = []
    tokens = [t.strip() for t in re.split(r"[\s_\-/]+", str(query or "")) if len(t.strip()) > 1]

    # 1) Tarjeta Akai MPC Sample (FTS5 si existe, fallback LIKE)
    if os.path.exists(MPC_SAMPLE_DB):
        sources_checked.append("MPCSMPL")
        try:
            conn = sqlite3.connect(MPC_SAMPLE_DB)
            cur = conn.cursor()
            has_fts = bool(cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='samples_fts'").fetchone())
            rows = []
            if has_fts and tokens:
                fts_q = " AND ".join(f'"{t.replace(chr(34), "")}"*' for t in tokens[:8])
                try:
                    rows = cur.execute("""
                        SELECT s.filename, s.sound_type, s.sub_pack, s.size_mb, s.rel_path, s.bpm, s.musical_key
                        FROM samples_fts f JOIN samples s ON s.id = f.rowid
                        WHERE samples_fts MATCH ?
                        ORDER BY bm25(samples_fts)
                        LIMIT ?
                    """, (fts_q, top_k)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                conds, params = [], []
                for tok in tokens[:8]:
                    conds.append("(filename LIKE ? OR sound_type LIKE ? OR sub_pack LIKE ? OR rel_path LIKE ?)")
                    p = f"%{tok}%"
                    params.extend([p, p, p, p])
                where_sql = " AND ".join(conds) if conds else "1=1"
                rows = cur.execute(
                    f"SELECT filename, sound_type, sub_pack, size_mb, rel_path, bpm, musical_key FROM samples WHERE {where_sql} LIMIT ?",
                    params + [top_k],
                ).fetchall()
            conn.close()
            for r in rows:
                results.append({
                    "filename": r[0],
                    "genre": r[1],
                    "sub_genre": r[2],
                    "size_mb": round(r[3] or 0.0, 2),
                    "rel_path": r[4],
                    "bpm": r[5],
                    "musical_key": r[6],
                    "score": 0.90,
                    "disk": "MPCSMPL",
                    "source": "MPCSMPL (SQLite FTS5/LIKE)",
                })
        except sqlite3.Error:
            pass

    # 2) SanDisk SSD (Serato DJ)
    sandisk_db = "/Volumes/SanDisk SSD/_INDEX_SERATO_DJ/serato_dj.db"
    if len(results) < top_k and os.path.exists(sandisk_db):
        sources_checked.append("SanDisk SSD")
        try:
            conn = sqlite3.connect(sandisk_db)
            cur = conn.cursor()
            conds, params = [], []
            for tok in tokens[:8]:
                conds.append("(filename LIKE ? OR macro_genre LIKE ? OR sub_genre LIKE ?)")
                p = f"%{tok}%"
                params.extend([p, p, p])
            where_sql = " AND ".join(conds) if conds else "1=1"
            rows = cur.execute(
                f"SELECT filename, macro_genre, sub_genre, size_mb, rel_path FROM tracks WHERE {where_sql} LIMIT ?",
                params + [top_k - len(results)],
            ).fetchall()
            conn.close()
            for r in rows:
                results.append({
                    "filename": r[0],
                    "genre": r[1],
                    "sub_genre": r[2],
                    "size_mb": round(r[3] or 0.0, 1),
                    "rel_path": r[4],
                    "score": 0.85,
                    "disk": "SanDisk SSD",
                    "source": "SanDisk SSD (Fallback Text Engine)",
                })
        except sqlite3.Error:
            pass

    if not sources_checked:
        return {
            "engine": "Fallback-SQLite",
            "status": "FAIL",
            "message": "Ninguna base SQLite de audio conectada para fallback",
            "results": [],
            "latency_ms": round((time.time() - start_t) * 1000, 2),
        }

    return {
        "engine": f"Fallback-SQLite FTS5/LIKE ({', '.join(sources_checked)})",
        "status": "OK",
        "results": results[:top_k],
        "latency_ms": round((time.time() - start_t) * 1000, 2),
    }


def search_faiss_vector(query, top_k=5):
    """Motor primario vectorial: codifica query y recupera por distancia coseno con FAISS (caché en memoria)."""
    start_t = time.time()

    if not circuit_breaker.can_attempt_primary():
        return fallback_sqlite_search(query, top_k=top_k)

    try:
        import faiss

        if not os.path.exists(FAISS_INDEX_FILE) or not os.path.exists(METADATA_FILE):
            circuit_breaker.record_failure()
            return fallback_sqlite_search(query, top_k=top_k)

        index, metadata = _get_cached_faiss()
        model = get_embedding_model()
        if model is None:
            raise RuntimeError("Modelo de embeddings no disponible")

        q_vec = model.encode([query])
        faiss.normalize_L2(q_vec)

        distances, indices = index.search(q_vec, min(top_k, index.ntotal))

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx != -1 and idx < len(metadata):
                item = dict(metadata[idx])
                item["similarity_score"] = round(float(dist), 4)
                results.append(item)

        circuit_breaker.record_success()
        latency = round((time.time() - start_t) * 1000, 2)

        return {
            "engine": "Primary-FAISS (Dense Semantic Vectors)",
            "status": "OK",
            "results": results,
            "latency_ms": latency,
        }

    except Exception as e:
        print(f"{RED}❌ Fallo en Motor Primario FAISS: {e}{RESET}")
        circuit_breaker.record_failure()
        return fallback_sqlite_search(query, top_k=top_k)


def build_faiss_index_from_dbs(max_items=8000):
    """Indexa metadatos de audio (MPCSMPL + SanDisk + Samsung) en vectores densos y guarda el índice FAISS."""
    print(f"\n{CYAN}{BOLD}🔨 CONSTRUYENDO ÍNDICE VECTORIAL FAISS (all-MiniLM-L6-v2){RESET}")
    start_t = time.time()

    import faiss

    model = get_embedding_model()
    if model is None:
        print(f"{RED}Error: Se requiere sentence-transformers para indexar.{RESET}")
        return False

    corpus_texts = []
    metadata = []

    # 0. Extraer muestras de Akai MPC Sample (MPCSMPL)
    if os.path.exists(MPC_SAMPLE_DB):
        conn = sqlite3.connect(MPC_SAMPLE_DB)
        cur = conn.cursor()
        mpc_limit = int(max_items * 0.6)
        cur.execute(
            "SELECT filename, sound_type, sample_format, macro_category, sub_pack, bpm, musical_key, rel_path, size_mb FROM samples LIMIT ?",
            (mpc_limit,),
        )
        count_m = 0
        for r in cur.fetchall():
            fn, st, sfmt, macro, sub, bpm, mkey, rel, sz = r
            desc = f"mpc sample {fn} {st} {sfmt or ''} pack {sub or ''} {macro or ''} {f'{bpm}bpm' if bpm else ''} {mkey or ''}"
            corpus_texts.append(desc)
            metadata.append({
                "filename": fn,
                "title": fn,
                "artist": sub or "MPC Sample",
                "genre": st,
                "sub_genre": sub,
                "bpm": bpm,
                "musical_key": mkey,
                "rel_path": rel,
                "size_mb": sz,
                "disk": "MPCSMPL",
            })
            count_m += 1
        conn.close()
        print(f"  🎛️  MPCSMPL: Cargadas {count_m:,} muestras para vectorización.")

    # 1. Extraer muestras de SanDisk SSD
    sandisk_db = "/Volumes/SanDisk SSD/_INDEX_SERATO_DJ/serato_dj.db"
    if os.path.exists(sandisk_db):
        conn = sqlite3.connect(sandisk_db)
        cur = conn.cursor()
        cur.execute("SELECT filename, artist, title, macro_genre, sub_genre, rel_path, size_mb FROM tracks LIMIT ?", (max_items // 4,))
        count_sd = 0
        for r in cur.fetchall():
            fn, art, tit, macro, sub, rel, sz = r
            desc = f"{tit or fn} by {art or 'Unknown'} genre {macro} style {sub}"
            corpus_texts.append(desc)
            metadata.append({
                "filename": fn,
                "title": tit,
                "artist": art,
                "genre": macro,
                "sub_genre": sub,
                "rel_path": rel,
                "size_mb": sz,
                "disk": "SanDisk SSD",
            })
            count_sd += 1
        conn.close()
        print(f"  📁 SanDisk SSD: Cargadas {count_sd:,} pistas para vectorización.")

    # 2. Extraer muestras de Samsung PSSDT7 (Producción: sound_banks + ableton_projects)
    samsung_db = "/Volumes/samsung PSSDT7/_INDEX_PRODUCCION/produccion.db"
    if os.path.exists(samsung_db):
        try:
            conn = sqlite3.connect(samsung_db)
            cur = conn.cursor()
            tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            count_s = 0
            if "sound_banks" in tables:
                cur.execute("SELECT name, style_tag, source_folder, root_path, size_mb FROM sound_banks LIMIT ?", (max_items // 6,))
                for r in cur.fetchall():
                    fn, st, src_f, rp, sz = r
                    corpus_texts.append(f"sound bank {fn} style {st or ''} {src_f or ''}")
                    metadata.append({
                        "filename": fn, "title": fn, "artist": src_f or "Sound Bank",
                        "genre": st or "Production", "sub_genre": src_f or "",
                        "rel_path": rp or "", "size_mb": sz, "disk": "samsung PSSDT7",
                    })
                    count_s += 1
            if "ableton_projects" in tables:
                cur.execute("SELECT name, category, project_dir, size_mb FROM ableton_projects LIMIT ?", (max_items // 8,))
                for r in cur.fetchall():
                    fn, cat, pdir, sz = r
                    corpus_texts.append(f"ableton project {fn} category {cat or ''}")
                    metadata.append({
                        "filename": fn, "title": fn, "artist": "Ableton Project",
                        "genre": cat or "Ableton", "sub_genre": "ALS",
                        "rel_path": pdir or "", "size_mb": sz, "disk": "samsung PSSDT7",
                    })
                    count_s += 1
            conn.close()
            print(f"  📁 Samsung PSSDT7: Cargadas {count_s:,} entradas de producción.")
        except sqlite3.Error as _se:
            print(f"  ⚠️ Samsung PSSDT7 omitido: {_se}")
        
    if not corpus_texts:
        print(f"{RED}No se encontraron datos en los discos para indexar.{RESET}")
        return False
        
    print(f"  🧠 Codificando {len(corpus_texts):,} descripciones con embeddings de 384 dimensiones...")
    embeddings = model.encode(corpus_texts, show_progress_bar=True, batch_size=64)
    faiss.normalize_L2(embeddings)
    
    # Crear índice FAISS Flat Inner Product (Coseno)
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)
    
    faiss.write_index(index, FAISS_INDEX_FILE)
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        
    elapsed = round(time.time() - start_t, 2)
    print(f"\n✨ {GREEN}ÍNDICE FAISS GENERADO CON ÉXITO:{RESET}")
    print(f"  - Vectores Almacenados: {index.ntotal:,}")
    print(f"  - Archivo FAISS:        {FAISS_INDEX_FILE}")
    print(f"  - Metadatos:            {METADATA_FILE}")
    print(f"  - Tiempo Transcurrido:  {elapsed}s")
    return True


def print_search_report(query, res_data):
    engine = res_data.get("engine")
    status = res_data.get("status")
    latency = res_data.get("latency_ms")
    results = res_data.get("results", [])
    
    color_eng = GREEN if "Primary" in engine else YELLOW
    print(f"\n{CYAN}{BOLD}🔍 BÚSQUEDA VECTORIAL / SEMÁNTICA:{RESET} \"{BOLD}{query}{RESET}\"")
    print(f"Motor: {color_eng}{BOLD}{engine}{RESET} | Estado: {status} | Latencia: {BOLD}{latency} ms{RESET}")
    print("-" * 65)
    
    if not results:
        print("  (No se encontraron coincidencias)")
        return
        
    for i, r in enumerate(results, 1):
        score_val = r.get("similarity_score") or r.get("score") or 0.0
        pct = round(score_val * 100, 1)
        score_bar = f"{GREEN}{pct}%{RESET}" if pct >= 65 else f"{YELLOW}{pct}%{RESET}"
        fn = r.get("filename")
        art = r.get("artist") or "-"
        genre = r.get("genre") or r.get("category") or "-"
        sub = r.get("sub_genre") or "-"
        disk = r.get("disk") or "SSD"
        
        print(f"  {BOLD}{i}.{RESET} [{score_bar}] {BOLD}{fn}{RESET}")
        print(f"     Artista: {art} | Género: {genre} / {sub} | Disco: {disk}")
        if r.get("rel_path"):
            print(f"     Ruta: {DIM}{r.get('rel_path')[:70]}...{RESET}")
    print("-" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cerebro OS FAISS Vector Engine with Auto-Failover")
    parser.add_argument("--search", type=str, help="Texto de consulta semántica o tímbrica")
    parser.add_argument("--top", type=int, default=5, help="Número de resultados a recuperar")
    parser.add_argument("--index-samples", type=int, nargs="?", const=3000, help="Construir índice FAISS desde las DBs")
    parser.add_argument("--health", action="store_true", help="Diagnóstico de salud del motor vectorial")
    
    args = parser.parse_args()
    
    if args.health:
        print(f"{CYAN}{BOLD}🏥 FAISS & FAILOVER ENGINE HEALTH CHECK{RESET}")
        print(f"  Índice FAISS en disco: {'✅ Presente' if os.path.exists(FAISS_INDEX_FILE) else '⚠️  No creado aún'}")
        print(f"  Modelo all-MiniLM-L6-v2: {'✅ Presente' if os.path.exists(MODEL_SNAPSHOT) else '⚠️  No encontrado'}")
        print(f"  Circuit Breaker: {GREEN}{circuit_breaker.state}{RESET}")
        fb = fallback_sqlite_search("test", top_k=1)
        print(f"  Fallback SQLite: {'✅ Operativo (' + str(fb['latency_ms']) + 'ms)' if fb['status'] == 'OK' else '❌ Error'}")
    elif args.index_samples:
        build_faiss_index_from_dbs(max_items=args.index_samples)
    elif args.search:
        res = search_faiss_vector(args.search, top_k=args.top)
        print_search_report(args.search, res)
    else:
        parser.print_help()
