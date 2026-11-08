@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  rem The window does not need a terminal. This console closes immediately.
  start "" wscript //nologo "%~dp0launch-gui.vbs"
  exit /b 0
)
where py >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.10 or newer from https://www.python.org/downloads/
  echo During setup, check "Add python.exe to PATH".
  pause
  exit /b 1
)
py -3 -m discord_archiver %*
endlocal
