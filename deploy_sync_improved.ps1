# Novel Writing Agent - Improved Bidirectional Deployment Script
# Features:
# - Config-driven file selection
# - Bidirectional sync with remote deletion
# - Archive-first uploads with per-file fallback
# - Backend/frontend rebuild and restart
# - Basic deployment validation
# - Auto-detect remote docker compose command

param(
    [string]$ConfigFile = "deploy_config.json",
    [string]$ServerIP = "",
    [string]$ServerUser = "",
    [string]$LocalPath = "",
    [string]$RemotePath = "",
    [ValidateSet("Auto", "Archive", "PerFile")]
    [string]$UploadStrategy = "Auto",
    [int]$MaxRetries = 3,
    [int]$TimeoutSeconds = 30,
    [switch]$DryRun = $false,
    [switch]$SkipDelete = $false,
    [switch]$SkipBuild = $false,
    [switch]$SkipValidation = $false
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Get-PropertyValue {
    param(
        [Parameter(Mandatory = $false)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $false)]$Default = $null
    )

    if ($null -eq $Object) {
        return $Default
    }

    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) {
            return $Object[$Name]
        }
        return $Default
    }

    if ($Object.PSObject.Properties.Match($Name).Count -gt 0) {
        return $Object.$Name
    }

    return $Default
}

function Normalize-RelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $normalized = $Path.Replace("\", "/")
    while ($normalized.StartsWith("./")) {
        $normalized = $normalized.Substring(2)
    }
    return $normalized.TrimStart("/")
}

function Quote-Posix {
    param([Parameter(Mandatory = $true)][string]$Value)

    return "'" + $Value.Replace("'", "'""'""'") + "'"
}

function Format-ByteSize {
    param([Parameter(Mandatory = $true)][long]$Bytes)

    if ($Bytes -ge 1GB) {
        return "{0:N2} GB" -f ($Bytes / 1GB)
    }
    if ($Bytes -ge 1MB) {
        return "{0:N2} MB" -f ($Bytes / 1MB)
    }
    if ($Bytes -ge 1KB) {
        return "{0:N2} KB" -f ($Bytes / 1KB)
    }

    return "$Bytes B"
}

function Test-MatchesAnyPattern {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $false)][AllowEmptyCollection()][string[]]$Patterns = @()
    )

    if ($null -eq $Patterns -or $Patterns.Count -eq 0) {
        return $false
    }

    $normalizedPath = Normalize-RelativePath $RelativePath

    foreach ($pattern in $Patterns) {
        $regexPattern = Convert-GlobToRegex -Pattern $pattern
        if ([System.Text.RegularExpressions.Regex]::IsMatch($normalizedPath, $regexPattern)) {
            return $true
        }
    }

    return $false
}

function Convert-GlobToRegex {
    param(
        [Parameter(Mandatory = $true)][string]$Pattern
    )

    $normalizedPattern = Normalize-RelativePath $Pattern
    $builder = New-Object System.Text.StringBuilder
    $index = 0

    while ($index -lt $normalizedPattern.Length) {
        if (($index + 2) -lt $normalizedPattern.Length -and $normalizedPattern.Substring($index, 3) -eq "**/") {
            $null = $builder.Append("(?:.*/)?")
            $index += 3
            continue
        }

        if (($index + 1) -lt $normalizedPattern.Length -and $normalizedPattern.Substring($index, 2) -eq "**") {
            $null = $builder.Append(".*")
            $index += 2
            continue
        }

        $char = $normalizedPattern[$index]
        switch ($char) {
            '*' {
                $null = $builder.Append("[^/]*")
                break
            }
            '?' {
                $null = $builder.Append("[^/]")
                break
            }
            default {
                $null = $builder.Append([System.Text.RegularExpressions.Regex]::Escape([string]$char))
                break
            }
        }

        $index += 1
    }

    return "^$builder$"
}

function Merge-UniqueStrings {
    param(
        [Parameter(Mandatory = $false)][string[]]$Primary = @(),
        [Parameter(Mandatory = $false)][string[]]$Secondary = @()
    )

    $result = New-Object System.Collections.Generic.List[string]
    foreach ($item in @($Primary) + @($Secondary)) {
        if ([string]::IsNullOrWhiteSpace($item)) {
            continue
        }
        if (-not $result.Contains($item)) {
            $null = $result.Add($item)
        }
    }
    return $result.ToArray()
}

function Test-ShouldSyncFile {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)]$SyncSections
    )

    foreach ($section in $SyncSections.Values) {
        $includePatterns = @($section.include)
        $excludePatterns = @($section.exclude)

        if ((Test-MatchesAnyPattern -RelativePath $RelativePath -Patterns $includePatterns) -and
            (-not (Test-MatchesAnyPattern -RelativePath $RelativePath -Patterns $excludePatterns))) {
            return $true
        }
    }

    return $false
}

