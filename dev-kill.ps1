# ========= 拾光工坊 - 开发环境清理脚本 =========
# 用途: 清理后端(FastAPI/Uvicorn)和前端(Vite/React)相关进程
# 使用方法: .\dev-kill.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  拾光工坊 - 开发环境清理工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ========= 1. 杀掉常见开发进程（后端/前端） =========
$targets = @(
    "python",   # FastAPI / Uvicorn / Celery Worker
    "python3",
    "uvicorn",
    "node",     # Vite / React 前端
    "npm",
    "pnpm",
    "yarn",
    "celery"    # Celery Worker
)

Write-Host " 步骤 1: 清理常见开发进程..." -ForegroundColor Yellow
$foundProcesses = $false
foreach ($name in $targets) {
    $processes = Get-Process $name -ErrorAction SilentlyContinue
    if ($processes) {
        $foundProcesses = $true
        foreach ($proc in $processes) {
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                Write-Host "   [OK] 已杀死: $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Green
            } catch {
                Write-Host "   [WARN] 无法杀死: $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Red
            }
        }
    }
}

if (-not $foundProcesses) {
    Write-Host "   [INFO] 未发现需要清理的进程" -ForegroundColor Gray
}

Write-Host ""

# ========= 2. 精确按端口杀进程 =========
# 项目实际使用的端口:
# - 8000: FastAPI 后端
# - 5173: Vite 前端开发服务器
$ports = @(8000, 5173)

Write-Host "[PORT] 步骤 2: 清理端口占用..." -ForegroundColor Yellow
foreach ($port in $ports) {
    $lines = netstat -ano | Select-String ":$port"
    if (-not $lines) {
        Write-Host "   [OK] 端口 $port 当前未被占用" -ForegroundColor Green
        continue
    }

    Write-Host "   [CHECK] 检测到端口 $port 有进程占用，开始清理..." -ForegroundColor Yellow

    foreach ($line in $lines) {
        $parts = $line.ToString().Trim() -split "\s+"
        $pid = $parts[-1]

        # 跳过无效 PID
        if (-not [int]::TryParse($pid, [ref]$null)) {
            continue
        }

        try {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "      [KILL] 已杀死 PID $pid ($($proc.ProcessName))" -ForegroundColor Green
            }
        } catch {
            Write-Host "      [WARN] 无法杀死 PID $pid : $_" -ForegroundColor Red
        }
    }
}

Write-Host ""

# ========= 3. 清理后再次检查端口状态 =========
Write-Host " 步骤 3: 验证端口释放状态..." -ForegroundColor Yellow
$allClean = $true
foreach ($port in $ports) {
    $lines = netstat -ano | Select-String ":$port"
    if (-not $lines) {
        Write-Host "   [OK] 端口 $port 已释放" -ForegroundColor Green
    } else {
        Write-Host "   [FAIL] 端口 $port 仍有占用：" -ForegroundColor Red
        foreach ($line in $lines) {
            Write-Host "      $line" -ForegroundColor Gray
        }
        $allClean = $false
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan

if ($allClean) {
    Write-Host "[SUCCESS] 清理完成！所有端口已释放" -ForegroundColor Green
    Write-Host ""
    Write-Host "[TIP] 提示: 现在可以重新启动开发环境:" -ForegroundColor Cyan
    Write-Host "   后端: cd backend ; uvicorn app.main:application --host 0.0.0.0 --port 8000" -ForegroundColor Gray
    Write-Host "   前端: cd frontend ; npm run dev" -ForegroundColor Gray
} else {
    Write-Host "[WARN] 部分端口未能完全释放，请手动检查" -ForegroundColor Yellow
    Write-Host "   使用命令: netstat -ano | findstr '<端口号>'" -ForegroundColor Gray
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
