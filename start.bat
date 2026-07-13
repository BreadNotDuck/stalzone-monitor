@echo off
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Virtual environment not found: .venv
    echo Create: python -m venv .venv
    echo Install: .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting STALZONE Monitor...
"%PY%" main.py
if errorlevel 1 (
    echo.
    echo Startup failed. Try: .venv\Scripts\pip install -r requirements.txt
    pause
)
