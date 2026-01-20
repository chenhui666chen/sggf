@echo off
chcp 65001 >nul
cd /d "%~dp0"
cls

echo ================================================================
echo 拾光工坊 - 生产环境启动脚本
echo ================================================================
echo.
echo 生产环境配置：
echo   - 数据库：PostgreSQL
echo   - 缓存：Redis（带密码）
echo   - DEBUG：关闭
echo   - SSL：启用
echo.
echo ================================================================
echo.

:: 检查Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker未安装或未在PATH中
    echo 请先安装Docker Desktop
    pause
    exit /b 1
)

:: 检查Docker Compose
docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Compose未安装或未在PATH中
    echo 请先安装Docker Compose
    pause
    exit /b 1
)

echo [OK] Docker环境检查通过
echo.

:: 检查SSL证书
if not exist "ssl\cert.pem" (
    echo [WARNING] SSL证书文件不存在: ssl\cert.pem
    echo 将使用占位符证书（仅用于测试）
    echo.
)

if not exist "ssl\key.pem" (
    echo [WARNING] SSL私钥文件不存在: ssl\key.pem
    echo 将使用占位符私钥（仅用于测试）
    echo.
)

:: 停止现有服务
echo [1/5] 停止现有服务...
docker-compose down

:: 清理旧容器和镜像（可选）
echo [2/5] 清理旧容器...
docker-compose rm -f

:: 构建镜像
echo [3/5] 构建Docker镜像...
docker-compose build

:: 启动服务
echo [4/5] 启动所有服务...
docker-compose up -d

:: 等待服务启动
echo [5/5] 等待服务启动...
timeout /t 10 /nobreak >nul

:: 检查服务状态
echo.
echo ================================================================
echo 服务状态检查
echo ================================================================
echo.
docker-compose ps

:: 检查PostgreSQL
echo.
echo [检查] PostgreSQL...
docker exec novel_postgres pg_isready -U novel_user >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PostgreSQL启动失败
    echo 查看日志: docker-compose logs postgres
) else (
    echo [OK] PostgreSQL运行正常
)

:: 检查Redis
echo [检查] Redis...
docker exec novel_redis redis-cli -a MfDUzsb5%%&1uYW9N ping >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Redis启动失败
    echo 查看日志: docker-compose logs redis
) else (
    echo [OK] Redis运行正常
)

:: 检查Backend
echo [检查] Backend...
curl -f http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Backend启动失败
    echo 查看日志: docker-compose logs backend
) else (
    echo [OK] Backend运行正常
)

:: 检查Frontend
echo [检查] Frontend...
curl -f http://localhost:3000 >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Frontend可能未启动（这是正常的，通过Nginx访问）
) else (
    echo [OK] Frontend运行正常
)

:: 检查Nginx
echo [检查] Nginx...
docker exec novel_nginx nginx -t >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Nginx配置错误
    echo 查看日志: docker-compose logs nginx
) else (
    echo [OK] Nginx配置正确
)

echo.
echo ================================================================
echo [SUCCESS] 拾光工坊生产环境启动完成！
echo ================================================================
echo.
echo 服务访问地址：
echo   - 前端：http://localhost:3000
echo   - 后端：http://localhost:8000
echo   - API文档：http://localhost:8000/docs
echo   - 健康检查：http://localhost:8000/health
echo.
echo 生产环境访问（需要配置DNS）：
echo   - 前端：https://sggf.net
echo   - 后端：https://sggf.net/api/
echo   - WebSocket：wss://sggf.net/ws/
echo.
echo 管理命令：
echo   - 查看日志：docker-compose logs -f [service]
echo   - 停止服务：docker-compose down
echo   - 重启服务：docker-compose restart [service]
echo   - 查看状态：docker-compose ps
echo.
echo ================================================================
echo.
echo 按任意键打开浏览器...
pause

:: 打开浏览器
start http://localhost:3000

echo.
echo [DONE] 浏览器已打开
echo.
pause
