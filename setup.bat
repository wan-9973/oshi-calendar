@echo off
rem === Oshi Calendar setup (Windows) ===
cd /d "%~dp0"

rem --- Guard: Windows MAX_PATH. Deep folders break venv creation. ---
call :strlen HERELEN "%CD%"
if %HERELEN% GTR 120 (
    echo [ERROR] Folder path is too long for Windows ^(%HERELEN% chars^).
    echo         Please copy the whole "oshi-calendar" folder to a short
    echo         location such as C:\oshi-calendar and run setup.bat there.
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+ from
    echo         https://www.python.org/downloads/
    echo         and check "Add python.exe to PATH", then run this again.
    pause
    exit /b 1
)

echo [1/3] Creating virtual env...
if not exist .venv (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed. See message above.
        pause
        exit /b 1
    )
)

echo [2/3] Installing libraries...
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. Check network and try again.
    pause
    exit /b 1
)

echo [3/3] Preparing config files...
if not exist .env copy .env.example .env >nul
if not exist data mkdir data
if not exist logs mkdir logs

echo.
echo ============================================================
echo  Setup complete. Next steps:
echo    1. Open .env in Notepad and fill in the 3 Rakuten IDs
echo       and OPERATOR_NAME, then save.
echo    2. Double-click start.bat to launch the server.
echo ============================================================
pause
exit /b 0

:strlen  <resultVar> <string>
setlocal enabledelayedexpansion
set "s=%~2#"
set "len=0"
for %%P in (4096 2048 1024 512 256 128 64 32 16 8 4 2 1) do (
    if "!s:~%%P,1!" NEQ "" (
        set /a "len+=%%P"
        set "s=!s:~%%P!"
    )
)
endlocal & set "%~1=%len%"
exit /b
