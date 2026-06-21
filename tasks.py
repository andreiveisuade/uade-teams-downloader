"""Consolidacion de tareas y analisis de calidad de transcripciones."""

import re
import subprocess
from pathlib import Path

import config


AUDIO_REJECTED_MARKER = "[AUDIO INCOMPLETO — NO TRANSCRIBIBLE]"


def is_rejected_marker(text: str) -> bool:
    """True si el .txt es un tombstone de audio rechazado, no una transcripcion.

    Estos .txt no deben borrarse ni re-transcribirse: son estado terminal.
    """
    return text.lstrip().startswith(AUDIO_REJECTED_MARKER)


def check_audio_health(mp4_path: Path) -> tuple[bool, str]:
    """Sample de audio en 5 puntos del mp4. Si >60% son silencio, rechaza.

    Retorna (ok, razon). Si ffmpeg no esta disponible, asume ok.
    """
    try:
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp4_path)],
            capture_output=True, text=True, timeout=15,
        )
        total = float(dur.stdout.strip())
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return True, "ffprobe no disponible, skip check"

    if total < 60:
        return True, "video muy corto, skip check"

    samples = [total * f for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    silent = 0
    for t in samples:
        try:
            r = subprocess.run(
                ["ffmpeg", "-ss", str(t), "-t", "10", "-i", str(mp4_path),
                 "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, timeout=30,
            )
            for line in r.stderr.splitlines():
                if "mean_volume" in line:
                    db = float(line.split(":")[-1].strip().split()[0])
                    if db < -60:
                        silent += 1
                    break
        except (subprocess.SubprocessError, ValueError):
            continue

    if silent >= 4:
        return False, f"audio en silencio ({silent}/5 samples < -60dB)"
    return True, "ok"


def validate_transcription(text: str, size_mb: float) -> tuple[bool, str]:
    """Valida si una transcripcion es usable. Retorna (ok, razon).

    Criterios de rechazo:
    - Menos de 30 chars/MB en videos > 50MB (casi seguro basura)
    - Mas de 5% de repeticion triple de palabras (alucinacion)
    - Menos de 20 palabras totales en videos > 50MB
    """
    words = text.split()

    if size_mb > 50 and len(words) < 20:
        return False, f"transcripcion casi vacia ({len(words)} palabras para {size_mb:.0f} MB)"

    chars_per_mb = len(text) / max(size_mb, 1)
    if size_mb > 50 and chars_per_mb < 30:
        return False, f"contenido insuficiente ({chars_per_mb:.0f} chars/MB, minimo: 30)"

    if len(words) > 50:
        # Detectar repeticion triple de cualquier palabra (incluye "y y y")
        repeats = sum(
            1 for i in range(2, len(words))
            if words[i] == words[i-1] == words[i-2]
        )
        if repeats / len(words) > 0.05:
            return False, f"alucinacion detectada ({repeats/len(words):.0%} repeticion)"

    return True, "ok"


def assess_quality(text: str, mp4_path: Path) -> str | None:
    """Analiza la calidad de la transcripcion. Retorna advertencia o None.

    A diferencia de validate_transcription(), esto genera warnings suaves
    para el resumen pero no bloquea el guardado.
    """
    issues = []

    size_mb = mp4_path.stat().st_size / (1024 * 1024)
    chars_per_mb = len(text) / max(size_mb, 1)

    if size_mb > 50 and chars_per_mb < 80:
        issues.append(
            f"poco contenido transcripto para el tamaño del video "
            f"({chars_per_mb:.0f} chars/MB, normal: >150)"
        )

    words = text.split()
    if len(words) > 50:
        repeats = sum(
            1 for i in range(2, len(words))
            if words[i] == words[i-1] == words[i-2] and len(words[i]) > 2
        )
        if repeats / len(words) > 0.02:
            issues.append("repeticiones excesivas detectadas (posible audio con ruido o eco)")

    if issues:
        return "ADVERTENCIA: Calidad de audio baja — " + "; ".join(issues) + "."
    return None


def consolidate(log_fn=print):
    """Parsea todos los _resumen.md y genera un tareas.md por materia."""
    task_pattern = re.compile(r'^- \[ \] .+', re.MULTILINE)

    for materia_dir in sorted(config.BASE_DIR.iterdir()):
        if not materia_dir.is_dir():
            continue
        apuntes_dir = materia_dir / config.FOLDERS["apuntes"]
        if not apuntes_dir.exists():
            continue

        all_tasks = []
        for resumen in sorted(apuntes_dir.glob("*_resumen.md")):
            text = resumen.read_text(encoding="utf-8")
            found = task_pattern.findall(text)
            if found:
                clase_name = resumen.stem.replace("_resumen", "")
                all_tasks.append(f"### {clase_name}\n")
                all_tasks.extend(found)
                all_tasks.append("")

        if all_tasks:
            tareas_path = materia_dir / "tareas.md"
            content = f"# Tareas — {materia_dir.name}\n\n"
            content += "Generado automaticamente por el pipeline.\n\n"
            content += "\n".join(all_tasks) + "\n"
            tareas_path.write_text(content, encoding="utf-8")
            count = len([t for t in all_tasks if t.startswith("- [ ]")])
            log_fn(f"  Tareas consolidadas: {tareas_path.name} ({count} tareas)")


def show_status(log_fn=print):
    """Muestra un resumen del estado del pipeline."""
    total_mp4 = 0
    total_txt = 0
    total_resumen = 0
    for materia_dir in sorted(config.BASE_DIR.iterdir()):
        if not materia_dir.is_dir():
            continue
        grab_dir = materia_dir / config.FOLDERS["grabacion"]
        apuntes_dir = materia_dir / config.FOLDERS["apuntes"]
        if grab_dir.exists():
            total_mp4 += len(list(grab_dir.glob("*.mp4")))
            total_txt += len(list(grab_dir.glob("*.txt")))
        if apuntes_dir.exists():
            total_resumen += len(list(apuntes_dir.glob("*_resumen.md")))
    log_fn(f"  Estado: {total_mp4} grabaciones, {total_txt} transcripciones, {total_resumen} resumenes")
