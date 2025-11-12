@echo off
REM 项目上传到 GitHub 脚本 (CMD - 简化版)
REM 使用方法: upload_to_github_simple.bat

chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ========================================
echo   Novel Writing Agent - GitHub Upload
echo ========================================
echo.

REM 检查 Git 是否安装
echo 📍 检查 Git...
git --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Git 未安装或未添加到 PATH
    echo 请访问 https://git-scm.com/download/win 下载安装
    pause
    exit /b 1
)
echo ✅ Git 已安装

REM 检查是否已初始化 Git 仓库
echo.
echo 📍 检查 Git 仓库...
if not exist .git (
    echo 初始化 Git 仓库...
    git init
    echo ✅ Git 仓库已初始化
) else (
    echo ✅ Git 仓库已存在
)

REM 检查 Git 用户配置
echo.
echo 📍 检查 Git 用户配置...
git config user.name >nul 2>&1
if errorlevel 1 (
    echo ⚠️  Git 用户未配置
    set /p git_name="请输入你的名字: "
    git config --global user.name "%git_name%"
    
    set /p git_email="请输入你的邮箱: "
    git config --global user.email "%git_email%"
    echo ✅ Git 用户已配置
) else (
    echo ✅ Git 用户已配置
)

REM 显示当前状态
echo.
echo 📊 当前 Git 状态:
git status

REM 添加所有文件
echo.
echo 📍 添加所有文件...
git add .
echo ✅ 文件已添加

REM 创建提交
echo.
echo 📍 创建提交...
set /p commit_msg="请输入提交信息 (默认: Initial commit): "
if "%commit_msg%"=="" set commit_msg=Initial commit

git commit -m "%commit_msg%"
if errorlevel 1 (
    echo ⚠️  没有新的更改需要提交
) else (
    echo ✅ 提交已创建
)

REM 检查远程仓库
echo.
echo 📍 检查远程仓库...
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo ⚠️  远程仓库未配置
    echo.
    echo 请输入 GitHub 仓库 URL:
    echo 例如: https://github.com/username/novel_writing_agent.git
    echo 或: git@github.com:username/novel_writing_agent.git
    set /p remote_url="GitHub 仓库 URL: "
    
    git remote add origin %remote_url%
    echo ✅ 远程仓库已添加
) else (
    echo ✅ 远程仓库已配置
    echo.
    git remote -v
)

REM 重命名分支为 main
echo.
echo 📍 检查分支...
git branch -M main
echo ✅ 分支已设置为 main

REM 推送到 GitHub
echo.
echo 📍 推送到 GitHub...
echo 这可能需要几秒钟...
git push -u origin main

if errorlevel 1 (
    echo.
    echo ❌ 推送失败
    echo 可能的原因:
    echo 1. 远程仓库 URL 不正确
    echo 2. SSH 密钥未配置（如果使用 SSH）
    echo 3. 网络连接问题
    echo 4. GitHub 认证失败
    echo.
    echo 解决方案:
    echo - 使用 HTTPS URL 而不是 SSH
    echo - 检查网络连接
    echo - 重新运行脚本
    echo.
    pause
    exit /b 1
) else (
    echo.
    echo ✅ 推送成功！
    echo.
    echo 🎉 项目已上传到 GitHub
    echo.
    echo 📍 访问你的仓库:
    git remote get-url origin
    echo.
    echo ✨ 上传完成！
)

pause

