"""Backend de transcripcion con Whisper.

Auto-detecta mlx-whisper (macOS Apple Silicon) u openai-whisper (cross-platform).
Pre-procesa audio con ffmpeg: extrae a WAV y divide en chunks para evitar
alucinaciones en archivos largos (comun con grabaciones de Teams).
"""

import glob as globmod
import os
import platform
import re
import shutil
import subprocess
import tempfile

import config
from logger import log

_backend = None
_model_loaded = False

CHUNK_MINUTES = 5


def _split_audio(mp4_path: str, chunk_minutes: int = CHUNK_MINUTES) -> list[str] | None:
    """Extrae audio y divide en chunks WAV. Retorna lista de paths o None."""
    if not shutil.which("ffmpeg"):
        return None
    tmpdir = tempfile.mkdtemp(prefix="whisper_")
    pattern = os.path.join(tmpdir, "chunk_%04d.wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp4_path, "-vn",
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
             "-f", "segment", "-segment_time", str(chunk_minutes * 60),
             pattern],
            capture_output=True, timeout=600,
        )
        chunks = sorted(globmod.glob(os.path.join(tmpdir, "chunk_*.wav")))
        if chunks and os.path.getsize(chunks[0]) > 1000:
            return chunks
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _cleanup_chunks(chunks: list[str]):
    """Limpia archivos temporales de chunks."""
    if not chunks:
        return
    tmpdir = os.path.dirname(chunks[0])
    for f in chunks:
        try:
            os.unlink(f)
        except OSError:
            pass
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass


def _clean_hallucinations(text: str) -> str:
    """Limpia secciones alucinadas de un texto transcripto.

    Detecta y remueve repeticiones excesivas que son artefactos de Whisper
    al procesar silencio o audio de baja calidad.
    """
    words = text.split()
    if len(words) < 10:
        return text

    # Buscar y eliminar secuencias repetitivas con ventana deslizante.
    # Para cada posición, probar frases de 1 a 12 palabras.
    # Si una frase se repite 3+ veces seguidas, mantener solo una.
    result = []
    i = 0
    while i < len(words):
        best_phrase_len = 0
        best_reps = 0
        # Probar longitudes de frase de 1 a 12
        for plen in range(1, min(13, (len(words) - i) // 2 + 1)):
            phrase = words[i:i+plen]
            reps = 1
            j = i + plen
            while j + plen <= len(words):
                candidate = words[j:j+plen]
                # Comparar ignorando puntuación al final
                match = all(
                    a.rstrip('.,;:!?') == b.rstrip('.,;:!?')
                    for a, b in zip(phrase, candidate)
                )
                if match:
                    reps += 1
                    j += plen
                else:
                    break
            if reps >= 3 and plen * reps > best_phrase_len * best_reps:
                best_phrase_len = plen
                best_reps = reps
        if best_phrase_len > 0 and best_reps >= 3:
            # Mantener solo una ocurrencia de la frase
            result.extend(words[i:i+best_phrase_len])
            i += best_phrase_len * best_reps
        else:
            result.append(words[i])
            i += 1

    return " ".join(result)


def _is_empty_after_cleaning(text: str) -> bool:
    """Verifica si un chunk queda vacío después de limpiar alucinaciones."""
    cleaned = _clean_hallucinations(text)
    words = cleaned.split()
    return len(words) < 5


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


def _transcribe_single(audio_path: str, model: str, language: str, backend: str) -> str:
    """Transcribe un solo archivo de audio."""
    global _model_loaded

    if backend == "mlx":
        import mlx_whisper
        if not _model_loaded:
            log(f"  Cargando modelo Whisper '{model}' (la primera vez descarga ~1.5 GB, puede tardar)...")
            _model_loaded = True
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=f"mlx-community/whisper-{model}",
            language=language,
            verbose=False,
            condition_on_previous_text=False,
        )
        return result["text"]

    elif backend == "openai-whisper":
        import whisper
        if not _model_loaded:
            log(f"  Cargando modelo Whisper '{model}' (la primera vez descarga ~1.5 GB, puede tardar)...")
        whisper_model = whisper.load_model(model)
        _model_loaded = True
        result = whisper_model.transcribe(
            audio_path, language=language, verbose=False, fp16=False,
            condition_on_previous_text=False,
        )
        return result["text"]

    raise RuntimeError(f"Backend de whisper desconocido: {backend}")


def _transcribe_chunked(mp4_path: str, model: str, language: str,
                        backend: str, chunk_minutes: int) -> str:
    """Transcribe con chunks del tamaño indicado. Retorna texto."""
    chunks = _split_audio(mp4_path, chunk_minutes)
    if not chunks:
        log(f"  ffmpeg no disponible, transcribiendo directo")
        return _transcribe_single(mp4_path, model, language, backend)

    log(f"  Audio dividido en {len(chunks)} segmentos de {chunk_minutes} min")

    try:
        parts = []
        skipped = 0
        cleaned_count = 0
        for i, chunk in enumerate(chunks):
            log(f"  Transcribiendo segmento {i+1}/{len(chunks)}...")
            text = _transcribe_single(chunk, model, language, backend)
            cleaned = _clean_hallucinations(text)
            if _is_empty_after_cleaning(text):
                log(f"  Segmento {i+1} descartado (silencio)")
                skipped += 1
                continue
            if len(cleaned) < len(text) * 0.9:
                cleaned_count += 1
            parts.append(cleaned)
        if skipped or cleaned_count:
            log(f"  {skipped} segmentos descartados, {cleaned_count} limpiados")
        return " ".join(parts)
    finally:
        _cleanup_chunks(chunks)


def transcribe(mp4_path: str, model: str = "", language: str = "") -> str:
    """Transcribe un archivo de audio con validación de calidad y retry automático.

    Estrategia:
    1. Intenta con chunks de 5 min
    2. Valida calidad del resultado
    3. Si falla, reintenta con chunks de 2 min (más granular, menos alucinación)
    4. Si sigue fallando, retorna lo mejor que tiene con un warning en el log
    """
    from tasks import validate_transcription

    model = model or config.WHISPER_MODEL
    language = language or config.LANGUAGE
    backend = detect()
    size_mb = os.path.getsize(mp4_path) / (1024 * 1024)

    # Videos chicos (<50MB, ~5 min) no necesitan chunking
    if size_mb < 50:
        text = _transcribe_chunked(mp4_path, model, language, backend, CHUNK_MINUTES)
        return text

    strategies = [
        (CHUNK_MINUTES, "chunks de 5 min"),
        (2, "chunks de 2 min (retry)"),
    ]

    best_text = ""
    for chunk_min, label in strategies:
        text = _transcribe_chunked(mp4_path, model, language, backend, chunk_min)
        ok, reason = validate_transcription(text, size_mb)
        if ok:
            return text
        log(f"  Validacion fallida ({label}): {reason}")
        # Quedarse con el intento que tenga más contenido útil
        if len(text) > len(best_text):
            best_text = text

    # Agotamos las estrategias — retornar lo mejor que tenemos
    log(f"  WARN: transcripcion de baja calidad despues de {len(strategies)} intentos")
    return best_text
