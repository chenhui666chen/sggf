# GitHub Upload Script
# Usage: .\upload_to_github_simple.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Novel Writing Agent - GitHub Upload" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Git is installed
Write-Host "Checking Git..." -ForegroundColor Yellow
git --version 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Git is installed" -ForegroundColor Green
}
else {
    Write-Host "Git is not installed" -ForegroundColor Red
    Write-Host "Download from: https://git-scm.com/download/win" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if Git repository exists
Write-Host ""
Write-Host "Checking Git repository..." -ForegroundColor Yellow
if (-not (Test-Path .git)) {
    Write-Host "Initializing Git repository..." -ForegroundColor Yellow
    git init
    Write-Host "Git repository initialized" -ForegroundColor Green
}
else {
    Write-Host "Git repository exists" -ForegroundColor Green
}

# Check Git user configuration
Write-Host ""
Write-Host "Checking Git user configuration..." -ForegroundColor Yellow
$gitName = git config user.name 2>&1
if ([string]::IsNullOrWhiteSpace($gitName)) {
    Write-Host "Git user not configured" -ForegroundColor Yellow
    $gitName = Read-Host "Enter your name"
    git config --global user.name $gitName

    $gitEmail = Read-Host "Enter your email"
    git config --global user.email $gitEmail
    Write-Host "Git user configured" -ForegroundColor Green
}
else {
    Write-Host "Git user configured: $gitName" -ForegroundColor Green
}

# Show current status
Write-Host ""
Write-Host "Current Git status:" -ForegroundColor Cyan
git status

# Add all files
Write-Host ""
Write-Host "Adding all files..." -ForegroundColor Yellow
git add .
Write-Host "Files added" -ForegroundColor Green

# Create commit
Write-Host ""
Write-Host "Creating commit..." -ForegroundColor Yellow
$commitMsg = Read-Host "Enter commit message (default: Initial commit)"
if ([string]::IsNullOrWhiteSpace($commitMsg)) {
    $commitMsg = "Initial commit"
}

git commit -m $commitMsg
if ($LASTEXITCODE -ne 0) {
    Write-Host "No changes to commit" -ForegroundColor Yellow
}
else {
    Write-Host "Commit created" -ForegroundColor Green
}

# Check remote repository
Write-Host ""
Write-Host "Checking remote repository..." -ForegroundColor Yellow
$remoteUrl = git remote get-url origin 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Remote repository not configured" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Enter GitHub repository URL:" -ForegroundColor Cyan
    Write-Host "Example: https://github.com/username/novel_writing_agent.git" -ForegroundColor Gray
    $remoteUrl = Read-Host "GitHub repository URL"

    git remote add origin $remoteUrl
    Write-Host "Remote repository added" -ForegroundColor Green
}
else {
    Write-Host "Remote repository configured" -ForegroundColor Green
    Write-Host ""
    git remote -v
}

# Set branch to main
Write-Host ""
Write-Host "Setting branch to main..." -ForegroundColor Yellow
git branch -M main
Write-Host "Branch set to main" -ForegroundColor Green

# Push to GitHub
Write-Host ""
Write-Host "Pushing to GitHub..." -ForegroundColor Yellow
Write-Host "This may take a few seconds..." -ForegroundColor Gray
git push -u origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Push failed" -ForegroundColor Red
    Write-Host "Possible reasons:" -ForegroundColor Yellow
    Write-Host "1. Incorrect repository URL" -ForegroundColor Gray
    Write-Host "2. SSH key not configured" -ForegroundColor Gray
    Write-Host "3. Network connection issue" -ForegroundColor Gray
    Write-Host "4. GitHub authentication failed" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Solutions:" -ForegroundColor Yellow
    Write-Host "- Use HTTPS URL instead of SSH" -ForegroundColor Gray
    Write-Host "- Check network connection" -ForegroundColor Gray
    Write-Host "- Run the script again" -ForegroundColor Gray
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
else {
    Write-Host ""
    Write-Host "Push successful!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Project uploaded to GitHub!" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Repository URL:" -ForegroundColor Cyan
    $repoUrl = git remote get-url origin
    Write-Host $repoUrl -ForegroundColor Green
    Write-Host ""
    Write-Host "Upload complete!" -ForegroundColor Green
}

Read-Host "Press Enter to exit"


