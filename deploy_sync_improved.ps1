# Novel Writing Agent - Improved Bidirectional Sync Script
# Fixes: upload failures, delete hangs, better error handling

param(
    [string]$ServerIP = "101.132.154.143",
    [string]$ServerUser = "root",
    [string]$LocalPath = "C:\Users\cuigu\novel_writing_agent",
    [string]$RemotePath = "/root/novel_writing_agent",
    [int]$MaxRetries = 3,
    [int]$TimeoutSeconds = 30,
    [switch]$DryRun = $false,
    [switch]$SkipDelete = $false
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Improved Sync Script v2.0" -ForegroundColor Cyan
Write-Host "  - Retry mechanism for uploads" -ForegroundColor Cyan
Write-Host "  - Batch delete for performance" -ForegroundColor Cyan
Write-Host "  - Better error handling" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $LocalPath

# Step 1: Get local file list
Write-Host "[Step 1/5] Scanning local files..." -ForegroundColor Yellow

$localFiles = Get-ChildItem -Path . -Recurse -File -Include *.py,*.tsx,*.ts,*.json,*.yml,*.yaml,*.conf | 
    Where-Object { $_.FullName -notmatch "node_modules|\.venv|__pycache__|\.git|\.next|dist|build|\.tmp" }

$localFileList = @{}
foreach ($file in $localFiles) {
    $relativePath = $file.FullName.Substring($LocalPath.Length + 1)
    $relativePath = $relativePath.Replace("\", "/")
    $localFileList[$relativePath] = $true
}

Write-Host "  Local files: $($localFileList.Count)" -ForegroundColor Green
Write-Host ""

# Step 2: Get remote file list
Write-Host "[Step 2/5] Scanning remote files..." -ForegroundColor Yellow

$remoteFileList = @{}
$remoteFiles = ssh -o ConnectTimeout=30 $ServerUser@$ServerIP "cd $RemotePath && find . -type f \( -name '*.py' -o -name '*.tsx' -o -name '*.ts' -o -name '*.json' -o -name '*.yml' -o -name '*.yaml' -o -name '*.conf' \) ! -path '*/node_modules/*' ! -path '*/.venv/*' ! -path '*/__pycache__/*' ! -path '*/.git/*' ! -path '*/.next/*' ! -path '*/dist/*' ! -path '*/build/*' ! -path '*/.tmp/*' 2>/dev/null"

foreach ($file in $remoteFiles) {
    if ($file -match "^\./(.+)$") {
        $relativePath = $matches[1]
        $remoteFileList[$relativePath] = $true
    }
}

Write-Host "  Remote files: $($remoteFileList.Count)" -ForegroundColor Green
Write-Host ""

# Step 3: Find files to delete
Write-Host "[Step 3/5] Finding files to delete..." -ForegroundColor Yellow

$filesToDelete = @()
foreach ($remoteFile in $remoteFileList.Keys) {
    if (-not $localFileList.ContainsKey($remoteFile)) {
        $filesToDelete += $remoteFile
    }
}

if ($filesToDelete.Count -gt 0) {
    Write-Host "  Files to delete: $($filesToDelete.Count)" -ForegroundColor Red
} else {
    Write-Host "  No files to delete" -ForegroundColor Green
}
Write-Host ""

# Step 4: Upload local files with retry
Write-Host "[Step 4/5] Uploading local files (with retry)..." -ForegroundColor Yellow

# First, ensure all directories exist on remote
Write-Host "  Creating remote directories..." -ForegroundColor Yellow
$directories = @{}
foreach ($localPath_item in $localFileList.Keys) {
    $dir = Split-Path $localPath_item -Parent
    if ($dir -and -not $directories.ContainsKey($dir)) {
        $directories[$dir] = $true
    }
}

$dirList = $directories.Keys -join " "
$mkdirCmd = "mkdir -p $RemotePath/" + ($directories.Keys | ForEach-Object { $_.Replace("`"", "\`"") }) -join " "
ssh -o ConnectTimeout=60 $ServerUser@$ServerIP "cd $RemotePath && mkdir -p $($directories.Keys -join ' ')" 2>&1 | Out-Null
Write-Host "  Created $($directories.Count) directories" -ForegroundColor Green

$uploaded = 0
$failed = 0
$failedFiles = @()

foreach ($localPath_item in $localFileList.Keys) {
    $localFile = Join-Path $LocalPath $localPath_item.Replace("/", "\")
    $remoteFile = "$($ServerUser)@$($ServerIP):$($RemotePath)/$($localPath_item)"
    
    Write-Host "  Uploading: $localPath_item" -NoNewline
    
    $success = $false
    for ($retry = 1; $retry -le $MaxRetries; $retry++) {
        try {
            $result = scp -o StrictHostKeyChecking=no -o ConnectTimeout=$TimeoutSeconds $localFile $remoteFile 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host " [OK]" -ForegroundColor Green
                $uploaded++
                $success = $true
                break
            } else {
                if ($retry -lt $MaxRetries) {
                    Write-Host " [Retry $retry/$MaxRetries]" -ForegroundColor Yellow -NoNewline
                    Start-Sleep -Seconds 2
                }
            }
        } catch {
            if ($retry -lt $MaxRetries) {
                Write-Host " [Retry $retry/$MaxRetries]" -ForegroundColor Yellow -NoNewline
                Start-Sleep -Seconds 2
            }
        }
    }
    
    if (-not $success) {
        Write-Host " [FAILED]" -ForegroundColor Red
        $failed++
        $failedFiles += $localPath_item
    }
}

Write-Host ""
Write-Host "Upload completed:" -ForegroundColor Green
Write-Host "  Success: $uploaded" -ForegroundColor Green
Write-Host "  Failed: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })

if ($failedFiles.Count -gt 0) {
    Write-Host ""
    Write-Host "Failed files:" -ForegroundColor Red
    foreach ($f in $failedFiles) {
        Write-Host "  - $f" -ForegroundColor Red
    }
}
Write-Host ""

# Step 5: Batch delete remote files
if (-not $SkipDelete -and $filesToDelete.Count -gt 0) {
    Write-Host "[Step 5/5] Deleting remote files (batch mode)..." -ForegroundColor Yellow
    
    if ($DryRun) {
        Write-Host "  [DRY RUN] Would delete $($filesToDelete.Count) files:" -ForegroundColor Magenta
        foreach ($file in $filesToDelete) {
            Write-Host "    - $file" -ForegroundColor Magenta
        }
    } else {
        # Batch delete - create delete script on remote
        $deleteScript = $filesToDelete | ForEach-Object { "rm -f '$RemotePath/$_'" }
        $deleteScriptStr = $deleteScript -join "`n"
        
        Write-Host "  Deleting $($filesToDelete.Count) files in batch..." -NoNewline
        
        try {
            $result = ssh -o ConnectTimeout=60 $ServerUser@$ServerIP "cd $RemotePath && $deleteScriptStr" 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host " [OK]" -ForegroundColor Green
                Write-Host "  Deleted: $($filesToDelete.Count) files" -ForegroundColor Green
            } else {
                Write-Host " [PARTIAL]" -ForegroundColor Yellow
                Write-Host "  Some files may not have been deleted" -ForegroundColor Yellow
            }
        } catch {
            Write-Host " [ERROR]" -ForegroundColor Red
            Write-Host "  Error: $_" -ForegroundColor Red
        }
    }
} else {
    Write-Host "[Step 5/5] Skipping file deletion" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "[SUCCESS] Sync completed!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Summary:" -ForegroundColor Yellow
Write-Host "  Uploaded: $uploaded files" -ForegroundColor Green
Write-Host "  Failed: $failed files" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })
Write-Host "  Deleted: $(if ($SkipDelete) { 'Skipped' } else { $filesToDelete.Count }) files" -ForegroundColor $(if ($SkipDelete) { "Yellow" } else { "Red" })
Write-Host ""

if ($DryRun) {
    Write-Host "This was a DRY RUN. No changes were made." -ForegroundColor Magenta
    Write-Host "Run without -DryRun to apply changes." -ForegroundColor Yellow
}

if ($failedFiles.Count -gt 0) {
    Write-Host ""
    Write-Host "To retry failed files, run:" -ForegroundColor Yellow
    Write-Host "  .\deploy_sync_improved.ps1" -ForegroundColor Cyan
}
