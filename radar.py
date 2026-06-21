"""Radar de pendientes UADE.

Auto-descubre las materias del cuatrimestre activo (~/UADE/actual), parsea los
tareas.md que genera el pipeline y clasifica cada tarea por urgencia contra hoy.
Estado de "entregado" persistido en task_status (DB compartida con el pipeline).

Uso:
    python radar.py            # tablero legible
    python radar.py --json     # salida estructurada (para la skill /uade)
    python radar.py done   <key>   # marcar tarea como entregada
    python radar.py undone <key>   # desmarcar
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import config
import db

DATE_RE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
TASK_RE = re.compile(r"^-\s*\[[ xX]\]\s*(.+)$")


def active_cuatri() -> Path | None:
    """Cuatri activo = config.BASE_DIR (UADE_BASE_DIR en .env, compartido con el pipeline)."""
    base = config.BASE_DIR
    return base if base.is_dir() and any(p.is_dir() for p in base.iterdir()) else None


def task_key(materia: str, text: str) -> str:
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha1(f"{materia}|{norm}".encode()).hexdigest()[:6]


def parse_materia(materia_dir: Path) -> list[dict]:
    f = materia_dir / "tareas.md"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        m = TASK_RE.match(line.strip())
        if not m:
            continue
        raw = m.group(1).strip()
        dm = DATE_RE.search(raw)
        due = dm.group(1) if dm else None
        text = DATE_RE.sub("", raw).strip(" -–·")
        out.append({
            "key": task_key(materia_dir.name, text),
            "materia": materia_dir.name,
            "text": text,
            "due": due,
        })
    return out


def classify(tasks: list[dict], today: date) -> dict:
    buckets = {"vencida_reciente": [], "esta_semana": [], "proxima": [],
               "sin_fecha": [], "backlog": {}, "nuevo_material": {}}
    for t in tasks:
        if t["due"] is None:
            buckets["sin_fecha"].append(t)
            continue
        d = date.fromisoformat(t["due"])
        days = (d - today).days
        t = {**t, "days": days}
        if days < -14:
            buckets["backlog"][t["materia"]] = buckets["backlog"].get(t["materia"], 0) + 1
        elif days < 0:
            buckets["vencida_reciente"].append(t)
        elif days <= 7:
            buckets["esta_semana"].append(t)
        else:
            buckets["proxima"].append(t)
    for k in ("vencida_reciente", "esta_semana", "proxima"):
        buckets[k].sort(key=lambda t: t["days"])
    return buckets


def recent_material(materia_dir: Path, today: date) -> int:
    """Cuenta resumenes/transcripciones modificados en los ultimos 7 dias."""
    n = 0
    for sub in (config.FOLDERS["apuntes"], config.FOLDERS["grabacion"]):
        d = materia_dir / sub
        if not d.is_dir():
            continue
        for f in d.glob("*"):
            if f.is_file() and (today - date.fromtimestamp(f.stat().st_mtime)).days <= 7:
                n += 1
    return n


def build(today: date) -> dict:
    cuatri = active_cuatri()
    if cuatri is None:
        return {"error": "no encontre cuatri activo en ~/UADE (creá symlink 'actual')"}
    conn = db.get_connection()
    done = db.done_task_keys(conn)
    materias = sorted(d for d in cuatri.iterdir() if d.is_dir())
    all_tasks, nuevo = [], {}
    for md in materias:
        all_tasks += [t for t in parse_materia(md) if t["key"] not in done]
        r = recent_material(md, today)
        if r:
            nuevo[md.name] = r
    conn.close()
    buckets = classify(all_tasks, today)
    buckets["nuevo_material"] = nuevo
    return {"cuatri": cuatri.name, "today": today.isoformat(),
            "materias": [m.name for m in materias], "buckets": buckets}


def short(materia: str) -> str:
    return materia.replace("_", " ")


def render(data: dict) -> str:
    if "error" in data:
        return f"!! {data['error']}"
    b = data["buckets"]
    L = [f"📅 Radar UADE — {data['cuatri']} · hoy {data['today']}", ""]

    def rows(items):
        return [f"  [{t['key']}] {short(t['materia'])[:18]:18} {t['text'][:48]:48} "
                f"📅 {t['due']} ({t['days']:+d}d)" for t in items]

    if b["vencida_reciente"]:
        L += ["🔴 Vencidas recientes (¿entregaste? → done <key>)"] + rows(b["vencida_reciente"])
    if b["esta_semana"]:
        L += ["🟡 Esta semana"] + rows(b["esta_semana"])
    if b["proxima"]:
        L += ["🟢 Próximas"] + rows(b["proxima"])
    if b["sin_fecha"]:
        L += ["⚪ Sin fecha"] + [f"  [{t['key']}] {short(t['materia'])[:18]:18} {t['text'][:54]}"
                                 for t in b["sin_fecha"]]
    if b["backlog"]:
        bl = " · ".join(f"{short(m)} {n}" for m, n in b["backlog"].items())
        L += ["", f"Backlog (>14d, revisá si quedó algo): {bl}"]
    if b["nuevo_material"]:
        nm = " · ".join(f"{short(m)} {n}" for m, n in b["nuevo_material"].items())
        L += [f"🆕 Material nuevo (7d): {nm}"]
    if not any(b[k] for k in ("vencida_reciente", "esta_semana", "proxima", "sin_fecha")):
        L += ["Sin pendientes con fecha. Todo al día."]
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description="Radar de pendientes UADE")
    p.add_argument("cmd", nargs="?", default="radar", choices=["radar", "done", "undone"])
    p.add_argument("key", nargs="?")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.cmd in ("done", "undone"):
        if not args.key:
            sys.exit(f"falta <key>. uso: radar.py {args.cmd} <key>")
        conn = db.get_connection()
        if args.cmd == "done":
            data = build(date.today())
            match = next((t for bk in ("vencida_reciente", "esta_semana", "proxima", "sin_fecha")
                          for t in data["buckets"][bk] if t["key"] == args.key), None)
            if not match:
                conn.close()
                sys.exit(f"key {args.key} no está entre las pendientes")
            db.mark_task_done(conn, args.key, match["materia"], match["text"])
            print(f"✓ entregada: {match['text'][:60]}")
        else:
            db.unmark_task_done(conn, args.key)
            print(f"↩ desmarcada {args.key}")
        conn.close()
        return

    data = build(date.today())
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data))


if __name__ == "__main__":
    main()
