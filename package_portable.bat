@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VERSION=2.0.2"
set "OUT=%~dp0dist"
set "STAGE=%TEMP%\BitcoinMinerStudio-v%VERSION%-portable"

if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" >nul 2>nul
if errorlevel 1 (
  echo ERROR: Could not create staging directory.
  exit /b 1
)

echo Creating clean portable source release...
robocopy "%~dp0" "%STAGE%" /E /XD "__pycache__" ".git" "dist" /XF "startup-error.log" "startup-bridge.log" "*.pyc" >nul
if errorlevel 8 (
  echo ERROR: robocopy failed.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -LiteralPath '%STAGE%' -DestinationPath '%OUT%\BitcoinMinerStudio-v%VERSION%-portable.zip' -Force"
if errorlevel 1 (
  echo ERROR: Could not create ZIP.
  exit /b 1
)

rmdir /s /q "%STAGE%"
echo.
echo Created:
echo %OUT%\BitcoinMinerStudio-v%VERSION%-portable.zip
exit /b 0
