<#
.SYNOPSIS
Runs a real, installed Velopack client update against a loopback-only feed.

.DESCRIPTION
The baseline installer and feed must both live inside this repository. The
client is installed into a unique directory under build\tests, never into the
normal LocalAppData package directory. The script refuses to run if the current
user already has this Velopack package registered or its shortcuts are present.

The update probe is deliberately guarded inside MissionLegal.exe by
MISSION_LEGAL_ENABLE_UPDATE_SMOKE_TEST=1. Regardless of success or failure, the
loopback server is stopped, processes executing from the test install are
terminated, Velopack's uninstaller is invoked, and the test install directory
is removed. Small logs remain under build\tests\installed-client-update.

Use -ValidateOnly for a fast, non-mutating artifact and safety validation.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaselineInstaller,

    [Parameter(Mandatory = $true)]
    [string]$FeedDirectory,

    [Parameter(Mandatory = $true)]
    [string]$BaselineVersion,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion,

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Channel = "stable",

    [string]$PythonPath = "",

    [ValidateRange(0, 65535)]
    [int]$Port = 0,

    [ValidateRange(30, 3600)]
    [int]$InstallTimeoutSeconds = 900,

    [ValidateRange(30, 7200)]
    [int]$UpdateTimeoutSeconds = 1800,

    [ValidateRange(30, 1800)]
    [int]$CleanupTimeoutSeconds = 300,

    [bool]$RequireDelta = $true,

    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "The installed client update smoke test is Windows-only."
}

$RepoRoot = [IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
)
$RepoPrefix = $RepoRoot.TrimEnd("\/".ToCharArray()) + [IO.Path]::DirectorySeparatorChar

function Test-PathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $FullCandidate = [IO.Path]::GetFullPath($Candidate)
    $FullRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\/".ToCharArray())
    $Prefix = $FullRoot + [IO.Path]::DirectorySeparatorChar
    return (
        $FullCandidate.Equals($FullRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $FullCandidate.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)
    )
}

function Assert-NoReparsePointBelow {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $FullCandidate = [IO.Path]::GetFullPath($Candidate)
    $FullRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\/".ToCharArray())
    if (-not (Test-PathWithin -Candidate $FullCandidate -Root $FullRoot)) {
        throw "$Description must stay inside the repository: $FullCandidate"
    }

    if ($FullCandidate.Equals($FullRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return
    }

    $Relative = $FullCandidate.Substring($FullRoot.Length).TrimStart("\/".ToCharArray())
    $Current = $FullRoot
    foreach ($Part in $Relative.Split(@('\', '/'), [StringSplitOptions]::RemoveEmptyEntries)) {
        $Current = Join-Path $Current $Part
        if (-not (Test-Path -LiteralPath $Current)) {
            continue
        }
        $Attributes = (Get-Item -LiteralPath $Current -Force).Attributes
        if (($Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Description may not pass through a junction or symbolic link: $Current"
        }
    }
}

function Assert-NoReparsePointsInTree {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Description
    )

    if (-not (Test-Path -LiteralPath $Root)) {
        return
    }
    $RootItem = Get-Item -LiteralPath $Root -Force
    if (($RootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Description is itself a junction or symbolic link: $Root"
    }
    $UnsafeItem = Get-ChildItem -LiteralPath $Root -Recurse -Force | Where-Object {
        ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    } | Select-Object -First 1
    if ($null -ne $UnsafeItem) {
        throw "$Description contains a junction or symbolic link: $($UnsafeItem.FullName)"
    }
}

function Resolve-RepoArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][ValidateSet("Leaf", "Container")][string]$PathType
    )

    $Resolved = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $Path -ErrorAction Stop).ProviderPath
    )
    if (-not (Test-PathWithin -Candidate $Resolved -Root $RepoRoot)) {
        throw "$Description must stay inside the repository: $Resolved"
    }
    Assert-NoReparsePointBelow -Candidate $Resolved -Root $RepoRoot -Description $Description
    if (-not (Test-Path -LiteralPath $Resolved -PathType $PathType)) {
        throw "$Description has the wrong path type: $Resolved"
    }
    return $Resolved
}

