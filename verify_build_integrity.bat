@echo off
setlocal
cd /d "%~dp0"
echo.
echo Bitcoin Miner Studio - Build Provenance Verification
echo =====================================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py -c "from purple_dragon_security import provenance_report; print(provenance_report())"
) else (
  python -c "from purple_dragon_security import provenance_report; print(provenance_report())"
)
echo.
pause
