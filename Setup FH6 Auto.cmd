@echo off
cd /d "%~dp0"
echo Setting up FH6 Auto in its own Python environment...
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo Install Python 3.10 or newer for Windows, then run this setup again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-gui.txt
if errorlevel 1 (
  echo Setup failed. Please keep this window open and share the error.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --no-deps -r requirements-window-capture.txt
if errorlevel 1 (
  echo Game-window capture setup failed. Please keep this window open and share the error.
  pause
  exit /b 1
)
echo Setup complete. Opening the dashboard.
start "" ".venv\Scripts\pythonw.exe" "FH6 Auto.pyw"
