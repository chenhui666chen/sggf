# Setup SSH Passwordless Login
# This script configures SSH key authentication for automatic deployment

param(
    [string]$ServerIP = "101.132.154.143",
    [string]$ServerUser = "root"
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  SSH Passwordless Login Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check if SSH key exists
$keyPath = "$env:USERPROFILE\.ssh\id_rsa"
$pubKeyPath = "$env:USERPROFILE\.ssh\id_rsa.pub"

Write-Host "[Step 1/4] Checking SSH key..." -ForegroundColor Yellow

if (Test-Path $keyPath) {
    Write-Host "  SSH key already exists" -ForegroundColor Green
} else {
    Write-Host "  Generating new SSH key..." -ForegroundColor Yellow
    
    # Create .ssh directory if not exists
    $sshDir = "$env:USERPROFILE\.ssh"
    if (-not (Test-Path $sshDir)) {
        New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
    }
    
    # Generate SSH key (no passphrase for automation)
    ssh-keygen -t rsa -b 4096 -f $keyPath -N '""' -C "$env:USERNAME@$env:COMPUTERNAME"
    
    Write-Host "  SSH key generated successfully" -ForegroundColor Green
}

Write-Host ""

# Step 2: Read public key
Write-Host "[Step 2/4] Reading public key..." -ForegroundColor Yellow

$pubKey = Get-Content $pubKeyPath -Raw
Write-Host "  Public key loaded" -ForegroundColor Green
Write-Host ""

# Step 3: Copy key to server
Write-Host "[Step 3/4] Copying key to server..." -ForegroundColor Yellow
Write-Host "  You will need to enter your password ONE LAST TIME" -ForegroundColor Magenta
Write-Host ""

# Use ssh-copy-id equivalent
$command = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pubKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

ssh $ServerUser@$ServerIP $command

if ($LASTEXITCODE -eq 0) {
    Write-Host "  Key copied to server successfully" -ForegroundColor Green
} else {
    Write-Host "  Failed to copy key" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Step 4: Test passwordless login
Write-Host "[Step 4/4] Testing passwordless login..." -ForegroundColor Yellow

$result = ssh -o BatchMode=yes -o ConnectTimeout=5 $ServerUser@$ServerIP "echo 'Passwordless login successful!'"

if ($LASTEXITCODE -eq 0) {
    Write-Host "  $result" -ForegroundColor Green
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "[SUCCESS] SSH passwordless login configured!" -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "You can now run deployment scripts without entering password!" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host "  Passwordless login test failed" -ForegroundColor Red
    Write-Host "  Please check the configuration" -ForegroundColor Red
    exit 1
}
