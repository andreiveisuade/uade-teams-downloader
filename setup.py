#!/usr/bin/env python3
"""Setup interactivo para UADE Teams Downloader.

Guia al usuario paso a paso para configurar el sistema.
Correr con: python setup.py
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
SO = platform.system()
ARCH = platform.machine()


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
    print(f"\n  [{num}/{total}] {title}")
    print(f"  {'─' * 45}")


def ok(msg: str):
    print(f"  + {msg}")


def warn(msg: str):
    print(f"  ! {msg}")


def err(msg: str):
    print(f"  X {msg}")


def pip_cmd():
    venv = PROJECT_DIR / ".venv"
    if SO == "Windows":
        return str(venv / "Scripts" / "pip")
    return str(venv / "bin" / "pip")


def python_cmd():
    venv = PROJECT_DIR / ".venv"
    if SO == "Windows":
        return str(venv / "Scripts" / "python")
    return str(venv / "bin" / "python")


def run_quiet(cmd, **kwargs):
    """Corre un comando suprimiendo output. Muestra error si falla."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)
        return True
    except subprocess.CalledProcessError as e:
        err(f"Fallo: {' '.join(str(c) for c in cmd)}")
        if e.stderr:
            for line in e.stderr.strip().split("\n")[:5]:
                print(f"    {line}")
        return False


