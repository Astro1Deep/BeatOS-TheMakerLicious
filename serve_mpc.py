#!/usr/bin/env python3
"""
Akai MPC Sample Finder & Hardware Multi-Sampler Audio Streamer (v3.6)
Ubicación: serve_mpc.py
Repositorio: Astro1Deep/mpc-sample-database

Servidor HTTP de alto rendimiento con:
1. RFC 7233 Range Requests (HTTP 206 Partial Content) para streaming fluido en Safari, Chrome, Firefox y WebKit.
2. Soporte completo de CORS para Web Audio API y controladores hardware.
3. API REST para el Ecosistema Multi-Sampler:
   - GET  /api/status: Estado del sistema, memoria, espacio y tarjeta montada.
   - GET  /api/task_status: Estado de tareas de reindexación en segundo plano.
   - GET  /api/po33_backups: Inspección de audio de respaldos; no valida sus datos.
   - GET  /api/po33_backup_audio: Descarga de audio de respaldo de PO-33.
   - GET  /api/scales: Lista de escalas musicales y notas para creación melódica.
   - POST /api/create_kit: Síntesis y exportación universal de kits para Akai MPC (.xpm/.xpj), NI Maschine (WAV + mapa JSON), Roland SP-404MK2 y PO-33 Drum Reel.
   - POST /api/create_chromatic_kit: Generación de instrumento melódico afinado en escala a partir de un sample one-shot.
   - POST /api/load_project: Carga de proyectos MPC (.xpj) en el Beatmaker Rack.
   - POST /api/reindex: Re-indexación autónoma en segundo plano.
   - POST /api/clean_metadata: Purga de residuos AppleDouble (._*) y .DS_Store.
   - POST /api/sync_dashboard: Sincronización con el Master Dashboard de 4 Pilares.
"""

from __future__ import annotations

import argparse
import datetime
import contextlib
import hashlib
import json
import mimetypes
import os
import re
import shutil
from typing import Any
import socket
import sqlite3
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer
from pathlib import Path
from beatos_paths import CATALOG_REL, MASTER_DASHBOARD_REL, config_dir, database_path, default_library_root
from beatos_i18n import get_request_language, localize_api_payload, translate_text

mimetypes.init()
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/aiff", ".aif")
mimetypes.add_type("audio/aiff", ".aiff")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

# Estado global de tareas en segundo plano
TASK_LOCK = threading.Lock()
PO_BACKUP_LOCK = threading.Lock()
PO_BACKUP_CACHE = {}
TASK_STATE = {
    "running": False,
    "task_name": "",
    "logs": [],
    "success": None,
    "started_at": 0,
    "finished_at": 0,
}

_LOADED_BUILDER_MODULE = {}

def get_hardware_kit_builder(root_dir: str):
    """Carga de forma dinámica y tolerante a fallos el módulo hardware_kit_builder con caché."""
    global _LOADED_BUILDER_MODULE
    candidates = [os.path.join(os.path.dirname(__file__), "hardware_kit_builder.py"),
                  os.path.join(root_dir, "BeatOS", "hardware_kit_builder.py")]
    for cand in candidates:
        if os.path.isfile(cand):
            try:
                mtime = os.path.getmtime(cand)
                cached = _LOADED_BUILDER_MODULE.get(cand)
                if cached and cached.get("mtime") == mtime:
                    return cached.get("mod")
                import importlib.util
                spec = importlib.util.spec_from_file_location("hardware_kit_builder", cand)
                if spec and spec.loader:
                    kit_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(kit_mod)
                    _LOADED_BUILDER_MODULE[cand] = {"mod": kit_mod, "mtime": mtime}
                    return kit_mod
            except Exception as e:
                sys.stderr.write(f"⚠️ Error cargando {cand}: {e}\n")
    return None

def run_reindex_thread(root_dir: str):
    global TASK_STATE
    TASK_STATE["running"] = True
    TASK_STATE["task_name"] = "reindex"
    TASK_STATE["logs"] = ["🚀 Iniciando reindexación de MPC Sample Database..."]
    TASK_STATE["started_at"] = time.time()
    TASK_STATE["finished_at"] = 0
    TASK_STATE["success"] = None

    candidates = [os.path.join(os.path.dirname(__file__), "index_mpc_library.py"),
                  os.path.join(root_dir, "BeatOS", "index_mpc_library.py")]
    script_path = None
    for cand in candidates:
        if os.path.isfile(cand):
            script_path = cand
            break

    if not script_path:
        TASK_STATE["success"] = False
        TASK_STATE["logs"].append("❌ No se encontró el script de indexación.")
        TASK_STATE["running"] = False
        TASK_STATE["finished_at"] = time.time()
        return

    try:
        reindex_env = os.environ.copy()
        reindex_env["PYTHONIOENCODING"] = "utf-8"
        reindex_env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-B", script_path, "--path", root_dir],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=root_dir,
            env=reindex_env,
        )
        if proc.stdout:
            for line in proc.stdout:
                clean_l = line.rstrip()
                if clean_l:
                    TASK_STATE["logs"].append(clean_l)
                    if len(TASK_STATE["logs"]) > 300:
                        TASK_STATE["logs"].pop(1)
        proc.wait()

        TASK_STATE["success"] = (proc.returncode == 0)
        if proc.returncode == 0:
            _DISCOVERED_LIBS_CACHE["timestamp"] = 0.0
            kit_mod = get_hardware_kit_builder(root_dir)
            if kit_mod and hasattr(kit_mod, "clear_expansion_kits_cache"):
                kit_mod.clear_expansion_kits_cache()
        TASK_STATE["logs"].append(
            "✔ Proceso finalizado correctamente."
            if proc.returncode == 0
            else "❌ Error en el proceso de reindexación."
        )
    except Exception as e:
        TASK_STATE["success"] = False
        TASK_STATE["logs"].append(f"❌ Excepción durante ejecución: {str(e)}")
    finally:
        TASK_STATE["running"] = False
        TASK_STATE["finished_at"] = time.time()

