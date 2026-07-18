[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [Parameter(Mandatory = $true)][string]$AuthorizationFile,
    [Parameter(Mandatory = $true)][string]$AuthorizationToken,
    [Parameter(Mandatory = $true)][string]$ReadyFile,
    [Parameter(Mandatory = $true)][string]$SignalFile,
    [Parameter(Mandatory = $true)][string]$ResultFile,
    [ValidateRange(30, 900)][int]$TimeoutSeconds = 300
)

# This helper is intentionally destructive. It may only be launched by the
# disposable-VM installer validation harness after that harness completes all
# of its independent VM, marker, path, artifact, and pristine-state gates.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Purpose = "mission-legal-server-installer-post-copy-failure"
$ProgramFilesRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
$InstallDir = [IO.Path]::GetFullPath((Join-Path $ProgramFilesRoot "Mission Legal\Server"))
$TargetPath = [IO.Path]::GetFullPath((Join-Path $InstallDir "MissionLegalService.exe"))
$CandidateSha256 = $null
$CandidateSize = 0
$DamagedSha256 = $null
$InstallerPid = 0
$AuthorizedBaselineSha256 = $null
$AuthorizedUpgradeInstallerSha256 = $null
$script:ResolvedResult = $null

function Test-IsAdministrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-NoReparseAncestors {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Current = [IO.Path]::GetFullPath($Path)
    while ($Current) {
        if (Test-Path -LiteralPath $Current) {
            $Item = Get-Item -LiteralPath $Current -Force -ErrorAction Stop
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Failure-injection path contains a reparse point: $Current"
            }
        }
        $Parent = [IO.Directory]::GetParent($Current)
        if ($null -eq $Parent -or $Parent.FullName -ieq $Current) {
            break
        }
        $Current = $Parent.FullName
    }
}

function Assert-SafeWorkRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($Resolved.StartsWith('\\')) {
        throw "WorkRoot must be a local path: $Resolved"
    }
    $VolumeRoot = [IO.Path]::GetPathRoot($Resolved)
    $Drive = [IO.DriveInfo]::new($VolumeRoot)
    if ($Drive.DriveType -ne [IO.DriveType]::Fixed) {
        throw "WorkRoot must be on a fixed local volume: $Resolved"
    }
    $Parent = [IO.Directory]::GetParent($Resolved)
    if (
        $null -eq $Parent -or
        -not $Parent.FullName.TrimEnd('\').Equals(
            $VolumeRoot.TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "WorkRoot must be the dedicated top-level validation directory: $Resolved"
    }
    if ([IO.Path]::GetFileName($Resolved) -notmatch '^MissionLegalInstallerValidation-[A-Za-z0-9_-]{2,64}$') {
        throw "WorkRoot does not use the dedicated validation name: $Resolved"
    }
    if (-not (Test-Path -LiteralPath $Resolved -PathType Container)) {
        throw "WorkRoot is missing: $Resolved"
    }
    Assert-NoReparseAncestors $Resolved
    return $Resolved
}