def main():
    print()
    print("=" * 55)
    print("  UADE Teams Downloader — Setup")
    print("=" * 55)
    print(f"\n  Sistema: {SO} ({ARCH})")
    print(f"  Python:  {sys.version.split()[0]}")

    if sys.version_info < (3, 10):
        err("Se requiere Python 3.10 o superior.")
        print("  Descargar desde: https://www.python.org/downloads/")
        return

    total = 5
    env_lines = []

    # ── Paso 1: Carpeta destino ──────────────────────────
    step(1, total, "Carpeta destino")
    print("  Aca se van a guardar los archivos descargados de Teams,")
    print("  organizados por materia.")
    print()
    default_dir = str(Path.home() / "UADE" / "4to cuatrimestre")
    base_dir = ask("Carpeta destino", default_dir)
    base_path = Path(base_dir)

    if not base_path.exists():
        base_path.mkdir(parents=True, exist_ok=True)
        ok(f"Carpeta creada: {base_path}")
    else:
        ok(f"Carpeta: {base_path}")

    if str(base_path) != default_dir:
        env_lines.append(f"UADE_BASE_DIR={base_path}")

    # ── Paso 2: Dependencias ─────────────────────────────
    step(2, total, "Instalando dependencias")

    # Entorno virtual
    venv_path = PROJECT_DIR / ".venv"
    if not venv_path.exists():
        print("  Creando entorno virtual...")
        if not run_quiet([sys.executable, "-m", "venv", str(venv_path)]):
            err("No se pudo crear el entorno virtual.")
            return
        ok("Entorno virtual creado")
    else:
        ok("Entorno virtual ya existe")

    # Dependencias base
    print("  Instalando dependencias base...")
    if not run_quiet([pip_cmd(), "install", "-q", "-r",
                      str(PROJECT_DIR / "requirements.txt")]):
        return

    # Whisper segun SO
    if SO == "Darwin" and ARCH == "arm64":
        print("  macOS Apple Silicon detectado. Instalando mlx-whisper (GPU Metal)...")
        req_file = "requirements-mlx.txt"
    else:
        print("  Instalando OpenAI Whisper (esto puede tardar unos minutos)...")
        req_file = "requirements-whisper.txt"

    if not run_quiet([pip_cmd(), "install", "-q", "-r",
                      str(PROJECT_DIR / req_file)]):
        warn("Whisper no se instalo. La transcripcion no va a funcionar.")
    else:
        ok("Whisper instalado")

    # Playwright + Chromium
    print("  Instalando browser para descarga de Teams...")
    if not run_quiet([python_cmd(), "-m", "playwright", "install", "chromium"]):
        warn("Chromium no se instalo. La descarga de Teams no va a funcionar.")
    else:
        ok("Chromium instalado")

    # ── Paso 3: LLM para resumenes ───────────────────────
    step(3, total, "Configurar IA para resumenes")
    print("  El sistema necesita un modelo de lenguaje (LLM) para")
    print("  generar resumenes y extraer tareas de las grabaciones.")
    print("  Sin LLM, solo descarga y transcribe (sin resumenes).")
    print()

    # Detectar lo que ya hay
    has_claude = shutil.which("claude") is not None
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))

    if has_claude:
        ok("Claude Code detectado. Se va a usar automaticamente.")
    elif has_gemini:
        ok("GEMINI_API_KEY detectada. Se va a usar Gemini.")
    else:
        print("  Opciones disponibles:")
        print()
        print("    1. Google Gemini (RECOMENDADO — gratis)")
        print("       Necesitas una API key de Google AI Studio.")
        print()
        print("    2. Claude Code (requiere suscripcion)")
        print("       Si ya lo tenes instalado, el sistema lo detecta solo.")
        print()
        print("    3. Ollama (gratis, corre local)")
        print("       Necesitas instalarlo y descargar un modelo.")
        print()
        print("    4. Sin LLM (solo descarga + transcripcion)")
        print()

        choice = ask("Que opcion elegis? (1-4)", "1")

        if choice == "1":
            print()
            print("  Como obtener la API key (gratis):")
            print("  ─────────────────────────────────")
            print("  1. Abrir https://aistudio.google.com")
            print("  2. Iniciar sesion con tu cuenta de Google")
            print("  3. En el menu lateral: 'Get API Key'")
            print("  4. Click en 'Create API Key in new project'")
            print("  5. Copiar la key que aparece")
            print()
            api_key = ask("Pegar la API key aca")
            if api_key and len(api_key) > 10:
                env_lines.append(f"GEMINI_API_KEY={api_key}")
                run_quiet([pip_cmd(), "install", "-q", "-r",
                           str(PROJECT_DIR / "requirements-gemini.txt")])
                ok("Gemini configurado")
            else:
                warn("API key invalida o vacia. Continuando sin resumenes.")
                warn("Podes configurarlo despues editando el archivo .env")
        elif choice == "3":
            print("  1. Descargar Ollama desde https://ollama.ai")
            print("  2. Instalar y abrir")
            print("  3. En la terminal: ollama pull llama3")
            print("  4. Correr este setup de nuevo")
            warn("Continuando sin LLM por ahora.")
        elif choice == "2":
            print("  Descargar Claude Code desde https://claude.ai/code")
            warn("Continuando sin LLM por ahora.")
        else:
            warn("Sin LLM. Solo se va a descargar y transcribir.")

    # ── Paso 4: Teams ────────────────────────────────────
    step(4, total, "Configurar equipos de Teams")
    print("  Para descargar material, el sistema necesita saber")
    print("  cuales son tus equipos (materias) en Teams.")
    print()
    print("  Como encontrar los IDs de tus equipos:")
    print("  ───────────────────────────────────────")
    print("  1. Abrir Teams en el browser (teams.microsoft.com)")
    print("  2. Entrar a un equipo/materia")
    print("  3. En la URL vas a ver algo como:")
    print("     ...teams.microsoft.com/.../Section_568898/...")
    print("                                    ^^^^^^")
    print("     Ese numero (568898) es el ID del equipo.")
    print("  4. Repetir para cada materia.")
    print()

    if ask_yn("Tenes los IDs de tus equipos?", False):
        ids_input = ask("IDs separados por coma (ej: 568898,561218)")
        if ids_input:
            ids = [i.strip() for i in ids_input.split(",") if i.strip()]
            if ids:
                env_lines.append(f"TEAM_PREFIXES={','.join(ids)}")
                ok(f"Equipos configurados: {', '.join(ids)}")
    else:
        print("  No hay problema. Cuando los tengas, agregarlos al archivo .env:")
        print(f"  TEAM_PREFIXES=id1,id2,id3")

    # ── Paso 5: Login en Teams ───────────────────────────
    step(5, total, "Login en Teams")
    print("  El sistema necesita loguearse en Teams una vez para")
    print("  poder descargar archivos. Se abre un browser, te")
    print("  logueas con tu cuenta de UADE, y la sesion queda")
    print("  guardada por aproximadamente 30 dias.")
    print()

    if ask_yn("Loguearte en Teams ahora?", False):
        print()
        print("  Abriendo browser...")
        print("  → Logueate en Teams con tu cuenta de UADE")
        print("  → Cuando veas el panel de Teams, volve aca")
        print()
        subprocess.run([python_cmd(), str(PROJECT_DIR / "downloader.py"), "--visible"])
        ok("Sesion guardada")
    else:
        print("  Para loguearte despues:")
        if SO == "Windows":
            print("    python downloader.py --visible")
        else:
            print("    ./uade-login.sh")

    # ── Guardar .env ─────────────────────────────────────
    if env_lines:
        env_path = PROJECT_DIR / ".env"
        existing = ""
        if env_path.exists():
            existing = env_path.read_text(encoding="utf-8")
        with open(env_path, "a", encoding="utf-8") as f:
            for line in env_lines:
                key = line.split("=")[0]
                if key not in existing:
                    f.write(line + "\n")
        ok("Configuracion guardada en .env")

    # ── Fin ──────────────────────────────────────────────
    print()
    print("=" * 55)
    print("  Setup completado!")
    print("=" * 55)
    print()
    print("  Proximos pasos:")
    print("  ────────────────")
    if SO == "Windows":
        print("  1. Activar el entorno:  .venv\\Scripts\\activate.bat")
        print("  2. Correr el pipeline:  run-pipeline.bat")
    else:
        print("  1. Activar el entorno:  source .venv/bin/activate")
        print("  2. Correr el pipeline:  ./run-pipeline.sh")
    print()
    print("  El pipeline descarga material de Teams, lo organiza en")
    print("  carpetas, transcribe las grabaciones, y genera resumenes")
    print("  con tareas extraidas automaticamente.")
    print()
    print("  Para ver el estado:     python status.py")
    print("  Para ver grabaciones:   python status.py --mp4")
    print()


if __name__ == "__main__":
    main()
