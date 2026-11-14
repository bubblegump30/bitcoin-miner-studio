@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bitcoin Miner Studio

rem The packaged application owns its embedded Python and native tray.
if exist "%~dp0BitcoinMinerStudio.exe" (
  start "" /d "%~dp0" "%~dp0BitcoinMinerStudio.exe"
  exit /b 0
)
call "%~dp0select_python.bat"

if not defined PYEXE (
  echo ERROR: No supported Python 3.11+ interpreter was found.
  echo Install Python 3.11+ and make sure python.exe is available.
  pause
  exit /b 1
)

if not exist "%PYEXE%" (
  echo ERROR: Python resolved to a missing executable:
  echo %PYEXE%
  echo.
  echo Run diagnose.bat after repairing your Python installation.
  pause
  exit /b 1
)

"%PYEXE%" -E bootstrap.py
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Bitcoin Miner Studio failed to launch. Error code: %ERR%
  echo Run diagnose.bat for details.
  pause
  exit /b %ERR%
)

exit /b 0
