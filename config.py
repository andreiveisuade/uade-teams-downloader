"""Configuracion centralizada del pipeline UADE Teams Downloader.

Auto-detecta el entorno (SO, backends disponibles, carpetas).
Override con variables de entorno o archivo .env.
"""

import os
from pathlib import Path

# Cargar .env si existe
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# --- Paths ---

BASE_DIR = Path(os.getenv(
    "UADE_BASE_DIR",
    str(Path.home() / "UADE" / "4to cuatrimestre"),
))

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "data" / "downloads.db"

# --- Teams ---

_default_teams = "568898,561218,558193,562914"
TEAM_PREFIXES = [t.strip() for t in os.getenv("TEAM_PREFIXES", _default_teams).split(",") if t.strip()]

# --- Whisper ---

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
LANGUAGE = os.getenv("LANGUAGE", "es")

# --- Estructura de carpetas ---

FOLDERS = {
    "material":  os.getenv("FOLDER_MATERIAL",  "01_Material_de_Clase"),
    "apuntes":   os.getenv("FOLDER_APUNTES",   "02_Apuntes_Personales"),
    "tp":        os.getenv("FOLDER_TP",         "03_Trabajos_Practicos"),
    "eval":      os.getenv("FOLDER_EVAL",       "04_Evaluaciones"),
    "grabacion": os.getenv("FOLDER_GRABACION",  "05_Grabaciones"),
    "extra":     os.getenv("FOLDER_EXTRA",       "06_Material_Extra"),
}


def ensure_folder_structure(materia_dir: Path):
    """Crea la estructura de carpetas si no existe."""
    for folder in FOLDERS.values():
        (materia_dir / folder).mkdir(parents=True, exist_ok=True)
