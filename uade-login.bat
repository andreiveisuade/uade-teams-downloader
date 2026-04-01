@echo off
REM Login en Teams — abre un browser para autenticarse.
REM La sesion se guarda y dura ~30 dias.

cd /d "%~dp0"
call .venv\Scripts\activate.bat

echo.
echo   Abriendo browser para login en Teams...
echo   Logueate con tu cuenta de UADE.
echo   Cuando veas el panel de Teams, volve aca.
echo.

python downloader.py --visible
pause
