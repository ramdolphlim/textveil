@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" desktop\textveil_desktop.py %*
) else (
  python desktop\textveil_desktop.py %*
)
if errorlevel 1 pause
