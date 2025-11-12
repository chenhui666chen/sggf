# Fix Git PATH Script
# Usage: .\fix_git_path.ps1
# Run as Administrator

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Git PATH Fix Tool" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    Write-Host ""
    Write-Host "How to run as Administrator:" -ForegroundColor Yellow
    Write-Host "1. Right-click on PowerShell" -ForegroundColor Gray
    Write-Host "2. Select 'Run as administrator'" -ForegroundColor Gray
    Write-Host "3. Run this script again" -ForegroundColor Gray
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Running as Administrator" -ForegroundColor Green
Write-Host ""

# Find Git installation
Write-Host "Looking for Git installation..." -ForegroundColor Yellow
$gitPaths = @(
    "C:\Program Files\Git\cmd",
    "C:\Program Files (x86)\Git\cmd",
    "C:\Program Files\Git\bin",
    "C:\Program Files (x86)\Git\bin"
)

$gitFound = $null
foreach ($path in $gitPaths) {
    if (Test-Path $path) {
        $gitFound = $path
        Write-Host "Found Git at: $gitFound" -ForegroundColor Green
        break
    }
}

if (-not $gitFound) {
    Write-Host "Git installation not found" -ForegroundColor Red
    Write-Host "Please install Git first from: https://git-scm.com/download/win" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if already in PATH
Write-Host ""
Write-Host "Checking if Git is already in PATH..." -ForegroundColor Yellow
$systemPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
if ($systemPath -like "*$gitFound*") {
    Write-Host "Git is already in system PATH" -ForegroundColor Green
    Write-Host ""
    Write-Host "Restarting PowerShell should fix the issue." -ForegroundColor Yellow
    Write-Host "Please close and reopen PowerShell." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 0
}

# Add to PATH
Write-Host ""
Write-Host "Adding Git to system PATH..." -ForegroundColor Yellow
$newPath = $systemPath + ";" + $gitFound
[Environment]::SetEnvironmentVariable("Path", $newPath, "Machine")
Write-Host "Git added to system PATH" -ForegroundColor Green

# Verify
Write-Host ""
Write-Host "Verifying..." -ForegroundColor Yellow
$updatedPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
if ($updatedPath -like "*$gitFound*") {
    Write-Host "Verification successful" -ForegroundColor Green
}
else {
    Write-Host "Verification failed" -ForegroundColor Red
}

# Instructions
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Next Steps" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Close this PowerShell window" -ForegroundColor Yellow
Write-Host "2. Close ALL PowerShell windows" -ForegroundColor Yellow
Write-Host "3. Open a new PowerShell window" -ForegroundColor Yellow
Write-Host "4. Run: git --version" -ForegroundColor Yellow
Write-Host "5. If successful, run: .\upload_to_github_simple.ps1" -ForegroundColor Yellow
Write-Host ""

Read-Host "Press Enter to exit"

