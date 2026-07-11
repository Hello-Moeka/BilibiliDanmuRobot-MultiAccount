@echo off
REM --- This file is pure ASCII on purpose: cmd.exe on a GBK system may
REM     misread UTF-8 bytes in a .bat and break command parsing. Keep it
REM     ASCII-only; Chinese banners are printed by run.py instead. ---

cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM 1) Check Python is on PATH
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

REM 2) Install deps only if missing (skips network when already installed)
python -c "import flask, yaml, psutil, requests" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    python -m pip install -r manager\requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed. Check network or install manually.
        pause
        exit /b 1
    )
)

echo.
echo Starting panel... a browser window will open shortly.
echo Close THIS window or press Ctrl+C to stop the server.
echo.

python run.py

echo.
echo Server stopped. Press any key to close this window.
pause >nul
