@echo off
rem Run event_probe from a plain cmd window. Read-only: it logs in once and
rem reads the event log. See README.txt.
rem
rem Start it as  .\run.cmd  - on a machine with NoDefaultCurrentDirectoryInExePath
rem set, a bare  run.cmd  is "not recognized" even in its own folder.
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

py event_probe.py --user "%ACCOUNT%" --out result.txt --raw raw.out %1 %2 %3 %4 %5

:done
echo.
pause
endlocal
