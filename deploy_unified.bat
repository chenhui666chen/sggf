@echo off
setlocal enabledelayedexpansion

echo.
echo ==========================================================
echo     Novel Writing Agent - Unified Deployment v3.0
echo     Smart Detection - Full Sync - Auto Build - Validation
echo ==========================================================
echo.

set SERVER_IP=101.132.154.143
set SERVER_USER=root
set LOCAL_PATH=%~dp0
set REMOTE_PATH=/root/novel_writing_agent
set TIMESTAMP=%date:~0,10%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set LOG_FILE=deploy_%TIMESTAMP%.log

cd /d "%LOCAL_PATH%"

echo Log file: %LOG_FILE%
echo.

echo ==========================================================
echo [Step 1/6] Environment Check
echo ==========================================================
echo.

echo Checking required tools...
where scp >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] scp command not found, please install OpenSSH
    pause
    exit /b 1
)

where ssh >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] ssh command not found, please install OpenSSH
    pause
    exit /b 1
)

echo [OK] Environment check passed
echo.

echo ==========================================================
echo [Step 2/6] File Scanning
echo ==========================================================
echo.

set /a total_files=0
set /a backend_count=0
set /a frontend_count=0
set /a other_count=0

echo Scanning backend files...
if exist backend\app (
    for /r backend\app %%f in (*.py) do (
        set /a backend_count+=1
        set /a total_files+=1
    )
)
echo   Backend Python files: %backend_count%

echo Scanning frontend files...
if exist frontend\src (
    for /r frontend\src %%f in (*.tsx *.ts) do (
        set /a frontend_count+=1
        set /a total_files+=1
    )
)
echo   Frontend TypeScript files: %frontend_count%

echo Scanning other files...
if exist adapters (
    for /r adapters %%f in (*.py) do set /a other_count+=1
    for /r adapters %%f in (*.py) do set /a total_files+=1
)
if exist agents (
    for /r agents %%f in (*.py) do set /a other_count+=1
    for /r agents %%f in (*.py) do set /a total_files+=1
)
if exist pipeline (
    for /r pipeline %%f in (*.py) do set /a other_count+=1
    for /r pipeline %%f in (*.py) do set /a total_files+=1
)
if exist shared (
    for /r shared %%f in (*.py) do set /a other_count+=1
    for /r shared %%f in (*.py) do set /a total_files+=1
)
echo   Other files: %other_count%

echo.
echo Total: %total_files% files
echo.

set /p choice="Continue deployment? (y/n): "
if /i not "%choice%"=="y" (
    echo Deployment cancelled
    pause
    exit /b 0
)

echo.
echo ==========================================================
echo [Step 3/6] Creating Sync List
echo ==========================================================
echo.

set SYNC_LIST=sync_list_%TIMESTAMP%.txt
if exist %SYNC_LIST% del %SYNC_LIST%

echo Generating sync list...

if exist backend\app (
    for /r backend\app %%f in (*.py *.json) do (
        set "file=%%f"
        set "file=!file:%LOCAL_PATH%=!"
        echo !file!>> %SYNC_LIST%
    )
)

if exist frontend\src (
    for /r frontend\src %%f in (*.tsx *.ts *.css) do (
        set "file=%%f"
        set "file=!file:%LOCAL_PATH%=!"
        echo !file!>> %SYNC_LIST%
    )
)

if exist adapters (
    for /r adapters %%f in (*.py) do (
        set "file=%%f"
        set "file=!file:%LOCAL_PATH%=!"
        echo !file!>> %SYNC_LIST%
    )
)
if exist agents (
    for /r agents %%f in (*.py) do (
        set "file=%%f"
        set "file=!file:%LOCAL_PATH%=!"
        echo !file!>> %SYNC_LIST%
    )
)
if exist pipeline (
    for /r pipeline %%f in (*.py) do (
        set "file=%%f"
        set "file=!file:%LOCAL_PATH%=!"
        echo !file!>> %SYNC_LIST%
    )
)
if exist shared (
    for /r shared %%f in (*.py) do (
        set "file=%%f"
        set "file=!file:%LOCAL_PATH%=!"
        echo !file!>> %SYNC_LIST%
    )
)

for %%f in (docker-compose.yml nginx-prod.conf .env.example deploy.sh) do (
    if exist %%f echo %%f>> %SYNC_LIST%
)

set /a list_count=0
for /f %%a in (%SYNC_LIST%) do set /a list_count+=1

