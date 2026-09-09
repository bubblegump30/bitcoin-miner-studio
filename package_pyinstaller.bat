@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where pyinstaller >nul 2>nul
if errorlevel 1 (
  echo PyInstaller is not installed on this packaging machine.
  echo.
  echo Install it intentionally in your release-build environment, then run
  echo this script again. This script will not install packages automatically.
  exit /b 2
)

python -c "import webview,sys; print('Python:',sys.executable); print('pywebview: OK')" || exit /b 3

if exist "build" rmdir /s /q "build"
if exist "dist\BitcoinMinerStudio" rmdir /s /q "dist\BitcoinMinerStudio"

pyinstaller --noconfirm --clean --windowed ^
  --name "BitcoinMinerStudio" ^
  --icon "assets\BitcoinMinerStudio.ico" ^
  --version-file "windows_version_info.txt" ^
  --add-data "assets;assets" ^
  --add-data "ui;ui" ^
  --add-data "purple_dragon_manifest.json;." ^
  --add-data "release_info.json;." ^
  --collect-all webview ^
  launch.pyw

if errorlevel 1 exit /b 4

echo.
echo Executable build created under dist\BitcoinMinerStudio
echo IMPORTANT: code-sign the executable/installer with your trusted Windows
echo code-signing certificate before public distribution.
exit /b 0
