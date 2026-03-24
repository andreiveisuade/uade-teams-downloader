#!/usr/bin/env bash
# Pipeline completo: download → organize → transcribe+resumir
# Llamado por launchd o manualmente.
# Usa caffeinate para que la Mac no duerma durante la ejecución.

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

LOGFILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"

# --- Colores (solo si hay terminal) ---
if [ -t 1 ]; then
    BOLD='\033[1m'
    DIM='\033[2m'
    GREEN='\033[32m'
    YELLOW='\033[33m'
    RED='\033[31m'
    CYAN='\033[36m'
    RESET='\033[0m'
    INTERACTIVE=true
else
    BOLD='' DIM='' GREEN='' YELLOW='' RED='' CYAN='' RESET=''
    INTERACTIVE=false
fi

header() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${BOLD}  $1${RESET}"
    echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
}

step() {
    local num=$1 total=$2 label=$3
    echo ""
    echo -e "  ${BOLD}[${num}/${total}]${RESET} ${GREEN}${label}${RESET}"
    echo -e "  ${DIM}$(printf '%.0s─' {1..46})${RESET}"
}

ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}!${RESET} $1"; }
err()  { echo -e "  ${RED}✗${RESET} $1"; }

notify() {
    osascript -e "display notification \"$1\" with title \"UADE Pipeline\"" 2>/dev/null || true
}

# --- Main ---

caffeinate -i -w $$ &
CAFF_PID=$!

run_pipeline() {
    header "UADE Pipeline — $(date '+%d/%m %H:%M')"
    echo -e "  ${DIM}Log: ${LOGFILE}${RESET}"
    echo -e "  ${DIM}Sleep bloqueado (caffeinate PID: ${CAFF_PID})${RESET}"

    cd "$PROJECT_DIR"
    source .venv/bin/activate

    # Paso 1: Descargar
    step 1 4 "Descarga de Teams"
    python3 -u downloader.py 2>&1
    DL_EXIT=$?

    if [ $DL_EXIT -eq 0 ]; then
        ok "Descarga completada"
    elif [ $DL_EXIT -eq 2 ]; then
        err "Sesión expirada — corré: ./uade-login.sh"
        notify "Sesión expirada. Corré: ./uade-login.sh"
        warn "Continuando con material existente..."
    else
        err "Descarga falló (exit $DL_EXIT)"
        notify "Error en descarga (exit $DL_EXIT). Ver logs."
        warn "Continuando con material existente..."
    fi

    # Paso 2: Organizar
    step 2 4 "Organización de archivos"
    python3 -u organizer.py 2>&1
    ok "Organización completada"

    # Paso 3: Transcribir + Resumir
    step 3 4 "Transcripción + Resúmenes"
    if command -v claude &>/dev/null; then
        python3 -u transcriber.py 2>&1
    else
        warn "claude CLI no disponible, sin resúmenes"
        python3 -u transcriber.py --no-summary 2>&1
    fi
    ok "Transcripción completada"

    # Paso 4: Status
    step 4 4 "Estado del pipeline"
    python3 -u status.py 2>&1

    header "Pipeline completado — $(date '+%d/%m %H:%M')"
}

# Si hay terminal: mostrar en vivo + guardar en log
# Si no hay terminal (launchd): solo log
if $INTERACTIVE; then
    run_pipeline 2>&1 | tee "$LOGFILE"
else
    run_pipeline >> "$LOGFILE" 2>&1
fi

kill "$CAFF_PID" 2>/dev/null || true
find "$LOG_DIR" -name '*.log' -mtime +30 -delete 2>/dev/null || true
