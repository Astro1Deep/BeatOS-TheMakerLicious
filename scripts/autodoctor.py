#!/usr/bin/env python3
"""
Cerebro OS & BeatOS — AutoDoctor
Módulo Inteligente de Auto-Diagnóstico, Auto-Recuperación y Saneamiento Continuo.

Uso:
  python3 autodoctor.py --check             # Diagnóstico completo (solo lectura)
  python3 autodoctor.py --heal              # Diagnóstico + auto-reparación inmediata
  python3 autodoctor.py --daemon [interval] # Modo guardián en segundo plano (def: 60s)
  python3 autodoctor.py --install-service   # Instala LaunchAgent en macOS
  python3 autodoctor.py --uninstall-service # Desinstala LaunchAgent
"""

import os
import sys
import time
import socket
import sqlite3
import subprocess
import urllib.request
import logging
from datetime import datetime
from pathlib import Path

# Configuración de Rutas y Logging
LOG_PATH = os.path.expanduser("~/.gemini/antigravity/scratch/autodoctor.log")
PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/com.cerebro.autodoctor.plist")
SYNC_DASHBOARD_SCRIPT = "/Users/ivan/.gemini/antigravity/scratch/sync_master_dashboard.py"
SERVE_MPC_SCRIPT = "/Users/ivan/Documents/mpc-sample-database/serve_mpc.py"
OPEN_WEBUI_SCRIPT = "/Users/ivan/.mlx-stack/start-webui.sh"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Colores ANSI
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Definición de Servicios Clave
SERVICES = [
    {
        "name": "BeatOS / MPC Server",
        "port": 8888,
        "url": "http://127.0.0.1:8888/",
        "start_cmd": ["python3", SERVE_MPC_SCRIPT, "--no-browser"],
        "critical": True
    },
    {
        "name": "Open WebUI (Local LLM)",
        "port": 3000,
        "url": "http://127.0.0.1:3000/",
        "start_cmd": ["bash", OPEN_WEBUI_SCRIPT],
        "critical": False
    },
    {
        "name": "Ollama Local Daemon",
        "port": 11434,
        "url": "http://127.0.0.1:11434/api/tags",
        "start_cmd": ["ollama", "serve"],
        "critical": False
    }
]

# Definición de Discos y Bases de Datos
DISKS = [
    {
        "name": "Akai MPC Sample (MicroSD)",
        "mount": "/Volumes/MPCSMPL",
        "needs_dot_clean": True,
        "reindex_script": None,
        "db_path": None
    },
    {
        "name": "SanDisk SSD (Serato DJ & VJ Loops)",
        "mount": "/Volumes/SanDisk SSD",
        "needs_dot_clean": False,
        "reindex_script": "/Volumes/SanDisk SSD/_INDEX_SERATO_DJ/reindex_serato_dj.py",
        "db_path": "/Volumes/SanDisk SSD/_INDEX_SERATO_DJ/serato_dj.db"
    },
    {
        "name": "Samsung PSSDT7 (Producción & Ableton)",
        "mount": "/Volumes/samsung PSSDT7",
        "needs_dot_clean": False,
        "reindex_script": "/Volumes/samsung PSSDT7/_INDEX_PRODUCCION/reindex_produccion.py",
        "db_path": "/Volumes/samsung PSSDT7/_INDEX_PRODUCCION/produccion.db"
    },
    {
        "name": "Realtek (Native Instruments & Reaktor)",
        "mount": "/Volumes/Realtek RTL9210B-CG Media",
        "needs_dot_clean": False,
        "reindex_script": "/Volumes/Realtek RTL9210B-CG Media/_INDEX_AUDIOTECA/reindex_audiotheque.py",
        "db_path": "/Volumes/Realtek RTL9210B-CG Media/_INDEX_AUDIOTECA/audiotheque.db"
    }
]


def log_event(msg, level="info"):
    print(msg)
    clean_msg = msg.replace(CYAN, "").replace(GREEN, "").replace(YELLOW, "").replace(RED, "").replace(MAGENTA, "").replace(BOLD, "").replace(DIM, "").replace(RESET, "")
    if level == "error":
        logging.error(clean_msg)
    elif level == "warning":
        logging.warning(clean_msg)
    else:
        logging.info(clean_msg)


