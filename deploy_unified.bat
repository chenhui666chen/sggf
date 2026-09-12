@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

echo ==========================================================
echo   Shiguang Studio - Unified Deployment Entry
echo ==========================================================
echo.
echo This launcher delegates to deploy_sync_improved.ps1
echo Remote path is managed by deploy_config.json
echo.

powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%deploy_sync_improved.ps1" %*
exit /b %errorlevel%
