@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bitcoin Miner Studio Diagnostics
if exist "%~dp0BitcoinMinerStudio.exe" goto native
call "%~dp0select_python.bat"
if not defined PYEXE (
  echo ERROR: No supported Python 3.11+ interpreter was found.
  echo Use BitcoinMinerStudio.exe from the complete Windows release ZIP.
  pause
  exit /b 1
)
echo Working Python selected by launcher:
echo %PYEXE%
echo.
"%PYEXE%" -E bootstrap.py --diagnose --console
set "ERR=%ERRORLEVEL%"
echo.
echo Exit code: %ERR%
if exist startup-error.log (
  echo.
  echo === startup-error.log ===
  type startup-error.log
)
pause
exit /b %ERR%

:native
if not exist "%~dp0_runtime\python.exe" (
  echo ERROR: Embedded Python is missing. Extract the complete Windows ZIP.
  pause
  exit /b 1
)
"%~dp0_runtime\python.exe" -X utf8 bootstrap.py --diagnose
set "ERR=%ERRORLEVEL%"
pause
exit /b %ERR%
