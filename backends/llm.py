"""Backend de LLM para generacion de resumenes.

Auto-detecta claude-cli, gemini o ollama.
"""

import os
import shutil
import subprocess

_provider = None


def detect() -> str:
    """Detecta el LLM disponible."""
    global _provider
    if _provider:
        return _provider

    forced = os.getenv("LLM_PROVIDER")
    if forced:
        _provider = forced
        return forced

    if shutil.which("claude"):
        _provider = "claude-cli"
        return "claude-cli"

    if os.getenv("GEMINI_API_KEY"):
        _provider = "gemini"
        return "gemini"

    if shutil.which("ollama"):
        _provider = "ollama"
        return "ollama"

    _provider = "none"
    return "none"


def is_available() -> bool:
    return detect() != "none"


def complete(prompt: str, model: str = "") -> str:
    """Enviar prompt a un LLM."""
    provider = detect()

    if provider == "none":
        raise RuntimeError(
            "No hay LLM configurado. Opciones:\n"
            "  1. Instalar Claude Code: https://claude.ai/code\n"
            "  2. Setear GEMINI_API_KEY: https://aistudio.google.com\n"
            "  3. Instalar Ollama: https://ollama.ai"
        )

    if provider == "claude-cli":
        model = model or os.getenv("LLM_MODEL", "sonnet")
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", model],
                input=prompt, capture_output=True, text=True, timeout=900,
            )
            if result.returncode != 0:
                raise RuntimeError(f"claude CLI fallo: {result.stderr.strip()}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            if model != "haiku":
                result = subprocess.run(
                    ["claude", "-p", "--model", "haiku"],
                    input=prompt, capture_output=True, text=True, timeout=900,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"claude CLI fallo (haiku retry): {result.stderr.strip()}")
                return result.stdout.strip()
            raise

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


def complete_fast(prompt: str) -> str:
    """LLM rapido para tareas de clasificacion."""
    provider = detect()
    if provider == "claude-cli":
        return complete(prompt, model="haiku")
    elif provider == "gemini":
        return complete(prompt, model="gemini-2.0-flash")
    elif provider == "ollama":
        return complete(prompt, model="llama3")
    return complete(prompt)
