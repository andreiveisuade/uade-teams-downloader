#!/usr/bin/env python3
"""File lifecycle status for UADE material pipeline.

Shows the state of each file across download → organize → transcribe stages.
"""

import argparse
import sqlite3
from pathlib import Path

import config
from logger import log

DB_PATH = config.DB_PATH

VIEW_SQL = """
CREATE VIEW IF NOT EXISTS file_status AS
SELECT
    d.filename,
    d.team_prefix,
    d.local_path                            AS download_path,
    d.downloaded_at,
    o.dest_path                             AS organized_path,
    o.category,
    o.organized_at,
    t.txt_path                              AS transcript_path,
    t.summary_path,
    t.transcribed_at,
    t.summarized_at,
    CASE
        WHEN t.summary_path IS NOT NULL THEN 'complete'
        WHEN t.mp4_path IS NOT NULL THEN 'transcribed'
        WHEN o.source_path IS NOT NULL AND d.filename LIKE '%.mp4' THEN 'pending_transcription'
        WHEN o.source_path IS NOT NULL THEN 'organized'
        ELSE 'pending_organize'
    END AS status
FROM (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY team_prefix, filename ORDER BY LENGTH(local_path)
    ) AS rn FROM downloads
) d
LEFT JOIN organized o ON o.source_path = d.local_path
LEFT JOIN transcriptions t ON t.mp4_path = o.dest_path OR t.mp4_path = d.local_path
WHERE d.rn = 1
"""





def ensure_view(conn):
    conn.execute("DROP VIEW IF EXISTS file_status")
    conn.execute(VIEW_SQL)


def cmd_summary(conn):
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM file_status GROUP BY status ORDER BY COUNT(*) DESC"
    ).fetchall()
    total = sum(r[1] for r in rows)
    print(f"Pipeline status ({total} archivos):")
    for status, count in rows:
        print(f"  {status:30s} {count}")


def cmd_pending(conn):
    for status, label in [
        ("pending_organize", "Pendientes de organizar"),
        ("pending_transcription", "Pendientes de transcribir"),
    ]:
        rows = conn.execute(
            "SELECT filename, download_path FROM file_status WHERE status=?",
            (status,),
        ).fetchall()
        print(f"\n{label} ({len(rows)}):")
        if not rows:
            print("  (ninguno)")
        for fname, path in rows:
            print(f"  {fname}")


def cmd_mp4(conn):
    rows = conn.execute(
        "SELECT filename, status, organized_path, transcript_path, summary_path "
        "FROM file_status WHERE filename LIKE '%.mp4' ORDER BY filename"
    ).fetchall()
    print(f"Grabaciones ({len(rows)}):\n")
    for fname, status, org, txt, summary in rows:
        marks = []
        marks.append("DL")
        marks.append("ORG" if org else "   ")
        marks.append("TXT" if txt else "   ")
        marks.append("RES" if summary else "   ")
        print(f"  [{' '.join(marks)}] {fname}")
        if org:
            print(f"              → {Path(org).name}")
    print(f"\n  Leyenda: DL=descargado ORG=organizado TXT=transcripto RES=resumido")


def cmd_detail(conn):
    rows = conn.execute(
        "SELECT filename, team_prefix, status, category, organized_path "
        "FROM file_status ORDER BY team_prefix, status, filename"
    ).fetchall()
    current_prefix = None
    for fname, prefix, status, cat, org_path in rows:
        if prefix != current_prefix:
            current_prefix = prefix
            print(f"\n  Team {prefix}:")
        dest = Path(org_path).name if org_path else "(sin organizar)"
        print(f"    {status:25s} [{cat or '?':10s}] {fname}")


# --- Health check ---


