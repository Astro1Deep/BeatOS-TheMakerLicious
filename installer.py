#!/usr/bin/env python3
"""
Akai MPC Sample Database Toolkit - Cross-Platform Python Installer
Compatible con Windows, macOS y Linux.
Permite indexación rápida, servidor web local sin restricciones, limpieza y gestión SQLite.
"""

import os
import sys
sys.dont_write_bytecode = True
from beatos_paths import data_dir, default_library_root
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
    print("    BeatOS 3.7.1 • Astro1Deep • Compatible con Akai MPC Standalone")
    print("=" * 70)
    print("1. 🚀 Indexar tarjeta Micro SD o carpeta de samples para MPC")
    print("2. 🌐 Iniciar Servidor Web Local y Abrir Catálogo (Audio y herramientas locales)")
    print("3. 🧹 Limpiar archivos fantasma (._* y .DS_Store) en tarjeta SD")
    print("4. 🗄️  Inicializar base de datos SQLite en blanco desde schema.sql")
    print("5. 📚 Abrir Wiki Oficial y Guías de Uso")
    print("6. 🚪 Salir")
    print("=" * 70)
    
    choice = input("Elige una opción (1-6): ").strip()
    
    if choice == "1":
        path = input("Ingresa la ruta de la tarjeta SD / samples (Enter para carpeta actual): ").strip()
        if not path:
            path = str(default_library_root(script_dir))
        
            
        cmd = [sys.executable, os.path.join(script_dir, "index_mpc_library.py"), "--path", path]
        subprocess.run(cmd, check=True)
        
        cat_path = os.path.join(path, "catalogo_mpc_sample.html")
        cat_sub = os.path.join(path, "SQLITE_DATABASE", "catalogo_mpc_sample.html")
        target_cat = cat_path if os.path.exists(cat_path) else (cat_sub if os.path.exists(cat_sub) else None)
        
        if target_cat:
            ans = input("\n¿Deseas abrir el catálogo en tu navegador ahora? (s/n): ").strip().lower()
            if ans in ["s", "y", "si", "yes"]:
                import serve_mpc
                serve_mpc.run_server(os.path.abspath(path))
                
    elif choice == "2":
        path = input("Ingresa la ruta de la tarjeta SD (Enter para carpeta de instalación): ").strip()
        try:
            import serve_mpc
            serve_mpc.run_server(path if path else str(default_library_root(script_dir)))
        except ImportError:
            # Fallback inline si serve_mpc no estuviera disponible
            subprocess.run([sys.executable, os.path.join(script_dir, "serve_mpc.py"), path if path else ""])
            
    elif choice == "3":
        path = input("Ingresa la ruta a limpiar (Enter para carpeta actual): ").strip()
        if not path:
            path = str(default_library_root(script_dir))
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
        output = data_dir(default_library_root(script_dir))
        output.mkdir(parents=True, exist_ok=True)
        db_path = output / "mpc_sample.db"
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
