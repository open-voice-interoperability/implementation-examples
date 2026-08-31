@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%reset_and_run_stack.ps1"

if not exist "%PS_SCRIPT%" (
  echo ERROR: Could not find %PS_SCRIPT%
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
exit /b %ERRORLEVEL%
