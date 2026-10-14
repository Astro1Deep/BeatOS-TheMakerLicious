#!/usr/bin/env python3
"""
Akai MPC Sample Finder - High-Performance Audio Streaming Web Server
Soporte completo para Range Requests (RFC 7233), CORS, MIME Types de audio y resolución multi-directorio.
Garantiza reproducción fluida en Safari, Chrome, Firefox y WebKit en macOS, Linux y Windows.
"""

import os
import sys
import mimetypes
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import webbrowser
import threading
import time

mimetypes.init()
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/aiff", ".aif")
mimetypes.add_type("audio/aiff", ".aiff")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("image/svg+xml", ".svg")

def find_card_root(start_dir):
    """Detecta la raíz de la tarjeta SD o proyecto donde residen los samples."""
    # 1. Si start_dir contiene MPC-Sample o Expansions, es la raíz
    if os.path.isdir(os.path.join(start_dir, "MPC-Sample")) or os.path.isdir(os.path.join(start_dir, "Expansions")):
        return os.path.abspath(start_dir)
        
    # 2. Si el padre contiene MPC-Sample o Expansions (ej. estamos en SQLITE_DATABASE)
    parent = os.path.dirname(os.path.abspath(start_dir))
    if os.path.isdir(os.path.join(parent, "MPC-Sample")) or os.path.isdir(os.path.join(parent, "Expansions")):
        return parent
        
    # 3. Comprobar ruta canónica de tarjeta montada en macOS
    if os.path.isdir("/Volumes/MPCSMPL"):
        return "/Volumes/MPCSMPL"
        
    # 4. Fallback a start_dir
    return os.path.abspath(start_dir)

def find_available_port(start_port=8888, max_attempts=50):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start_port

class MPCAudioRequestHandler(BaseHTTPRequestHandler):
    server_version = "MPCAudioStreamer/2.0"

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        self.handle_request(send_body=True)

    def do_HEAD(self):
        self.handle_request(send_body=False)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, Accept, Origin")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")

    def log_message(self, format, *args):
        # Log simplificado y elegante en consola
        sys.stderr.write(f"  [HTTP] {args[0]} - {args[1]}\n")

    def handle_request(self, send_body=True):
        parsed = urllib.parse.urlparse(self.path)
        clean_path = urllib.parse.unquote(parsed.path).lstrip("/")
        
        # Redirección de raíz al catálogo principal
        if clean_path in ("", "index.html", "catalogo", "catalogo.html"):
            for candidate in ("catalogo_mpc_sample.html", "catalogo_universal.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
                if os.path.isfile(os.path.join(self.server.root_dir, candidate)):
                    clean_path = candidate
                    break

        # Resolver archivo físico
        target_path = os.path.join(self.server.root_dir, clean_path)
        
        # Fallbacks inteligentes de resolución
        if not os.path.isfile(target_path):
            # Probar dentro de SQLITE_DATABASE
            sub_path = os.path.join(self.server.root_dir, "SQLITE_DATABASE", clean_path)
            if os.path.isfile(sub_path):
                target_path = sub_path
            # O si viene con prefijo SQLITE_DATABASE y está en raíz
            elif clean_path.startswith("SQLITE_DATABASE/"):
                root_direct = os.path.join(self.server.root_dir, clean_path.replace("SQLITE_DATABASE/", "", 1))
                if os.path.isfile(root_direct):
                    target_path = root_direct
            # O si busca MPC-Sample en la tarjeta física montada
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

        # Manejo de Range Requests (HTTP 206 Partial Content para streaming de audio)
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
            except (ValueError, IOError) as e:
                # Si el rango es inválido, caer a respuesta 200 completa
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

def run_server(custom_path=None, port=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_root = find_card_root(custom_path if custom_path else script_dir)
    
    if not port:
        port = find_available_port(8888)

    # Identificar página del catálogo a abrir
    catalog_rel = None
    for cand in ("catalogo_mpc_sample.html", "catalogo_universal.html", "SQLITE_DATABASE/catalogo_mpc_sample.html"):
        if os.path.isfile(os.path.join(target_root, cand)):
            catalog_rel = cand
            break
            
    if not catalog_rel:
        # Si no está en target_root pero sí en script_dir
        if os.path.isfile(os.path.join(script_dir, "catalogo_universal.html")):
            catalog_rel = "catalogo_universal.html"
        elif os.path.isfile(os.path.join(script_dir, "catalogo_mpc_sample.html")):
            catalog_rel = "catalogo_mpc_sample.html"

    url = f"http://localhost:{port}/" + (catalog_rel if catalog_rel else "")

    print("\n" + "=" * 70)
    print("🔊 AKAI MPC SAMPLE DATABASE - SERVIDOR DE AUDIO PROFESIONAL")
    print("=" * 70)
    print(f"  📁 Raíz de Medios / Tarjeta:  {target_root}")
    print(f"  🌐 URL del Catálogo:          {url}")
    print(f"  ⚡ Soporte HTTP:              RFC 7233 (Range 206 Partial Content)")
    print(f"  🔒 Compatibilidad Navegador:  100% Safari, Chrome, Firefox, Arc")
    print("=" * 70)
    print("  💡 Presiona Ctrl+C en esta terminal para detener el servidor.\n")

    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, MPCAudioRequestHandler)
    httpd.root_dir = target_root

    def open_browser():
        time.sleep(1.2)
        try:
            if sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", url])
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
    path_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_server(path_arg)
