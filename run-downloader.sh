#!/usr/bin/env bash
# Wrapper para launchd — activa venv y corre el downloader con logging.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

LOGFILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"

{
    echo "=== UADE Downloader — $(date) ==="
    cd "$PROJECT_DIR"
    source .venv/bin/activate
    python3 downloader.py 2>&1
    echo "=== Fin — $(date) ==="
} >> "$LOGFILE" 2>&1

# Limpiar logs viejos (más de 30 días)
find "$LOG_DIR" -name '*.log' -mtime +30 -delete 2>/dev/null || true
