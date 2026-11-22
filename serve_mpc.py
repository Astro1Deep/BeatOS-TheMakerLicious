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
import array
from collections import OrderedDict
import copy
import datetime
import contextlib
import gzip
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import shutil
import struct
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
import unicodedata
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
from beatos_paths import CATALOG_REL, MASTER_DASHBOARD_REL, config_dir, database_path, default_library_root
from beatos_i18n import cli_failure, get_request_language, localize_api_payload, translate_text

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

# Estado global de tareas en segundo plano y cachés protegidas por mutex
TASK_LOCK = threading.Lock()
_BUILDER_LOCK = threading.Lock()
LIBRARY_NAMES_LOCK = threading.Lock()
_LIBS_CACHE_LOCK = threading.Lock()
_BRIDGE_SYNC_LOCK = threading.Lock()
_BRIDGE_SYNC_STATE = {"ts": 0.0, "sig": None}
_CEREBRO_MEMORY_LOCK = threading.Lock()
_CEREBRO_MEMORY_STORE = None
_CEREBRO_MEMORY_DIR = None
_MLX_MODEL_CACHE_LOCK = threading.Lock()
_MLX_MODEL_CACHE: dict[str, Any] = {"ts": 0.0, "base": "", "model": ""}
_RACK_MIX_PROFILES_LOCK = threading.Lock()
_SQLITE_TLS = threading.local()
_SEARCH_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE: OrderedDict[tuple[str, int, str, str, int], dict[str, Any]] = OrderedDict()
_SEARCH_CACHE_MAX_ITEMS = 128


def open_sqlite_readonly(db_path: str | Path) -> sqlite3.Connection:
    """Devuelve conexión SQLite RO thread-local con mmap + caché en RAM, invalidada al cambiar mtime."""
    p = Path(db_path).resolve()
    p_str = str(p)
    try:
        mtime_ns = p.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    pool = getattr(_SQLITE_TLS, "ro_conns", None)
    if pool is None:
        pool = {}
        _SQLITE_TLS.ro_conns = pool
    cached = pool.get(p_str)
    if cached is not None:
        conn, cached_mtime = cached
        if cached_mtime == mtime_ns:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                pass
        with contextlib.suppress(Exception):
            conn.close()
        pool.pop(p_str, None)

    conn = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=1.5)
    for pragma in ("PRAGMA mmap_size = 67108864", "PRAGMA cache_size = -16000", "PRAGMA temp_store = MEMORY"):
        with contextlib.suppress(sqlite3.Error):
            conn.execute(pragma)
    pool[p_str] = (conn, mtime_ns)
    return conn
PO_BACKUP_LOCK = threading.Lock()
PO_BACKUP_CACHE = {}

_BROWSER_WAV_LOCK = threading.Lock()
_BROWSER_WAV_CACHE: OrderedDict[tuple[str, int, int], bytes | None] = OrderedDict()
_BROWSER_WAV_CACHE_BYTES = 0
_BROWSER_WAV_CACHE_MAX_ITEMS = 64
_BROWSER_WAV_CACHE_MAX_BYTES = 128 * 1024 * 1024
_BROWSER_WAV_MAX_FILE_BYTES = 64 * 1024 * 1024

try:
    import numpy as _np
except Exception:
    _np = None


def _convert_pcm_to_pcm16(pcm: bytes, afmt: int, bps: int, ch: int) -> bytes | None:
    """Convierte PCM (8/16/24/32 int o 32/64 IEEE float LE) a PCM signed 16-bit LE."""
    ch = max(1, int(ch or 1))
    sample_bytes = bps // 8
    frame_bytes = sample_bytes * ch
    if sample_bytes <= 0 or frame_bytes <= 0:
        return None
    aligned_len = len(pcm) - (len(pcm) % frame_bytes)
    if aligned_len <= 0:
        return b""
    mv = memoryview(pcm)[:aligned_len]

    if afmt == 1 and bps == 16:
        return bytes(mv)
    if afmt == 1 and bps == 24:
        n_samples = aligned_len // 3
        out = bytearray(n_samples * 2)
        out[0::2] = mv[1::3]
        out[1::2] = mv[2::3]
        return bytes(out)
    if afmt == 1 and bps == 32:
        n_samples = aligned_len // 4
        out = bytearray(n_samples * 2)
        out[0::2] = mv[2::4]
        out[1::2] = mv[3::4]
        return bytes(out)
    if afmt == 1 and bps == 8:
        if _np is not None:
            arr = _np.frombuffer(mv, dtype=_np.uint8).astype(_np.int16)
            return ((arr - 128) << 8).astype("<i2").tobytes()
        arr_h = array.array("h", ((b - 128) << 8 for b in mv))
        if sys.byteorder != "little":
            arr_h.byteswap()
        return arr_h.tobytes()
    if afmt == 3 and bps == 32:
        if _np is not None:
            arr = _np.frombuffer(mv, dtype="<f4")
            clean = _np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)
            return (_np.clip(clean, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        arr_f = array.array("f")
        arr_f.frombytes(bytes(mv))
        if sys.byteorder != "little":
            arr_f.byteswap()
        arr_h = array.array(
            "h",
            (int(max(-1.0, min(1.0, x if math.isfinite(x) else 0.0)) * 32767.0) for x in arr_f),
        )
        if sys.byteorder != "little":
            arr_h.byteswap()
        return arr_h.tobytes()
    if afmt == 3 and bps == 64:
        if _np is not None:
            arr = _np.frombuffer(mv, dtype="<f8")
            clean = _np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)
            return (_np.clip(clean, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        arr_d = array.array("d")
        arr_d.frombytes(bytes(mv))
        if sys.byteorder != "little":
            arr_d.byteswap()
        arr_h = array.array(
            "h",
            (int(max(-1.0, min(1.0, x if math.isfinite(x) else 0.0)) * 32767.0) for x in arr_d),
        )
        if sys.byteorder != "little":
            arr_h.byteswap()
        return arr_h.tobytes()
    return None


def get_browser_playable_wav_bytes(full_path: str) -> bytes | None:
    """Devuelve un WAV PCM 16-bit estándar cuando un .wav tiene RIFF corrupto, chunks Akai (atem/slic) o float32/24-bit."""
    global _BROWSER_WAV_CACHE_BYTES
    if not full_path.lower().endswith(".wav"):
        return None
    try:
        st = os.stat(full_path)
    except OSError:
        return None
    if st.st_size < 44 or st.st_size > _BROWSER_WAV_MAX_FILE_BYTES:
        return None

    cache_key = (full_path, int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))), int(st.st_size))
    with _BROWSER_WAV_LOCK:
        if cache_key in _BROWSER_WAV_CACHE:
            _BROWSER_WAV_CACHE.move_to_end(cache_key)
            return _BROWSER_WAV_CACHE[cache_key]

    result: bytes | None = None
    try:
        with open(full_path, "rb") as fp:
            hdr = fp.read(min(st.st_size, 65536))
        if len(hdr) >= 44 and hdr[:4] == b"RIFF" and hdr[8:12] == b"WAVE":
            riff_sz = struct.unpack_from("<I", hdr, 4)[0]
            pos = 12
            afmt = ch = sr = bps = 0
            fmt_found = False
            data_off = None
            data_sz = 0
            proprietary_chunks = False

            def _scan_chunks(buf: bytes):
                nonlocal afmt, ch, sr, bps, fmt_found, data_off, data_sz, proprietary_chunks
                afmt = ch = sr = bps = 0
                fmt_found = False
                data_off = None
                data_sz = 0
                proprietary_chunks = False
                p = 12
                buf_len = len(buf)
                while p + 8 <= buf_len:
                    cid = buf[p:p + 4]
                    csz = struct.unpack_from("<I", buf, p + 4)[0]
                    payload_off = p + 8
                    if cid == b"fmt " and csz >= 16 and payload_off + 16 <= buf_len:
                        raw_fmt, ch, sr, _, _, bps = struct.unpack_from("<HHIIHH", buf, payload_off)
                        if raw_fmt == 0xFFFE and csz >= 40 and payload_off + 26 <= buf_len:
                            afmt = struct.unpack_from("<H", buf, payload_off + 24)[0]
                        else:
                            afmt = raw_fmt
                        fmt_found = True
                    elif cid == b"data":
                        data_off = payload_off
                        data_sz = csz
                        break
                    elif cid in (b"atem", b"slic", b"meta"):
                        proprietary_chunks = True
                    p += 8 + csz + (csz & 1)

            _scan_chunks(hdr)
            raw = None
            if (not fmt_found or data_off is None) and st.st_size > len(hdr):
                with open(full_path, "rb") as fp:
                    raw = fp.read()
                _scan_chunks(raw)

            if fmt_found and data_off is not None and ch > 0 and sr > 0:
                needs_normalize = (
                    (riff_sz + 8 != st.st_size)
                    or (afmt != 1)
                    or (bps != 16)
                    or proprietary_chunks
                    or (data_off + data_sz > st.st_size)
                )
                if needs_normalize:
                    if raw is None:
                        with open(full_path, "rb") as fp:
                            raw = fp.read()
                    pcm_end = min(len(raw), data_off + data_sz) if data_sz > 0 else len(raw)
                    pcm_raw = raw[data_off:pcm_end]
                    pcm16 = _convert_pcm_to_pcm16(pcm_raw, afmt, bps, ch)
                    if pcm16 is not None:
                        block_align = ch * 2
                        byte_rate = sr * block_align
                        data_len = len(pcm16)
                        wav_hdr = struct.pack(
                            "<4sI4s4sIHHIIHH4sI",
                            b"RIFF",
                            36 + data_len,
                            b"WAVE",
                            b"fmt ",
                            16,
                            1,
                            ch,
                            sr,
                            byte_rate,
                            block_align,
                            16,
                            b"data",
                            data_len,
                        )
                        result = wav_hdr + pcm16
    except Exception:
        result = None

    with _BROWSER_WAV_LOCK:
        # Eliminar entradas obsoletas del mismo path para no duplicar memoria
        stale_keys = [k for k in _BROWSER_WAV_CACHE if k[0] == full_path and k != cache_key]
        for sk in stale_keys:
            old_val = _BROWSER_WAV_CACHE.pop(sk, None)
            if old_val is not None:
                _BROWSER_WAV_CACHE_BYTES -= len(old_val)
        val_size = len(result) if result is not None else 0
        if val_size <= 28 * 1024 * 1024:
            _BROWSER_WAV_CACHE[cache_key] = result
            _BROWSER_WAV_CACHE_BYTES += val_size
            while (len(_BROWSER_WAV_CACHE) > _BROWSER_WAV_CACHE_MAX_ITEMS) or (
                _BROWSER_WAV_CACHE_BYTES > _BROWSER_WAV_CACHE_MAX_BYTES and _BROWSER_WAV_CACHE
            ):
                _, evicted = _BROWSER_WAV_CACHE.popitem(last=False)
                if evicted is not None:
                    _BROWSER_WAV_CACHE_BYTES -= len(evicted)

    return result
TASK_STATE = {
    "running": False,
    "task_name": "",
    "logs": [],
    "success": None,
    "started_at": 0,
    "finished_at": 0,
}


def _snapshot_task_state() -> dict:
    with TASK_LOCK:
        return {**TASK_STATE, "logs": list(TASK_STATE["logs"])}


def _reset_task_state(task_name: str, initial_log: str) -> None:
    with TASK_LOCK:
        TASK_STATE["running"] = True
        TASK_STATE["task_name"] = task_name
        TASK_STATE["logs"] = [initial_log]
        TASK_STATE["started_at"] = time.time()
        TASK_STATE["finished_at"] = 0
        TASK_STATE["success"] = None


def _append_task_log(line: str) -> None:
    clean_l = str(line or "").rstrip()
    if not clean_l:
        return
    with TASK_LOCK:
        TASK_STATE["logs"].append(clean_l)
        if len(TASK_STATE["logs"]) > 300:
            TASK_STATE["logs"].pop(1)


def _finish_task_state(success: bool | None = None, final_log: str | None = None) -> None:
    with TASK_LOCK:
        if success is not None:
            TASK_STATE["success"] = bool(success)
        if final_log:
            TASK_STATE["logs"].append(final_log)
            if len(TASK_STATE["logs"]) > 300:
                TASK_STATE["logs"].pop(1)
        TASK_STATE["finished_at"] = time.time()
        TASK_STATE["running"] = False


_LOADED_BUILDER_MODULE = {}

def get_hardware_kit_builder(root_dir: str):
    """Carga de forma dinámica y tolerante a fallos el módulo hardware_kit_builder con caché."""
    candidates = [os.path.join(os.path.dirname(__file__), "hardware_kit_builder.py"),
                  os.path.join(root_dir, "BeatOS", "hardware_kit_builder.py")]
    for cand in candidates:
        if os.path.isfile(cand):
            try:
                mtime = os.path.getmtime(cand)
                with _BUILDER_LOCK:
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
    _reset_task_state("reindex", "🚀 Iniciando reindexación de MPC Sample Database...")

    candidates = [os.path.join(os.path.dirname(__file__), "index_mpc_library.py"),
                  os.path.join(root_dir, "BeatOS", "index_mpc_library.py")]
    script_path = None
    for cand in candidates:
        if os.path.isfile(cand):
            script_path = cand
            break

    if not script_path:
        _finish_task_state(False, "❌ No se encontró el script de indexación.")
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
                _append_task_log(line)
        proc.wait()

        ok = (proc.returncode == 0)
        if ok:
            with _LIBS_CACHE_LOCK:
                _DISCOVERED_LIBS_CACHE["timestamp"] = 0.0
            kit_mod = get_hardware_kit_builder(root_dir)
            if kit_mod and hasattr(kit_mod, "clear_expansion_kits_cache"):
                kit_mod.clear_expansion_kits_cache()
        _finish_task_state(
            ok,
            "✔ Proceso finalizado correctamente." if ok else "❌ Error en el proceso de reindexación.",
        )
    except Exception as e:
        _finish_task_state(False, f"❌ Excepción durante ejecución: {str(e)}")


def run_install_capabilities_thread(root_dir: str, profile: str = "full", include_system_ffmpeg: bool = True):
    _reset_task_state(
        "install_capabilities",
        f"🛠️ Iniciando instalación de soporte y códecs (perfil: {profile})...",
    )

    try:
        import beatos_runtime
        code_dir = os.path.dirname(os.path.abspath(__file__))
        res = beatos_runtime.install_support_profile(
            profile,
            include_system_ffmpeg=bool(include_system_ffmpeg),
            code_dir=code_dir,
            log_cb=_append_task_log,
        )
        if res.get("needs_restart"):
            _append_task_log("ℹ️ Soporte instalado en ~/.beatos/venv. Reinicia BeatOS con ABRIR_BEATOS para cargarlo en memoria.")
        _finish_task_state(bool(res.get("success")), "✔ Instalación de capacidades completada.")
    except Exception as e:
        _finish_task_state(False, f"❌ Error instalando capacidades: {str(e)}")

def run_clean_metadata(root_dir: str):
    logs, errors = [], []
    excluded_dirs = {".Spotlight-V100", ".fseventsd", ".Trashes", ".TemporaryItems",
                     ".DocumentRevisions-V100", ".git"}
    if not Path(root_dir).is_dir():
        return {"success": False, "error": "La biblioteca ya no está disponible."}
    deleted_count = 0
    if sys.platform == "darwin" and shutil.which("dot_clean"):
        result = subprocess.run(["dot_clean", "-m", root_dir], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, errors="replace", timeout=100)
        if result.returncode == 0:
            logs.append("✔ dot_clean ejecutado en el volumen.")
        else:
            logs.append(f"dot_clean: exit {result.returncode}")
            if result.stderr.strip():
                logs.append(result.stderr.strip())
    for dirpath, dirnames, filenames in os.walk(root_dir, onerror=errors.append):
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        for filename in filenames:
            if filename.startswith("._") or filename == ".DS_Store":
                try:
                    (Path(dirpath) / filename).unlink()
                    deleted_count += 1
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    errors.append(exc)
    logs.append(f"✔ Purgados {deleted_count} archivos ocultos de metadatos AppleDouble (._* y .DS_Store).")
    logs.extend(str(error) for error in errors[:20])
    result = {"success": not errors, "logs": logs, "deleted_count": deleted_count}
    if errors:
        result["error"] = "No se pudo limpiar toda la biblioteca."
    return result


def run_sync_dashboard(root_dir: str, port: int) -> dict:
    """Refresh the live inventory and its local snapshot. Cerebro uses the same bridge."""
    if not Path(root_dir).is_dir():
        return {"success": False, "error": "La biblioteca ya no está disponible."}
    inventory = dashboard_inventory(root_dir, refresh=True)
    cerebro = detect_cerebro_os(inventory["root_dir"], port, mounted_libraries=inventory["libraries"])
    inventory["cerebro_installed"] = cerebro["installed"]
    inventory["cerebro_synced"] = cerebro.get("bridge_synced", False)
    write_state_json(config_dir(root_dir) / "ecosystem_inventory.json", inventory)
    return {"success": True, "inventory": inventory, "message": "Inventario del ecosistema actualizado."}


def _bounded_io_call(fn, timeout: float = 0.4, default=None):
    """Ejecuta una comprobación de sistema de archivos con timeout para evitar bloqueos por volúmenes colgados."""
    box = [default]
    def _runner():
        try:
            box[0] = fn()
        except OSError:
            pass
    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join(timeout)
    return box[0]
def mounted_volume_paths() -> list[Path]:
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        mask = kernel.GetLogicalDrives()
        return [Path(f"{chr(65 + index)}:/") for index in range(26)
                if mask & (1 << index) and kernel.GetDriveTypeW(f"{chr(65 + index)}:\\") in (2, 3)
                and f"{chr(65 + index)}:" != os.environ.get("SystemDrive", "C:")]
    if sys.platform == "darwin":
        try:
            mp_out = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=1.2).stdout
            cands = []
            for m in re.finditer(r" on (/Volumes/[^\r\n]+?) \(([^)]+)\)\s*$", mp_out, re.M):
                vol_p = Path(m.group(1))
                if not vol_p.name.startswith("."):
                    cands.append(vol_p)
            roots = []
            for child in sorted(set(cands)):
                ok = _bounded_io_call(lambda c=child: c.is_dir() and not c.is_symlink(), timeout=0.35, default=False)
                if ok:
                    roots.append(child)
            return roots
        except Exception:
            pass
    parents = [Path("/Volumes")] if sys.platform == "darwin" else [
        Path("/media"), Path("/mnt"), Path("/run/media")]
    if sys.platform != "darwin":
        for parent in (Path("/media"), Path("/run/media")):
            try:
                parents.extend(child for child in parent.iterdir() if child.is_dir() and not child.is_symlink())
            except OSError:
                pass
    roots = []
    for parent in parents:
        try:
            roots.extend(child for child in sorted(parent.iterdir()) if child.is_dir() and child.is_mount()
                         and not child.name.startswith(".") and not child.is_symlink())
        except OSError:
            pass
    return roots


def dashboard_inventory(root_dir: str, refresh: bool = False) -> dict:
    root = Path(root_dir).resolve()
    mounts = mounted_volume_paths()
    libraries = discover_mounted_audio_libraries(str(root), mounts=mounts, refresh=refresh)
    volumes = []
    for volume in dict.fromkeys(path.resolve() for path in [root, *mounts]):
        space = _bounded_io_call(lambda v=volume: shutil.disk_usage(v), timeout=0.4, default=None)
        if space is None:
            continue
        volumes.append({"name": volume.name or volume.anchor, "path": str(volume),
                        "active": volume == root, "free_bytes": space.free, "total_bytes": space.total})
    return {"root_dir": str(root), "volumes": volumes, "libraries": libraries}


def _probe_local_port(port: int, timeout: float = 0.04) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


_DISCOVERED_LIBS_CACHE = {"timestamp": 0.0, "libs": [], "root": ""}


def discover_mounted_audio_libraries(active_root: str = "", *, mounts=None, refresh=False) -> list[dict]:
    """
    Descubre dinámicamente bibliotecas SQLite de audio en volúmenes montados (/Volumes/*, /media/*, /mnt/*)
    sin depender de nombres de discos personales codificados a fuego.
    """
    now = time.time()
    with _LIBS_CACHE_LOCK:
        if not refresh and _DISCOVERED_LIBS_CACHE["root"] == active_root and (now - _DISCOVERED_LIBS_CACHE["timestamp"]) < 15.0:
            return list(_DISCOVERED_LIBS_CACHE["libs"])

    discovered: list[dict] = []
    seen_dbs: set[str] = set()

    def _inspect_candidate_db(db_file: Path, mount_path: Path, is_active: bool = False):
        try:
            real_db = str(db_file.resolve())
            if real_db in seen_dbs or not db_file.is_file():
                return
            with contextlib.closing(sqlite3.connect(db_file.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                all_tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]
                chosen_table = ""
                sample_count = 0
                for candidate_t in ("samples", "audio_assets", "tracks", "sound_banks", "sp404_hardware") + tuple(all_tables):
                    if candidate_t not in all_tables or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate_t):
                        continue
                    cur.execute(f"PRAGMA table_info({candidate_t})")
                    cols = {r[1] for r in cur.fetchall()}
                    if any(key in cols for key in ("filename", "name", "title")) and any(k in cols for k in ("rel_path", "relative_path", "full_path", "path", "root_path")):
                        cur.execute(f"SELECT COUNT(*) FROM {candidate_t}")
                        cnt_row = cur.fetchone()
                        cnt = int(cnt_row[0]) if cnt_row else 0
                        chosen_table = candidate_t
                        sample_count = cnt
                        break
            if not chosen_table:
                return
            seen_dbs.add(real_db)
            discovered.append({
                "id": ("mpc" if is_active and chosen_table == "samples" and not discovered
                       else "library_" + hashlib.sha256(os.fsencode(real_db)).hexdigest()[:12]),
                "name": mount_path.name or mount_path.anchor,
                "mount_path": str(mount_path.resolve()),
                "db_path": real_db,
                "table_name": chosen_table,
                "sample_count": sample_count,
                "is_active_root": bool(is_active),
            })
        except Exception:
            pass

    if active_root:
        act_p = Path(active_root).resolve()
        act_db = Path(database_path(active_root))
        if act_db.is_file():
            _inspect_candidate_db(act_db, act_p, is_active=True)

    for volume in mounts if mounts is not None else mounted_volume_paths():
        is_active = bool(active_root and volume.resolve() == Path(active_root).resolve())
        _inspect_candidate_db(database_path(volume), volume, is_active)
        try:
            for index_dir in sorted(volume.glob("_INDEX_*")):
                if index_dir.is_dir() and not index_dir.is_symlink():
                    for db_file in sorted(index_dir.glob("*.db")):
                        if not db_file.is_symlink():
                            _inspect_candidate_db(db_file, volume, is_active)
        except OSError:
            continue
    with _LIBS_CACHE_LOCK:
        _DISCOVERED_LIBS_CACHE["timestamp"] = now
        _DISCOVERED_LIBS_CACHE["root"] = active_root
        _DISCOVERED_LIBS_CACHE["libs"] = list(discovered)
    return discovered