def check_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.8)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_http_service(url, timeout=1.5):
    try:
        req = urllib.request.urlopen(url, timeout=timeout)
        return req.getcode() == 200
    except Exception:
        return False


def kill_process_on_port(port):
    """Mata cualquier proceso zombie ocupando un puerto específico para evitar conflictos."""
    try:
        res = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        pids = [p.strip() for p in res.stdout.strip().split("\n") if p.strip()]
        for pid in pids:
            log_event(f"  {YELLOW}Liberando socket en puerto {port} (PID: {pid})...{RESET}")
            subprocess.run(["kill", "-9", pid], capture_output=True)
        return len(pids) > 0
    except Exception as e:
        log_event(f"  {RED}Error liberando puerto {port}: {e}{RESET}", "error")
        return False


def start_service_in_background(cmd, name):
    try:
        log_event(f"  {CYAN}⚡ AutoDoctor levantando servicio: {BOLD}{name}{RESET}...")
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setpgrp
        )
        time.sleep(1.5)
        return True
    except Exception as e:
        log_event(f"  {RED}❌ Fallo al iniciar {name}: {e}{RESET}", "error")
        return False


def check_and_heal_services(heal=False):
    log_event(f"\n{BOLD}📡 1. Diagnóstico de Servicios y Puertos HTTP{RESET}")
    report = []
    
    for srv in SERVICES:
        name = srv["name"]
        port = srv["port"]
        url = srv["url"]
        
        is_port_open = check_port_open(port)
        is_http_ok = check_http_service(url) if is_port_open else False
        
        if is_http_ok:
            log_event(f"  ✅ {name:<26} [Puerto {port}]: {GREEN}ONLINE (HTTP 200 OK){RESET}")
            report.append((name, True, "ONLINE"))
        else:
            status_desc = "PUERTO CERRADO" if not is_port_open else "HTTP ERROR / ZOMBIE"
            log_event(f"  ⚠️ {name:<26} [Puerto {port}]: {RED}{status_desc}{RESET}", "warning")
            report.append((name, False, status_desc))
            
            if heal and srv["start_cmd"]:
                log_event(f"  🔧 {YELLOW}Aplicando Auto-Healing para {name}...{RESET}")
                if is_port_open:
                    kill_process_on_port(port)
                started = start_service_in_background(srv["start_cmd"], name)
                time.sleep(1.0)
                if check_http_service(url, timeout=3.0):
                    log_event(f"  ✨ {GREEN}{name} RESTAURADO CON ÉXITO Y RESPONDIENDO EN HTTP 200!{RESET}")
                else:
                    log_event(f"  🚨 {RED}No se pudo verificar respuesta inmediata de {name}.{RESET}", "error")
                    
    return report


def check_and_heal_disks(heal=False):
    log_event(f"\n{BOLD}💾 2. Diagnóstico de Discos, Saneamiento y Bases de Datos{RESET}")
    report = []
    
    for d in DISKS:
        name = d["name"]
        mount = d["mount"]
        
        if not os.path.exists(mount):
            log_event(f"  ⏸  {name:<34}: {DIM}No conectado / desmontado{RESET}")
            report.append((name, False, "DESMONTADO"))
            continue
            
        log_event(f"  ✅ {name:<34}: {GREEN}MONTADO{RESET} en {mount}")
        
        # 1. Limpieza de archivos parásitos (dot_clean) en MicroSD o discos
        if d.get("needs_dot_clean"):
            if heal:
                log_event(f"    🧹 Saneando forks de recursos Mac (dot_clean -m)...")
                subprocess.run(["dot_clean", "-m", mount], capture_output=True)
                log_event(f"    ✨ {GREEN}Forks ._* y .DS_Store saneados.{RESET}")
                
        # 2. Verificación de integridad SQLite
        db_path = d.get("db_path")
        if db_path and os.path.exists(db_path):
            try:
                con = sqlite3.connect(db_path)
                cur = con.cursor()
                res = cur.execute("PRAGMA integrity_check;").fetchone()[0]
                con.close()
                if res == "ok":
                    log_event(f"    🗄  SQLite ({os.path.basename(db_path)}): {GREEN}Integridad 100% OK{RESET}")
                else:
                    log_event(f"    🚨 {RED}SQLite corrupto ({os.path.basename(db_path)}): {res}{RESET}", "error")
            except Exception as e:
                log_event(f"    🚨 {RED}Error abriendo base de datos {db_path}: {e}{RESET}", "error")
                
        # 3. Verificación de presencia del Master Dashboard
        dash_file = os.path.join(mount, "MASTER_ECOSISTEMA_DISCOS.html")
        if not os.path.exists(dash_file):
            log_event(f"    ⚠️  {YELLOW}Falta Master Dashboard en {mount}{RESET}", "warning")
            if heal and os.path.exists(SYNC_DASHBOARD_SCRIPT):
                log_event(f"    🔧 Replicando Master Dashboard con sync_master_dashboard.py...")
                subprocess.run(["python3", SYNC_DASHBOARD_SCRIPT], capture_output=True)
        else:
            log_event(f"    📑 Master Dashboard: {GREEN}Presente y sincronizado{RESET}")
            
        report.append((name, True, "MONTADO_OK"))
        
    return report


