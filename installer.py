#!/usr/bin/env python3
"""
Akai MPC Sample Database Toolkit - Cross-Platform Python Installer
Compatible con Windows, macOS y Linux.
"""

import os
import sys
import subprocess
import shutil

def main():
    print("=" * 65)
    print("🎛️  AKAI MPC SAMPLE DATABASE & FINDER TOOLKIT - INSTALADOR")
    print("=" * 65)
    print("1. Indexar una tarjeta Micro SD o carpeta de samples para MPC")
    print("2. Inicializar base de datos SQLite en blanco desde schema.sql")
    print("3. Abrir Catálogo Web en el navegador")
    print("4. Salir")
    print("=" * 65)
    
    choice = input("Elige una opción (1-4): ").strip()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if choice == "1":
        path = input("Ingresa la ruta de la tarjeta SD / samples (Enter para carpeta actual): ").strip()
        if not path:
            path = script_dir
        cmd = [sys.executable, os.path.join(script_dir, "index_mpc_library.py"), "--path", path]
        subprocess.run(cmd)
        
        cat_path = os.path.join(path, "SQLITE_DATABASE", "catalogo_mpc_sample.html")
        if os.path.exists(cat_path):
            if sys.platform == "darwin":
                subprocess.run(["open", cat_path])
            elif sys.platform == "win32":
                os.startfile(cat_path)
            else:
                subprocess.run(["xdg-open", cat_path])
                
    elif choice == "2":
        db_path = os.path.join(script_dir, "mpc_sample_master.db")
        schema_path = os.path.join(script_dir, "schema.sql")
        import sqlite3
        conn = sqlite3.connect(db_path)
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.close()
        print(f"✔ Base de datos SQLite creada con éxito en: {db_path}")
        
    elif choice == "3":
        for root, _, files in os.walk(script_dir):
            for f in files:
                if f.endswith(".html"):
                    fp = os.path.join(root, f)
                    print(f"Abriendo: {fp}")
                    if sys.platform == "darwin":
                        subprocess.run(["open", fp])
                    elif sys.platform == "win32":
                        os.startfile(fp)
                    else:
                        subprocess.run(["xdg-open", fp])
                    return
        print("No se encontró ningún catálogo HTML. Ejecuta la opción 1 primero.")
        
    else:
        print("Saliendo.")

if __name__ == "__main__":
    main()
