@echo off
chcp 65001 >nul
echo ========================================
echo   项目重构 Git 提交脚本
echo ========================================
echo.

REM 添加 Git 到 PATH
set "PATH=%PATH%;C:\Program Files\Git\cmd"

REM 检查 Git 版本
echo 检查 Git 版本...
git --version
if errorlevel 1 (
    echo 错误: 未找到 Git
    echo 请先安装 Git: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo.
echo 检查 Git 状态...
git status --short

echo.
echo 添加所有更改到暂存区...
git add .

echo.
echo 将要提交的文件:
git status --short

echo.
echo 提交更改...
git commit -m "refactor: 项目结构重构和前端按钮优化" -m "主要更改:" -m "1. 项目结构重构" -m "   - 将所有 Agent 模块从根目录移动到 backend/app/services/agents/" -m "   - 更新所有导入路径为相对导入" -m "   - 移除 sys.path.insert() hack" -m "   - 统一依赖管理到 backend/requirements.txt" -m "" -m "2. 修复问题" -m "   - 修复 LangChain API 调用" -m "   - 修复缺失的 os 模块导入" -m "   - 修复前端 token 键名错误" -m "" -m "3. 前端优化" -m "   - 移除概念开发阶段的上一步按钮" -m "   - 移除迭代优化阶段的生成下一章按钮" -m "   - 清理未使用的导入和函数" -m "" -m "4. 清理工作" -m "   - 删除根目录的旧 Python 文件" -m "   - 删除 __pycache__ 目录" -m "   - 删除根目录的 requirements.txt"

if errorlevel 1 (
    echo.
    echo 提交失败
    pause
    exit /b 1
)

echo.
echo 提交成功!
echo.
echo 最近的提交:
git log --oneline -5

echo.
echo ========================================
echo 提示: 如果需要推送到远程仓库，请运行:
echo   git push origin main
echo   (或者 git push origin master)
echo ========================================
echo.
pause

