# 项目上传到 GitHub 脚本 (PowerShell)
# 使用方法: .\upload_to_github.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Novel Writing Agent - GitHub Upload" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Git 是否安装
$gitExists = $null
try {
    $gitExists = git --version 2>$null
    if ($gitExists) {
        Write-Host "✅ Git 已安装" -ForegroundColor Green
    } else {
        throw "Git not found"
    }
} catch {
    Write-Host "❌ Git 未安装或未添加到 PATH" -ForegroundColor Red
    Write-Host "请访问 https://git-scm.com/download/win 下载安装" -ForegroundColor Yellow
    Read-Host "按 Enter 键退出"
    exit 1
}

# 检查是否已初始化 Git 仓库
if (-not (Test-Path .git)) {
    Write-Host ""
    Write-Host "📍 初始化 Git 仓库..." -ForegroundColor Yellow
    git init
    Write-Host "✅ Git 仓库已初始化" -ForegroundColor Green
} else {
    Write-Host "✅ Git 仓库已存在" -ForegroundColor Green
}

# 检查 Git 用户配置
$gitName = git config user.name 2>$null
if (-not $gitName) {
    Write-Host ""
    Write-Host "⚠️  Git 用户未配置" -ForegroundColor Yellow
    $gitName = Read-Host "请输入你的名字"
    git config --global user.name $gitName
    
    $gitEmail = Read-Host "请输入你的邮箱"
    git config --global user.email $gitEmail
    Write-Host "✅ Git 用户已配置" -ForegroundColor Green
}

# 显示当前状态
Write-Host ""
Write-Host "📊 当前 Git 状态:" -ForegroundColor Cyan
git status

# 添加所有文件
Write-Host ""
Write-Host "📍 添加所有文件..." -ForegroundColor Yellow
git add .
Write-Host "✅ 文件已添加" -ForegroundColor Green

# 创建提交
Write-Host ""
Write-Host "📍 创建提交..." -ForegroundColor Yellow
$commitMsg = Read-Host "请输入提交信息 (默认: Initial commit)"
if ([string]::IsNullOrWhiteSpace($commitMsg)) {
    $commitMsg = "Initial commit"
}

git commit -m $commitMsg
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  没有新的更改需要提交" -ForegroundColor Yellow
} else {
    Write-Host "✅ 提交已创建" -ForegroundColor Green
}

# 检查远程仓库
Write-Host ""
Write-Host "📍 检查远程仓库..." -ForegroundColor Yellow
$remoteUrl = git remote get-url origin 2>$null
if (-not $remoteUrl) {
    Write-Host "⚠️  远程仓库未配置" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "请输入 GitHub 仓库 URL:" -ForegroundColor Cyan
    Write-Host "例如: git@github.com:username/novel_writing_agent.git" -ForegroundColor Gray
    Write-Host "或: https://github.com/username/novel_writing_agent.git" -ForegroundColor Gray
    $remoteUrl = Read-Host "GitHub 仓库 URL"
    
    git remote add origin $remoteUrl
    Write-Host "✅ 远程仓库已添加" -ForegroundColor Green
} else {
    Write-Host "✅ 远程仓库已配置" -ForegroundColor Green
    Write-Host ""
    git remote -v
}

# 重命名分支为 main
Write-Host ""
Write-Host "📍 检查分支..." -ForegroundColor Yellow
git branch -M main
Write-Host "✅ 分支已设置为 main" -ForegroundColor Green

# 推送到 GitHub
Write-Host ""
Write-Host "📍 推送到 GitHub..." -ForegroundColor Yellow
git push -u origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ 推送失败" -ForegroundColor Red
    Write-Host "可能的原因:" -ForegroundColor Yellow
    Write-Host "1. 远程仓库 URL 不正确" -ForegroundColor Gray
    Write-Host "2. SSH 密钥未配置" -ForegroundColor Gray
    Write-Host "3. 网络连接问题" -ForegroundColor Gray
    Write-Host ""
    Write-Host "请检查后重试" -ForegroundColor Yellow
    Read-Host "按 Enter 键退出"
    exit 1
} else {
    Write-Host ""
    Write-Host "✅ 推送成功！" -ForegroundColor Green
    Write-Host ""
    Write-Host "🎉 项目已上传到 GitHub" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "📍 访问你的仓库:" -ForegroundColor Cyan
    git remote get-url origin
    Write-Host ""
}

Read-Host "按 Enter 键退出"

