#!/usr/bin/env python3
"""File lifecycle status for UADE material pipeline.

Shows the state of each file across download → organize → transcribe stages.
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "downloads.db"

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


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


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
        marks.append("DL" if True else "  ")
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


def main():
    parser = argparse.ArgumentParser(description="UADE pipeline file status")
    parser.add_argument("--pending", action="store_true",
                        help="Mostrar archivos pendientes de cada etapa")
    parser.add_argument("--mp4", action="store_true",
                        help="Ciclo de vida de grabaciones")
    parser.add_argument("--detail", action="store_true",
                        help="Detalle por team/materia")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    ensure_view(conn)

    if args.pending:
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
