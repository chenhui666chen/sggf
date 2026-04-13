@echo off
echo ========================================
echo Novel Writing Agent - 安装向导
echo ========================================
echo.

echo [1/3] 检查 Python 环境...
python --version
if errorlevel 1 (
    echo 错误: 未检测到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo.
echo [2/3] 安装依赖...
pip install -r requirements.txt

echo.
echo [3/3] 初始化配置...
if not exist .env (
    echo 提示: 未找到 .env 文件，正在创建...
    copy .env.example .env
    echo.
    echo 请编辑 .env 文件并填入所需的 API 配置
    echo.
)

echo.
echo ========================================
echo 安装完成
echo ========================================
echo.
echo 下一步:
echo 1. 编辑 .env 配置 API 密钥
echo 2. 运行示例: python example.py
echo 3. 运行 CLI: python cli.py
echo.
pause
