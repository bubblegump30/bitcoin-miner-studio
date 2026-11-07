@echo off
rem Discovery only: execute the selected absolute python.exe/pythonw.exe later.
set "PYEXE="
call :probe py -3.12
if defined PYEXE exit /b 0
call :probe py -3
if defined PYEXE exit /b 0
call :probe python
if defined PYEXE exit /b 0
exit /b 1

:probe
for /f "usebackq delims=" %%I in (`%* -E -c "import sys; print(sys.executable) if sys.version_info[:2] >= (3,11) else None" 2^>nul`) do set "PYEXE=%%I"
exit /b 0
