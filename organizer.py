#!/usr/bin/env python3
"""Organize downloaded Teams material into UADE folder structure.

Moves files from teams_material/ to the standard 01_-06_ folders,
applying naming conventions from the prompt 05 system.
"""

import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

# --- Config ---

BASE_DIR = Path.home() / "UADE" / "4to cuatrimestre"
PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "data" / "downloads.db"

DEST_FOLDERS = {
    "material": "01_Material_de_Clase",
    "apuntes": "02_Apuntes_Personales",
    "tp": "03_Trabajos_Practicos",
    "eval": "04_Evaluaciones",
    "grabacion": "05_Grabaciones",
    "extra": "06_Material_Extra",
}

SKIP_DIRS = {"Student Work", "Submitted files", "Working files"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}

# --- DB ---


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS organized (
            source_path TEXT PRIMARY KEY,
            dest_path   TEXT NOT NULL,
            category    TEXT NOT NULL,
            organized_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def is_organized(conn, source: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM organized WHERE source_path=?", (source,)
    ).fetchone()
    return row is not None


def get_organized_dest(conn, source: str) -> str | None:
    row = conn.execute(
        "SELECT dest_path FROM organized WHERE source_path=?", (source,)
    ).fetchone()
    return row[0] if row else None


def record_organized(conn, source: str, dest: str, category: str):
    conn.execute(
        "INSERT OR REPLACE INTO organized VALUES (?,?,?,?)",
        (source, dest, category, datetime.now().isoformat()),
    )
    conn.commit()


# --- Classification ---


def extract_class_num(path: Path) -> int | None:
    """Extract class number from path or filename."""
    # From parent folder: "Clase 3", "Clase01", "Clase 2"
    for part in path.parts:
        m = re.match(r'[Cc]lase\s*(\d+)', part)
        if m:
            return int(m.group(1))
    # From filename: "Clase 1_...", "PDS_clase_2_...", "IDD-II_Clase02..."
    m = re.search(r'[Cc]lase\s*_?(\d+)', path.name)
    if m:
        return int(m.group(1))
    return None


def classify_file(path: Path) -> tuple[str, str]:
    """Classify a file and generate its new name.

    Returns (category, new_filename).
    """
    name = path.name
    name_lower = name.lower()
    suffix = path.suffix.lower()
    class_num = extract_class_num(path)

    # --- Recordings ---
    if suffix == ".mp4":
        num = class_num or 0
        # Extract date from filename for uniqueness (20260312_075133)
        date_match = re.search(r'(\d{8})_\d{6}', name)
        date_tag = f"_{date_match.group(1)}" if date_match else ""
        clean = _clean_name(name, suffix)
        return "grabacion", f"GRAB_{num:02d}{date_tag}_{clean}{suffix}"

    # --- Transcriptions (follow their mp4) ---
    if suffix == ".txt" and ("grabación" in name_lower or "recording" in name_lower):
        num = class_num or 0
        date_match = re.search(r'(\d{8})_\d{6}', name)
        date_tag = f"_{date_match.group(1)}" if date_match else ""
        return "grabacion", f"GRAB_{num:02d}{date_tag}_transcripcion{suffix}"

    # --- In Recordings/ folder but not mp4 (e.g. other files next to recordings) ---
    if "Recordings" in path.parts or "recordings" in path.parts:
        num = class_num or 0
        date_match = re.search(r'(\d{8})_\d{6}', name)
        date_tag = f"_{date_match.group(1)}" if date_match else ""
        return "grabacion", f"GRAB_{num:02d}{date_tag}_{_clean_name(name, suffix)}{suffix}"

    # --- Exercises / TPs / Actividades ---
    if any(kw in name_lower for kw in ("ejercicio", "actividad", "tp_", "trabajo práctico", "trabajo practico", "trabajo integrador")):
        if "resolucion" in name_lower or "resolución" in name_lower:
            num = class_num or 0
            return "tp", f"TP_{num:02d}_resolucion_{_clean_name(name, suffix)}{suffix}"
        num = class_num or 0
        return "tp", f"TP_{num:02d}_{_clean_name(name, suffix)}{suffix}"

    # --- Cronograma / plan de materia ---
    if any(kw in name_lower for kw in ("cronograma", "3.4.", "presencial")):
        return "extra", _clean_name(name, suffix) + suffix

    # --- Slides / presentations ---
    if suffix in (".pptx", ".ppt"):
        num = class_num or 0
        return "material", f"CLASE_{num:02d}_{_clean_name(name, suffix)}{suffix}"

    # --- Class material (pdf/docx in a Clase folder) ---
    if class_num is not None and suffix in (".pdf", ".docx"):
        return "material", f"CLASE_{class_num:02d}_{_clean_name(name, suffix)}{suffix}"

    # --- Spreadsheets (grupos, equipos, etc) ---
    if suffix in (".xlsx", ".xls"):
        return "extra", _clean_name(name, suffix) + suffix

    # --- Images ---
    if suffix in (".jpg", ".jpeg", ".png", ".gif"):
        num = class_num or 0
        if num:
            return "material", f"CLASE_{num:02d}_{_clean_name(name, suffix)}{suffix}"
        return "extra", _clean_name(name, suffix) + suffix

    # --- Fallback: ask Claude ---
    return classify_with_claude(path)


def classify_with_claude(path: Path) -> tuple[str, str]:
    """Fallback: use claude -p to classify ambiguous files."""
    prompt = f"""Clasificá este archivo universitario en UNA de estas categorías:
- material (slides, PDFs de clase, presentaciones)
- tp (ejercicios, trabajos prácticos, actividades)
- eval (parciales, finales, simulacros)
- grabacion (videos de clase)
- extra (cronogramas, bibliografía, otros)

Archivo: {path.name}
Ruta completa: {path}

Respondé SOLO con el nombre de la categoría, una palabra, sin explicación."""

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
        category = result.stdout.strip().lower()
        if category in DEST_FOLDERS:
            return category, _clean_name(path.name, path.suffix) + path.suffix
    except Exception:
        pass

    # Ultimate fallback
    return "extra", _clean_name(path.name, path.suffix) + path.suffix


def _clean_name(name: str, suffix: str) -> str:
    """Sanitize filename: remove extension, normalize spaces/special chars."""
    base = name
    if suffix and base.lower().endswith(suffix.lower()):
        base = base[:-len(suffix)]
    # Remove date stamps like 20260316_184607
    base = re.sub(r'-?\d{8}_\d{6}', '', base)
    # Remove "Grabación de la reunión" / "Meeting Recording"
    base = re.sub(r'[-_\s]*(Grabación de la reunión|Meeting Recording)', '', base, flags=re.IGNORECASE)
    # Normalize whitespace and special chars
    base = re.sub(r'[<>:"/\\|?*]', '_', base)
    base = re.sub(r'\s+', '_', base.strip())
    base = re.sub(r'_+', '_', base)
    base = base.strip('_.- ')
    return base


# --- Helpers ---


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def should_skip(path: Path) -> bool:
    """Skip Student Work, hidden files, etc."""
    if path.name in SKIP_FILES:
        return True
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    return False


def is_duplicate(path: Path, seen_files: dict) -> bool:
    """SharePoint mirrors files in General/ and Documentos/General/. Keep shortest path."""
    # Key by filename + size to avoid false positives on different files with same name
    try:
        key = (path.name, path.stat().st_size)
    except OSError:
        key = (path.name, 0)
    if key in seen_files:
        existing = seen_files[key]
        if len(str(path)) < len(str(existing)):
            seen_files[key] = path
            return False
        return True
    seen_files[key] = path
    return False


def ensure_dest_folders(materia_dir: Path):
    """Create 01_-06_ folders if they don't exist."""
    for folder in DEST_FOLDERS.values():
        (materia_dir / folder).mkdir(parents=True, exist_ok=True)


# --- Main ---


def organize_materia(materia_dir: Path, conn, dry_run: bool = False):
    """Organize all files in teams_material/ for one materia."""
    teams_dir = materia_dir / "teams_material"
    if not teams_dir.exists():
        return

    ensure_dest_folders(materia_dir)

    files = sorted(f for f in teams_dir.rglob("*") if f.is_file())
    if not files:
        return

    log(f"\n{'='*50}")
    log(f"Materia: {materia_dir.name}")
    log(f"Archivos en teams_material/: {len(files)}")

    seen_files = {}
    moved = 0
    skipped = 0

    for f in files:
        if should_skip(f):
            continue

        if is_duplicate(f, seen_files) and seen_files[f.name] != f:
            skipped += 1
            continue

        source_key = str(f)
        if is_organized(conn, source_key):
            # Ya organizado: si el destino existe, borrar el original
            dest_path = get_organized_dest(conn, source_key)
            if dest_path and Path(dest_path).exists() and not dry_run:
                f.unlink()
            skipped += 1
            continue

        category, new_name = classify_file(f)
        dest_folder = materia_dir / DEST_FOLDERS[category]
        dest = dest_folder / new_name

        # Avoid overwriting
        if dest.exists():
            if dest.stat().st_size == f.stat().st_size:
                record_organized(conn, source_key, str(dest), category)
                skipped += 1
                continue
            # Different size, add suffix
            stem = dest.stem
            dest = dest.with_name(f"{stem}_v2{dest.suffix}")

        if dry_run:
            log(f"  [DRY] {f.name} → {DEST_FOLDERS[category]}/{new_name}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
            record_organized(conn, source_key, str(dest), category)
            log(f"  + {f.name} → {DEST_FOLDERS[category]}/{new_name}")
            moved += 1

    # Limpiar duplicados: archivos en teams_material/ que ya están organizados
    dupes_removed = 0
    for f in sorted(teams_dir.rglob("*"), reverse=True):
        if f.is_file() and not should_skip(f):
            if is_organized(conn, str(f)):
                continue
            # Archivo duplicado de SharePoint (misma data, path más largo)
            # Si ya se movió el original, este es la copia espejo
            try:
                key = (f.name, f.stat().st_size)
            except OSError:
                continue
            if key in seen_files and seen_files[key] != f:
                if not dry_run:
                    f.unlink()
                    dupes_removed += 1

    # Limpiar carpetas vacías en teams_material/
    if not dry_run:
        for dirpath in sorted(teams_dir.rglob("*"), reverse=True):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                dirpath.rmdir()

    log(f"Resultado: {moved} movidos, {skipped} omitidos, {dupes_removed} duplicados eliminados")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Organize UADE Teams material")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo mostrar qué haría, sin mover")
    parser.add_argument("--materia", type=str,
                        help="Solo organizar esta materia (nombre de carpeta)")
    args = parser.parse_args()

    conn = init_db()

    log("UADE Material Organizer")
    log(f"Modo: {'DRY RUN' if args.dry_run else 'EJECUCIÓN'}")

    for materia_dir in sorted(BASE_DIR.iterdir()):
        if not materia_dir.is_dir():
            continue
        if args.materia and materia_dir.name != args.materia:
            continue
        organize_materia(materia_dir, conn, dry_run=args.dry_run)

    conn.close()
    log("\nListo.")


if __name__ == "__main__":
    main()
