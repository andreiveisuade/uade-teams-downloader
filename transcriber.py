#!/usr/bin/env python3
"""Transcribe UADE class recordings and generate summaries.

Finds .mp4 files in ~/UADE/4to cuatrimestre/*/05_Grabaciones/,
transcribes with mlx-whisper (local, Apple Silicon), and generates
summaries via Claude Code CLI. Summaries go to 02_Apuntes_Personales/.
"""

import argparse
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from pathlib import Path

import mlx_whisper

# --- Config ---

BASE_DIR = Path.home() / "UADE" / "4to cuatrimestre"
PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "data" / "downloads.db"
WHISPER_MODEL = "mlx-community/whisper-medium"


# --- DB ---


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            mp4_path    TEXT PRIMARY KEY,
            txt_path    TEXT NOT NULL,
            summary_path TEXT,
            transcribed_at TEXT NOT NULL,
            summarized_at TEXT
        )
    """)
    conn.commit()
    return conn


def is_transcribed(conn, mp4_path: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM transcriptions WHERE mp4_path=?", (mp4_path,)
    ).fetchone()
    return row is not None


def record_transcription(conn, mp4_path: str, txt_path: str,
                         summary_path: str | None = None):
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO transcriptions
           (mp4_path, txt_path, summary_path, transcribed_at, summarized_at)
           VALUES (?, ?, ?, ?, ?)""",
        (mp4_path, txt_path, summary_path, now, now if summary_path else None),
    )
    conn.commit()


# --- Helpers ---


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def find_mp4s() -> list[Path]:
    """Find .mp4 files in 05_Grabaciones/ that haven't been transcribed."""
    results = []
    for materia_dir in sorted(BASE_DIR.iterdir()):
        if not materia_dir.is_dir():
            continue
        grab_dir = materia_dir / "05_Grabaciones"
        if not grab_dir.exists():
            continue
        for mp4 in sorted(grab_dir.glob("*.mp4")):
            txt = mp4.with_suffix(".txt")
            if txt.exists():
                continue
            results.append(mp4)
    return results


def find_course_materials(materia_dir: Path) -> list[Path]:
    """Find PDFs and PPTXs in the materia directory."""
    materials = []
    for ext in ("*.pdf", "*.pptx", "*.ppt"):
        materials.extend(materia_dir.rglob(ext))
    return sorted(materials)


def transcribe(mp4_path: Path, model: str = WHISPER_MODEL) -> str:
    """Transcribe an mp4 file using mlx-whisper."""
    log(f"  Transcribiendo: {mp4_path.name}")
    result = mlx_whisper.transcribe(
        str(mp4_path),
        path_or_hf_repo=model,
        language="es",
        verbose=False,
    )
    return result["text"]


def summarize(transcript: str, mp4_name: str, materials: list[Path]) -> str:
    """Generate a class summary using Claude Code CLI (claude -p)."""
    material_list = ""
    if materials:
        names = [f"- {m.name}" for m in materials]
        material_list = (
            "\n\nMaterial de cátedra disponible en la carpeta:\n"
            + "\n".join(names)
            + "\n\nMencioná qué slides/documentos corresponden a lo explicado."
        )

    prompt = f"""Sos un asistente académico. A partir de la transcripción de una clase universitaria,
generá un resumen estructurado en español.

Archivo: {mp4_name}

Transcripción:
{transcript}
{material_list}

Generá un resumen con este formato markdown:

# Resumen de clase: {mp4_name}

## Temas principales
- ...

## Conceptos clave
- ...

## Definiciones importantes
- ...

## Fechas y deadlines mencionados
- ... (o "No se mencionaron")

## Tareas asignadas
- ... (o "No se asignaron")

## Correspondencia con material de cátedra
- ... (o "No hay material disponible para cruzar")

Sé conciso pero completo. No inventes información que no esté en la transcripción."""

    result = subprocess.run(
        ["claude", "-p", "--model", "haiku"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI falló: {result.stderr.strip()}")
    return result.stdout.strip()


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Transcribe UADE class recordings")
    parser.add_argument("--no-summary", action="store_true",
                        help="Solo transcribir, sin resumen")
    parser.add_argument("--model", type=str, default=WHISPER_MODEL,
                        help="Modelo whisper (default: medium)")
    parser.add_argument("--file", type=str,
                        help="Procesar solo este archivo .mp4")
    args = parser.parse_args()

    conn = init_db()
    whisper_model = args.model

    if args.file:
        mp4s = [Path(args.file)]
    else:
        mp4s = find_mp4s()

    if not mp4s:
        log("No hay .mp4 pendientes de transcripción.")
        return

    log(f"Encontrados {len(mp4s)} videos pendientes")

    # Thread pool for summarization (runs in parallel with next transcription)
    executor = ThreadPoolExecutor(max_workers=1) if not args.no_summary else None
    pending_summary: Future | None = None

    def wait_pending_summary():
        """Wait for any pending summary to finish and log result."""
        nonlocal pending_summary
        if pending_summary is None:
            return
        try:
            pending_summary.result()
        except Exception as e:
            log(f"  ERROR en resumen pendiente: {e}")
        pending_summary = None

    def submit_summary(text, mp4, mp4_path_str, txt_path, summary_path, materia_dir):
        """Submit summarization to run in background thread."""
        nonlocal pending_summary
        wait_pending_summary()

        def _do_summary():
            materials = find_course_materials(materia_dir)
            log(f"  Generando resumen ({len(materials)} materiales)...")
            summary = summarize(text, mp4.name, materials)
            summary_path.write_text(summary, encoding="utf-8")
            log(f"  OK: {summary_path.name}")
            record_transcription(conn, mp4_path_str, str(txt_path), str(summary_path))

        pending_summary = executor.submit(_do_summary)

    for mp4 in mp4s:
        if is_transcribed(conn, str(mp4)):
            log(f"  SKIP (ya en DB): {mp4.name}")
            continue

        txt_path = mp4.with_suffix(".txt")
        materia_dir = mp4.parent.parent
        apuntes_dir = materia_dir / "02_Apuntes_Personales"
        apuntes_dir.mkdir(parents=True, exist_ok=True)
        summary_path = apuntes_dir / (mp4.stem + "_resumen.md")

        # Transcribe (GPU)
        try:
            text = transcribe(mp4, model=whisper_model)
        except Exception as e:
            log(f"  ERROR transcribiendo {mp4.name}: {e}")
            continue

        txt_path.write_text(text, encoding="utf-8")
        log(f"  OK: {txt_path.name} ({len(text)} chars)")

        # Summarize (network — runs in parallel with next transcription)
        if not args.no_summary and executor:
            submit_summary(text, mp4, str(mp4), txt_path, summary_path, materia_dir)
        else:
            record_transcription(conn, str(mp4), str(txt_path))

    # Wait for last summary
    wait_pending_summary()
    if executor:
        executor.shutdown(wait=True)

    conn.close()
    log("Listo.")


if __name__ == "__main__":
    main()
