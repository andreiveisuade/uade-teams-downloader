@echo off
REM Pipeline completo: download -> organize -> transcribe+resumir (Windows)
REM Lanza el script PowerShell que hace todo el trabajo.

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0run-pipeline.ps1"
pause
