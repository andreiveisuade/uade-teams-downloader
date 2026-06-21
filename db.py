"""Capa de base de datos unificada para el pipeline.

SQLite con WAL mode. Tablas: downloads, runs, organized, transcriptions.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import config


def get_connection(check_same_thread: bool = True) -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=check_same_thread)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            key         TEXT PRIMARY KEY,
            team_prefix TEXT NOT NULL,
            remote_path TEXT NOT NULL,
            filename    TEXT NOT NULL,
            size        INTEGER NOT NULL,
            local_path  TEXT NOT NULL,
            downloaded_at TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'complete'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            files_downloaded INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS organized (
            source_path TEXT PRIMARY KEY,
            dest_path   TEXT NOT NULL,
            category    TEXT NOT NULL,
            organized_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            mp4_path    TEXT PRIMARY KEY,
            txt_path    TEXT NOT NULL,
            summary_path TEXT,
            transcribed_at TEXT NOT NULL,
            summarized_at TEXT,
            context_hash TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_status (
            task_key TEXT PRIMARY KEY,
            materia  TEXT NOT NULL,
            text     TEXT NOT NULL,
            done_at  TEXT NOT NULL
        )
    """)
    # Migraciones de columnas nuevas
    for col, table, default in [
        ("context_hash", "transcriptions", None),
        ("status", "downloads", "'complete'"),
    ]:
        try:
            conn.execute(f"SELECT {col} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            default_clause = f" DEFAULT {default}" if default else ""
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT{default_clause}")
    conn.commit()


# --- Downloads ---

def has_download(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM downloads WHERE key=? AND status='complete'", (key,)
    ).fetchone() is not None


def record_download(conn: sqlite3.Connection, key: str, team_prefix: str,
                    remote_path: str, filename: str, size: int, local_path: str):
    conn.execute(
        "INSERT OR REPLACE INTO downloads VALUES (?,?,?,?,?,?,?,?)",
        (key, team_prefix, remote_path, filename, size,
         local_path, datetime.now().isoformat(), "complete"),
    )
    conn.commit()


def record_download_pending(conn: sqlite3.Connection, key: str, team_prefix: str,
                            remote_path: str, filename: str, size: int):
    """Reserva un key en la DB antes de descargar. Status='downloading'."""
    conn.execute(
        "INSERT OR REPLACE INTO downloads VALUES (?,?,?,?,?,?,?,?)",
        (key, team_prefix, remote_path, filename, size,
         "", datetime.now().isoformat(), "downloading"),
    )
    conn.commit()


def complete_download(conn: sqlite3.Connection, key: str, local_path: str):
    """Marca una descarga como completada."""
    conn.execute(
        "UPDATE downloads SET local_path=?, downloaded_at=?, status='complete' WHERE key=?",
        (local_path, datetime.now().isoformat(), key),
    )
    conn.commit()


def delete_download(conn: sqlite3.Connection, key: str):
    """Borra un registro de descarga (para limpiar fallidos)."""
    conn.execute("DELETE FROM downloads WHERE key=?", (key,))
    conn.commit()


def cleanup_incomplete_downloads(conn: sqlite3.Connection) -> int:
    """Limpia descargas que quedaron en status='downloading' (crash anterior)."""
    cur = conn.execute("DELETE FROM downloads WHERE status='downloading'")
    conn.commit()
    return cur.rowcount


def count_downloads(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE status='complete'"
    ).fetchone()[0]


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)",
                       (datetime.now().isoformat(),))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, files_downloaded: int):
    conn.execute("UPDATE runs SET finished_at=?, files_downloaded=? WHERE id=?",
                 (datetime.now().isoformat(), files_downloaded, run_id))
    conn.commit()


# --- Organized ---

def is_organized(conn: sqlite3.Connection, source: str) -> bool:
    return conn.execute("SELECT 1 FROM organized WHERE source_path=?", (source,)).fetchone() is not None


def get_organized_dest(conn: sqlite3.Connection, source: str) -> str | None:
    row = conn.execute("SELECT dest_path FROM organized WHERE source_path=?", (source,)).fetchone()
    return row[0] if row else None


def record_organized(conn: sqlite3.Connection, source: str, dest: str, category: str):
    conn.execute("INSERT OR REPLACE INTO organized VALUES (?,?,?,?)",
                 (source, dest, category, datetime.now().isoformat()))
    conn.commit()


def delete_organized(conn: sqlite3.Connection, source: str):
    """Borra un registro de organizacion (phantom record)."""
    conn.execute("DELETE FROM organized WHERE source_path=?", (source,))
    conn.commit()


# --- Transcriptions ---

def is_transcribed(conn: sqlite3.Connection, mp4_path: str) -> bool:
    return conn.execute("SELECT 1 FROM transcriptions WHERE mp4_path=?", (mp4_path,)).fetchone() is not None


def needs_resummarize(conn: sqlite3.Connection, mp4_path: str, current_hash: str) -> bool:
    row = conn.execute(
        "SELECT context_hash, summary_path FROM transcriptions WHERE mp4_path=?",
        (mp4_path,)
    ).fetchone()
    if not row:
        return False
    old_hash, summary_path = row
    if not summary_path:
        return True
    if old_hash != current_hash:
        return True
    return False


def record_transcription(conn: sqlite3.Connection, mp4_path: str, txt_path: str,
                         summary_path: str | None = None,
                         context_hash: str | None = None):
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO transcriptions
           (mp4_path, txt_path, summary_path, transcribed_at, summarized_at, context_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (mp4_path, txt_path, summary_path, now,
         now if summary_path else None, context_hash),
    )
    conn.commit()


def delete_transcription(conn: sqlite3.Connection, mp4_path: str):
    """Borra un registro de transcripcion (phantom record)."""
    conn.execute("DELETE FROM transcriptions WHERE mp4_path=?", (mp4_path,))
    conn.commit()


# --- Health check helpers ---

def all_downloads(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT key, local_path, status FROM downloads"
    ).fetchall()


def all_organized(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT source_path, dest_path FROM organized"
    ).fetchall()


def all_transcriptions(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT mp4_path, txt_path, summary_path FROM transcriptions"
    ).fetchall()


def reconcile_downloads_to_organized(conn: sqlite3.Connection) -> int:
    """Reapunta downloads.local_path a la ubicacion organizada (dest_path).

    El organizer mueve archivos de teams_dir a su carpeta final. Sin esto el
    registro de download queda apuntando al path viejo (ya movido) -> el health
    check lo marca phantom y lo borra -> se re-descarga en la proxima corrida.
    Retorna cuantos registros se reapuntaron.
    """
    cur = conn.execute(
        """UPDATE downloads
           SET local_path = (
               SELECT dest_path FROM organized
               WHERE organized.source_path = downloads.local_path
           )
           WHERE local_path IN (SELECT source_path FROM organized)"""
    )
    conn.commit()
    return cur.rowcount


# --- Task status (radar) ---

def mark_task_done(conn: sqlite3.Connection, task_key: str, materia: str, text: str):
    conn.execute(
        "INSERT OR REPLACE INTO task_status VALUES (?,?,?,?)",
        (task_key, materia, text, datetime.now().isoformat()),
    )
    conn.commit()


def unmark_task_done(conn: sqlite3.Connection, task_key: str):
    conn.execute("DELETE FROM task_status WHERE task_key=?", (task_key,))
    conn.commit()


def done_task_keys(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT task_key FROM task_status").fetchall()}
