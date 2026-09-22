@echo off
rem Run mode_probe from a plain cmd window. See README.txt before using it:
rem this arms and disarms a real alarm, and one step sends a wrong PIN.
setlocal

cd /d "%~dp0"

if "%~1"=="" (
    set /p ACCOUNT="SmartHomeSec account (e-mail): "
) else (
    set "ACCOUNT=%~1"
    shift
)

if "%ACCOUNT%"=="" (
    echo No account given - nothing to do.
    goto :done
)

py mode_probe.py --user "%ACCOUNT%" %1 %2 %3 %4 %5
if errorlevel 1 (
    echo.
    echo mode_probe exited with an error. If it stopped partway, CHECK YOUR PANEL.
)

:done
echo.
pause
endlocal