echo [OK] Sync list created: %list_count% files
echo.

echo ==========================================================
echo [Step 4/6] File Synchronization
echo ==========================================================
echo.

set /a uploaded=0
set /a failed=0
set /a progress=0

echo Starting file upload...
echo.

for /f "delims=" %%f in (%SYNC_LIST%) do (
    set "file=%%f"
    set "file=!file:~1!"
    
    set /a progress+=1
    set /a percent=progress*100/list_count
    
    echo [!progress!/%list_count%] Uploading: !file!
    
    set "local_file=%LOCAL_PATH%!file!"
    set "remote_file=%SERVER_USER%@%SERVER_IP%:%REMOTE_PATH%!file!"
    
    scp -o StrictHostKeyChecking=no -o ConnectTimeout=10 "!local_file!" "!remote_file!" >> %LOG_FILE% 2>&1
    
    if !errorlevel! equ 0 (
        set /a uploaded+=1
        echo     [OK] Success
    ) else (
        set /a failed+=1
        echo     [FAIL] Failed >> %LOG_FILE%
        echo     [FAIL] Failed
    )
)

echo.
echo ----------------------------------------------------------
echo Sync Results:
echo   Success: %uploaded% files
echo   Failed: %failed% files
echo ----------------------------------------------------------
echo.

if %failed% gtr 0 (
    echo [WARNING] %failed% files failed to upload
    echo Check log file for details: %LOG_FILE%
    echo.
    set /p continue="Continue deployment? (y/n): "
    if /i not "!continue!"=="y" (
        echo Deployment cancelled
        pause
        exit /b 1
    )
)

echo.
echo ==========================================================
echo [Step 5/6] Service Build and Restart
echo ==========================================================
echo.

echo [5.1] Stopping old containers...
ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose down backend" >> %LOG_FILE% 2>&1
echo [OK] Old containers stopped
echo.

echo [5.2] Rebuilding backend image (estimated 3-5 minutes)...
echo       This may take some time, please wait...
echo.

ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose build backend" >> %LOG_FILE% 2>&1

if %errorlevel% neq 0 (
    echo [FAIL] Backend image build failed
    echo Check log file for details: %LOG_FILE%
    pause
    exit /b 1
)

echo [OK] Backend image build completed
echo.

echo [5.3] Starting backend service...
ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose up -d backend" >> %LOG_FILE% 2>&1

if %errorlevel% neq 0 (
    echo [FAIL] Backend service start failed
    pause
    exit /b 1
)

echo [OK] Backend service started
echo.

echo [5.4] Restarting frontend service...
ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose restart frontend" >> %LOG_FILE% 2>&1
echo [OK] Frontend service restarted
echo.

echo ==========================================================
echo [Step 6/6] Deployment Validation
echo ==========================================================
echo.

echo [6.1] Waiting for services to start (15 seconds)...
timeout /t 15 /nobreak >nul
echo [OK] Wait completed
echo.

echo [6.2] Checking container status...
echo.
ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose ps"
echo.

echo [6.3] Testing backend API...
echo.
set API_RESULT=
for /f "delims=" %%a in ('ssh %SERVER_USER%@%SERVER_IP% "curl -s http://localhost:8000/api/v1/health 2>&1"') do set API_RESULT=%%a

if defined API_RESULT (
    if "!API_RESULT!"=="OK" (
        echo [OK] API response normal: !API_RESULT!
    ) else (
        echo [WARN] API response: !API_RESULT!
    )
) else (
    echo [FAIL] API not responding
)
echo.

echo.
echo ==========================================================
echo              Deployment Completed Successfully!
echo ==========================================================
echo.
echo ----------------------------------------------------------
echo Deployment Statistics:
echo ----------------------------------------------------------
echo   Scanned files: %total_files%
echo   Synced files: %uploaded%
echo   Failed files: %failed%
echo   Log file: %LOG_FILE%
echo.
echo ----------------------------------------------------------
echo Access URLs:
echo ----------------------------------------------------------
echo   HTTP:  http://%SERVER_IP%
echo   HTTPS: https://sggf.net
echo   Domain: https://www.sggf.net
echo.
echo ----------------------------------------------------------
echo Next Steps:
echo ----------------------------------------------------------
echo   1. Visit website to test new features
echo   2. Check logs for any errors
echo   3. If issues, check log: %LOG_FILE%
echo.
echo ==========================================================
echo.

del %SYNC_LIST% 2>nul
pause
