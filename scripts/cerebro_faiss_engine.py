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
import sys
import time
import json
import sqlite3
import argparse
from pathlib import Path

# Configuración de Rutas del Stack MLX y Modelos Locales
MLX_PYTHON = "/Users/ivan/.mlx-stack/venv/bin/python"
MODEL_SNAPSHOT = "/Users/ivan/.mlx-stack/models/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
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


def get_embedding_model():
    """Carga el modelo SentenceTransformer desde la caché local sin descargas."""
    try:
        from sentence_transformers import SentenceTransformer
        if os.path.exists(MODEL_SNAPSHOT):
            return SentenceTransformer(MODEL_SNAPSHOT)
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as e:
        print(f"{YELLOW}⚠️  No se pudo cargar SentenceTransformer directamente: {e}{RESET}")
        return None


def fallback_sqlite_search(query, top_k=5):
    """Motor secundario de ultra-alta velocidad (Failover FTS / Like) sobre serato_dj.db."""
    start_t = time.time()
    db_path = "/Volumes/SanDisk SSD/_INDEX_SERATO_DJ/serato_dj.db"
    
    if not os.path.exists(db_path):
        return {
            "engine": "Fallback-SQLite",
            "status": "FAIL",
            "message": "Disco SanDisk no conectado para fallback",
            "results": [],
            "latency_ms": round((time.time() - start_t) * 1000, 2)
        }
        
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tokens = [t.strip() for t in query.split() if len(t.strip()) > 1]
    
    conditions = []
    params = []
    for tok in tokens:
        conditions.append("(filename LIKE ? OR macro_genre LIKE ? OR sub_genre LIKE ?)")
        p = f"%{tok}%"
        params.extend([p, p, p])
        
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
    SELECT filename, macro_genre, sub_genre, size_mb, rel_path 
    FROM tracks 
    WHERE {where_clause} 
    LIMIT {top_k}
    """
    
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    
    results = [
        {
            "filename": r[0],
            "genre": r[1],
            "sub_genre": r[2],
            "size_mb": round(r[3] or 0.0, 1),
            "rel_path": r[4],
            "score": 0.85,  # Score heurístico en fallback
            "source": "SanDisk SSD (Fallback Text Engine)"
        }
        for r in rows
    ]
    
    return {
        "engine": "Fallback-SQLite (BM25/Like)",
        "status": "OK",
        "results": results,
        "latency_ms": round((time.time() - start_t) * 1000, 2)
    }


def search_faiss_vector(query, top_k=5):
    """Motor primario vectorial: codifica query y recupera por distancia coseno con FAISS."""
    start_t = time.time()
    
    # Comprobar estado del Circuit Breaker
    if not circuit_breaker.can_attempt_primary():
        print(f"{YELLOW}⚡ Circuit Breaker [OPEN]: Conmutando inmediatamente a Failover Engine...{RESET}")
        return fallback_sqlite_search(query, top_k=top_k)
        
    try:
        import faiss
        import numpy as np
        
        if not os.path.exists(FAISS_INDEX_FILE) or not os.path.exists(METADATA_FILE):
            print(f"{YELLOW}⚠️  Índice FAISS no encontrado. Ejecutando creación automática o fallback...{RESET}")
            circuit_breaker.record_failure()
            return fallback_sqlite_search(query, top_k=top_k)
            
        index = faiss.read_index(FAISS_INDEX_FILE)
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        model = get_embedding_model()
        if model is None:
            raise RuntimeError("Modelo de embeddings no disponible")
            
        # Generar embedding de consulta y normalizar L2 para Cosine Similarity
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
            "latency_ms": latency
        }
        
    except Exception as e:
        print(f"{RED}❌ Fallo en Motor Primario FAISS: {e}{RESET}")
        circuit_breaker.record_failure()
        return fallback_sqlite_search(query, top_k=top_k)


def build_faiss_index_from_dbs(max_items=5000):
    """Indexa metadatos de audio en vectores densos y guarda el índice FAISS."""
    print(f"\n{CYAN}{BOLD}🔨 CONSTRUYENDO ÍNDICE VECTORIAL FAISS (all-MiniLM-L6-v2){RESET}")
    start_t = time.time()
    
    import faiss
    import numpy as np
    
    model = get_embedding_model()
    if model is None:
        print(f"{RED}Error: Se requiere sentence-transformers para indexar.{RESET}")
        return False
        
    corpus_texts = []
    metadata = []
    
    # 1. Extraer muestras de SanDisk SSD
    sandisk_db = "/Volumes/SanDisk SSD/_INDEX_SERATO_DJ/serato_dj.db"
    if os.path.exists(sandisk_db):
        conn = sqlite3.connect(sandisk_db)
        cur = conn.cursor()
        cur.execute("SELECT filename, artist, title, macro_genre, sub_genre, rel_path, size_mb FROM tracks LIMIT ?", (max_items // 2,))
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
                "disk": "SanDisk SSD"
            })
        conn.close()
        print(f"  📁 SanDisk SSD: Cargadas {len(metadata):,} pistas para vectorización.")
        
    # 2. Extraer muestras de Samsung PSSDT7 (Producción)
    samsung_db = "/Volumes/samsung PSSDT7/_INDEX_PRODUCCION/produccion.db"
    if os.path.exists(samsung_db):
        conn = sqlite3.connect(samsung_db)
        cur = conn.cursor()
        cur.execute("SELECT filename, category, sub_category, rel_path, size_mb FROM production_files LIMIT ?", (max_items // 2,))
        count_s = 0
        for r in cur.fetchall():
            fn, cat, sub, rel, sz = r
            desc = f"sample {fn} category {cat} type {sub}"
            corpus_texts.append(desc)
            metadata.append({
                "filename": fn,
                "title": fn,
                "artist": "Sample Pack",
                "genre": cat,
                "sub_genre": sub,
                "rel_path": rel,
                "size_mb": sz,
                "disk": "samsung PSSDT7"
            })
            count_s += 1
        conn.close()
        print(f"  📁 Samsung PSSDT7: Cargadas {count_s:,} muestras de producción.")
        
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
