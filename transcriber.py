#!/usr/bin/env python3
"""Transcribe grabaciones de clase y genera resumenes inteligentes.

Busca .mp4 en 05_Grabaciones/, transcribe con Whisper (local),
y genera resumenes con contexto (slides + cronograma + clase anterior).
"""

import argparse
import hashlib
import re
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from pathlib import Path

import config
import db
from backends import whisper as whisper_backend
from backends import llm as llm_backend
import tasks

# --- Config ---

BASE_DIR = config.BASE_DIR

MATERIA_DISPLAY = {
    "Inteligencia_Artificial_Aplicada": "IA Aplicada",
    "Proceso_de_Desarrollo_de_Software": "PDS",
    "Desarrollo_de_Aplicaciones": "Desarrollo de Aplicaciones I",
    "Ingenieria_de_Datos_II": "Ingeniería de Datos II",
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# --- Text extraction ---


def extract_text_from_file(path: Path) -> str | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n\n".join(p.extract_text() or "" for p in reader.pages).strip()
        elif suffix in (".pptx", ".ppt"):
            from pptx import Presentation
            prs = Presentation(str(path))
            texts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        texts.append(shape.text_frame.text)
            return "\n\n".join(texts).strip()
        elif suffix in (".txt", ".md"):
            return path.read_text(encoding="utf-8").strip()
        elif suffix == ".docx":
            import zipfile
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(str(path)) as z:
                xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            return "\n".join(
                t.text for t in tree.iter(f"{{{ns['w']}}}t") if t.text
            ).strip()
    except Exception as e:
        log(f"    WARN: no se pudo extraer texto de {path.name}: {e}")
    return None


# --- Context ---


def extract_class_num(mp4_path: Path) -> int | None:
    m = re.match(r'GRAB_(\d+)', mp4_path.stem)
    if m:
        num = int(m.group(1))
        return num if num > 0 else None
    return None


def extract_date(mp4_path: Path) -> str | None:
    m = re.search(r'GRAB_\d+_(\d{8})', mp4_path.stem)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return None


def compute_context_hash(materia_dir: Path, class_num: int | None) -> str:
    h = hashlib.md5()
    material_dir = materia_dir / config.FOLDERS["material"]
    extra_dir = materia_dir / config.FOLDERS["extra"]

    if class_num and material_dir.exists():
        prefix = f"CLASE_{class_num:02d}_"
        for f in sorted(material_dir.iterdir()):
            if f.name.startswith(prefix) and f.suffix.lower() in (".pdf", ".pptx", ".ppt", ".docx"):
                h.update(f.name.encode())
                h.update(str(f.stat().st_size).encode())
                h.update(str(f.stat().st_mtime).encode())

    if extra_dir.exists():
        for f in sorted(extra_dir.iterdir()):
            if f.suffix.lower() == ".pdf" and ("3.4." in f.name or "cronograma" in f.name.lower()):
                h.update(f.name.encode())
                h.update(str(f.stat().st_size).encode())
                h.update(str(f.stat().st_mtime).encode())

    return h.hexdigest()


def find_class_context(materia_dir: Path, class_num: int | None) -> dict:
    ctx = {
        "slides": None, "cronograma": None, "prev_summary": None,
        "materia_name": MATERIA_DISPLAY.get(materia_dir.name, materia_dir.name),
    }

    material_dir = materia_dir / config.FOLDERS["material"]
    extra_dir = materia_dir / config.FOLDERS["extra"]
    apuntes_dir = materia_dir / config.FOLDERS["apuntes"]

    if class_num and material_dir.exists():
        prefix = f"CLASE_{class_num:02d}_"
        slide_texts = []
        for f in sorted(material_dir.iterdir()):
            if f.name.startswith(prefix) and f.suffix.lower() in (".pdf", ".pptx", ".ppt", ".docx"):
                text = extract_text_from_file(f)
                if text:
                    slide_texts.append(f"### {f.name}\n{text}")
        if slide_texts:
            ctx["slides"] = "\n\n".join(slide_texts)

    if extra_dir.exists():
        for f in sorted(extra_dir.iterdir()):
            if f.suffix.lower() == ".pdf" and ("3.4." in f.name or "cronograma" in f.name.lower()):
                text = extract_text_from_file(f)
                if text:
                    ctx["cronograma"] = text
                    break

    if class_num and class_num > 1 and apuntes_dir.exists():
        prev_pattern = f"GRAB_{class_num - 1:02d}_"
        for f in sorted(apuntes_dir.iterdir()):
            if f.name.startswith(prev_pattern) and f.name.endswith("_resumen.md"):
                text = f.read_text(encoding="utf-8").strip()
                if text:
                    ctx["prev_summary"] = "\n".join(text.split("\n")[:80])
                    break

    return ctx


# --- Transcription ---


def transcribe(mp4_path: Path, model: str = "") -> str:
    size_mb = mp4_path.stat().st_size / (1024 * 1024)
    backend = whisper_backend.detect()
    log(f"  Transcribiendo: {mp4_path.name} ({size_mb:.0f} MB) [{backend}]")

    stop_heartbeat = threading.Event()
    start = datetime.now()

    def heartbeat():
        while not stop_heartbeat.wait(30):
            elapsed = datetime.now() - start
            mins = int(elapsed.total_seconds() // 60)
            secs = int(elapsed.total_seconds() % 60)
            log(f"  ... transcribiendo ({mins}m {secs}s)")

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()

    try:
        text = whisper_backend.transcribe(str(mp4_path), model=model)
    finally:
        stop_heartbeat.set()
        hb.join(timeout=1)

    elapsed = datetime.now() - start
    mins = int(elapsed.total_seconds() // 60)
    secs = int(elapsed.total_seconds() % 60)
    log(f"  Transcripcion completada en {mins}m {secs}s")
    return text


# --- Summarization ---


def summarize(transcript: str, mp4_path: Path, class_num: int | None,
              class_date: str | None, ctx: dict,
              quality_warning: str | None = None) -> str:

    materia = ctx["materia_name"]
    clase_label = f"Clase {class_num}" if class_num else "Clase"
    fecha_label = class_date or "fecha desconocida"

    context_parts = []
    if ctx["cronograma"]:
        context_parts.append(f"## Cronograma/Plan de la materia\n{ctx['cronograma'][:3000]}")
    if ctx["slides"]:
        context_parts.append(f"## Slides de esta clase\n{ctx['slides'][:8000]}")
    if ctx["prev_summary"]:
        context_parts.append(f"## Resumen de la clase anterior\n{ctx['prev_summary']}")

    context_block = "\n\n---\n\n".join(context_parts) if context_parts else ""

    prompt = f"""Sos un asistente académico experto. Generá un resumen estructurado de esta clase
universitaria para estudio. El resumen debe ser útil para: preparar parciales, ponerse al día
si se faltó, armar apuntes propios, y no perderse entregas.

Materia: {materia}
Clase: {clase_label} ({fecha_label})

{f"--- MATERIAL DE CONTEXTO ---{chr(10)}{chr(10)}{context_block}{chr(10)}{chr(10)}" if context_block else ""}--- TRANSCRIPCIÓN DE LA CLASE ---

{transcript}

--- INSTRUCCIONES ---

Generá el resumen con EXACTAMENTE este formato markdown:

# {materia} — {clase_label} ({fecha_label})

## Ubicación en el programa
- Unidad/tema según el cronograma (si se proporcionó)
- Conexión con la clase anterior (si hay resumen previo)

## Temas explicados
- Cada tema con una explicación concisa pero precisa
- Priorizá lo que el profe desarrolló en detalle

## Conceptos clave para el examen
- Concepto: definición precisa tal como la dio el profesor

## Ejemplos y casos prácticos
- Cada ejemplo mencionado y qué concepto ilustra

## Lo que dijo el profe (citas relevantes)
> Frases textuales que enfatizan algo importante

## Correspondencia con slides
- Qué slides corresponden a cada tema (si se proporcionó material)

## Tareas y entregas
- [ ] Descripción de la tarea 📅 YYYY-MM-DD
- Si no hay tareas: "No se asignaron tareas en esta clase."

## Fechas y deadlines mencionados
- Parcial/entrega/evento: fecha

## Dudas para revisar
- Puntos ambiguos o temas que quedaron incompletos

---

REGLAS:
- Escribí en español argentino
- No inventes información que no esté en la transcripción
- Las citas del profe deben ser lo más textuales posible
- El formato de tareas debe ser compatible con Obsidian Tasks
- Sé completo pero no redundante"""

    summary = llm_backend.complete(prompt)
    if quality_warning:
        summary = f"> **{quality_warning}**\n\n{summary}"
    return summary


# --- Main ---


def find_mp4s() -> list[Path]:
    results = []
    for materia_dir in sorted(BASE_DIR.iterdir()):
        if not materia_dir.is_dir():
            continue
        grab_dir = materia_dir / config.FOLDERS["grabacion"]
        if not grab_dir.exists():
            continue
        for mp4 in sorted(grab_dir.glob("*.mp4")):
            if not mp4.with_suffix(".txt").exists():
                results.append(mp4)
    return results


def main():
    parser = argparse.ArgumentParser(description="Transcribe UADE class recordings")
    parser.add_argument("--no-summary", action="store_true", help="Solo transcribir")
    parser.add_argument("--model", type=str, default="", help="Modelo whisper")
    parser.add_argument("--file", type=str, help="Procesar solo este .mp4")
    args = parser.parse_args()

    conn = db.get_connection(check_same_thread=False)

    mp4s = [Path(args.file)] if args.file else find_mp4s()
    if not mp4s:
        log("No hay .mp4 pendientes de transcripcion.")
        tasks.show_status(log)
        return

    log(f"Encontrados {len(mp4s)} videos pendientes")

    skip_summary = args.no_summary
    if not skip_summary and not llm_backend.is_available():
        log("AVISO: No hay LLM configurado. Solo transcripcion (sin resumenes).")
        skip_summary = True

    executor = ThreadPoolExecutor(max_workers=1) if not skip_summary else None
    pending_summary: Future | None = None

    def wait_pending():
        nonlocal pending_summary
        if pending_summary is None:
            return
        try:
            pending_summary.result()
        except Exception as e:
            log(f"  ERROR en resumen: {e}")
        pending_summary = None

    def submit_summary(text, mp4, txt_path, summary_path, materia_dir, is_regen=False):
        nonlocal pending_summary
        wait_pending()
        class_num = extract_class_num(mp4)
        class_date = extract_date(mp4)

        def _do():
            label = "Regenerando" if is_regen else "Recopilando contexto para"
            log(f"  {label} {mp4.name}...")
            ctx = find_class_context(materia_dir, class_num)
            ctx_hash = compute_context_hash(materia_dir, class_num)
            parts = [k for k in ("slides", "cronograma", "prev_summary") if ctx[k]]
            log(f"  Contexto: {', '.join(parts) if parts else 'solo transcripcion'}")
            quality_warn = tasks.assess_quality(text, mp4)
            if quality_warn:
                log(f"  {quality_warn}")
            log(f"  Generando resumen con {llm_backend.detect()}...")
            summary = summarize(text, mp4, class_num, class_date, ctx,
                                quality_warning=quality_warn)
            summary_path.write_text(summary, encoding="utf-8")
            log(f"  OK: {summary_path.name}")
            db.record_transcription(conn, str(mp4), str(txt_path),
                                    str(summary_path), context_hash=ctx_hash)

        pending_summary = executor.submit(_do)

    # Procesar nuevos
    for mp4 in mp4s:
        if db.is_transcribed(conn, str(mp4)):
            log(f"  SKIP (ya en DB): {mp4.name}")
            continue

        txt_path = mp4.with_suffix(".txt")
        materia_dir = mp4.parent.parent
        apuntes_dir = materia_dir / config.FOLDERS["apuntes"]
        apuntes_dir.mkdir(parents=True, exist_ok=True)
        summary_path = apuntes_dir / (mp4.stem + "_resumen.md")

        try:
            text = transcribe(mp4, model=args.model)
        except Exception as e:
            log(f"  ERROR transcribiendo {mp4.name}: {e}")
            continue

        txt_path.write_text(text, encoding="utf-8")
        log(f"  OK: {txt_path.name} ({len(text)} chars)")
        db.record_transcription(conn, str(mp4), str(txt_path))

        if not skip_summary and executor:
            submit_summary(text, mp4, txt_path, summary_path, materia_dir)

    wait_pending()

    # Detectar resumenes stale (material cambio)
    if not skip_summary and executor:
        stale = 0
        for materia_dir in sorted(BASE_DIR.iterdir()):
            if not materia_dir.is_dir():
                continue
            grab_dir = materia_dir / config.FOLDERS["grabacion"]
            if not grab_dir.exists():
                continue
            for mp4 in sorted(grab_dir.glob("*.mp4")):
                txt_path = mp4.with_suffix(".txt")
                if not txt_path.exists():
                    continue
                class_num = extract_class_num(mp4)
                ctx_hash = compute_context_hash(materia_dir, class_num)
                if db.needs_resummarize(conn, str(mp4), ctx_hash):
                    stale += 1
                    apuntes_dir = materia_dir / config.FOLDERS["apuntes"]
                    apuntes_dir.mkdir(parents=True, exist_ok=True)
                    summary_path = apuntes_dir / (mp4.stem + "_resumen.md")
                    text = txt_path.read_text(encoding="utf-8")
                    log(f"  Material nuevo detectado para {mp4.name}")
                    submit_summary(text, mp4, txt_path, summary_path, materia_dir, is_regen=True)
        if stale:
            wait_pending()
            log(f"  {stale} resumenes regenerados por cambio de material")

    if executor:
        executor.shutdown(wait=True)
    conn.close()

    if not skip_summary:
        tasks.consolidate(log)

    tasks.show_status(log)
    log("Listo.")


if __name__ == "__main__":
    main()
