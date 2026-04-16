@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

echo ==========================================================
echo   Novel Writing Agent - Unified Deployment Entry
echo ==========================================================
echo.
echo This launcher delegates to deploy_sync_improved.ps1
echo Remote path is managed by deploy_config.json
echo.

powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%deploy_sync_improved.ps1" %*
exit /b %errorlevel%
