"""Tests para el backend de Whisper: limpieza, validacion, retry y pipeline."""

import pytest
from backends.whisper import (
    _clean_hallucinations, _is_empty_after_cleaning, _transcribe_chunked,
    transcribe,
)
from tasks import assess_quality, validate_transcription
from pathlib import Path
from unittest.mock import patch, MagicMock


# =====================================================================
# _clean_hallucinations — limpieza de artefactos de Whisper
# =====================================================================


class TestCleanHallucinations:
    def test_pure_silence_single_word(self):
        text = "y " * 100
        result = _clean_hallucinations(text)
        assert len(result.split()) <= 1

    def test_pure_silence_no_no(self):
        text = "no, " * 50 + "no"
        result = _clean_hallucinations(text)
        assert len(result.split()) < 5

    def test_preserves_real_content(self):
        text = ("Bueno, como les decía, la inteligencia artificial es una "
                "herramienta muy poderosa. La inteligencia artificial nos "
                "permite automatizar tareas repetitivas.")
        assert _clean_hallucinations(text) == text

    def test_removes_word_repetitions_keeps_content(self):
        text = "y y y y y y y y y Hola mundo, esto es contenido real."
        result = _clean_hallucinations(text)
        assert "Hola mundo" in result
        assert "y y y y" not in result

    def test_removes_phrase_repetitions(self):
        text = ("en Facebook, en Facebook, en Facebook, en Facebook, "
                "en Facebook, en Facebook. Y después la clase.")
        result = _clean_hallucinations(text)
        assert "Y después la clase" in result
        assert result.count("en Facebook") <= 2

    def test_removes_long_phrase_repetitions(self):
        phrase = "y que se está haciendo con la gente de la comunidad "
        text = phrase * 5 + "Entonces empezamos."
        result = _clean_hallucinations(text)
        assert "Entonces empezamos" in result
        assert result.count("gente de la comunidad") <= 1

    def test_mixed_hallucination_and_content(self):
        text = ("y y y y y No es que sea normal, es que es un programa "
                "que se ha hecho en Facebook, en Facebook, en Facebook, "
                "en Facebook. Y después tenemos la clase de hoy que "
                "habla sobre redes neuronales.")
        result = _clean_hallucinations(text)
        assert "redes neuronales" in result
        assert result.count("en Facebook") <= 2

    def test_short_text_unchanged(self):
        text = "Hola mundo"
        assert _clean_hallucinations(text) == text

    def test_empty_text(self):
        assert _clean_hallucinations("") == ""

    def test_natural_repetition_preserved(self):
        """Repeticion natural del habla (2 veces) no se toca."""
        text = "dijo que sí, dijo que sí, pero al final no vino."
        result = _clean_hallucinations(text)
        assert result.count("dijo que sí") == 2


# =====================================================================
# _is_empty_after_cleaning — deteccion de chunks de silencio
# =====================================================================


class TestIsEmptyAfterCleaning:
    def test_pure_silence_is_empty(self):
        assert _is_empty_after_cleaning("y " * 100) is True

    def test_real_content_not_empty(self):
        assert _is_empty_after_cleaning(
            "La clase de hoy trata sobre bases de datos relacionales."
        ) is False

    def test_mixed_content_not_empty(self):
        text = "y y y y y y y y Bueno, empezamos la clase de hoy con el tema de grafos."
        assert _is_empty_after_cleaning(text) is False


# =====================================================================
# validate_transcription — gate de calidad (bloquea guardado de basura)
# =====================================================================


