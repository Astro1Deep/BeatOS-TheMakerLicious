#!/usr/bin/env bash
# ==============================================================================
# Akai MPC Sample Database & Finder Toolkit - Instalador Oficial
# Compatible con: macOS y Linux | Akai MPC Live, One, X, Key, Studio
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
GOLD='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${RED}${BOLD}"
echo "  ███╗   ███╗██████╗  ██████╗    ███████╗ █████╗ ███╗   ███╗██████╗ ██╗     ███████╗"
echo "  ████╗ ████║██╔══██╗██╔════╝    ██╔════╝██╔══██╗████╗ ████║██╔══██╗██║     ██╔════╝"
echo "  ██╔████╔██║██████╔╝██║         ███████╗███████║██╔████╔██║██████╔╝██║     █████╗  "
echo "  ██║╚██╔╝██║██╔═══╝ ██║         ╚════██║██╔══██║██║╚██╔╝██║██╔═══╝ ██║     ██╔══╝  "
echo "  ██║ ╚═╝ ██║██║     ╚██████╗    ███████║██║  ██║██║ ╚═╝ ██║██║     ███████╗███████╗"
echo "  ╚═╝     ╚═╝╚═╝      ╚═════╝    ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝"
echo -e "${NC}"
echo -e "${CYAN}  🎛️  Toolkit de Base de Datos SQLite y Catálogo Visual para Akai MPC${NC}"
echo -e "${GOLD}  BeatOS 3.6.5 • Open Source Community Edition • Astro1Deep${NC}"
echo "=============================================================================="

# 1. Comprobación de requisitos
echo -e "\n${BOLD}[1/2] Comprobando dependencias...${NC}"

if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo -e "  ${GREEN}✔ Python 3 detectado (versión $PY_VER)${NC}"
else
    echo -e "  ${RED}❌ Error: Se requiere Python 3 para ejecutar este toolkit.${NC}"
    exit 1
fi

if command -v sqlite3 &>/dev/null; then
    SQL_VER=$(sqlite3 --version | awk '{print $1}')
    echo -e "  ${GREEN}✔ SQLite 3 CLI detectado (versión $SQL_VER)${NC}"
else
    echo -e "  ${GOLD}ℹ️ SQLite 3 CLI no está en el PATH, pero Python utilizará sqlite3 integrado.${NC}"
fi

# 2. Menú de Opciones
echo -e "\n${BOLD}[2/2] Selecciona una opción:${NC}"
echo -e "  ${CYAN}1)${NC} 🚀 Indexar automáticamente tarjeta Micro SD o carpeta de samples"
echo -e "  ${CYAN}2)${NC} 🌐 Iniciar Servidor Web Local y Abrir Catálogo (Audio y herramientas locales)"
echo -e "  ${CYAN}3)${NC} 🧹 Limpiar archivos fantasma de macOS (._* y .DS_Store) en la tarjeta"
echo -e "  ${CYAN}4)${NC} 🗄️ Inicializar una Base de Datos SQLite vacía desde schema.sql"
echo -e "  ${CYAN}5)${NC} 📚 Abrir Wiki y Documentación Oficial"
echo -e "  ${CYAN}6)${NC} 🚪 Salir"

read -p "Elige una opción [1-6]: " OPTION

case $OPTION in
    1)
        echo -e "\n${BOLD}Ruta a indexar:${NC}"
        echo -e "Ingresa la ruta absoluta (o presiona ENTER para usar la carpeta actual):"
        read -p "> " TARGET_PATH
        if [ -z "$TARGET_PATH" ]; then
            TARGET_PATH="$SCRIPT_DIR"
        fi
        
        echo -e "\n${CYAN}Iniciando indexador en:${NC} $TARGET_PATH"
        python3 "$SCRIPT_DIR/index_mpc_library.py" --path "$TARGET_PATH"
        
        CAT_ROOT="$TARGET_PATH/catalogo_mpc_sample.html"
        CAT_SUB="$TARGET_PATH/SQLITE_DATABASE/catalogo_mpc_sample.html"
        TARGET_CAT=""
        if [ -f "$CAT_ROOT" ]; then TARGET_CAT="$CAT_ROOT"; elif [ -f "$CAT_SUB" ]; then TARGET_CAT="$CAT_SUB"; fi
        
        if [ -n "$TARGET_CAT" ]; then
            echo -e "\n${GREEN}✔ Catálogo generado con éxito: $TARGET_CAT${NC}"
            echo -e "¿Deseas abrir el catálogo en tu navegador ahora? (s/n)"
            read -p "> " OPEN_NOW
            if [[ "$OPEN_NOW" =~ ^[sSyY] ]]; then
                python3 "$SCRIPT_DIR/serve_mpc.py" "$TARGET_PATH"
            fi
        fi
        ;;
    2)
        echo -e "\n${BOLD}Ruta del catálogo / tarjeta SD:${NC}"
        echo -e "Ingresa la ruta raíz de la tarjeta (o ENTER para auto-detectar tarjeta montada):"
        read -p "> " SERVE_PATH
        
        python3 "$SCRIPT_DIR/serve_mpc.py" "$SERVE_PATH"
        ;;
    3)
        echo -e "\n${BOLD}Ruta a limpiar de metadatos de macOS:${NC}"
        read -p "> " CLEAN_PATH
        if [ -z "$CLEAN_PATH" ]; then
            CLEAN_PATH="$SCRIPT_DIR"
        fi
        echo -e "${CYAN}Purgando archivos ._* y .DS_Store en:${NC} $CLEAN_PATH"
        if command -v dot_clean &>/dev/null; then
            dot_clean -m "$CLEAN_PATH" 2>/dev/null || true
        fi
        find "$CLEAN_PATH" -name "._*" -delete 2>/dev/null || true
        find "$CLEAN_PATH" -name ".DS_Store" -delete 2>/dev/null || true
        echo -e "${GREEN}✔ Limpieza completada. La tarjeta está 100% optimizada para Akai MPC Standalone.${NC}"
        ;;
    4)
        DB_NAME="mpc_sample_master.db"
        echo -e "\n${CYAN}Creando base de datos vacía:${NC} $DB_NAME desde schema.sql..."
        if command -v sqlite3 &>/dev/null; then
            sqlite3 "$DB_NAME" < "$SCRIPT_DIR/schema.sql"
        else
            python3 -c "import sqlite3; conn = sqlite3.connect('$DB_NAME'); conn.executescript(open('$SCRIPT_DIR/schema.sql').read()); conn.close()"
        fi
        echo -e "${GREEN}✔ Base de datos inicializada: $SCRIPT_DIR/$DB_NAME${NC}"
        ;;
    5)
        WIKI_URL="https://github.com/Astro1Deep/mpc-sample-database/wiki"
        LOCAL_WIKI="$SCRIPT_DIR/docs/wiki/Home.md"
        echo -e "${CYAN}Abriendo Wiki Oficial:${NC} $WIKI_URL"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            open "$WIKI_URL" || open "$LOCAL_WIKI"
        elif command -v xdg-open &>/dev/null; then
            xdg-open "$WIKI_URL" || xdg-open "$LOCAL_WIKI"
        fi
        ;;
    6)
        echo "Saliendo..."
        exit 0
        ;;
    *)
        echo -e "${RED}Opción inválida.${NC}"
        exit 1
        ;;
esac

echo -e "\n${GREEN}${BOLD}✨ ¡Listo para producir en tu hardware Akai MPC!${NC}"
