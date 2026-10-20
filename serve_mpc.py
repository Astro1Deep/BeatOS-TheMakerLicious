#!/usr/bin/env python3
"""
Akai MPC Sample Finder & Hardware Multi-Sampler Audio Streamer (v3.5)
Ubicación: serve_mpc.py
Repositorio: Astro1Deep/mpc-sample-database

Servidor HTTP de alto rendimiento con:
1. RFC 7233 Range Requests (HTTP 206 Partial Content) para streaming fluido en Safari, Chrome, Firefox y WebKit.
2. Soporte completo de CORS para Web Audio API y controladores hardware.
3. API REST para el Ecosistema Multi-Sampler:
   - GET  /api/status: Estado del sistema, memoria, espacio y tarjeta montada.
   - GET  /api/task_status: Estado de tareas de reindexación en segundo plano.
   - GET  /api/po33_backups: Escaneo y verificación de señales módem FSK de Pocket Operator.
   - GET  /api/po33_backup_audio: Streaming de audio de respaldo de PO-33 para carga directa en pads.
   - POST /api/create_kit: Síntesis y exportación universal de kits para Akai MPC (.xpm/.xpj), NI Maschine (.mxgrp), Roland SP-404MK2 y PO-33 Drum Reel.
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
import tempfile
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

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
    candidates = [
        os.path.join(root_dir, "hardware_kit_builder.py"),
        os.path.join(root_dir, "_INDEX_MPC_SAMPLE", "hardware_kit_builder.py"),
        os.path.expanduser("~/Documents/mpc-sample-database/hardware_kit_builder.py"),
        "/Volumes/MPCSMPL/_INDEX_MPC_SAMPLE/hardware_kit_builder.py",
        "/Volumes/MPCSMPL/hardware_kit_builder.py",
    ]
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

    candidates = [
        os.path.join(root_dir, "index_mpc_library.py"),
        os.path.join(root_dir, "_INDEX_MPC_SAMPLE", "reindex_mpc_sample.py"),
        "/Volumes/MPCSMPL/_INDEX_MPC_SAMPLE/reindex_mpc_sample.py",
        os.path.expanduser("~/Documents/mpc-sample-database/index_mpc_library.py"),
    ]
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
            [sys.executable, script_path],
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

        dashboard_script = os.path.expanduser("~/.gemini/antigravity/scratch/sync_master_dashboard.py")
        if proc.returncode == 0 and os.path.isfile(dashboard_script):
            TASK_STATE["logs"].append("📊 Sincronizando Master Dashboard...")
            subprocess.run([sys.executable, dashboard_script], stderr=subprocess.DEVNULL, check=False)

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

    db_candidates = [
        os.path.join(root_dir, "SQLITE_DATABASE", "mpc_sample.db"),
        os.path.join(root_dir, "_INDEX_MPC_SAMPLE", "mpc_sample.db"),
        "/Volumes/MPCSMPL/SQLITE_DATABASE/mpc_sample.db",
        "/Volumes/MPCSMPL/_INDEX_MPC_SAMPLE/mpc_sample.db",
        os.path.expanduser("~/Documents/mpc-sample-database/SQLITE_DATABASE/mpc_sample.db"),
    ]
    sample_count = 0
    for cand in db_candidates:
        if os.path.isfile(cand):
            try:
                conn = sqlite3.connect(cand)
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
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port

class MPCAudioRequestHandler(BaseHTTPRequestHandler):
    server_version = "MPCAudioStreamer/3.5"

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Range, Content-Type, Accept, Origin, Authorization, X-Requested-With, Cache-Control",
        )
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        clean_path = parsed.path.rstrip("/")

        # Endpoints API
        if clean_path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            data = get_system_status(self.server.root_dir)
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/task_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(TASK_STATE, ensure_ascii=False).encode("utf-8"))
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
            self.wfile.write(json.dumps({"success": True, "theme": current_theme}, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_path == "/api/po33_backups":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            kit_mod = get_hardware_kit_builder(self.server.root_dir)
            if kit_mod and hasattr(kit_mod, "scan_po33_backups"):
                try:
                    backups = kit_mod.scan_po33_backups()
                    self.wfile.write(json.dumps({"success": True, "backups": backups}, ensure_ascii=False).encode("utf-8"))
                except Exception as e:
                    self.wfile.write(json.dumps({"success": False, "error": str(e), "backups": []}).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"success": False, "error": "Módulo hardware_kit_builder no disponible.", "backups": []}).encode("utf-8"))
            return

        elif clean_path == "/api/po33_backup_audio":
            query = urllib.parse.parse_qs(parsed.query)
            file_name = query.get("file", [""])[0] or query.get("path", [""])[0]
            target_path = None
            if file_name:
                p_cand = Path(file_name)
                if p_cand.is_absolute() and p_cand.is_file():
                    target_path = p_cand
                else:
                    cand2 = Path("/Users/ivan/Documents/PO- POCKET OPERATORS") / Path(file_name).name
                    if cand2.is_file():
                        target_path = cand2
            if not target_path or not target_path.is_file():
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Audio de backup no encontrado."}).encode("utf-8"))
                return
            try:
                data = target_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Disposition", f'inline; filename="{target_path.name}"')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self.send_response(500)
                self.end_headers()
            return

        self.handle_request(send_body=True)

    def do_HEAD(self):
        self.handle_request(send_body=False)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        clean_api = parsed.path.rstrip("/")

        if clean_api == "/api/create_kit":
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

                result = kit_mod.create_kit(kit_name, pads, target=target, source_root=self.server.root_dir)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                err_resp = {"success": False, "error": str(e)}
                self.wfile.write(json.dumps(err_resp).encode("utf-8"))
            return

        elif clean_api == "/api/reindex":
            if TASK_STATE["running"]:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "success": False,
                            "message": "Ya hay una reindexación en ejecución en segundo plano.",
                            "task_state": TASK_STATE,
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
                json.dumps(
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
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/sync_dashboard":
            res = run_sync_dashboard()
            self.send_response(200 if res.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/load_project":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                rel_path = payload.get("rel_path")
                if not rel_path:
                    raise ValueError("Falta parámetro 'rel_path'")

                src_path = os.path.join(self.server.root_dir, rel_path)
                if not os.path.isfile(src_path):
                    # Probar rutas alternativas
                    alt_cand = Path("/Volumes/MPCSMPL") / rel_path
                    if alt_cand.is_file():
                        src_path = str(alt_cand)
                    else:
                        raise FileNotFoundError(f"Proyecto no encontrado: {src_path}")

                kit_mod = get_hardware_kit_builder(self.server.root_dir)
                if kit_mod and hasattr(kit_mod, "parse_xpj_project"):
                    proj_info = kit_mod.parse_xpj_project(src_path, source_root=self.server.root_dir)
                    resp = {"success": True, "project": proj_info}
                else:
                    raise RuntimeError("Función parse_xpj_project no disponible.")
            except Exception as e:
                resp = {"success": False, "error": str(e)}

            self.send_response(200 if resp.get("success") else 500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
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
                    if not exp_root.is_dir():
                        exp_root = Path("/Volumes/MPCSMPL/Expansions")
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
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
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
                src_path = os.path.join(self.server.root_dir, clean_rel)
                if not os.path.isfile(src_path):
                    alt_cand = Path("/Volumes/MPCSMPL") / clean_rel
                    if alt_cand.is_file():
                        src_path = str(alt_cand)
                    else:
                        # Buscar si está en el directorio del script
                        script_cand = Path(__file__).parent / clean_rel
                        if script_cand.is_file():
                            src_path = str(script_cand)
                        else:
                            raise FileNotFoundError(f"Programa XPM no encontrado: {src_path}")

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
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        elif clean_api == "/api/download_xpa":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                rel_path = payload.get("rel_path")
                if not rel_path:
                    raise ValueError("Falta parámetro 'rel_path'")
                src_path = os.path.join(self.server.root_dir, rel_path)
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
                                zf.write(full_path, arcname)

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
                self.wfile.write(json.dumps(err_resp).encode("utf-8"))
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
                
                local_theme = os.path.join(self.server.root_dir, "theme_config.json")
                with open(local_theme, "w", encoding="utf-8") as f:
                    json.dump(theme_data, f, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "theme": theme_name}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
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
            for candidate in ("catalogo_universal.html", "catalogo_mpc_sample.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
                if os.path.isfile(os.path.join(self.server.root_dir, candidate)):
                    clean_path = candidate
                    break

        target_path = os.path.join(self.server.root_dir, clean_path)

        if not os.path.isfile(target_path):
            sub_path = os.path.join(self.server.root_dir, "SQLITE_DATABASE", clean_path)
            if os.path.isfile(sub_path):
                target_path = sub_path
            elif clean_path.startswith("SQLITE_DATABASE/"):
                root_direct = os.path.join(self.server.root_dir, clean_path.replace("SQLITE_DATABASE/", "", 1))
                if os.path.isfile(root_direct):
                    target_path = root_direct
            elif os.path.isdir("/Volumes/MPCSMPL") and not target_path.startswith("/Volumes/MPCSMPL"):
                alt_path = os.path.join("/Volumes/MPCSMPL", clean_path)
                if os.path.isfile(alt_path):
                    target_path = alt_path

        if not os.path.isfile(target_path):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            if send_body:
                msg = f"404 No encontrado: {clean_path}\nBuscado en: {target_path}\n"
                self.wfile.write(msg.encode("utf-8"))
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

def run_server(custom_path: str | None = None, port: int | None = None, auto_open: bool = True):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_root = find_card_root(custom_path if custom_path else script_dir)

    if not port:
        port = find_available_port(8888)

    catalog_rel = None
    for cand in ("catalogo_universal.html", "catalogo_mpc_sample.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
        if os.path.isfile(os.path.join(target_root, cand)):
            catalog_rel = cand
            break

    if not catalog_rel:
        if os.path.isfile(os.path.join(script_dir, "catalogo_universal.html")):
            catalog_rel = "catalogo_universal.html"
        elif os.path.isfile(os.path.join(script_dir, "catalogo_mpc_sample.html")):
            catalog_rel = "catalogo_mpc_sample.html"

    url = f"http://localhost:{port}/" + (catalog_rel if catalog_rel else "")

    print("\n" + "=" * 70)
    print("🔊 BeatOS — The MakerLicious")
    print("   The system ★ [universal beatmaker station]")
    print("   │ ref: mpc · sp-404 · po-20 · maschine // spec sheet 01 │")
    print("=" * 70)
    print(f"  📁 Raíz de Medios / Repositorio: {target_root}")
    print(f"  🌐 URL del Catálogo Web:         {url}")
    print(f"  ⚡ Streaming RFC 7233:           HTTP 206 Partial Content (Safari, Chrome, Arc)")
    print(f"  🎛️ Multi-Sampler API:            Akai MPC, Roland SP-404MK2, NI Maschine, PO-33")
    print("=" * 70)
    print("  💡 Presiona Ctrl+C en esta terminal para detener el servidor.\n")

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
        print("\n✔ Servidor web detenido correctamente.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MPC Sample & Multi-Sampler Audio Streamer")
    parser.add_argument("path", nargs="?", default=None, help="Directorio raíz de la tarjeta o base")
    parser.add_argument("--port", "-p", type=int, default=8888, help="Puerto HTTP (def: 8888)")
    parser.add_argument("--no-browser", action="store_true", help="No abrir automáticamente el navegador")
    args = parser.parse_args()
    run_server(args.path, port=args.port, auto_open=not args.no_browser)
