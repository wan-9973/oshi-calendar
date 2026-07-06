@echo off
rem === Oshi Calendar server (Windows) ===
rem R1: keep ONE process (do not add --workers) to keep rate limiting unified.
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo [ERROR] Run setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
start "" http://localhost:8000/
python -m uvicorn src.web.app:app --host 127.0.0.1 --port 8000
pause