def cmd_health(conn, fix: bool = False):
    """Cross-check DB con filesystem. Detecta phantoms, huerfanos, inconsistencias."""
    import db

    issues = []
    fixed = 0

    # 1. Phantom downloads (en DB pero archivo no existe)
    dl_ok = 0
    for key, local_path, status in db.all_downloads(conn):
        if status != "complete":
            issues.append(("download_incomplete", key, f"status={status}"))
            if fix:
                db.delete_download(conn, key)
                fixed += 1
            continue
        if local_path and not Path(local_path).exists():
            issues.append(("download_phantom", key, local_path))
            if fix:
                db.delete_download(conn, key)
                fixed += 1
        else:
            dl_ok += 1

    # 2. Phantom organized (dest no existe)
    org_ok = 0
    for source, dest in db.all_organized(conn):
        if not Path(dest).exists():
            issues.append(("organized_phantom", source, dest))
            if fix:
                db.delete_organized(conn, source)
                fixed += 1
        else:
            org_ok += 1
            # Source todavia existe = cleanup incompleto
            if Path(source).exists():
                issues.append(("organized_leftover_source", source, dest))
                if fix:
                    Path(source).unlink()
                    fixed += 1

    # 3. Phantom transcriptions (txt o summary no existe)
    tx_ok = 0
    for mp4_path, txt_path, summary_path in db.all_transcriptions(conn):
        if txt_path and not Path(txt_path).exists():
            issues.append(("transcription_phantom_txt", mp4_path, txt_path))
            if fix:
                db.delete_transcription(conn, mp4_path)
                fixed += 1
            continue
        if summary_path and not Path(summary_path).exists():
            issues.append(("transcription_phantom_summary", mp4_path, summary_path))
            if fix:
                # Solo limpiar summary_path, no borrar todo el record
                conn.execute(
                    "UPDATE transcriptions SET summary_path=NULL, summarized_at=NULL WHERE mp4_path=?",
                    (mp4_path,),
                )
                conn.commit()
                fixed += 1
            continue
        tx_ok += 1

    # 4. Archivos huerfanos en disco (mp4/txt sin record en DB)
    orphans = []
    for materia_dir in sorted(config.BASE_DIR.iterdir()):
        if not materia_dir.is_dir():
            continue
        grab_dir = materia_dir / config.FOLDERS.get("grabacion", "05_Grabaciones")
        if not grab_dir.exists():
            continue
        for mp4 in sorted(grab_dir.glob("*.mp4")):
            if not db.is_transcribed(conn, str(mp4)):
                txt = mp4.with_suffix(".txt")
                has_txt = txt.exists()
                orphans.append(("orphan_mp4", str(mp4), f"txt={'si' if has_txt else 'no'}"))

    # Reportar
    print(f"\nHealth check:")
    if dl_ok:
        print(f"  OK  {dl_ok} downloads verificados")
    if org_ok:
        print(f"  OK  {org_ok} organized verificados")
    if tx_ok:
        print(f"  OK  {tx_ok} transcriptions verificados")

    phantoms = [i for i in issues if "phantom" in i[0]]
    incompletes = [i for i in issues if "incomplete" in i[0]]
    leftovers = [i for i in issues if "leftover" in i[0]]

    if phantoms:
        print(f"  !!  {len(phantoms)} phantom records (en DB pero archivo no existe)")
        for kind, key, detail in phantoms[:5]:
            print(f"      {kind}: {Path(detail).name if '/' in detail else detail}")
        if len(phantoms) > 5:
            print(f"      ... y {len(phantoms) - 5} mas")

    if incompletes:
        print(f"  !!  {len(incompletes)} descargas incompletas")

    if leftovers:
        print(f"  !!  {len(leftovers)} source files no limpiados")

    if orphans:
        print(f"  !!  {len(orphans)} mp4 sin registro de transcripcion")
        for _, path, detail in orphans[:5]:
            print(f"      {Path(path).name} ({detail})")
        if len(orphans) > 5:
            print(f"      ... y {len(orphans) - 5} mas")

    if not issues and not orphans:
        print(f"  OK  Todo consistente")
    elif fix and fixed:
        print(f"\n  Reparados: {fixed} problemas")
    elif issues:
        print(f"\n  Usar --fix para reparar automaticamente")


def main():
    parser = argparse.ArgumentParser(description="UADE pipeline file status")
    parser.add_argument("--pending", action="store_true",
                        help="Mostrar archivos pendientes de cada etapa")
    parser.add_argument("--mp4", action="store_true",
                        help="Ciclo de vida de grabaciones")
    parser.add_argument("--detail", action="store_true",
                        help="Detalle por team/materia")
    parser.add_argument("--health", action="store_true",
                        help="Cross-check DB con filesystem")
    parser.add_argument("--fix", action="store_true",
                        help="Reparar inconsistencias (junto con --health)")
    args = parser.parse_args()

    import db as _db
    conn = _db.get_connection()  # Aplica migraciones + WAL + busy_timeout
    ensure_view(conn)

    if args.health:
        cmd_health(conn, fix=args.fix)
    elif args.pending:
        cmd_pending(conn)
    elif args.mp4:
        cmd_mp4(conn)
    elif args.detail:
        cmd_detail(conn)
    else:
        cmd_summary(conn)

    conn.close()


if __name__ == "__main__":
    main()
