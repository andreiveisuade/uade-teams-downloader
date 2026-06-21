"""Tests para el sistema de trackeo: DB, health check, recovery."""

import os
import sqlite3
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

import db


@pytest.fixture
def tmp_db(tmp_path):
    """Crea una DB temporal para tests."""
    db_path = tmp_path / "test.db"
    with patch.object(db.config, 'DB_PATH', db_path):
        conn = db.get_connection()
        yield conn
        conn.close()


# =====================================================================
# Two-phase downloads
# =====================================================================


class TestTwoPhaseDownloads:
    def test_pending_then_complete(self, tmp_db):
        db.record_download_pending(tmp_db, "k1", "team", "path", "file.pdf", 100)
        # Pending no cuenta como descargado
        assert db.has_download(tmp_db, "k1") is False
        assert db.count_downloads(tmp_db) == 0

        db.complete_download(tmp_db, "k1", "/tmp/file.pdf")
        assert db.has_download(tmp_db, "k1") is True
        assert db.count_downloads(tmp_db) == 1

    def test_pending_then_fail(self, tmp_db):
        db.record_download_pending(tmp_db, "k1", "team", "path", "file.pdf", 100)
        db.delete_download(tmp_db, "k1")
        assert db.has_download(tmp_db, "k1") is False
        assert db.count_downloads(tmp_db) == 0

    def test_cleanup_incomplete(self, tmp_db):
        # Simular crash: 2 pending, 1 complete
        db.record_download_pending(tmp_db, "k1", "t", "p", "f1.pdf", 100)
        db.record_download_pending(tmp_db, "k2", "t", "p", "f2.pdf", 200)
        db.record_download(tmp_db, "k3", "t", "p", "f3.pdf", 300, "/tmp/f3.pdf")

        cleaned = db.cleanup_incomplete_downloads(tmp_db)
        assert cleaned == 2
        assert db.has_download(tmp_db, "k1") is False
        assert db.has_download(tmp_db, "k2") is False
        assert db.has_download(tmp_db, "k3") is True

    def test_has_download_ignores_pending(self, tmp_db):
        db.record_download_pending(tmp_db, "k1", "t", "p", "f.pdf", 100)
        assert db.has_download(tmp_db, "k1") is False


# =====================================================================
# Health check helpers
# =====================================================================


class TestHealthCheckHelpers:
    def test_all_downloads(self, tmp_db):
        db.record_download(tmp_db, "k1", "t", "p", "f.pdf", 100, "/tmp/f.pdf")
        rows = db.all_downloads(tmp_db)
        assert len(rows) == 1
        assert rows[0][0] == "k1"
        assert rows[0][2] == "complete"

    def test_all_organized(self, tmp_db):
        db.record_organized(tmp_db, "/src/f.pdf", "/dst/f.pdf", "material")
        rows = db.all_organized(tmp_db)
        assert len(rows) == 1

    def test_all_transcriptions(self, tmp_db):
        db.record_transcription(tmp_db, "/v.mp4", "/v.txt", "/v_resumen.md")
        rows = db.all_transcriptions(tmp_db)
        assert len(rows) == 1

    def test_delete_organized(self, tmp_db):
        db.record_organized(tmp_db, "/src/f.pdf", "/dst/f.pdf", "material")
        assert db.is_organized(tmp_db, "/src/f.pdf") is True
        db.delete_organized(tmp_db, "/src/f.pdf")
        assert db.is_organized(tmp_db, "/src/f.pdf") is False

    def test_delete_transcription(self, tmp_db):
        db.record_transcription(tmp_db, "/v.mp4", "/v.txt")
        assert db.is_transcribed(tmp_db, "/v.mp4") is True
        db.delete_transcription(tmp_db, "/v.mp4")
        assert db.is_transcribed(tmp_db, "/v.mp4") is False

    def test_reconcile_reapunta_download_a_organized(self, tmp_db):
        """Tras organizar (mover), el download apunta al dest, no al path viejo."""
        staging = "/teams_dir/Clase 1- Actividad.docx"
        final = "/UADE/Materia/01_Material/Clase 1- Actividad.docx"
        db.record_download(tmp_db, "k1", "t", "p", "Clase 1- Actividad.docx", 100, staging)
        db.record_organized(tmp_db, staging, final, "material")

        n = db.reconcile_downloads_to_organized(tmp_db)

        assert n == 1
        key, local_path, status = db.all_downloads(tmp_db)[0]
        assert local_path == final  # ya no apunta al staging movido

    def test_reconcile_no_toca_downloads_sin_organizar(self, tmp_db):
        """Un download que no fue organizado queda intacto."""
        db.record_download(tmp_db, "k1", "t", "p", "f.pdf", 100, "/teams_dir/f.pdf")
        n = db.reconcile_downloads_to_organized(tmp_db)
        assert n == 0
        assert db.all_downloads(tmp_db)[0][1] == "/teams_dir/f.pdf"


