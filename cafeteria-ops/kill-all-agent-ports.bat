@echo off
setlocal enabledelayedexpansion

rem Convener + all specialist agent ports for cafeteria-ops.
set PORTS=8300 8301 8302 8303 8304 8305 8306 8310

for %%P in (%PORTS%) do (
    set FOUND=0
    for /f "tokens=5" %%p in ('netstat -aon ^| findstr /r /c:":%%P[^0-9].*LISTENING"') do (
        set FOUND=1
        echo Killing process %%p listening on port %%P...
        taskkill /PID %%p /F
    )
    if "!FOUND!"=="0" (
        echo No process found listening on port %%P.
    )
)

endlocal
