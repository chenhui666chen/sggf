# ========= 拾光工坊 - 开发环境清理脚本（精确打击版） =========
# 用途: 一次性关闭本项目五个服务(Backend / Celery Audiobook / Celery DreamWeaver / Celery Beat / Frontend)
#       仅按命令行特征匹配本项目进程，不误杀系统里其他 python / node 进程
# 使用方法: .\dev-kill.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  拾光工坊 - 开发环境清理工具（精确版）" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# 本项目进程的命令行特征（uvicorn 后端 / celery worker / vite 前端 / dev.bat 宿主窗口）
$includePattern = 'novel_writing_agent|uvicorn app\.main|celery_app|vite|npm(\.cmd)? run dev'
# 排除：IDE 辅助进程、本清理脚本自身所在会话
$excludePattern = 'autopep|qoder\\extensions|dev-kill'

# ========= 1. 优雅停止 Celery worker（避免腰斩执行中的任务） =========
Write-Host " 步骤 1: 尝试优雅停止 Celery worker..." -ForegroundColor Yellow
$celeryExe = Join-Path $projectRoot ".venv\Scripts\celery.exe"
if (Test-Path $celeryExe) {
    $job = Start-Job -ScriptBlock {
        param($exe, $root)
        Set-Location (Join-Path $root "backend")
        & $exe -A app.celery_app.celery_app control shutdown 2>$null
    } -ArgumentList $celeryExe, $projectRoot
    if (Wait-Job $job -Timeout 6) {
        Write-Host "   [OK] 已发送优雅停止指令" -ForegroundColor Green
    } else {
        Write-Host "   [INFO] 发送超时（broker 可能未运行），转入强制清理" -ForegroundColor Gray
    }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
} else {
    Write-Host "   [INFO] 未找到 celery.exe，跳过" -ForegroundColor Gray
}
Write-Host ""

# ========= 2. 按命令行特征精确终止本项目进程 =========
Write-Host " 步骤 2: 精确清理本项目进程..." -ForegroundColor Yellow
$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in 'cmd.exe', 'python.exe', 'node.exe', 'celery.exe') -and
    $_.CommandLine -and
    ($_.CommandLine -match $includePattern) -and
    ($_.CommandLine -notmatch $excludePattern) -and
    ($_.ProcessId -ne $PID)
}

if ($targets) {
    foreach ($proc in $targets) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Host "   [KILL] $($proc.Name) (PID: $($proc.ProcessId))" -ForegroundColor Green
        } catch {
            Write-Host "   [WARN] 无法终止: $($proc.Name) (PID: $($proc.ProcessId))" -ForegroundColor Red
        }
    }
} else {
    Write-Host "   [INFO] 未发现本项目相关进程" -ForegroundColor Gray
}
Write-Host ""

# ========= 3. 按端口兜底清理（8000 后端 / 5173 前端） =========
# 注意: 8000 端口可能由 Docker 容器(novel_backend)占用，此时占用者是
#       com.docker.backend / wslrelay 等 Docker 基础进程，绝不能强杀
Write-Host " 步骤 3: 端口兜底清理..." -ForegroundColor Yellow
$ports = @(8000, 5173)
$killableNames = @('python', 'node', 'cmd', 'celery', 'uvicorn')
foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "   [OK] 端口 $port 未被占用" -ForegroundColor Green
        continue
    }
    foreach ($conn in $conns) {
        $owner = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if (-not $owner) { continue }
        if ($killableNames -contains $owner.ProcessName.ToLower()) {
            Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue
            Write-Host "   [KILL] 端口 $port 占用者 PID $($owner.Id) ($($owner.ProcessName))" -ForegroundColor Green
        } else {
            Write-Host "   [SKIP] 端口 $port 由 $($owner.ProcessName) 占用（疑似 Docker 容器映射），不强杀" -ForegroundColor Yellow
            Write-Host "          如需释放请执行: docker stop novel_backend" -ForegroundColor Gray
        }
    }
}
Write-Host ""

# ========= 4. 验证清理结果 =========
Write-Host " 步骤 4: 验证清理结果..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
$allClean = $true

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "   [OK] 端口 $port 已释放" -ForegroundColor Green
        continue
    }
    $ownerNames = @($conns | ForEach-Object { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } | Where-Object { $_ } | Select-Object -Unique)
    if ($ownerNames.Count -eq 0) {
        Write-Host "   [INFO] 端口 $port 存在无属主的残留监听条目（属主进程已退出，系统稍后自动回收）" -ForegroundColor Gray
        continue
    }
    $onlyDocker = -not ($ownerNames | Where-Object { $killableNames -contains $_.ToLower() })
    if ($onlyDocker) {
        Write-Host "   [INFO] 端口 $port 由 $($ownerNames -join ', ') 占用（Docker 容器映射，不属本次清理范围）" -ForegroundColor Gray
    } else {
        Write-Host "   [FAIL] 端口 $port 仍被占用: $($ownerNames -join ', ')" -ForegroundColor Red
        $allClean = $false
    }
}

$residual = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in 'cmd.exe', 'python.exe', 'node.exe', 'celery.exe') -and
    $_.CommandLine -and
    ($_.CommandLine -match $includePattern) -and
    ($_.CommandLine -notmatch $excludePattern) -and
    ($_.ProcessId -ne $PID)
}
if ($residual) {
    Write-Host "   [FAIL] 仍有残留进程:" -ForegroundColor Red
    $residual | ForEach-Object { Write-Host "      PID $($_.ProcessId) $($_.Name)" -ForegroundColor Gray }
    $allClean = $false
} else {
    Write-Host "   [OK] 无本项目进程残留" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($allClean) {
    Write-Host "[SUCCESS] 清理完成！五个服务已全部关闭" -ForegroundColor Green
} else {
    Write-Host "[WARN] 部分目标未能完全清理，请按上方提示手动检查" -ForegroundColor Yellow
}
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
