"""Backend de transcripcion con Whisper.

Auto-detecta mlx-whisper (macOS Apple Silicon) u openai-whisper (cross-platform).
"""

import os
import platform

import config
from logger import log

_backend = None
_model_loaded = False


def detect() -> str:
    """Detecta el backend de Whisper disponible."""
    global _backend
    if _backend:
        return _backend

    forced = os.getenv("WHISPER_BACKEND")
    if forced:
        _backend = forced
        return forced

    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401
            _backend = "mlx"
            return "mlx"
        except ImportError:
            pass

    try:
        import whisper  # noqa: F401
        _backend = "openai-whisper"
        return "openai-whisper"
    except ImportError:
        pass

    raise RuntimeError(
        "No se encontro ningun backend de Whisper.\n"
        "  macOS Apple Silicon: pip install mlx-whisper\n"
        "  Windows/Linux:       pip install openai-whisper"
    )


def transcribe(mp4_path: str, model: str = "", language: str = "") -> str:
    """Transcribe un archivo de audio."""
    model = model or config.WHISPER_MODEL
    language = language or config.LANGUAGE
    backend = detect()

    global _model_loaded

    if backend == "mlx":
        import mlx_whisper
        if not _model_loaded:
            log(f"  Cargando modelo Whisper '{model}' (la primera vez descarga ~1.5 GB, puede tardar)...")
            _model_loaded = True
        result = mlx_whisper.transcribe(
            mp4_path,
            path_or_hf_repo=f"mlx-community/whisper-{model}",
            language=language,
            verbose=False,
        )
        return result["text"]

    elif backend == "openai-whisper":
        import whisper
        if not _model_loaded:
            log(f"  Cargando modelo Whisper '{model}' (la primera vez descarga ~1.5 GB, puede tardar)...")
        whisper_model = whisper.load_model(model)
        _model_loaded = True
        result = whisper_model.transcribe(
            mp4_path, language=language, verbose=False, fp16=False,
        )
        return result["text"]

    raise RuntimeError(f"Backend de whisper desconocido: {backend}")
