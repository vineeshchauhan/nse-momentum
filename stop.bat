@echo off
echo Stopping NSE Momentum Trading System...

:: Kill the python process running main.py
taskkill /FI "WINDOWTITLE eq NSE-Trading" /T /F >NUL 2>&1

:: Also find and kill any python process running main.py
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH 2^>NUL') do (
    wmic process where "ProcessId=%%~i" get CommandLine 2>NUL | find "main.py" >NUL
    if not errorlevel 1 (
        taskkill /PID %%~i /F >NUL 2>&1
    )
)

echo NSE Momentum Trading System stopped.
pause
