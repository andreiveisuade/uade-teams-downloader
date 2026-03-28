"""Configuracion centralizada del pipeline UADE Teams Downloader.

Auto-detecta el entorno (SO, backends disponibles, carpetas).
Override con variables de entorno o archivo .env.
"""

import os
import platform
import shutil
from pathlib import Path

# Cargar .env si existe (no falla si no esta)
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


# --- Whisper backend ---

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
LANGUAGE = os.getenv("LANGUAGE", "es")

_whisper_backend = None


def detect_whisper_backend() -> str:
    global _whisper_backend
    if _whisper_backend:
        return _whisper_backend

    forced = os.getenv("WHISPER_BACKEND")
    if forced:
        _whisper_backend = forced
        return forced

    # Auto-detectar: mlx en macOS ARM, openai-whisper en el resto
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401
            _whisper_backend = "mlx"
            return "mlx"
        except ImportError:
            pass

    try:
        import whisper  # noqa: F401
        _whisper_backend = "openai-whisper"
        return "openai-whisper"
    except ImportError:
        pass

    raise RuntimeError(
        "No se encontro ningun backend de Whisper.\n"
        "  macOS Apple Silicon: pip install mlx-whisper\n"
        "  Windows/Linux:       pip install openai-whisper"
    )


def transcribe_audio(mp4_path: str, model: str = "", language: str = "") -> str:
    """Transcribe un archivo de audio. Auto-detecta el backend."""
    model = model or WHISPER_MODEL
    language = language or LANGUAGE
    backend = detect_whisper_backend()

    if backend == "mlx":
        import mlx_whisper
        result = mlx_whisper.transcribe(
            mp4_path,
            path_or_hf_repo=f"mlx-community/whisper-{model}",
            language=language,
            verbose=False,
        )
        return result["text"]

    elif backend == "openai-whisper":
        import whisper
        whisper_model = whisper.load_model(model)
        result = whisper_model.transcribe(mp4_path, language=language, verbose=False, fp16=False)
        return result["text"]

    raise RuntimeError(f"Backend de whisper desconocido: {backend}")


# --- LLM provider ---

_llm_provider = None


def detect_llm_provider() -> str:
    global _llm_provider
    if _llm_provider:
        return _llm_provider

    forced = os.getenv("LLM_PROVIDER")
    if forced:
        _llm_provider = forced
        return forced

    # Auto-detectar
    if shutil.which("claude"):
        _llm_provider = "claude-cli"
        return "claude-cli"

    if os.getenv("GEMINI_API_KEY"):
        _llm_provider = "gemini"
        return "gemini"

    if shutil.which("ollama"):
        _llm_provider = "ollama"
        return "ollama"

    _llm_provider = "none"
    return "none"


def has_llm() -> bool:
    """Retorna True si hay algun LLM disponible."""
    return detect_llm_provider() != "none"


def llm_complete(prompt: str, model: str = "") -> str:
    """Enviar prompt a un LLM. Auto-detecta el provider."""
    import subprocess
    provider = detect_llm_provider()

    if provider == "none":
        raise RuntimeError(
            "No hay LLM configurado. Opciones:\n"
            "  1. Instalar Claude Code: https://claude.ai/code\n"
            "  2. Setear GEMINI_API_KEY: https://aistudio.google.com\n"
            "  3. Instalar Ollama: https://ollama.ai"
        )

    if provider == "claude-cli":
        model = model or os.getenv("LLM_MODEL", "sonnet")
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt, capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI fallo: {result.stderr.strip()}")
        return result.stdout.strip()

    elif provider == "gemini":
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY no seteada")
        genai.configure(api_key=api_key)
        model_name = model or os.getenv("LLM_MODEL", "gemini-2.0-flash")
        gmodel = genai.GenerativeModel(model_name)
        response = gmodel.generate_content(prompt)
        if not response.text:
            raise RuntimeError("Gemini retorno respuesta vacia o bloqueada")
        return response.text.strip()

    elif provider == "ollama":
        model = model or os.getenv("LLM_MODEL", "llama3")
        result = subprocess.run(
            ["ollama", "run", model],
            input=prompt, capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ollama fallo: {result.stderr.strip()}")
        return result.stdout.strip()

    raise RuntimeError(f"LLM provider desconocido: {provider}")


def llm_complete_fast(prompt: str) -> str:
    """LLM rapido para clasificacion (haiku/flash)."""
    provider = detect_llm_provider()
    if provider == "claude-cli":
        return llm_complete(prompt, model="haiku")
    elif provider == "gemini":
        return llm_complete(prompt, model="gemini-2.0-flash")
    elif provider == "ollama":
        return llm_complete(prompt, model="llama3")
    return llm_complete(prompt)
