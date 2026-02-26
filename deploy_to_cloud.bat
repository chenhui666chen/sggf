@echo off
REM ========================================
REM 拾光工坊 - 云端部署脚本 (Windows)
REM ========================================

setlocal enabledelayedexpansion

echo ==========================================
echo   拾光工坊 - 云端部署脚本
echo ==========================================
echo.

REM 配置变量
set SERVER_IP=101.132.154.143
set SERVER_USER=root
set PROJECT_DIR=/root/novel_writing_agent
set LOCAL_DIR=C:\Users\cuigu\novel_writing_agent

REM 检查SCP是否可用
where scp >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到SCP命令
    echo 请安装Git Bash或OpenSSH客户端
    pause
    exit /b 1
)

echo [1/5] 检查本地项目文件...
if not exist "%LOCAL_DIR%\docker-compose.yml" (
    echo [错误] 未找到docker-compose.yml文件
    pause
    exit /b 1
)
if not exist "%LOCAL_DIR%\backend\.env" (
    echo [错误] 未找到backend\.env文件
    pause
    exit /b 1
)
if not exist "%LOCAL_DIR%\ssl\cert.pem" (
    echo [错误] 未找到ssl\cert.pem文件
    pause
    exit /b 1
)
if not exist "%LOCAL_DIR%\ssl\key.pem" (
    echo [错误] 未找到ssl\key.pem文件
    pause
    exit /b 1
)
echo [完成] 本地项目文件检查通过
echo.

echo [2/5] 上传项目文件到服务器...
echo 正在上传，请稍候...
scp -r "%LOCAL_DIR%" %SERVER_USER%@%SERVER_IP%:%PROJECT_DIR%
if %errorlevel% neq 0 (
    echo [错误] 文件上传失败
    pause
    exit /b 1
)
echo [完成] 项目文件上传成功
echo.

echo [3/5] 在服务器上执行部署脚本...
ssh %SERVER_USER%@%SERVER_IP% "cd %PROJECT_DIR% && chmod +x deploy.sh && ./deploy.sh"
if %errorlevel% neq 0 (
    echo [错误] 部署脚本执行失败
    pause
    exit /b 1
)
echo [完成] 部署脚本执行成功
echo.

echo [4/5] 检查服务状态...
ssh %SERVER_USER%@%SERVER_IP% "cd %PROJECT_DIR% && docker-compose ps"
echo.

echo [5/5] 部署完成！
echo.
echo ==========================================
echo   访问地址
echo ==========================================
echo   - HTTP:  http://sggf.net
echo   - HTTPS: https://sggf.net
echo   - API:   https://sggf.net/api
echo.
echo ==========================================
echo   管理命令
echo ==========================================
echo   查看日志: ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose logs -f"
echo   停止服务: ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose stop"
echo   重启服务: ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose restart"
echo   查看状态: ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose ps"
echo.
pause