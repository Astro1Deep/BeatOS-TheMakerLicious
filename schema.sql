-- ==============================================================================
-- Schema SQL Oficial: Akai MPC Sample Database Toolkit
-- Compatible con: SQLite 3.x | Akai MPC Live, One, X, Key, Studio, Renaissance
-- ==============================================================================

PRAGMA foreign_keys = ON;

-- 1. Categorías estándar de sonido
CREATE TABLE IF NOT EXISTS sound_categories (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT
);

INSERT OR IGNORE INTO sound_categories (code, name, icon) VALUES
('KICK', 'Kicks & Bombos', '🥁'),
('SNARE', 'Snares & Tarolas', '💥'),
('CLAP', 'Claps & Snaps', '👏'),
('HIHAT', 'Hi-Hats (Cerrado/Abierto)', '✨'),
('CYMBAL', 'Címbalos, Rides & Crashes', '💿'),
('PERCUSSION', 'Percusión & Foley', '🪘'),
('BASS_808', '808s, Sub & Bajos', '🔊'),
('KEYS_SYNTH', 'Pianos, Sintetizadores & Stabs', '🎹'),
('MELODIC_LOOP', 'Loops Melódicos & Chops', '🎸'),
('DRUM_LOOP', 'Breakbeats & Drum Loops', '🔁'),
('VOCAL', 'Voces, Acapellas & Chants', '🎤'),
('FX', 'Efectos & Texturas Sonoras', '⚡');

-- 2. Expansiones Oficiales y de Terceros
CREATE TABLE IF NOT EXISTS expansions (
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

-- 3. Proyectos MPC Standalone (.xpj)
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    tempo REAL,
    musical_key TEXT,
    sample_refs_count INTEGER DEFAULT 0,
    missing_samples_count INTEGER DEFAULT 0,
    status TEXT, -- 'HEALTHY', 'MISSING_SAMPLES'
    size_kb REAL DEFAULT 0.0
);

-- 4. Soundbanks y Carpetas de Colección
CREATE TABLE IF NOT EXISTS packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    macro_category TEXT,
    samples_count INTEGER DEFAULT 0,
    size_mb REAL DEFAULT 0.0,
    full_path TEXT
);

-- 5. Tabla Principal de Muestras de Audio (Samples)
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
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
    rel_path TEXT,
    FOREIGN KEY(sound_type) REFERENCES sound_categories(code)
);

-- Índices de Alto Rendimiento para Búsqueda Instantánea
CREATE INDEX IF NOT EXISTS idx_sample_name ON samples(filename);
CREATE INDEX IF NOT EXISTS idx_sample_type ON samples(sound_type);
CREATE INDEX IF NOT EXISTS idx_sample_macro ON samples(macro_category);
CREATE INDEX IF NOT EXISTS idx_sample_bpm ON samples(bpm);
CREATE INDEX IF NOT EXISTS idx_sample_key ON samples(musical_key);
CREATE INDEX IF NOT EXISTS idx_sample_camelot ON samples(camelot);
CREATE INDEX IF NOT EXISTS idx_sample_energy ON samples(energy_level);
