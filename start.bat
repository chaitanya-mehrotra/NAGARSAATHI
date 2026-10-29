@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Missing .venv. See docs\DEPLOY_FREE.md & pause & exit /b 1)
findstr /i /c:"<ref>" /c:"<password>" /c:"<pooler-host>" /c:"<secret key>" /c:"<your-app>" .env >nul && (echo Fill in the placeholders in .env first. & notepad .env & pause & exit /b 1)
set PYTHONPATH=%CD%\services\api;%CD%\services\worker
.venv\Scripts\python.exe scripts\launch.py
pause