def run_clean_metadata(root_dir: str):
    logs = []
    excluded_dirs = {
        ".Spotlight-V100",
        ".fseventsd",
        ".Trashes",
        ".TemporaryItems",
        ".DocumentRevisions-V100",
    }
    try:
        if sys.platform == "darwin":
            subprocess.run(["dot_clean", "-m", root_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            logs.append("✔ dot_clean ejecutado en el volumen.")

        deleted_count = 0
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
            for f in filenames:
                if f.startswith("._") or f == ".DS_Store":
                    try:
                        os.remove(os.path.join(dirpath, f))
                        deleted_count += 1
                    except Exception:
                        pass
        logs.append(f"✔ Purgados {deleted_count} archivos ocultos de metadatos AppleDouble (._* y .DS_Store).")
        return {"success": True, "logs": logs, "deleted_count": deleted_count}
    except Exception as e:
        return {"success": False, "error": str(e)}

def run_sync_dashboard():
    candidates = [
        os.path.expanduser("~/.gemini/antigravity/scratch/sync_master_dashboard.py"),
        os.path.expanduser("~/Music/Audiotheque_Index/sync_master_dashboard.py"),
    ]
    for dashboard_script in candidates:
        if os.path.isfile(dashboard_script):
            try:
                res = subprocess.run([sys.executable, dashboard_script], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)
                return {"success": True, "output": res.stdout}
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": (e.stderr or e.stdout or str(e)).strip()}

    # Respaldo directo en Python si no existe el script externo de Cerebro OS
    source_candidates = [
        Path.home() / "Music" / "Audiotheque_Index" / "master_ecosistema_discos.html",
        Path("/Volumes/Realtek RTL9210B-CG Media/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/samsung PSSDT7/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/SanDisk SSD/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/MPCSMPL/BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/MPC-SAMPL3/BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html"),
    ]
    source_path = next((sc for sc in source_candidates if sc.is_file()), None)
    if not source_path:
        return {"success": False, "error": "Script sync_master_dashboard.py y plantilla MASTER_ECOSISTEMA_DISCOS.html no encontrados."}

    destinations = [
        Path("/Volumes/Realtek RTL9210B-CG Media/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/samsung PSSDT7/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/SanDisk SSD/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/MPCSMPL/BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html"),
        Path("/Volumes/MPC-SAMPL3/BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html"),
        Path.home() / "Music" / "Audiotheque_Index" / "master_ecosistema_discos.html",
    ]
    synced = []
    for dest in destinations:
        if dest.parent.is_dir():
            try:
                if dest.exists() and dest.resolve() == source_path.resolve():
                    continue
                shutil.copy2(str(source_path), str(dest))
                synced.append(str(dest))
            except OSError:
                pass
    return {
        "success": True,
        "output": f"Sincronizado desde {source_path} hacia {len(synced)} destinos.",
    }

def _probe_local_port(port: int, timeout: float = 0.04) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


_DISCOVERED_LIBS_CACHE = {"timestamp": 0.0, "libs": [], "root": ""}


def discover_mounted_audio_libraries(active_root: str = "") -> list[dict]:
    """
    Descubre dinámicamente bibliotecas SQLite de audio en volúmenes montados (/Volumes/*, /media/*, /mnt/*)
    sin depender de nombres de discos personales codificados a fuego.
    """
    now = time.time()
    if _DISCOVERED_LIBS_CACHE["root"] == active_root and (now - _DISCOVERED_LIBS_CACHE["timestamp"]) < 15.0:
        return list(_DISCOVERED_LIBS_CACHE["libs"])

    discovered: list[dict] = []
    seen_dbs: set[str] = set()

    def _inspect_candidate_db(db_file: Path, mount_path: Path, is_active: bool = False):
        try:
            real_db = str(db_file.resolve())
            if real_db in seen_dbs or not db_file.is_file():
                return
            conn = sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            all_tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]
            chosen_table = ""
            sample_count = 0
            for candidate_t in ("samples", "audio_assets", "tracks", "sound_banks", "sp404_hardware") + tuple(all_tables):
                if candidate_t not in all_tables:
                    continue
                cur.execute(f"PRAGMA table_info({candidate_t})")
                cols = {r[1] for r in cur.fetchall()}
                if ("filename" in cols or "name" in cols) and any(k in cols for k in ("rel_path", "relative_path", "full_path", "path", "root_path")):
                    cur.execute(f"SELECT COUNT(*) FROM {candidate_t}")
                    cnt_row = cur.fetchone()
                    cnt = int(cnt_row[0]) if cnt_row else 0
                    if cnt > 0:
                        chosen_table = candidate_t
                        sample_count = cnt
                        break
            conn.close()
            if not chosen_table:
                return
            seen_dbs.add(real_db)
            discovered.append({
                "id": re.sub(r"[^a-z0-9_]+", "_", mount_path.name.lower()).strip("_") or "library",
                "name": mount_path.name,
                "mount_path": str(mount_path.resolve()),
                "db_path": real_db,
                "table_name": chosen_table,
                "sample_count": sample_count,
                "is_active_root": bool(is_active),
            })
        except Exception:
            pass

    if active_root:
        act_p = Path(active_root)
        act_db = Path(database_path(active_root))
        if act_db.is_file():
            _inspect_candidate_db(act_db, act_p, is_active=True)

    # Escanear puntos de montaje estándar multiplataforma (/Volumes en macOS, /media y /mnt en Linux)
    mount_Numeric_roots = [Path("/Volumes"), Path("/media"), Path("/mnt")]
    for m_root in mount_Numeric_roots:
        if not m_root.is_dir():
            continue
        try:
            children = sorted(m_root.iterdir())
        except OSError:
            continue
        for vol in children:
            if not vol.is_dir() or vol.name.startswith("."):
                continue
            is_act = bool(active_root and vol.resolve() == Path(active_root).resolve())
            # 1. Estándar BeatOS: <vol>/BeatOS/data/mpc_sample.db
            b_db = vol / "BeatOS" / "data" / "mpc_sample.db"
            if b_db.is_file():
                _inspect_candidate_db(b_db, vol, is_active=is_act)
            # 2. Índices de audioteca / producción: <vol>/_INDEX_*/*.db
            try:
                for idx_dir in vol.glob("_INDEX_*"):
                    if idx_dir.is_dir():
                        for db_f in idx_dir.glob("*.db"):
                            _inspect_candidate_db(db_f, vol, is_active=is_act)
            except OSError:
                pass
    _DISCOVERED_LIBS_CACHE["timestamp"] = now
    _DISCOVERED_LIBS_CACHE["root"] = active_root
    _DISCOVERED_LIBS_CACHE["libs"] = list(discovered)
    return discovered


def detect_cerebro_os(root_dir: str = "") -> dict:
    """Detecta si Cerebro OS (~/.mlx-stack) está instalado en el sistema anfitrión y sincroniza el puente bidireccional."""
    if os.environ.get("BEATOS_FORCE_HIDE_CEREBRO") == "1":
        return {"installed": False, "venv_ready": False, "mlx_server_online": False, "dashboard_online": False, "capabilities": [], "mounted_libraries": []}
    mlx_root = Path.home() / ".mlx-stack"
    cerebro_dir = mlx_root / "cerebro"
    venv_py = mlx_root / "venv" / "bin" / "python"
    installed = mlx_root.is_dir() and (cerebro_dir.is_dir() or venv_py.is_file())
    venv_ready = venv_py.is_file() and os.access(venv_py, os.X_OK)
    mlx_online = _probe_local_port(8080) if installed else False
    dash_online = _probe_local_port(3050) if installed else False
    mounted_libs = discover_mounted_audio_libraries(root_dir) if installed else []

    if installed and root_dir:
        try:
            bridge_file = mlx_root / "beatos_bridge.json"
            bridge_payload = {
                "schema": "cerebro-beatos-bridge-v2",
                "beatos_active": True,
                "root_dir": str(root_dir),
                "database_path": str(database_path(root_dir)),
                "api_base": "http://127.0.0.1:8888",
                "mounted_libraries": mounted_libs,
                "updated_at": datetime.datetime.now().isoformat(),
                "capabilities": [
                    "mpc_modern_xpj_xpm",
                    "mpc1000_2500_pgm",
                    "mpc2000xl_pgm_dos83",
                    "sp404mk2_sp404a",
                    "ep133_ko2",
                    "po33_modem_crc",
                    "cerebro_acoustic_dsp",
                    "autochop_zero_crossing",
                    "harmonic_808_autotune",
                    "prompt_to_kit",
                    "timbral_similarity",
                    "federated_library_search",
                ],
            }
            bridge_file.write_text(json.dumps(bridge_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    return {
        "installed": bool(installed),
        "venv_ready": bool(venv_ready),
        "mlx_server_online": bool(mlx_online),
        "dashboard_online": bool(dash_online),
        "llm_online": bool(mlx_online),
        "mounted_libraries_count": len(mounted_libs),
        "mounted_libraries": mounted_libs,
        "engine": "Cerebro OS · MLX Acoustic & Genre DSP" if installed else "",
        "capabilities": [
            "acoustic_spectral_dsp",
            "underground_genre_classifier",
            "smart_choke_matrix",
            "po33_crc_modem_decoder",
            "autochop_zero_crossing",
            "harmonic_808_autotune",
            "prompt_to_kit",
            "timbral_similarity",
            "federated_library_search",
        ] if installed else [],
    }


def analyze_rack_with_cerebro(root_dir: str, payload: dict) -> dict:
    """Analiza acústicamente los pads del Rack (PCM ZCR, ratio subgrave, transientes, duración) + heurística underground."""
    import math
    import struct
    import wave

    kit_mod = get_hardware_kit_builder(root_dir)
    kit_name = str(payload.get("kit_name") or payload.get("name") or "Rack Kit").strip()
    current_tempo = float(payload.get("tempo") or 120.0)
    pads_in = payload.get("pads") or []

    pad_reports = []
    text_tokens = [kit_name]
    sub_heavy_count = 0
    open_hat_count = 0
    closed_hat_count = 0

    for item in pads_in:
        if not isinstance(item, dict):
            continue
        p_num = int(item.get("pad") or item.get("pad_number") or 0)
        if not 1 <= p_num <= 16:
            continue
        sname = str(item.get("sample_name") or item.get("sampleName") or "").strip()
        rel_path = str(item.get("rel_path") or item.get("relPath") or "").strip()
        stype = str(item.get("sound_type") or item.get("soundType") or "").strip().upper()
        text_tokens.append(f"{sname} {rel_path}")

        if not stype or stype == "SAMPLE":
            stype = kit_mod.detect_sound_type(sname or rel_path) if kit_mod else "PERCUSSION"

        # Métricas acústicas reales sobre el WAV si está accesible en la biblioteca
        duration_sec = 0.0
        zcr_hz = 0.0
        low_ratio = 0.0
        crest_db = 0.0
        acoustic_role = stype
        resolved_wav: Optional[Path] = None

        if rel_path:
            try:
                wav_path = resolve_library_path(root_dir, rel_path)
                if wav_path.is_file() and wav_path.suffix.lower() == ".wav":
                    resolved_wav = wav_path
                    with wave.open(str(wav_path), "rb") as wf:
                        n_ch = wf.getnchannels()
                        sw = wf.getsampwidth()
                        fr = wf.getframerate() or 44100
                        n_frames = wf.getnframes()
                        duration_sec = round(n_frames / float(fr), 3) if fr else 0.0
                        read_n = min(n_frames, int(fr * 1.5), 66150)
                        raw = wf.readframes(read_n)
                        if sw == 2 and read_n > 32 and n_ch >= 1:
                            total_short = len(raw) // 2
                            samples = struct.unpack(f"<{total_short}h", raw[: total_short * 2])
                            mono = samples[::n_ch] if n_ch > 1 else samples
                            if len(mono) > 16:
                                peak = max(abs(x) for x in mono) or 1
                                sum_sq = sum(float(x) * float(x) for x in mono)
                                rms = math.sqrt(sum_sq / len(mono)) or 1.0
                                crest_db = round(20.0 * math.log10(peak / rms), 1)
                                # Zero-crossing rate (Hz)
                                zc = sum(1 for i in range(1, len(mono)) if (mono[i - 1] >= 0) != (mono[i] >= 0))
                                zcr_hz = round((zc * fr) / (2.0 * len(mono)), 1)
                                # Filtro paso bajo de 1er orden (~180 Hz) para estimar energía subgrave
                                alpha = min(0.95, (2.0 * math.pi * 180.0) / (fr + 2.0 * math.pi * 180.0))
                                lp = 0.0
                                lp_sq = 0.0
                                for x in mono:
                                    lp = lp + alpha * (float(x) - lp)
                                    lp_sq += lp * lp
                                low_ratio = round(lp_sq / sum_sq, 3) if sum_sq > 0 else 0.0
            except Exception:
                pass

        # Refinamiento acústico del rol sonoro
        low_sname = sname.lower()
        is_tom = bool(kit_mod and kit_mod.re.search(r"(?:^|[\s_\-.])(?:tom|flr|floor\s*tom)(?:[\s_\-.0-9]|$)", low_sname))
        if stype in ("BASS_808", "KICK") and low_ratio >= 0.62 and duration_sec >= 0.42:
            acoustic_role = "BASS_808" if ("808" in low_sname or "sub" in low_sname or duration_sec >= 0.65) else "SUB_KICK"
            sub_heavy_count += 1
        elif stype == "HIHAT" or (zcr_hz >= 2600 and low_ratio < 0.15 and stype not in ("CYMBAL", "SNARE", "CLAP")):
            if "open" in low_sname or "oh" in low_sname or duration_sec >= 0.24:
                acoustic_role = "HIHAT_OPEN"
                open_hat_count += 1
            else:
                acoustic_role = "HIHAT_CLOSED"
                closed_hat_count += 1
            stype = "HIHAT"
        elif is_tom:
            acoustic_role = "TOM"

        smart_vol = (
            kit_mod.compute_smart_pad_volume(stype, resolved_wav)
            if kit_mod and hasattr(kit_mod, "compute_smart_pad_volume")
            else {"volume": 0.501187, "gain_db": -6.0, "peak_dbfs": 0.0, "rms_dbfs": -12.0}
        )

        pad_reports.append({
            "pad": p_num,
            "sample_name": sname,
            "rel_path": rel_path,
            "sound_type": stype,
            "acoustic_role": acoustic_role,
            "duration_sec": duration_sec,
            "zcr_hz": zcr_hz,
            "low_energy_ratio": low_ratio,
            "crest_db": crest_db,
            "f0_hz": 0.0,
            "detected_note": "",
            "pitch_class": None,
            "cents_offset": 0,
            "recommended_tune": int(item.get("tune") or 0),
            "recommended_fine_tune": 0,
            "recommended_root_note": 0,
            "recommended_trigger_mode": "noteon" if ((acoustic_role == "BASS_808" and duration_sec >= 0.8) or stype == "MELODIC_LOOP") else "oneshot",
            "recommended_volume": smart_vol["volume"],
            "hierarchical_volume": kit_mod.default_pad_volume(stype, "hierarchical_a") if kit_mod else 0.501187,
            "uniform_volume": 0.501187,
            "recommended_gain_db": smart_vol["gain_db"],
            "peak_dbfs": smart_vol["peak_dbfs"],
            "rms_dbfs": smart_vol["rms_dbfs"],
        })

    # Detección de tono fundamental (CQT/YIN Autocorrelación) y bloqueo armónico de 808s
    anchor_pc = None
    anchor_note_label = ""
    if kit_mod and hasattr(kit_mod, "detect_sample_pitch_and_key"):
        for pr in pad_reports:
            if not pr.get("rel_path"):
                continue
            if pr["sound_type"] in ("BASS_808", "KEYS_SYNTH", "MELODIC_LOOP", "KICK") or pr["acoustic_role"] in ("BASS_808", "SUB_KICK"):
                try:
                    wav_p = resolve_library_path(root_dir, pr["rel_path"])
                    if wav_p.is_file():
                        pinfo = kit_mod.detect_sample_pitch_and_key(wav_p)
                        pr["f0_hz"] = pinfo.get("f0_hz", 0.0)
                        pr["detected_note"] = pinfo.get("note", "")
                        pr["pitch_class"] = pinfo.get("pitch_class")
                        pr["cents_offset"] = pinfo.get("cents_offset", 0)
                        if float(pinfo.get("f0_hz") or 0.0) > 0.0:
                            pr["recommended_root_note"] = int(pinfo.get("midi_note") or 0)
                            pr["recommended_fine_tune"] = max(-90, min(90, -int(round(float(pinfo.get("cents_offset") or 0)))))
                        if anchor_pc is None and pr["sound_type"] in ("MELODIC_LOOP", "KEYS_SYNTH") and pinfo.get("pitch_class") is not None:
                            anchor_pc = pinfo["pitch_class"]
                            anchor_note_label = pinfo.get("note_root") or pinfo.get("note") or ""
                except Exception:
                    pass

        if anchor_pc is None:
            for pr in pad_reports:
                if pr.get("pitch_class") is not None:
                    anchor_pc = pr["pitch_class"]
                    anchor_note_label = pr.get("detected_note", "")
                    break

        if anchor_pc is not None:
            for pr in pad_reports:
                if (pr["sound_type"] == "BASS_808" or pr["acoustic_role"] == "BASS_808") and pr.get("pitch_class") is not None:
                    diff = (anchor_pc - int(pr["pitch_class"])) % 12
                    if diff > 6:
                        diff -= 12
                    pr["recommended_tune"] = int(diff)

    # Doctor de Fase y Enmascaramiento Subgrave (Kick vs 808 y Snare vs Clap)
    phase_warnings: list[str] = []
    if kit_mod and hasattr(kit_mod, "detect_transient_phase_conflict"):
        kicks = [p for p in pad_reports if p["sound_type"] == "KICK" and p.get("rel_path")]
        basses = [p for p in pad_reports if (p["sound_type"] == "BASS_808" or p["acoustic_role"] == "BASS_808") and p.get("rel_path")]
        snares = [p for p in pad_reports if p["sound_type"] == "SNARE" and p.get("rel_path")]
        claps = [p for p in pad_reports if p["sound_type"] == "CLAP" and p.get("rel_path")]

        for k_pad in kicks[:2]:
            for b_pad in basses[:2]:
                if k_pad["pad"] == b_pad["pad"]:
                    continue
                try:
                    wa = resolve_library_path(root_dir, k_pad["rel_path"])
                    wb = resolve_library_path(root_dir, b_pad["rel_path"])
                    ph = kit_mod.detect_transient_phase_conflict(wa, wb)
                    if ph.get("phase_conflict"):
                        phase_warnings.append(
                            f"Cancelación de fase subgrave detectada entre PAD {k_pad['pad']} y PAD {b_pad['pad']} (corr={ph['correlation']})."
                        )
                except Exception:
                    pass

        for s_pad in snares[:2]:
            for c_pad in claps[:2]:
                try:
                    wa = resolve_library_path(root_dir, s_pad["rel_path"])
                    wb = resolve_library_path(root_dir, c_pad["rel_path"])
                    ph = kit_mod.detect_transient_phase_conflict(wa, wb)
                    if ph.get("phase_conflict"):
                        phase_warnings.append(
                            f"Oposición de fase en transiente Snare+Clap entre PAD {s_pad['pad']} y PAD {c_pad['pad']} (corr={ph['correlation']})."
                        )
                except Exception:
                    pass

    combined_text = " ".join(text_tokens)
    style_info = (
        kit_mod.detect_musical_style(combined_text, bpm=current_tempo if current_tempo != 120.0 else None)
        if kit_mod and hasattr(kit_mod, "detect_musical_style")
        else {"id": "standard", "style": "Hip-Hop / Electrónica", "bpm": current_tempo, "mute_profile": "punch_clean"}
    )

    # Si el análisis acústico detecta colas subgraves/808 densas, priorizar perfil club_clean
    recommended_profile = style_info.get("mute_profile", "punch_clean")
    if sub_heavy_count >= 2 and recommended_profile in ("real_drums", "punch_clean"):
        recommended_profile = "club_clean"

    inferred_bpm = kit_mod.infer_kit_bpm(combined_text, fallback=style_info.get("bpm", current_tempo)) if kit_mod else current_tempo

    tuning_adjustments = []
    for pr in pad_reports:
        rec_mg = (
            kit_mod.mute_group_for_profile(
                "BASS_808" if pr["acoustic_role"] == "BASS_808" else pr["sound_type"],
                pr["sample_name"],
                profile=recommended_profile,
            )
            if kit_mod
            else 0
        )
        pr["recommended_mute_group"] = rec_mg
        if pr.get("detected_note") and (pr["sound_type"] == "BASS_808" or pr["acoustic_role"] == "BASS_808"):
            tuning_adjustments.append({
                "pad": pr["pad"],
                "detected_note": pr["detected_note"],
                "f0_hz": pr["f0_hz"],
                "recommended_tune": pr["recommended_tune"],
                "recommended_fine_tune": pr.get("recommended_fine_tune", 0),
                "recommended_root_note": pr.get("recommended_root_note", 0),
            })

    notes_parts = [
        f"Pads sub-graves: {sub_heavy_count}",
        f"Pareja Hi-Hat (Open+Closed): {'Sí' if (open_hat_count >= 1 and closed_hat_count >= 1) else 'No'}",
    ]
    if anchor_note_label:
        notes_parts.append(f"Tono ancla: {anchor_note_label}")
    if phase_warnings:
        notes_parts.append(f"⚠️ {len(phase_warnings)} aviso(s) de fase")

    return {
        "success": True,
        "cerebro_os": detect_cerebro_os(root_dir),
        "detected_style": style_info.get("style", "Hip-Hop / Electrónica"),
        "style_id": style_info.get("id", "standard"),
        "recommended_bpm": inferred_bpm,
        "recommended_mute_profile": recommended_profile,
        "anchor_key": anchor_note_label,
        "sub_heavy_pads": sub_heavy_count,
        "hihat_pair_detected": bool(open_hat_count >= 1 and closed_hat_count >= 1),
        "phase_warnings": phase_warnings,
        "tuning_adjustments": tuning_adjustments,
        "style": {
            "id": style_info.get("id", "standard"),
            "label": style_info.get("style", "Hip-Hop / Electrónica"),
            "bpm": inferred_bpm,
            "mute_profile": recommended_profile,
            "anchor_key": anchor_note_label,
            "confidence": 0.92 if style_info.get("id", "standard") != "standard" else 0.78,
            "notes": " · ".join(notes_parts),
        },
        "pads": pad_reports,
    }


def build_cerebro_smart_kit(root_dir: str, payload: dict) -> dict:
    """
    Construye un Kit inteligente de 16 pads a partir de una descripción en lenguaje natural / género
    (Baile Funk, Drill, Grime, UK Garage, 2-Step, Dubstep, Boom Bap, Jungle, Amapiano, etc.),
    emparejando BPM, perfil de Choke y tonalidad desde la base SQLite activa.
    """
    import random

    kit_mod = get_hardware_kit_builder(root_dir)
    prompt = str(payload.get("prompt") or payload.get("style") or "Hip-Hop").strip()
    style_info = (
        kit_mod.detect_musical_style(prompt)
        if kit_mod and hasattr(kit_mod, "detect_musical_style")
        else {"id": "standard", "style": "Hip-Hop / Electrónica", "bpm": 120.0, "mute_profile": "punch_clean"}
    )
    target_bpm = float(payload.get("bpm") or (kit_mod.infer_kit_bpm(prompt, fallback=style_info["bpm"]) if kit_mod else style_info["bpm"]))
    mute_profile = str(payload.get("mute_profile") or style_info.get("mute_profile") or "punch_clean")

    db_file = database_path(root_dir)
    if not os.path.isfile(db_file):
        raise ValueError("La base de datos SQLite no existe todavía. Ejecuta una reindexación primero.")

    # Extraer tokens de búsqueda del prompt que no sean palabras vacías
    stop_words = {"kit", "de", "con", "para", "en", "el", "la", "los", "las", "un", "una", "y", "a", "bpm", "style", "estilo", "pads", "pad"}
    raw_words = [w.lower() for w in re.findall(r"[a-zA-Z0-9#]+", prompt) if len(w) >= 3 and w.lower() not in stop_words and not w.isdigit()]

    slot_plan = [
        (1, "KICK", ["kick", "bd", "bombo"]),
        (2, "KICK", ["kick", "sub", "punch"]),
        (3, "SNARE", ["snare", "sd", "caja"]),
        (4, "SNARE", ["rim", "snare", "snap"]),
        (5, "CLAP", ["clap", "cp", "snap"]),
        (6, "CLAP", ["clap", "perc"]),
        (7, "HIHAT", ["closed", "ch", "chh", "hat"]),
        (8, "HIHAT", ["closed", "pedal", "hat"]),
        (9, "HIHAT", ["open", "oh", "ohh", "hat"]),
        (10, "HIHAT", ["open", "hat", "cymbal"]),
        (11, "PERCUSSION", ["perc", "atabaque", "bongo", "conga", "shaker", "wood"]),
        (12, "PERCUSSION", ["tom", "perc", "cowbell", "tamb", "fx"]),
        (13, "BASS_808", ["808", "sub", "bass", "reese", "donk"]),
        (14, "BASS_808", ["808", "bass", "glide", "sub"]),
        (15, "KEYS_SYNTH", ["chord", "synth", "keys", "rhodes", "stab", "pad"]),
        (16, "MELODIC_LOOP", ["loop", "melod", "vocal", "vox", "sample", "riff"]),
    ]

    conn = sqlite3.connect(Path(db_file).as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    used_paths: set[str] = set()
    pads_out: list[dict] = []

    for pad_num, stype, hints in slot_plan:
        cur.execute(
            "SELECT filename, rel_path, sound_type, bpm, musical_key, size_mb, energy_level FROM samples WHERE sound_type = ? LIMIT 800",
            (stype,),
        )
        rows = [r for r in (dict(raw_r) for raw_r in cur.fetchall()) if r.get("rel_path") and r["rel_path"] not in used_paths]
        if not rows:
            cur.execute(
                "SELECT filename, rel_path, sound_type, bpm, musical_key, size_mb, energy_level FROM samples LIMIT 400"
            )
            rows = [r for r in (dict(raw_r) for raw_r in cur.fetchall()) if r.get("rel_path") and r["rel_path"] not in used_paths]
        if not rows:
            continue

        def _score_row(r: dict) -> float:
            fn_low = f"{r.get('filename', '')} {r.get('rel_path', '')}".lower()
            sc = random.random() * 0.35
            for w in raw_words:
                if w in fn_low:
                    sc += 4.0
            for h_idx, h in enumerate(hints):
                if h in fn_low:
                    sc += 2.5 - (h_idx * 0.3)
            # Para charles cerrados (Pads 7-8) vs abiertos (Pads 9-10)
            sz = float(r.get("size_mb") or 0.0)
            if pad_num in (7, 8):
                if "open" in fn_low or "oh" in fn_low:
                    sc -= 3.0
                if 0.002 < sz <= 0.06:
                    sc += 1.5
            elif pad_num in (9, 10):
                if "open" in fn_low or "oh" in fn_low:
                    sc += 3.5
                if sz >= 0.05:
                    sc += 1.5
            # Cercanía de BPM en loops/melodías
            r_bpm = float(r.get("bpm") or 0.0)
            if r_bpm > 0 and abs(r_bpm - target_bpm) <= 8:
                sc += 3.0
            return sc

        best = max(rows, key=_score_row)
        used_paths.add(best["rel_path"])
        mg = (
            kit_mod.mute_group_for_profile(stype, best["filename"], profile=mute_profile)
            if kit_mod
            else (1 if stype == "KICK" else (2 if stype == "HIHAT" else (3 if stype == "SNARE" else 0)))
        )
        pads_out.append({
            "pad": pad_num,
            "rel_path": best["rel_path"],
            "filename": best["filename"],
            "sound_type": stype,
            "duration_sec": 0.6,
            "mute_group": mg,
            "volume": kit_mod.default_pad_volume(stype) if kit_mod and hasattr(kit_mod, "default_pad_volume") else 0.501187,
            "pan": 0.5,
            "tune": 0,
        })

    conn.close()
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", style_info.get("style", "Smart_Kit").split("/")[0].strip()).strip("_") or "Cerebro_Kit"
    return {
        "success": True,
        "kit_name": f"{slug}_{int(round(target_bpm))}BPM",
        "style": style_info,
        "recommended_bpm": target_bpm,
        "recommended_mute_profile": mute_profile,
        "pads": pads_out,
    }


def find_cerebro_similar_samples(root_dir: str, payload: dict) -> dict:
    """
    Encuentra las muestras acústica y tímbricamente más similares en la biblioteca SQLite
    comparando tipo de sonido, tamaño/duración, nivel de energía RMS, BPM y formato.
    """
    rel_path = str(payload.get("rel_path") or "").strip()
    sound_type = str(payload.get("sound_type") or "").strip().upper()
    limit = max(4, min(24, int(payload.get("limit") or 10)))

    db_file = database_path(root_dir)
    if not os.path.isfile(db_file):
        raise ValueError("La base de datos SQLite no está disponible.")

    conn = sqlite3.connect(Path(db_file).as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    target_row = None
    if rel_path:
        cur.execute(
            "SELECT filename, rel_path, sound_type, sample_format, bpm, musical_key, energy_level, size_mb FROM samples WHERE rel_path = ? LIMIT 1",
            (rel_path,),
        )
        row = cur.fetchone()
        if row:
            target_row = dict(row)
            if not sound_type:
                sound_type = str(target_row.get("sound_type") or "").upper()

    if not sound_type:
        sound_type = "KICK"

    target_sz = float((target_row or {}).get("size_mb") or 0.08)
    target_energy = str((target_row or {}).get("energy_level") or "GROOVE")
    target_bpm = float((target_row or {}).get("bpm") or 0.0)
    target_fmt = str((target_row or {}).get("sample_format") or "ONE_SHOT")

    cur.execute(
        "SELECT filename, rel_path, sound_type, sample_format, sub_pack, bpm, musical_key, energy_level, size_mb "
        "FROM samples WHERE sound_type = ? AND rel_path != ? LIMIT 1500",
        (sound_type, rel_path),
    )
    candidates = [dict(r) for r in cur.fetchall()]
    conn.close()

    scored: list[tuple[float, dict]] = []
    for c in candidates:
        c_sz = float(c.get("size_mb") or 0.08)
        c_energy = str(c.get("energy_level") or "GROOVE")
        c_bpm = float(c.get("bpm") or 0.0)
        dist = abs(c_sz - target_sz) * 3.0
        if c_energy != target_energy:
            dist += 0.35
        if c.get("sample_format") != target_fmt:
            dist += 1.5
        if target_bpm > 0 and c_bpm > 0:
            dist += abs(c_bpm - target_bpm) * 0.04
        similarity = round(max(0.10, min(0.99, 1.0 / (1.0 + dist))), 2)
        scored.append((
            similarity,
            {
                "filename": c["filename"],
                "rel_path": c["rel_path"],
                "sound_type": c["sound_type"],
                "sub_pack": c.get("sub_pack") or "",
                "size_mb": round(c_sz, 3),
                "bpm": c_bpm,
                "musical_key": c.get("musical_key") or "",
                "similarity": similarity,
            },
        ))

    scored.sort(key=lambda t: t[0], reverse=True)
    return {
        "success": True,
        "target_rel_path": rel_path,
        "sound_type": sound_type,
        "results": [item for _, item in scored[:limit]],
    }


def search_federated_libraries(root_dir: str, payload: dict) -> dict:
    """
    Busca muestras simultáneamente en todas las bibliotecas SQLite montadas en el sistema
    sin depender de nombres de discos fijos.
    """
    query = str(payload.get("query") or "").strip()
    sound_type = str(payload.get("sound_type") or "").strip().upper()
    limit = max(5, min(60, int(payload.get("limit") or 25)))
    libs = discover_mounted_audio_libraries(root_dir)
    results: list[dict] = []

    for lib in libs:
        db_p = Path(lib["db_path"])
        mount_p = Path(lib["mount_path"])
        t_name = lib.get("table_name") or "samples"
        if not db_p.is_file() or not re.match(r"^[a-zA-Z0-9_]+$", t_name):
            continue
        try:
            conn = sqlite3.connect(db_p.as_uri() + "?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({t_name})")
            cols = {r[1] for r in cur.fetchall()}
            name_col = "filename" if "filename" in cols else ("name" if "name" in cols else "")
            if not name_col:
                conn.close()
                continue

            sql = f"SELECT * FROM {t_name} WHERE 1=1"
            params: list[Any] = []
            if query:
                if "sub_pack" in cols:
                    sql += f" AND ({name_col} LIKE ? OR sub_pack LIKE ?)"
                    params.extend([f"%{query}%", f"%{query}%"])
                elif "style_tag" in cols:
                    sql += f" AND ({name_col} LIKE ? OR style_tag LIKE ?)"
                    params.extend([f"%{query}%", f"%{query}%"])
                else:
                    sql += f" AND {name_col} LIKE ?"
                    params.append(f"%{query}%")
            if sound_type:
                if "sound_type" in cols:
                    sql += " AND sound_type = ?"
                    params.append(sound_type)
                elif "sample_type" in cols:
                    sql += " AND UPPER(sample_type) LIKE ?"
                    params.append(f"%{sound_type}%")
            sql += f" LIMIT {limit}"
            cur.execute(sql, params)
            for row in cur.fetchall():
                rd = dict(row)
                rel_p = rd.get("rel_path") or rd.get("relative_path") or ""
                full_p = rd.get("full_path") or rd.get("path") or rd.get("root_path") or (str(mount_p / rel_p) if rel_p else "")
                results.append({
                    "library_name": lib["name"],
                    "is_active_root": lib["is_active_root"],
                    "filename": rd.get(name_col, ""),
                    "sound_type": rd.get("sound_type") or rd.get("sample_type") or rd.get("category") or "SAMPLE",
                    "bpm": rd.get("bpm") or 0,
                    "musical_key": rd.get("musical_key") or rd.get("key") or "",
                    "rel_path": rel_p if lib["is_active_root"] else "",
                    "external_full_path": full_p if not lib["is_active_root"] else "",
                })
            conn.close()
        except Exception:
            pass

    return {
        "success": True,
        "libraries": libs,
        "results": results[:limit],
    }


def import_external_sample_to_library(root_dir: str, payload: dict) -> dict:
    """
    Copia de forma segura una muestra procedente de otra biblioteca/disco externo montado
    hacia `Custom_Kits/_Imported_Samples/` dentro de la biblioteca activa de BeatOS.
    """
    ext_path_str = str(payload.get("external_full_path") or "").strip()
    if not ext_path_str:
        raise ValueError("Ruta de muestra externa requerida.")
    ext_p = Path(ext_path_str).resolve()
    if not ext_p.is_file() or ext_p.suffix.lower() not in {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".m4a"}:
        raise ValueError("Archivo de audio externo no válido.")

    # Verificar que pertenece a alguno de los volúmenes de audio montados descubiertos
    allowed_roots = [Path(lib["mount_path"]).resolve() for lib in discover_mounted_audio_libraries(root_dir)]
    if not any(ext_p.is_relative_to(ar) for ar in allowed_roots):
        raise ValueError("La muestra externa no pertenece a una biblioteca montada autorizada.")

    dest_dir = Path(root_dir).resolve() / "Custom_Kits" / "_Imported_Samples"
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", ext_p.name)
    dest_file = dest_dir / safe_name
    if not dest_file.exists():
        shutil.copy2(ext_p, dest_file)
    rel_dest = dest_file.relative_to(Path(root_dir).resolve()).as_posix()
    kit_mod = get_hardware_kit_builder(root_dir)
    stype = kit_mod.detect_sound_type(dest_file.name) if kit_mod else "PERCUSSION"
    return {
        "success": True,
        "filename": dest_file.name,
        "rel_path": rel_dest,
        "sound_type": stype,
    }


def get_system_status(root_dir: str):
    library_available = os.path.isdir(root_dir)
    card_mounted = library_available and os.path.ismount(root_dir)
    disk_stat = shutil.disk_usage(root_dir) if os.path.exists(root_dir) else None

    db_candidates = [database_path(root_dir)]
    sample_count = 0
    for cand in db_candidates:
        if os.path.isfile(cand):
            try:
                conn = sqlite3.connect(Path(cand).as_uri() + "?mode=ro", uri=True)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM samples")
                row = c.fetchone()
                sample_count = row[0] if row else 0
                conn.close()
                if sample_count > 0:
                    break
            except Exception:
                pass

    return {
        "status": "online" if library_available else "library_unavailable",
        "library_available": library_available,
        "card_mounted": card_mounted,
        "root_dir": root_dir,
        "sample_count": sample_count,
        "disk_free_gb": round(disk_stat.free / (1024**3), 2) if disk_stat else 0,
        "disk_total_gb": round(disk_stat.total / (1024**3), 2) if disk_stat else 0,
        "task_state": TASK_STATE,
        "cerebro_os": detect_cerebro_os(root_dir),
    }

def find_card_root(start_dir: str) -> str:
    """Detecta la raíz de la tarjeta SD o el repositorio local donde residen los samples."""
    installed_root = default_library_root(start_dir)
    if installed_root != Path(start_dir).resolve():
        return str(installed_root)
    if os.path.isdir(os.path.join(start_dir, "MPC-Sample")) or os.path.isdir(os.path.join(start_dir, "Expansions")):
        return os.path.abspath(start_dir)

    parent = os.path.dirname(os.path.abspath(start_dir))
    if os.path.isdir(os.path.join(parent, "MPC-Sample")) or os.path.isdir(os.path.join(parent, "Expansions")):
        return parent

    if os.path.isdir("/Volumes/MPCSMPL"):
        return "/Volumes/MPCSMPL"

    docs_repo = os.path.expanduser("~/Documents/mpc-sample-database")
    if os.path.isdir(docs_repo):
        return docs_repo

    return os.path.abspath(start_dir)

def find_available_port(start_port: int = 8888, max_attempts: int = 50) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if sys.platform != 'win32':
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port

def resolve_library_path(root_dir: str, value: str) -> Path:
    root = Path(root_dir).resolve()
    candidate = Path(value)
    candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
    relative = candidate.relative_to(root)
    if any(part.startswith('.') for part in relative.parts) or (relative.parts and relative.parts[0] == 'BeatOS'):
        raise ValueError('Las rutas privadas no están disponibles por HTTP')
    return candidate


class MPCAudioRequestHandler(BaseHTTPRequestHandler):
    server_version = "MPCAudioStreamer/3.8.0"

    def _api_json_dumps(self, payload, **kwargs):
        """Localize user-facing API messages by this request's ES/EN preference."""
        localized = localize_api_payload(payload, get_request_language(self.headers))
        return json.dumps(localized, **kwargs)

    def send_cors_headers(self):
        origin = self.headers.get('Origin')
        if origin:
            try:
                parsed_origin = urllib.parse.urlsplit(origin)
                host = self.headers.get('Host', '')
                server_port = self.server.server_address[1]
                is_local = (
                    parsed_origin.scheme == 'http'
                    and parsed_origin.hostname in {'127.0.0.1', 'localhost', '::1'}
                    and parsed_origin.port == server_port
                )
                if is_local:
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
                    self.send_header('Access-Control-Allow-Private-Network', 'true')
            except ValueError:
                pass
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Range, Content-Type, Accept, Origin, Authorization, X-Requested-With, Cache-Control, X-BeatOS-Client",
        )
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")
        self.send_header("Access-Control-Max-Age", "86400")

    def allow_local_request(self):
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        server_port = self.server.server_address[1]
        try:
            parsed_host = urllib.parse.urlsplit('http://' + host)
            valid_host = parsed_host.hostname in {'127.0.0.1', 'localhost', '::1'}
            valid_host = valid_host and parsed_host.port == server_port
            parsed_origin = urllib.parse.urlsplit(origin) if origin else None
            is_local_origin = bool(
                parsed_origin
                and parsed_origin.scheme == 'http'
                and parsed_origin.hostname in {'127.0.0.1', 'localhost', '::1'}
                and parsed_origin.port == server_port
            )
            valid_origin = not origin or is_local_origin
        except ValueError:
            valid_host = valid_origin = False
        clean_req_path = urllib.parse.unquote(self.path.split('?', 1)[0])
        is_top_level_nav = (
            self.command in ('GET', 'HEAD')
            and not clean_req_path.startswith('/api/')
            and not origin
            and (
                self.headers.get('Sec-Fetch-Mode') == 'navigate'
                or self.headers.get('Sec-Fetch-Dest') in ('document', 'iframe')
            )
        )
        is_local_probe = (
            self.command in ('GET', 'HEAD')
            and clean_req_path == '/beatos-online.js'
            and not origin
        )
        is_cross_site = (
            self.headers.get('Sec-Fetch-Site') == 'cross-site'
            and not is_top_level_nav
            and not is_local_probe
        )
        if not valid_host or not valid_origin or is_cross_site:
            self.send_error(403, 'Use la interfaz local de BeatOS')
            return False
        return True

    def do_OPTIONS(self):
        if not self.allow_local_request():
            return
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.allow_local_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        clean_path = parsed.path.rstrip("/")

        if clean_path == "/beatos-online.js":
            port = self.server.server_address[1]
            payload_js = f'window.__BEATOS_LOCAL_SERVER_ONLINE = "http://127.0.0.1:{port}";\n'.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload_js)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(payload_js)
            return

        # Endpoints API
        if clean_path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            data = get_system_status(self.server.root_dir)
            self.wfile.write(self._api_json_dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/cerebro_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            data = {"success": True, "cerebro_os": detect_cerebro_os(self.server.root_dir)}
            self.wfile.write(self._api_json_dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/task_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(TASK_STATE, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/theme":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            theme_file = os.path.expanduser("~/.gemini/antigravity/scratch/ecosystem_theme.json")
            current_theme = "te-arcade"
            if os.path.isfile(theme_file):
                try:
                    with open(theme_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        current_theme = data.get("theme", "te-arcade")
                except Exception:
                    pass
            self.wfile.write(self._api_json_dumps({"success": True, "theme": current_theme}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/po33_backups":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            if kit_mod and hasattr(kit_mod, "scan_po33_backups"):
                try:
                    with PO_BACKUP_LOCK:
                        backups = kit_mod.scan_po33_backups(kit_mod.po33_backup_dirs(self.server.root_dir), cache=PO_BACKUP_CACHE)
                    self.wfile.write(self._api_json_dumps({"success": True, "backups": backups}, ensure_ascii=False).encode("utf-8"))
                except Exception as e:
                    self.wfile.write(self._api_json_dumps({"success": False, "error": str(e), "backups": []}).encode("utf-8"))
            else:
                self.wfile.write(self._api_json_dumps({"success": False, "error": "Módulo hardware_kit_builder no disponible.", "backups": []}).encode("utf-8"))
            return

        elif clean_path == "/api/po_backup_profiles":
            from po_backup_protocols import PROFILES, AUDIO_ONLY
            payload = {'success': True, 'backup_models': PROFILES, 'audio_only_models': AUDIO_ONLY}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(payload, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/list_exportable_kits":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            if kit_mod and hasattr(kit_mod, "list_exportable_user_kits"):
                try:
                    kits_list = kit_mod.list_exportable_user_kits(self.server.root_dir)
                    self.wfile.write(self._api_json_dumps({"success": True, "kits": kits_list}, ensure_ascii=False).encode("utf-8"))
                except Exception as e:
                    self.wfile.write(self._api_json_dumps({"success": False, "error": str(e), "kits": []}, ensure_ascii=False).encode("utf-8"))
            else:
                self.wfile.write(self._api_json_dumps({"success": False, "error": "Módulo hardware_kit_builder no disponible.", "kits": []}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/scales":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            scales_dict = getattr(kit_mod, "SCALES", {}) if kit_mod else {}
            notes_list = getattr(kit_mod, "NOTE_NAMES", ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]) if kit_mod else []
            payload = {
                "success": True,
                "scales": sorted(list(scales_dict.keys())),
                "default_scale": "minor",
                "notes": notes_list,
            }
            self.wfile.write(self._api_json_dumps(payload, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/sampqol_config":
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            if kit_mod and hasattr(kit_mod, "read_mpcqol_conf"):
                try:
                    resp = kit_mod.read_mpcqol_conf(self.server.root_dir)
                    code = 200
                except Exception as e:
                    resp = {"success": False, "error": str(e)}
                    code = 500
            else:
                resp = {"success": False, "error": "Módulo hardware_kit_builder no disponible."}
                code = 500
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/po33_backup_audio":
            query = urllib.parse.parse_qs(parsed.query)
            file_name = query.get("file", [""])[0] or query.get("path", [""])[0]
            target_path = None
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            if file_name and kit_mod:
                roots = [p.resolve() for p in kit_mod.po33_backup_dirs(self.server.root_dir)]
                candidate = Path(file_name)
                candidate = (candidate if candidate.is_absolute() else roots[0] / candidate).resolve()
                if any(candidate.is_relative_to(root) for root in roots) and candidate.suffix.lower() == '.wav':
                    target_path = candidate
            if not target_path or not target_path.is_file():
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"error": "Audio de backup no encontrado."}).encode("utf-8"))
                return
            try:
                expected = query.get('sha256', [''])[0]
                if expected and not re.fullmatch('[a-fA-F0-9]{64}', expected):
                    self.send_error(400, 'Invalid SHA-256')
                    return
                with target_path.open('rb') as source, (tempfile.TemporaryFile() if expected else contextlib.nullcontext(source)) as transfer:
                    if expected:
                        shutil.copyfileobj(source, transfer, length=64 * 1024)
                        transfer.seek(0)
                        if hashlib.file_digest(transfer, 'sha256').hexdigest() != expected.lower():
                            self.send_error(409, 'Backup changed since inspection; refresh the library before restoring')
                            return
                        transfer.seek(0)
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(os.fstat(transfer.fileno()).st_size))
                    self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + urllib.parse.quote(target_path.name, safe=''))
                    self.send_cors_headers()
                    self.end_headers()
                    shutil.copyfileobj(transfer, self.wfile, length=64 * 1024)
            except Exception:
                self.send_response(500)
                self.end_headers()
            return

        elif clean_path == "/api/download_file":
            query = urllib.parse.parse_qs(parsed.query)
            file_name = query.get("file", [""])[0] or query.get("path", [""])[0]
            try:
                target_path = resolve_library_path(self.server.root_dir, file_name) if file_name else None
            except ValueError:
                self.send_error(403, 'Ruta fuera de la biblioteca')
                return
            if not target_path or not target_path.is_file():
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"error": "Archivo no encontrado."}).encode("utf-8"))
                return
            headers_sent = False
            try:
                # Stream from disk in bounded chunks: kits may contain many large samples.
                with target_path.open("rb") as source:
                    length = os.fstat(source.fileno()).st_size
                    mime = mimetypes.guess_type(target_path.name)[0] or "application/octet-stream"
                    quoted_name = urllib.parse.quote(target_path.name, safe="")
                    ascii_name = "".join(
                        c if c.isascii() and (c.isalnum() or c in "._-") else "_"
                        for c in target_path.name
                    )[:120] or "download"
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(length))
                    self.send_header("Content-Disposition",
                                     f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted_name}")
                    self.send_cors_headers()
                    self.end_headers()
                    headers_sent = True
                    shutil.copyfileobj(source, self.wfile, length=64 * 1024)
            except (BrokenPipeError, ConnectionResetError):
                # A cancelled browser download needs no follow-up response.
                pass
            except Exception:
                if not headers_sent:
                    # Preserve an explicit HTTP error when opening a file fails.
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(self._api_json_dumps(
                        {"success": False, "error": "No se pudo abrir el archivo de descarga."},
                        ensure_ascii=False).encode("utf-8"))
                else:
                    # A streaming error after headers cannot change the HTTP status.
                    self.close_connection = True
            return

        self.handle_request(send_body=True)

    def do_HEAD(self):
        if not self.allow_local_request():
            return
        self.handle_request(send_body=False)

    def do_POST(self):
        if not self.allow_local_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        clean_api = parsed.path.rstrip("/")
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400, 'Content-Length no válido')
            return
        limit = 128 * 1024 * 1024 if clean_api == '/api/po33_backups' else 1024 * 1024
        if length < 0 or length > limit:
            self.send_error(400 if length < 0 else 413, 'Tamaño de petición no permitido')
            return
        if clean_api == '/api/po33_backups':
            try:
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Transferencia incompleta')
                if self.headers.get_content_type() != 'audio/wav':
                    raise ValueError('Envía el archivo WAV original con Content-Type audio/wav')
                params = urllib.parse.parse_qs(parsed.query)
                filename = params.get('name', ['PO33.wav'])[0]
                model = params.get('model', [None])[0]
                project = params.get('project', [None])[0]
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                with PO_BACKUP_LOCK:
                    result = kit_mod.import_po33_backup(self.server.root_dir, filename, data, model=model, project=project)
                response, code = {'success': True, 'backup': result}, 200
            except (ValueError, EOFError) as error:
                response, code = {'success': False, 'error': str(error)}, 400
            except Exception as error:
                response, code = {'success': False, 'error': str(error)}, 500
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(response, ensure_ascii=False).encode('utf-8'))
            return

        elif clean_api == '/api/po_backup_classify':
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON request')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete request')
                payload = json.loads(data)
                import po_backup_protocols as protocols
                model = protocols.validate_model(payload.get('model'))
                project = payload.get('project')
                protocols.safe_slug(project)
                requested = payload.get('file', '')
                if not isinstance(requested, str) or not requested:
                    raise ValueError('Missing backup path')
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                roots = [p.resolve() for p in kit_mod.po33_backup_dirs(self.server.root_dir)]
                candidate = Path(requested)
                if candidate.is_symlink():
                    raise ValueError('Symlinked backups are not supported')
                candidate = (candidate if candidate.is_absolute() else roots[0] / candidate).resolve()
                if not (candidate.is_file() and candidate.suffix.lower() == '.wav'
                        and any(candidate.is_relative_to(root) for root in roots)):
                    raise ValueError('Backup outside the library')
                with PO_BACKUP_LOCK:
                    audio = kit_mod.inspect_po33_backup(candidate)
                    if not audio.get('wav_complete') or not audio.get('audio_compatible'):
                        raise ValueError('Unsupported/incomplete WAV; do not prepare restoration')
                    metadata = protocols.write_sidecar(candidate, model, project, source=candidate.name)
                response, code = {'success': True, 'backup': {
                    **audio, 'model': metadata['model'], 'project': metadata['project'],
                    'payload_verified': False, 'device_restore_verified': False}}, 200
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                response, code = {'success': False, 'error': str(error)}, 400
            except Exception as error:
                response, code = {'success': False, 'error': str(error)}, 500
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(response, ensure_ascii=False).encode('utf-8'))
            return

        elif clean_api == '/api/po_backup_verify':
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON request')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete request')
                payload = json.loads(data)
                candidate_text = payload.get('file', '')
                if not isinstance(candidate_text, str) or not candidate_text:
                    raise ValueError('Missing backup file')
                import po_backup_protocols as protocols
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                roots = [p.resolve() for p in kit_mod.po33_backup_dirs(self.server.root_dir)]
                requested = Path(candidate_text)
                if requested.is_symlink():
                    raise ValueError('Symlinked backups are not supported')
                candidate = (requested if requested.is_absolute() else roots[0] / requested).resolve()
                if not (candidate.is_file() and candidate.suffix.lower() == '.wav'
                        and any(candidate.is_relative_to(root) for root in roots)):
                    raise ValueError('Backup outside the library')
                info = kit_mod.inspect_po33_backup(candidate)
                metadata = protocols.read_sidecar(candidate, info.get('sha256', ''))
                if not metadata:
                    raise ValueError('Classify this legacy recording with its device model before protocol verification')
                if not info.get('audio_compatible') or info.get('capture_interrupted'):
                    raise ValueError('Incomplete or unsupported WAV recording')
                verified = protocols.verify_modem(candidate, metadata['model'])
                response, code = {'success': True, 'verification': verified}, 200
            except (ValueError, json.JSONDecodeError, TypeError) as error:
                response, code = {'success': False, 'error': str(error)}, 400
            except Exception as error:
                response, code = {'success': False, 'error': str(error)}, 500
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(response, ensure_ascii=False).encode('utf-8'))
            return

        elif clean_api == "/api/cerebro_analyze":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                result = analyze_rack_with_cerebro(self.server.root_dir, payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/cerebro_autochop":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                rel_path = str(payload.get("rel_path") or "").strip()
                if not rel_path:
                    raise ValueError("Selecciona una muestra o loop para dividir en pads.")
                src_wav = resolve_library_path(self.server.root_dir, rel_path)
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "autochop_sample_to_16_pads"):
                    raise RuntimeError("Motor autochop no disponible.")
                result = kit_mod.autochop_sample_to_16_pads(
                    src_wav,
                    self.server.root_dir,
                    max_slices=int(payload.get("max_slices") or 16),
                    kit_name=payload.get("kit_name"),
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/cerebro_smart_kit":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                result = build_cerebro_smart_kit(self.server.root_dir, payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/cerebro_similar_samples":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                result = find_cerebro_similar_samples(self.server.root_dir, payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/cerebro_federated_search":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                result = search_federated_libraries(self.server.root_dir, payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/cerebro_import_external_sample":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                result = import_external_sample_to_library(self.server.root_dir, payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/create_expansion":
            try:
                import base64
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "create_custom_expansion"):
                    raise RuntimeError("Motor create_custom_expansion no disponible en el servidor.")

                cover_b64 = payload.get("cover_base64") or payload.get("cover_data_url") or ""
                cover_bytes = None
                if isinstance(cover_b64, str) and cover_b64.strip():
                    raw_b64 = cover_b64.split(",", 1)[-1] if "," in cover_b64 else cover_b64
                    cover_bytes = base64.b64decode(raw_b64)

                selected_kits = payload.get("selected_kits") or payload.get("source_kits") or []

                result = kit_mod.create_custom_expansion(
                    title=payload.get("title", ""),
                    manufacturer=payload.get("manufacturer", "Astro1Deep"),
                    description=payload.get("description", ""),
                    artist_subfolder=payload.get("artist_subfolder", ""),
                    cover_bytes=cover_bytes,
                    cover_filename=payload.get("cover_filename", "Artwork.png"),
                    selected_kit_paths=selected_kits,
                    rack_pads=payload.get("rack_pads"),
                    rack_kit_name=payload.get("rack_kit_name", ""),
                    rack_tempo=float(payload.get("rack_tempo") or 90.0),
                    source_root=self.server.root_dir,
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except ValueError as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/create_kit":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "create_kit"):
                    raise RuntimeError("Motor hardware_kit_builder no disponible en el servidor.")

                kit_name = payload.get("name", "Custom_Beatmaker_Kit")
                target = payload.get("target", "universal")
                pads = payload.get("pads", [])

                entries = pads.values() if isinstance(pads, dict) else pads
                if not isinstance(pads, (dict, list)):
                    raise ValueError('Los pads deben ser una lista o un objeto')
                for pad in entries:
                    if not isinstance(pad, dict):
                        raise ValueError('Cada pad debe ser un objeto')
                    for field in ('source_path', 'rel_path', 'relPath', 'sample_path'):
                        if pad.get(field):
                            resolve_library_path(self.server.root_dir, pad[field])
                result = kit_mod.create_kit(
                    kit_name,
                    pads,
                    target=target,
                    source_root=self.server.root_dir,
                    tempo=payload.get("tempo", 120),
                    po_options=payload.get("po_options"),
                    mpc_options=payload.get("mpc_options"),
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                err_resp = {"success": False, "error": str(e)}
                self.wfile.write(self._api_json_dumps(err_resp).encode("utf-8"))
            return

        elif clean_api == "/api/create_chromatic_kit":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "create_chromatic_kit"):
                    raise RuntimeError("Función create_chromatic_kit no disponible en hardware_kit_builder.")

                kit_name = payload.get("name") or payload.get("kit_name", "Chromatic_Instrument")
                target = payload.get("target", "universal")
                sample_rel = payload.get("sample_path") or payload.get("sample") or payload.get("rel_path", "")
                if not sample_rel:
                    raise ValueError("Falta el parámetro 'sample_path' o 'sample'")

                sample_full = resolve_library_path(self.server.root_dir, sample_rel)
                if not sample_full.is_file():
                    raise FileNotFoundError(f"Archivo de muestra no encontrado: {sample_rel}")

                scale = payload.get("scale", "minor")
                root_note = payload.get("root_note", "C2")
                start_octave = int(payload.get("start_octave", 0))
                monophonic = bool(payload.get("monophonic", True))
                tempo = float(payload.get("tempo", 120.0))

                result = kit_mod.create_chromatic_kit(
                    sample_path=sample_full,
                    kit_name=kit_name,
                    scale=scale,
                    root_note=root_note,
                    start_octave=start_octave,
                    monophonic=monophonic,
                    target=target,
                    source_root=self.server.root_dir,
                    tempo=tempo,
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                err_resp = {"success": False, "error": str(e)}
                self.wfile.write(self._api_json_dumps(err_resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/rack_scale_spread":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                rel_path = str(payload.get("rel_path") or payload.get("relPath") or "").strip()
                if not rel_path:
                    raise ValueError("Selecciona o carga primero una muestra en el pad activo.")
                sample_full = resolve_library_path(self.server.root_dir, rel_path)
                if not sample_full.is_file():
                    raise FileNotFoundError(f"Muestra no encontrada: {rel_path}")
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "build_rack_scale_bank"):
                    raise RuntimeError("Función build_rack_scale_bank no disponible.")
                result = kit_mod.build_rack_scale_bank(
                    sample_path=sample_full,
                    scale=str(payload.get("scale") or "minor"),
                    target_root_note=str(payload.get("target_root_note") or "C2"),
                    source_root_note=payload.get("source_root_note"),
                    start_octave=int(payload.get("start_octave") or 0),
                    bank_index=int(payload.get("bank_index") or 0),
                    monophonic=bool(payload.get("monophonic", True)),
                    auto_detect_pitch=bool(payload.get("auto_detect_pitch", True)),
                    source_root=self.server.root_dir,
                )
                code = 200
            except (ValueError, FileNotFoundError, TypeError, json.JSONDecodeError) as e:
                result, code = {"success": False, "error": str(e)}, 400
            except Exception as e:
                result, code = {"success": False, "error": str(e)}, 500
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/sampqol_config":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "update_mpcqol_conf"):
                    raise RuntimeError("Gestor mpcqol.conf no disponible.")
                result = kit_mod.update_mpcqol_conf(
                    self.server.root_dir,
                    updates=payload.get("settings") or {},
                    preset=payload.get("preset"),
                )
                code = 200
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                result, code = {"success": False, "error": str(e)}, 400
            except Exception as e:
                result, code = {"success": False, "error": str(e)}, 500
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/reveal_in_finder":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                target_path = payload.get("path", "").strip()
                if not target_path:
                    raise ValueError("Falta parámetro 'path'")

                p = resolve_library_path(self.server.root_dir, target_path)
                if not p.exists():
                    raise FileNotFoundError(f"Ruta no encontrada: {target_path}")

                if sys.platform == 'darwin':
                    subprocess.run(['open', str(p)] if p.is_dir() else ['open','-R',str(p)], check=True)
                elif sys.platform == 'win32':
                    os.startfile(str(p if p.is_dir() else p.parent))
                else:
                    subprocess.run(['xdg-open',str(p if p.is_dir() else p.parent)], check=True)
                resp = {"success": True, "message": f"Abierto en el explorador: {p}"}
            except Exception as e:
                resp = {"success": False, "error": str(e)}

            self.send_response(200 if resp.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/launch_ep_tool":
            try:
                url = "https://teenage.engineering/apps/ep-sample-tool"
                if sys.platform == 'darwin':
                    browser = next((str(Path('/Applications')/name) for name in ['Google Chrome.app','Microsoft Edge.app','Firefox.app'] if (Path('/Applications')/name).is_dir()), None)
                    if not browser:
                        raise RuntimeError("Abre la herramienta oficial en Chrome, Edge o Firefox de escritorio; Safari no admite Web MIDI.")
                    subprocess.run(['open','-a',browser,url],check=True)
                elif not webbrowser.open(url):
                    raise RuntimeError("Abre la herramienta oficial en un navegador con Web MIDI")
                resp = {"success": True, "url": url}
            except Exception as e:
                resp = {"success": False, "error": str(e)}

            self.send_response(200 if resp.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/reindex":
            with TASK_LOCK:
                if TASK_STATE["running"]:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(
                        self._api_json_dumps(
                            {
                                "success": False,
                                "message": "Ya hay una reindexación en ejecución en segundo plano.",
                                "task_state": TASK_STATE,
                            },
                            ensure_ascii=False,
                        ).encode("utf-8")
                    )
                    return

                TASK_STATE["running"] = True
            t = threading.Thread(target=run_reindex_thread, args=(self.server.root_dir,), daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(
                self._api_json_dumps(
                    {
                        "success": True,
                        "message": "🚀 Reindexación iniciada en segundo plano con éxito.",
                        "task_state": TASK_STATE,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return

        elif clean_api == "/api/clean_metadata":
            res = run_clean_metadata(self.server.root_dir)
            self.send_response(200 if res.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/sync_dashboard":
            res = run_sync_dashboard()
            self.send_response(200 if res.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/load_project":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                rel_path = payload.get("rel_path")
                if not rel_path:
                    raise ValueError("Falta parámetro 'rel_path'")

                src_path = str(resolve_library_path(self.server.root_dir, rel_path))
                if not os.path.isfile(src_path):
                    raise FileNotFoundError('Proyecto no encontrado en la biblioteca')

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if kit_mod and hasattr(kit_mod, "parse_xpj_project"):
                    proj_info = kit_mod.parse_xpj_project(src_path, source_root=self.server.root_dir, track_index=payload.get("track_index"))
                    resp = {"success": True, "project": proj_info}
                else:
                    raise RuntimeError("Función parse_xpj_project no disponible.")
            except Exception as e:
                resp = {"success": False, "error": str(e)}

            self.send_response(200 if resp.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/list_expansion_programs":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                expansion_name = str(payload.get("expansion_name") or "").strip()
                expansion_path = str(payload.get("expansion_path") or "").strip()
                target_exp = expansion_path or expansion_name
                if not target_exp:
                    raise ValueError("Falta parámetro 'expansion_name'")

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if kit_mod and hasattr(kit_mod, "list_expansion_kits"):
                    exp_root = Path(self.server.root_dir) / "Expansions"
                    kits = kit_mod.list_expansion_kits(target_exp, expansions_root=exp_root, source_root=self.server.root_dir)
                    resp = {"success": True, "expansion_name": expansion_name or target_exp, "programs": kits, "total": len(kits)}
                else:
                    raise RuntimeError("Función list_expansion_kits no disponible.")
            except Exception as e:
                resp = {"success": False, "error": str(e), "programs": []}

            self.send_response(200 if resp.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/load_xpm_program":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                rel_path = payload.get("rel_path", "").strip()
                if not rel_path:
                    exp_name = payload.get("expansion_name", "")
                    prog_file = payload.get("program_file", "")
                    if exp_name and prog_file:
                        rel_path = f"Expansions/{exp_name}/{prog_file}"
                if not rel_path:
                    raise ValueError("Falta parámetro 'rel_path' o 'program_file'")

                clean_rel = rel_path.lstrip("/")
                src_path = str(resolve_library_path(self.server.root_dir, clean_rel))
                if not os.path.isfile(src_path):
                    raise FileNotFoundError('Programa XPM no encontrado en la biblioteca')

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if kit_mod and hasattr(kit_mod, "parse_xpm_program"):
                    prog_info = kit_mod.parse_xpm_program(src_path, source_root=self.server.root_dir)
                    resp = {"success": True, "program": prog_info}
                else:
                    raise RuntimeError("Función parse_xpm_program no disponible.")
            except Exception as e:
                sys.stderr.write(f"  [ERROR load_xpm_program] {e}\n")
                resp = {"success": False, "error": str(e)}

            self.send_response(200 if resp.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/download_xpa":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                rel_path = payload.get("rel_path")
                if not rel_path:
                    raise ValueError("Falta parámetro 'rel_path'")
                src_path = str(resolve_library_path(self.server.root_dir, rel_path))
                if not os.path.isfile(src_path):
                    raise FileNotFoundError(f"Proyecto no encontrado: {src_path}")

                fd, zip_path = tempfile.mkstemp(suffix=".xpa")
                os.close(fd)
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(src_path, os.path.basename(src_path))
                    proj_dir = os.path.splitext(src_path)[0] + "_[ProjectData]"
                    if not os.path.isdir(proj_dir):
                        proj_dir = os.path.splitext(src_path)[0] + "_ProjectData"
                    if os.path.isdir(proj_dir):
                        for root, _, files in os.walk(proj_dir):
                            for f in files:
                                full_path = os.path.join(root, f)
                                arcname = os.path.relpath(full_path, os.path.dirname(src_path))
                                zf.write(resolve_library_path(self.server.root_dir, full_path), arcname)

                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{os.path.basename(rel_path)}.xpa"'
                )
                self.send_cors_headers()
                self.end_headers()
                with open(zip_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
                os.remove(zip_path)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                err_resp = {"success": False, "error": str(e)}
                self.wfile.write(self._api_json_dumps(err_resp).encode("utf-8"))
            return

        elif clean_api == "/api/theme":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                theme_name = payload.get("theme", "te-arcade")
                
                theme_file = os.path.expanduser("~/.gemini/antigravity/scratch/ecosystem_theme.json")
                os.makedirs(os.path.dirname(theme_file), exist_ok=True)
                theme_data = {
                    "theme": theme_name,
                    "updated_at": datetime.datetime.now().isoformat(),
                    "source": "mpc_sample_database",
                    "synchronized_ecosystem": ["cerebro_os", "djproduccertool", "open_webui", "audiotheque"]
                }
                with open(theme_file, "w", encoding="utf-8") as f:
                    json.dump(theme_data, f, indent=2)
                
                local_dir = config_dir(self.server.root_dir)
                local_dir.mkdir(parents=True, exist_ok=True)
                local_theme = local_dir / "theme_config.json"
                with open(local_theme, "w", encoding="utf-8") as f:
                    json.dump(theme_data, f, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": True, "theme": theme_name}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(self._api_json_dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        self.send_response(404)
        self.send_cors_headers()
        self.end_headers()

    def log_message(self, format, *args):
        sys.stderr.write(f"  [HTTP] {args[0]} - {args[1]}\n")

    def handle_request(self, send_body: bool = True):
        parsed = urllib.parse.urlparse(self.path)
        clean_path = urllib.parse.unquote(parsed.path).lstrip("/")

        if clean_path in ("", "index.html", "catalogo", "catalogo.html"):
            for candidate in (CATALOG_REL, "catalogo_beatos.html", "catalogo_universal.html", "catalogo_mpc_sample.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
                if os.path.isfile(os.path.join(self.server.root_dir, candidate)):
                    clean_path = candidate
                    break

        file_root = self.server.root_dir
        if clean_path == CATALOG_REL:
            file_root = os.path.join(self.server.root_dir, 'BeatOS', 'data')
            clean_path = 'catalogo.html'
        elif clean_path == MASTER_DASHBOARD_REL or (
            clean_path == 'catalogo_universal.html'
            and os.path.isfile(os.path.join(self.server.root_dir, MASTER_DASHBOARD_REL))
        ):
            file_root = os.path.join(self.server.root_dir, 'BeatOS', 'docs')
            clean_path = 'MASTER_ECOSISTEMA_DISCOS.html'
        elif clean_path in {'SQLITE_DATABASE/catalogo_mpc_sample.html', 'SQLITE_DATABASE/catalogo_universal.html',
                            '_INDEX_MPC_SAMPLE/catalogo_mpc_sample.html', '_INDEX_MPC_SAMPLE/catalogo_universal.html'} and os.path.isfile(os.path.join(self.server.root_dir,CATALOG_REL)):
            file_root = os.path.join(self.server.root_dir, 'BeatOS', 'data')
            clean_path = 'catalogo.html'
        else:
            for prefix in ('BeatOS/docs/assets/', 'docs/assets/'):
                if clean_path.startswith(prefix):
                    file_root = os.path.join(os.path.dirname(__file__),'docs','assets')
                    clean_path = clean_path[len(prefix):]
                    break

        try:
            target_path = str(resolve_library_path(file_root, clean_path))
        except ValueError:
            self.send_error(403, 'Ruta fuera de la biblioteca')
            return

        if file_root == self.server.root_dir and not os.path.isfile(target_path):
            sub_path = os.path.join(self.server.root_dir, "SQLITE_DATABASE", clean_path)
            if os.path.isfile(sub_path):
                target_path = sub_path
            elif clean_path.startswith("SQLITE_DATABASE/"):
                root_direct = os.path.join(self.server.root_dir, clean_path.replace("SQLITE_DATABASE/", "", 1))
                if os.path.isfile(root_direct):
                    target_path = root_direct

        if not os.path.isfile(target_path):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            if send_body:
                msg = f"404 No encontrado: {clean_path}\nBuscado en: {target_path}\n"
                self.wfile.write(msg.encode("utf-8"))
            return

        try:
            target_path = str(resolve_library_path(file_root, target_path))
        except ValueError:
            self.send_error(403, 'Ruta fuera de la biblioteca')
            return

        file_size = os.path.getsize(target_path)
        mime_type, _ = mimetypes.guess_type(target_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        range_header = self.headers.get("Range")

        # RFC 7233 Range Requests para streaming
        if range_header and range_header.startswith("bytes="):
            try:
                ranges = range_header.replace("bytes=", "").split("-")
                start = int(ranges[0]) if ranges[0] else 0
                end = int(ranges[1]) if ranges[1] else file_size - 1
                if end >= file_size:
                    end = file_size - 1
                length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_cors_headers()
                self.end_headers()

                if send_body:
                    try:
                        with open(target_path, "rb") as f:
                            f.seek(start)
                            remaining = length
                            chunk_size = 64 * 1024
                            while remaining > 0:
                                read_len = min(chunk_size, remaining)
                                chunk = f.read(read_len)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                return
            except (ValueError, OSError):
                pass

        # Respuesta 200 completa
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        if mime_type == "text/html":
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_cors_headers()
        self.end_headers()

        if send_body:
            try:
                with open(target_path, "rb") as f:
                    chunk_size = 64 * 1024
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

def existing_library_root(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=2) as response:
            state = json.loads(response.read(65536))
        return Path(state['root_dir']).resolve() if state.get('status') == 'online' else None
    except (OSError, ValueError, KeyError):
        return None

def run_server(custom_path: str | None = None, port: int | None = None, auto_open: bool = True):
    def emit(message):
        print(translate_text(str(message), (os.environ.get("BEATOS_LANG") or "en")))

    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_root = str(Path(custom_path).expanduser().resolve()) if custom_path else find_card_root(script_dir)
    if not Path(target_root).is_dir():
        raise ValueError(translate_text(f"La biblioteca no existe: {target_root}", (os.environ.get("BEATOS_LANG") or "en")))
    from index_mpc_library import restore_empty_catalog
    if restore_empty_catalog(target_root, Path(script_dir) / 'templates/catalogo.html'):
        emit('Recovered the empty catalog from the existing index; audio and database were preserved.')

    desired_port = port or 8888
    port = find_available_port(desired_port)

    catalog_rel = None
    for cand in (CATALOG_REL, "catalogo_beatos.html", "catalogo_universal.html", "catalogo_mpc_sample.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
        if os.path.isfile(os.path.join(target_root, cand)):
            catalog_rel = cand
            break

    if not catalog_rel:
        if os.path.isfile(os.path.join(script_dir, "catalogo_beatos.html")):
            catalog_rel = "catalogo_beatos.html"
        elif os.path.isfile(os.path.join(script_dir, "catalogo_universal.html")):
            catalog_rel = "catalogo_universal.html"
        elif os.path.isfile(os.path.join(script_dir, "catalogo_mpc_sample.html")):
            catalog_rel = "catalogo_mpc_sample.html"

    if port != desired_port and existing_library_root(desired_port) == Path(target_root):
        existing_url = f"http://127.0.0.1:{desired_port}/" + (catalog_rel if catalog_rel else "")
        if auto_open:
            emit(f"✔ El servidor BeatOS ya está activo en segundo plano en {existing_url} — abriendo navegador...")
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", existing_url], check=False)
                else:
                    webbrowser.open(existing_url)
            except Exception:
                pass
        else:
            emit(f"✔ El servidor BeatOS ya está activo en segundo plano en {existing_url} — omitiendo instancia duplicada.")
        return

    if port != desired_port:
        emit(f"Puerto {desired_port} ocupado por otra biblioteca o servicio; esta biblioteca usa {port}.")
    url = f"http://127.0.0.1:{port}/" + (catalog_rel if catalog_rel else "")

    emit("\n" + "=" * 70)
    emit("🔊 BeatOS — The MakerLicious")
    emit("   The system ★ [universal beatmaker station]")
    emit("   │ ref: mpc · sp-404 · pocket operator · maschine · ep-133 k.o. ii │")
    emit("=" * 70)
    emit(f"  📁 Raíz de Medios / Repositorio: {target_root}")
    emit(f"  🌐 URL del Catálogo Web:         {url}")
    emit(f"  ⚡ Streaming RFC 7233:           HTTP 206 Partial Content (Safari, Chrome, Arc)")
    emit(f"  🎛️ Multi-Sampler API:            Akai MPC, Roland SP-404MK2, NI Maschine, PO-33, EP-133 K.O. II")
    emit("=" * 70)
    emit("  💡 Presiona Ctrl+C en esta terminal para detener el servidor.\n")

    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, MPCAudioRequestHandler)
    httpd.root_dir = target_root

    if auto_open:
        def open_browser():
            time.sleep(1.2)
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", url], check=False)
                else:
                    webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=open_browser, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        emit("\n✔ Servidor web detenido correctamente.")
    finally:
        httpd.server_close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MPC Sample & Multi-Sampler Audio Streamer")
    parser.add_argument("path", nargs="?", default=None, help="Directorio raíz de la tarjeta o base")
    parser.add_argument("--port", "-p", type=int, default=None, help="Puerto HTTP (def: 8888)")
    parser.add_argument("--no-browser", action="store_true", help="No abrir automáticamente el navegador")
    args = parser.parse_args()
    run_server(args.path, port=args.port, auto_open=not args.no_browser)
