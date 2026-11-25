@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or 3.12 and enable Add Python to PATH.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe python -m venv .venv
if errorlevel 1 goto failed
if not exist .venv\installed.flag (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
  echo installed>.venv\installed.flag
)
.venv\Scripts\python.exe run.py
pause
exit /b
:failed
echo Setup failed. Check internet connection and Python version.
pause
exit /b 1
