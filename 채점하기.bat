@echo off
cd /d "%~dp0"
if not exist "private\paddle-env\Scripts\pythonw.exe" (
  echo Python environment was not found.
  echo Check private\paddle-env\Scripts\pythonw.exe in this folder.
  pause
  exit /b 1
)
start "" "%~dp0private\paddle-env\Scripts\pythonw.exe" "%~dp0app\egw4_app.py"