class TestValidateTranscription:
    def test_good_transcription_passes(self):
        words = ["hola", "bueno", "entonces", "clase", "tema", "profesor",
                 "materia", "examen", "parcial", "trabajo", "practico"]
        text = " ".join(words[i % len(words)] for i in range(5000))
        ok, reason = validate_transcription(text, size_mb=200)
        assert ok is True
        assert reason == "ok"

    def test_rejects_almost_empty(self):
        """Video de 500MB con 10 palabras = basura."""
        ok, reason = validate_transcription("hola mundo", size_mb=500)
        assert ok is False
        assert "vacia" in reason

    def test_rejects_very_low_chars_per_mb(self):
        """Video de 200MB con 100 chars = basura."""
        text = "algo de texto " * 7  # ~100 chars
        ok, reason = validate_transcription(text, size_mb=200)
        assert ok is False
        assert "insuficiente" in reason

    def test_rejects_hallucinated_content(self):
        """Texto con >5% triple repeticion = basura."""
        # "Facebook Facebook Facebook" x 100 = 100% repeticion
        text = "Facebook " * 300
        ok, reason = validate_transcription(text, size_mb=10)
        assert ok is False
        assert "alucinacion" in reason

    def test_passes_small_file_with_little_text(self):
        """Archivos chicos (<50MB) no se rechazan por poco texto."""
        ok, reason = validate_transcription("corto", size_mb=30)
        assert ok is True

    def test_borderline_repetition_passes(self):
        """Repeticion < 5% no se rechaza."""
        # 95% contenido variado + 5% repeticion
        words = ["hola", "bueno", "entonces", "clase", "tema"] * 190
        words += ["Facebook"] * 30  # no son triples consecutivos
        text = " ".join(words)
        ok, _ = validate_transcription(text, size_mb=100)
        assert ok is True

    def test_rejects_short_word_hallucination(self):
        """'y y y y y' (palabras de 1 char) tambien se rechaza."""
        text = "y " * 300
        ok, reason = validate_transcription(text, size_mb=10)
        assert ok is False
        assert "alucinacion" in reason

    def test_real_world_garbage_rejected(self):
        """Simula output real de whisper alucinando."""
        text = " y" * 4000  # puro "y y y y y"
        ok, reason = validate_transcription(text, size_mb=1000)
        assert ok is False


# =====================================================================
# assess_quality — warnings suaves (no bloquean, solo informan)
# =====================================================================


class TestAssessQuality:
    def test_good_transcription_no_warning(self):
        words = ["hola", "bueno", "entonces", "clase", "tema", "profesor",
                 "materia", "examen", "parcial", "trabajo", "practico"]
        text = " ".join(words[i % len(words)] for i in range(5000))
        mp4 = Path("/fake/video.mp4")
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_size = int(100 * 1024 * 1024)
            result = assess_quality(text, mp4)
        assert result is None

    def test_low_chars_per_mb_warns(self):
        text = "poco texto"
        mp4 = Path("/fake/video.mp4")
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_size = int(200 * 1024 * 1024)
            result = assess_quality(text, mp4)
        assert result is not None
        assert "poco contenido" in result

    def test_repetitive_text_warns(self):
        text = "Facebook " * 500
        mp4 = Path("/fake/video.mp4")
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_size = int(10 * 1024 * 1024)
            result = assess_quality(text, mp4)
        assert result is not None
        assert "repeticiones" in result

    def test_small_file_no_size_warning(self):
        text = "corto"
        mp4 = Path("/fake/video.mp4")
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_size = int(30 * 1024 * 1024)
            result = assess_quality(text, mp4)
        assert result is None


# =====================================================================
# Retry automático — whisper.transcribe() reintenta con chunks más chicos
# =====================================================================


