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
echo -e "${GOLD}  Versión 1.0.0 • Open Source Community Edition${NC}"
echo "=============================================================================="

# 1. Comprobación de requisitos
echo -e "\n${BOLD}[1/3] Comprobando dependencias...${NC}"

if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo -e "  ${GREEN}✔ Python 3 detectado (versión $PY_VER)${NC}"
else
    echo -e "  ${RED}❌ Error: Se requiere Python 3 para ejecutar este toolkit.${NC}"
    exit 1
fi

if command -v sqlite3 &>/dev/null; then
    SQL_VER=$(sqlite3 --version | awk '{print $1}')
    echo -e "  ${GREEN}✔ SQLite 3 detectado (versión $SQL_VER)${NC}"
else
    echo -e "  ${GOLD}⚠️ Aviso: sqlite3 CLI no está en el PATH, pero Python incluye sqlite3 nativo.${NC}"
fi

# 2. Menú de Opciones
echo -e "\n${BOLD}[2/3] Selecciona una opción:${NC}"
echo -e "  ${CYAN}1)${NC} Indexar automáticamente una tarjeta SD o carpeta de samples"
echo -e "  ${CYAN}2)${NC} Inicializar una Base de Datos SQLite vacía desde schema.sql"
echo -e "  ${CYAN}3)${NC} Abrir el Catálogo Web HTML en el navegador"
echo -e "  ${CYAN}4)${NC} Salir"

read -p "Elige una opción [1-4]: " OPTION

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
        
        if [ -f "$TARGET_PATH/SQLITE_DATABASE/catalogo_mpc_sample.html" ]; then
            echo -e "\n${GREEN}✔ Catálogo generado con éxito.${NC}"
            if [[ "$OSTYPE" == "darwin"* ]]; then
                open "$TARGET_PATH/SQLITE_DATABASE/catalogo_mpc_sample.html"
            elif command -v xdg-open &>/dev/null; then
                xdg-open "$TARGET_PATH/SQLITE_DATABASE/catalogo_mpc_sample.html"
            fi
        fi
        ;;
    2)
        DB_NAME="mpc_sample_master.db"
        echo -e "\n${CYAN}Creando base de datos:${NC} $DB_NAME desde schema.sql..."
        sqlite3 "$DB_NAME" < "$SCRIPT_DIR/schema.sql"
        echo -e "${GREEN}✔ Base de datos inicializada: $SCRIPT_DIR/$DB_NAME${NC}"
        ;;
    3)
        CATALOG_FILE=$(find "$SCRIPT_DIR" -maxdepth 2 -name "*catalogo*.html" | head -n 1)
        if [ -n "$CATALOG_FILE" ]; then
            echo -e "${GREEN}Abriendo catálogo:${NC} $CATALOG_FILE"
            if [[ "$OSTYPE" == "darwin"* ]]; then
                open "$CATALOG_FILE"
            elif command -v xdg-open &>/dev/null; then
                xdg-open "$CATALOG_FILE"
            fi
        else
            echo -e "${RED}No se encontró ningún catálogo HTML generado. Ejecuta la opción 1 primero.${NC}"
        fi
        ;;
    4)
        echo "Saliendo..."
        exit 0
        ;;
    *)
        echo -e "${RED}Opción inválida.${NC}"
        exit 1
        ;;
esac

echo -e "\n${GREEN}${BOLD}✨ ¡Listo para usar con tu hardware Akai MPC!${NC}"
