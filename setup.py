#!/usr/bin/env python3
"""Setup interactivo para UADE Teams Downloader.

Guia al usuario paso a paso para configurar el sistema.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent


def print_header():
    print()
    print("=" * 55)
    print("  UADE Teams Downloader — Setup")
    print("=" * 55)
    print()


def ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"  {question}{suffix}: ").strip()
    return answer or default


def ask_yn(question: str, default: bool = True) -> bool:
    suffix = " [S/n]" if default else " [s/N]"
    answer = input(f"  {question}{suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in ("s", "si", "y", "yes")


def step(num: int, total: int, title: str):
    print()
    print(f"  [{num}/{total}] {title}")
    print(f"  {'─' * 45}")


def ok(msg: str):
    print(f"  ✓ {msg}")


def warn(msg: str):
    print(f"  ! {msg}")


def err(msg: str):
    print(f"  ✗ {msg}")


def main():
    print_header()

    so = platform.system()
    arch = platform.machine()
    print(f"  Sistema: {so} ({arch})")
    print(f"  Python:  {sys.version.split()[0]}")
    print()

    total_steps = 5
    env_lines = []

    # --- Paso 1: Carpeta destino ---
    step(1, total_steps, "Carpeta destino")
    default_dir = str(Path.home() / "UADE" / "4to cuatrimestre")
    base_dir = ask("Carpeta donde estan tus materias", default_dir)
    base_path = Path(base_dir)

    if not base_path.exists():
        if ask_yn(f"  La carpeta no existe. Crearla?"):
            base_path.mkdir(parents=True, exist_ok=True)
            ok(f"Creada: {base_path}")
        else:
            err("Necesitas una carpeta destino. Creala y volve a correr setup.")
            return

    if str(base_path) != default_dir:
        env_lines.append(f"UADE_BASE_DIR={base_path}")
    ok(f"Destino: {base_path}")

    # --- Paso 2: Entorno virtual + dependencias ---
    step(2, total_steps, "Dependencias")

    venv_path = PROJECT_DIR / ".venv"
    if not venv_path.exists():
        print("  Creando entorno virtual...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
        ok("Entorno virtual creado")

    if so == "Windows":
        pip = str(venv_path / "Scripts" / "pip")
        python = str(venv_path / "Scripts" / "python")
    else:
        pip = str(venv_path / "bin" / "pip")
        python = str(venv_path / "bin" / "python")

    print("  Instalando dependencias base...")
    subprocess.run([pip, "install", "-q", "-r", str(PROJECT_DIR / "requirements.txt")],
                   check=True, capture_output=True)
    ok("Dependencias base instaladas")

    # Whisper
    if so == "Darwin" and arch == "arm64":
        print("  Detectado macOS Apple Silicon — instalando mlx-whisper...")
        subprocess.run([pip, "install", "-q", "-r", str(PROJECT_DIR / "requirements-mlx.txt")],
                       check=True, capture_output=True)
        ok("mlx-whisper instalado (GPU Metal)")
    else:
        print("  Instalando OpenAI Whisper (puede tardar unos minutos)...")
        subprocess.run([pip, "install", "-q", "-r", str(PROJECT_DIR / "requirements-whisper.txt")],
                       check=True, capture_output=True)
        ok("OpenAI Whisper instalado")

    # Playwright
    print("  Instalando browser Chromium (para descarga de Teams)...")
    subprocess.run([python, "-m", "playwright", "install", "chromium"],
                   check=True, capture_output=True)
    ok("Chromium instalado")

    # --- Paso 3: LLM para resumenes ---
    step(3, total_steps, "LLM para resumenes")

    has_claude = shutil.which("claude") is not None
    has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))

    if has_claude:
        ok("Claude Code detectado. Se usara para resumenes.")
    elif has_gemini_key:
        ok("GEMINI_API_KEY detectada. Se usara Gemini.")
    else:
        print()
        print("  No se detecto ningun LLM. Sin LLM, el sistema descarga")
        print("  y transcribe pero NO genera resumenes ni extrae tareas.")
        print()
        print("  Opciones:")
        print("    1. Google Gemini (gratis) — necesitas una API key")
        print("    2. Claude Code (suscripcion) — instalar desde claude.ai/code")
        print("    3. Ollama (gratis, local) — instalar desde ollama.ai")
        print("    4. Continuar sin LLM (solo transcripcion)")
        print()

        choice = ask("Elegir opcion (1-4)", "1")

        if choice == "1":
            print()
            print("  Para obtener tu API key gratis:")
            print("    1. Ir a https://aistudio.google.com")
            print("    2. Loguearte con tu cuenta de Google")
            print("    3. Click en 'Get API Key' → 'Create API Key'")
            print("    4. Copiar la key y pegarla aca")
            print()
            api_key = ask("GEMINI_API_KEY")
            if api_key:
                env_lines.append(f"GEMINI_API_KEY={api_key}")
                subprocess.run([pip, "install", "-q", "-r",
                                str(PROJECT_DIR / "requirements-gemini.txt")],
                               check=True, capture_output=True)
                ok("Gemini configurado")
            else:
                warn("Sin API key. Continuando sin resumenes.")
        elif choice == "2":
            print("  Instalar Claude Code desde: https://claude.ai/code")
            print("  Despues de instalarlo, volve a correr este setup.")
            warn("Continuando sin LLM por ahora.")
        elif choice == "3":
            print("  Instalar Ollama desde: https://ollama.ai")
            print("  Despues: ollama pull llama3")
            warn("Continuando sin LLM por ahora.")
        else:
            warn("Sin LLM. Solo se hara descarga + transcripcion.")

    # --- Paso 4: Configurar Teams ---
    step(4, total_steps, "Configurar Teams")
    print("  Necesitas los IDs de tus equipos de Teams.")
    print("  Los encontras en la URL de cada equipo en Teams web.")
    print()

    if ask_yn("Queres configurar los Team IDs ahora?", False):
        print("  Ingresa los IDs separados por coma (ej: 568898,561218,558193)")
        ids = ask("Team IDs", "")
        if ids:
            ok(f"Teams configurados: {ids}")
            print(f"\n  NOTA: Editar TEAM_PREFIXES en downloader.py con estos IDs.")
    else:
        print("  OK. Editar TEAM_PREFIXES en downloader.py cuando los tengas.")

    # --- Paso 5: Login en Teams ---
    step(5, total_steps, "Login en Teams")
    print("  Para descargar material, necesitas loguearte en Teams")
    print("  una vez. Se abre un browser, te logueas, y la sesion")
    print("  se guarda por ~30 dias.")
    print()

    if ask_yn("Queres loguearte ahora?", False):
        print("  Abriendo browser... Logueate en Teams y espera.")
        subprocess.run([python, str(PROJECT_DIR / "downloader.py"), "--visible"])
    else:
        if so == "Windows":
            print(f"  Para loguearte despues: python downloader.py --visible")
        else:
            print(f"  Para loguearte despues: ./uade-login.sh")

    # --- Guardar .env ---
    if env_lines:
        env_path = PROJECT_DIR / ".env"
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        ok(f"Configuracion guardada en .env")

    # --- Fin ---
    print()
    print("=" * 55)
    print("  Setup completado!")
    print("=" * 55)
    print()
    if so == "Windows":
        print("  Para correr el pipeline: run-pipeline.bat")
    else:
        print("  Para correr el pipeline: ./run-pipeline.sh")
    print()
    print("  El pipeline descarga, organiza, transcribe y genera")
    print("  resumenes automaticamente.")
    print()


if __name__ == "__main__":
    main()
