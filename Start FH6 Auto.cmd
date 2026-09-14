@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "FH6 Auto.pyw"
  exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
  py "FH6 Auto.pyw"
) else (
  python "FH6 Auto.pyw"
)
if errorlevel 1 pause
