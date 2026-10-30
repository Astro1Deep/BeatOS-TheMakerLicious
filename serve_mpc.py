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
   - POST /api/create_kit: Síntesis y exportación universal de kits para Akai MPC (.xpm/.xpj), NI Maschine (WAV + mapa JSON), Roland SP-404MK2 y PO-33 Drum Reel.
   - POST /api/load_project: Carga de proyectos MPC (.xpj) en el Beatmaker Rack.
   - POST /api/reindex: Re-indexación autónoma en segundo plano.
   - POST /api/clean_metadata: Purga de residuos AppleDouble (._*) y .DS_Store.
   - POST /api/sync_dashboard: Sincronización con el Master Dashboard de 4 Pilares.
"""

from __future__ import annotations

import argparse
import datetime
import json
import mimetypes
import os
import shutil
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
from beatos_paths import CATALOG_REL, config_dir, database_path, default_library_root
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

def get_hardware_kit_builder(root_dir: str):
    """Carga de forma dinámica y tolerante a fallos el módulo hardware_kit_builder."""
    candidates = [os.path.join(os.path.dirname(__file__), "hardware_kit_builder.py"),
                  os.path.join(root_dir, "BeatOS", "hardware_kit_builder.py")]
    for cand in candidates:
        if os.path.isfile(cand):
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("hardware_kit_builder", cand)
                if spec and spec.loader:
                    kit_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(kit_mod)
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
        proc = subprocess.Popen(
            [sys.executable, "-B", script_path, "--path", root_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=root_dir,
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
    try:
        if sys.platform == "darwin":
            subprocess.run(["dot_clean", "-m", root_dir], stderr=subprocess.DEVNULL, check=False)
            logs.append("✔ dot_clean ejecutado en el volumen.")

        deleted_count = 0
        for dirpath, _, filenames in os.walk(root_dir):
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
    dashboard_script = os.path.expanduser("~/.gemini/antigravity/scratch/sync_master_dashboard.py")
    if os.path.isfile(dashboard_script):
        try:
            res = subprocess.run([sys.executable, dashboard_script], capture_output=True, text=True, check=True)
            return {"success": True, "output": res.stdout}
        except subprocess.CalledProcessError as e:
            return {"success": False, "error": e.stderr}
    return {"success": False, "error": "Script sync_master_dashboard.py no encontrado."}

def get_system_status(root_dir: str):
    card_mounted = os.path.isdir("/Volumes/MPCSMPL")
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
        "status": "online",
        "card_mounted": card_mounted,
        "root_dir": root_dir,
        "sample_count": sample_count,
        "disk_free_gb": round(disk_stat.free / (1024**3), 2) if disk_stat else 0,
        "disk_total_gb": round(disk_stat.total / (1024**3), 2) if disk_stat else 0,
        "task_state": TASK_STATE,
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
        if origin and urllib.parse.urlsplit(origin).netloc == self.headers.get('Host'):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Range, Content-Type, Accept, Origin, Authorization, X-Requested-With, Cache-Control",
        )
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")
        self.send_header("Access-Control-Max-Age", "86400")

    def allow_local_request(self):
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        try:
            parsed_host = urllib.parse.urlsplit('http://' + host)
            valid_host = parsed_host.hostname in {'127.0.0.1', 'localhost', '::1'}
            valid_host = valid_host and parsed_host.port == self.server.server_address[1]
            parsed_origin = urllib.parse.urlsplit(origin) if origin else None
            valid_origin = not origin or (parsed_origin.scheme == 'http' and parsed_origin.netloc == host)
        except ValueError:
            valid_host = valid_origin = False
        if not valid_host or not valid_origin or self.headers.get('Sec-Fetch-Site') == 'cross-site':
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

        # Endpoints API
        if clean_path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            data = get_system_status(self.server.root_dir)
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
                size = target_path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + urllib.parse.quote(target_path.name, safe=''))
                self.send_cors_headers()
                self.end_headers()
                with target_path.open('rb') as source:
                    shutil.copyfileobj(source, self.wfile, length=64 * 1024)
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
                if self.headers.get_content_type() != 'audio/wav':
                    raise ValueError('Envía el archivo WAV original con Content-Type audio/wav')
                filename = urllib.parse.parse_qs(parsed.query).get('name', ['PO33.wav'])[0]
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Transferencia incompleta')
                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                with PO_BACKUP_LOCK:
                    result = kit_mod.import_po33_backup(self.server.root_dir, filename, data)
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
                result = kit_mod.create_kit(kit_name, pads, target=target, source_root=self.server.root_dir, tempo=payload.get("tempo",120), po_options=payload.get("po_options"))

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
                expansion_name = payload.get("expansion_name", "").strip()
                if not expansion_name:
                    raise ValueError("Falta parámetro 'expansion_name'")

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if kit_mod and hasattr(kit_mod, "list_expansion_kits"):
                    exp_root = Path(self.server.root_dir) / "Expansions"
                    kits = kit_mod.list_expansion_kits(expansion_name, expansions_root=exp_root, source_root=self.server.root_dir)
                    resp = {"success": True, "expansion_name": expansion_name, "programs": kits, "total": len(kits)}
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
            for candidate in (CATALOG_REL, "catalogo_universal.html", "catalogo_mpc_sample.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
                if os.path.isfile(os.path.join(self.server.root_dir, candidate)):
                    clean_path = candidate
                    break

        file_root = self.server.root_dir
        if clean_path == CATALOG_REL:
            file_root = os.path.join(self.server.root_dir, 'BeatOS', 'data')
            clean_path = 'catalogo.html'
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
        print(translate_text(str(message), os.environ.get("BEATOS_LANG", "en")))

    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_root = str(Path(custom_path).expanduser().resolve()) if custom_path else find_card_root(script_dir)
    if not Path(target_root).is_dir():
        raise ValueError(translate_text(f"La biblioteca no existe: {target_root}", os.environ.get("BEATOS_LANG", "en")))

    desired_port = port or 8888
    port = find_available_port(desired_port)

    catalog_rel = None
    for cand in (CATALOG_REL, "catalogo_universal.html", "catalogo_mpc_sample.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
        if os.path.isfile(os.path.join(target_root, cand)):
            catalog_rel = cand
            break

    if not catalog_rel:
        if os.path.isfile(os.path.join(script_dir, "catalogo_universal.html")):
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
