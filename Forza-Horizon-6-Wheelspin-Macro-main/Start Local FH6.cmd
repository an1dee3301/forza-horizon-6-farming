@echo off
cd /d "%~dp0"
if not exist "..\.venv\Scripts\pythonw.exe" (
  echo Run Setup FH6 Auto.cmd in the parent folder first.
  pause
  exit /b 1
)
if exist "%ProgramFiles%\AutoHotkey\v2\AutoHotkey64.exe" (
  start "" "%ProgramFiles%\AutoHotkey\v2\AutoHotkey64.exe" "%~dp0Main.ahk"
  exit /b
)
echo Install AutoHotkey v2, then open Main.ahk.
pause
exit /b 1