function Assert-ContainedFilePath {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $ParentPrefix = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $Resolved = [IO.Path]::GetFullPath($Path)
    if (-not $Resolved.StartsWith($ParentPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description must remain under WorkRoot: $Resolved"
    }
    Assert-NoReparseAncestors $Resolved
    return $Resolved
}

function Get-LowerFileHash {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-StreamSha256 {
    param([Parameter(Mandatory = $true)][IO.Stream]$Stream)

    $Sha = [Security.Cryptography.SHA256]::Create()
    try {
        $Stream.Position = 0
        $Bytes = $Sha.ComputeHash($Stream)
        return ([BitConverter]::ToString($Bytes)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $Sha.Dispose()
    }
}

function Write-WatcherResult {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Message
    )

    $Payload = [ordered]@{
        schema_version = 1
        purpose = $Purpose
        status = $Status
        message = $Message
        installer_pid = $InstallerPid
        target_path = $TargetPath
        baseline_sha256 = $AuthorizedBaselineSha256
        candidate_sha256 = $CandidateSha256
        candidate_size = $CandidateSize
        damaged_sha256 = $DamagedSha256
        upgrade_installer_sha256 = $AuthorizedUpgradeInstallerSha256
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $Payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $script:ResolvedResult -Encoding UTF8
}

try {
    if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) {
        throw "The failure watcher can only run on Windows."
    }
    if (-not (Test-IsAdministrator)) {
        throw "The failure watcher requires an elevated Windows PowerShell process."
    }
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        throw "The failure watcher requires 64-bit Windows PowerShell."
    }

    $ResolvedWorkRoot = Assert-SafeWorkRoot $WorkRoot
    $ResolvedAuthorization = Assert-ContainedFilePath $ResolvedWorkRoot $AuthorizationFile "AuthorizationFile"
    $ResolvedReady = Assert-ContainedFilePath $ResolvedWorkRoot $ReadyFile "ReadyFile"
    $ResolvedSignal = Assert-ContainedFilePath $ResolvedWorkRoot $SignalFile "SignalFile"
    $script:ResolvedResult = Assert-ContainedFilePath $ResolvedWorkRoot $ResultFile "ResultFile"
    foreach ($Output in @($ResolvedReady, $ResolvedSignal, $script:ResolvedResult)) {
        if (Test-Path -LiteralPath $Output) {
            throw "Failure-watcher coordination path must be initially absent: $Output"
        }
    }
    if (-not (Test-Path -LiteralPath $ResolvedAuthorization -PathType Leaf)) {
        throw "Failure-watcher authorization file is missing: $ResolvedAuthorization"
    }
    Assert-NoReparseAncestors $InstallDir
    Assert-NoReparseAncestors $TargetPath

    $Authorization = Get-Content -LiteralPath $ResolvedAuthorization -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [int]$Authorization.schema_version -ne 1 -or
        [string]$Authorization.purpose -cne $Purpose -or
        [string]$Authorization.token -cne $AuthorizationToken
    ) {
        throw "Failure-watcher authorization does not match this invocation."
    }
    $Expires = [DateTimeOffset]::Parse([string]$Authorization.expires_at_utc)
    if ($Expires -le [DateTimeOffset]::UtcNow -or $Expires -gt [DateTimeOffset]::UtcNow.AddMinutes(15)) {
        throw "Failure-watcher authorization is expired or exceeds the 15-minute maximum."
    }
    foreach ($Check in @(
        @([string]$Authorization.install_dir, $InstallDir, "install directory"),
        @([string]$Authorization.target_path, $TargetPath, "target path")
    )) {
        $Actual = [IO.Path]::GetFullPath($Check[0])
        if (-not $Actual.Equals($Check[1], [StringComparison]::OrdinalIgnoreCase)) {
            throw "Failure-watcher authorization has the wrong $($Check[2]): $Actual"
        }
    }
    $BaselineSha256 = ([string]$Authorization.baseline_sha256).ToLowerInvariant()
    $AuthorizedBaselineSha256 = $BaselineSha256
    if ($BaselineSha256 -notmatch '^[a-f0-9]{64}$') {
        throw "Failure-watcher authorization has an invalid baseline SHA-256."
    }
    $UpgradeInstaller = [IO.Path]::GetFullPath([string]$Authorization.upgrade_installer_path)
    $UpgradeInstallerSha256 = ([string]$Authorization.upgrade_installer_sha256).ToLowerInvariant()
    $AuthorizedUpgradeInstallerSha256 = $UpgradeInstallerSha256
    if (-not (Test-Path -LiteralPath $UpgradeInstaller -PathType Leaf)) {
        throw "Authorized upgrade installer is missing: $UpgradeInstaller"
    }
    Assert-NoReparseAncestors $UpgradeInstaller
    if ((Get-LowerFileHash $UpgradeInstaller) -cne $UpgradeInstallerSha256) {
        throw "Authorized upgrade installer SHA-256 changed before watcher readiness."
    }
    if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) {
        throw "Baseline service executable is missing: $TargetPath"
    }
    if ((Get-LowerFileHash $TargetPath) -cne $BaselineSha256) {
        throw "Installed service executable does not match the authorized baseline SHA-256."
    }

    [ordered]@{
        schema_version = 1
        purpose = $Purpose
        token = $AuthorizationToken
        ready_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $ResolvedReady -Encoding UTF8

    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not (Test-Path -LiteralPath $ResolvedSignal -PathType Leaf)) {
        if ([DateTimeOffset]::UtcNow -ge $Deadline) {
            throw "Timed out waiting for the installer start signal."
        }
        Start-Sleep -Milliseconds 100
    }
    Assert-NoReparseAncestors $ResolvedSignal
    $Signal = Get-Content -LiteralPath $ResolvedSignal -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [int]$Signal.schema_version -ne 1 -or
        [string]$Signal.purpose -cne $Purpose -or
        [string]$Signal.token -cne $AuthorizationToken
    ) {
        throw "Failure-watcher start signal does not match the authorization."
    }
    $InstallerPid = [int]$Signal.installer_pid
    if ($InstallerPid -le 0) {
        throw "Failure-watcher start signal has an invalid installer PID."
    }
    $InstallerProcess = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$InstallerPid" -ErrorAction Stop
    $ProcessPath = [IO.Path]::GetFullPath([string]$InstallerProcess.ExecutablePath)
    if (-not $ProcessPath.Equals($UpgradeInstaller, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Authorized PID is not the prevalidated upgrade installer: $ProcessPath"
    }
    if ((Get-LowerFileHash $ProcessPath) -cne $UpgradeInstallerSha256) {
        throw "Upgrade installer SHA-256 changed after launch."
    }

    $StableCandidate = $null
    $StableObservations = 0
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        if ($null -eq (Get-Process -Id $InstallerPid -ErrorAction SilentlyContinue)) {
            throw "Upgrade installer exited before a distinct candidate service executable could be damaged."
        }
        if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) {
            $StableCandidate = $null
            $StableObservations = 0
            Start-Sleep -Milliseconds 50
            continue
        }
        Assert-NoReparseAncestors $TargetPath
        try {
            $ObservedHash = Get-LowerFileHash $TargetPath
            $ObservedLength = (Get-Item -LiteralPath $TargetPath -Force).Length
        }
        catch {
            Start-Sleep -Milliseconds 50
            continue
        }
        if ($ObservedLength -le 0 -or $ObservedHash -ceq $BaselineSha256) {
            $StableCandidate = $null
            $StableObservations = 0
            Start-Sleep -Milliseconds 50
            continue
        }
        if ($ObservedHash -ceq $StableCandidate) {
            $StableObservations += 1
        }
        else {
            $StableCandidate = $ObservedHash
            $StableObservations = 1
        }
        if ($StableObservations -lt 2) {
            Start-Sleep -Milliseconds 75
            continue
        }

        $Stream = $null
        try {
            $Stream = [IO.File]::Open(
                $TargetPath,
                [IO.FileMode]::Open,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
            $ExclusiveHash = Get-StreamSha256 $Stream
            if ($ExclusiveHash -ceq $BaselineSha256 -or $ExclusiveHash -cne $StableCandidate) {
                throw "Candidate changed before the watcher acquired its exclusive handle."
            }
            if ($null -eq (Get-Process -Id $InstallerPid -ErrorAction SilentlyContinue)) {
                throw "Upgrade installer exited before the authorized mutation."
            }
            $CandidateSha256 = $ExclusiveHash
            $CandidateSize = $Stream.Length
            $Stream.SetLength(0)
            $Stream.Flush($true)
            if ($Stream.Length -ne 0) {
                throw "The candidate stream did not truncate to zero bytes."
            }
            $DamagedSha256 = Get-StreamSha256 $Stream
        }
        catch {
            if ($null -ne $Stream) {
                $Stream.Dispose()
                $Stream = $null
            }
            Start-Sleep -Milliseconds 75
            continue
        }
        finally {
            if ($null -ne $Stream) {
                $Stream.Dispose()
            }
        }
        if ($CandidateSize -le 0 -or $DamagedSha256 -ceq $CandidateSha256) {
            throw "The authorized candidate-binary damage was not observable."
        }
        Write-WatcherResult -Status "injected" -Message "Distinct post-copy candidate service binary was truncated."
        exit 0
    }
    throw "Timed out waiting for a distinct post-copy candidate service executable."
}
catch {
    try {
        if ($script:ResolvedResult) {
            Write-WatcherResult -Status "failed" -Message $_.Exception.Message
        }
    }
    catch {
    }
    Write-Error $_.Exception.Message
    exit 1
}
