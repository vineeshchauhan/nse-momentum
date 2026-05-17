@echo off
echo Starting NSE Momentum Trading System...

:: Check if already running
tasklist /FI "WINDOWTITLE eq NSE-Trading" 2>NUL | find /I "cmd.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    echo Application is already running.
    pause
    exit /b 1
)

:: Start postgres if not running
echo Checking PostgreSQL...
docker start trading_postgres >NUL 2>&1

:: Start the app in a named window so stop.bat can find it
start "NSE-Trading" cmd /k "cd /d %~dp0 && python main.py"

echo NSE Momentum Trading System started.
echo Close the "NSE-Trading" window or run stop.bat to stop it.
