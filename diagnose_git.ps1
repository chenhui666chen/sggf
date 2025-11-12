# Git Diagnostic Script
# Usage: .\diagnose_git.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Git Diagnostic Tool" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check 1: Git executable in PATH
Write-Host "Check 1: Looking for git in PATH..." -ForegroundColor Yellow
$gitPath = Get-Command git -ErrorAction SilentlyContinue
if ($gitPath) {
    Write-Host "Found git at: $($gitPath.Source)" -ForegroundColor Green
}
else {
    Write-Host "Git not found in PATH" -ForegroundColor Red
}

# Check 2: Common Git installation locations
Write-Host ""
Write-Host "Check 2: Checking common Git installation locations..." -ForegroundColor Yellow

$commonPaths = @(
    "C:\Program Files\Git\cmd\git.exe",
    "C:\Program Files (x86)\Git\cmd\git.exe",
    "C:\Program Files\Git\bin\git.exe",
    "C:\Program Files (x86)\Git\bin\git.exe"
)

foreach ($path in $commonPaths) {
    if (Test-Path $path) {
        Write-Host "Found: $path" -ForegroundColor Green
    }
}

# Check 3: PATH environment variable
Write-Host ""
Write-Host "Check 3: Current PATH environment variable..." -ForegroundColor Yellow
$pathVar = [Environment]::GetEnvironmentVariable("Path", "User")
Write-Host "User PATH:" -ForegroundColor Cyan
$pathVar -split ";" | ForEach-Object {
    if ($_ -like "*Git*") {
        Write-Host "  $_ (Git related)" -ForegroundColor Green
    }
    elseif ($_ -ne "") {
        Write-Host "  $_" -ForegroundColor Gray
    }
}

# Check 4: System PATH
Write-Host ""
Write-Host "Check 4: System PATH environment variable..." -ForegroundColor Yellow
$systemPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
Write-Host "System PATH:" -ForegroundColor Cyan
$systemPath -split ";" | ForEach-Object {
    if ($_ -like "*Git*") {
        Write-Host "  $_ (Git related)" -ForegroundColor Green
    }
    elseif ($_ -ne "") {
        Write-Host "  $_" -ForegroundColor Gray
    }
}

# Check 5: Try running git directly
Write-Host ""
Write-Host "Check 5: Trying to run git directly..." -ForegroundColor Yellow
try {
    $gitVersion = & "C:\Program Files\Git\cmd\git.exe" --version 2>&1
    Write-Host "Git version: $gitVersion" -ForegroundColor Green
}
catch {
    Write-Host "Could not run git directly" -ForegroundColor Red
}

# Check 6: Registry check
Write-Host ""
Write-Host "Check 6: Checking Windows Registry..." -ForegroundColor Yellow
$regPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
$gitInstalled = Get-ItemProperty $regPath | Where-Object { $_.DisplayName -like "*Git*" }
if ($gitInstalled) {
    Write-Host "Git found in Registry:" -ForegroundColor Green
    Write-Host "  Name: $($gitInstalled.DisplayName)" -ForegroundColor Green
    Write-Host "  Version: $($gitInstalled.DisplayVersion)" -ForegroundColor Green
    Write-Host "  Install Location: $($gitInstalled.InstallLocation)" -ForegroundColor Green
}
else {
    Write-Host "Git not found in Registry" -ForegroundColor Red
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Diagnostic Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($gitPath) {
    Write-Host "Status: Git is installed and accessible" -ForegroundColor Green
    Write-Host "Location: $($gitPath.Source)" -ForegroundColor Green
}
else {
    Write-Host "Status: Git is NOT accessible from PowerShell" -ForegroundColor Red
    Write-Host ""
    Write-Host "Solutions:" -ForegroundColor Yellow
    Write-Host "1. Restart PowerShell (close and reopen)" -ForegroundColor Gray
    Write-Host "2. Restart your computer" -ForegroundColor Gray
    Write-Host "3. Reinstall Git and select 'Add to PATH'" -ForegroundColor Gray
    Write-Host "4. Manually add Git to PATH (see next section)" -ForegroundColor Gray
}

Write-Host ""
Read-Host "Press Enter to exit"

