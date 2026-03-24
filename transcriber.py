#!/usr/bin/env python3
"""Transcribe UADE class recordings and generate summaries.

Finds .mp4 files in ~/UADE/4to cuatrimestre/*/teams_material/,
transcribes with mlx-whisper (local, Apple Silicon), and generates
summaries via Claude Code CLI.
"""

import argparse
import sqlite3
import subprocess
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
    """Find .mp4 files that don't have a .txt transcription yet.

    Deduplicates by filename — SharePoint sometimes mirrors files in
    General/ and Documentos/General/. Prefers the shorter path.
    """
    seen = {}  # filename -> Path (keep shortest path)
    for materia_dir in sorted(BASE_DIR.iterdir()):
        if not materia_dir.is_dir():
            continue
        teams_dir = materia_dir / "teams_material"
        if not teams_dir.exists():
            continue
        for mp4 in sorted(teams_dir.rglob("*.mp4")):
            txt = mp4.with_suffix(".txt")
            if txt.exists():
                continue
            key = (materia_dir.name, mp4.name)
            if key not in seen or len(str(mp4)) < len(str(seen[key])):
                seen[key] = mp4
    return sorted(seen.values())


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
        ["claude", "-p", prompt, "--model", "haiku"],
        capture_output=True, text=True, timeout=120,
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

    for mp4 in mp4s:
        if is_transcribed(conn, str(mp4)):
            log(f"  SKIP (ya en DB): {mp4.name}")
            continue

        txt_path = mp4.with_suffix(".txt")
        summary_path = mp4.with_name(mp4.stem + "_resumen.md")

        # Transcribe
        try:
            text = transcribe(mp4, model=whisper_model)
        except Exception as e:
            log(f"  ERROR transcribiendo {mp4.name}: {e}")
            continue

        txt_path.write_text(text, encoding="utf-8")
        log(f"  OK: {txt_path.name} ({len(text)} chars)")

        # Summarize
        if not args.no_summary:
            try:
                materia_dir = mp4
                while materia_dir.name != "teams_material" and materia_dir != BASE_DIR:
                    materia_dir = materia_dir.parent
                materia_dir = materia_dir.parent
                materials = find_course_materials(materia_dir)
                log(f"  Generando resumen ({len(materials)} materiales encontrados)...")
                summary = summarize(text, mp4.name, materials)
                summary_path.write_text(summary, encoding="utf-8")
                log(f"  OK: {summary_path.name}")
                record_transcription(conn, str(mp4), str(txt_path), str(summary_path))
            except Exception as e:
                log(f"  ERROR en resumen: {e}")
                record_transcription(conn, str(mp4), str(txt_path))
        else:
            record_transcription(conn, str(mp4), str(txt_path))

    conn.close()
    log("Listo.")


if __name__ == "__main__":
    main()
