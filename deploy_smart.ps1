# Novel Writing Agent - Smart Sync Script (PowerShell)
# Version: 2.0
# Feature: Auto detect and sync all modified files

param(
    [string]$ServerIP = "101.132.154.143",
    [string]$ServerUser = "root",
    [string]$LocalPath = "C:\Users\cuigu\novel_writing_agent",
    [string]$RemotePath = "/data/apps/novel_writing_agent",
    [switch]$Force = $false,
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Novel Writing Agent - Smart Sync v2.0" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Set encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$PSDefaultParameterValues['*:Encoding'] = 'utf8'

# Switch to project directory
Set-Location $LocalPath

# Step 1: Detect modified files
Write-Host "[Step 1/5] Detecting modified files..." -ForegroundColor Yellow
Write-Host ""

$modifiedFiles = @()
$categories = @{
    "Backend Core" = @("backend/app/api/**/*.py", "backend/app/models/**/*.py", "backend/app/schemas/**/*.py", "backend/app/core/**/*.py")
    "Backend Tasks" = @("backend/app/tasks/**/*.py")
    "Frontend Pages" = @("frontend/src/pages/**/*.tsx", "frontend/src/pages/**/*.ts")
    "Frontend Components" = @("frontend/src/components/**/*.tsx", "frontend/src/components/**/*.ts")
    "Frontend Services" = @("frontend/src/services/**/*.ts", "frontend/src/utils/**/*.ts")
    "Frontend Core" = @("frontend/src/App.tsx", "frontend/src/main.tsx")
    "Adapters" = @("adapters/**/*.py")
    "Agents" = @("agents/**/*.py")
    "Pipeline" = @("pipeline/**/*.py")
    "Shared" = @("shared/**/*.py")
    "Config" = @("docker-compose.yml", "nginx-prod.conf", ".env.example")
}

$fileStats = @{}

foreach ($category in $categories.Keys) {
    $patterns = $categories[$category]
    $files = @()
    
    foreach ($pattern in $patterns) {
        $foundFiles = Get-ChildItem -Path . -Filter $pattern -Recurse -File -ErrorAction SilentlyContinue
        $files += $foundFiles
    }
    
    if ($files.Count -gt 0) {
        $fileStats[$category] = $files.Count
        Write-Host "  $category : $($files.Count) files" -ForegroundColor Green
    }
}

Write-Host ""

# Step 2: Generate sync list
Write-Host "[Step 2/5] Generating sync list..." -ForegroundColor Yellow
Write-Host ""

$syncList = @()
$allFiles = Get-ChildItem -Path . -Recurse -File -Include *.py,*.tsx,*.ts,*.json,*.yml,*.yaml,*.conf | 
    Where-Object { $_.FullName -notmatch "node_modules|\.venv|__pycache__|\.git|\.next|dist|build" }

foreach ($file in $allFiles) {
    $relativePath = $file.FullName.Substring($LocalPath.Length + 1)
    $relativePath = $relativePath.Replace("\", "/")
    
    $syncList += [PSCustomObject]@{
        LocalPath = $file.FullName
        RelativePath = $relativePath
        Size = $file.Length
        LastModified = $file.LastWriteTime
    }
}

Write-Host "  Total files to sync: $($syncList.Count)" -ForegroundColor Green
Write-Host ""

if ($DryRun) {
    Write-Host "[Dry Run Mode] Following files will be synced:" -ForegroundColor Magenta
    $syncList | Select-Object -First 20 | ForEach-Object { Write-Host "  $($_.RelativePath)" }
    if ($syncList.Count -gt 20) {
        Write-Host "  ... and $($syncList.Count - 20) more files" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "Dry run completed, no actual sync performed" -ForegroundColor Yellow
    exit 0
}

# Step 3: Upload files
Write-Host "[Step 3/5] Uploading files to server..." -ForegroundColor Yellow
Write-Host ""

$uploaded = 0
$failed = 0
$failedFiles = @()

foreach ($item in $syncList) {
    $localFile = $item.LocalPath
    $remoteFile = "$($ServerUser)@$($ServerIP):$($RemotePath)/$($item.RelativePath)"
    
    Write-Host "  Uploading: $($item.RelativePath)" -NoNewline
    
    try {
        $result = scp -o StrictHostKeyChecking=no -o ConnectTimeout=5 $localFile $remoteFile 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host " [OK]" -ForegroundColor Green
            $uploaded++
        } else {
            Write-Host " [FAIL]" -ForegroundColor Red
            $failed++
            $failedFiles += $item.RelativePath
        }
    } catch {
        Write-Host " [ERROR]" -ForegroundColor Red
        $failed++
        $failedFiles += $item.RelativePath
    }
}

Write-Host ""
Write-Host "Upload completed:" -ForegroundColor Green
Write-Host "  Success: $uploaded files" -ForegroundColor Green
Write-Host "  Failed: $failed files" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })

if ($failed -gt 0) {
    Write-Host ""
    Write-Host "Failed files:" -ForegroundColor Red
    $failedFiles | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    
    $continue = Read-Host "Continue deployment? (y/n)"
    if ($continue -ne "y") {
        Write-Host "Deployment cancelled" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""

# Step 4: Rebuild and restart services
Write-Host "[Step 4/5] Rebuilding and restarting services..." -ForegroundColor Yellow
Write-Host ""

Write-Host "  Stopping old containers..." -NoNewline
ssh $ServerUser@$ServerIP "cd $RemotePath ; docker-compose down backend" 2>&1 | Out-Null
Write-Host " [OK]" -ForegroundColor Green

Write-Host "  Rebuilding backend image (this may take a few minutes)..." -ForegroundColor Yellow
$result = ssh $ServerUser@$ServerIP "cd $RemotePath ; docker-compose build backend" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Backend image build failed" -ForegroundColor Red
    Write-Host $result
    exit 1
}
Write-Host "  [OK] Backend image build completed" -ForegroundColor Green

Write-Host "  Starting backend service..." -NoNewline
ssh $ServerUser@$ServerIP "cd $RemotePath ; docker-compose up -d backend" 2>&1 | Out-Null
Write-Host " [OK]" -ForegroundColor Green

Write-Host "  Restarting frontend service..." -NoNewline
ssh $ServerUser@$ServerIP "cd $RemotePath ; docker-compose restart frontend" 2>&1 | Out-Null
Write-Host " [OK]" -ForegroundColor Green

Write-Host ""

# Step 5: Validate deployment
Write-Host "[Step 5/5] Validating deployment..." -ForegroundColor Yellow
Write-Host ""

Write-Host "  Waiting for services to start..." -NoNewline
Start-Sleep -Seconds 15
Write-Host " [OK]" -ForegroundColor Green

Write-Host ""
Write-Host "Container status:" -ForegroundColor Cyan
ssh $ServerUser@$ServerIP "cd $RemotePath ; docker-compose ps"

Write-Host ""
Write-Host "Testing backend API..." -ForegroundColor Cyan
$apiTest = ssh $ServerUser@$ServerIP "curl -s http://localhost:8000/api/v1/health"
Write-Host $apiTest

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "[SUCCESS] Smart sync completed!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Deployment statistics:" -ForegroundColor Yellow
Write-Host "  Uploaded files: $uploaded" -ForegroundColor Green
Write-Host "  Failed files: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })
Write-Host ""
Write-Host "Access URLs:" -ForegroundColor Yellow
Write-Host "  HTTP:  http://$ServerIP" -ForegroundColor White
Write-Host "  HTTPS: https://sggf.net" -ForegroundColor White
Write-Host "  Domain: https://www.sggf.net" -ForegroundColor White
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
