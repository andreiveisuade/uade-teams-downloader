@echo off
REM Pipeline completo: download → organize → transcribe+resumir (Windows)

cd /d "%~dp0"
call .venv\Scripts\activate.bat

echo.
echo ====================================================
echo   UADE Pipeline — Windows
echo ====================================================

echo.
echo [1/4] Descarga de Teams
python -u downloader.py
if %ERRORLEVEL% EQU 2 (
    echo ! Sesion expirada — correr: python uade-login.py
    echo ! Continuando con material existente...
)

echo.
echo [2/4] Organizacion de archivos
python -u organizer.py

echo.
echo [3/4] Transcripcion + Resumenes
python -u transcriber.py

echo.
echo [4/4] Estado del pipeline
python -u status.py

echo.
echo ====================================================
echo   Pipeline completado
echo ====================================================
pause