function Get-DefaultSyncSections {
    return @{
        backend = @{
            include = @(
                "backend/app/**/*.py",
                "backend/app/**/*.json",
                "backend/alembic/**/*.py",
                "backend/backend/data/**/*.json",
                "backend/*.ini",
                "backend/*.txt",
                "backend/*.json",
                "backend/Dockerfile"
            )
            exclude = @(
                "backend/**/__pycache__/**",
                "backend/**/*.pyc",
                "backend/.venv/**",
                "backend/data/**",
                "backend/memory_data/**",
                "backend/runs/**"
            )
        }
        frontend = @{
            include = @(
                "frontend/src/**/*.tsx",
                "frontend/src/**/*.ts",
                "frontend/src/**/*.css",
                "frontend/public/**/*",
                "frontend/*.json",
                "frontend/*.js",
                "frontend/*.ts",
                "frontend/*.mjs",
                "frontend/*.cjs",
                "frontend/*.html",
                "frontend/Dockerfile"
            )
            exclude = @(
                "frontend/node_modules/**",
                "frontend/.next/**",
                "frontend/dist/**",
                "frontend/build/**"
            )
        }
        shared = @{
            include = @(
                "agents/**/*.py",
                "adapters/**/*.py",
                "pipeline/**/*.py",
                "shared/**/*.py",
                "core/**/*.py",
                "schemas/**/*.py",
                "config/**/*.json",
                "config/**/*.yml",
                "config/**/*.yaml",
                "docker-compose.yml",
                "nginx-prod.conf",
                ".env.example",
                "deploy_config.json"
            )
            exclude = @()
        }
    }
}

function Get-SyncSections {
    param(
        [Parameter(Mandatory = $true)]$ConfigRoot
    )

    $defaults = Get-DefaultSyncSections
    $resolved = @{}
    $configuredRules = Get-PropertyValue -Object $ConfigRoot -Name "sync_rules" -Default $null

    foreach ($sectionName in $defaults.Keys) {
        $configuredSection = Get-PropertyValue -Object $configuredRules -Name $sectionName -Default $null
        $defaultSection = $defaults[$sectionName]

        $resolved[$sectionName] = @{
            include = Merge-UniqueStrings -Primary @($defaultSection.include) -Secondary @((Get-PropertyValue -Object $configuredSection -Name "include" -Default @()))
            exclude = Merge-UniqueStrings -Primary @($defaultSection.exclude) -Secondary @((Get-PropertyValue -Object $configuredSection -Name "exclude" -Default @()))
        }
    }

    if ($null -ne $configuredRules) {
        foreach ($property in $configuredRules.PSObject.Properties) {
            if ($resolved.ContainsKey($property.Name)) {
                continue
            }

            $resolved[$property.Name] = @{
                include = @((Get-PropertyValue -Object $property.Value -Name "include" -Default @()))
                exclude = @((Get-PropertyValue -Object $property.Value -Name "exclude" -Default @()))
            }
        }
    }

    return $resolved
}

function Get-ScanSpecs {
    param(
        [Parameter(Mandatory = $true)]$SyncSections
    )

    $scanSpecMap = @{}

    foreach ($section in $SyncSections.Values) {
        foreach ($pattern in @($section.include)) {
            if ([string]::IsNullOrWhiteSpace($pattern)) {
                continue
            }

            $normalizedPattern = Normalize-RelativePath $pattern
            $specType = ""
            $specPath = ""

            if ($normalizedPattern -notmatch "[\*\?]") {
                $specType = "file"
                $specPath = $normalizedPattern
            } elseif ($normalizedPattern.Contains("**")) {
                $doubleWildcardIndex = $normalizedPattern.IndexOf("**")
                $specType = "dir_recursive"
                $specPath = $normalizedPattern.Substring(0, $doubleWildcardIndex).TrimEnd("/")
                if ([string]::IsNullOrWhiteSpace($specPath)) {
                    $specPath = "."
                }
            } else {
                $specType = "dir_flat"
                $specPath = Normalize-RelativePath (Split-Path $normalizedPattern -Parent)
                if ([string]::IsNullOrWhiteSpace($specPath)) {
                    $specPath = "."
                }
            }

            $specKey = "$specType|$specPath"
            if (-not $scanSpecMap.ContainsKey($specKey)) {
                $scanSpecMap[$specKey] = [PSCustomObject]@{
                    Type = $specType
                    Path = $specPath
                }
            }
        }
    }

    return @($scanSpecMap.Values | Sort-Object Type, Path)
}

