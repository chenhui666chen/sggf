@echo off
echo ==========================================================
echo   SSH Passwordless Login Setup
echo ==========================================================
echo.

set SERVER_IP=101.132.154.143
set SERVER_USER=root
set SSH_DIR=%USERPROFILE%\.ssh
set KEY_FILE=%SSH_DIR%\id_rsa

echo [Step 1/3] Checking SSH directory...
if not exist "%SSH_DIR%" (
    mkdir "%SSH_DIR%"
    echo Created .ssh directory
)

echo.
echo [Step 2/3] Generating SSH key...
echo Please press Enter 3 times to accept defaults (no passphrase)
echo.

ssh-keygen -t rsa -b 4096 -f "%KEY_FILE%"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to generate SSH key
    pause
    exit /b 1
)

echo.
echo [Step 3/3] Copying key to server...
echo You need to enter your password ONE LAST TIME
echo.

type "%KEY_FILE%.pub" | ssh %SERVER_USER%@%SERVER_IP% "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

if %errorlevel% equ 0 (
    echo.
    echo ==========================================================
    echo [SUCCESS] SSH key configured!
    echo ==========================================================
    echo.
    echo Testing passwordless login...
    ssh %SERVER_USER%@%SERVER_IP% "echo 'Passwordless login works!'"
    echo.
    echo You can now run deployment scripts without password!
    echo.
) else (
    echo.
    echo [ERROR] Failed to copy key to server
    echo Please check your password and try again
)

pause
