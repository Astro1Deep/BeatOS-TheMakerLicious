#!/usr/bin/env bash
# ==============================================================================
# Script de Sincronización Automática de la Wiki con GitHub
# Repositorio: Astro1Deep/mpc-sample-database
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
GOLD='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIKI_DIR="$SCRIPT_DIR/docs/wiki"
TMP_WIKI="/tmp/mpc_sample_database_wiki_clone"

echo -e "${CYAN}${BOLD}📚 Sincronizador de Wiki Oficial GitHub (Astro1Deep/mpc-sample-database)${NC}\n"

# Obtener credenciales de git si están guardadas en el sistema
GH_TOKEN=$(gh auth token 2>/dev/null || true)
TOKEN=$(printf "protocol=https\nhost=github.com\n" | git credential fill 2>/dev/null | grep "^password=" | cut -d'=' -f2 || true)
if [ -n "$GH_TOKEN" ]; then
    WIKI_REMOTE="https://x-access-token:${GH_TOKEN}@github.com/Astro1Deep/mpc-sample-database.wiki.git"
elif [ -n "$TOKEN" ]; then
    WIKI_REMOTE="https://Astro1Deep:${TOKEN}@github.com/Astro1Deep/mpc-sample-database.wiki.git"
else
    WIKI_REMOTE="https://github.com/Astro1Deep/mpc-sample-database.wiki.git"
fi

rm -rf "$TMP_WIKI"

echo -e "${GOLD}Comprobando estado del repositorio Wiki en GitHub...${NC}"
if git clone "$WIKI_REMOTE" "$TMP_WIKI" 2>/dev/null; then
    echo -e "${GREEN}✔ Repositorio Wiki conectado con éxito.${NC}"
    echo "Copiando páginas de documentación desde docs/wiki/..."
    cp -r "$WIKI_DIR"/* "$TMP_WIKI"/
    
    cd "$TMP_WIKI"
    git add -A
    if git diff --staged --quiet; then
        echo -e "${GREEN}✔ La Wiki de GitHub ya está al día. Sin cambios pendientes.${NC}"
    else
        git commit --no-gpg-sign -m "docs(wiki): update complete documentation, taxonomy and architecture guides"
        git push origin master
        echo -e "\n${GREEN}${BOLD}🎉 ¡Wiki de GitHub actualizada y publicada con éxito!${NC}"
        echo -e "Visítala en: ${CYAN}https://github.com/Astro1Deep/mpc-sample-database/wiki${NC}"
    fi
    rm -rf "$TMP_WIKI"
else
    echo -e "\n${GOLD}⚠️ El repositorio Git de la Wiki no ha sido inicializado en GitHub aún.${NC}"
    echo -e "En GitHub, las Wikis requieren activar la primera página una sola vez:"
    echo -e "  1. Entra en: ${CYAN}https://github.com/Astro1Deep/mpc-sample-database/wiki/_new${NC}"
    echo -e "  2. Haz clic en el botón verde ${BOLD}'Save page'${NC} (creará Home automáticamente)."
    echo -e "  3. Vuelve a ejecutar este script: ${BOLD}./sync_wiki.sh${NC}"
    echo -e "\n${GREEN}Todos los archivos de la Wiki ya están preparados y listos en:${NC} docs/wiki/"
fi