function Resolve-PythonExecutable {
    param([string]$RequestedPath)

    $Candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $Candidates += $RequestedPath
    }
    else {
        $Candidates += (Join-Path $RepoRoot "venv\Scripts\python.exe")
        $Candidates += (Join-Path $RepoRoot ".venv\Scripts\python.exe")
        $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -ne $PythonCommand) {
            $Candidates += $PythonCommand.Source
        }
    }

    foreach ($Candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace([string]$Candidate)) {
            continue
        }
        try {
            $Resolved = [IO.Path]::GetFullPath(
                (Resolve-Path -LiteralPath ([string]$Candidate) -ErrorAction Stop).ProviderPath
            )
            if (Test-Path -LiteralPath $Resolved -PathType Leaf) {
                return $Resolved
            }
        }
        catch {
            continue
        }
    }
    throw "Python was not found. Pass -PythonPath or create the repository venv."
}

function Join-WindowsArguments {
    param([string[]]$Arguments)

    $Quoted = foreach ($Argument in $Arguments) {
        $Value = [string]$Argument
        if ($Value.IndexOf([char]0) -ge 0 -or $Value -match "[`r`n]") {
            throw "A process argument contains an unsafe control character."
        }
        if ($Value -notmatch '[\s"]') {
            $Value
            continue
        }
        # Paths and generated values cannot contain a quote on Windows. Reject
        # one instead of attempting an ambiguous command-line transformation.
        if ($Value.Contains('"')) {
            throw "A process argument contains an unsupported quote character."
        }
        '"' + $Value + '"'
    }
    return ($Quoted -join " ")
}

function Start-HiddenProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = "",
        [switch]$CaptureOutput
    )

    $StartInfo = New-Object Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $FilePath
    $StartInfo.Arguments = Join-WindowsArguments -Arguments $Arguments
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $StartInfo.WorkingDirectory = $WorkingDirectory
    }
    if ($CaptureOutput) {
        $StartInfo.RedirectStandardOutput = $true
        $StartInfo.RedirectStandardError = $true
    }

    $Process = New-Object Diagnostics.Process
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) {
        throw "Could not start process: $FilePath"
    }

    if ($CaptureOutput) {
        return [pscustomobject]@{
            Process = $Process
            StdoutTask = $Process.StandardOutput.ReadToEndAsync()
            StderrTask = $Process.StandardError.ReadToEndAsync()
        }
    }
    return $Process
}

function Invoke-BoundedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [string]$WorkingDirectory = ""
    )

    $Process = Start-HiddenProcess `
        -FilePath $FilePath `
        -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory
    try {
        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $Process.Kill() } catch { }
            throw "Process timed out after $TimeoutSeconds seconds: $FilePath"
        }
        $Process.WaitForExit()
        return $Process.ExitCode
    }
    finally {
        $Process.Dispose()
    }
}

function Get-AvailableLoopbackPort {
    param([int]$RequestedPort)

    if ($RequestedPort -ne 0) {
        if ($RequestedPort -lt 1024) {
            throw "A fixed loopback port must be 1024 or higher."
        }
        return $RequestedPort
    }

    $Listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    try {
        $Listener.Start()
        return ([Net.IPEndPoint]$Listener.LocalEndpoint).Port
    }
    finally {
        $Listener.Stop()
    }
}

function Test-LoopbackPort {
    param([int]$PortNumber)

    $Client = New-Object Net.Sockets.TcpClient
    try {
        $Task = $Client.ConnectAsync([Net.IPAddress]::Loopback, $PortNumber)
        if (-not $Task.Wait(500)) {
            return $false
        }
        return $Client.Connected
    }
    catch {
        return $false
    }
    finally {
        $Client.Dispose()
    }
}

function Get-XmlPackageVersion {
    param([Parameter(Mandatory = $true)][string]$VersionFile)

    try {
        [xml]$Document = Get-Content -LiteralPath $VersionFile -Raw
        $Node = $Document.SelectSingleNode(
            "/*[local-name()='package']/*[local-name()='metadata']/*[local-name()='version']"
        )
    }
    catch {
        throw "Installed sq.version is not valid XML: $VersionFile"
    }
    if ($null -eq $Node -or [string]::IsNullOrWhiteSpace($Node.InnerText)) {
        throw "Installed sq.version does not contain a version: $VersionFile"
    }
    return $Node.InnerText.Trim()
}