def write_state_json(path: Path, data: dict) -> None:
    """Replace a state file atomically so concurrent readers get complete JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as stream:
        pending = Path(stream.name)
        try:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.close()
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


ECOSYSTEM_THEMES = frozenset({
    "te-arcade", "te-ko", "mpc-vintage", "mpc-blue-le", "sp404-studio",
    "maschine-studio", "makerlicious-bone", "cerebro-neon", "astro1deep-obsidian",
})


def ecosystem_theme_path() -> Path:
    return Path.home() / ".gemini" / "antigravity" / "scratch" / "ecosystem_theme.json"


def read_ecosystem_theme(root_dir: str) -> str | None:
    for path in (ecosystem_theme_path(), config_dir(root_dir) / "theme_config.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            theme = payload.get("theme") if isinstance(payload, dict) else None
            if isinstance(theme, str) and theme in ECOSYSTEM_THEMES:
                return theme
        except (OSError, ValueError):
            continue
    return None


def _is_temp_test_root(path_str: str) -> bool:
    norm = os.path.abspath(path_str) if path_str else ""
    return norm.startswith(("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"))


def _probe_gateway_circuits(timeout: float = 0.45) -> dict[str, Any]:
    """Consulta http://127.0.0.1:8081/circuits del Cerebro Gateway sin bloquear."""
    try:
        req = urllib.request.Request("http://127.0.0.1:8081/circuits", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if not isinstance(raw, dict):
            return {}
        node = raw.get("circuits") if isinstance(raw.get("circuits"), dict) else raw
        mlx_info = node.get("mlx") if isinstance(node.get("mlx"), dict) else {}
        ollama_info = node.get("ollama") if isinstance(node.get("ollama"), dict) else {}
        return {
            "mlx_state": str(mlx_info.get("state") or raw.get("mlx_state") or "UNKNOWN"),
            "mlx_avg_latency_ms": mlx_info.get("avg_latency_ms"),
            "ollama_state": str(ollama_info.get("state") or raw.get("ollama_state") or "UNKNOWN"),
            "raw": raw,
        }
    except Exception:
        return {}


def _count_cerebro_audio_rag_chunks() -> int:
    """Cuenta los chunks de conocimiento Audio/MIR vectorizados en ~/.mlx-stack/knowledge/user_memory.db."""
    db_file = Path.home() / ".mlx-stack" / "knowledge" / "user_memory.db"
    if not db_file.is_file():
        return 0
    try:
        with contextlib.closing(sqlite3.connect(str(db_file), timeout=0.4)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE source IN ('beatos_audio_mir', 'beatos_production')"
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def sync_beatos_bridge(
    root_dir: str,
    port: int | None,
    mounted_libraries: list[dict] | None = None,
    *,
    force: bool = False,
) -> bool:
    """Sincroniza ~/.mlx-stack/beatos_bridge.json de forma atómica con el estado y capacidades activas de BeatOS."""
    if os.environ.get("BEATOS_FORCE_HIDE_CEREBRO") == "1":
        return False
    mlx_root = Path.home() / ".mlx-stack"
    cerebro_dir = mlx_root / "cerebro"
    venv_py = mlx_root / "venv" / "bin" / "python"
    installed = mlx_root.is_dir() and (cerebro_dir.exists() or venv_py.is_file())
    if not installed or not root_dir:
        return False
    bridge_file = mlx_root / "beatos_bridge.json"

    if port is None:
        # Preserva estado real del puente cuando se consulta sin puerto (p.ej. llamada interna)
        if bridge_file.is_file():
            try:
                existing = json.loads(bridge_file.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and existing.get("beatos_active"):
                    if str(existing.get("root_dir") or "") == str(root_dir) or _is_temp_test_root(str(root_dir)):
                        return True
            except Exception:
                pass
        return False

    if os.environ.get("BEATOS_ALLOW_TEMP_BRIDGE") != "1" and _is_temp_test_root(str(root_dir)) and not _is_temp_test_root(str(Path.home())):
        return False

    libs = mounted_libraries if mounted_libraries is not None else discover_mounted_audio_libraries(root_dir)
    sig = (
        str(root_dir),
        int(port),
        tuple((lib.get("db_path"), lib.get("sample_count")) for lib in libs),
    )
    now_m = time.monotonic()
    with _BRIDGE_SYNC_LOCK:
        needs_write = (
            force
            or not bridge_file.is_file()
            or _BRIDGE_SYNC_STATE["sig"] != sig
            or (now_m - _BRIDGE_SYNC_STATE["ts"]) >= 30.0
        )
        if not needs_write:
            return True
        try:
            bridge_payload = {
                "schema": "cerebro-beatos-bridge-v2",
                "beatos_active": True,
                "root_dir": str(root_dir),
                "database_path": str(database_path(root_dir)),
                "api_base": f"http://127.0.0.1:{int(port)}",
                "mounted_libraries": libs,
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
                    "studio_live_profiles",
                    "multibank_coherence",
                    "mpc_ducking_advisor",
                    "bounce_loudness_meter",
                ],
            }
            write_state_json(bridge_file, bridge_payload)
            _BRIDGE_SYNC_STATE["sig"] = sig
            _BRIDGE_SYNC_STATE["ts"] = now_m
            return True
        except OSError:
            return False


def detect_cerebro_os(root_dir: str = "", port: int | None = None, *, mounted_libraries=None) -> dict:
    """Detecta si Cerebro OS (~/.mlx-stack) está instalado en el sistema anfitrión y sincroniza el puente bidireccional."""
    if os.environ.get("BEATOS_FORCE_HIDE_CEREBRO") == "1":
        return {
            "installed": False,
            "bridge_synced": False,
            "venv_ready": False,
            "gateway_online": False,
            "gateway_circuit": {},
            "mlx_server_online": False,
            "webui_online": False,
            "ollama_embed_online": False,
            "dashboard_online": False,
            "llm_online": False,
            "active_model": "",
            "rag_audio_chunks_count": 0,
            "capabilities": [],
            "mounted_libraries": [],
        }
    mlx_root = Path.home() / ".mlx-stack"
    cerebro_dir = mlx_root / "cerebro"
    venv_py = mlx_root / "venv" / "bin" / "python"
    installed = mlx_root.is_dir() and (cerebro_dir.exists() or venv_py.is_file())
    venv_ready = venv_py.is_file() and os.access(venv_py, os.X_OK)
    gateway_online = _probe_local_port(8081) if installed else False
    mlx_online = _probe_local_port(8080) if installed else False
    webui_online = _probe_local_port(3000) if installed else False
    ollama_embed_online = _probe_local_port(11434) if installed else False
    dash_online = _probe_local_port(3050) if installed else False
    gateway_circuit = _probe_gateway_circuits(timeout=0.35) if gateway_online else {}
    mounted_libs = (mounted_libraries if mounted_libraries is not None else discover_mounted_audio_libraries(root_dir)) if installed else []
    rag_audio_chunks_count = _count_cerebro_audio_rag_chunks() if installed else 0

    active_model = ""
    if installed and os.environ.get("BEATOS_DISABLE_MLX_LLM") != "1" and (gateway_online or mlx_online):
        try:
            probe_base = "http://127.0.0.1:8081" if gateway_online else "http://127.0.0.1:8080"
            active_model = _select_mlx_chat_model(probe_base)
        except Exception:
            active_model = ""

    bridge_synced = sync_beatos_bridge(root_dir, port, mounted_libs) if installed else False
    llm_online = bool(mlx_online or (gateway_online and gateway_circuit.get("mlx_state") != "OPEN"))

    return {
        "installed": bool(installed),
        "bridge_synced": bool(bridge_synced),
        "venv_ready": bool(venv_ready),
        "gateway_online": bool(gateway_online),
        "gateway_circuit": gateway_circuit,
        "mlx_server_online": bool(mlx_online),
        "webui_online": bool(webui_online),
        "ollama_embed_online": bool(ollama_embed_online),
        "dashboard_online": bool(dash_online),
        "llm_online": bool(llm_online),
        "active_model": active_model,
        "rag_audio_chunks_count": rag_audio_chunks_count,
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
            "studio_live_profiles",
            "multibank_coherence",
            "mpc_ducking_advisor",
            "bounce_loudness_meter",
        ] if installed else [],
    }


def _extract_pad_acoustic_signature(wav_path: Path, kit_mod: Any = None) -> Optional[dict]:
    """Calcula firma acústica rápida de un WAV (duración, ZCR, crest dB y energía en 3 bandas PCM)."""
    import math
    import struct
    import wave

    if not wav_path or not wav_path.is_file():
        return None
    mono: list[int] = []
    fr = 44100
    duration_sec = 0.0
    try:
        if wav_path.suffix.lower() == ".wav":
            with wave.open(str(wav_path), "rb") as wf:
                n_ch = wf.getnchannels()
                sw = wf.getsampwidth()
                fr = wf.getframerate() or 44100
                n_frames = wf.getnframes()
                duration_sec = round(n_frames / float(fr), 3) if fr else 0.0
                read_n = min(n_frames, int(fr * 1.6), 70560)
                raw = wf.readframes(read_n)
                if sw == 2 and read_n > 32 and n_ch >= 1:
                    total_short = len(raw) // 2
                    samples = struct.unpack(f"<{total_short}h", raw[: total_short * 2])
                    mono = list(samples[::n_ch] if n_ch > 1 else samples)
    except Exception:
        mono = []

    if not mono and kit_mod and hasattr(kit_mod, "_convert_audio"):
        try:
            conv = kit_mod._convert_audio(wav_path, mono=True, sample_rate=44100)
            fr = 44100
            duration_sec = round(len(conv) / float(fr), 3) if conv else 0.0
            mono = list(conv[:70560])
        except Exception:
            return None

    if len(mono) < 32:
        return None

    peak = max(abs(x) for x in mono) or 1
    sum_sq = sum(float(x) * float(x) for x in mono)
    if sum_sq <= 1e-6:
        return None
    rms = math.sqrt(sum_sq / len(mono))
    crest_db = round(20.0 * math.log10(peak / max(1e-6, rms)), 1)
    zc = sum(1 for i in range(1, len(mono)) if (mono[i - 1] >= 0) != (mono[i] >= 0))
    zcr_hz = round((zc * fr) / (2.0 * len(mono)), 1)

    fs = float(max(8000, fr))
    a_sub = math.exp(-2.0 * math.pi * 175.0 / fs)
    a_mid = math.exp(-2.0 * math.pi * 2800.0 / fs)
    lp_sub1 = lp_sub2 = lp_mid = 0.0
    sub_e = mid_e = high_e = 0.0
    for x_i in mono:
        x = float(x_i)
        lp_sub1 = (1.0 - a_sub) * x + a_sub * lp_sub1
        lp_sub2 = (1.0 - a_sub) * lp_sub1 + a_sub * lp_sub2
        lp_mid = (1.0 - a_mid) * x + a_mid * lp_mid
        mid_b = lp_mid - lp_sub2
        high_b = x - lp_mid
        sub_e += lp_sub2 * lp_sub2
        mid_e += mid_b * mid_b
        high_e += high_b * high_b

    tot_e = max(1e-9, sub_e + mid_e + high_e)
    return {
        "duration_sec": duration_sec,
        "zcr_hz": zcr_hz,
        "crest_db": crest_db,
        "sub_ratio": round(sub_e / tot_e, 3),
        "mid_ratio": round(mid_e / tot_e, 3),
        "high_ratio": round(high_e / tot_e, 3),
    }


def _select_mlx_chat_model(base_url: str = "http://127.0.0.1:8080", *, use_cache: bool = True) -> str:
    """Consulta modelos cargados en MLX server/Gateway local con caché TTL 30s y timeout 1.5s."""
    import urllib.request
    now_m = time.monotonic()
    if use_cache:
        with _MLX_MODEL_CACHE_LOCK:
            if (
                _MLX_MODEL_CACHE.get("base") == base_url
                and _MLX_MODEL_CACHE.get("model")
                and (now_m - float(_MLX_MODEL_CACHE.get("ts") or 0.0)) < 30.0
            ):
                return str(_MLX_MODEL_CACHE["model"])
    req = urllib.request.Request(f"{base_url}/v1/models", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=1.5) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    entries = [m for m in payload.get("data", []) if isinstance(m, dict) and m.get("id")]
    if not entries:
        return ""
    chosen = ""
    for m in entries:
        if m.get("owned_by") == "cerebro-active":
            chosen = str(m["id"])
            break
    if not chosen:
        models = [str(m.get("id") or "") for m in entries]
        preferred = ("qwen2.5-coder-14b", "qwen2.5-7b", "qwen2.5-3b", "deepseek", "qwen2.5-0.5b", "qwen3.5")
        for p_tok in preferred:
            for mid in models:
                low = mid.lower()
                if p_tok in low and "-vl-" not in low:
                    chosen = mid
                    break
            if chosen:
                break
        if not chosen:
            chosen = next((mid for mid in models if "-vl-" not in mid.lower()), models[0])
    with _MLX_MODEL_CACHE_LOCK:
        _MLX_MODEL_CACHE["ts"] = now_m
        _MLX_MODEL_CACHE["base"] = base_url
        _MLX_MODEL_CACHE["model"] = chosen
    return chosen


def _get_cerebro_memory_store(knowledge_dir: Path) -> Any:
    """Singleton thread-safe para PersistentMemoryStore + FaissHotCache sin recargar LanceDB en cada petición."""
    global _CEREBRO_MEMORY_STORE, _CEREBRO_MEMORY_DIR
    k_str = str(knowledge_dir.resolve())
    with _CEREBRO_MEMORY_LOCK:
        if _CEREBRO_MEMORY_STORE is not None and _CEREBRO_MEMORY_DIR == k_str:
            return _CEREBRO_MEMORY_STORE
        stack_dir = str(Path.home() / ".mlx-stack")
        if stack_dir not in sys.path:
            sys.path.insert(0, stack_dir)
        from cerebro_core.persistent_memory import PersistentMemoryStore

        _CEREBRO_MEMORY_STORE = PersistentMemoryStore(knowledge_dir)
        _CEREBRO_MEMORY_DIR = k_str
        return _CEREBRO_MEMORY_STORE


_AUDIO_MIR_PLAYBOOK_CARDS: tuple[dict[str, Any], ...] = (
    {
        "id": "anticlipping",
        "title": "Anti-Clipping Float32 (-0.80 dBFS)",
        "keywords": ("clipping", "aac", "mp4", "float32", "headroom", "dc", "hpf", "dither", "tpdf", "wav", "master"),
        "summary": "Decodifica MP4/AAC a float32 44.1 kHz, HPF 24 Hz Butterworth orden 2 fase cero, pico exacto a -0.80 dBFS y dither triangular TPDF (±1 LSB) a 16-bit.",
        "rules": [
            "Evita conversión directa int16 en MP4/AAC (los picos inter-muestra llegan a +2.5/+3.0 dBFS).",
            "HPF 24 Hz sosfiltfilt elimina DC offset y rumble de vinilo sin desfasar transientes.",
            "Mantén crest factor >7 dB en vinilos/boleros sin limitadores destructivos.",
        ],
    },
    {
        "id": "tempo_downbeat",
        "title": "Tempo Real, Compás y Downbeat φ*",
        "keywords": ("tempo", "bpm", "compas", "downbeat", "hcdf", "fft", "3/4", "4/4", "6/8", "12/8", "tiempo 1", "maracas", "doble"),
        "summary": "Onset compuesto 0.45*perc + 0.30*bass(<=220Hz) + 0.25*HCDF a hop=256, autocorrelación FFT insesgada (62–118 BPM), compás lag 3 vs 4 y fase φ*.",
        "rules": [
            "Evita beat_track(hop=512) y ventanas cortas que duplican tempo por maracas/hi-hats (130–160 BPM).",
            "φ* = argmax(0.55*HCDF + 0.35*Bass + 0.10*RMS_jump) ancla el Tiempo 1 en el cambio de acorde real.",
            "Para puentes 3/4→4/4 dispara 4 chops de 2 tiempos en pasos 1, 5, 9 y 13 (M6).",
        ],
    },
    {
        "id": "camelot_808",
        "title": "Tonalidad Vintage A440, Camelot y 808 Pitch",
        "keywords": ("tonalidad", "camelot", "a440", "tuning", "cents", "808", "pitch", "bajo", "choque", "armonico", "cqt", "hpss"),
        "summary": "HPSS (margin=2.0) + estimate_tuning (±10..25c en cinta/vinilo) + CQT 36 bins/oct con perfiles Krumhansl+Temperley, Camelot 1A–12B y F0 real de bajos.",
        "rules": [
            "Nunca mezcles la octava F0 de un sample con el pitch_class global de la tonalidad del loop.",
            "Los bajos/808 se afinan usando su F0 fundamental real (f0_pitch_class) respecto a la tónica ancla.",
            "Corrige cualquier choque armónico (semitone_fix != 0) fuera de tónica o quinta justa.",
        ],
    },
    {
        "id": "mmr_chopping",
        "title": "Chopping Musical MMR (3 Bancos / 48 Pads)",
        "keywords": ("chop", "mmr", "banco", "bancos", "48", "zero", "crossing", "fade", "click", "stub", "microcorte", "triadas"),
        "summary": "Reconocimiento de 24 tríadas + selección MMR en 16 zonas (cos_sim <= 0.94): Banco A frases 1 compás, Banco B chops 2 tiempos, Banco C turnarounds/hooks.",
        "rules": [
            "Ajusta inicio/fin al cruce por cero (±5 ms) y aplica micro-fades coseno (2 ms in / 8 ms out).",
            "Bloquea micro-stubs <0.25 s con min_dist_frames y min_tail_frames.",
            "Configura pads de chop en Mono=True, Polyphony=1, MuteGroup M6 y disparo Note-On.",
        ],
    },
    {
        "id": "rubato_formants",
        "title": "Rubato, Límite de Formantes (±4.5 st) y Mezcla",
        "keywords": ("rubato", "drumless", "formante", "formantes", "warp", "repitch", "hpf", "barro", "220", "380", "mezcla", "submix"),
        "summary": "Prohibido Warp global en rubato/drumless; si |repitch_st| > 4.5 usa MPC Warp 0 st por riesgo de formantes; HPF 95–120 Hz y limpieza 220–380 Hz.",
        "rules": [
            "Si |Δst| > 4.5 semitonos en Vinyl Repitch, evita distorsión ardilla/monstruo usando Warp 0 st o chops de 2t.",
            "HPF 95–120 Hz en chops melódicos libera subgrave para Kick y 808; limpia barro 220–380 Hz (-2/-3 dB).",
            "Mute Groups estándar: M1/M6 Chops, M2 Hi-Hats (Open/Closed), M3 Bass/808.",
        ],
    },
    {
        "id": "mpc_packaging",
        "title": "Empaquetado MPC (.xpm/.xpj) e Higiene .mp4",
        "keywords": ("xpm", "xpj", "acvs", "expansion", "mp4", "sha256", "autorun", "mpcqol", "reindex"),
        "summary": "Clona .xpm de plantilla completa (>900 KB); .xpj gzip con cabecera de 5 líneas ACVS/1.3.0.12 y floats con decimal (1.0); aparta .mp4 a _RAW_SOURCE_ARCHIVES.",
        "rules": [
            "Deduplica por SHA-256 antes de generar WAVs/kits y nunca dejes .mp4 dentro de Expansions/.",
            "Prohibido modificar /autorun o /mpcqol.conf fuera del gestor seguro.",
            "Tras editar /Volumes/MPCSMPL ejecuta dot_clean -m + BeatOS/index_mpc_library.py.",
        ],
    },
    {
        "id": "studio_vs_live_pa",
        "title": "Perfiles Studio/Pre-Master vs Directo/PA (AK4558)",
        "keywords": ("studio", "premaster", "mastering", "live", "directo", "pa", "foh", "lufs", "dbtp", "ak4558", "snapshot", "reversible", "subsonico"),
        "summary": "Studio/Pre-Master apunta a -16..-14 LUFS y mix bus -6..-3 dBFS (-1.0 dBTP); Directo/PA empuja a -10..-8 LUFS con techo estricto -0.8 a -1.0 dBTP (DAC AK4558 sin headroom anti-ISP) y HPF subsónico 30–35 Hz.",
        "rules": [
            "Guarda siempre snapshot no destructivo Studio ↔ Live PA en BeatOS/config/rack_mix_profiles.json y exporta directo como <KitName>_LIVE.xpj.",
            "El DAC AK4558 recorta picos inter-muestra >0.0 dBTP: respeta -1.0 dBTP (nunca > -0.8 dBTP) y vigila Color Compressor con In Boost > +6 dB.",
            "En PA aplica filtro subsónico 30–35 Hz y subgraves mono <120 Hz para proteger subwoofers y evitar cancelaciones de sala.",
        ],
    },
    {
        "id": "mpc_ducking_compression",
        "title": "Compresión & Ducking MPC (Color Comp / Pumper / Mother Ducker / Melodee)",
        "keywords": ("compresor", "compressor", "duck", "ducking", "sidechain", "pumper", "mother", "ducker", "color", "limiter", "soft", "clipper", "release", "melodee"),
        "summary": "Color Compressor (SHIFT+PAD 5) ofrece glue con Auto Make-Up; SampQOL Mother Ducker (buses 1–8 pre-fader + Ghost Kick Vol 0) y Melodee Sidechain (key_pad) dan ducking real; Pumper solo en 4x4 recto.",
        "rules": [
            "Calcula Release al BPM: 1/16 = 60000/(BPM*4) ms, 1/8 = 60000/(BPM*2) ms; ajusta 65–85% del hueco para evitar bombeo sucio.",
            "Regla anti-Pumper: prohibido Pumper en Dilla/Jazz-Hop con swing, Trap, Drill o DnB sincopado; usa Mother Ducker o Melodee Sidechain.",
            "En SampQOL Mother Ducker: Input pre-fader en Kick o Ghost Kick (Vol 0), Auto Make-Up Off; en AIR Stereo Width pon Low=0% para bajos mono.",
        ],
    },
    {
        "id": "multibank_coherence",
        "title": "Coherencia Multi-Banco A–H (Loudness, Camelot y Master)",
        "keywords": ("multibanco", "multibank", "bancos", "coherencia", "uniforme", "trim", "lufs", "spread", "a-h", "fase", "espectro", "mono"),
        "summary": "Evalúa cada pad y cada banco A–H por separado, y luego nivela el conjunto para ΔLUFS ≤ ±1.0 LU entre bancos, compatibilidad Camelot y fase limpia intra-banco.",
        "rules": [
            "Calcula mediana de LUFS/RMS entre bancos activos y aplica trim por banco (clamp ±3.0 dB) para evitar saltos bruscos de volumen en directo.",
            "Revisa la matriz Camelot entre bancos melódicos/808 (mismo código, ±1 o relativa A↔B) y aplica semitone_fix cuando haya choque.",
            "Valida cancelación de fase Kick↔808 y Snare↔Clap dentro de cada banco y mantén correlación estéreo <120 Hz ≥ 0.70.",
        ],
    },
)


def _get_audio_mir_playbook_cards() -> list[dict[str, Any]]:
    """Devuelve copias serializables de las 9 tarjetas técnicas Audio/MIR para UI y API."""
    return [
        {
            "id": card["id"],
            "title": card["title"],
            "keywords": list(card["keywords"]),
            "summary": card["summary"],
            "rules": list(card["rules"]),
        }
        for card in _AUDIO_MIR_PLAYBOOK_CARDS
    ]


def _retrieve_cerebro_audio_knowledge(
    query: str = "",
    *,
    topic: str = "",
    telemetry: dict | None = None,
    limit: int = 3,
    use_semantic_rrf: bool = False,
) -> dict[str, Any]:
    """
    Recupera reglas relevantes de ingeniería de audio, DSP/MIR y teoría musical desde:
      1) Memoria activa de Cerebro OS (~/.mlx-stack/knowledge/user_memory.db + LanceDB RRF singleton)
      2) Tarjetas locales verificadas del Playbook Audio/MIR (garantía offline <5ms).
    """
    tele = telemetry if isinstance(telemetry, dict) else {}
    rhy = tele.get("rhythm_analysis") or {}
    adp = tele.get("hiphop_adaptation") or {}
    haud = tele.get("headroom_audit") or {}
    clashes = tele.get("harmonic_clashes") or []
    mix_mode = str(tele.get("mix_mode") or "").strip().lower()
    gc = tele.get("global_coherence") or {}

    ctx_tokens: list[str] = []
    if query.strip():
        ctx_tokens.append(query.strip())
    if topic.strip():
        ctx_tokens.append(topic.strip())
    if tele.get("detected_style"):
        ctx_tokens.append(str(tele["detected_style"]))
    if mix_mode in ("live_pa", "studio_mastering"):
        ctx_tokens.append("studio live pa ak4558 dbtp lufs ducking sidechain" if mix_mode == "live_pa" else "studio premaster mastering headroom dbtp")
    if len(gc.get("active_banks") or []) > 1:
        ctx_tokens.append("multibanco coherencia lufs spread camelot bancos")
    if tele.get("ducking_recipe"):
        ctx_tokens.append("ducking sidechain color compressor mother ducker pumper")
    if rhy.get("is_rubato"):
        ctx_tokens.append("rubato drumless warp frases M6")
    if rhy.get("time_signature") in ("3/4", "6/8", "12/8", "5/4"):
        ctx_tokens.append(f"compas {rhy.get('time_signature')} tiempo 1 phi puente")
    if abs(float(adp.get("repitch_semitones") or 0.0)) > 4.5:
        ctx_tokens.append("formantes repitch MPC Warp 0 st")
    if haud.get("clipping_pads") or haud.get("dc_offset_pads"):
        ctx_tokens.append("anti-clipping float32 -0.80 dBFS HPF 24Hz TPDF")
    if clashes or tele.get("anchor_camelot"):
        ctx_tokens.append("camelot choque armonico 808 tuning cents")
    if not ctx_tokens:
        ctx_tokens.append("anti-clipping chop mmr bancos hpf camelot studio live pa ducking")

    combined_query = " ".join(ctx_tokens)
    q_low = combined_query.lower()

    # Puntuación rápida local sobre tarjetas del Playbook
    scored_cards: list[tuple[int, dict[str, Any]]] = []
    cards = _get_audio_mir_playbook_cards()
    for card in cards:
        sc = 0
        if topic and card["id"] == topic.strip().lower():
            sc += 30
        for kw in card["keywords"]:
            if kw in q_low:
                sc += 3
        if sc > 0 or not query.strip():
            scored_cards.append((sc, card))
    scored_cards.sort(key=lambda pair: pair[0], reverse=True)
    matched_cards = [pair[1] for pair in scored_cards[: max(1, min(9, int(limit)))]]
    if not matched_cards:
        matched_cards = cards[: max(1, min(9, int(limit)))]

    rag_hits: list[dict[str, Any]] = []
    rag_mode = "local_playbook"
    knowledge_dir = Path.home() / ".mlx-stack" / "knowledge"
    db_file = knowledge_dir / "user_memory.db"
    if os.environ.get("BEATOS_DISABLE_CEREBRO_RAG") != "1" and db_file.is_file():
        # Intentar RRF semántico completo vía singleton cacheado solo cuando se solicita
        if use_semantic_rrf and query.strip():
            try:
                store = _get_cerebro_memory_store(knowledge_dir)
                rrf_res = store.search_rrf(combined_query, limit=max(limit * 2, 6))
                rrf_sorted = sorted(
                    rrf_res,
                    key=lambda r: (1 if r.get("source") in ("beatos_audio_mir", "beatos_production") else 0, float(r.get("score") or 0.0)),
                    reverse=True,
                )
                for item in rrf_sorted[:limit]:
                    rag_hits.append({
                        "id": str(item.get("id") or ""),
                        "source": str(item.get("source") or "cerebro_rag"),
                        "score": round(float(item.get("score") or 0.0), 4),
                        "text": str(item.get("text") or ""),
                    })
                if rag_hits:
                    rag_mode = "semantic_rrf_singleton"
            except Exception:
                rag_hits = []

        # Consulta BM25 ultrarrápida (<5 ms) sobre memories_fts en SQLite para análisis en tiempo real / fallback
        if not rag_hits:
            try:
                tokens = [t for t in re.findall(r"[\wÀ-ÿ0-9_-]{2,}", combined_query) if t.strip()][:12]
                with contextlib.closing(sqlite3.connect(str(db_file), timeout=0.6)) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = []
                    if tokens:
                        fts_q = " OR ".join(f'"{t}"' for t in tokens)
                        rows = conn.execute(
                            """
                            SELECT m.id, m.text, m.source, bm25(memories_fts) AS rank_v
                            FROM memories_fts f
                            JOIN memories m ON m.id = f.id
                            WHERE memories_fts MATCH ?
                            ORDER BY (CASE WHEN m.source IN ('beatos_audio_mir', 'beatos_production') THEN 0 ELSE 1 END) ASC, rank_v ASC
                            LIMIT ?
                            """,
                            (fts_q, max(1, int(limit))),
                        ).fetchall()
                    if not rows:
                        rows = conn.execute(
                            "SELECT id, text, source FROM memories WHERE source IN ('beatos_audio_mir', 'beatos_production') ORDER BY created_at DESC LIMIT ?",
                            (max(1, int(limit)),),
                        ).fetchall()
                for idx_r, row in enumerate(rows):
                    rag_hits.append({
                        "id": str(row["id"]),
                        "source": str(row["source"]),
                        "score": round(max(0.1, 1.0 - idx_r * 0.12), 3),
                        "text": str(row["text"]),
                    })
                if rag_hits:
                    rag_mode = "sqlite_fts5_bm25"
            except Exception:
                pass

    return {
        "success": True,
        "query": query.strip() or combined_query,
        "cards": cards,
        "matched_cards": matched_cards,
        "rag_hits": rag_hits[: max(1, int(limit))],
        "rag_mode": rag_mode,
        "source": "Cerebro OS RAG + Playbook Audio/MIR" if rag_hits else "Playbook Audio/MIR BeatOS",
    }


def _fallback_ducking_recipe(
    style_id: str,
    bpm: float,
    mix_mode: str = "studio_mastering",
    *,
    swing_pct: float = 50.0,
) -> dict[str, Any]:
    """Receta determinista de fallback si hardware_kit_builder.build_mpc_ducking_recipe no está disponible."""
    safe_bpm = max(40.0, min(220.0, float(bpm or 90.0)))
    r_16 = round(60000.0 / (safe_bpm * 4.0), 1)
    r_8 = round(60000.0 / (safe_bpm * 2.0), 1)
    r_32 = round(60000.0 / (safe_bpm * 8.0), 1)
    sid = str(style_id or "standard").strip().lower()
    is_live = mix_mode == "live_pa"
    syncopated = sid in ("jazz_hop", "boombap", "trap", "drill", "dnb", "jungle_footwork", "drumless", "bolero", "oldies") or swing_pct >= 54.0
    pumper_allowed = not syncopated
    pumper_warn = "" if pumper_allowed else "Evita Pumper en patrones con swing o síncopa: usa SampQOL Mother Ducker o Melodee Sidechain."
    rec_engine = "sampqol_mother_ducker" if syncopated else "sampqol_mother_ducker_or_pumper"
    rel_opt = round(max(35.0, min(220.0, r_16 * (0.72 if is_live else 0.82))), 1)
    return {
        "style_id": sid,
        "bpm": safe_bpm,
        "mix_mode": mix_mode,
        "release_1_16_ms": r_16,
        "release_1_8_ms": r_8,
        "release_1_32_ms": r_32,
        "pumper_allowed": pumper_allowed,
        "pumper_warning": pumper_warn,
        "recommended_engine": rec_engine,
        "mpc_stock_color_comp": {
            "attack_ms": 10.0 if is_live else 15.0,
            "release_ms": rel_opt,
            "amount_pct": 40 if is_live else 25,
            "color": "On" if sid in ("boombap", "lofi", "jazz_hop") else "Off",
            "in_boost_db": 3.0 if is_live else 0.0,
        },
        "mpc_knob_fx_pumper": {
            "enabled": pumper_allowed,
            "speed": "1/4",
            "shape_pct": 28 if is_live else 22,
            "depth_pct": (55 if is_live else 40) if pumper_allowed else 0,
        },
        "sampqol_mother_ducker": {
            "bus": 1,
            "key_pads": ["Kick / Ghost Kick (Vol 0)"],
            "target_pads": ["Bass/808", "Melodic Chops"],
            "threshold_db": -12.0 if is_live else -9.0,
            "ratio": "6:1" if is_live else "4:1",
            "attack_ms": 2.0 if sid in ("trap", "drill", "dnb") else 6.0,
            "release_ms": rel_opt,
            "soft_knee_db": 0.0 if sid in ("trap", "drill", "dnb") else 4.0,
        },
        "melodee_sidechain": {
            "enabled": True,
            "key_pad": "Kick",
            "amount_pct": 55 if is_live else 35,
            "release_ms": rel_opt,
        },
        "pa_safety_chain": {
            "true_peak_ceiling_dbtp": -1.0,
            "subsonic_hpf_hz": 32 if is_live else 24,
            "air_stereo_width_low_pct": 0,
        },
    }


def query_cerebro_mlx_advisor(
    telemetry: dict,
    *,
    allow_llm: bool = True,
    rag_bundle: dict | None = None,
) -> dict:
    """
    Combina el diagnóstico DSP determinista + RAG Audio/MIR con el Cerebro Gateway (:8081) o MLX (:8080)
    cuando está activo, reportando telemetría completa y garantizando fallback determinista offline.
    """
    import urllib.request

    t0 = time.monotonic()
    rhy = telemetry.get("rhythm_analysis") or {}
    adp = telemetry.get("hiphop_adaptation") or {}
    haud = telemetry.get("headroom_audit") or {}
    style_lbl = str(telemetry.get("detected_style") or "Hip-Hop / Electrónica")
    style_id = str(telemetry.get("style_id") or "standard")
    anchor_key = str(telemetry.get("anchor_key") or "Sin tonalidad fija")
    anchor_camelot = str(telemetry.get("anchor_camelot") or "")
    clashes = telemetry.get("harmonic_clashes") or []
    mix_adv = telemetry.get("mix_advice") or []
    seq = adp.get("sequencer_guide") or {}
    mix_mode = str(telemetry.get("mix_mode") or "studio_mastering").strip().lower()
    if mix_mode not in ("studio_mastering", "live_pa"):
        mix_mode = "studio_mastering"
    scope = str(telemetry.get("scope") or "all_banks")
    banks_summary = telemetry.get("banks_summary") or []
    global_coherence = telemetry.get("global_coherence") or {}
    pad_outliers = telemetry.get("pad_outliers") or []
    ducking_recipe = telemetry.get("ducking_recipe") or _fallback_ducking_recipe(
        style_id,
        float(telemetry.get("recommended_bpm") or 90.0),
        mix_mode,
        swing_pct=float(rhy.get("swing_pct") or 50.0),
    )

    chop_mode_l = str(adp.get("recommended_chop_mode") or "phrases")
    repitch_st = float(adp.get("repitch_semitones") or 0.0)
    formant_risk = abs(repitch_st) > 4.5
    mid_pct = round(float(rhy.get("mid_warmth_ratio", 0.0)) * 100)
    hpf_hz = int(seq.get("highpass_hz_cut", 105) or 105)
    clip_cnt = len(haud.get("clipping_pads") or [])

    if rhy.get("is_rubato"):
        det_chop = "Fraseo rubato: usa Auto-Chop por frases en cruces por cero (±5ms, fade 2/8ms) en M6 sin Warp global."
    elif chop_mode_l == "phrase_3_4_to_4_4":
        det_chop = (
            f"Compás {rhy.get('time_signature', '3/4')}→4/4: 4 chops de 2 tiempos en pasos "
            f"{seq.get('chop_trigger_steps', [1, 5, 9, 13])} (Banco B, cruces ±5ms, M6)."
        )
    else:
        det_chop = (
            f"Cortes ({chop_mode_l}) en Tiempo 1 con cruces por cero ±5ms, micro-fade 2/8ms, "
            "bancos A/B/C (1/2/3 tiempos) en M6."
        )

    is_live = mix_mode == "live_pa"
    det_mix = mix_adv[0] if mix_adv else (
        f"Modo Directo PA: techo estricto -1.0 dBTP (AK4558), HPF subsónico 32 Hz y HPF <{hpf_hz} Hz en chops."
        if is_live
        else f"Modo Studio/Pre-Master: headroom -6..-3 dBFS (-1.0 dBTP) y HPF <{hpf_hz} Hz en chops."
    )
    if mid_pct >= 52 and "220" not in det_mix and "380" not in det_mix:
        det_mix += " · Limpia barro en 220–380 Hz (-2/-3 dB)."
    if clip_cnt > 0 and "-0.80" not in det_mix and "-1.0" not in det_mix:
        det_mix += f" · {clip_cnt} pad(s) cerca de 0 dBFS: calibra headroom PCM."
    if clashes:
        det_mix += f" · Corrige choque armónico en {clashes[0].get('sample_name', 'Pad')} ({clashes[0].get('semitone_fix', 0):+d} st)."
    det_seq = str(seq.get("tip") or f"Secuenciador 1/16 con Swing {seq.get('swing_pct', 56)}% y Kick {seq.get('kick_steps', [1, 3, 9, 11])}.")
    if formant_risk:
        det_flip = (
            f"Tónica {anchor_key} · Salto {repitch_st:+.1f} st (>±4.5 st riesgo de formantes): "
            f"usa MPC Warp 0 st o chops de 2 tiempos a {adp.get('target_bpm', 84)} BPM en lugar de Vinyl Repitch."
        )
    else:
        det_flip = f"Tónica {anchor_key} · Prueba Lo-Fi ({adp.get('target_bpm', 84)} BPM) vs Vinyl Repitch sin timestretch (A/B/C)."

    det_profile_advice = {
        "active_scenario": mix_mode,
        "target_ceiling_dbtp": -1.0 if is_live else -1.0,
        "target_lufs_range": "-10 a -8 LUFS (PA FOH)" if is_live else "-16 a -14 LUFS (Pre-Master)",
        "key_actions": [
            "HPF subsónico 30–35 Hz + subgraves mono <120 Hz (AIR Stereo Width Low=0%)." if is_live else "Preserva Crest Factor >8–10 dB y margen -6..-3 dBFS en bus Master.",
            "Techo estricto -1.0 dBTP en DAC AK4558; exportar sesión independiente *_LIVE.xpj." if is_live else "Snapshot reversible guardado antes de cualquier ajuste de directo.",
        ],
    }
    det_pad_fixes = [
        {
            "pad": o.get("pad"),
            "bank": o.get("bank", "A"),
            "action": str(o.get("recommendation") or o.get("issue") or "Calibrar volumen PCM"),
        }
        for o in pad_outliers[:6]
    ]
    spread_db = float(global_coherence.get("bank_rms_spread_db") or 0.0)
    active_banks = global_coherence.get("active_banks") or [b.get("bank") for b in banks_summary if b.get("pad_count")]
    bank_clashes = global_coherence.get("camelot_clashes_between_banks") or []
    det_multibank_plan = {
        "loudness_alignment": (
            f"Desviación entre bancos ({spread_db:.1f} dB): aplica Nivelar Bancos A–H para ΔLUFS ≤ ±1.0 LU."
            if spread_db > 1.8 and len(active_banks) > 1
            else (f"Bancos {', '.join(active_banks)} alineados (spread {spread_db:.1f} dB)." if active_banks else "Banco único activo.")
        ),
        "harmonic_flow": (
            f"Choque Camelot entre bancos {bank_clashes[0].get('from_bank')}↔{bank_clashes[0].get('to_bank')}: aplica transposición sugerida."
            if bank_clashes
            else f"Continuidad armónica estable sobre {anchor_key}{f' [{anchor_camelot}]' if anchor_camelot else ''}."
        ),
        "master_bus_summary": (
            "Live PA: Mixer -2 dB / Out 1/2 -1 dB, Color Comp moderado sin saturar AK4558."
            if is_live
            else "Studio Pre-Master: Mixer -3 dB / Out 1/2 -3 dB, bus limpio listo para mastering."
        ),
    }

    deterministic_plan = {
        "chop_plan": det_chop,
        "mix_plan": det_mix,
        "sequencer_tip": det_seq,
        "creative_flip": det_flip,
        "profile_advice": det_profile_advice,
        "ducking_recipe": ducking_recipe,
        "pad_fixes": det_pad_fixes,
        "multibank_coherence_plan": det_multibank_plan,
    }

    active_rag = rag_bundle if isinstance(rag_bundle, dict) else _retrieve_cerebro_audio_knowledge(
        "", telemetry=telemetry, limit=3, use_semantic_rrf=False
    )
    rag_hits = active_rag.get("rag_hits") or []
    rag_mode = str(active_rag.get("rag_mode") or "local_playbook")
    rag_summary = " | ".join(str(h.get("text") or "")[:260] for h in rag_hits)[:900]

    def _finish_fallback(reason: str, endpoint: str = "", model: str = "") -> dict[str, Any]:
        return {
            "used_llm": False,
            "engine": "Cerebro DSP Determinista",
            "model": model,
            "endpoint": endpoint,
            "latency_ms": int(round((time.monotonic() - t0) * 1000)),
            "fallback_reason": reason,
            "rag_rules_used": len(rag_hits),
            "rag_mode": rag_mode,
            "plan": deterministic_plan,
        }

    if not allow_llm or os.environ.get("BEATOS_DISABLE_MLX_LLM") == "1":
        return _finish_fallback("llm_disabled_by_config")

    gateway_up = _probe_local_port(8081, timeout=0.05)
    mlx_up = False
    llm_base = ""
    use_gateway = False
    if gateway_up:
        circ = _probe_gateway_circuits(timeout=0.35)
        if str(circ.get("mlx_state") or "").upper() == "OPEN":
            mlx_up = _probe_local_port(8080, timeout=0.05)
            if not mlx_up:
                return _finish_fallback("gateway_circuit_open", endpoint="http://127.0.0.1:8081")
            llm_base = "http://127.0.0.1:8080"
        else:
            use_gateway = True
            llm_base = "http://127.0.0.1:8081"
    else:
        mlx_up = _probe_local_port(8080, timeout=0.05)
        if not mlx_up:
            return _finish_fallback("mlx_and_gateway_offline")
        llm_base = "http://127.0.0.1:8080"

    model_override = (os.environ.get("BEATOS_MLX_MODEL") or "").strip()
    active_model_label = ""
    try:
        if model_override:
            request_model = model_override
            active_model_label = model_override
        elif use_gateway:
            # Consulta sin caché TTL en inferencia para respetar mocks y cambios de modelo en vivo
            active_model_label = _select_mlx_chat_model(llm_base, use_cache=False) or "default_model"
            request_model = "default_model"
        else:
            request_model = _select_mlx_chat_model(llm_base, use_cache=False)
            active_model_label = request_model
        if not request_model:
            return _finish_fallback("no_active_model", endpoint=llm_base)

        is_multibank_call = len(active_banks) > 1
        default_timeout = 25.0 if is_multibank_call else 18.0
        if telemetry.get("_temp_test_root") and not os.environ.get("BEATOS_MLX_TIMEOUT_S"):
            default_timeout = 5.5
        try:
            http_timeout = float(os.environ.get("BEATOS_MLX_TIMEOUT_S") or default_timeout)
        except ValueError:
            http_timeout = default_timeout
        http_timeout = max(2.0, min(60.0, http_timeout))

        compact_ctx = {
            "scenario": mix_mode,
            "scope": "multi_bank" if len(active_banks) > 1 else "single_bank",
            "style": style_lbl,
            "bpm": telemetry.get("recommended_bpm"),
            "anchor_key": anchor_key,
            "anchor_camelot": anchor_camelot,
            "time_signature": rhy.get("time_signature", "4/4"),
            "source_bpm": rhy.get("source_bpm"),
            "swing_pct": rhy.get("swing_pct"),
            "is_rubato": rhy.get("is_rubato", False),
            "is_drumless": rhy.get("is_drumless", False),
            "sub_pct": round(float(rhy.get("sub_energy_ratio", 0.0)) * 100),
            "mid_pct": mid_pct,
            "air_pct": round(float(rhy.get("high_air_ratio", 0.0)) * 100),
            "target_bpm": adp.get("target_bpm"),
            "repitch_st": repitch_st,
            "formant_risk": formant_risk,
            "chop_mode": chop_mode_l,
            "highpass_hz": hpf_hz,
            "harmonic_clashes": len(clashes),
            "clash_fix_st": int(clashes[0].get("semitone_fix", 0) or 0) if clashes else 0,
            "headroom_max_peak_dbfs": haud.get("max_peak_dbfs"),
            "clipping_pads_count": clip_cnt,
            "phase_warnings": len(telemetry.get("phase_warnings") or []),
            "pad_count": telemetry.get("pad_count", 0),
            "banks_summary": [
                {
                    "bank": b.get("bank"),
                    "pad_count": b.get("pad_count"),
                    "dominant_role": b.get("dominant_role"),
                    "bank_lufs_est": b.get("bank_lufs_est"),
                    "max_peak_dbfs": b.get("max_peak_dbfs"),
                    "camelot": b.get("camelot"),
                }
                for b in banks_summary[:8]
            ],
            "pad_outliers": pad_outliers[:6],
            "global_coherence": {
                "active_banks": active_banks,
                "bank_rms_spread_db": spread_db,
                "bank_trims_db": global_coherence.get("bank_trims_db") or {},
                "camelot_clashes_between_banks": bank_clashes[:4],
                "sub_mono_risk_pads": (global_coherence.get("sub_mono_risk_pads") or [])[:6],
            },
            "ducking_context": {
                "release_1_16_ms": ducking_recipe.get("release_1_16_ms"),
                "release_1_8_ms": ducking_recipe.get("release_1_8_ms"),
                "pumper_allowed": ducking_recipe.get("pumper_allowed"),
                "recommended_engine": ducking_recipe.get("recommended_engine"),
            },
            "cerebro_rag_rules": rag_summary,
        }
        body = {
            "model": request_model,
            "temperature": 0.2,
            "max_tokens": 650,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres ingeniero de audio MIR/Mastering y productor experto de Akai MPC Sample (Stock 1.3 + SampQOL + Melodee). "
                        "Basándote SOLO en las métricas reales y cerebro_rag_rules: "
                        "(1) Diferencia scenario='studio_mastering' (-16..-14 LUFS, -1.0 dBTP, mix bus -6..-3 dBFS) vs 'live_pa' (-10..-8 LUFS, techo estricto -1.0 dBTP / -0.80 dBFS en AK4558, HPF subsónico 32 Hz, mono <120 Hz); "
                        "(2) Respeta la regla anti-Pumper si pumper_allowed=false (usa Mother Ducker / Melodee Sidechain); "
                        "(3) Alinea coherencia multi-banco A-H (ΔLUFS ≤ ±1.0 LU, continuidad Camelot) y corrige pad_outliers; "
                        "(4) En rubato/drumless prohíbe Warp global; si formant_risk=true recomienda MPC Warp 0 st. "
                        "Responde SOLO JSON válido sin markdown en español técnico conciso con claves: "
                        "{\"chop_plan\":\"...\",\"mix_plan\":\"...\",\"sequencer_tip\":\"...\",\"creative_flip\":\"...\","
                        "\"multibank_coherence_plan\":{\"loudness_alignment\":\"...\",\"harmonic_flow\":\"...\",\"master_bus_summary\":\"...\"}}."
                    ),
                },
                {"role": "user", "content": json.dumps(compact_ctx, ensure_ascii=False)},
            ],
        }
        req = urllib.request.Request(
            f"{llm_base}/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="ignore"))
        content = str((((raw.get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()
        m_json = re.search(r"\{.*\}", content, re.S)
        parsed = json.loads(m_json.group(0) if m_json else content)
        if not isinstance(parsed, dict):
            raise ValueError("Respuesta MLX no JSON")
        merged_plan = dict(deterministic_plan)
        for k in ("chop_plan", "mix_plan", "sequencer_tip", "creative_flip"):
            v = parsed.get(k)
            if isinstance(v, str) and v.strip():
                merged_plan[k] = v.strip()[:260]
        if isinstance(parsed.get("multibank_coherence_plan"), dict):
            mb = dict(det_multibank_plan)
            for mk in ("loudness_alignment", "harmonic_flow", "master_bus_summary"):
                mv = parsed["multibank_coherence_plan"].get(mk)
                if isinstance(mv, str) and mv.strip():
                    mb[mk] = mv.strip()[:240]
            merged_plan["multibank_coherence_plan"] = mb
        if isinstance(parsed.get("profile_advice"), dict) and isinstance(parsed["profile_advice"].get("key_actions"), list):
            acts = [str(a).strip()[:200] for a in parsed["profile_advice"]["key_actions"] if str(a).strip()]
            if acts:
                merged_plan["profile_advice"] = {**det_profile_advice, "key_actions": acts[:4]}
        return {
            "used_llm": True,
            "engine": "Cerebro MLX LLM + DSP",
            "model": active_model_label or request_model,
            "endpoint": llm_base,
            "latency_ms": int(round((time.monotonic() - t0) * 1000)),
            "fallback_reason": "",
            "rag_rules_used": len(rag_hits),
            "rag_mode": rag_mode,
            "plan": merged_plan,
        }
    except Exception as exc:
        return _finish_fallback(f"{type(exc).__name__}: {str(exc)[:140]}", endpoint=llm_base, model=active_model_label)


def _rack_mix_profiles_path(root_dir: str) -> Path:
    return config_dir(root_dir) / "rack_mix_profiles.json"


def _compute_rack_set_id(kit_name: str, pads: list[dict] | dict | None) -> str:
    """Identificador determinista de un set multi-banco basado en kit_name + layout (pad, rel_path)."""
    canon_pads: list[tuple[int, str]] = []
    if isinstance(pads, dict):
        for k, v in pads.items():
            if isinstance(v, dict):
                p_num = int(v.get("pad") or v.get("pad_number") or k or 0)
                rel = str(v.get("rel_path") or v.get("relPath") or "").strip()
                if p_num > 0 and rel:
                    canon_pads.append((p_num, rel))
    elif isinstance(pads, list):
        for v in pads:
            if isinstance(v, dict):
                p_num = int(v.get("pad") or v.get("pad_number") or 0)
                rel = str(v.get("rel_path") or v.get("relPath") or "").strip()
                if p_num > 0 and rel:
                    canon_pads.append((p_num, rel))
    canon_pads.sort()
    raw = json.dumps({"kit": str(kit_name or "Rack_Kit").strip(), "layout": canon_pads}, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_profile_pad(item: dict) -> dict[str, Any]:
    """Normaliza un pad para persistencia lossless en BeatOS/config/rack_mix_profiles.json."""
    p_num = int(item.get("pad") or item.get("pad_number") or 0)
    out: dict[str, Any] = {
        "pad": p_num,
        "rel_path": str(item.get("rel_path") or item.get("relPath") or "").strip(),
        "sample_name": str(item.get("sample_name") or item.get("sampleName") or item.get("filename") or "").strip(),
        "sound_type": str(item.get("sound_type") or item.get("soundType") or "PERCUSSION").strip().upper(),
        "volume": round(float(item.get("volume") if item.get("volume") is not None else 0.707946), 6),
        "volume_locked": bool(item.get("volume_locked", True)),
        "pan": round(float(item.get("pan") if item.get("pan") is not None else 0.5), 6),
        "tune": int(item.get("tune") or 0),
        "fine_tune": int(item.get("fine_tune") if item.get("fine_tune") is not None else (item.get("fineTune") or 0)),
        "mute_group": int(item.get("mute_group") if item.get("mute_group") is not None else (item.get("muteGroup") or 0)),
        "submix": int(item.get("submix") or 0),
        "trigger_mode": str(item.get("trigger_mode") or item.get("triggerMode") or "oneshot"),
        "monophonic": bool(item.get("monophonic", True)),
        "root_note": int(item.get("root_note") if item.get("root_note") is not None else (item.get("rootNote") or 0)),
        "key_track": bool(item.get("key_track") if item.get("key_track") is not None else item.get("keyTrack", False)),
        "reverse": bool(item.get("reverse", False)),
        "loop_mode": int(item.get("loop_mode") if item.get("loop_mode") is not None else (item.get("loopMode") or 0)),
        "tail_length": float(item.get("tail_length") if item.get("tail_length") is not None else (item.get("tailLength") or 0.0)),
        "sample_offset": int(item.get("sample_offset") if item.get("sample_offset") is not None else (item.get("sampleOffset") or 0)),
        "pad_link": int(item.get("pad_link") if item.get("pad_link") is not None else (item.get("padLink") or 0)),
    }
    return out


def _normalize_profile_pads_map(pads_in: list[dict] | dict | None) -> dict[str, dict[str, Any]]:
    pads_map: dict[str, dict[str, Any]] = {}
    if isinstance(pads_in, dict):
        for k, v in pads_in.items():
            if not isinstance(v, dict):
                continue
            item = dict(v)
            item.setdefault("pad", int(k) if str(k).isdigit() else 0)
            norm = _normalize_profile_pad(item)
            if 1 <= norm["pad"] <= 160:
                pads_map[str(norm["pad"])] = norm
    elif isinstance(pads_in, list):
        for v in pads_in:
            if not isinstance(v, dict):
                continue
            norm = _normalize_profile_pad(v)
            if 1 <= norm["pad"] <= 160:
                pads_map[str(norm["pad"])] = norm
    return pads_map


def _load_rack_mix_profiles_store(root_dir: str) -> dict[str, Any]:
    path = _rack_mix_profiles_path(root_dir)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("sets"), dict):
                return data
        except (OSError, ValueError):
            pass
    return {"schema_version": 1, "updated_at": datetime.datetime.now().isoformat(), "sets": {}}


def _save_rack_mix_profiles_store(root_dir: str, store: dict[str, Any]) -> None:
    store["schema_version"] = 1
    store["updated_at"] = datetime.datetime.now().isoformat()
    write_state_json(_rack_mix_profiles_path(root_dir), store)


def get_rack_mix_profile(root_dir: str, set_id: str = "") -> dict[str, Any]:
    with _RACK_MIX_PROFILES_LOCK:
        store = _load_rack_mix_profiles_store(root_dir)
    sets = store.get("sets") or {}
    if set_id:
        entry = sets.get(set_id)
        return {
            "success": True,
            "set_id": set_id,
            "found": entry is not None,
            "profile": entry,
            "active_mode": (entry or {}).get("active_mode", "studio_mastering"),
            "available_snapshots": sorted((entry or {}).get("snapshots", {}).keys()),
        }
    return {
        "success": True,
        "schema_version": store.get("schema_version", 1),
        "updated_at": store.get("updated_at"),
        "sets_count": len(sets),
        "sets": {
            sid: {
                "set_id": sid,
                "kit_name": ent.get("kit_name", ""),
                "active_mode": ent.get("active_mode", "studio_mastering"),
                "updated_at": ent.get("updated_at", ""),
                "available_snapshots": sorted((ent.get("snapshots") or {}).keys()),
            }
            for sid, ent in sets.items()
            if isinstance(ent, dict)
        },
    }


def save_rack_mix_profile(root_dir: str, payload: dict) -> dict[str, Any]:
    kit_name = str(payload.get("kit_name") or payload.get("name") or "Rack_Kit").strip()
    pads_map = _normalize_profile_pads_map(payload.get("pads"))
    if not pads_map:
        raise ValueError("Asigna al menos 1 pad al Rack antes de guardar el perfil.")
    mode = str(payload.get("mode") or payload.get("mix_mode") or "studio_mastering").strip().lower()
    if mode not in ("studio_mastering", "live_pa", "baseline_original"):
        raise ValueError("Modo de perfil no válido (usa studio_mastering, live_pa o baseline_original).")
    set_id = str(payload.get("set_id") or "").strip() or _compute_rack_set_id(kit_name, pads_map)
    globals_in = payload.get("globals") if isinstance(payload.get("globals"), dict) else {}
    now_iso = datetime.datetime.now().isoformat()

    with _RACK_MIX_PROFILES_LOCK:
        store = _load_rack_mix_profiles_store(root_dir)
        entry = store["sets"].get(set_id) or {
            "set_id": set_id,
            "kit_name": kit_name,
            "active_mode": "studio_mastering",
            "updated_at": now_iso,
            "snapshots": {},
        }
        entry["kit_name"] = kit_name
        entry["updated_at"] = now_iso
        snaps = entry.setdefault("snapshots", {})
        if "baseline_original" not in snaps:
            snaps["baseline_original"] = {
                "captured_at": now_iso,
                "edited_by_user": True,
                "globals": copy.deepcopy(globals_in),
                "pads": copy.deepcopy(pads_map),
            }
        snaps[mode] = {
            "captured_at": now_iso,
            "edited_by_user": bool(payload.get("edited_by_user", True)),
            "globals": copy.deepcopy(globals_in),
            "pads": copy.deepcopy(pads_map),
        }
        if mode in ("studio_mastering", "live_pa"):
            entry["active_mode"] = mode
        if isinstance(payload.get("last_multibank_digest"), dict):
            entry["last_multibank_digest"] = payload["last_multibank_digest"]
        store["sets"][set_id] = entry
        _save_rack_mix_profiles_store(root_dir, store)

    return {
        "success": True,
        "set_id": set_id,
        "saved_mode": mode,
        "active_mode": entry["active_mode"],
        "available_snapshots": sorted(entry["snapshots"].keys()),
        "pad_count": len(pads_map),
    }


def _synthesize_mode_pads(
    root_dir: str,
    base_pads_map: dict[str, dict[str, Any]],
    target_mode: str,
    style_id: str = "standard",
    bank_trims_db: dict[str, float] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """Sintetiza volúmenes calibrados para target_mode (studio_mastering | live_pa) sin perder otros parámetros."""
    kit_mod = get_hardware_kit_builder(root_dir)
    trims = bank_trims_db if isinstance(bank_trims_db, dict) else {}
    out_pads: dict[str, dict[str, Any]] = {}
    deltas_db: dict[str, float] = {}

    for p_key, p_val in base_pads_map.items():
        p_copy = dict(p_val)
        old_vol = max(1e-6, float(p_copy.get("volume") or 0.501187))
        bank_letter = chr(65 + max(0, min(9, (int(p_copy["pad"]) - 1) // 16)))
        b_trim = float(trims.get(bank_letter, 0.0) or 0.0)
        wav_p = None
        if p_copy.get("rel_path"):
            try:
                cand = resolve_library_path(root_dir, p_copy["rel_path"])
                if cand.is_file():
                    wav_p = cand
            except Exception:
                wav_p = None

        if kit_mod and hasattr(kit_mod, "compute_profiled_pad_volume"):
            calc = kit_mod.compute_profiled_pad_volume(
                p_copy.get("sound_type", "PERCUSSION"),
                wav_p,
                mix_mode=target_mode,
                style_id=style_id,
                bank_trim_db=b_trim,
            )
            new_vol = float(calc.get("volume", old_vol))
        elif kit_mod and hasattr(kit_mod, "compute_smart_pad_volume"):
            base_calc = kit_mod.compute_smart_pad_volume(p_copy.get("sound_type", "PERCUSSION"), wav_p)
            base_db = float(base_calc.get("gain_db", -6.0))
            mode_offset = 2.6 if target_mode == "live_pa" else -0.5
            adj_db = max(-14.0, min(-0.85, base_db + mode_offset + b_trim))
            new_vol = round(10.0 ** (adj_db / 20.0), 6)
        else:
            mode_offset = 2.5 if target_mode == "live_pa" else -2.5
            cur_db = 20.0 * math.log10(old_vol)
            adj_db = max(-14.0, min(-0.85, cur_db + mode_offset + b_trim))
            new_vol = round(10.0 ** (adj_db / 20.0), 6)

        p_copy["volume"] = round(max(0.01, min(1.0, new_vol)), 6)
        p_copy["volume_locked"] = True
        deltas_db[p_key] = round(20.0 * math.log10(max(1e-6, p_copy["volume"]) / old_vol), 2)
        out_pads[p_key] = p_copy

    return out_pads, deltas_db


def switch_rack_mix_profile(root_dir: str, payload: dict) -> dict[str, Any]:
    """
    Transición reversible atómica Studio/Mastering-Safe ↔ Live/PA-Ready:
      1) Guarda baseline_original si no existe.
      2) Persiste el estado saliente en snapshots[from_mode] (nunca pierde ajustes manuales).
      3) Si snapshots[target_mode] existe con el mismo layout y no se pidió force_recompute,
         restaura bit-a-bit ese snapshot; en caso contrario lo sintetiza y persiste.
    """
    kit_name = str(payload.get("kit_name") or payload.get("name") or "Rack_Kit").strip()
    cur_pads_map = _normalize_profile_pads_map(payload.get("pads"))
    if not cur_pads_map:
        raise ValueError("Asigna al menos 1 pad al Rack antes de cambiar de perfil.")

    target_mode = str(payload.get("target_mode") or payload.get("mix_mode") or "live_pa").strip().lower()
    if target_mode not in ("studio_mastering", "live_pa"):
        raise ValueError("target_mode debe ser 'studio_mastering' o 'live_pa'.")
    from_mode = str(payload.get("from_mode") or ("live_pa" if target_mode == "studio_mastering" else "studio_mastering")).strip().lower()
    if from_mode not in ("studio_mastering", "live_pa"):
        from_mode = "studio_mastering"

    style_id = str(payload.get("style_id") or "standard").strip().lower()
    force_recompute = bool(payload.get("force_recompute", False))
    globals_in = payload.get("globals") if isinstance(payload.get("globals"), dict) else {}
    bank_trims_in = payload.get("bank_trims_db") if isinstance(payload.get("bank_trims_db"), dict) else None
    set_id = str(payload.get("set_id") or "").strip() or _compute_rack_set_id(kit_name, cur_pads_map)
    now_iso = datetime.datetime.now().isoformat()

    with _RACK_MIX_PROFILES_LOCK:
        store = _load_rack_mix_profiles_store(root_dir)
        entry = store["sets"].get(set_id) or {
            "set_id": set_id,
            "kit_name": kit_name,
            "active_mode": from_mode,
            "updated_at": now_iso,
            "snapshots": {},
        }
        entry["kit_name"] = kit_name
        entry["updated_at"] = now_iso
        snaps = entry.setdefault("snapshots", {})

        if "baseline_original" not in snaps:
            snaps["baseline_original"] = {
                "captured_at": now_iso,
                "edited_by_user": True,
                "globals": copy.deepcopy(globals_in),
                "pads": copy.deepcopy(cur_pads_map),
            }

        # Persistir estado saliente completo antes de conmutar
        snaps[from_mode] = {
            "captured_at": now_iso,
            "edited_by_user": True,
            "globals": copy.deepcopy(globals_in),
            "pads": copy.deepcopy(cur_pads_map),
        }

        existing_target = snaps.get(target_mode)
        restored_from_snapshot = False
        deltas_db: dict[str, float] = {}

        def _layout_matches(snap_pads: dict) -> bool:
            if not isinstance(snap_pads, dict) or set(snap_pads.keys()) != set(cur_pads_map.keys()):
                return False
            return all(
                str((snap_pads.get(k) or {}).get("rel_path") or "") == str(cur_pads_map[k].get("rel_path") or "")
                for k in cur_pads_map
            )

        if not force_recompute and isinstance(existing_target, dict) and _layout_matches(existing_target.get("pads") or {}):
            target_pads_map = copy.deepcopy(existing_target["pads"])
            target_globals = copy.deepcopy(existing_target.get("globals") or globals_in)
            for k, p_new in target_pads_map.items():
                old_v = max(1e-6, float((cur_pads_map.get(k) or {}).get("volume") or 0.501187))
                new_v = max(1e-6, float(p_new.get("volume") or old_v))
                deltas_db[k] = round(20.0 * math.log10(new_v / old_v), 2)
            restored_from_snapshot = True
        else:
            source_for_synth = (snaps.get("studio_mastering") or {}).get("pads") if (target_mode == "live_pa" and isinstance(snaps.get("studio_mastering"), dict)) else cur_pads_map
            if not _layout_matches(source_for_synth or {}):
                source_for_synth = cur_pads_map
            trims = bank_trims_in
            if trims is None and isinstance(entry.get("last_multibank_digest"), dict):
                trims = entry["last_multibank_digest"].get("bank_trims_db")
            target_pads_map, deltas_db = _synthesize_mode_pads(
                root_dir,
                source_for_synth,
                target_mode,
                style_id=style_id,
                bank_trims_db=trims,
            )
            target_globals = copy.deepcopy(globals_in)
            target_globals["mix_mode"] = target_mode
            target_globals["master_bus_db"] = -1.0 if target_mode == "live_pa" else -3.0
            snaps[target_mode] = {
                "captured_at": now_iso,
                "edited_by_user": False,
                "globals": copy.deepcopy(target_globals),
                "pads": copy.deepcopy(target_pads_map),
            }

        entry["active_mode"] = target_mode
        store["sets"][set_id] = entry
        _save_rack_mix_profiles_store(root_dir, store)

    return {
        "success": True,
        "set_id": set_id,
        "active_mode": target_mode,
        "restored_from_snapshot": restored_from_snapshot,
        "pads": [target_pads_map[k] for k in sorted(target_pads_map, key=lambda x: int(x))],
        "pads_map": target_pads_map,
        "globals": target_globals,
        "deltas_db": deltas_db,
        "available_snapshots": sorted(entry["snapshots"].keys()),
    }


def reset_rack_mix_profile(root_dir: str, payload: dict) -> dict[str, Any]:
    """Restaura baseline_original de forma exacta (o borra un snapshot concreto para regenerarlo)."""
    kit_name = str(payload.get("kit_name") or payload.get("name") or "Rack_Kit").strip()
    cur_pads_map = _normalize_profile_pads_map(payload.get("pads"))
    set_id = str(payload.get("set_id") or "").strip() or (
        _compute_rack_set_id(kit_name, cur_pads_map) if cur_pads_map else ""
    )
    if not set_id:
        raise ValueError("Se requiere set_id o pads activos para restaurar el perfil.")
    clear_snapshot = str(payload.get("clear_snapshot") or "").strip().lower()

    with _RACK_MIX_PROFILES_LOCK:
        store = _load_rack_mix_profiles_store(root_dir)
        entry = store["sets"].get(set_id)
        if not isinstance(entry, dict):
            raise ValueError("No existe un snapshot guardado para este set todavía.")
        snaps = entry.get("snapshots") or {}
        if clear_snapshot in ("studio_mastering", "live_pa"):
            snaps.pop(clear_snapshot, None)
            entry["updated_at"] = datetime.datetime.now().isoformat()
            _save_rack_mix_profiles_store(root_dir, store)
            return {
                "success": True,
                "set_id": set_id,
                "cleared": clear_snapshot,
                "active_mode": entry.get("active_mode", "studio_mastering"),
                "available_snapshots": sorted(snaps.keys()),
            }
        baseline = snaps.get("baseline_original")
        if not isinstance(baseline, dict) or not isinstance(baseline.get("pads"), dict):
            raise ValueError("No se encontró snapshot baseline_original para este set.")
        restored_pads = copy.deepcopy(baseline["pads"])
        restored_globals = copy.deepcopy(baseline.get("globals") or {})
        entry["active_mode"] = "studio_mastering"
        snaps["studio_mastering"] = {
            "captured_at": datetime.datetime.now().isoformat(),
            "edited_by_user": True,
            "globals": copy.deepcopy(restored_globals),
            "pads": copy.deepcopy(restored_pads),
        }
        entry["updated_at"] = datetime.datetime.now().isoformat()
        _save_rack_mix_profiles_store(root_dir, store)

    return {
        "success": True,
        "set_id": set_id,
        "active_mode": "studio_mastering",
        "restored_from": "baseline_original",
        "pads": [restored_pads[k] for k in sorted(restored_pads, key=lambda x: int(x))],
        "pads_map": restored_pads,
        "globals": restored_globals,
        "available_snapshots": sorted(entry["snapshots"].keys()),
    }


def _fallback_multibank_coherence(
    pad_reports: list[dict],
    *,
    mix_mode: str = "studio_mastering",
    style_id: str = "standard",
    bpm: float = 90.0,
    swing_pct: float = 50.0,
) -> dict[str, Any]:
    """Coherencia multi-banco A-H de respaldo si hardware_kit_builder.analyze_multibank_coherence aún no está cargado."""
    banks_grouped: dict[int, list[dict]] = {}
    for pr in pad_reports:
        p_num = int(pr.get("pad") or 1)
        b_idx = max(0, min(7, (p_num - 1) // 16))
        banks_grouped.setdefault(b_idx, []).append(pr)

    banks_summary: list[dict[str, Any]] = []
    lufs_values: list[float] = []
    pad_outliers: list[dict[str, Any]] = []
    sub_mono_risk_pads: list[int] = []
    subsonic_pa_risk_pads: list[int] = []

    for b_idx in sorted(banks_grouped.keys()):
        b_let = chr(65 + b_idx)
        b_pads = banks_grouped[b_idx]
        roles: dict[str, int] = {}
        rms_vals: list[float] = []
        lufs_vals: list[float] = []
        peaks: list[float] = []
        tpeaks: list[float] = []
        crests: list[float] = []
        lows: list[float] = []
        notes: list[str] = []
        for pr in b_pads:
            st = str(pr.get("sound_type") or "PERCUSSION")
            roles[st] = roles.get(st, 0) + 1
            if float(pr.get("rms_dbfs", -120.0)) > -90.0:
                rms_vals.append(float(pr["rms_dbfs"]))
            l_est = float(pr.get("lufs_active_est", pr.get("rms_dbfs", -120.0)))
            if l_est > -90.0:
                lufs_vals.append(l_est)
            if float(pr.get("peak_dbfs", -120.0)) > -90.0:
                peaks.append(float(pr["peak_dbfs"]))
            tp = float(pr.get("true_peak_dbtp", pr.get("peak_dbfs", -120.0)))
            if tp > -90.0:
                tpeaks.append(tp)
            if float(pr.get("crest_db", 0.0)) > 0.0:
                crests.append(float(pr["crest_db"]))
            lows.append(float(pr.get("low_energy_ratio", 0.0)))
            if pr.get("detected_note"):
                notes.append(str(pr["detected_note"]))

            issues = []
            if pr.get("clipping_risk") or tp > -0.8:
                issues.append("clipping_risk")
            if 0.0 < float(pr.get("crest_db", 0.0)) < 7.0:
                issues.append("overcompressed")
            if float(pr.get("subsonic_ratio_35hz", 0.0)) > 0.18:
                issues.append("subsonic_pa_risk")
                subsonic_pa_risk_pads.append(int(pr["pad"]))
            if float(pr.get("low_energy_ratio", 0.0)) > 0.45 and float(pr.get("low_stereo_corr_120hz", 1.0)) < 0.70:
                issues.append("sub_mono_risk")
                sub_mono_risk_pads.append(int(pr["pad"]))
            if issues:
                pad_outliers.append({
                    "pad": int(pr["pad"]),
                    "bank": b_let,
                    "sample_name": pr.get("sample_name", ""),
                    "role": st,
                    "peak_dbfs": pr.get("peak_dbfs", -120.0),
                    "true_peak_dbtp": tp,
                    "rms_dbfs": pr.get("rms_dbfs", -120.0),
                    "crest_db": pr.get("crest_db", 0.0),
                    "issue": "+".join(issues),
                    "recommendation": "Bajar ganancia a -1.0 dBTP y aplicar HPF subsónico 32 Hz" if "clipping_risk" in issues or "subsonic_pa_risk" in issues else "Revisar mono <120 Hz / dinámica",
                })

        dom_role = max(roles.items(), key=lambda kv: kv[1])[0] if roles else "MIXED"
        b_lufs = round(sum(lufs_vals) / len(lufs_vals), 2) if lufs_vals else -16.0
        lufs_values.append(b_lufs)
        banks_summary.append({
            "bank": b_let,
            "bank_idx": b_idx,
            "pad_count": len(b_pads),
            "dominant_role": dom_role,
            "dominant_key": notes[0] if notes else "",
            "camelot": "",
            "bank_lufs_est": b_lufs,
            "avg_rms_dbfs": round(sum(rms_vals) / len(rms_vals), 2) if rms_vals else -16.0,
            "max_peak_dbfs": round(max(peaks), 2) if peaks else -120.0,
            "bank_max_true_peak_dbtp": round(max(tpeaks), 2) if tpeaks else -120.0,
            "crest_avg_db": round(sum(crests) / len(crests), 2) if crests else 0.0,
            "sub_ratio_avg": round(sum(lows) / len(lows), 3) if lows else 0.0,
            "roles": roles,
            "intra_bank_phase_warnings": [],
        })

    sorted_lufs = sorted(lufs_values)
    median_lufs = sorted_lufs[len(sorted_lufs) // 2] if sorted_lufs else -16.0
    spread_db = round((max(lufs_values) - min(lufs_values)), 2) if len(lufs_values) >= 2 else 0.0
    bank_trims_db: dict[str, float] = {}
    for bs in banks_summary:
        diff = median_lufs - float(bs["bank_lufs_est"])
        trim = round(max(-3.0, min(3.0, diff)), 2) if abs(diff) > 1.0 else 0.0
        bank_trims_db[bs["bank"]] = trim
        bs["recommended_bank_trim_db"] = trim

    duck = _fallback_ducking_recipe(style_id, bpm, mix_mode, swing_pct=swing_pct)
    return {
        "banks_summary": banks_summary,
        "pad_outliers": pad_outliers,
        "global_coherence": {
            "active_banks": [b["bank"] for b in banks_summary],
            "median_bank_lufs": round(median_lufs, 2),
            "bank_rms_spread_db": spread_db,
            "bank_trims_db": bank_trims_db,
            "camelot_clashes_between_banks": [],
            "sub_mono_risk_pads": sorted(set(sub_mono_risk_pads)),
            "subsonic_pa_risk_pads": sorted(set(subsonic_pa_risk_pads)),
        },
        "master_bus_plan": {
            "mix_mode": mix_mode,
            "target_mixer_volume": 0.7943282347242815 if mix_mode == "live_pa" else 0.7079457640647888,
            "target_output_volume": 0.8912509381337456 if mix_mode == "live_pa" else 0.7079457640647888,
            "true_peak_ceiling_dbtp": -1.0,
            "subsonic_hpf_hz": 32 if mix_mode == "live_pa" else 24,
        },
        "ducking_recipe": duck,
    }


def analyze_rack_with_cerebro(root_dir: str, payload: dict, *, port: int | None = None) -> dict:
    """Analiza acústicamente los pads del Rack (individual, por banco A–H y coherencia global) + Cerebro OS MLX."""
    import math
    import struct
    import wave

    kit_mod = get_hardware_kit_builder(root_dir)
    kit_name = str(payload.get("kit_name") or payload.get("name") or "Rack Kit").strip()
    current_tempo = float(payload.get("tempo") or 120.0)
    pads_in = payload.get("pads") or []
    scope = str(payload.get("scope") or "all_banks").strip().lower()
    if scope not in ("all_banks", "active_bank", "single_pad"):
        scope = "all_banks"
    target_bank = payload.get("target_bank")
    target_pad = payload.get("target_pad")
    mix_mode = str(payload.get("mix_mode") or payload.get("scenario") or "studio_mastering").strip().lower()
    if mix_mode not in ("studio_mastering", "live_pa"):
        mix_mode = "studio_mastering"

    filtered_pads_in = []
    for item in pads_in:
        if not isinstance(item, dict):
            continue
        p_num = int(item.get("pad") or item.get("pad_number") or 0)
        if not 1 <= p_num <= 128:
            continue
        if scope == "single_pad" and target_pad is not None and p_num != int(target_pad):
            continue
        if scope == "active_bank" and target_bank is not None and ((p_num - 1) // 16) != int(target_bank):
            continue
        filtered_pads_in.append(item)
    if not filtered_pads_in and pads_in:
        filtered_pads_in = [x for x in pads_in if isinstance(x, dict)]

    pad_reports = []
    text_tokens = [kit_name]
    sub_heavy_count = 0
    open_hat_count = 0
    closed_hat_count = 0
    candidate_loop_wav: Optional[Path] = None
    candidate_loop_score = ()
    reference_sample = None
    reference_style = None
    rhythm_hints = {}
    melodic_roles = {"MELODIC_LOOP", "KEYS_SYNTH", "VOCAL"}
    drum_roles = {"KICK", "SNARE", "TOM", "CLAP", "HIHAT", "CYMBAL", "PERCUSSION", "DRUM_LOOP"}

    for item in filtered_pads_in:
        p_num = int(item.get("pad") or item.get("pad_number") or 0)
        if not 1 <= p_num <= 128:
            continue
        sname = str(item.get("sample_name") or item.get("sampleName") or "").strip()
        rel_path = str(item.get("rel_path") or item.get("relPath") or "").strip()
        stype = str(item.get("sound_type") or item.get("soundType") or "").strip().upper()
        text_tokens.append(f"{sname} {rel_path}")
        filename = Path(rel_path).name or sname
        label_style = kit_mod.detect_musical_style(filename) if kit_mod else {"id": "standard"}

        if not stype or stype == "SAMPLE":
            stype = kit_mod.detect_sound_type(sname or rel_path) if kit_mod else "PERCUSSION"

        # Delegar análisis físico-acústico estéreo en hardware_kit_builder.analyze_sample_acoustics (sin parser mono duplicado)
        ac: dict[str, Any] = {}
        zcr_hz = 0.0
        acoustic_role = stype
        resolved_wav: Optional[Path] = None

        if rel_path:
            try:
                wav_path = resolve_library_path(root_dir, rel_path)
                if wav_path.is_file():
                    resolved_wav = wav_path
                    if kit_mod and hasattr(kit_mod, "analyze_sample_acoustics"):
                        ac = kit_mod.analyze_sample_acoustics(wav_path) or {}
                    if wav_path.suffix.lower() == ".wav":
                        try:
                            with wave.open(str(wav_path), "rb") as wf:
                                n_ch = max(1, wf.getnchannels())
                                sw = wf.getsampwidth()
                                fr = wf.getframerate() or 44100
                                n_frames = wf.getnframes()
                                if not ac.get("duration_sec"):
                                    duration_sec = round(n_frames / float(fr), 3) if fr else 0.0
                                read_n = min(n_frames, int(fr * 1.5), 66150)
                                raw = wf.readframes(read_n)
                                if sw == 2 and read_n > 32:
                                    total_s = len(raw) // 2
                                    samps = struct.unpack(f"<{total_s}h", raw[: total_s * 2])
                                    if n_ch > 1:
                                        channels = (samps[ch::n_ch] for ch in range(n_ch))
                                        mono = max(channels, key=lambda channel: sum(x * x for x in channel))
                                    else:
                                        mono = samps
                                    if len(mono) > 16:
                                        zc = sum(1 for i in range(1, len(mono)) if (mono[i - 1] >= 0) != (mono[i] >= 0))
                                        zcr_hz = round((zc * fr) / (2.0 * len(mono)), 1)
                        except Exception:
                            pass
            except Exception:
                pass

        duration_sec = float(ac.get("duration_sec") or 0.0)
        low_ratio = float(ac.get("low_energy_ratio") or 0.0)
        crest_db = float(ac.get("crest_factor_db") or 0.0)
        dc_offset_val = float(ac.get("dc_offset") or 0.0)
        true_peak_dbtp = float(ac.get("true_peak_dbtp") if ac.get("true_peak_dbtp") is not None else ac.get("peak_dbfs", -120.0))
        lufs_active_est = float(ac.get("lufs_active_est") if ac.get("lufs_active_est") is not None else ac.get("rms_active_dbfs", -120.0))
        subsonic_ratio_35hz = float(ac.get("subsonic_ratio_35hz") or 0.0)
        low_stereo_corr_120hz = float(ac.get("low_stereo_corr_120hz") if ac.get("low_stereo_corr_120hz") is not None else ac.get("stereo_correlation", 1.0))

        # Refinamiento acústico del rol sonoro
        low_sname = sname.lower()
        is_tom = bool(kit_mod and kit_mod.re.search(r"(?:^|[\s_\-.])(?:tom|flr|floor\s*tom)(?:[\s_\-.0-9]|$)", low_sname))
        if stype in ("BASS_808", "KICK") and low_ratio >= 0.62 and duration_sec >= 0.42:
            acoustic_role = "BASS_808" if ("808" in low_sname or "sub" in low_sname or duration_sec >= 0.65) else "SUB_KICK"
            sub_heavy_count += 1
        elif stype == "HIHAT" or (zcr_hz >= 2600 and low_ratio < 0.15 and stype == "PERCUSSION" and not is_tom):
            if "open" in low_sname or "oh" in low_sname or duration_sec >= 0.24:
                acoustic_role = "HIHAT_OPEN"
                open_hat_count += 1
            else:
                acoustic_role = "HIHAT_CLOSED"
                closed_hat_count += 1
            stype = "HIHAT"
        elif is_tom:
            acoustic_role = "TOM"

        if stype in drum_roles and label_style["id"] != "standard":
            style_key = label_style["id"]
            hint = rhythm_hints.setdefault(style_key, {"label": label_style["style"], "pads": []})
            hint["pads"].append(p_num)

        if resolved_wav is not None and duration_sec >= 0.85:
            tagged_bpm = kit_mod._extract_explicit_bpm_from_text(filename) if kit_mod else None
            score = (stype in melodic_roles, stype in {"MELODIC_LOOP", "KEYS_SYNTH"},
                     label_style["id"] != "standard", bool(tagged_bpm), min(duration_sec, 24.0), -p_num)
            if score > candidate_loop_score:
                candidate_loop_score = score
                candidate_loop_wav = resolved_wav
                reference_sample = {"pad": p_num, "filename": filename, "sound_type": stype,
                                    "tagged_bpm": tagged_bpm}
                reference_style = label_style

        if kit_mod and hasattr(kit_mod, "compute_profiled_pad_volume"):
            studio_vol_info = kit_mod.compute_profiled_pad_volume(stype, resolved_wav, mix_mode="studio_mastering")
            live_vol_info = kit_mod.compute_profiled_pad_volume(stype, resolved_wav, mix_mode="live_pa")
            smart_vol = live_vol_info if mix_mode == "live_pa" else studio_vol_info
        elif kit_mod and hasattr(kit_mod, "compute_smart_pad_volume"):
            smart_vol = kit_mod.compute_smart_pad_volume(stype, resolved_wav)
            studio_vol_info = smart_vol
            live_gain_db = max(-12.0, min(-0.85, float(smart_vol.get("gain_db", -6.0)) + 2.5))
            live_vol_info = {**smart_vol, "gain_db": round(live_gain_db, 3), "volume": round(10.0 ** (live_gain_db / 20.0), 6)}
        else:
            smart_vol = {"volume": 0.501187, "gain_db": -6.0, "peak_dbfs": -120.0, "rms_dbfs": -120.0}
            studio_vol_info = smart_vol
            live_vol_info = {"volume": 0.668344, "gain_db": -3.5, "peak_dbfs": -120.0, "rms_dbfs": -120.0}

        bank_idx = (p_num - 1) // 16
        pad_reports.append({
            "pad": p_num,
            "bank": chr(65 + bank_idx),
            "bank_idx": bank_idx,
            "sample_name": sname,
            "rel_path": rel_path,
            "sound_type": stype,
            "acoustic_role": acoustic_role,
            "channels": int(ac.get("channels") or 1),
            "sample_rate": int(ac.get("sample_rate") or 44100),
            "volume": float(item.get("volume") if item.get("volume") is not None else smart_vol["volume"]),
            "duration_sec": duration_sec,
            "zcr_hz": zcr_hz,
            "low_energy_ratio": low_ratio,
            "crest_db": crest_db,
            "true_peak_dbtp": round(true_peak_dbtp, 2),
            "lufs_active_est": round(lufs_active_est, 2),
            "subsonic_ratio_35hz": round(subsonic_ratio_35hz, 3),
            "low_stereo_corr_120hz": round(low_stereo_corr_120hz, 3),
            "stereo_correlation": round(float(ac.get("stereo_correlation", 1.0)), 3),
            "f0_hz": 0.0,
            "detected_note": "",
            "pitch_class": None,
            "f0_pitch_class": None,
            "cents_offset": 0,
            "tuning_cents_drift": 0,
            "dc_offset": dc_offset_val,
            "clipping_risk": bool(resolved_wav is not None and (float(smart_vol.get("peak_dbfs", -120.0)) >= -0.75 or true_peak_dbtp >= -0.80)),
            "dc_offset_warning": bool(abs(dc_offset_val) >= 0.015),
            "recommended_tune": int(item.get("tune") or 0),
            "recommended_fine_tune": 0,
            "recommended_root_note": 0,
            "recommended_trigger_mode": "noteon" if ((acoustic_role == "BASS_808" and duration_sec >= 0.8) or stype == "MELODIC_LOOP") else "oneshot",
            "recommended_volume": smart_vol["volume"],
            "recommended_volume_studio": studio_vol_info["volume"],
            "recommended_volume_live": live_vol_info["volume"],
            "hierarchical_volume": kit_mod.default_pad_volume(stype, "hierarchical_a") if kit_mod else 0.501187,
            "uniform_volume": 0.501187,
            "recommended_gain_db": smart_vol["gain_db"],
            "peak_dbfs": smart_vol.get("peak_dbfs", ac.get("peak_dbfs", -120.0)),
            "rms_dbfs": smart_vol.get("rms_dbfs", ac.get("rms_active_dbfs", -120.0)),
        })

    # Detección jerárquica de tono fundamental:
    # 1) Loops melódicos / Keys / Vocals (los más largos primero)
    # 2) Confirmación secundaria con 808s y Kicks tonales (sin inventar C en batería seca atonal)
    anchor_pc = None
    anchor_note_label = ""
    anchor_full_key = ""
    key_source = "atonal_drums"
    confirmed_by_drums = False
    rack_wavs: list[Path] = []
    if kit_mod and hasattr(kit_mod, "detect_sample_pitch_and_key"):
        melodic_candidates = []
        bass_candidates = []
        kick_candidates = []
        for pr in pad_reports:
            if not pr.get("rel_path"):
                continue
            is_mel = pr["sound_type"] in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL", "STEM") or (pr.get("duration_sec", 0.0) >= 1.4 and pr["sound_type"] not in ("DRUM_LOOP", "KICK", "SNARE", "CLAP", "HIHAT", "CYMBAL", "TOM", "FX"))
            is_bass = pr["sound_type"] == "BASS_808" or pr["acoustic_role"] == "BASS_808"
            is_kick = pr["sound_type"] == "KICK" or pr["acoustic_role"] == "SUB_KICK"
            try:
                wav_p = resolve_library_path(root_dir, pr["rel_path"])
                if wav_p.is_file():
                    rack_wavs.append(wav_p)
                    if is_mel or is_bass or is_kick:
                        pinfo = kit_mod.detect_sample_pitch_and_key(wav_p)
                        pr["f0_hz"] = pinfo.get("f0_hz", 0.0)
                        pr["detected_note"] = pinfo.get("note", "")
                        pr["pitch_class"] = pinfo.get("pitch_class")
                        pr["f0_pitch_class"] = pinfo.get("f0_pitch_class")
                        pr["cents_offset"] = pinfo.get("cents_offset", 0)
                        pr["tuning_cents_drift"] = pinfo.get("tuning_cents_drift", pinfo.get("cents_offset", 0))
                        conf = float(pinfo.get("confidence") or 0.0)
                        if float(pinfo.get("f0_hz") or 0.0) > 0.0:
                            pr["recommended_root_note"] = int(pinfo.get("midi_note") or 0)
                            pr["recommended_fine_tune"] = max(-90, min(90, -int(round(float(pinfo.get("cents_offset") or 0)))))
                        if is_mel and pinfo.get("pitch_class") is not None and conf >= 0.45:
                            melodic_candidates.append((float(pr.get("duration_sec") or 0.0), conf, pr, pinfo))
                        elif is_bass and pinfo.get("pitch_class") is not None and conf >= 0.48:
                            bass_candidates.append((conf, pr, pinfo))
                        elif is_kick and pinfo.get("pitch_class") is not None and conf >= 0.62:
                            kick_candidates.append((conf, pr, pinfo))
            except Exception:
                pass

        if melodic_candidates:
            melodic_candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
            _, _, best_pr, best_pinfo = melodic_candidates[0]
            anchor_pc = best_pr["pitch_class"]
            anchor_full_key = str(best_pinfo.get("key") or "")
            anchor_note_label = anchor_full_key or str(best_pinfo.get("note_root") or best_pinfo.get("note") or "")
            key_source = "melodic_loop"
            for _, d_pr, _ in (bass_candidates + kick_candidates):
                eff_d_pc = d_pr.get("f0_pitch_class") if (d_pr.get("f0_hz", 0.0) > 0.0 and d_pr.get("f0_pitch_class") is not None) else d_pr["pitch_class"]
                if (int(eff_d_pc) - int(anchor_pc)) % 12 in (0, 7):
                    confirmed_by_drums = True
                    break
        elif bass_candidates:
            bass_candidates.sort(key=lambda t: t[0], reverse=True)
            _, best_pr, best_pinfo = bass_candidates[0]
            anchor_pc = best_pr.get("f0_pitch_class") if (best_pr.get("f0_hz", 0.0) > 0.0 and best_pr.get("f0_pitch_class") is not None) else best_pr["pitch_class"]
            anchor_full_key = str(best_pinfo.get("key") or "")
            anchor_note_label = anchor_full_key or str(best_pinfo.get("note_root") or best_pinfo.get("note") or "")
            key_source = "808_tonal"
            confirmed_by_drums = True
        else:
            anchor_note_label = "Percusión / Atonal"
            key_source = "atonal_drums"

        if anchor_pc is not None:
            for pr in pad_reports:
                eff_b_pc = pr.get("f0_pitch_class") if (pr.get("f0_hz", 0.0) > 0.0 and pr.get("f0_pitch_class") is not None) else pr.get("pitch_class")
                if (pr["sound_type"] == "BASS_808" or pr["acoustic_role"] == "BASS_808") and eff_b_pc is not None:
                    diff = (anchor_pc - int(eff_b_pc)) % 12
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
    fallback_style = {"id": "standard", "style": "Hip-Hop / Electrónica",
                      "bpm": current_tempo, "mute_profile": "punch_clean"}
    kit_style = kit_mod.detect_musical_style(Path(kit_name).name) if kit_mod else fallback_style
    style_basis = ("sample_label" if reference_style and reference_style["id"] != "standard" else
                   "kit_label" if kit_style["id"] != "standard" else "undetermined")
    bpm_source = "genre_inference"
    if kit_mod and rack_wavs and hasattr(kit_mod, "analyze_kit_key_and_bpm"):
        kit_meta = kit_mod.analyze_kit_key_and_bpm(
            kit_name,
            rack_wavs,
            project_tempo=current_tempo,
            expansion_hint=kit_name,
        )
        inferred_bpm = float(kit_meta.get("bpm") or current_tempo)
        bpm_source = str(kit_meta.get("bpm_source") or "genre_inference")
        if (not anchor_note_label or anchor_note_label == "Percusión / Atonal") and kit_meta.get("musical_key"):
            anchor_note_label = str(kit_meta["musical_key"])
            key_source = str(kit_meta.get("key_source") or key_source)
            confirmed_by_drums = bool(kit_meta.get("confirmed_by_drums", confirmed_by_drums))
    else:
        inferred_bpm = (reference_sample or {}).get("tagged_bpm") or (
            kit_mod.infer_kit_bpm(kit_name or combined_text, fallback=current_tempo) if kit_mod else current_tempo
        )

    # Análisis de Patrón Rítmico del sample melódico/loop principal ANTES de puntuar el estilo
    rhythm_analysis = None
    hiphop_adaptation = None
    adapt_mode = str(payload.get("adapt_mode") or "auto").strip().lower()
    crate_digging_styles = (
        "bolero", "oldies", "soul_vintage", "jazz_hop", "lofi", "boombap", "rnb_soul", "funk_jazz",
        "drumless", "bossa_samba", "cumbia_son", "tango_vals", "psych_library",
    )
    if kit_mod and hasattr(kit_mod, "analyze_rhythmic_pattern_and_hiphop_adaptation"):
        if candidate_loop_wav is not None and candidate_loop_wav.is_file():
            try:
                loop_style_hint = reference_sample["filename"] if reference_sample else f"{kit_name} {candidate_loop_wav.stem}".strip()
                rhythm_bundle = kit_mod.analyze_rhythmic_pattern_and_hiphop_adaptation(
                    candidate_loop_wav,
                    style_hint=loop_style_hint,
                    target_bpm_hint=current_tempo if current_tempo != 120.0 else None,
                    adapt_mode=adapt_mode,
                )
                rhythm_analysis = rhythm_bundle.get("rhythm_analysis")
                hiphop_adaptation = rhythm_bundle.get("hiphop_adaptation")
            except Exception:
                rhythm_analysis = None
                hiphop_adaptation = None

    # Clasificación multimodal ponderada de estilo (prioriza sample melódico principal + consenso + coherencia DSP)
    bpm_for_style = (
        float(rhythm_analysis.get("effective_source_bpm") or rhythm_analysis.get("source_bpm") or inferred_bpm)
        if isinstance(rhythm_analysis, dict)
        else (inferred_bpm if abs(inferred_bpm - 120.0) > 0.25 else (current_tempo if current_tempo != 120.0 else None))
    )
    if kit_mod and hasattr(kit_mod, "detect_kit_style_weighted"):
        style_info = kit_mod.detect_kit_style_weighted(
            kit_name=kit_name,
            pad_reports=pad_reports,
            bpm=bpm_for_style,
            sub_heavy_count=sub_heavy_count,
            rhythm_analysis=rhythm_analysis,
            fallback_text=combined_text,
        )
    elif kit_mod and hasattr(kit_mod, "detect_musical_style"):
        style_info = kit_mod.detect_musical_style(combined_text, bpm=current_tempo if current_tempo != 120.0 else None)
    else:
        style_info = dict(fallback_style)
    style_id = style_info.get("id", "standard")
    secondary_styles = style_info.get("secondary_styles") or []
    style_evidence = str(style_info.get("style_evidence") or "")

    # Si el análisis acústico detecta colas subgraves/808 densas (>=2), priorizar perfil club_clean
    recommended_profile = style_info.get("mute_profile", "punch_clean")
    if sub_heavy_count >= 2 and recommended_profile in ("real_drums", "punch_clean"):
        recommended_profile = "club_clean"
    elif sub_heavy_count == 0 and style_id in ("lofi", "jazz_hop", "boombap", "drumless", "bolero", "oldies", "soul_vintage") and recommended_profile == "club_clean":
        recommended_profile = "jazz_funk" if style_id != "boombap" else "real_drums"

    is_crate_digging_style = style_id in crate_digging_styles
    if kit_mod and hasattr(kit_mod, "analyze_rhythmic_pattern_and_hiphop_adaptation"):
        if rhythm_analysis is None and is_crate_digging_style:
            src_b = round(float(inferred_bpm or style_info.get("bpm") or 86.0), 1)
            mode_bpm_map = {"lofi_chill": 82.0, "boombap_classic": 90.0, "dilla_jazzhop": 86.0, "drumless_alchemist": 78.0}
            default_tgt = 78.0 if style_id == "drumless" else (82.0 if style_id == "tango_vals" else (84.0 if style_id in ("bolero", "bossa_samba", "oldies") else (86.0 if style_id in ("soul_vintage", "lofi", "psych_library") else (90.0 if style_id == "boombap" else 88.0))))
            tgt_b = round(float(mode_bpm_map.get(adapt_mode, default_tgt)), 1)
            eff_b = round(src_b / 2.0, 1) if src_b >= 132.0 else src_b
            half_applied = bool(src_b >= 132.0)
            low_comb = kit_name.lower()
            ts_fb = (
                "3/4" if any(k in low_comb for k in ("vals", "waltz", "3/4"))
                else ("12/8" if (re.search(r"(?:^|[\W_])12[/_\-]8(?:$|[\W_])", low_comb) or ("4/4" not in low_comb and any(k in low_comb for k in ("doo wop", "doo-wop", "doowop", "lowrider", "oldies"))))
                      else ("6/8" if "6/8" in low_comb else ("5/4" if "5/4" in low_comb else "4/4")))
            )
            swing_fb = 60.0 if style_id == "oldies" or ts_fb == "12/8" else (58.0 if style_id in ("soul_vintage", "jazz_hop", "bossa_samba") else 54.0)
            if hasattr(kit_mod, "_compute_hiphop_adaptation_profile") and hasattr(kit_mod, "_build_adaptation_profiles_and_sequencer"):
                main_prof = kit_mod._compute_hiphop_adaptation_profile(adapt_mode, "Hip-Hop / Lo-Fi", eff_b, tgt_b, half_applied)
                profiles, seq_guide = kit_mod._build_adaptation_profiles_and_sequencer(
                    eff_b, half_applied, style_id, ts_fb, swing_fb, 0.25, adapt_mode
                )
            else:
                ratio = max(0.55, min(1.85, tgt_b / max(30.0, eff_b)))
                semi_f = max(-7.0, min(7.0, 12.0 * math.log2(ratio)))
                semi_i = int(round(semi_f))
                cents_i = int(round((semi_f - semi_i) * 100))
                main_prof = {
                    "target_bpm": tgt_b, "stretch_ratio": round(ratio, 4),
                    "repitch_semitones": semi_i, "repitch_fine_tune_cents": cents_i,
                }
                profiles, seq_guide = [], {}
            clave_map = {
                "bolero": "Tresillo / Cinquillo Cubano (3:3:2)",
                "oldies": "Arpegio Tresillo 12/8 (Doo-Wop / Lowrider Oldies)" if ts_fb == "12/8" else "Backbeat Shuffle / Motown 60s (2 y 4)",
                "bossa_samba": "Clave Bossa / Samba (3-2 / Partido Alto)",
                "cumbia_son": "Clave Son / Cumbia (3-2 & Contratiempo)",
                "tango_vals": "Vals / Ternario (1-2-3)" if ts_fb == "3/4" else "Tango Marcato (4/4)",
                "jazz_hop": "Jazz Ride / Triplet Swing",
                "drumless": "Fraseo Libre / Drumless Rubato",
            }
            rhythm_analysis = {
                "basis": "kit_label",
                "source_bpm": src_b,
                "effective_source_bpm": eff_b,
                "time_signature": ts_fb,
                "groove_pattern": (
                    "Bolero Clásico / Tresillo Melódico" if style_id == "bolero"
                    else ("Doo-Wop / Sweet Soul Ballad (12/8)" if (style_id == "oldies" and ts_fb == "12/8")
                          else ("Lowrider Oldies / Backbeat Shuffle" if style_id == "oldies"
                                else ("Soul Swing Vintage / Backbeat" if style_id == "soul_vintage" else ("Jazz Swing / Chord Phrasing" if style_id == "jazz_hop" else f"{style_info.get('style', 'Hip-Hop / Lo-Fi')}"))))
                ),
                "clave_pattern": clave_map.get(style_id, "Backbeat 2 y 4 (4/4)"),
                "swing_pct": swing_fb,
                "rubato_index": 0.22 if style_id in ("bolero", "drumless", "tango_vals") else 0.08,
                "onset_count": 0,
                "duration_sec": 0.0,
                "timbre_profile": "vintage_oldies" if style_id == "oldies" else "warm_analog",
                "timbre_label": "Cinta Vintage 50s/60s (Oldies)" if style_id == "oldies" else "Orgánico / Referencia de Kit",
            }
            hiphop_adaptation = {
                "basis": "kit_label",
                "target_style": "Hip-Hop / Lo-Fi" if style_id in ("bolero", "oldies", "lofi", "bossa_samba", "drumless") else "Boom Bap & Lo-Fi",
                "adapt_mode": adapt_mode,
                "target_bpm": main_prof["target_bpm"],
                "stretch_ratio": main_prof["stretch_ratio"],
                "repitch_semitones": main_prof["repitch_semitones"],
                "repitch_fine_tune_cents": main_prof["repitch_fine_tune_cents"],
                "half_time_applied": half_applied,
                "recommended_chop_mode": "phrase_3_4_to_4_4" if ts_fb in ("3/4", "6/8", "12/8") else "transients",
                "adaptation_profiles": profiles,
                "sequencer_guide": seq_guide,
                "meter_bridge_note": (
                    "Para adaptar este kit orgánico a Hip-Hop o Lo-Fi: mantén los chops en Mute Group M6, "
                    "aplica swing 56–62% en charles y usa la afinación recomendada o Time Stretch al BPM objetivo."
                ),
            }

    if rhythm_analysis and rhythm_analysis.get("basis") != "kit_label":
        inferred_bpm = rhythm_analysis.get("source_bpm") or inferred_bpm
        acoustic_style = rhythm_analysis.get("acoustic_style_id")
        if style_basis == "undetermined" and acoustic_style in crate_digging_styles:
            style_id = acoustic_style
            style_basis = "acoustic"
            style_info = {"style": rhythm_analysis.get("acoustic_style") or
                          rhythm_analysis.get("groove_pattern") or fallback_style["style"]}

    if hiphop_adaptation and (
        style_id in ("bolero", "oldies", "soul_vintage", "jazz_hop", "drumless", "bossa_samba", "cumbia_son", "tango_vals", "psych_library")
        or style_id in ("lofi", "boombap")
        or adapt_mode in ("lofi_chill", "boombap_classic", "dilla_jazzhop", "drumless_alchemist")
    ):
        inferred_bpm = float(hiphop_adaptation["target_bpm"])
        # Sugerir adaptación tonal/temporal en pads melódicos o loops largos del rack
        rep_st = int(hiphop_adaptation.get("repitch_semitones", 0))
        rep_ct = int(hiphop_adaptation.get("repitch_fine_tune_cents", 0))
        if abs(rep_st) <= 5 and (rep_st != 0 or abs(rep_ct) >= 8):
            for pr in pad_reports:
                if pr["sound_type"] in ("MELODIC_LOOP", "KEYS_SYNTH") and pr.get("duration_sec", 0.0) >= 0.85:
                    pr["recommended_tune"] = rep_st
                    pr["recommended_fine_tune"] = rep_ct

    harmonic_clashes: list[dict] = []
    if anchor_pc is not None and kit_mod and hasattr(kit_mod, "compute_pitch_shift_to_compatible_key"):
        for pr in pad_reports:
            eff_pc = pr.get("f0_pitch_class") if (pr.get("f0_hz", 0.0) > 0.0 and pr.get("f0_pitch_class") is not None) else pr.get("pitch_class")
            if eff_pc is None:
                continue
            is_bass_pad = pr["sound_type"] == "BASS_808" or pr["acoustic_role"] == "BASS_808"
            is_second_mel = (
                pr["sound_type"] in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL")
                and pr.get("detected_note")
                and str(pr["sample_name"]) != ""
            )
            if not (is_bass_pad or is_second_mel):
                continue
            sem_fix, target_role_lbl = kit_mod.compute_pitch_shift_to_compatible_key(int(eff_pc), int(anchor_pc))
            if is_bass_pad:
                diff = (anchor_pc - int(eff_pc)) % 12
                if diff > 6:
                    diff -= 12
                pr["recommended_tune"] = int(diff)
            if sem_fix != 0 and (is_bass_pad or pr.get("sound_type") == "KEYS_SYNTH"):
                harmonic_clashes.append({
                    "pad": pr["pad"],
                    "sample_name": pr["sample_name"],
                    "detected_note": pr.get("detected_note") or "",
                    "semitone_fix": int(sem_fix),
                    "reason": f"Choque armónico frente a tónica {anchor_note_label or ''}: ajusta {sem_fix:+d} st a {target_role_lbl}",
                })

    tuning_adjustments = []
    clipping_pads = []
    dc_offset_pads = []
    low_crest_pads = []
    measured_peaks: list[float] = []
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
        pk_val = float(pr.get("peak_dbfs", -120.0))
        if pr.get("rel_path") and pk_val > -100.0:
            measured_peaks.append(pk_val)
            if pk_val >= -0.75:
                clipping_pads.append({"pad": pr["pad"], "sample_name": pr["sample_name"], "peak_dbfs": round(pk_val, 2)})
        if pr.get("dc_offset_warning"):
            dc_offset_pads.append({"pad": pr["pad"], "sample_name": pr["sample_name"], "dc_offset": pr.get("dc_offset", 0.0)})
        if 0.0 < float(pr.get("crest_db", 0.0)) < 7.0:
            low_crest_pads.append({"pad": pr["pad"], "sample_name": pr["sample_name"], "crest_db": pr.get("crest_db", 0.0)})

        if pr.get("detected_note") and (pr["sound_type"] == "BASS_808" or pr["acoustic_role"] == "BASS_808"):
            tuning_adjustments.append({
                "pad": pr["pad"],
                "detected_note": pr["detected_note"],
                "f0_hz": pr["f0_hz"],
                "recommended_tune": pr["recommended_tune"],
                "recommended_fine_tune": pr.get("recommended_fine_tune", 0),
                "recommended_root_note": pr.get("recommended_root_note", 0),
            })

    max_peak_dbfs = round(max(measured_peaks), 2) if measured_peaks else -120.0
    if clipping_pads or dc_offset_pads:
        headroom_status = "warning"
        headroom_summary = (
            f"⚠️ {len(clipping_pads)} pad(s) sobre techo -0.80 dBFS (pico máx {max_peak_dbfs:+.2f} dBFS"
            + (f" · {len(dc_offset_pads)} con DC offset" if dc_offset_pads else "")
            + "): aplica Calibrar Headroom PCM (-0.80 dBFS)."
        )
    else:
        headroom_status = "safe"
        headroom_summary = (
            f"Headroom seguro (pico máx {max_peak_dbfs:.2f} dBFS ≤ -0.80 dBFS · sin DC)"
            if measured_peaks
            else "Headroom seguro (-0.80 dBFS objetivo)"
        )
    headroom_audit = {
        "status": headroom_status,
        "target_ceiling_dbfs": -0.80,
        "max_peak_dbfs": max_peak_dbfs,
        "clipping_pads": clipping_pads,
        "dc_offset_pads": dc_offset_pads,
        "low_crest_pads": low_crest_pads,
        "summary": headroom_summary,
    }

    mix_advice: list[str] = []
    if rhythm_analysis and isinstance(rhythm_analysis.get("mix_eq_advice"), list):
        mix_advice.extend(str(x) for x in rhythm_analysis["mix_eq_advice"] if x)
    if clipping_pads:
        mix_advice.append(headroom_summary)
    if sub_heavy_count >= 2:
        mix_advice.append("Múltiples pads con subgrave: activa Cut Self / Group M1 en Kick + Bajo.")
    if harmonic_clashes:
        mix_advice.append(harmonic_clashes[0]["reason"])

    notes_parts = [
        f"Pads sub-graves: {sub_heavy_count}",
        f"Pareja Hi-Hat (Open+Closed): {'Sí' if (open_hat_count >= 1 and closed_hat_count >= 1) else 'No'}",
    ]
    if rhythm_analysis and hiphop_adaptation:
        notes_parts.append(
            f"Compás {rhythm_analysis['time_signature']} ({rhythm_analysis['source_bpm']} → {hiphop_adaptation['target_bpm']} BPM Hip-Hop/Lo-Fi)"
        )
    if anchor_note_label:
        notes_parts.append(f"Tono ancla: {anchor_note_label}")
    if phase_warnings:
        notes_parts.append(f"⚠️ {len(phase_warnings)} aviso(s) de fase")

    anchor_key_info = kit_mod.parse_musical_key_info(anchor_note_label) if (kit_mod and hasattr(kit_mod, "parse_musical_key_info")) else None
    anchor_camelot = (anchor_key_info or {}).get("camelot") or ""

    sampqol_active = (Path(root_dir) / "mpcqol.conf").is_file() or (Path(root_dir) / "autorun" / "mpcqol.so").is_file()
    swing_val = float((rhythm_analysis or {}).get("swing_pct") or 50.0)
    if kit_mod and hasattr(kit_mod, "analyze_multibank_coherence"):
        try:
            mb_result = kit_mod.analyze_multibank_coherence(
                pad_reports,
                mix_mode=mix_mode,
                style_id=style_id,
                bpm=inferred_bpm,
                sampqol_active=sampqol_active,
                root_dir=root_dir,
            )
        except Exception:
            mb_result = _fallback_multibank_coherence(
                pad_reports, mix_mode=mix_mode, style_id=style_id, bpm=inferred_bpm, swing_pct=swing_val
            )
    else:
        mb_result = _fallback_multibank_coherence(
            pad_reports, mix_mode=mix_mode, style_id=style_id, bpm=inferred_bpm, swing_pct=swing_val
        )

    ducking_recipe = mb_result.get("ducking_recipe")
    if not isinstance(ducking_recipe, dict):
        if kit_mod and hasattr(kit_mod, "build_mpc_ducking_recipe"):
            try:
                has_kick = any(pr.get("sound_type") == "KICK" for pr in pad_reports)
                has_bass = any(pr.get("sound_type") == "BASS_808" or pr.get("acoustic_role") == "BASS_808" for pr in pad_reports)
                has_mel = any(pr.get("sound_type") in ("MELODIC_LOOP", "KEYS_SYNTH", "VOCAL") for pr in pad_reports)
                ducking_recipe = kit_mod.build_mpc_ducking_recipe(
                    style_id=style_id,
                    bpm=inferred_bpm,
                    mix_mode=mix_mode,
                    has_kick=has_kick,
                    has_bass=has_bass,
                    has_melodic=has_mel,
                    swing_pct=swing_val,
                    sampqol_active=sampqol_active,
                )
            except Exception:
                ducking_recipe = _fallback_ducking_recipe(style_id, inferred_bpm, mix_mode, swing_pct=swing_val)
        else:
            ducking_recipe = _fallback_ducking_recipe(style_id, inferred_bpm, mix_mode, swing_pct=swing_val)

    telemetry_out = {
        "success": True,
        "cerebro_os": detect_cerebro_os(root_dir, port=port),
        "scope": scope,
        "target_bank": target_bank,
        "target_pad": target_pad,
        "mix_mode": mix_mode,
        "detected_style": style_info.get("style", "Hip-Hop / Electrónica"),
        "style_id": style_id,
        "recommended_bpm": inferred_bpm,
        "bpm_source": bpm_source,
        "rack_bpm": current_tempo,
        "style_reference": reference_sample,
        "drum_style_hints": sorted(rhythm_hints.values(), key=lambda hint: -len(hint["pads"])),
        "recommended_mute_profile": recommended_profile,
        "anchor_key": anchor_note_label,
        "anchor_camelot": anchor_camelot,
        "key_source": key_source,
        "confirmed_by_drums": confirmed_by_drums,
        "sub_heavy_pads": sub_heavy_count,
        "hihat_pair_detected": bool(open_hat_count >= 1 and closed_hat_count >= 1),
        "phase_warnings": phase_warnings,
        "harmonic_clashes": harmonic_clashes,
        "headroom_audit": headroom_audit,
        "mix_advice": mix_advice,
        "tuning_adjustments": tuning_adjustments,
        "rhythm_analysis": rhythm_analysis,
        "hiphop_adaptation": hiphop_adaptation,
        "banks_summary": mb_result.get("banks_summary") or [],
        "pad_outliers": mb_result.get("pad_outliers") or [],
        "global_coherence": mb_result.get("global_coherence") or {},
        "master_bus_plan": mb_result.get("master_bus_plan") or {},
        "ducking_recipe": ducking_recipe,
        "style": {
            "id": style_id,
            "label": style_info.get("style", "Hip-Hop / Electrónica"),
            "bpm": inferred_bpm,
            "mute_profile": recommended_profile,
            "anchor_key": anchor_note_label,
            "camelot": anchor_camelot,
            "basis": style_basis,
            "secondary_styles": secondary_styles,
            "evidence": style_evidence,
            "notes": " · ".join(notes_parts),
        },
        "secondary_styles": secondary_styles,
        "style_evidence": style_evidence,
        "pad_count": len(pad_reports),
        "pads": pad_reports,
    }
    allow_llm = payload.get("use_llm", True) is not False
    if _is_temp_test_root(str(root_dir)) and "use_llm" not in payload and os.environ.get("BEATOS_MLX_FORCE_TEMP_LLM") != "1":
        telemetry_out["_temp_test_root"] = True
    rag_bundle = _retrieve_cerebro_audio_knowledge(
        "", telemetry=telemetry_out, limit=3, use_semantic_rrf=False
    )
    telemetry_out["audio_knowledge_hits"] = rag_bundle.get("rag_hits", [])
    telemetry_out["mlx_copilot"] = query_cerebro_mlx_advisor(
        telemetry_out, allow_llm=allow_llm, rag_bundle=rag_bundle
    )
    telemetry_out.pop("_temp_test_root", None)
    return telemetry_out


def build_cerebro_smart_kit(root_dir: str, payload: dict) -> dict:
    """
    Construye un Kit inteligente de 16 pads a partir de una descripción en lenguaje natural / género
    (Bolero, Soul, Jazz → Hip-Hop/Lo-Fi, Baile Funk, Drill, Grime, UK Garage, 2-Step, Dubstep, Boom Bap, etc.),
    emparejando BPM, perfil de Choke y tonalidad desde la base SQLite activa.
    """
    import math
    import random

    kit_mod = get_hardware_kit_builder(root_dir)
    prompt = str(payload.get("prompt") or payload.get("style") or "Hip-Hop").strip()
    style_info = (
        kit_mod.detect_musical_style(prompt)
        if kit_mod and hasattr(kit_mod, "detect_musical_style")
        else {"id": "standard", "style": "Hip-Hop / Electrónica", "bpm": 120.0, "mute_profile": "punch_clean"}
    )
    style_id = style_info.get("id", "standard")
    adapt_mode = str(payload.get("adapt_mode") or "auto").strip().lower()
    mode_bpm_map = {"lofi_chill": 82.0, "boombap_classic": 90.0, "dilla_jazzhop": 86.0, "drumless_alchemist": 78.0}
    explicit_prompt_bpm = None
    m_prompt = re.search(r"\b(6\d|[7-9]\d|1[0-8]\d)(?:\s*bpm)?\b", prompt, re.I)
    if m_prompt:
        val_bpm = float(m_prompt.group(1))
        if val_bpm not in (808, 909, 303):
            explicit_prompt_bpm = val_bpm

    target_bpm = float(
        payload.get("bpm")
        or explicit_prompt_bpm
        or mode_bpm_map.get(adapt_mode)
        or (kit_mod.infer_kit_bpm(prompt, fallback=style_info["bpm"]) if kit_mod else style_info["bpm"])
    )
    mute_profile = str(payload.get("mute_profile") or style_info.get("mute_profile") or "punch_clean")

    db_file = database_path(root_dir)
    if not os.path.isfile(db_file):
        raise ValueError("La base de datos SQLite no existe todavía. Ejecuta una reindexación primero.")

    # Extraer tokens de búsqueda del prompt que no sean palabras vacías
    stop_words = {"kit", "de", "con", "para", "en", "el", "la", "los", "las", "un", "una", "y", "a", "bpm", "style", "estilo", "pads", "pad"}
    raw_words = [w.lower() for w in re.findall(r"[a-zA-Z0-9#]+", prompt) if len(w) >= 3 and w.lower() not in stop_words and not w.isdigit()]

    is_organic_sampling = style_id in (
        "bolero", "oldies", "soul_vintage", "jazz_hop", "lofi", "boombap",
        "drumless", "bossa_samba", "cumbia_son", "tango_vals", "psych_library",
    ) or adapt_mode in ("lofi_chill", "boombap_classic", "dilla_jazzhop", "drumless_alchemist")
    if is_organic_sampling:
        slot_plan = [
            (1, "KICK", ["boom bap", "lofi", "dusty", "vinyl", "warm", "kick", "bombo"]),
            (2, "KICK", ["dusty", "lofi", "acoustic", "kick", "sub"]),
            (3, "SNARE", ["boom bap", "lofi", "vinyl", "snare", "caja"]),
            (4, "SNARE", ["rim", "brush", "snare", "sidestick", "snap"]),
            (5, "CLAP", ["clap", "dusty", "snap", "lofi"]),
            (6, "HIHAT", ["closed", "brush", "ch", "hat", "vinyl"]),
            (7, "HIHAT", ["closed", "shaker", "hat", "lofi"]),
            (8, "HIHAT", ["open", "oh", "ride", "cymbal"]),
            (9, "PERCUSSION", ["bongo", "conga", "maraca", "clave", "shaker", "perc", "guiro"]),
            (10, "PERCUSSION", ["tamb", "wood", "perc", "bong", "shaker"]),
            (11, "BASS_808", ["upright", "contrabajo", "bass", "acoustic", "warm", "sub"]),
            (12, "BASS_808", ["bass", "warm", "808", "sub"]),
            (13, "KEYS_SYNTH", ["guitar", "requinto", "rhodes", "piano", "chord", "keys"]),
            (14, "KEYS_SYNTH", ["wurlitzer", "organ", "rhodes", "jazz", "soul", "chord"]),
            (15, "MELODIC_LOOP", ["bolero", "soul", "jazz", "bossa", "guitar", "sax", "strings", "loop"]),
            (16, "MELODIC_LOOP", ["vocal", "horn", "flute", "loop", "sample", "chop"]),
        ]
    else:
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

    style_kw_map = {
        "bolero": ["bolero", "guitar", "requinto", "nylon", "acoustic", "bongo", "conga", "maraca", "latin", "ballad", "lofi", "dusty", "vinyl", "boom bap"],
        "oldies": ["oldies", "doo-wop", "lowrider", "sweet soul", "motown", "50s", "60s", "vinyl", "warm", "rhodes", "vocal", "strings", "boom bap", "lofi"],
        "soul_vintage": ["soul", "motown", "rhodes", "wurlitzer", "organ", "gospel", "brass", "horn", "warm", "vintage", "boom bap", "lofi", "dusty"],
        "jazz_hop": ["jazz", "bossa", "upright", "ride", "brush", "piano", "rhodes", "sax", "horn", "lofi", "chillhop", "boom bap", "vinyl"],
        "lofi": ["lofi", "lo-fi", "chillhop", "dusty", "vinyl", "tape", "rhodes", "warm"],
        "boombap": ["boom bap", "boombap", "marco polo", "cookin soul", "bodega", "deli", "east coast", "dusty", "vinyl"],
        "drumless": ["drumless", "soul", "strings", "piano", "choir", "brass", "vinyl", "dusty", "chord", "vocal", "loop", "rhodes"],
        "bossa_samba": ["bossa", "samba", "nylon", "guitar", "shaker", "pandeiro", "cuica", "rhodes", "flute", "jazz", "vinyl", "lofi"],
        "cumbia_son": ["cumbia", "son", "guajira", "conga", "bongo", "timbales", "guiro", "cowbell", "maraca", "bass", "horn", "guitar", "boom bap"],
        "tango_vals": ["tango", "vals", "waltz", "bandoneon", "violin", "strings", "piano", "contrabajo", "upright", "guitar", "vinyl", "dusty"],
        "psych_library": ["psych", "library", "ost", "soundtrack", "mellotron", "harpsichord", "organ", "fuzz", "flute", "sitar", "breaks", "vinyl"],
    }
    extra_style_kws = style_kw_map.get(style_id, [])

    used_paths: set[str] = set()
    pads_out: list[dict] = []
    anchor_key = ""
    anchor_camelot = ""
    anchor_pc: Optional[int] = None

    # Ordenar selección: loops/melódicos primero para fijar tonalidad ancla Camelot y luego alinear 808/bajos
    harmonic_first_order = sorted(
        slot_plan,
        key=lambda item: (0 if item[1] in ("MELODIC_LOOP", "KEYS_SYNTH") else (1 if item[1] == "BASS_808" else 2), item[0]),
    )
    selected_by_pad: dict[int, dict] = {}

    with contextlib.closing(sqlite3.connect(Path(db_file).as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for pad_num, stype, hints in harmonic_first_order:
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
                sc = random.random() * 0.30
                for w in raw_words:
                    if w in fn_low:
                        sc += 4.0
                for ek in extra_style_kws:
                    if ek in fn_low:
                        sc += 1.6
                for h_idx, h in enumerate(hints):
                    if h in fn_low:
                        sc += 2.5 - (h_idx * 0.3)
                # Para charles cerrados vs abiertos
                sz = float(r.get("size_mb") or 0.0)
                is_closed_slot = pad_num in ((6, 7) if is_organic_sampling else (7, 8))
                is_open_slot = (pad_num == 8) if is_organic_sampling else (pad_num in (9, 10))
                if is_closed_slot:
                    if "open" in fn_low or "oh" in fn_low:
                        sc -= 3.0
                    if 0.002 < sz <= 0.06:
                        sc += 1.5
                elif is_open_slot:
                    if "open" in fn_low or "oh" in fn_low or "ride" in fn_low:
                        sc += 3.5
                    if sz >= 0.05:
                        sc += 1.5
                # Cercanía de BPM (incluyendo relación half-time / double-time)
                r_bpm = float(r.get("bpm") or 0.0)
                if r_bpm > 0:
                    best_diff = min(abs(r_bpm - target_bpm), abs(r_bpm - target_bpm * 2.0), abs(r_bpm * 2.0 - target_bpm))
                    if best_diff <= 8.0:
                        sc += 3.0
                # Coherencia armónica Camelot frente al ancla melódica
                r_key = str(r.get("musical_key") or "").strip()
                if anchor_key and stype in ("BASS_808", "KEYS_SYNTH", "MELODIC_LOOP") and r_key and kit_mod and hasattr(kit_mod, "camelot_compatibility_score"):
                    cam_sc, _ = kit_mod.camelot_compatibility_score(anchor_key, r_key)
                    if cam_sc >= 0.85:
                        sc += 4.2
                    elif cam_sc >= 0.60:
                        sc += 1.8
                    elif cam_sc <= 0.25:
                        sc -= 2.5
                return sc

            best = max(rows, key=_score_row)
            used_paths.add(best["rel_path"])

            best_key = str(best.get("musical_key") or "").strip()
            best_tune = 0
            if not anchor_key and stype in ("MELODIC_LOOP", "KEYS_SYNTH") and best_key and kit_mod and hasattr(kit_mod, "parse_musical_key_info"):
                ak_info = kit_mod.parse_musical_key_info(best_key)
                if ak_info:
                    anchor_key = ak_info["key"]
                    anchor_camelot = ak_info.get("camelot") or ""
                    anchor_pc = ak_info.get("pitch_class")
            elif anchor_pc is not None and stype == "BASS_808" and best_key and kit_mod and hasattr(kit_mod, "parse_musical_key_info"):
                bk_info = kit_mod.parse_musical_key_info(best_key)
                if bk_info and bk_info.get("pitch_class") is not None:
                    raw_diff = (anchor_pc - int(bk_info["pitch_class"])) % 12
                    if raw_diff > 6:
                        raw_diff -= 12
                    if 0 < abs(raw_diff) <= 4:
                        best_tune = int(raw_diff)

            if is_organic_sampling and stype in ("KEYS_SYNTH", "MELODIC_LOOP"):
                mg = 6  # Chops melódicos en grupo monofónico estilo MPC
            else:
                mg = (
                    kit_mod.mute_group_for_profile(stype, best["filename"], profile=mute_profile)
                    if kit_mod
                    else (1 if stype == "KICK" else (2 if stype == "HIHAT" else (3 if stype == "SNARE" else 0)))
                )
            selected_by_pad[pad_num] = {
                "pad": pad_num,
                "rel_path": best["rel_path"],
                "filename": best["filename"],
                "sound_type": stype,
                "musical_key": best_key,
                "duration_sec": 0.6,
                "mute_group": mg,
                "volume": kit_mod.default_pad_volume(stype) if kit_mod and hasattr(kit_mod, "default_pad_volume") else 0.501187,
                "pan": 0.5,
                "tune": best_tune,
            }

    for pad_num, _, _ in slot_plan:
        if pad_num in selected_by_pad:
            pads_out.append(selected_by_pad[pad_num])

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", style_info.get("style", "Smart_Kit").split("/")[0].strip()).strip("_") or "Cerebro_Kit"
    hiphop_adaptation = None
    if is_organic_sampling:
        profiles, seq_guide = (
            kit_mod._build_adaptation_profiles_and_sequencer(
                target_bpm, False, style_id, "4/4", 58.0 if style_id in ("jazz_hop", "soul_vintage") else 54.0, 0.25, adapt_mode
            )
            if kit_mod and hasattr(kit_mod, "_build_adaptation_profiles_and_sequencer")
            else ([], {})
        )
        hiphop_adaptation = {
            "target_style": "Hip-Hop / Lo-Fi" if style_id in ("bolero", "lofi", "bossa_samba", "drumless") else "Boom Bap & Lo-Fi",
            "adapt_mode": adapt_mode,
            "target_bpm": round(target_bpm, 1),
            "stretch_ratio": 1.0,
            "repitch_semitones": 0,
            "repitch_fine_tune_cents": 0,
            "adaptation_profiles": profiles,
            "sequencer_guide": seq_guide,
            "meter_bridge_note": (
                f"Batería cálida/orgánica (Pads 1–10) + Chops melódicos con corte mutuo M6 (Pads 13–16) listos a {round(target_bpm)} BPM"
                + (f" · Tonalidad {anchor_key} ({anchor_camelot})." if anchor_key else ".")
            ),
        }
    smart_telemetry = {
        "detected_style": style_info.get("style", "Hip-Hop / Electrónica"),
        "recommended_bpm": target_bpm,
        "anchor_key": anchor_key,
        "rhythm_analysis": {"time_signature": "4/4", "source_bpm": target_bpm, "swing_pct": 56.0},
        "hiphop_adaptation": hiphop_adaptation or {"target_bpm": target_bpm, "recommended_chop_mode": "phrases", "sequencer_guide": {"kick_steps": [1,3,9,11], "swing_pct": 54.0}},
        "pad_count": len(pads_out),
    }
    return {
        "success": True,
        "kit_name": f"{slug}_{int(round(target_bpm))}BPM",
        "style": style_info,
        "recommended_bpm": target_bpm,
        "recommended_mute_profile": mute_profile,
        "anchor_key": anchor_key,
        "anchor_camelot": anchor_camelot,
        "harmonic_coherent": bool(anchor_key),
        "hiphop_adaptation": hiphop_adaptation,
        "mlx_copilot": query_cerebro_mlx_advisor(smart_telemetry, allow_llm=payload.get("use_llm", True) is not False),
        "pads": pads_out,
    }


def master_produce_rack(root_dir: str, payload: dict) -> dict:
    """Analyze and calibrate the rack in place. A prompt can populate an empty rack."""
    pads = payload.get("pads", [])
    if not isinstance(pads, list) or len(pads) > 128:
        raise ValueError("Los pads deben ser una lista de hasta 128 entradas.")
    generated = not pads
    prompt = str(payload.get("prompt") or "").strip()
    if generated and not prompt:
        raise ValueError("Asigna muestras al rack o escribe un estilo.")
    builder = get_hardware_kit_builder(root_dir)
    if builder is None:
        raise ValueError("Motor hardware_kit_builder no disponible en el servidor.")
    kit = build_cerebro_smart_kit(root_dir, payload) if generated else {}
    pads = kit.get("pads", pads)
    if generated:
        existing_pads = []
        for pad in pads:
            try:
                if resolve_library_path(root_dir, pad["rel_path"]).is_file():
                    existing_pads.append(pad)
            except ValueError:
                continue
        pads = existing_pads
        if payload.get("target_device") == "ep133":
            pads = [pad for pad in pads if pad["pad"] <= 12]
    if not pads:
        raise ValueError("La biblioteca no contiene muestras disponibles para ese estilo.")
    by_pad = {}
    for pad in pads:
        if not isinstance(pad, dict):
            raise ValueError("Cada pad debe ser un objeto.")
        number = int(pad.get("pad") or 0)
        if not 1 <= number <= 128 or number in by_pad:
            raise ValueError("Número de pad no válido o duplicado.")
        path = pad.get("rel_path")
        if not isinstance(path, str) or not path or not resolve_library_path(root_dir, path).is_file():
            raise ValueError(f"Pad {number}: muestra ausente o fuera de la biblioteca")
        by_pad[number] = pad

    tempo = kit.get("recommended_bpm", float(payload.get("tempo") or 120))
    if not math.isfinite(tempo) or not 30 <= tempo <= 300:
        raise ValueError("Tempo fuera de rango (30–300 BPM)")
    name = str(payload.get("kit_name") or kit.get("kit_name") or "Rack Kit")
    analyzed_pads = [{**pad, "sample_name": pad.get("sample_name") or pad.get("filename")
                      or Path(pad["rel_path"]).name} for pad in pads]
    analysis = analyze_rack_with_cerebro(root_dir, {
        **payload, "kit_name": name, "tempo": tempo, "pads": analyzed_pads,
    })
    gain = {"smart_pcm": "recommended_volume", "hierarchical_a": "hierarchical_volume",
            "uniform_b": "uniform_volume"}.get(payload.get("gain_profile", "smart_pcm"))
    bus_counts = dict.fromkeys(("main_0", "sub1_bass", "sub2_hats", "sub3_melodic", "sub4_fx"), 0)
    calibrated = []
    for report in analysis["pads"]:
        original = by_pad[report["pad"]]
        stype = report["sound_type"]
        route = builder.mpc_routed_pads({report["pad"]: {**original, "sound_type": stype}}, "submix_split")
        submix = int(route[report["pad"]]["submix"])
        bus_name = tuple(bus_counts)[submix] if 0 <= submix <= 4 else "main_0" if submix == 9 else None
        if bus_name:
            bus_counts[bus_name] += 1
        result = {**original, "sound_type": stype, "submix": submix,
                  "volume": report[gain] if gain else original.get("volume", 0.707946),
                  "mute_group": original.get("mute_group", report["recommended_mute_group"])}
        if payload.get("auto_tune_808", True) and stype in {"BASS_808", "BASS"}:
            if report.get("detected_note"):
                result.update(tune=report["recommended_tune"], fine_tune=report["recommended_fine_tune"],
                              root_note=report["recommended_root_note"])
        result["volume"] = float(result["volume"])
        if not math.isfinite(result["volume"]) or not 0 <= result["volume"] <= 1:
            raise ValueError(f"Pad {report['pad']}: volume fuera de rango")
        calibrated.append(result)
    gains = [20.0 * math.log10(pad["volume"]) for pad in calibrated if pad["volume"] > 0]
    return {
        "success": True, "kit_name": name, "generated_from_prompt": generated, "analysis": analysis,
        "recommended_bpm": analysis["recommended_bpm"],
        "recommended_mute_profile": analysis["recommended_mute_profile"],
        "calibration": {"pads": calibrated, "avg_gain_db": round(sum(gains) / len(gains), 1) if gains else None},
        "submix_routing": {"bus_counts": bus_counts},
        "master_summary": {"style_label": analysis["detected_style"], "anchor_key": analysis["anchor_key"]},
    }


def find_cerebro_similar_samples(root_dir: str, payload: dict) -> dict:
    """
    Encuentra las muestras acústica y tímbricamente más similares en la biblioteca SQLite
    comparando firma PCM real (3 bandas, ZCR, crest factor, duración), BPM y afinidad Camelot.
    """
    kit_mod = get_hardware_kit_builder(root_dir)
    rel_path = str(payload.get("rel_path") or "").strip()
    sound_type = str(payload.get("sound_type") or "").strip().upper()
    limit = max(4, min(24, int(payload.get("limit") or 10)))

    db_file = database_path(root_dir)
    if not os.path.isfile(db_file):
        raise ValueError("La base de datos SQLite no está disponible.")

    target_sig: Optional[dict] = None
    if rel_path:
        try:
            tgt_wav = resolve_library_path(root_dir, rel_path)
            if tgt_wav.is_file():
                target_sig = _extract_pad_acoustic_signature(tgt_wav, kit_mod=kit_mod)
        except Exception:
            target_sig = None

    with contextlib.closing(sqlite3.connect(Path(db_file).as_uri() + "?mode=ro", uri=True)) as conn:
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
        target_key = str((target_row or {}).get("musical_key") or "").strip()

        cur.execute(
            "SELECT filename, rel_path, sound_type, sample_format, sub_pack, bpm, musical_key, energy_level, size_mb "
            "FROM samples WHERE sound_type = ? AND rel_path != ? LIMIT 1500",
            (sound_type, rel_path),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    # Fase 1: Pre-filtro rápido por metadatos SQLite
    pre_scored: list[tuple[float, dict, list[str]]] = []
    for c in candidates:
        c_sz = float(c.get("size_mb") or 0.08)
        c_energy = str(c.get("energy_level") or "GROOVE")
        c_bpm = float(c.get("bpm") or 0.0)
        c_key = str(c.get("musical_key") or "").strip()
        dist = abs(c_sz - target_sz) * 3.0
        reasons: list[str] = []
        if c_energy == target_energy:
            reasons.append(f"Energía {c_energy}")
        else:
            dist += 0.35
        if c.get("sample_format") != target_fmt:
            dist += 1.5
        if target_bpm > 0 and c_bpm > 0:
            bpm_diff = min(
                abs(c_bpm - target_bpm),
                abs(c_bpm - target_bpm * 2.0),
                abs(c_bpm * 2.0 - target_bpm),
            )
            dist += bpm_diff * 0.04
            if bpm_diff <= 4.0:
                reasons.append(f"BPM cercano ({int(round(c_bpm))})")
        if target_key and c_key and kit_mod and hasattr(kit_mod, "camelot_compatibility_score"):
            cam_sc, cam_lbl = kit_mod.camelot_compatibility_score(target_key, c_key)
            if cam_sc >= 0.85:
                dist = max(0.0, dist - 0.25)
                reasons.append(cam_lbl)
            elif cam_sc <= 0.25:
                dist += 0.45
        pre_scored.append((dist, c, reasons))

    pre_scored.sort(key=lambda t: t[0])

    # Fase 2: Medición acústica PCM real sobre top-28 candidatos locales cuando la muestra origen tiene firma WAV
    final_scored: list[tuple[float, dict]] = []
    inspect_cap = 28 if target_sig else 0
    for idx_c, (base_dist, c, reasons) in enumerate(pre_scored[: max(limit * 3, 40)]):
        dist = base_dist
        cand_reasons = list(reasons)
        c_sz = float(c.get("size_mb") or 0.08)
        c_bpm = float(c.get("bpm") or 0.0)
        if target_sig and idx_c < inspect_cap:
            try:
                c_wav = resolve_library_path(root_dir, c["rel_path"])
                c_sig = _extract_pad_acoustic_signature(c_wav, kit_mod=kit_mod) if c_wav.is_file() else None
            except Exception:
                c_sig = None
            if c_sig:
                spec_d = (
                    abs(c_sig["sub_ratio"] - target_sig["sub_ratio"]) * 2.4
                    + abs(c_sig["mid_ratio"] - target_sig["mid_ratio"]) * 1.8
                    + abs(c_sig["high_ratio"] - target_sig["high_ratio"]) * 2.4
                )
                zcr_rel = abs(c_sig["zcr_hz"] - target_sig["zcr_hz"]) / max(250.0, target_sig["zcr_hz"], c_sig["zcr_hz"])
                crest_d = abs(c_sig["crest_db"] - target_sig["crest_db"]) / 18.0
                dur_d = min(1.5, abs(c_sig["duration_sec"] - target_sig["duration_sec"]) / max(0.25, target_sig["duration_sec"]))
                acoustic_dist = spec_d + 0.55 * zcr_rel + 0.35 * crest_d + 0.40 * dur_d
                dist = 0.25 * base_dist + acoustic_dist
                if spec_d <= 0.22:
                    cand_reasons.insert(0, "Espectro PCM afín")
                if crest_d <= 0.18:
                    cand_reasons.append(f"Punch {c_sig['crest_db']}dB")

        similarity = round(max(0.10, min(0.99, 1.0 / (1.0 + dist))), 2)
        final_scored.append((
            similarity,
            {
                "filename": c["filename"],
                "rel_path": c["rel_path"],
                "sound_type": c["sound_type"],
                "sub_pack": c.get("sub_pack") or "",
                "size_mb": round(c_sz, 3),
                "bpm": c_bpm,
                "musical_key": c.get("musical_key") or "",
                "match_reasons": cand_reasons[:3],
                "similarity": similarity,
            },
        ))

    final_scored.sort(key=lambda t: t[0], reverse=True)
    return {
        "success": True,
        "acoustic_fingerprinting": bool(target_sig),
        "target_rel_path": rel_path,
        "sound_type": sound_type,
        "results": [item for _, item in final_scored[:limit]],
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
            with contextlib.closing(sqlite3.connect(db_p.as_uri() + "?mode=ro", uri=True, timeout=1.0)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(f"PRAGMA table_info({t_name})")
                cols = {r[1] for r in cur.fetchall()}
                name_col = "filename" if "filename" in cols else ("name" if "name" in cols else "")
                if not name_col:
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
    ext_raw = Path(ext_path_str)
    if ext_raw.is_symlink():
        raise ValueError("No se admiten enlaces simbólicos en muestras externas.")
    ext_p = ext_raw.resolve()
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
    with ext_p.open("rb") as sf:
        src_digest = hashlib.file_digest(sf, "sha256").hexdigest()
    need_copy = True
    if dest_file.exists():
        if dest_file.is_symlink():
            raise ValueError("No se admiten enlaces simbólicos en el destino.")
        with dest_file.open("rb") as ef:
            dst_digest = hashlib.file_digest(ef, "sha256").hexdigest()
        if dst_digest == src_digest:
            need_copy = False
        else:
            dest_file = dest_dir / f"{dest_file.stem}_{src_digest[:8]}{dest_file.suffix}"
            if dest_file.exists():
                need_copy = False
    if need_copy:
        tmp_path = None
        try:
            with ext_p.open("rb") as sf, tempfile.NamedTemporaryFile(
                dir=dest_dir, prefix=".import-", suffix=dest_file.suffix, delete=False
            ) as tf:
                tmp_path = Path(tf.name)
                shutil.copyfileobj(sf, tf, length=64 * 1024)
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(tmp_path, dest_file)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
    rel_dest = dest_file.relative_to(Path(root_dir).resolve()).as_posix()
    kit_mod = get_hardware_kit_builder(root_dir)
    stype = kit_mod.detect_sound_type(dest_file.name) if kit_mod else "PERCUSSION"
    return {
        "success": True,
        "filename": dest_file.name,
        "rel_path": rel_dest,
        "sound_type": stype,
    }


def get_system_status(root_dir: str, port: int = 8888):
    library_available = os.path.isdir(root_dir)
    card_mounted = library_available and os.path.ismount(root_dir)
    disk_stat = shutil.disk_usage(root_dir) if os.path.exists(root_dir) else None

    db_candidates = [database_path(root_dir)]
    sample_count = 0
    for cand in db_candidates:
        if os.path.isfile(cand):
            try:
                with contextlib.closing(sqlite3.connect(Path(cand).as_uri() + "?mode=ro", uri=True, timeout=1.0)) as conn:
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM samples")
                    row = c.fetchone()
                    sample_count = row[0] if row else 0
                if sample_count > 0:
                    break
            except Exception:
                pass

    caps_summary = None
    try:
        import beatos_runtime
        caps_summary = beatos_runtime.inspect_capabilities(
            os.path.dirname(os.path.abspath(__file__)), probe_codecs=False
        )["summary"]
    except Exception:
        caps_summary = None

    return {
        "status": "online" if library_available else "library_unavailable",
        "library_available": library_available,
        "card_mounted": card_mounted,
        "root_dir": root_dir,
        "port": port,
        "sample_count": sample_count,
        "disk_free_gb": round(disk_stat.free / (1024**3), 2) if disk_stat else 0,
        "disk_total_gb": round(disk_stat.total / (1024**3), 2) if disk_stat else 0,
        "task_state": _snapshot_task_state(),
        "cerebro_os": detect_cerebro_os(root_dir),
        "capabilities_summary": caps_summary,
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


def library_names_file(root) -> Path:
    return config_dir(root) / "library_names.json"


def read_library_names(root, *, strict=False) -> dict[str, str]:
    try:
        names = json.loads(library_names_file(root).read_text(encoding="utf-8"))
        if not isinstance(names, dict) or not all(isinstance(value, str) for value in names.values()):
            raise ValueError("El archivo de nombres de la biblioteca no es válido.")
        return names
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if strict:
            raise
        return {}


def catalog_display_name(names: dict, root: str, path: str, native_name: str) -> str:
    item = Path(path)
    try:
        relative = item.relative_to(Path(root).resolve()).as_posix() if item.is_absolute() else item.as_posix()
    except ValueError:
        return native_name
    return names.get(relative, native_name)


def save_library_name(root: str, payload: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str) or not payload["path"].strip():
        raise ValueError("Se requiere una ruta de biblioteca.")
    if not isinstance(payload.get("name"), str):
        raise ValueError("Se requiere un nombre válido.")
    name = unicodedata.normalize("NFC", payload["name"]).strip()
    if len(name) > 120 or any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in name):
        raise ValueError("Usa un nombre de hasta 120 caracteres sin saltos de línea.")
    path = resolve_library_path(root, payload["path"])
    if not ((path.is_file() and path.suffix.lower() in {".xpj", ".xpm"})
            or (path.is_dir() and (path / "Expansion.xml").is_file())):
        raise ValueError("Selecciona un proyecto, programa o expansión existente.")
    relative = path.relative_to(Path(root).resolve()).as_posix()
    with LIBRARY_NAMES_LOCK:
        names = read_library_names(root, strict=True)
        if name:
            names[relative] = name
        else:
            names.pop(relative, None)
        write_state_json(library_names_file(root), names)
    return {"success": True, "path": relative, "name": name or None}


class HTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # The local listener uses a numeric address. Avoid a reverse DNS lookup
        # during startup, which can delay the loopback server on macOS.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class MPCAudioRequestHandler(BaseHTTPRequestHandler):
    server_version = "MPCAudioStreamer/3.9.1"

    def send_error(self, code, message=None, explain=None):
        # The request line may be rejected before BaseHTTPRequestHandler has headers.
        language = get_request_language(getattr(self, "headers", {}))
        super().send_error(code, translate_text(message, language), explain)

    def _api_json_dumps(self, payload, **kwargs):
        """Localize user-facing API messages by this request's ES/EN preference."""
        localized = localize_api_payload(payload, get_request_language(self.headers))
        return json.dumps(localized, **kwargs)

    def _serve_card_config_get(self, fn_name, missing_msg):
        """Serve GET JSON for SD-card OS managers (SampQOL / Melodee)."""
        kit_mod = get_hardware_kit_builder(self.server.root_dir)
        reader = getattr(kit_mod, fn_name, None) if kit_mod else None
        if callable(reader):
            try:
                resp, code = reader(self.server.root_dir), 200
            except Exception as e:
                resp, code = {"success": False, "error": str(e)}, 500
        else:
            resp, code = {"success": False, "error": missing_msg}, 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))

    def _serve_card_config_post(self, length, fn_name, missing_msg):
        """Serve POST JSON updates/presets for SD-card OS managers (SampQOL / Melodee)."""
        try:
            raw_bytes = self.rfile.read(length) if length > 0 else b"{}"
            if length > 0 and len(raw_bytes) != length:
                raise ValueError("Transferencia incompleta")
            body = raw_bytes.decode("utf-8")
            payload = json.loads(body) if body.strip() else {}
            if not isinstance(payload, dict):
                raise ValueError("Se esperaba un objeto JSON")
            raw_updates = payload.get("settings")
            if raw_updates is not None and not isinstance(raw_updates, dict):
                raise ValueError("El parámetro 'settings' debe ser un objeto JSON")
            preset = payload.get("preset")
            if preset is not None and not isinstance(preset, str):
                raise ValueError("El parámetro 'preset' debe ser texto")
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            updater = getattr(kit_mod, fn_name, None) if kit_mod else None
            if not callable(updater):
                raise RuntimeError(missing_msg)
            extra_kwargs: Dict[str, Any] = {}
            if fn_name == "update_melodee_settings":
                if "start_project" in payload:
                    if payload["start_project"] is not None and not isinstance(payload["start_project"], str):
                        raise ValueError("El parámetro 'start_project' debe ser texto")
                    extra_kwargs["start_project"] = payload["start_project"]
                if "action" in payload:
                    if payload["action"] is not None and not isinstance(payload["action"], str):
                        raise ValueError("El parámetro 'action' debe ser texto")
                    extra_kwargs["action"] = payload["action"]
            result = updater(
                self.server.root_dir,
                updates=raw_updates if raw_updates is not None else {},
                preset=preset,
                **extra_kwargs,
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
                    self.send_header('Access-Control-Allow-Private-Network', 'true')
            except ValueError:
                pass
        self.send_header('Vary', 'Origin, Accept-Encoding')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
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

    def run_maintenance(self, operation):
        with TASK_LOCK:
            if TASK_STATE["running"]:
                return {"success": False, "error": "Ya hay una tarea de mantenimiento en curso.", "busy": True}
            TASK_STATE["running"] = True
        try:
            return operation()
        except (OSError, subprocess.SubprocessError) as exc:
            return {"success": False, "error": str(exc)}
        finally:
            with TASK_LOCK:
                TASK_STATE["running"] = False

    def _accepts_gzip(self) -> bool:
        ae = str(self.headers.get("Accept-Encoding") or "").lower()
        return "gzip" in ae

    def send_api_json(self, data, status=200):
        raw = self._api_json_dumps(data, ensure_ascii=False).encode("utf-8")
        use_gz = len(raw) >= 4096 and self._accepts_gzip()
        body = gzip.compress(raw, compresslevel=5) if use_gz else raw
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

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
            payload_js = (
                f'window.__BEATOS_LOCAL_SERVER_ONLINE = "http://127.0.0.1:{port}";\n'
                f'window.beatosProbeKey = "{library_identity(self.server.root_dir)}";\n'
            ).encode("utf-8")
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
            data = get_system_status(self.server.root_dir, self.server.server_port)
            self.wfile.write(self._api_json_dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/library_names":
            root = self.server.root_dir
            self.send_api_json({"success": True, "root_dir": root, "names": read_library_names(root)})
            return

        elif clean_path == "/api/ecosystem":
            self.send_api_json({"success": True, "inventory": dashboard_inventory(self.server.root_dir, refresh=True)})
            return

        elif clean_path == "/api/search":
            qs = urllib.parse.parse_qs(parsed.query or "")
            q_raw = str((qs.get("q") or qs.get("query") or [""])[0]).strip()
            mode = str((qs.get("mode") or ["fts"])[0]).strip().lower()
            try:
                limit = max(1, min(200, int((qs.get("limit") or ["40"])[0])))
            except ValueError:
                limit = 40
            t0 = time.time()
            db_file = database_path(self.server.root_dir)
            db_mtime_ns = 0
            try:
                if db_file.is_file():
                    db_mtime_ns = db_file.stat().st_mtime_ns
            except OSError:
                db_mtime_ns = 0
            cache_key = (str(db_file), db_mtime_ns, q_raw, mode, limit)
            if q_raw:
                with _SEARCH_CACHE_LOCK:
                    cached_payload = _SEARCH_CACHE.get(cache_key)
                    if cached_payload is not None:
                        _SEARCH_CACHE.move_to_end(cache_key)
                        hit = dict(cached_payload)
                        hit["cache_hit"] = True
                        hit["latency_ms"] = round((time.time() - t0) * 1000, 2)
                        self.send_api_json(hit, 200)
                        return

            results = []
            engine_used = "sqlite_fts5"
            faiss_warning = ""
            if db_file.is_file() and q_raw:
                tokens = [t for t in re.split(r"[\s_\-/]+", q_raw) if len(t) >= 2][:10]
                try:
                    con = open_sqlite_readonly(db_file)
                    cur = con.cursor()
                    has_fts = bool(cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='samples_fts'").fetchone())
                    rows = []
                    if has_fts and tokens:
                        fts_q = " AND ".join(f'"{t.replace(chr(34), "")}"*' for t in tokens)
                        try:
                            rows = cur.execute("""
                                SELECT s.id, s.filename, s.sound_type, s.sample_format, s.macro_category, s.sub_pack,
                                       s.bpm, s.musical_key, s.camelot, s.energy_level, s.size_mb, s.rel_path
                                FROM samples_fts f JOIN samples s ON s.id = f.rowid
                                WHERE samples_fts MATCH ?
                                ORDER BY bm25(samples_fts)
                                LIMIT ?
                            """, (fts_q, limit)).fetchall()
                        except sqlite3.OperationalError:
                            rows = []
                    if not rows:
                        engine_used = "sqlite_like"
                        conds, params = [], []
                        for tok in (tokens or [q_raw]):
                            conds.append("(filename LIKE ? OR sound_type LIKE ? OR sub_pack LIKE ? OR rel_path LIKE ?)")
                            p = f"%{tok}%"
                            params.extend([p, p, p, p])
                        rows = cur.execute(
                            f"SELECT id, filename, sound_type, sample_format, macro_category, sub_pack, bpm, musical_key, camelot, energy_level, size_mb, rel_path FROM samples WHERE {' AND '.join(conds)} LIMIT ?",
                            params + [limit],
                        ).fetchall()
                    for r in rows:
                        results.append({
                            "id": r[0], "filename": r[1], "sound_type": r[2], "sample_format": r[3],
                            "macro_category": r[4], "sub_pack": r[5], "bpm": r[6], "musical_key": r[7],
                            "camelot": r[8], "energy_level": r[9], "size_mb": r[10], "rel_path": r[11],
                        })
                except sqlite3.Error as e:
                    self.send_api_json({"success": False, "error": str(e), "results": []}, 500)
                    return
            should_use_faiss = bool(
                q_raw
                and mode != "exact"
                and (mode == "hybrid" or (len(results) == 0 and len(q_raw.split()) >= 2))
            )
            if should_use_faiss and len(results) < limit:
                try:
                    scripts_dir = str(Path(__file__).resolve().parent / "scripts")
                    if scripts_dir not in sys.path:
                        sys.path.insert(0, scripts_dir)
                    import cerebro_faiss_engine as _cfe
                    vec_res = _cfe.search_faiss_vector(q_raw, top_k=min(20, limit))
                    seen_rel = {r.get("rel_path") for r in results}
                    for vr in vec_res.get("results", []):
                        rp = vr.get("rel_path") or vr.get("full_path") or ""
                        if rp and rp not in seen_rel:
                            seen_rel.add(rp)
                            results.append({
                                "filename": vr.get("filename"), "sound_type": vr.get("genre"),
                                "sub_pack": vr.get("sub_genre"), "bpm": vr.get("bpm"),
                                "musical_key": vr.get("musical_key"), "rel_path": rp,
                                "similarity_score": vr.get("similarity_score"), "disk": vr.get("disk"),
                            })
                    engine_used = f"{engine_used}+faiss"
                except Exception as exc:
                    faiss_warning = f"FAISS fallback omitido: {exc}"
            payload_out: dict[str, Any] = {
                "success": True,
                "query": q_raw,
                "engine": engine_used,
                "count": len(results[:limit]),
                "cache_hit": False,
                "latency_ms": round((time.time() - t0) * 1000, 2),
                "results": results[:limit],
            }
            if faiss_warning:
                payload_out["faiss_warning"] = faiss_warning
            if q_raw:
                with _SEARCH_CACHE_LOCK:
                    _SEARCH_CACHE[cache_key] = dict(payload_out)
                    _SEARCH_CACHE.move_to_end(cache_key)
                    while len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX_ITEMS:
                        _SEARCH_CACHE.popitem(last=False)
            self.send_api_json(payload_out, 200)
            return

        elif clean_path == "/api/health_audit":
            root_p = Path(self.server.root_dir)
            db_file = database_path(self.server.root_dir)
            audit: dict[str, Any] = {
                "success": True,
                "root_dir": str(root_p),
                "mounted": root_p.is_dir(),
                "gzip_enabled": True,
                "security_headers": True,
                "autorun_active": (
                    "SampQOL-OS" if (root_p / "autorun" / "mpcqol.so").is_file()
                    else ("Melodee" if (root_p / "autorun" / "melodee").is_file() else "Stock")
                ),
                "sqlite": {"present": db_file.is_file()},
            }
            try:
                usage = shutil.disk_usage(str(root_p))
                audit["disk"] = {
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "used_pct": round((usage.used / max(1, usage.total)) * 100.0, 1),
                }
            except OSError:
                pass
            if db_file.is_file():
                try:
                    con = sqlite3.connect(str(db_file))
                    cur = con.cursor()
                    audit["sqlite"]["integrity"] = cur.execute("PRAGMA quick_check;").fetchone()[0]
                    audit["sqlite"]["samples"] = cur.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
                    audit["sqlite"]["projects"] = cur.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
                    audit["sqlite"]["expansions"] = cur.execute("SELECT COUNT(*) FROM expansions").fetchone()[0]
                    audit["sqlite"]["packs"] = cur.execute("SELECT COUNT(*) FROM packs").fetchone()[0]
                    audit["sqlite"]["fts5_ready"] = bool(cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='samples_fts'").fetchone())
                    cols = {r[1] for r in cur.execute("PRAGMA table_info(samples)").fetchall()}
                    if "wav_health" in cols:
                        audit["sqlite"]["wav_health"] = dict(cur.execute("SELECT wav_health, COUNT(*) FROM samples GROUP BY wav_health").fetchall())
                    con.close()
                except sqlite3.Error as e:
                    audit["sqlite"]["error"] = str(e)
            self.send_api_json(audit, 200)
            return

        elif clean_path == "/api/cerebro_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            data = {"success": True, "cerebro_os": detect_cerebro_os(self.server.root_dir, self.server.server_port)}
            self.wfile.write(self._api_json_dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/cerebro_audio_knowledge":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query or "")
            q_txt = str((qs.get("q") or qs.get("query") or [""])[0])
            topic_txt = str((qs.get("topic") or [""])[0])
            sem_flag = str((qs.get("semantic") or ["0"])[0]).lower() in ("1", "true", "yes")
            res = _retrieve_cerebro_audio_knowledge(
                q_txt,
                topic=topic_txt,
                limit=4,
                use_semantic_rrf=sem_flag,
            )
            self.send_api_json(res, 200)
            return

        elif clean_path == "/api/rack_mix_profiles":
            try:
                qs = urllib.parse.parse_qs(parsed.query or "")
                set_id = str((qs.get("set_id") or [""])[0]).strip()
                res = get_rack_mix_profile(self.server.root_dir, set_id=set_id)
                self.send_api_json(res, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            return

        elif clean_path == "/api/task_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(_snapshot_task_state(), ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/system/capabilities":
            try:
                import beatos_runtime
                force_refresh = "refresh=1" in (parsed.query or "")
                if force_refresh:
                    beatos_runtime.clear_runtime_cache()
                caps = beatos_runtime.inspect_capabilities(os.path.dirname(os.path.abspath(__file__)), probe_codecs=True)
                self.send_api_json({"success": True, "capabilities": caps}, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 500)
            return

        elif clean_path == "/api/system/bootstrap_script":
            try:
                import beatos_runtime
                qs = urllib.parse.parse_qs(parsed.query or "")
                tgt = qs.get("target", [None])[0]
                prof = qs.get("profile", ["full"])[0]
                filename, content = beatos_runtime.generate_bootstrap_script(tgt, prof)
                raw = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(raw)
            except ValueError as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 500)
            return

        elif clean_path == "/api/theme":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            current_theme = read_ecosystem_theme(self.server.root_dir)
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
                        backups = kit_mod.scan_po33_backups(
                            kit_mod.po33_backup_dirs(self.server.root_dir),
                            cache=PO_BACKUP_CACHE,
                            root=self.server.root_dir,
                        )
                        lib_cfg = (
                            kit_mod.get_po_backup_library_status(self.server.root_dir)
                            if hasattr(kit_mod, "get_po_backup_library_status")
                            else None
                        )
                    self.wfile.write(self._api_json_dumps({"success": True, "backups": backups, "config": lib_cfg}, ensure_ascii=False).encode("utf-8"))
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

        elif clean_path == "/api/po_backup_config":
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            if kit_mod and hasattr(kit_mod, "get_po_backup_library_status"):
                try:
                    cfg = kit_mod.get_po_backup_library_status(self.server.root_dir)
                    resp, code = {"success": True, "config": cfg}, 200
                except Exception as e:
                    resp, code = {"success": False, "error": str(e)}, 500
            else:
                resp, code = {"success": False, "error": "Módulo hardware_kit_builder no disponible."}, 500
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(resp, ensure_ascii=False).encode("utf-8"))
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
            self._serve_card_config_get("read_mpcqol_conf", "Módulo hardware_kit_builder no disponible.")
            return

        elif clean_path == "/api/melodee_config":
            self._serve_card_config_get("read_melodee_settings", "Gestor Melodee/settings no disponible.")
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
        limit = (
            128 * 1024 * 1024
            if clean_api == '/api/po33_backups'
            else (32 * 1024 * 1024 if clean_api in ('/api/create_expansion', '/api/update_expansion') else 1024 * 1024)
        )
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
                storage = params.get('storage', [None])[0]
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                with PO_BACKUP_LOCK:
                    result = kit_mod.import_po33_backup(self.server.root_dir, filename, data, model=model, project=project, storage=storage)
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

        elif clean_api == '/api/po_backup_config':
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON request')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete request')
                payload = json.loads(data) if data else {}
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                with PO_BACKUP_LOCK:
                    cfg = kit_mod.save_po_backup_config(self.server.root_dir, payload)
                    PO_BACKUP_CACHE.clear()
                response, code = {'success': True, 'config': cfg}, 200
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

        elif clean_api == '/api/po_backup_config/pick_folder':
            try:
                if sys.platform != 'darwin':
                    raise ValueError('Selector nativo disponible en macOS; escribe la ruta absoluta manualmente.')
                script = 'POSIX path of (choose folder with prompt "Selecciona la carpeta externa para tus backups de Pocket Operator")'
                proc = subprocess.run(['osascript', '-e', script], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, check=False)
                if proc.returncode != 0:
                    stderr_low = (proc.stderr or '').lower()
                    if '-128' in stderr_low or 'cancel' in stderr_low:
                        response, code = {'success': True, 'cancelled': True, 'path': ''}, 200
                    else:
                        raise RuntimeError((proc.stderr or 'No se pudo abrir el selector de carpetas').strip()[:300])
                else:
                    chosen = proc.stdout.strip().rstrip('/') or '/'
                    response, code = {'success': True, 'cancelled': False, 'path': chosen}, 200
            except subprocess.TimeoutExpired:
                response, code = {'success': False, 'error': 'Tiempo de espera agotado en el selector de carpetas'}, 400
            except ValueError as error:
                response, code = {'success': False, 'error': str(error)}, 400
            except Exception as error:
                response, code = {'success': False, 'error': str(error)}, 500
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(response, ensure_ascii=False).encode('utf-8'))
            return

        elif clean_api == '/api/po_backup_update':
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON request')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete request')
                payload = json.loads(data)
                if not isinstance(payload, dict):
                    raise ValueError('Invalid format')
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                with PO_BACKUP_LOCK:
                    updated = kit_mod.update_po_backup_metadata(
                        self.server.root_dir,
                        payload.get('file', ''),
                        project=payload.get('project'),
                        notes=payload.get('notes'),
                    )
                response, code = {'success': True, 'backup': updated}, 200
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

        elif clean_api == '/api/po_backup_copy':
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON request')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete request')
                payload = json.loads(data)
                if not isinstance(payload, dict):
                    raise ValueError('Invalid format')
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                with PO_BACKUP_LOCK:
                    copied = kit_mod.copy_po_backup_to_target(
                        self.server.root_dir,
                        payload.get('file', ''),
                        str(payload.get('destination') or ''),
                    )
                    PO_BACKUP_CACHE.clear()
                response, code = {'success': True, 'backup': copied}, 200
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

        elif clean_api == '/api/po_backup_delete':
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON request')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete request')
                payload = json.loads(data)
                if not isinstance(payload, dict):
                    raise ValueError('Invalid format')
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                with PO_BACKUP_LOCK:
                    deleted = kit_mod.delete_po_backup(self.server.root_dir, payload.get('file', ''))
                    PO_BACKUP_CACHE.clear()
                response, code = {'success': True, **deleted}, 200
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

        elif clean_api == '/api/po_backup_reveal':
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON request')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete request')
                payload = json.loads(data)
                req_path = str(payload.get('path') or '').strip() if isinstance(payload, dict) else ''
                if not req_path:
                    raise ValueError("Falta parámetro 'path'")
                p_in = Path(req_path)
                if p_in.is_symlink():
                    raise ValueError('Symlinked backups are not supported')
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                roots = [r.resolve() for r in kit_mod.po33_backup_dirs(self.server.root_dir)]
                default_dir = kit_mod.default_po_backup_dir(self.server.root_dir)
                if default_dir.exists() and default_dir.resolve() not in roots:
                    roots.append(default_dir.resolve())
                candidate = p_in.resolve()
                if not candidate.exists() or candidate.is_symlink():
                    raise ValueError('Ruta de backup no encontrada')
                if not any(candidate == r or candidate.is_relative_to(r) for r in roots):
                    raise ValueError('Backup outside the library')
                if sys.platform == 'darwin':
                    subprocess.run(['open', str(candidate)] if candidate.is_dir() else ['open', '-R', str(candidate)], timeout=15, check=True)
                elif sys.platform == 'win32':
                    os.startfile(str(candidate if candidate.is_dir() else candidate.parent))
                else:
                    subprocess.run(['xdg-open', str(candidate if candidate.is_dir() else candidate.parent)], timeout=15, check=True)
                response, code = {'success': True, 'message': f'Abierto en el explorador: {candidate}'}, 200
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

        elif clean_api == "/api/cerebro_analyze":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                result = analyze_rack_with_cerebro(
                    self.server.root_dir,
                    payload,
                    port=getattr(self.server, "server_port", None),
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

        elif clean_api == "/api/rack_mix_profiles/save":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")
                res = save_rack_mix_profile(self.server.root_dir, payload)
                self.send_api_json(res, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            return

        elif clean_api == "/api/rack_mix_profiles/switch":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")
                res = switch_rack_mix_profile(self.server.root_dir, payload)
                self.send_api_json(res, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            return

        elif clean_api == "/api/rack_mix_profiles/reset":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")
                res = reset_rack_mix_profile(self.server.root_dir, payload)
                self.send_api_json(res, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            return

        elif clean_api == "/api/audio_measure_bounce":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")
                raw_path = str(payload.get("path") or payload.get("rel_path") or "").strip()
                if not raw_path:
                    raise ValueError("Indica la ruta del archivo WAV de bounce dentro de la biblioteca.")
                wav_path = resolve_library_path(self.server.root_dir, raw_path)
                if not wav_path.is_file():
                    raise FileNotFoundError(f"Archivo no encontrado: {raw_path}")
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if kit_mod and hasattr(kit_mod, "measure_wav_loudness_report"):
                    report = kit_mod.measure_wav_loudness_report(wav_path)
                elif kit_mod and hasattr(kit_mod, "analyze_sample_acoustics"):
                    ac = kit_mod.analyze_sample_acoustics(wav_path)
                    tp = float(ac.get("true_peak_dbtp") if ac.get("true_peak_dbtp") is not None else ac.get("peak_dbfs", -120.0))
                    lufs_i = float(ac.get("lufs_active_est") if ac.get("lufs_active_est") is not None else ac.get("rms_active_dbfs", -120.0))
                    report = {
                        "lufs_integrated": round(lufs_i, 2),
                        "true_peak_dbtp": round(tp, 2),
                        "lra_lu": 0.0,
                        "peak_dbfs": float(ac.get("peak_dbfs", -120.0)),
                        "crest_db": float(ac.get("crest_factor_db", 0.0)),
                        "subsonic_ratio_35hz": float(ac.get("subsonic_ratio_35hz", 0.0)),
                        "low_stereo_corr_120hz": float(ac.get("low_stereo_corr_120hz", ac.get("stereo_correlation", 1.0))),
                        "studio_ready": bool(-18.0 <= lufs_i <= -13.0 and tp <= -1.0),
                        "live_pa_ready": bool(-11.5 <= lufs_i <= -7.5 and tp <= -0.8),
                        "warnings": [] if tp <= -0.8 else [f"True Peak {tp:+.2f} dBTP excede techo seguro AK4558 (-0.8 dBTP)."],
                    }
                else:
                    raise RuntimeError("Motor de medición acústica no disponible.")
                self.send_api_json({"success": True, "path": raw_path, "report": report}, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            return

        elif clean_api == "/api/cerebro_audio_knowledge":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")
                res = _retrieve_cerebro_audio_knowledge(
                    str(payload.get("query") or ""),
                    topic=str(payload.get("topic") or ""),
                    telemetry=payload.get("context") if isinstance(payload.get("context"), dict) else None,
                    limit=max(1, min(6, int(payload.get("limit") or 4))),
                    use_semantic_rrf=bool(payload.get("semantic", True)),
                )
                self.send_api_json(res, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            return

        elif clean_api == "/api/cerebro_pattern_generate":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "generate_euclidean_mpc_pattern"):
                    raise RuntimeError("Motor hardware_kit_builder no disponible en el servidor.")
                res = kit_mod.generate_euclidean_mpc_pattern(
                    style=str(payload.get("style") or "boombap"),
                    bpm=float(payload["bpm"]) if payload.get("bpm") is not None else None,
                    bars=int(payload.get("bars") or 2),
                    swing=float(payload["swing"]) if payload.get("swing") is not None else None,
                    swing_unit=int(payload["swing_unit"]) if payload.get("swing_unit") is not None else None,
                    humanize_ms=float(payload["humanize_ms"]) if payload.get("humanize_ms") is not None else None,
                    limb_spread=float(payload.get("limb_spread") if payload.get("limb_spread") is not None else 0.25),
                    conformity=float(payload.get("conformity") if payload.get("conformity") is not None else 0.80),
                    seed=int(payload.get("seed") if payload.get("seed") is not None else 1337),
                )
                self.send_api_json(res, 200)
            except Exception as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            return

        elif clean_api == "/api/cerebro_master_produce":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se requiere un objeto JSON.")
                pads_in = payload.get("pads") or []
                prompt_in = str(payload.get("prompt") or payload.get("style") or "").strip()
                if not pads_in and not prompt_in:
                    raise ValueError("Carga muestras en el rack o indica un estilo para que Cerebro OS orqueste la sesión.")
                result = master_produce_rack(self.server.root_dir, payload)
                result["master_orchestrated"] = True
                result.setdefault("pads", result["calibration"]["pads"])
                self.send_api_json(result, 200)
            except (ValueError, TypeError) as e:
                self.send_api_json({"success": False, "error": str(e)}, 400)
            except (OSError, sqlite3.Error) as e:
                self.send_api_json({"success": False, "error": str(e)}, 500)
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
                chop_mode_in = str(payload.get("chop_mode") or "auto")
                default_slices = 48 if chop_mode_in.strip().lower() == "mmr_3bank_48" else 16
                result = kit_mod.autochop_sample_to_16_pads(
                    src_wav,
                    self.server.root_dir,
                    max_slices=int(payload.get("max_slices") or default_slices),
                    kit_name=payload.get("kit_name"),
                    style_hint=str(payload.get("style_hint") or ""),
                    target_bpm=payload.get("target_bpm"),
                    chop_mode=chop_mode_in,
                    adapt_mode=str(payload.get("adapt_mode") or "auto"),
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
                if hasattr(kit_mod, "clear_expansion_kits_cache"):
                    kit_mod.clear_expansion_kits_cache()
                try:
                    from index_mpc_library import sync_expansion_into_catalog
                    sync_info = sync_expansion_into_catalog(
                        self.server.root_dir,
                        Path(self.server.root_dir) / result.get("expansion_path", ""),
                        Path(__file__).resolve().parent / "templates" / "catalogo.html",
                    )
                    if isinstance(sync_info, dict):
                        result["card_html"] = sync_info.get("card_html", "")
                        result["expansion"] = sync_info.get("expansion", {})
                except Exception as sync_err:
                    sys.stderr.write(f"  [WARN sync_expansion_into_catalog] {sync_err}\n")
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

        elif clean_api == "/api/update_expansion":
            try:
                import base64
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if not kit_mod or not hasattr(kit_mod, "update_expansion_metadata"):
                    raise RuntimeError("Editor de expansiones no disponible en el servidor.")

                cover_b64 = payload.get("cover_base64") or payload.get("cover_data_url") or ""
                cover_bytes = None
                if isinstance(cover_b64, str) and cover_b64.strip():
                    raw_b64 = cover_b64.split(",", 1)[-1] if "," in cover_b64 else cover_b64
                    cover_bytes = base64.b64decode(raw_b64)

                result = kit_mod.update_expansion_metadata(
                    expansion_path=payload.get("expansion_path") or payload.get("path") or "",
                    title=payload.get("title"),
                    manufacturer=payload.get("manufacturer"),
                    description=payload.get("description"),
                    cover_bytes=cover_bytes,
                    cover_filename=str(payload.get("cover_filename") or "Artwork.png"),
                    regenerate_cover=bool(payload.get("regenerate_cover")),
                    rename_folder=bool(payload.get("rename_folder")),
                    source_root=self.server.root_dir,
                )
                try:
                    from index_mpc_library import sync_expansion_into_catalog
                    old_exp_arg = Path(self.server.root_dir) / result["old_path"] if result.get("renamed_folder") else None
                    sync_info = sync_expansion_into_catalog(
                        self.server.root_dir,
                        Path(self.server.root_dir) / result.get("expansion_path", ""),
                        Path(__file__).resolve().parent / "templates" / "catalogo.html",
                        old_exp_path=old_exp_arg,
                    )
                    if isinstance(sync_info, dict):
                        result["card_html"] = sync_info.get("card_html", "")
                        result["expansion"] = sync_info.get("expansion", {})
                except Exception as sync_err:
                    sys.stderr.write(f"  [WARN sync_expansion_into_catalog update] {sync_err}\n")

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
            self._serve_card_config_post(length, "update_mpcqol_conf", "Gestor mpcqol.conf no disponible.")
            return

        elif clean_api == "/api/melodee_config":
            self._serve_card_config_post(length, "update_melodee_settings", "Gestor Melodee/settings no disponible.")
            return

        elif clean_api == "/api/reveal_in_finder":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body)
                target_path = payload.get("path", "").strip()
                if not target_path:
                    raise ValueError("Falta parámetro 'path'")

                p = resolve_library_path(self.server.root_dir, target_path)
                if not p.exists():
                    raise FileNotFoundError(f"Ruta no encontrada: {target_path}")

                if sys.platform == 'darwin':
                    subprocess.run(['open', str(p)] if p.is_dir() else ['open', '-R', str(p)], timeout=15, check=True)
                elif sys.platform == 'win32':
                    os.startfile(str(p if p.is_dir() else p.parent))
                else:
                    subprocess.run(['xdg-open', str(p if p.is_dir() else p.parent)], timeout=15, check=True)
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
                    subprocess.run(['open', '-a', browser, url], timeout=15, check=True)
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
            already_running = False
            with TASK_LOCK:
                if TASK_STATE["running"]:
                    already_running = True
                    state_snap = {**TASK_STATE, "logs": list(TASK_STATE["logs"])}
                else:
                    TASK_STATE["running"] = True
                    state_snap = {**TASK_STATE, "logs": list(TASK_STATE["logs"])}
            if already_running:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(
                    self._api_json_dumps(
                        {
                            "success": False,
                            "message": "Ya hay una reindexación en ejecución en segundo plano.",
                            "task_state": state_snap,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

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
                        "task_state": state_snap,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return

        elif clean_api == "/api/action/install_capabilities":
            try:
                import beatos_runtime
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Invalid format")
                profile = beatos_runtime.validate_profile(payload.get("profile") or "full")
                inc_sys = payload.get("include_system_ffmpeg", True) is not False
            except (ValueError, TypeError, json.JSONDecodeError) as err:
                self.send_api_json({"success": False, "error": str(err)}, 400)
                return

            already_running = False
            with TASK_LOCK:
                if TASK_STATE["running"]:
                    already_running = True
                    state_snap = {**TASK_STATE, "logs": list(TASK_STATE["logs"])}
                else:
                    TASK_STATE["running"] = True
                    state_snap = {**TASK_STATE, "logs": list(TASK_STATE["logs"])}
            if already_running:
                self.send_api_json(
                    {"success": False, "message": "Ya hay una tarea en ejecución en segundo plano.", "task_state": state_snap},
                    409,
                )
                return
            t = threading.Thread(
                target=run_install_capabilities_thread,
                args=(self.server.root_dir, profile, inc_sys),
                daemon=True,
            )
            t.start()
            self.send_api_json(
                {"success": True, "message": f"🛠️ Instalación de soporte ({profile}) iniciada en segundo plano.", "task_state": state_snap},
                200,
            )
            return

        elif clean_api == "/api/system/export_bootstrap_pack":
            try:
                import beatos_runtime
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(body) if body.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Invalid format")
                profile = beatos_runtime.validate_profile(payload.get("profile") or "full")
                root_res = Path(self.server.root_dir).resolve()
                dest_dir = root_res / "BeatOS" / "instaladores"
                if dest_dir.exists() and dest_dir.is_symlink():
                    raise ValueError("La carpeta de instaladores no puede ser un enlace simbólico")
                dest_dir.mkdir(parents=True, exist_ok=True)
                if not dest_dir.resolve().is_relative_to(root_res):
                    raise ValueError("Ruta fuera de la biblioteca")
                pack = beatos_runtime.export_bootstrap_pack(dest_dir, profile=profile)
                self.send_api_json(pack, 200)
            except (ValueError, TypeError, json.JSONDecodeError) as err:
                self.send_api_json({"success": False, "error": str(err)}, 400)
            except Exception as err:
                self.send_api_json({"success": False, "error": str(err)}, 500)
            return

        elif clean_api == "/api/clean_metadata":
            res = self.run_maintenance(lambda: run_clean_metadata(self.server.root_dir))
            self.send_api_json(res, 200 if res["success"] else 409 if res.get("busy") else 500)
            return

        elif clean_api == "/api/sync_dashboard":
            res = self.run_maintenance(lambda: run_sync_dashboard(self.server.root_dir, self.server.server_port))
            self.send_api_json(res, 200 if res["success"] else 409 if res.get("busy") else 500)
            return

        elif clean_api == "/api/library_names":
            try:
                if length > 16384:
                    raise ValueError("Tamaño de petición no permitido")
                result = save_library_name(self.server.root_dir, json.loads(self.rfile.read(length)))
            except ValueError as error:
                self.send_api_json({"success": False, "error": str(error)}, 400)
            except OSError as error:
                self.send_api_json({"success": False, "error": str(error)}, 500)
            else:
                self.send_api_json(result)
            return

        elif clean_api == "/api/load_project":
            try:
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
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
                    names = read_library_names(self.server.root_dir)
                    proj_info["project_name"] = catalog_display_name(
                        names, self.server.root_dir, src_path, proj_info["project_name"]
                    )
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
                    names = read_library_names(self.server.root_dir)
                    kits = [{**kit, "original_name": kit["name"],
                             "name": catalog_display_name(names, self.server.root_dir, kit["rel_path"], kit["name"])}
                            for kit in kits]
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
                    names = read_library_names(self.server.root_dir)
                    prog_info["program_name"] = catalog_display_name(
                        names, self.server.root_dir, src_path, prog_info["program_name"]
                    )
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
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 4096:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                theme_name = payload.get("theme") if isinstance(payload, dict) else None
                if not isinstance(theme_name, str) or theme_name not in ECOSYSTEM_THEMES:
                    raise ValueError
            except ValueError:
                status = 400
                response = {"success": False, "error": "Tema del ecosistema no válido."}
            else:
                theme_data = {
                    "theme": theme_name,
                    "updated_at": datetime.datetime.now().isoformat(),
                    "source": "mpc_sample_database",
                }
                try:
                    write_state_json(ecosystem_theme_path(), theme_data)
                except OSError:
                    try:
                        write_state_json(config_dir(self.server.root_dir) / "theme_config.json", theme_data)
                    except OSError:
                        status = 500
                        response = {"success": False, "error": "No se pudo guardar el tema del ecosistema."}
                    else:
                        status = 200
                        response = {"success": True, "theme": theme_name}
                else:
                    try:
                        write_state_json(config_dir(self.server.root_dir) / "theme_config.json", theme_data)
                    except OSError:
                        pass
                    status = 200
                    response = {"success": True, "theme": theme_name}
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(self._api_json_dumps(response).encode("utf-8"))
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
        elif clean_path == "ecosystem" or (
            clean_path == MASTER_DASHBOARD_REL and not (Path(self.server.root_dir) / MASTER_DASHBOARD_REL).is_file()
        ):
            file_root = os.path.join(os.path.dirname(__file__), "docs")
            clean_path = "MASTER_ECOSISTEMA_DISCOS.html"
        elif clean_path == "assets/beatos-maintenance.js":
            file_root = os.path.join(os.path.dirname(__file__), "docs", "assets")
            clean_path = "beatos-maintenance.js"
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
            for prefix in ('BeatOS/data/BeatOS/docs/assets/', 'BeatOS/docs/assets/', 'docs/assets/'):
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
                msg = f"404 No encontrado: {clean_path}\n"
                self.wfile.write(msg.encode("utf-8"))
            return

        try:
            target_path = str(resolve_library_path(file_root, target_path))
        except ValueError:
            self.send_error(403, 'Ruta fuera de la biblioteca')
            return

        wav_bytes = get_browser_playable_wav_bytes(target_path)
        file_size = len(wav_bytes) if wav_bytes is not None else os.path.getsize(target_path)
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
                if start < 0:
                    start = 0
                if end >= file_size:
                    end = file_size - 1
                if start > end and file_size > 0:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.send_cors_headers()
                    self.end_headers()
                    return
                length = max(0, end - start + 1)

                self.send_response(206)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_cors_headers()
                self.end_headers()

                if send_body:
                    try:
                        stream_ctx = (
                            contextlib.nullcontext(io.BytesIO(wav_bytes))
                            if wav_bytes is not None
                            else open(target_path, "rb")
                        )
                        with stream_ctx as f:
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

        # Respuesta 200 completa (con compresión gzip automática para HTML/JSON/JS/CSS >= 4KB)
        compressible = (
            wav_bytes is None
            and file_size >= 4096
            and self._accepts_gzip()
            and mime_type in ("text/html", "application/json", "application/javascript", "text/javascript", "text/css", "image/svg+xml")
        )
        if compressible:
            with open(target_path, "rb") as f:
                gz_body = gzip.compress(f.read(), compresslevel=5)
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(gz_body)))
            if mime_type == "text/html":
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_cors_headers()
            self.end_headers()
            if send_body:
                try:
                    self.wfile.write(gz_body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            return

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
                stream_ctx = (
                    contextlib.nullcontext(io.BytesIO(wav_bytes))
                    if wav_bytes is not None
                    else open(target_path, "rb")
                )
                with stream_ctx as f:
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
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=0.5) as response:
            state = json.loads(response.read(65536))
        if isinstance(state, dict) and state.get("status") == "online" and isinstance(state.get("root_dir"), str):
            return Path(state["root_dir"]).resolve()
        return None
    except (OSError, ValueError, KeyError):
        return None

def write_connection_hint(root: str, port: int) -> None:
    """The file view uses this per-library port only as a navigation hint."""
    path = Path(root) / "BeatOS/data/beatos-connection.js"
    if not path.parent.is_dir():
        return
    try:
        # A token derived from the root lets a stale hint reject a different library on the same port.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".beatos-connection.", delete=False) as stream:
            pending = Path(stream.name)
            try:
                data = {"port": port, "key": library_identity(root)}
                stream.write(f"window.beatosConnection = {json.dumps(data)};\n")
                stream.close()
                pending.replace(path)
            finally:
                pending.unlink(missing_ok=True)
    except OSError:
        pass


def library_identity(root: str) -> str:
    return hashlib.sha256(os.fsencode(os.path.normcase(str(Path(root).resolve())))).hexdigest()


def run_server(custom_path: str | None = None, port: int | None = None, auto_open: bool = True, dashboard: bool = False):
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

    if dashboard:
        catalog_rel = "ecosystem"

    existing_port = next((candidate for candidate in range(desired_port, port)
                          if existing_library_root(candidate) == Path(target_root)), None)
    if existing_port is not None:
        existing_url = f"http://127.0.0.1:{existing_port}/" + (catalog_rel or "")
        write_connection_hint(target_root, existing_port)
        if auto_open:
            emit(f"✔ El servidor BeatOS ya está activo en segundo plano en {existing_url} — abriendo navegador...")
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", existing_url], timeout=15, check=False)
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
    write_connection_hint(target_root, port)
    try:
        sync_beatos_bridge(target_root, port, force=True)
    except Exception:
        pass

    if auto_open:
        def open_browser():
            time.sleep(1.2)
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", url], timeout=15, check=False)
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
    parser.add_argument("--dashboard", action="store_true", help="Open the ecosystem dashboard")
    args = parser.parse_args()
    try:
        run_server(args.path, port=args.port, auto_open=not args.no_browser, dashboard=args.dashboard)
    except (OSError, ValueError, sqlite3.Error) as error:
        language = "es" if os.environ.get("BEATOS_LANG") == "es" else "en"
        parser.exit(1, cli_failure("No se pudo iniciar el servidor.", error, language) + "\n")
