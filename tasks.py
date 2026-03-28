"""Consolidacion de tareas y analisis de calidad de transcripciones."""

import re
from pathlib import Path

import config


def assess_quality(text: str, mp4_path: Path) -> str | None:
    """Analiza la calidad de la transcripcion. Retorna advertencia o None."""
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
