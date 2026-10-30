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


# Installer prompts use the selected locale; no extra input is requested from existing users.
_INSTALLER_EN = {"🎛️  AKAI MPC SAMPLE DATABASE & FINDER TOOLKIT - INSTALADOR UNIVERSAL": "🎛️  BEATOS — THE MAKERLICIOUS — Universal installer","    BeatOS 3.8.0 • Astro1Deep • Compatible con Akai MPC Standalone": "    BeatOS 3.8.0 • Astro1Deep • Hardware sampler kit workstation","1. 🚀 Indexar tarjeta Micro SD o carpeta de samples para MPC": "1. 🚀 Index a sample folder or MicroSD card","2. 🌐 Iniciar Servidor Web Local y Abrir Catálogo (Audio y herramientas locales)": "2. 🌐 Start local web server and open catalog","3. 🧹 Limpiar archivos fantasma (._* y .DS_Store) en tarjeta SD": "3. 🧹 Remove auxiliary AppleDouble / .DS_Store files","4. 🗄️  Inicializar base de datos SQLite en blanco desde schema.sql": "4. 🗄️  Initialize SQLite schema from schema.sql","5. 📚 Abrir Wiki Oficial y Guías de Uso": "5. 📚 Open documentation","6. 🚪 Salir": "6. 🚪 Exit","Elige una opción (1-6):  ": "Choose an option (1-6):  ","Ingresa la ruta de la tarjeta SD / samples (Enter para carpeta actual):  ": "Enter SD card / sample-library path (Enter for default):  ","\\n¿Deseas abrir el catálogo en tu navegador ahora? (s/n):  ": "\\nOpen the catalog in your browser now? (y/n):  ","Ingresa la ruta de la tarjeta SD (Enter para carpeta de instalación):  ": "Enter sample library path (Enter for default):  ","Ingresa la ruta a limpiar (Enter para carpeta actual):  ": "Enter directory to clean (Enter for default):  ","Limpiando archivos en:  {path}...": "Removing auxiliary files in:  {path}...","✔ Se eliminaron {count} archivos innecesarios de metadatos.": "✔ Removed {count} auxiliary metadata files.","✔ Base de datos SQLite creada con éxito en:  {db_path}": "✔ SQLite schema initialized at:  {db_path}","Abriendo Wiki:  {wiki_url}": "Opening documentation:  {wiki_url}","Saliendo.": "Exiting."}
def get_language(argv=None, environ=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return "en" if argv[i + 1].lower() == "en" else "es"
        if arg.startswith("--lang="):
            return "en" if arg.partition("=")[2].lower() == "en" else "es"
    return "en" if environ.get("BEATOS_LANG", "es").lower() == "en" else "es"

def locale_text(message, lang=None):
    return _INSTALLER_EN.get(message, message) if (lang or get_language()) == "en" else message

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
    print(locale_text("🎛️  AKAI MPC SAMPLE DATABASE & FINDER TOOLKIT - INSTALADOR UNIVERSAL"))
    print(locale_text("    BeatOS 3.8.0 • Astro1Deep • Compatible con Akai MPC Standalone"))
    print("=" * 70)
    print(locale_text("1. 🚀 Indexar tarjeta Micro SD o carpeta de samples para MPC"))
    print(locale_text("2. 🌐 Iniciar Servidor Web Local y Abrir Catálogo (Audio y herramientas locales)"))
    print(locale_text("3. 🧹 Limpiar archivos fantasma (._* y .DS_Store) en tarjeta SD"))
    print(locale_text("4. 🗄️  Inicializar base de datos SQLite en blanco desde schema.sql"))
    print(locale_text("5. 📚 Abrir Wiki Oficial y Guías de Uso"))
    print(locale_text("6. 🚪 Salir"))
    print("=" * 70)
    
    choice = input(locale_text("Elige una opción (1-6): ")).strip()
    
    if choice == "1":
        path = input(locale_text("Ingresa la ruta de la tarjeta SD / samples (Enter para carpeta actual): ")).strip()
        if not path:
            path = str(default_library_root(script_dir))
        
            
        cmd = [sys.executable, os.path.join(script_dir, "index_mpc_library.py"), "--path", path]
        subprocess.run(cmd, check=True)
        
        cat_path = os.path.join(path, "catalogo_mpc_sample.html")
        cat_sub = os.path.join(path, "SQLITE_DATABASE", "catalogo_mpc_sample.html")
        target_cat = cat_path if os.path.exists(cat_path) else (cat_sub if os.path.exists(cat_sub) else None)
        
        if target_cat:
            ans = input(locale_text("\n¿Deseas abrir el catálogo en tu navegador ahora? (s/n): ")).strip().lower()
            if ans in ["s", "y", "si", "yes"]:
                import serve_mpc
                serve_mpc.run_server(os.path.abspath(path))
                
    elif choice == "2":
        path = input(locale_text("Ingresa la ruta de la tarjeta SD (Enter para carpeta de instalación): ")).strip()
        try:
            import serve_mpc
            serve_mpc.run_server(path if path else str(default_library_root(script_dir)))
        except ImportError:
            # Fallback inline si serve_mpc no estuviera disponible
            subprocess.run([sys.executable, os.path.join(script_dir, "serve_mpc.py"), path if path else ""])
            
    elif choice == "3":
        path = input(locale_text("Ingresa la ruta a limpiar (Enter para carpeta actual): ")).strip()
        if not path:
            path = str(default_library_root(script_dir))
        print(locale_text("Limpiando archivos en: {path}...").format(path=path))
        count = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                if f.startswith("._") or f == ".DS_Store":
                    try:
                        os.remove(os.path.join(root, f))
                        count += 1
                    except:
                        pass
        print(locale_text("✔ Se eliminaron {count} archivos innecesarios de metadatos.").format(count=count))
        
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
        print(locale_text("✔ Base de datos SQLite creada con éxito en: {db_path}").format(db_path=db_path))
        
    elif choice == "5":
        wiki_url = "https://github.com/Astro1Deep/BeatOS-TheMakerLicious/blob/main/docs/wiki/Home.md"
        print(locale_text("Abriendo Wiki: {wiki_url}").format(wiki_url=wiki_url))
        open_url_or_file(wiki_url)
        
    else:
        print(locale_text("Saliendo."))

if __name__ == "__main__":
    main()
