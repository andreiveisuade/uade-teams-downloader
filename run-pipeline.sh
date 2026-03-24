#!/usr/bin/env bash
# Pipeline completo: download → organize → transcribe+resumir
# Llamado por launchd en los horarios programados.

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

LOGFILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"

notify() {
    osascript -e "display notification \"$1\" with title \"UADE Pipeline\"" 2>/dev/null || true
}

{
    echo "=== UADE Pipeline — $(date) ==="
    cd "$PROJECT_DIR"
    source .venv/bin/activate

    # Paso 1: Descargar
    echo ""
    echo ">>> PASO 1: Descarga"
    python3 downloader.py 2>&1
    DL_EXIT=$?

    if [ $DL_EXIT -ne 0 ]; then
        echo "!!! Downloader falló (exit $DL_EXIT)"
        # Exit code 2 = auth expirada
        if [ $DL_EXIT -eq 2 ]; then
            notify "Sesión de Teams expirada. Corré: uade-login"
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
    echo ""
    echo ">>> PASO 3: Transcripción + Resúmenes"
    python3 transcriber.py 2>&1

    echo ""
    echo "=== Pipeline completado — $(date) ==="
} >> "$LOGFILE" 2>&1

# Limpiar logs viejos (más de 30 días)
find "$LOG_DIR" -name '*.log' -mtime +30 -delete 2>/dev/null || true