function Get-LocalFileMap {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)]$SyncSections
    )

    $fileMap = @{}
    $scanSpecs = Get-ScanSpecs -SyncSections $SyncSections

    foreach ($scanSpec in $scanSpecs) {
        $targetPath = if ($scanSpec.Path -eq ".") {
            $BasePath
        } else {
            Join-Path $BasePath ($scanSpec.Path.Replace("/", [System.IO.Path]::DirectorySeparatorChar))
        }

        switch ($scanSpec.Type) {
            "file" {
                if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
                    continue
                }

                $relativePath = Normalize-RelativePath($targetPath.Substring($BasePath.Length).TrimStart([char[]]"\/"))
                if (Test-ShouldSyncFile -RelativePath $relativePath -SyncSections $SyncSections) {
                    $fileMap[$relativePath] = $targetPath
                }
            }
            "dir_flat" {
                if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
                    continue
                }

                $files = Get-ChildItem -LiteralPath $targetPath -File
                foreach ($file in $files) {
                    $relativePath = Normalize-RelativePath($file.FullName.Substring($BasePath.Length).TrimStart([char[]]"\/"))
                    if (Test-ShouldSyncFile -RelativePath $relativePath -SyncSections $SyncSections) {
                        $fileMap[$relativePath] = $file.FullName
                    }
                }
            }
            "dir_recursive" {
                if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
                    continue
                }

                $files = Get-ChildItem -LiteralPath $targetPath -Recurse -File
                foreach ($file in $files) {
                    $relativePath = Normalize-RelativePath($file.FullName.Substring($BasePath.Length).TrimStart([char[]]"\/"))
                    if (Test-ShouldSyncFile -RelativePath $relativePath -SyncSections $SyncSections) {
                        $fileMap[$relativePath] = $file.FullName
                    }
                }
            }
        }
    }

    return $fileMap
}

function Get-RemoteFileSet {
    param(
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][string]$HostPath,
        [Parameter(Mandatory = $true)]$SyncSections,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    $remoteSet = @{}
    $scanSpecs = Get-ScanSpecs -SyncSections $SyncSections
    $quotedRemotePath = Quote-Posix $HostPath
    $commandParts = @("cd $quotedRemotePath 2>/dev/null || exit 0")

    foreach ($scanSpec in $scanSpecs) {
        $quotedScanPath = Quote-Posix $scanSpec.Path

        switch ($scanSpec.Type) {
            "file" {
                $commandParts += "if [ -f $quotedScanPath ]; then printf '%s\n' $quotedScanPath; fi"
            }
            "dir_flat" {
                if ($scanSpec.Path -eq ".") {
                    $commandParts += "find . -maxdepth 1 -type f -print 2>/dev/null"
                } else {
                    $commandParts += "if [ -d $quotedScanPath ]; then find $quotedScanPath -maxdepth 1 -type f -print 2>/dev/null; fi"
                }
            }
            "dir_recursive" {
                if ($scanSpec.Path -eq ".") {
                    $commandParts += "find . -type f -print 2>/dev/null"
                } else {
                    $commandParts += "if [ -d $quotedScanPath ]; then find $quotedScanPath -type f -print 2>/dev/null; fi"
                }
            }
        }
    }

    $findCommand = $commandParts -join "; "
    $remoteFiles = ssh -o ConnectTimeout=$ConnectTimeout "$HostUser@$HostIP" $findCommand 2>&1

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to scan remote files: $remoteFiles"
    }

    foreach ($file in $remoteFiles) {
        $relativePath = Normalize-RelativePath($file)
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }
        if (Test-ShouldSyncFile -RelativePath $relativePath -SyncSections $SyncSections) {
            $remoteSet[$relativePath] = $true
        }
    }

    return $remoteSet
}

function Ensure-RemoteDirectories {
    param(
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][string]$HostPath,
        [Parameter(Mandatory = $true)]$LocalFileMap,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    $directories = New-Object System.Collections.Generic.HashSet[string]
    $null = $directories.Add($HostPath.TrimEnd("/"))

    foreach ($relativePath in $LocalFileMap.Keys) {
        $directory = Split-Path $relativePath -Parent
        if ([string]::IsNullOrWhiteSpace($directory)) {
            continue
        }

        $normalizedDirectory = Normalize-RelativePath $directory
        $null = $directories.Add(($HostPath.TrimEnd("/") + "/" + $normalizedDirectory))
    }

    $quotedDirectories = $directories | Sort-Object | ForEach-Object { Quote-Posix $_ }
    $mkdirCommand = "mkdir -p " + ($quotedDirectories -join " ")
    $null = ssh -o ConnectTimeout=$ConnectTimeout "$HostUser@$HostIP" $mkdirCommand 2>&1

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create remote directories."
    }
}

