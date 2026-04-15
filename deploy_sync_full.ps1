# Novel Writing Agent - Bidirectional Sync Script
# This script syncs files AND removes files that don't exist locally

param(
    [string]$ServerIP = "101.132.154.143",
    [string]$ServerUser = "root",
    [string]$LocalPath = "C:\Users\cuigu\novel_writing_agent",
    [string]$RemotePath = "/data/apps/novel_writing_agent",
    [switch]$DryRun = $false,
    [switch]$SkipDelete = $false
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Bidirectional Sync Script v1.0" -ForegroundColor Cyan
Write-Host "  Syncs files AND removes deleted files" -ForegroundColor Cyan
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
$remoteFiles = ssh $ServerUser@$ServerIP "cd $RemotePath && find . -type f \( -name '*.py' -o -name '*.tsx' -o -name '*.ts' -o -name '*.json' -o -name '*.yml' -o -name '*.yaml' -o -name '*.conf' \) ! -path '*/node_modules/*' ! -path '*/.venv/*' ! -path '*/__pycache__/*' ! -path '*/.git/*' ! -path '*/.next/*' ! -path '*/dist/*' ! -path '*/build/*' ! -path '*/.tmp/*' 2>/dev/null"

foreach ($file in $remoteFiles) {
    if ($file -match "^\./(.+)$") {
        $relativePath = $matches[1]
        $remoteFileList[$relativePath] = $true
    }
}

Write-Host "  Remote files: $($remoteFileList.Count)" -ForegroundColor Green
Write-Host ""

# Step 3: Find files to delete (exist on remote but not on local)
Write-Host "[Step 3/5] Finding files to delete..." -ForegroundColor Yellow

$filesToDelete = @()
foreach ($remoteFile in $remoteFileList.Keys) {
    if (-not $localFileList.ContainsKey($remoteFile)) {
        $filesToDelete += $remoteFile
    }
}

if ($filesToDelete.Count -gt 0) {
    Write-Host "  Files to delete: $($filesToDelete.Count)" -ForegroundColor Red
    foreach ($file in $filesToDelete) {
        Write-Host "    - $file" -ForegroundColor Red
    }
} else {
    Write-Host "  No files to delete" -ForegroundColor Green
}
Write-Host ""

# Step 4: Upload local files
Write-Host "[Step 4/5] Uploading local files..." -ForegroundColor Yellow

$uploaded = 0
$failed = 0

foreach ($localPath_item in $localFileList.Keys) {
    $localFile = Join-Path $LocalPath $localPath_item.Replace("/", "\")
    $remoteFile = "$($ServerUser)@$($ServerIP):$($RemotePath)/$($localPath_item)"
    
    Write-Host "  Uploading: $localPath_item" -NoNewline
    
    try {
        scp -o StrictHostKeyChecking=no -o ConnectTimeout=5 $localFile $remoteFile 2>&1 | Out-Null
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host " [OK]" -ForegroundColor Green
            $uploaded++
        } else {
            Write-Host " [FAIL]" -ForegroundColor Red
            $failed++
        }
    } catch {
        Write-Host " [ERROR]" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "Upload completed:" -ForegroundColor Green
Write-Host "  Success: $uploaded" -ForegroundColor Green
Write-Host "  Failed: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })
Write-Host ""

# Step 5: Delete remote files
if (-not $SkipDelete -and $filesToDelete.Count -gt 0) {
    Write-Host "[Step 5/5] Deleting remote files..." -ForegroundColor Yellow
    
    if ($DryRun) {
        Write-Host "  [DRY RUN] Would delete $($filesToDelete.Count) files:" -ForegroundColor Magenta
        foreach ($file in $filesToDelete) {
            Write-Host "    - $file" -ForegroundColor Magenta
        }
    } else {
        $deleted = 0
        $deleteFailed = 0
        
        foreach ($file in $filesToDelete) {
            Write-Host "  Deleting: $file" -NoNewline
            
            $result = ssh $ServerUser@$ServerIP "rm -f '$RemotePath/$file'" 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host " [OK]" -ForegroundColor Green
                $deleted++
            } else {
                Write-Host " [FAIL]" -ForegroundColor Red
                $deleteFailed++
            }
        }
        
        Write-Host ""
        Write-Host "Delete completed:" -ForegroundColor Green
        Write-Host "  Deleted: $deleted" -ForegroundColor Green
        Write-Host "  Failed: $deleteFailed" -ForegroundColor $(if ($deleteFailed -gt 0) { "Red" } else { "Green" })
    }
} else {
    Write-Host "[Step 5/5] Skipping file deletion" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "[SUCCESS] Bidirectional sync completed!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Summary:" -ForegroundColor Yellow
Write-Host "  Uploaded: $uploaded files" -ForegroundColor Green
Write-Host "  Deleted: $(if ($SkipDelete) { 'Skipped' } else { $filesToDelete.Count }) files" -ForegroundColor $(if ($SkipDelete) { "Yellow" } else { "Red" })
Write-Host ""

if ($DryRun) {
    Write-Host "This was a DRY RUN. No changes were made." -ForegroundColor Magenta
    Write-Host "Run without -DryRun to apply changes." -ForegroundColor Yellow
}
