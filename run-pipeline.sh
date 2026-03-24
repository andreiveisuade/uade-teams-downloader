#!/usr/bin/env bash
# Pipeline completo: download → organize → transcribe+resumir
# Llamado por launchd en los horarios programados.
# Usa caffeinate para que la Mac no duerma durante la ejecución.

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

LOGFILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"

notify() {
    osascript -e "display notification \"$1\" with title \"UADE Pipeline\"" 2>/dev/null || true
}

# caffeinate -i: previene idle sleep mientras el pipeline corra
# -w $$: se libera automáticamente cuando este script termina
caffeinate -i -w $$ &
CAFF_PID=$!

{
    echo "=== UADE Pipeline — $(date) ==="
    echo "caffeinate PID: $CAFF_PID (sleep bloqueado)"
    cd "$PROJECT_DIR"
    source .venv/bin/activate

    # Paso 1: Descargar
    echo ""
    echo ">>> PASO 1: Descarga"
    python3 downloader.py 2>&1
    DL_EXIT=$?

    if [ $DL_EXIT -ne 0 ]; then
        echo "!!! Downloader falló (exit $DL_EXIT)"
        if [ $DL_EXIT -eq 2 ]; then
            notify "Sesión expirada. Corré: ~/projects/uade-teams-downloader/uade-login.sh"
        else
            notify "Error en descarga (exit $DL_EXIT). Ver logs."
        fi
        echo ">>> Continuando con organize + transcribe sobre material existente..."
    fi

    # Paso 2: Organizar
    echo ""
    echo ">>> PASO 2: Organización"
    python3 organizer.py 2>&1

    # Paso 3: Transcribir + Resumir
    # Verificar que claude está disponible para resúmenes
    echo ""
    echo ">>> PASO 3: Transcripción + Resúmenes"
    if command -v claude &>/dev/null; then
        python3 transcriber.py 2>&1
    else
        echo "claude CLI no disponible, transcribiendo sin resúmenes"
        python3 transcriber.py --no-summary 2>&1
    fi

    # Paso 4: Status
    echo ""
    echo ">>> STATUS"
    python3 status.py 2>&1

    echo ""
    echo "=== Pipeline completado — $(date) ==="
} >> "$LOGFILE" 2>&1

# caffeinate se mata automáticamente (-w $$), pero por si acaso
kill "$CAFF_PID" 2>/dev/null || true

# Limpiar logs viejos (más de 30 días)
find "$LOG_DIR" -name '*.log' -mtime +30 -delete 2>/dev/null || true
