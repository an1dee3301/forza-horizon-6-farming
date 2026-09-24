@echo off
setlocal
cd /d "%~dp0"
set "AHK=%ProgramFiles%\AutoHotkey\v2\AutoHotkey64.exe"
if not exist "%AHK%" (
  echo AutoHotkey v2 was not found at "%AHK%".
  echo Install AutoHotkey v2 and run this setup again.
  pause
  exit /b 1
)
echo Setting up FH6 Auto with the tested Python 3.12 runtime...
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3.12 -m venv .venv
  ) else (
    echo The Python launcher was not found. Install Python 3.12 for Windows.
    pause
    exit /b 1
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo Python 3.12 could not create the virtual environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
  echo This .venv was created with another Python version. Rename .venv, then run setup again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-lock-win-py312.txt
if errorlevel 1 (
  echo Dependency installation failed. Keep this window open and review the error above.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 (
  echo Installed dependency versions are inconsistent. Setup stopped before launch.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\release\smoke_runtime.py
if errorlevel 1 (
  echo Runtime smoke check failed. Setup stopped before launch.
  pause
  exit /b 1
)
"%AHK%" "%~dp0Forza-Horizon-6-Wheelspin-Macro-main\Main.ahk" --self-test
if errorlevel 1 (
  echo AutoHotkey panel self-test failed. Setup stopped before launch.
  pause
  exit /b 1
)
echo Setup complete. Opening the dashboard.
start "" ".venv\Scripts\pythonw.exe" "FH6 Auto.pyw"
endlocal