function Invoke-RemoteCommand {
    param(
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()

    try {
        $process = Start-Process -FilePath "ssh" `
            -ArgumentList @("-o", "ConnectTimeout=$ConnectTimeout", "$HostUser@$HostIP", $Command) `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile

        $stdout = if (Test-Path $stdoutFile) {
            Get-Content -Path $stdoutFile -Raw -Encoding utf8
        } else {
            ""
        }
        $stderr = if (Test-Path $stderrFile) {
            Get-Content -Path $stderrFile -Raw -Encoding utf8
        } else {
            ""
        }

        $combined = @($stdout, $stderr) -join ""
    } finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
    }

    return [PSCustomObject]@{
        Output = $combined
        ExitCode = $process.ExitCode
    }
}

function Invoke-LocalProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $false)][string]$WorkingDirectory = ""
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    $process = $null

    try {
        $startProcessArgs = @{
            FilePath               = $FilePath
            ArgumentList           = $ArgumentList
            NoNewWindow            = $true
            Wait                   = $true
            PassThru               = $true
            RedirectStandardOutput = $stdoutFile
            RedirectStandardError  = $stderrFile
        }

        if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
            $startProcessArgs.WorkingDirectory = $WorkingDirectory
        }

        $process = Start-Process @startProcessArgs

        $stdout = if (Test-Path $stdoutFile) {
            Get-Content -Path $stdoutFile -Raw -Encoding utf8
        } else {
            ""
        }
        $stderr = if (Test-Path $stderrFile) {
            Get-Content -Path $stderrFile -Raw -Encoding utf8
        } else {
            ""
        }

        $combined = @($stdout, $stderr) -join ""
    } finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
    }

    return [PSCustomObject]@{
        Output   = $combined
        ExitCode = if ($null -ne $process) { $process.ExitCode } else { 1 }
    }
}

function Test-LocalCommandAvailable {
    param([Parameter(Mandatory = $true)][string]$CommandName)

    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

function Get-RemoteDockerComposeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    $detectCommand = "if docker compose version >/dev/null 2>&1; then printf 'docker compose'; elif command -v docker-compose >/dev/null 2>&1; then printf 'docker-compose'; else exit 1; fi"
    $detectResult = Invoke-RemoteCommand -HostUser $HostUser -HostIP $HostIP -Command $detectCommand -ConnectTimeout $ConnectTimeout

    if ($detectResult.ExitCode -ne 0) {
        throw "Remote Docker Compose command not found. Install 'docker compose' plugin or 'docker-compose'."
    }

    $composeCommand = $detectResult.Output.Trim()
    if ([string]::IsNullOrWhiteSpace($composeCommand)) {
        throw "Remote Docker Compose detection returned an empty result."
    }

    return $composeCommand
}

function Test-RemoteTarAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    $checkResult = Invoke-RemoteCommand -HostUser $HostUser -HostIP $HostIP -Command "command -v tar >/dev/null 2>&1" -ConnectTimeout $ConnectTimeout
    return $checkResult.ExitCode -eq 0
}