function Get-PropertyText {
    param($Object, [string]$Name)

    if ($null -eq $Object) {
        return ""
    }
    $Property = $Object.PSObject.Properties[$Name]
    if ($null -eq $Property -or $null -eq $Property.Value) {
        return ""
    }
    return [string]$Property.Value
}

function Get-MatchingInstallRegistrations {
    param([string]$PackageId, [string]$PackageTitle)

    $Root = "Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall"
    if (-not (Test-Path -LiteralPath $Root)) {
        return @()
    }

    $Matches = @()
    foreach ($Key in Get-ChildItem -LiteralPath $Root -ErrorAction Stop) {
        $Properties = Get-ItemProperty -LiteralPath $Key.PSPath -ErrorAction SilentlyContinue
        $DisplayName = Get-PropertyText -Object $Properties -Name "DisplayName"
        $InstallLocation = Get-PropertyText -Object $Properties -Name "InstallLocation"
        $UninstallString = Get-PropertyText -Object $Properties -Name "UninstallString"
        if (
            $Key.PSChildName.IndexOf($PackageId, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $DisplayName.Equals($PackageTitle, [StringComparison]::OrdinalIgnoreCase) -or
            $InstallLocation.IndexOf($PackageId, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $UninstallString.IndexOf($PackageId, [StringComparison]::OrdinalIgnoreCase) -ge 0
        ) {
            $Matches += [pscustomobject]@{
                Key = $Key.PSChildName
                DisplayName = $DisplayName
                InstallLocation = $InstallLocation
            }
        }
    }
    return @($Matches)
}

function Stop-ProcessesWithin {
    param([Parameter(Mandatory = $true)][string]$Root)

    if (-not (Test-Path -LiteralPath $Root)) {
        return
    }
    $FullRoot = [IO.Path]::GetFullPath($Root)
    foreach ($Process in Get-Process -ErrorAction SilentlyContinue) {
        if ($Process.Id -eq $PID) {
            continue
        }
        try {
            $Executable = $Process.Path
            if (
                -not [string]::IsNullOrWhiteSpace($Executable) -and
                (Test-PathWithin -Candidate $Executable -Root $FullRoot)
            ) {
                Stop-Process -Id $Process.Id -Force -ErrorAction Stop
                $Process.WaitForExit(5000)
            }
        }
        catch {
            # Access to unrelated protected processes is expected to fail. A
            # process is only stopped after its executable path was read and
            # proven to be under the isolated install root.
            continue
        }
    }
}

$BaselineInstaller = Resolve-RepoArtifact `
    -Path $BaselineInstaller `
    -Description "Baseline installer" `
    -PathType Leaf
$FeedDirectory = Resolve-RepoArtifact `
    -Path $FeedDirectory `
    -Description "Update feed directory" `
    -PathType Container
$PythonPath = Resolve-PythonExecutable -RequestedPath $PythonPath

if ((Get-Item -LiteralPath $BaselineInstaller).Length -le 0) {
    throw "Baseline installer is empty: $BaselineInstaller"
}

$ReleaseConfigPath = Resolve-RepoArtifact `
    -Path (Join-Path $RepoRoot "deployment\client_release.json") `
    -Description "Client release configuration" `
    -PathType Leaf
$ReleaseConfig = Get-Content -LiteralPath $ReleaseConfigPath -Raw | ConvertFrom-Json
$PackageId = Get-PropertyText -Object $ReleaseConfig -Name "packId"
$PackageTitle = Get-PropertyText -Object $ReleaseConfig -Name "packTitle"
$MainExe = Get-PropertyText -Object $ReleaseConfig -Name "mainExe"
if (
    [string]::IsNullOrWhiteSpace($PackageId) -or
    [string]::IsNullOrWhiteSpace($PackageTitle) -or
    [string]::IsNullOrWhiteSpace($MainExe)
) {
    throw "client_release.json is missing packId, packTitle, or mainExe."
}

$FeedPath = Join-Path $FeedDirectory "releases.$Channel.json"
if (-not (Test-Path -LiteralPath $FeedPath -PathType Leaf)) {
    throw "Update feed is missing releases.$Channel.json: $FeedPath"
}
Assert-NoReparsePointBelow -Candidate $FeedPath -Root $FeedDirectory -Description "Update feed manifest"
try {
    $Feed = Get-Content -LiteralPath $FeedPath -Raw | ConvertFrom-Json
}
catch {
    throw "Update feed manifest is not valid JSON: $FeedPath"
}
$AssetsProperty = $Feed.PSObject.Properties["Assets"]
if ($null -eq $AssetsProperty) {
    throw "Update feed manifest does not contain Assets: $FeedPath"
}
$Assets = @($AssetsProperty.Value)
$FullAssets = @($Assets | Where-Object { (Get-PropertyText $_ "Type") -eq "Full" })
$ExpectedFull = @(
    $FullAssets | Where-Object { (Get-PropertyText $_ "Version") -eq $ExpectedVersion }
)
$ExpectedDelta = @(
    $Assets | Where-Object {
        (Get-PropertyText $_ "Type") -eq "Delta" -and
        (Get-PropertyText $_ "Version") -eq $ExpectedVersion
    }
)
if ($ExpectedFull.Count -ne 1) {
    throw "Feed must contain exactly one full package for expected version $ExpectedVersion."
}
if ($RequireDelta -and $ExpectedDelta.Count -ne 1) {
    throw "Feed must contain exactly one delta package for expected version $ExpectedVersion."
}

$VersionProbe = @'
import sys
from packaging.version import InvalidVersion, Version

try:
    baseline = Version(sys.argv[1])
    expected = Version(sys.argv[2])
    feed_versions = [Version(value) for value in sys.argv[3:]]
except (InvalidVersion, IndexError) as exc:
    raise SystemExit(f'invalid release version: {exc}')
if not feed_versions:
    raise SystemExit('feed has no full release versions')
if baseline >= expected:
    raise SystemExit(
        f'baseline {baseline} must be older than expected version {expected}'
    )
latest = max(feed_versions)
if latest != expected:
    raise SystemExit(
        f'expected version {expected} must be the latest full feed version, found {latest}'
    )
print(f'{baseline}|{expected}')
'@
$FullVersions = @($FullAssets | ForEach-Object { Get-PropertyText $_ "Version" })
$ProbeArguments = @("-B", "-c", $VersionProbe, $BaselineVersion, $ExpectedVersion) + $FullVersions
$VersionOutput = @(& $PythonPath @ProbeArguments 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Release version validation failed: $($VersionOutput -join ' ')"
}
$NormalizedVersions = ([string]$VersionOutput[-1]).Trim().Split('|')
if ($NormalizedVersions.Count -ne 2) {
    throw "Release version validation returned an unexpected result."
}
$NormalizedBaselineVersion = $NormalizedVersions[0]
$NormalizedExpectedVersion = $NormalizedVersions[1]

$TargetAssets = @($ExpectedFull)
if ($RequireDelta) {
    $TargetAssets += @($ExpectedDelta)
}
foreach ($Asset in $TargetAssets) {
    $FileName = Get-PropertyText $Asset "FileName"
    if (
        [string]::IsNullOrWhiteSpace($FileName) -or
        $FileName -match '[/\\]' -or
        [IO.Path]::GetFileName($FileName) -ne $FileName
    ) {
        throw "Feed contains an unsafe target asset file name: $FileName"
    }
    $AssetPath = Join-Path $FeedDirectory $FileName
    if (-not (Test-Path -LiteralPath $AssetPath -PathType Leaf)) {
        throw "Feed target asset is missing: $AssetPath"
    }
    Assert-NoReparsePointBelow -Candidate $AssetPath -Root $FeedDirectory -Description "Feed target asset"
    $AssetItem = Get-Item -LiteralPath $AssetPath
    $DeclaredSize = Get-PropertyText $Asset "Size"
    if ([string]::IsNullOrWhiteSpace($DeclaredSize) -or $AssetItem.Length -ne [int64]$DeclaredSize) {
        throw "Feed target asset size does not match: $FileName"
    }
    $DeclaredHash = (Get-PropertyText $Asset "SHA256").Trim()
    if ($DeclaredHash -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "Feed target asset is missing a valid SHA-256: $FileName"
    }
    $ActualHash = (Get-FileHash -LiteralPath $AssetPath -Algorithm SHA256).Hash
    if (-not $ActualHash.Equals($DeclaredHash, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Feed target asset SHA-256 does not match: $FileName"
    }
}

if ($ValidateOnly) {
    Write-Host (
        "Installed update harness validation passed: {0} -> {1} ({2})" -f
        $NormalizedBaselineVersion,
        $NormalizedExpectedVersion,
        $FeedPath
    )
    return
}

$ExistingDefaultInstall = Join-Path $env:LOCALAPPDATA $PackageId
if (Test-Path -LiteralPath $ExistingDefaultInstall) {
    throw "Refusing to disturb an existing default client installation: $ExistingDefaultInstall"
}
$ExistingRegistrations = @(Get-MatchingInstallRegistrations -PackageId $PackageId -PackageTitle $PackageTitle)
if ($ExistingRegistrations.Count -gt 0) {
    throw "Refusing to disturb an existing $PackageTitle client registration."
}
$ShortcutPaths = @(
    (Join-Path ([Environment]::GetFolderPath("DesktopDirectory")) "$PackageTitle.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "$PackageTitle.lnk")
)
foreach ($ShortcutPath in $ShortcutPaths) {
    if (Test-Path -LiteralPath $ShortcutPath) {
        throw "Refusing to overwrite an existing client shortcut: $ShortcutPath"
    }
}

$HarnessRoot = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "build\tests\installed-client-update")
)
if (-not (Test-PathWithin -Candidate $HarnessRoot -Root $RepoRoot)) {
    throw "Harness root escaped the repository: $HarnessRoot"
}
New-Item -ItemType Directory -Force -Path $HarnessRoot | Out-Null
Assert-NoReparsePointBelow -Candidate $HarnessRoot -Root $RepoRoot -Description "Harness root"
$RunRoot = Join-Path $HarnessRoot ([Guid]::NewGuid().ToString("N"))
$InstallRoot = Join-Path $RunRoot "install"
$ResultPath = Join-Path $RunRoot "installed-update-result.json"
$SetupLogPath = Join-Path $RunRoot "setup.log"
$UninstallLogPath = Join-Path $RunRoot "uninstall.log"
$FeedStdoutPath = Join-Path $RunRoot "feed.stdout.log"
$FeedStderrPath = Join-Path $RunRoot "feed.stderr.log"
$SummaryPath = Join-Path $RunRoot "summary.json"
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
Assert-NoReparsePointBelow -Candidate $RunRoot -Root $HarnessRoot -Description "Harness run directory"

$SelectedPort = Get-AvailableLoopbackPort -RequestedPort $Port
$FeedUrl = "http://127.0.0.1:$SelectedPort/"
$FeedServer = $null
$ProbeProcess = $null
$InstallAttempted = $false
$PrimaryError = $null
$CleanupErrors = New-Object 'System.Collections.Generic.List[string]'
$UninstallerLeftInstallRoot = $false
$ObservedStatuses = New-Object 'System.Collections.Generic.HashSet[string]'
$FinalPayload = $null

$EnvironmentNames = @(
    "MISSION_LEGAL_ENABLE_UPDATE_SMOKE_TEST",
    "MISSION_LEGAL_UPDATE_URL",
    "MISSION_LEGAL_UPDATE_PROVIDER",
    "MISSION_LEGAL_DISABLE_UPDATES"
)
$PreviousEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

try {
    $FeedServer = Start-HiddenProcess `
        -FilePath $PythonPath `
        -Arguments @(
            "-B", "-m", "http.server", [string]$SelectedPort,
            "--bind", "127.0.0.1", "--directory", $FeedDirectory
        ) `
        -WorkingDirectory $FeedDirectory `
        -CaptureOutput

    $FeedReadyDeadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $FeedReadyDeadline) {
        if ($FeedServer.Process.HasExited) {
            throw "The loopback update-feed server exited before it became ready."
        }
        if (Test-LoopbackPort -PortNumber $SelectedPort) {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-LoopbackPort -PortNumber $SelectedPort)) {
        throw "The loopback update-feed server did not become ready on port $SelectedPort."
    }

    $WebClient = New-Object Net.WebClient
    try {
        $WebClient.Proxy = $null
        $ServedFeed = $WebClient.DownloadString("${FeedUrl}releases.$Channel.json")
        if ([string]::IsNullOrWhiteSpace($ServedFeed)) {
            throw "The loopback update feed returned an empty manifest."
        }
    }
    finally {
        $WebClient.Dispose()
    }

    [Environment]::SetEnvironmentVariable(
        "MISSION_LEGAL_ENABLE_UPDATE_SMOKE_TEST", "1", "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "MISSION_LEGAL_UPDATE_URL", $FeedUrl, "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "MISSION_LEGAL_UPDATE_PROVIDER", "http", "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "MISSION_LEGAL_DISABLE_UPDATES", "0", "Process"
    )

    $InstallAttempted = $true
    $SetupExitCode = Invoke-BoundedProcess `
        -FilePath $BaselineInstaller `
        -Arguments @(
            "--silent", "--verbose", "--log", $SetupLogPath,
            "--installto", $InstallRoot
        ) `
        -TimeoutSeconds $InstallTimeoutSeconds `
        -WorkingDirectory $RunRoot
    if ($SetupExitCode -ne 0) {
        throw "Baseline installer exited with code $SetupExitCode. See $SetupLogPath"
    }

    $UpdateExe = Join-Path $InstallRoot "Update.exe"
    $StubExe = Join-Path $InstallRoot $MainExe
    $CurrentExe = Join-Path (Join-Path $InstallRoot "current") $MainExe
    $VersionFile = Join-Path (Join-Path $InstallRoot "current") "sq.version"
    foreach ($RequiredPath in @($UpdateExe, $StubExe, $CurrentExe, $VersionFile)) {
        if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
            throw "Installed Velopack layout is missing: $RequiredPath"
        }
        Assert-NoReparsePointBelow `
            -Candidate $RequiredPath `
            -Root $InstallRoot `
            -Description "Installed Velopack file"
    }
    $InstalledBaseline = Get-XmlPackageVersion -VersionFile $VersionFile
    $InstalledBaselineOutput = @(
        & $PythonPath -B -c "from packaging.version import Version; print(Version(__import__('sys').argv[1]))" $InstalledBaseline 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or ([string]$InstalledBaselineOutput[-1]).Trim() -ne $NormalizedBaselineVersion) {
        throw (
            "Baseline installer version is {0}; expected {1}." -f
            $InstalledBaseline,
            $NormalizedBaselineVersion
        )
    }

    $ProbeProcess = Start-HiddenProcess `
        -FilePath $StubExe `
        -Arguments @(
            "--installed-update-smoke-test", $ExpectedVersion, $ResultPath
        ) `
        -WorkingDirectory $InstallRoot

    $UpdateDeadline = [DateTime]::UtcNow.AddSeconds($UpdateTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $UpdateDeadline) {
        if ($FeedServer.Process.HasExited) {
            throw "The loopback update-feed server exited during the update."
        }
        if (Test-Path -LiteralPath $ResultPath -PathType Leaf) {
            try {
                $Payload = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
                $Status = Get-PropertyText $Payload "status"
                if (-not [string]::IsNullOrWhiteSpace($Status)) {
                    [void]$ObservedStatuses.Add($Status)
                }
                if ($Status -eq "failed") {
                    $Failure = Get-PropertyText $Payload "error"
                    throw "Installed update probe failed: $Failure"
                }
                if ($Status -eq "complete") {
                    $FinalPayload = $Payload
                    break
                }
            }
            catch [Management.Automation.RuntimeException] {
                throw
            }
            catch {
                # The probe uses atomic replacement, but antivirus/indexers can
                # briefly race a read. Retry malformed/transient reads.
            }
        }
        Start-Sleep -Seconds 1
    }
    if ($null -eq $FinalPayload) {
        throw "Installed update did not complete within $UpdateTimeoutSeconds seconds."
    }

    $ReportedVersion = Get-PropertyText $FinalPayload "installed_version"
    $ReportedVersionOutput = @(
        & $PythonPath -B -c "from packaging.version import Version; print(Version(__import__('sys').argv[1]))" $ReportedVersion 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or ([string]$ReportedVersionOutput[-1]).Trim() -ne $NormalizedExpectedVersion) {
        throw "Restarted client reported version $ReportedVersion; expected $ExpectedVersion."
    }

    $ReportedExecutable = Get-PropertyText $FinalPayload "executable"
    if ([string]::IsNullOrWhiteSpace($ReportedExecutable)) {
        throw "Restarted client did not report its executable path."
    }
    $ResolvedReportedExecutable = [IO.Path]::GetFullPath($ReportedExecutable)
    if (-not (Test-PathWithin -Candidate $ResolvedReportedExecutable -Root (Join-Path $InstallRoot "current"))) {
        throw "Restarted client executed outside the isolated install: $ResolvedReportedExecutable"
    }
    if (-not (Test-Path -LiteralPath $ResolvedReportedExecutable -PathType Leaf)) {
        throw "Restarted client executable is missing: $ResolvedReportedExecutable"
    }
    Assert-NoReparsePointBelow `
        -Candidate $ResolvedReportedExecutable `
        -Root $InstallRoot `
        -Description "Restarted client executable"

    if (-not (Test-Path -LiteralPath $VersionFile -PathType Leaf)) {
        throw "Updated sq.version is missing: $VersionFile"
    }
    Assert-NoReparsePointBelow `
        -Candidate $VersionFile `
        -Root $InstallRoot `
        -Description "Updated sq.version"
    $FinalInstalledVersion = Get-XmlPackageVersion -VersionFile $VersionFile
    $FinalVersionOutput = @(
        & $PythonPath -B -c "from packaging.version import Version; print(Version(__import__('sys').argv[1]))" $FinalInstalledVersion 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or ([string]$FinalVersionOutput[-1]).Trim() -ne $NormalizedExpectedVersion) {
        throw "Installed sq.version is $FinalInstalledVersion; expected $ExpectedVersion."
    }
}
catch {
    $PrimaryError = $_.Exception
}
finally {
    if ($null -ne $FeedServer) {
        try {
            if (-not $FeedServer.Process.HasExited) {
                $FeedServer.Process.Kill()
                [void]$FeedServer.Process.WaitForExit(5000)
            }
            $FeedStdout = $FeedServer.StdoutTask.Result
            $FeedStderr = $FeedServer.StderrTask.Result
            [IO.File]::WriteAllText($FeedStdoutPath, $FeedStdout, (New-Object Text.UTF8Encoding($false)))
            [IO.File]::WriteAllText($FeedStderrPath, $FeedStderr, (New-Object Text.UTF8Encoding($false)))
            $FeedServer.Process.Dispose()
            $PortCloseDeadline = [DateTime]::UtcNow.AddSeconds(5)
            while (
                (Test-LoopbackPort -PortNumber $SelectedPort) -and
                [DateTime]::UtcNow -lt $PortCloseDeadline
            ) {
                Start-Sleep -Milliseconds 100
            }
            if (Test-LoopbackPort -PortNumber $SelectedPort) {
                $CleanupErrors.Add("Loopback feed port $SelectedPort remained open.")
            }
        }
        catch {
            $CleanupErrors.Add("Could not stop the loopback feed server: $($_.Exception.Message)")
        }
    }

    if ($null -ne $ProbeProcess) {
        try { $ProbeProcess.Dispose() } catch { }
    }

    if ($InstallAttempted) {
        try {
            Stop-ProcessesWithin -Root $InstallRoot
        }
        catch {
            $CleanupErrors.Add("Could not stop installed test processes: $($_.Exception.Message)")
        }

        $UpdateExeForCleanup = Join-Path $InstallRoot "Update.exe"
        if (Test-Path -LiteralPath $UpdateExeForCleanup -PathType Leaf) {
            try {
                $UninstallExitCode = Invoke-BoundedProcess `
                    -FilePath $UpdateExeForCleanup `
                    -Arguments @(
                        "--silent", "--verbose", "--log", $UninstallLogPath, "uninstall"
                    ) `
                    -TimeoutSeconds $CleanupTimeoutSeconds `
                    -WorkingDirectory $RunRoot
                if ($UninstallExitCode -ne 0) {
                    $CleanupErrors.Add("Velopack uninstaller exited with code $UninstallExitCode.")
                }
            }
            catch {
                $CleanupErrors.Add("Velopack uninstall failed: $($_.Exception.Message)")
            }
        }

        try {
            $RemovalDeadline = [DateTime]::UtcNow.AddSeconds(30)
            while ((Test-Path -LiteralPath $InstallRoot) -and [DateTime]::UtcNow -lt $RemovalDeadline) {
                Start-Sleep -Milliseconds 250
            }
            Stop-ProcessesWithin -Root $InstallRoot
            if (Test-Path -LiteralPath $InstallRoot) {
                $UninstallerLeftInstallRoot = $true
                $CleanupErrors.Add(
                    "Velopack reported uninstall completion but left the install directory: $InstallRoot"
                )
                if (-not (Test-PathWithin -Candidate $InstallRoot -Root $HarnessRoot)) {
                    throw "Cleanup target escaped the harness root: $InstallRoot"
                }
                Assert-NoReparsePointBelow `
                    -Candidate $InstallRoot `
                    -Root $HarnessRoot `
                    -Description "Cleanup target"
                Assert-NoReparsePointsInTree `
                    -Root $InstallRoot `
                    -Description "Cleanup target"
                Remove-Item -LiteralPath $InstallRoot -Recurse -Force
            }
            if (Test-Path -LiteralPath $InstallRoot) {
                throw "Isolated install directory still exists: $InstallRoot"
            }
        }
        catch {
            $CleanupErrors.Add("Could not remove the isolated install: $($_.Exception.Message)")
        }

        try {
            $RemainingRegistrations = @(
                Get-MatchingInstallRegistrations -PackageId $PackageId -PackageTitle $PackageTitle
            )
            if ($RemainingRegistrations.Count -gt 0) {
                $CleanupErrors.Add("The test client registration remains after uninstall.")
            }
            foreach ($ShortcutPath in $ShortcutPaths) {
                if (Test-Path -LiteralPath $ShortcutPath) {
                    $CleanupErrors.Add("The test shortcut remains after uninstall: $ShortcutPath")
                }
            }
        }
        catch {
            $CleanupErrors.Add("Could not verify registration/shortcut cleanup: $($_.Exception.Message)")
        }
    }

    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable(
            $Name,
            $PreviousEnvironment[$Name],
            "Process"
        )
    }
}

$Summary = [ordered]@{
    status = if ($null -eq $PrimaryError -and $CleanupErrors.Count -eq 0) { "passed" } else { "failed" }
    baseline_version = $NormalizedBaselineVersion
    expected_version = $NormalizedExpectedVersion
    feed_url = $FeedUrl
    observed_statuses = @($ObservedStatuses)
    result = $FinalPayload
    installer_sha256 = (Get-FileHash -LiteralPath $BaselineInstaller -Algorithm SHA256).Hash
    uninstaller_left_install_root = $UninstallerLeftInstallRoot
    cleanup_errors = @($CleanupErrors)
}
$Summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $SummaryPath -Encoding UTF8

if ($null -ne $PrimaryError -or $CleanupErrors.Count -gt 0) {
    $Messages = @()
    if ($null -ne $PrimaryError) {
        $Messages += $PrimaryError.Message
    }
    $Messages += @($CleanupErrors)
    throw "Installed update smoke test failed: $($Messages -join ' | ') Logs: $RunRoot"
}

Write-Host (
    "Installed client update smoke test passed: {0} -> {1}. Logs: {2}" -f
    $NormalizedBaselineVersion,
    $NormalizedExpectedVersion,
    $RunRoot
)
