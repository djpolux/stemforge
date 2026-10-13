@echo off
REM Stem Forge — launcher (run install.bat once first)
cd /d %~dp0
call .venv\Scripts\activate
python app_stem.py