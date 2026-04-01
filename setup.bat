@echo off
REM Setup de UADE Teams Downloader
REM Doble click en este archivo para configurar el sistema.

cd /d "%~dp0"

REM Intentar encontrar Python
set PYTHON_CMD=

REM Opcion 1: python en PATH
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=python
    goto :found
)

REM Opcion 2: py launcher (se instala con Python aunque no se marque PATH)
py --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=py
    goto :found
)

REM Opcion 3: python3 en PATH
python3 --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=python3
    goto :found
)

REM Opcion 4: buscar en rutas comunes de instalacion
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%P (
        set PYTHON_CMD=%%P
        goto :found
    )
)

REM No se encontro Python
echo.
echo   X No se encontro Python en este equipo.
echo.
echo   Para instalar Python:
echo   1. Ir a https://www.python.org/downloads/
echo   2. Descargar e instalar
echo   3. Reiniciar esta ventana y volver a ejecutar setup.bat
echo.
echo   Nota: si ya lo instalaste y sigue apareciendo este error,
echo   busca "python" en el menu Inicio, click derecho, "Abrir
echo   ubicacion del archivo", y copia esa ruta aca:
echo.
set /p MANUAL_PATH="  Ruta a python.exe (o Enter para salir): "
if "%MANUAL_PATH%"=="" (
    pause
    exit /b 1
)
set PYTHON_CMD=%MANUAL_PATH%

:found
echo.
echo   Python encontrado: %PYTHON_CMD%
echo   Iniciando setup...
echo.
%PYTHON_CMD% setup.py
pause
