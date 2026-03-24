#!/usr/bin/env bash
# Re-login de Teams para el pipeline UADE.
# Abre Chromium visible → logueate → cerrá el browser.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
echo "Abriendo browser para login de Teams..."
echo "Logueate y esperá a que detecte la sesión."
python3 downloader.py --visible