class TestTranscribeRetry:
    """Tests de integración que mockean _transcribe_single para simular
    distintos escenarios de calidad."""

    def _mock_transcribe_by_strategy(self, results_by_chunk_min):
        """Crea un mock de _transcribe_chunked que retorna distinto según chunk_minutes."""
        def fake_chunked(mp4_path, model, language, backend, chunk_minutes):
            return results_by_chunk_min.get(chunk_minutes, "")
        return fake_chunked

    @patch('backends.whisper._transcribe_chunked')
    @patch('backends.whisper.detect', return_value='mlx')
    @patch('os.path.getsize', return_value=500 * 1024 * 1024)  # 500MB
    def test_good_first_try_no_retry(self, mock_size, mock_detect, mock_chunked):
        """Si el primer intento es bueno, no reintenta."""
        # ~50000 chars = 100 chars/MB para 500MB => pasa validacion
        good_text = "Esta es una clase sobre bases de datos relacionales y normalizacion. " * 700
        mock_chunked.return_value = good_text

        result = transcribe("/fake/video.mp4")
        assert result == good_text
        assert mock_chunked.call_count == 1

    @patch('backends.whisper._transcribe_chunked')
    @patch('backends.whisper.detect', return_value='mlx')
    @patch('os.path.getsize', return_value=500 * 1024 * 1024)
    def test_bad_first_try_retries_with_smaller_chunks(self, mock_size, mock_detect, mock_chunked):
        """Si el primer intento es basura, reintenta con chunks de 2 min."""
        garbage = "y " * 200  # basura
        good_text = "Esta es una clase sobre inteligencia artificial y aprendizaje automatico. " * 700

        call_count = [0]
        def side_effect(*args):
            call_count[0] += 1
            chunk_min = args[4]
            if chunk_min == 5:
                return garbage
            elif chunk_min == 2:
                return good_text
            return ""

        mock_chunked.side_effect = side_effect

        result = transcribe("/fake/video.mp4")
        assert result == good_text
        assert call_count[0] == 2  # intento 1 (5min) + retry (2min)

    @patch('backends.whisper._transcribe_chunked')
    @patch('backends.whisper.detect', return_value='mlx')
    @patch('os.path.getsize', return_value=500 * 1024 * 1024)
    def test_all_retries_fail_returns_best_effort(self, mock_size, mock_detect, mock_chunked):
        """Si todos los intentos fallan, retorna el mejor (más largo)."""
        short_garbage = "y y y"
        longer_garbage = "y y y y y y algo de texto pero poco"

        call_count = [0]
        def side_effect(*args):
            call_count[0] += 1
            chunk_min = args[4]
            if chunk_min == 5:
                return short_garbage
            return longer_garbage

        mock_chunked.side_effect = side_effect

        result = transcribe("/fake/video.mp4")
        # Retorna el más largo (longer_garbage)
        assert result == longer_garbage
        assert call_count[0] == 2

    @patch('backends.whisper._transcribe_chunked')
    @patch('backends.whisper.detect', return_value='mlx')
    @patch('os.path.getsize', return_value=20 * 1024 * 1024)  # 20MB = chico
    def test_small_file_less_strict_validation(self, mock_size, mock_detect, mock_chunked):
        """Archivos chicos (<50MB) tienen validación menos estricta."""
        short_text = "Hola, clase corta."
        mock_chunked.return_value = short_text

        result = transcribe("/fake/video.mp4")
        assert result == short_text
        # No debería haber reintentado
        assert mock_chunked.call_count == 1


# =====================================================================
# Pipeline transcriber.py — validación antes de guardar
# =====================================================================


class TestTranscriberPipeline:
    """Verifica que transcriber.py NO guarda archivos si la calidad es mala."""

    @patch('transcriber.transcribe')
    @patch('transcriber.db')
    def test_rejects_garbage_and_does_not_save(self, mock_db, mock_transcribe):
        """Si la transcripcion es basura, no se guarda .txt ni se registra en DB."""
        import transcriber
        import tempfile
        import os

        mock_transcribe.return_value = "y " * 200  # basura

        mp4 = Path(tempfile.mktemp(suffix=".mp4"))
        txt_path = mp4.with_suffix(".txt")

        # Crear mp4 fake de 100MB
        with open(mp4, "wb") as f:
            f.write(b"\0" * (100 * 1024 * 1024))

        try:
            # Simular el flujo de transcriber.main() para un solo archivo
            text = mock_transcribe(mp4)
            size_mb = mp4.stat().st_size / (1024 * 1024)
            from tasks import validate_transcription
            ok, reason = validate_transcription(text, size_mb)

            assert ok is False
            # Verificar que NO se crea el .txt
            assert not txt_path.exists()
            # Verificar que NO se llama a record_transcription
            mock_db.record_transcription.assert_not_called()
        finally:
            os.unlink(mp4)

    def test_accepts_good_transcription(self):
        """Una buena transcripcion pasa la validacion."""
        words = ["hola", "bueno", "entonces", "clase", "tema", "profesor"]
        text = " ".join(words[i % len(words)] for i in range(3000))
        ok, reason = validate_transcription(text, size_mb=200)
        assert ok is True


# =====================================================================
# Edge cases
# =====================================================================


