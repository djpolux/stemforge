@echo off
REM Stem Forge — one-shot install (Windows, Python 3.10+ and ffmpeg required on PATH)
cd /d %~dp0
py -m venv .venv || exit /b 1
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
if errorlevel 1 (
    echo CUDA torch install failed - falling back to CPU build
    pip install torch
)
pip install demucs fastapi uvicorn numpy
echo.
echo Install complete. Double-click StemForge.bat to launch the app.
pause