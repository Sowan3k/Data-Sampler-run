@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11, 3.12 or 3.13 from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe python -m venv .venv
if errorlevel 1 goto failed
rem Reinstall whenever requirements.txt changes (for example tzdata, added in 0.3.1).
set NEEDINSTALL=0
if not exist .venv\installed-requirements.txt set NEEDINSTALL=1
if exist .venv\installed-requirements.txt (
  fc /b requirements.txt .venv\installed-requirements.txt >nul 2>nul
  if errorlevel 1 set NEEDINSTALL=1
)
if "%NEEDINSTALL%"=="1" (
  echo Installing or updating dependencies. This needs an internet connection.
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
  copy /y requirements.txt .venv\installed-requirements.txt >nul
)
.venv\Scripts\python.exe run.py
pause
exit /b
:failed
echo Setup failed. Check your internet connection and Python version, then run this file again.
pause
exit /b 1
