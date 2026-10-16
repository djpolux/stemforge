@echo off
REM Stem Forge — launcher (run install.bat once first)
cd /d %~dp0
set URL=http://127.0.0.1:9005

REM Already running? Just open it instead of failing with "port already in use".
netstat -ano | findstr /R /C:"127\.0\.0\.1:9005 .*LISTENING" >nul
if not errorlevel 1 (
    echo Stem Forge is already running - opening %URL%
    start "" %URL%
    exit /b 0
)

if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat

REM Open the browser as soon as the server answers.
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest '%URL%' -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process '%URL%'; break}catch{Start-Sleep 1}}"

echo Stem Forge running at %URL% - close this window to stop it.
python app_stem.py
if errorlevel 1 pause
