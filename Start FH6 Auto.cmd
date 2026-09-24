@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run Setup FH6 Auto.cmd once before starting FH6 Auto.
  pause
  exit /b 1
)
if not exist "%ProgramFiles%\AutoHotkey\v2\AutoHotkey64.exe" (
  echo AutoHotkey v2 was not found. Install it and run Setup FH6 Auto.cmd again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 (
  echo FH6 Auto dependencies need repair. Run Setup FH6 Auto.cmd again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\release\smoke_runtime.py
if errorlevel 1 (
  echo FH6 Auto runtime validation failed. Run Setup FH6 Auto.cmd again.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "FH6 Auto.pyw"
endlocal
