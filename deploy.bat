@echo off
REM Windows部署脚本
REM 用于在Windows本地测试部署

echo ==========================================
echo   拾光工坊 - Windows本地部署脚本
echo ==========================================
echo.

REM 检查Docker是否安装
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker未安装，请先安装Docker Desktop
    pause
    exit /b 1
)
echo [1/5] Docker已安装
echo.

REM 检查Docker Compose是否安装
docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker Compose未安装，请先安装Docker Compose
    pause
    exit /b 1
)
echo [2/5] Docker Compose已安装
echo.

REM 停止旧容器
echo [3/5] 停止旧容器...
docker-compose down 2>nul
echo 旧容器已停止
echo.

REM 启动服务
echo [4/5] 启动服务...
docker-compose up -d
echo.

REM 等待服务启动
echo [5/5] 等待服务启动...
timeout /t 10 /nobreak >nul
echo.

REM 检查服务状态
echo 检查服务状态...
docker-compose ps
echo.

REM 健康检查
echo 执行健康检查...
timeout /t 5 /nobreak >nul

REM 检查PostgreSQL
docker-compose ps | findstr /C:"novel_postgres" | findstr /C:"Up" >nul
if %errorlevel% equ 0 (
    echo [OK] PostgreSQL 运行正常
) else (
    echo [错误] PostgreSQL 启动失败
)

REM 检查Redis
docker-compose ps | findstr /C:"novel_redis" | findstr /C:"Up" >nul
if %errorlevel% equ 0 (
    echo [OK] Redis 运行正常
) else (
    echo [错误] Redis 启动失败
)

REM 检查Backend
docker-compose ps | findstr /C:"novel_backend" | findstr /C:"Up" >nul
if %errorlevel% equ 0 (
    echo [OK] Backend 运行正常
) else (
    echo [错误] Backend 启动失败
)

REM 检查Frontend
docker-compose ps | findstr /C:"novel_frontend" | findstr /C:"Up" >nul
if %errorlevel% equ 0 (
    echo [OK] Frontend 运行正常
) else (
    echo [错误] Frontend 启动失败
)

REM 检查Nginx
docker-compose ps | findstr /C:"novel_nginx" | findstr /C:"Up" >nul
if %errorlevel% equ 0 (
    echo [OK] Nginx 运行正常
) else (
    echo [错误] Nginx 启动失败
)

echo.
echo ==========================================
echo   部署完成！
echo ==========================================
echo.
echo 访问地址：
echo   - 前端:   http://localhost:3000
echo   - API:    http://localhost:8000
echo   - 文档:   http://localhost:8000/docs
echo.
echo 管理命令：
echo   - 查看日志: docker-compose logs -f
echo   - 停止服务: docker-compose down
echo   - 重启服务: docker-compose restart
echo   - 查看状态: docker-compose ps
echo.
pause
