@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bitcoin Miner Studio Diagnostics

set "PYEXE="
for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "PYEXE=%%I"
if not defined PYEXE (
  for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYEXE=%%I"
)

if not defined PYEXE (
  echo ERROR: No working Python interpreter was found.
  pause
  exit /b 1
)

echo Working Python selected by launcher:
echo %PYEXE%
echo.

"%PYEXE%" bootstrap.py --diagnose --console
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
