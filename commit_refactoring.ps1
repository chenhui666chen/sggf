# Git 提交脚本 - 提交项目重构

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  项目重构 Git 提交脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 添加 Git 到 PATH
$gitPaths = @(
    "C:\Program Files\Git\cmd",
    "C:\Program Files (x86)\Git\cmd",
    "$env:LOCALAPPDATA\Programs\Git\cmd"
)

$gitFound = $false
foreach ($path in $gitPaths) {
    if (Test-Path $path) {
        $env:Path = $env:Path + ";$path"
        Write-Host "✅ 找到 Git: $path" -ForegroundColor Green
        $gitFound = $true
        break
    }
}

if (-not $gitFound) {
    Write-Host "❌ 未找到 Git，请先安装 Git" -ForegroundColor Red
    Write-Host "   下载地址: https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}

# 检查 Git 版本
Write-Host ""
Write-Host "📍 Git 版本:" -ForegroundColor Cyan
git --version

# 检查 Git 状态
Write-Host ""
Write-Host "📍 检查 Git 状态..." -ForegroundColor Cyan
git status --short

# 添加所有更改
Write-Host ""
Write-Host "📍 添加所有更改到暂存区..." -ForegroundColor Cyan
git add .

# 显示将要提交的文件
Write-Host ""
Write-Host "📍 将要提交的文件:" -ForegroundColor Cyan
git status --short

# 提交更改
Write-Host ""
Write-Host "📍 提交更改..." -ForegroundColor Cyan

git commit -m "refactor: 项目结构重构和前端按钮优化

主要更改:
1. 项目结构重构
   - 将所有 Agent 模块从根目录移动到 backend/app/services/agents/
   - 更新所有导入路径为相对导入
   - 移除 sys.path.insert() hack
   - 统一依赖管理到 backend/requirements.txt

2. 修复问题
   - 修复 LangChain API 调用 (llm -> llm.invoke)
   - 修复缺失的 os 模块导入
   - 修复前端 token 键名错误 (token -> access_token)

3. 前端优化
   - 移除概念开发阶段的上一步按钮
   - 移除迭代优化阶段的生成下一章按钮
   - 清理未使用的导入和函数

4. 清理工作
   - 删除根目录的旧 Python 文件
   - 删除 __pycache__ 目录
   - 删除根目录的 requirements.txt

测试状态: 所有功能正常运行"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ 提交成功!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📍 最近的提交:" -ForegroundColor Cyan
    git log --oneline -5
    Write-Host ""
    Write-Host "💡 提示: 如果需要推送到远程仓库，请运行:" -ForegroundColor Yellow
    Write-Host "   git push origin main" -ForegroundColor Yellow
    Write-Host "   (或者 git push origin master，取决于你的主分支名称)" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "❌ 提交失败" -ForegroundColor Red
    Write-Host "   请检查错误信息" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan

