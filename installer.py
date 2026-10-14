#!/usr/bin/env python3
"""
Akai MPC Sample Database Toolkit - Cross-Platform Python Installer
Compatible con Windows, macOS y Linux.
Permite indexación rápida, servidor web local sin restricciones, limpieza y gestión SQLite.
"""

import os
import sys
import subprocess
import shutil
import time

def open_url_or_file(target):
    if sys.platform == "darwin":
        subprocess.run(["open", target])
    elif sys.platform == "win32":
        os.startfile(target)
    else:
        subprocess.run(["xdg-open", target])

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("=" * 70)
    print("🎛️  AKAI MPC SAMPLE DATABASE & FINDER TOOLKIT - INSTALADOR UNIVERSAL")
    print("    Versión 1.1.0 • Astro1Deep • Compatible con Akai MPC Standalone")
    print("=" * 70)
    print("1. 🚀 Indexar tarjeta Micro SD o carpeta de samples para MPC")
    print("2. 🌐 Iniciar Servidor Web Local y Abrir Catálogo (Reproducción 100% garantizada)")
    print("3. 🧹 Limpiar archivos fantasma (._* y .DS_Store) en tarjeta SD")
    print("4. 🗄️  Inicializar base de datos SQLite en blanco desde schema.sql")
    print("5. 📚 Abrir Wiki Oficial y Guías de Uso")
    print("6. 🚪 Salir")
    print("=" * 70)
    
    choice = input("Elige una opción (1-6): ").strip()
    
    if choice == "1":
        path = input("Ingresa la ruta de la tarjeta SD / samples (Enter para carpeta actual): ").strip()
        if not path:
            path = script_dir
        
        # Limpieza previa si es Mac
        if sys.platform == "darwin":
            subprocess.run(["dot_clean", "-m", path], stderr=subprocess.DEVNULL)
            
        cmd = [sys.executable, os.path.join(script_dir, "index_mpc_library.py"), "--path", path]
        subprocess.run(cmd)
        
        cat_path = os.path.join(path, "catalogo_mpc_sample.html")
        cat_sub = os.path.join(path, "SQLITE_DATABASE", "catalogo_mpc_sample.html")
        target_cat = cat_path if os.path.exists(cat_path) else (cat_sub if os.path.exists(cat_sub) else None)
        
        if target_cat:
            ans = input("\n¿Deseas abrir el catálogo en tu navegador ahora? (s/n): ").strip().lower()
            if ans in ["s", "y", "si", "yes"]:
                open_url_or_file(target_cat)
                
    elif choice == "2":
        path = input("Ingresa la ruta de la tarjeta SD (Enter para carpeta actual): ").strip()
        if not path:
            path = script_dir
            
        port = 8888
        url = f"http://localhost:{port}/catalogo_mpc_sample.html"
        print(f"\n🌐 Iniciando servidor web en: {url}")
        print("💡 Para detener el servidor, presiona Ctrl+C en esta terminal.\n")
        
        import threading
        def delayed_open():
            time.sleep(1)
            open_url_or_file(url)
            
        threading.Thread(target=delayed_open, daemon=True).start()
        
        from http.server import HTTPServer, SimpleHTTPRequestHandler
        import functools
        handler = functools.partial(SimpleHTTPRequestHandler, directory=path)
        httpd = HTTPServer(('127.0.0.1', port), handler)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")
            
    elif choice == "3":
        path = input("Ingresa la ruta a limpiar (Enter para carpeta actual): ").strip()
        if not path:
            path = script_dir
        print(f"Limpiando archivos en: {path}...")
        count = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                if f.startswith("._") or f == ".DS_Store":
                    try:
                        os.remove(os.path.join(root, f))
                        count += 1
                    except:
                        pass
        print(f"✔ Se eliminaron {count} archivos innecesarios de metadatos.")
        
    elif choice == "4":
        db_path = os.path.join(script_dir, "mpc_sample_master.db")
        schema_path = os.path.join(script_dir, "schema.sql")
        import sqlite3
        conn = sqlite3.connect(db_path)
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.close()
        print(f"✔ Base de datos SQLite creada con éxito en: {db_path}")
        
    elif choice == "5":
        wiki_url = "https://github.com/Astro1Deep/mpc-sample-database/wiki"
        print(f"Abriendo Wiki: {wiki_url}")
        open_url_or_file(wiki_url)
        
    else:
        print("Saliendo.")

if __name__ == "__main__":
    main()