function Resolve-UploadStrategy {
    param(
        [Parameter(Mandatory = $true)][string]$PreferredStrategy,
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    if ($PreferredStrategy -eq "PerFile") {
        return [PSCustomObject]@{
            Strategy = "PerFile"
            Reason   = "Upload strategy forced to PerFile."
        }
    }

    $hasLocalTar = Test-LocalCommandAvailable -CommandName "tar"
    $hasRemoteTar = Test-RemoteTarAvailable -HostUser $HostUser -HostIP $HostIP -ConnectTimeout $ConnectTimeout

    if ($PreferredStrategy -eq "Archive") {
        if (-not $hasLocalTar) {
            throw "Upload strategy 'Archive' requires local 'tar', but it was not found."
        }
        if (-not $hasRemoteTar) {
            throw "Upload strategy 'Archive' requires remote 'tar', but it was not found."
        }

        return [PSCustomObject]@{
            Strategy = "Archive"
            Reason   = "Upload strategy forced to Archive and local/remote tar are available."
        }
    }

    if ($hasLocalTar -and $hasRemoteTar) {
        return [PSCustomObject]@{
            Strategy = "Archive"
            Reason   = "Auto-selected archive upload because local and remote tar are available."
        }
    }

    $missingParts = New-Object System.Collections.Generic.List[string]
    if (-not $hasLocalTar) {
        $null = $missingParts.Add("local tar")
    }
    if (-not $hasRemoteTar) {
        $null = $missingParts.Add("remote tar")
    }

    return [PSCustomObject]@{
        Strategy = "PerFile"
        Reason   = "Falling back to per-file upload because " + ($missingParts -join " and ") + " is unavailable."
    }
}

function New-DeploymentArchive {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)]$LocalFileMap
    )

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("novel_deploy_" + [System.Guid]::NewGuid().ToString("N"))
    $stageRoot = Join-Path $tempRoot "payload"
    $archivePath = Join-Path $tempRoot "payload.tar.gz"

    New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

    foreach ($relativePath in ($LocalFileMap.Keys | Sort-Object)) {
        $sourceFile = $LocalFileMap[$relativePath]
        $destinationFile = Join-Path $stageRoot ($relativePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar))
        $destinationDirectory = Split-Path $destinationFile -Parent

        if (-not [string]::IsNullOrWhiteSpace($destinationDirectory)) {
            New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        }

        Copy-Item -LiteralPath $sourceFile -Destination $destinationFile -Force
    }

    $tarResult = Invoke-LocalProcess -FilePath "tar" -ArgumentList @("-czf", $archivePath, "-C", $stageRoot, ".") -WorkingDirectory $BasePath
    if ($tarResult.ExitCode -ne 0 -or -not (Test-Path $archivePath)) {
        throw "Failed to create deployment archive: $($tarResult.Output)"
    }

    $archiveItem = Get-Item -LiteralPath $archivePath
    return [PSCustomObject]@{
        TempRoot    = $tempRoot
        StageRoot   = $stageRoot
        ArchivePath = $archivePath
        SizeBytes   = [int64]$archiveItem.Length
        FileCount   = $LocalFileMap.Count
    }
}

function Upload-FilesPerFile {
    param(
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][string]$HostPath,
        [Parameter(Mandatory = $true)]$LocalFileMap,
        [Parameter(Mandatory = $true)][int]$MaxRetryCount,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    Ensure-RemoteDirectories -HostUser $HostUser -HostIP $HostIP -HostPath $HostPath -LocalFileMap $LocalFileMap -ConnectTimeout $ConnectTimeout

    $uploaded = 0
    $failed = 0
    $failedFiles = @()

    foreach ($relativePath in ($LocalFileMap.Keys | Sort-Object)) {
        $localFile = $LocalFileMap[$relativePath]
        $remoteFile = "${HostUser}@${HostIP}:$($HostPath.TrimEnd('/'))/$relativePath"

        Write-Host "  Uploading: $relativePath" -NoNewline

        $success = $false
        for ($attempt = 1; $attempt -le $MaxRetryCount; $attempt++) {
            $scpResult = Invoke-LocalProcess -FilePath "scp" -ArgumentList @(
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=$ConnectTimeout",
                $localFile,
                $remoteFile
            )

            if ($scpResult.ExitCode -eq 0) {
                $success = $true
                break
            }

            if ($attempt -lt $MaxRetryCount) {
                Write-Host " [retry $attempt/$MaxRetryCount]" -ForegroundColor Yellow -NoNewline
                Start-Sleep -Seconds 2
            }
        }

        if ($success) {
            $uploaded++
            Write-Host " [OK]" -ForegroundColor Green
        } else {
            $failed++
            $failedFiles += $relativePath
            Write-Host " [FAILED]" -ForegroundColor Red
        }
    }

    return [PSCustomObject]@{
        Uploaded    = $uploaded
        Failed      = $failed
        FailedFiles = $failedFiles
    }
}