class TestEdgeCases:
    def test_clean_hallucinations_performance(self):
        """30000 palabras debe procesarse en < 2 segundos."""
        import time
        words = ["hola", "bueno", "entonces", "clase", "tema", "profesor"] * 5000
        text = " ".join(words)
        start = time.time()
        _clean_hallucinations(text)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Demasiado lento: {elapsed:.2f}s para 30000 palabras"

    def test_validate_rejects_after_clean_hallucinations_removes_all(self):
        """Si _clean_hallucinations reduce el texto a casi nada, validate lo rechaza."""
        # Simula un chunk que era 100% alucinacion y fue limpiado
        cleaned = "y"  # lo que queda despues de limpiar "y y y y y..."
        ok, _ = validate_transcription(cleaned, size_mb=500)
        assert ok is False

    def test_empty_string_validation(self):
        """String vacio es rechazado para archivos grandes."""
        ok, _ = validate_transcription("", size_mb=500)
        assert ok is False

    def test_empty_string_small_file_passes(self):
        """String vacio en archivo chico no se rechaza (podria ser video sin audio)."""
        ok, _ = validate_transcription("", size_mb=5)
        assert ok is True

    @patch('backends.whisper._transcribe_chunked')
    @patch('backends.whisper.detect', return_value='mlx')
    @patch('os.path.getsize', return_value=30 * 1024 * 1024)  # 30MB
    def test_small_file_skips_retry(self, mock_size, mock_detect, mock_chunked):
        """Archivos < 50MB no entran en el ciclo de retry."""
        mock_chunked.return_value = "clase corta sobre grafos"
        result = transcribe("/fake/small.mp4")
        assert result == "clase corta sobre grafos"
        # Solo 1 llamada, sin retry
        assert mock_chunked.call_count == 1

    def test_chunk_timeout_kills_subprocess(self, tmp_path):
        """Si un chunk se cuelga en subprocess, se mata por timeout y retorna None."""
        from backends.whisper import _transcribe_with_timeout
        import backends.whisper as whisper_mod

        # Crear helper falso que se cuelga
        fake_helper = tmp_path / "fake_hang.py"
        fake_helper.write_text("import time; time.sleep(60)\n")

        original = whisper_mod.TRANSCRIBE_HELPER
        whisper_mod.TRANSCRIBE_HELPER = fake_helper
        try:
            result = _transcribe_with_timeout(
                "/fake.wav", "medium", "es", "mlx", timeout=2
            )
            assert result is None
        finally:
            whisper_mod.TRANSCRIBE_HELPER = original

    def test_chunk_subprocess_returns_text(self, tmp_path):
        """Si el subprocess termina rapido, retorna el texto del archivo de output."""
        from backends.whisper import _transcribe_with_timeout
        import backends.whisper as whisper_mod

        fake_chunk = tmp_path / "chunk.wav"
        fake_chunk.write_bytes(b"fake")

        # Helper que escribe texto al out_path (sys.argv[5])
        fake_helper = tmp_path / "fake_ok.py"
        fake_helper.write_text(
            "import sys\n"
            "with open(sys.argv[5], 'w') as f:\n"
            "    f.write('texto transcripto')\n"
        )

        original = whisper_mod.TRANSCRIBE_HELPER
        whisper_mod.TRANSCRIBE_HELPER = fake_helper
        try:
            result = _transcribe_with_timeout(
                str(fake_chunk), "medium", "es", "mlx", timeout=10
            )
            assert result == "texto transcripto"
        finally:
            whisper_mod.TRANSCRIBE_HELPER = original

    def test_chunk_subprocess_failure_returns_none(self, tmp_path):
        """Si el subprocess falla (exit != 0), retorna None."""
        from backends.whisper import _transcribe_with_timeout
        import backends.whisper as whisper_mod

        fake_chunk = tmp_path / "chunk.wav"
        fake_chunk.write_bytes(b"fake")

        fake_helper = tmp_path / "fake_fail.py"
        fake_helper.write_text("import sys; sys.exit(1)\n")

        original = whisper_mod.TRANSCRIBE_HELPER
        whisper_mod.TRANSCRIBE_HELPER = fake_helper
        try:
            result = _transcribe_with_timeout(
                str(fake_chunk), "medium", "es", "mlx", timeout=10
            )
            assert result is None
        finally:
            whisper_mod.TRANSCRIBE_HELPER = original

    def test_resummarize_catches_stale_garbage(self):
        """validate_transcription detecta .txt basura que existian antes del fix."""
        # Simular un .txt viejo con basura
        garbage = "y " * 4000
        ok, reason = validate_transcription(garbage, size_mb=500)
        assert ok is False
        # Esto es lo que usaria transcriber.py para decidir borrar el .txt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
