@echo off
REM Setup de UADE Teams Downloader
REM Doble click en este archivo para configurar el sistema.

cd /d "%~dp0"

REM Verificar que Python esta instalado
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   X Python no esta instalado o no esta en el PATH.
    echo.
    echo   Para instalar Python:
    echo   1. Ir a https://www.python.org/downloads/
    echo   2. Descargar e instalar
    echo   3. IMPORTANTE: marcar "Add Python to PATH" durante la instalacion
    echo   4. Reiniciar esta ventana y volver a ejecutar setup.bat
    echo.
    pause
    exit /b 1
)

echo.
echo   Iniciando setup...
echo.
python setup.py
pause
