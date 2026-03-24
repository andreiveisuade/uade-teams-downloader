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
info() { echo -e "  ${DIM}$1${RESET}"; }

# Corre un comando, muestra spinner si interactivo, output va al log
# Uso: run_step "label" comando args...
run_step() {
    local label="$1"
    shift

    if $INTERACTIVE; then
        # Mostrar spinner mientras corre, output al log
        "$@" >> "$LOGFILE" 2>&1 &
        local pid=$!
        local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        local i=0
        while kill -0 "$pid" 2>/dev/null; do
            printf "\r  ${DIM}${spin:i++%${#spin}:1} ${label}...${RESET}  "
            sleep 0.1
        done
        wait "$pid"
        local exit_code=$?
        printf "\r%-60s\r" ""  # limpiar línea del spinner
        return $exit_code
    else
        "$@" >> "$LOGFILE" 2>&1
        return $?
    fi
}

notify() {
    osascript -e "display notification \"$1\" with title \"UADE Pipeline\"" 2>/dev/null || true
}

# --- Main ---

caffeinate -i -w $$ &
CAFF_PID=$!

run_pipeline() {
    header "UADE Pipeline — $(date '+%d/%m %H:%M')"
    info "Log: ${LOGFILE}"
    info "Sleep bloqueado (caffeinate)"

    cd "$PROJECT_DIR"
    source .venv/bin/activate

    local start_time=$SECONDS

    # Paso 1: Descargar
    step 1 4 "Descarga de Teams"
    run_step "Descargando de SharePoint" python3 -u downloader.py
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
    run_step "Organizando archivos" python3 -u organizer.py
    ok "Organización completada"

    # Paso 3: Transcribir + Resumir
    step 3 4 "Transcripción + Resúmenes"
    if command -v claude &>/dev/null; then
        run_step "Transcribiendo y generando resúmenes" python3 -u transcriber.py
    else
        warn "claude CLI no disponible, sin resúmenes"
        run_step "Transcribiendo (sin resúmenes)" python3 -u transcriber.py --no-summary
    fi
    ok "Transcripción completada"

    # Paso 4: Status
    step 4 4 "Estado del pipeline"
    echo ""
    python3 -u status.py 2>&1 | tee -a "$LOGFILE"

    local elapsed=$(( SECONDS - start_time ))
    local mins=$(( elapsed / 60 ))
    local secs=$(( elapsed % 60 ))
    header "Pipeline completado — ${mins}m ${secs}s"
}

run_pipeline
kill "$CAFF_PID" 2>/dev/null || true
find "$LOG_DIR" -name '*.log' -mtime +30 -delete 2>/dev/null || true