# =====================================================================
# Health check integration (status.py)
# =====================================================================


class TestHealthCheck:
    def test_detects_phantom_download(self, tmp_db, capsys):
        """Download en DB pero archivo no existe en disco."""
        db.record_download(tmp_db, "k1", "t", "p", "f.pdf", 100, "/nonexistent/f.pdf")

        from status import cmd_health
        cmd_health(tmp_db, fix=False)
        out = capsys.readouterr().out
        assert "phantom" in out.lower() or "1" in out

    def test_fix_phantom_download(self, tmp_db, capsys):
        """--fix borra phantom download records."""
        db.record_download(tmp_db, "k1", "t", "p", "f.pdf", 100, "/nonexistent/f.pdf")

        from status import cmd_health
        cmd_health(tmp_db, fix=True)
        assert db.has_download(tmp_db, "k1") is False

    def test_detects_phantom_transcription(self, tmp_db, capsys):
        """Transcription en DB pero .txt no existe."""
        db.record_transcription(tmp_db, "/fake/v.mp4", "/nonexistent/v.txt")

        from status import cmd_health
        cmd_health(tmp_db, fix=False)
        out = capsys.readouterr().out
        assert "phantom" in out.lower()

    def test_fix_phantom_transcription(self, tmp_db):
        """--fix borra phantom transcription."""
        db.record_transcription(tmp_db, "/fake/v.mp4", "/nonexistent/v.txt")

        from status import cmd_health
        cmd_health(tmp_db, fix=True)
        assert db.is_transcribed(tmp_db, "/fake/v.mp4") is False

    def test_clean_db_reports_ok(self, tmp_db, tmp_path, capsys):
        """DB limpia sin issues reporta OK."""
        # Crear archivo real para que no sea phantom
        real_file = tmp_path / "real.pdf"
        real_file.write_text("test")
        db.record_download(tmp_db, "k1", "t", "p", "real.pdf", 4, str(real_file))

        from status import cmd_health
        cmd_health(tmp_db, fix=False)
        out = capsys.readouterr().out
        assert "verificados" in out.lower()

    def test_detects_incomplete_downloads(self, tmp_db, capsys):
        """Detecta downloads con status='downloading'."""
        db.record_download_pending(tmp_db, "k1", "t", "p", "f.pdf", 100)

        from status import cmd_health
        cmd_health(tmp_db, fix=False)
        out = capsys.readouterr().out
        assert "incompleta" in out.lower()


# =====================================================================
# Schema migration
# =====================================================================


class TestSchemaMigration:
    def test_busy_timeout_set(self, tmp_db):
        """Verifica que busy_timeout esta configurado."""
        val = tmp_db.execute("PRAGMA busy_timeout").fetchone()[0]
        assert val == 5000

    def test_status_column_exists(self, tmp_db):
        """Verifica que la columna status existe en downloads."""
        tmp_db.execute("SELECT status FROM downloads LIMIT 1")

    def test_existing_records_default_to_complete(self, tmp_db):
        """Records existentes sin status explicito defaultean a 'complete'."""
        db.record_download(tmp_db, "k1", "t", "p", "f.pdf", 100, "/tmp/f.pdf")
        row = tmp_db.execute(
            "SELECT status FROM downloads WHERE key='k1'"
        ).fetchone()
        assert row[0] == "complete"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
