@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bitcoin Miner Studio

rem Prefer the normal python command because diagnostics show it resolves to
rem the working C:\Python314\python.exe on this machine. Do NOT invoke pyw.exe.
set "PYEXE="
for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "PYEXE=%%I"

if not defined PYEXE (
  rem Fallback only when the python command is unavailable. py.exe may still be
  rem used to START bootstrap.py; bootstrap then uses sys.executable directly.
  for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYEXE=%%I"
)

if not defined PYEXE (
  echo ERROR: No working Python interpreter was found.
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

"%PYEXE%" bootstrap.py
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Bitcoin Miner Studio failed to launch. Error code: %ERR%
  echo Run diagnose.bat for details.
  pause
  exit /b %ERR%
)

exit /b 0