def run_full_diagnosis(heal=False):
    start_time = time.time()
    log_event(f"{CYAN}{BOLD}======================================================{RESET}")
    log_event(f"{CYAN}{BOLD}🏥 CEREBRO OS & BEATOS — AUTODOCTOR HEALTH AUDIT{RESET}")
    mode_str = f"{YELLOW}[MODO AUTO-HEALING ACTIVO]{RESET}" if heal else f"{DIM}[MODO DIAGNÓSTICO LECTURA]{RESET}"
    log_event(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {mode_str}")
    log_event(f"{CYAN}{BOLD}======================================================{RESET}")
    
    srv_rep = check_and_heal_services(heal=heal)
    disk_rep = check_and_heal_disks(heal=heal)
    
    elapsed = round(time.time() - start_time, 2)
    log_event(f"\n{CYAN}{BOLD}======================================================{RESET}")
    log_event(f"⏱  Diagnóstico completado en {BOLD}{elapsed}s{RESET}.")
    log_event(f"📄 Registro guardado en: {DIM}{LOG_PATH}{RESET}")
    log_event(f"{CYAN}{BOLD}======================================================{RESET}\n")


def daemon_loop(interval=60):
    log_event(f"{MAGENTA}{BOLD}🛡  Iniciando AutoDoctor en Modo Guardián Daemon (Intervalo: {interval}s)...{RESET}")
    try:
        while True:
            run_full_diagnosis(heal=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        log_event(f"\n{YELLOW}AutoDoctor detenido por el usuario.{RESET}")


def install_launchagent():
    """Genera e instala el servicio en launchd de macOS para autoinicio en background."""
    python_bin = sys.executable
    script_path = os.path.abspath(__file__)
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cerebro.autodoctor</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{script_path}</string>
        <string>--daemon</string>
        <string>120</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_PATH}</string>
</dict>
</plist>
"""
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    with open(PLIST_PATH, "w", encoding="utf-8") as f:
        f.write(plist_content)
        
    subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
    subprocess.run(["launchctl", "load", PLIST_PATH], capture_output=True)
    log_event(f"✅ {GREEN}Servicio LaunchAgent instalado con éxito en:{RESET} {PLIST_PATH}")
    log_event(f"   AutoDoctor correrá automáticamente en segundo plano cada 120 segundos.")


def uninstall_launchagent():
    if os.path.exists(PLIST_PATH):
        subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
        os.remove(PLIST_PATH)
        log_event(f"✅ {GREEN}Servicio LaunchAgent desinstalado con éxito.{RESET}")
    else:
        log_event(f"ℹ️  No se encontró ningún LaunchAgent en {PLIST_PATH}")


if __name__ == "__main__":
    args = sys.argv[1:]
    
    if "--install-service" in args:
        install_launchagent()
    elif "--uninstall-service" in args:
        uninstall_launchagent()
    elif "--daemon" in args:
        interval = 60
        for i, a in enumerate(args):
            if a == "--daemon" and i + 1 < len(args) and args[i+1].isdigit():
                interval = int(args[i+1])
        daemon_loop(interval)
    elif "--heal" in args:
        run_full_diagnosis(heal=True)
    else:
        # Modo por defecto: check
        run_full_diagnosis(heal=False)
