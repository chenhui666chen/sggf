@echo off
setlocal enabledelayedexpansion

echo ==========================================================
echo   Novel Writing Agent - Git Smart Deployment v2.0
echo ==========================================================
echo.

set SERVER_IP=101.132.154.143
set SERVER_USER=root
set LOCAL_PATH=%~dp0
set REMOTE_PATH=/data/apps/novel_writing_agent

cd /d "%LOCAL_PATH%"

echo [Step 1/4] Detecting modified files...
echo.

git status --porcelain > git_changes.txt 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] Not a Git repository, will sync all files
    echo.
    goto :sync_all
)

set /a modified=0
set /a added=0
set /a deleted=0

for /f "tokens=1,2" %%a in (git_changes.txt) do (
    if "%%a"=="M" set /a modified+=1
    if "%%a"=="A" set /a added+=1
    if "%%a"=="D" set /a deleted+=1
    if "%%a"=="??" set /a added+=1
)

echo Git Status:
echo   - Modified files: %modified%
echo   - Added files: %added%
echo   - Deleted files: %deleted%
echo.

if %modified% equ 0 if %added% equ 0 (
    echo [INFO] No changes detected
    set /p force="Force sync all files? (y/n): "
    if /i not "!force!"=="y" (
        echo Deployment cancelled
        del git_changes.txt
        pause
        exit /b 0
    )
)

echo.
echo [Step 2/4] Uploading modified files...
echo.

set /a uploaded=0
set /a failed=0

for /f "tokens=2" %%f in (git_changes.txt) do (
    set "file=%%f"
    set "file=!file:/=\!"
    
    if exist "!file!" (
        echo Uploading: !file!
        
        for %%A in ("!file!") do set "dir=%%~pA"
        
        ssh %SERVER_USER%@%SERVER_IP% "mkdir -p %REMOTE_PATH%/!dir:/=\!"
        scp -o StrictHostKeyChecking=no "!file!" %SERVER_USER%@%SERVER_IP%:%REMOTE_PATH%/!file:/=\!
        
        if !errorlevel! equ 0 (
            set /a uploaded+=1
        ) else (
            echo [WARNING] Upload failed: !file!
            set /a failed+=1
        )
    )
)

del git_changes.txt

echo.
echo Upload completed:
echo   - Success: %uploaded% files
echo   - Failed: %failed% files
echo.

goto :deploy

:sync_all
echo [Step 2/4] Syncing all files...
echo.

echo Creating file list...
dir /s /b backend\app\*.py frontend\src\*.tsx frontend\src\*.ts adapters\*.py agents\*.py pipeline\*.py > all_files.txt

set /a total=0
for /f %%a in (all_files.txt) do set /a total+=1

echo Found %total% files to sync
echo.

set /a uploaded=0
set /a failed=0

for /f "delims=" %%f in (all_files.txt) do (
    set "file=%%f"
    set "file=!file:%LOCAL_PATH%=!"
    
    echo Uploading: !file!
    scp -o StrictHostKeyChecking=no "%%f" %SERVER_USER%@%SERVER_IP%:%REMOTE_PATH%/!file!
    
    if !errorlevel! equ 0 (
        set /a uploaded+=1
    ) else (
        set /a failed+=1
    )
)

del all_files.txt

echo.
echo Upload completed:
echo   - Success: %uploaded% files
echo   - Failed: %failed% files
echo.

:deploy
echo [Step 3/4] Rebuilding and restarting services...
echo.

echo Stopping old containers...
ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose down backend"

echo Rebuilding backend image...
ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose build backend"

if %errorlevel% neq 0 (
    echo [ERROR] Backend image build failed
    pause
    exit /b 1
)

echo Starting services...
ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose up -d backend && docker-compose restart frontend"

echo.
echo [Step 4/4] Validating deployment...
echo.

timeout /t 10 /nobreak >nul

ssh %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && docker-compose ps"

echo.
echo Testing API...
ssh %SERVER_USER%@%SERVER_IP% "curl -s http://localhost:8000/api/v1/health || echo 'API not responding'"

echo.
echo ==========================================================
echo [SUCCESS] Git Smart Deployment Completed!
echo ==========================================================
echo.
echo Access URLs:
echo   HTTP:  http://%SERVER_IP%
echo   HTTPS: https://sggf.net
echo   Domain: https://www.sggf.net
echo.
echo ==========================================================
echo.

pause
