# 📊 7. Consultas Avanzadas SQLite

La base de datos `mpc_sample.db` es un archivo relacional estándar de **SQLite 3**. Esto significa que puedes abrirlo con cualquier cliente gráfico (como *DB Browser for SQLite*, *TablePlus* o *DBeaver*) o lanzar consultas analíticas desde la terminal.

---

## 🏛️ Esquema de Tablas (`schema.sql`)

La base de datos cuenta con 5 tablas relacionales optimizadas con índices por tipo de sonido, tempo, clave y energía:

```sql
-- 1. Tabla de Samples Individuales
CREATE TABLE samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    sample_format TEXT DEFAULT 'ONE_SHOT',
    sound_type TEXT NOT NULL,
    macro_category TEXT,
    sub_pack TEXT,
    bpm INTEGER,
    bpm_tier TEXT,
    musical_key TEXT,
    camelot TEXT,
    energy_level TEXT,
    extension TEXT,
    size_mb REAL DEFAULT 0.0,
    full_path TEXT,
    rel_path TEXT
);

-- 2. Tabla de Proyectos Standalone (.xpj)
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    tempo REAL,
    musical_key TEXT,
    sample_refs_count INTEGER DEFAULT 0,
    missing_samples_count INTEGER DEFAULT 0,
    status TEXT,
    size_kb REAL DEFAULT 0.0
);

-- 3. Tabla de Expansiones Oficiales
CREATE TABLE expansions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    identifier TEXT,
    manufacturer TEXT,
    exp_type TEXT,
    version TEXT,
    cover_image TEXT,
    programs_count INTEGER DEFAULT 0,
    samples_count INTEGER DEFAULT 0,
    size_mb REAL DEFAULT 0.0,
    full_path TEXT
);
```

---

## 💻 Consultas SQL Útiles para Productores

A continuación tienes una selección de consultas SQL que puedes ejecutar con la herramienta de línea de comandos `sqlite3`:

### 1. Encontrar todos los 808s afinados en Do Menor (Cm / 5A)
```sql
SELECT filename, sub_pack, camelot, size_mb
FROM samples
WHERE sound_type = 'BASS_808' AND musical_key = 'Cm'
ORDER BY size_mb ASC;
```

### 2. Buscar Breakbeats clásicos de Boom Bap (88 a 94 BPM)
```sql
SELECT filename, bpm, macro_category, rel_path
FROM samples
WHERE sound_type = 'DRUM_LOOP' AND bpm BETWEEN 88 AND 94
ORDER BY bpm ASC;
```

### 3. Ver qué proyectos MPC tienen muestras faltantes (`ATTENTION`)
```sql
SELECT name, tempo, missing_samples_count, file_path
FROM projects
WHERE status = 'ATTENTION';
```

### 4. Ranking de las 10 carpetas con mayor número de samples
```sql
SELECT sub_pack, COUNT(*) AS total_samples, ROUND(SUM(size_mb), 2) AS total_mb
FROM samples
GROUP BY sub_pack
ORDER BY total_samples DESC
LIMIT 10;
```

### 5. Distribución porcentual de tipos de sonido en la colección
```sql
SELECT sound_type, COUNT(*) AS cantidad,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM samples), 1) AS porcentaje
FROM samples
GROUP BY sound_type
ORDER BY cantidad DESC;
```

---

## 🐍 Scripting en Python con la Base de Datos

Puedes integrar `mpc_sample.db` en tus propios scripts de Python con la biblioteca estándar:

```python
import sqlite3

conn = sqlite3.connect("file:BeatOS/data/mpc_sample.db?mode=ro", uri=True)
cur = conn.cursor()

# Obtener 5 bombos aleatorios para crear un kit
cur.execute("SELECT filename, rel_path FROM samples WHERE sound_type='KICK' ORDER BY RANDOM() LIMIT 5;")
for row in cur.fetchall():
    print(f"Bombo: {row[0]} -> {row[1]}")

conn.close()
```