function Upload-FilesByArchive {
    param(
        [Parameter(Mandatory = $true)][string]$HostUser,
        [Parameter(Mandatory = $true)][string]$HostIP,
        [Parameter(Mandatory = $true)][string]$HostPath,
        [Parameter(Mandatory = $true)]$ArchiveInfo,
        [Parameter(Mandatory = $true)][int]$MaxRetryCount,
        [Parameter(Mandatory = $true)][int]$ConnectTimeout
    )

    $remoteArchivePath = "/tmp/novel_deploy_" + [System.Guid]::NewGuid().ToString("N") + ".tar.gz"
    Write-Host "  Packaging selected files into archive..." -ForegroundColor Cyan
    Write-Host "  Archive size: $(Format-ByteSize -Bytes $ArchiveInfo.SizeBytes)" -ForegroundColor Cyan
    Write-Host "  Uploading archive to remote host..." -ForegroundColor Cyan

    $success = $false
    for ($attempt = 1; $attempt -le $MaxRetryCount; $attempt++) {
        $scpResult = Invoke-LocalProcess -FilePath "scp" -ArgumentList @(
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=$ConnectTimeout",
            $ArchiveInfo.ArchivePath,
            "${HostUser}@${HostIP}:$remoteArchivePath"
        )

        if ($scpResult.ExitCode -eq 0) {
            $success = $true
            break
        }

        if ($attempt -lt $MaxRetryCount) {
            Write-Host "  Archive upload retry $attempt/$MaxRetryCount" -ForegroundColor Yellow
            Start-Sleep -Seconds 2
        } else {
            throw "Archive upload failed: $($scpResult.Output)"
        }
    }

    if (-not $success) {
        throw "Archive upload failed for unknown reasons."
    }

    $quotedRemotePath = Quote-Posix $HostPath
    $quotedRemoteArchivePath = Quote-Posix $remoteArchivePath
    $extractCommand = "mkdir -p $quotedRemotePath && tar -xzf $quotedRemoteArchivePath -C $quotedRemotePath && rm -f $quotedRemoteArchivePath"
    $extractResult = Invoke-RemoteCommand -HostUser $HostUser -HostIP $HostIP -Command $extractCommand -ConnectTimeout $ConnectTimeout

    if ($extractResult.ExitCode -ne 0) {
        $cleanupCommand = "rm -f $quotedRemoteArchivePath"
        $null = Invoke-RemoteCommand -HostUser $HostUser -HostIP $HostIP -Command $cleanupCommand -ConnectTimeout $ConnectTimeout
        throw "Archive extraction failed: $($extractResult.Output)"
    }

    return [PSCustomObject]@{
        Uploaded    = $ArchiveInfo.FileCount
        Failed      = 0
        FailedFiles = @()
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($LocalPath)) {
    $LocalPath = $scriptRoot
}

$LocalPath = (Resolve-Path $LocalPath).Path.TrimEnd("\")
$configPath = Join-Path $LocalPath $ConfigFile
$configRoot = $null

if (Test-Path $configPath) {
    $configRoot = Get-Content -Path $configPath -Raw -Encoding utf8 | ConvertFrom-Json
}

$serverConfig = Get-PropertyValue -Object $configRoot -Name "server" -Default $null
$uploadConfig = Get-PropertyValue -Object $configRoot -Name "upload" -Default $null
$validationConfig = Get-PropertyValue -Object $configRoot -Name "validation" -Default $null

if ([string]::IsNullOrWhiteSpace($ServerIP)) {
    $ServerIP = Get-PropertyValue -Object $serverConfig -Name "ip" -Default "101.132.154.143"
}

if ([string]::IsNullOrWhiteSpace($ServerUser)) {
    $ServerUser = Get-PropertyValue -Object $serverConfig -Name "user" -Default "root"
}

if ([string]::IsNullOrWhiteSpace($RemotePath)) {
    $RemotePath = Get-PropertyValue -Object $serverConfig -Name "remote_path" -Default "/data/apps/novel_writing_agent"
}

if (-not $PSBoundParameters.ContainsKey("UploadStrategy")) {
    $UploadStrategy = Get-PropertyValue -Object $uploadConfig -Name "strategy" -Default $UploadStrategy
}

$apiEndpoint = Get-PropertyValue -Object $validationConfig -Name "api_endpoint" -Default "/api/v1/health"

$syncSections = Get-SyncSections -ConfigRoot $configRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Improved Bidirectional Deployment v3.0" -ForegroundColor Cyan
Write-Host "  Sync + Delete + Build + Validate" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Server: $ServerUser@$ServerIP" -ForegroundColor Yellow
Write-Host "Local:  $LocalPath" -ForegroundColor Yellow
Write-Host "Remote: $RemotePath" -ForegroundColor Yellow
Write-Host "DryRun: $DryRun" -ForegroundColor Yellow
Write-Host ""

Set-Location $LocalPath

Write-Host "[Preflight] Detecting remote Docker Compose command..." -ForegroundColor Yellow
$composeCommand = Get-RemoteDockerComposeCommand -HostUser $ServerUser -HostIP $ServerIP -ConnectTimeout $TimeoutSeconds
Write-Host "  Remote Compose command: $composeCommand" -ForegroundColor Green
Write-Host ""

Write-Host "[Preflight] Resolving upload strategy..." -ForegroundColor Yellow
$resolvedUploadStrategy = Resolve-UploadStrategy -PreferredStrategy $UploadStrategy -HostUser $ServerUser -HostIP $ServerIP -ConnectTimeout $TimeoutSeconds
$effectiveUploadStrategy = $resolvedUploadStrategy.Strategy
Write-Host "  Upload strategy: $effectiveUploadStrategy" -ForegroundColor Green
Write-Host "  Reason: $($resolvedUploadStrategy.Reason)" -ForegroundColor DarkGray
Write-Host ""

Write-Host "[Step 1/7] Scanning local files..." -ForegroundColor Yellow
$localFileMap = Get-LocalFileMap -BasePath $LocalPath -SyncSections $syncSections
if ($localFileMap.Count -eq 0) {
    throw "No files matched the configured sync rules. Deployment stopped."
}
Write-Host "  Local files selected: $($localFileMap.Count)" -ForegroundColor Green
Write-Host ""

Write-Host "[Step 2/7] Scanning remote files..." -ForegroundColor Yellow
$remoteFileSet = Get-RemoteFileSet -HostUser $ServerUser -HostIP $ServerIP -HostPath $RemotePath -SyncSections $syncSections -ConnectTimeout $TimeoutSeconds
Write-Host "  Remote files selected: $($remoteFileSet.Count)" -ForegroundColor Green
Write-Host ""

Write-Host "[Step 3/7] Calculating remote deletions..." -ForegroundColor Yellow
$filesToDelete = @($remoteFileSet.Keys | Where-Object { -not $localFileMap.ContainsKey($_) } | Sort-Object)
if ($filesToDelete.Count -gt 0) {
    Write-Host "  Remote files to delete: $($filesToDelete.Count)" -ForegroundColor Red
    foreach ($file in $filesToDelete) {
        Write-Host "    - $file" -ForegroundColor Red
    }
} else {
    Write-Host "  No remote files need deletion" -ForegroundColor Green
}
Write-Host ""

if ($DryRun) {
    Write-Host "[Step 4/7] Dry run mode - skipping upload" -ForegroundColor Magenta
    Write-Host "[Step 5/7] Dry run mode - skipping delete" -ForegroundColor Magenta
    Write-Host "[Step 6/7] Dry run mode - skipping build/restart" -ForegroundColor Magenta
    Write-Host "[Step 7/7] Dry run mode - skipping validation" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "Dry run completed. No changes were made." -ForegroundColor Magenta
    exit 0
}

Write-Host "[Step 4/7] Uploading files..." -ForegroundColor Yellow
$uploadResult = $null
$archiveInfo = $null

try {
    if ($effectiveUploadStrategy -eq "Archive") {
        $archiveInfo = New-DeploymentArchive -BasePath $LocalPath -LocalFileMap $localFileMap
        $uploadResult = Upload-FilesByArchive -HostUser $ServerUser -HostIP $ServerIP -HostPath $RemotePath -ArchiveInfo $archiveInfo -MaxRetryCount $MaxRetries -ConnectTimeout $TimeoutSeconds
    } else {
        $uploadResult = Upload-FilesPerFile -HostUser $ServerUser -HostIP $ServerIP -HostPath $RemotePath -LocalFileMap $localFileMap -MaxRetryCount $MaxRetries -ConnectTimeout $TimeoutSeconds
    }
} finally {
    if ($null -ne $archiveInfo -and -not [string]::IsNullOrWhiteSpace($archiveInfo.TempRoot) -and (Test-Path $archiveInfo.TempRoot)) {
        Remove-Item -LiteralPath $archiveInfo.TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$uploaded = $uploadResult.Uploaded
$failed = $uploadResult.Failed
$failedFiles = @($uploadResult.FailedFiles)

Write-Host ""
Write-Host "Upload summary:" -ForegroundColor Yellow
Write-Host "  Success: $uploaded" -ForegroundColor Green
Write-Host "  Failed:  $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })

if ($failedFiles.Count -gt 0) {
    Write-Host ""
    Write-Host "Failed uploads:" -ForegroundColor Red
    foreach ($file in $failedFiles) {
        Write-Host "  - $file" -ForegroundColor Red
    }
    throw "Upload step failed. Deployment stopped."
}

Write-Host ""
Write-Host "[Step 5/7] Deleting remote files..." -ForegroundColor Yellow
if ($SkipDelete) {
    Write-Host "  Skipped by parameter" -ForegroundColor Yellow
} elseif ($filesToDelete.Count -eq 0) {
    Write-Host "  Nothing to delete" -ForegroundColor Green
} else {
    $deleteCommands = $filesToDelete | ForEach-Object {
        "rm -f " + (Quote-Posix ($RemotePath.TrimEnd("/") + "/" + $_))
    }
    $deleteCommands += "find " + (Quote-Posix $RemotePath) + " -type d -empty -delete"
    $deleteCommand = $deleteCommands -join "; "

    $deleteResult = Invoke-RemoteCommand -HostUser $ServerUser -HostIP $ServerIP -Command $deleteCommand -ConnectTimeout $TimeoutSeconds
    if ($deleteResult.ExitCode -ne 0) {
        throw "Remote delete failed: $($deleteResult.Output)"
    }

    Write-Host "  Deleted remote files: $($filesToDelete.Count)" -ForegroundColor Green
}

Write-Host ""
Write-Host "[Step 6/7] Rebuilding and restarting services..." -ForegroundColor Yellow
if ($SkipBuild) {
    Write-Host "  Skipped by parameter" -ForegroundColor Yellow
} else {
    $quotedRemotePath = Quote-Posix $RemotePath
    $deployCommand = "cd $quotedRemotePath && $composeCommand up -d --build backend frontend && $composeCommand up -d nginx"
    $deployResult = Invoke-RemoteCommand -HostUser $ServerUser -HostIP $ServerIP -Command $deployCommand -ConnectTimeout 60

    if ($deployResult.ExitCode -ne 0) {
        throw "Service rebuild/restart failed: $($deployResult.Output)"
    }

    Write-Host "  Services rebuilt and restarted" -ForegroundColor Green
}

Write-Host ""
Write-Host "[Step 7/7] Validating deployment..." -ForegroundColor Yellow
if ($SkipValidation) {
    Write-Host "  Skipped by parameter" -ForegroundColor Yellow
} else {
    Start-Sleep -Seconds 10

    $quotedRemotePath = Quote-Posix $RemotePath
    $statusResult = Invoke-RemoteCommand -HostUser $ServerUser -HostIP $ServerIP -Command "cd $quotedRemotePath && $composeCommand ps" -ConnectTimeout $TimeoutSeconds
    Write-Host "  Container status:" -ForegroundColor Cyan
    $statusResult.Output | ForEach-Object { Write-Host "    $_" }

    $healthCommand = "curl -fsS http://127.0.0.1:8000$apiEndpoint"
    $healthResult = $null
    $maxHealthAttempts = 6

    for ($attempt = 1; $attempt -le $maxHealthAttempts; $attempt++) {
        $healthResult = Invoke-RemoteCommand -HostUser $ServerUser -HostIP $ServerIP -Command $healthCommand -ConnectTimeout $TimeoutSeconds
        if ($healthResult.ExitCode -eq 0) {
            break
        }

        if ($attempt -lt $maxHealthAttempts) {
            Start-Sleep -Seconds 5
        }
    }

    if ($null -eq $healthResult -or $healthResult.ExitCode -ne 0) {
        throw "Backend health check failed after $maxHealthAttempts attempts: $($healthResult.Output)"
    }

    Write-Host "  Backend health check: $($healthResult.Output)" -ForegroundColor Green

    $storageDriverCommand = "cd $quotedRemotePath && $composeCommand exec -T backend printenv AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER"
    $storageDriverResult = Invoke-RemoteCommand -HostUser $ServerUser -HostIP $ServerIP -Command $storageDriverCommand -ConnectTimeout $TimeoutSeconds
    $storageDriver = $storageDriverResult.Output.Trim()
    if ($storageDriverResult.ExitCode -ne 0 -or $storageDriver -ne "aliyun_oss") {
        throw "Audio library storage driver validation failed. Expected 'aliyun_oss', got '$storageDriver'. TTS preview shared cache requires a HEAD-capable OSS driver."
    }

    Write-Host "  Audio library storage driver: $storageDriver" -ForegroundColor Green

    $requiredOssEnvNames = @(
        "AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET",
        "AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT",
        "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID",
        "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET"
    )
    $missingOssEnvNames = New-Object System.Collections.Generic.List[string]
    foreach ($envName in $requiredOssEnvNames) {
        $envCommand = "cd $quotedRemotePath && $composeCommand exec -T backend printenv $envName"
        $envResult = Invoke-RemoteCommand -HostUser $ServerUser -HostIP $ServerIP -Command $envCommand -ConnectTimeout $TimeoutSeconds
        if ($envResult.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($envResult.Output.Trim())) {
            $null = $missingOssEnvNames.Add($envName)
        }
    }

    if ($missingOssEnvNames.Count -gt 0) {
        throw "Aliyun OSS audio library config missing in backend container: $($missingOssEnvNames -join ', '). TTS preview shared cache requires these variables for OSS HEAD checks."
    }

    Write-Host "  Aliyun OSS required config: present" -ForegroundColor Green
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "[SUCCESS] Deployment completed!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Summary:" -ForegroundColor Yellow
Write-Host "  Uploaded files: $uploaded" -ForegroundColor Green
Write-Host "  Upload mode:    $effectiveUploadStrategy" -ForegroundColor Green
Write-Host "  Deleted files:  $(if ($SkipDelete) { 'Skipped' } else { $filesToDelete.Count })" -ForegroundColor Green
Write-Host "  Server:         $ServerUser@$ServerIP" -ForegroundColor Green
Write-Host "  Remote path:    $RemotePath" -ForegroundColor Green
