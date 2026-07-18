param(
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe",
    [string]$IsccPath,
    [string]$ServerPackageDir,
    [string]$OutputDir,
    [switch]$SkipServerPackageBuild,
    [string]$SignToolName,
    [string]$SignToolCommand,
    [switch]$AllowUnpublishedDevelopmentOverwrite
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = [IO.Path]::GetFullPath($PythonPath)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable was not found: $PythonPath"
}

$AppVersion = (& $PythonPath -c "from version import APP_VERSION; print(APP_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $AppVersion) {
    throw "Could not read APP_VERSION from version.py."
}
if ($AppVersion -notmatch '^(\d+)\.(\d+)\.(\d+)(?:[.+-].*)?$') {
    throw "APP_VERSION must start with three numeric components for Windows version metadata: $AppVersion"
}
$NumericVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3]).0"

$RepoPrefix = $RepoRoot.TrimEnd('\') + '\'
function Assert-RepositoryPath {
    param([string]$Path, [string]$Description)

    $Resolved = [IO.Path]::GetFullPath($Path)
    if (-not $Resolved.StartsWith($RepoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description escaped the repository root: $Resolved"
    }
    return $Resolved
}

if (-not $OutputDir) {
    $OutputDir = Join-Path $RepoRoot "dist\$AppVersion\installers"
}
$OutputDir = Assert-RepositoryPath $OutputDir "Installer output directory"
$InstallerPath = Join-Path $OutputDir "MissionLegalServerSetup-$AppVersion.exe"
$ManifestPath = Join-Path $OutputDir "MissionLegalServerSetup-$AppVersion.json"
$ExistingReleaseArtifacts = @($InstallerPath, $ManifestPath) |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
if ($ExistingReleaseArtifacts.Count -gt 0 -and -not $AllowUnpublishedDevelopmentOverwrite) {
    throw (
        "Server release artifacts already exist for version $AppVersion. " +
        "Published or potentially published same-version artifacts are immutable. " +
        "Bump APP_VERSION, or use -AllowUnpublishedDevelopmentOverwrite only for an unpublished development build."
    )
}

if (-not $SkipServerPackageBuild) {
    & (Join-Path $PSScriptRoot "build_windows.ps1") `
        -Target Server `
        -PythonPath $PythonPath
    if ($LASTEXITCODE -ne 0) {
        throw "The frozen server package build failed."
    }
}

if (-not $ServerPackageDir) {
    $ServerPackageDir = Join-Path $RepoRoot "dist\$AppVersion\MissionLegalServer"
}
$ServerPackageDir = Assert-RepositoryPath $ServerPackageDir "Server package directory"
$ExpectedServerFiles = @(
    "MissionLegalServer.exe",
    "MissionLegalServerSetup.exe",
    "MissionLegalService.exe"
)
foreach ($Name in $ExpectedServerFiles) {
    $Path = Join-Path $ServerPackageDir $Name
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Expected frozen server artifact is missing: $Path"
    }
}

$ForbiddenPersistentFiles = Get-ChildItem -LiteralPath $ServerPackageDir -Recurse -Force -File |
    Where-Object {
        $_.Extension -in @(".db", ".sqlite", ".sqlite3", ".key") -or
        $_.Name -match '^(server-key|ca-key)'
    }
if ($ForbiddenPersistentFiles) {
    $Names = ($ForbiddenPersistentFiles.FullName -join [Environment]::NewLine)
    throw "Persistent data or secret material was found in the server package:`n$Names"
}

& $PythonPath -c "import PyInstaller"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is required. Run: $PythonPath -m pip install -r requirements_build.txt"
}

$BuildRoot = Assert-RepositoryPath (Join-Path $RepoRoot "build\installer\server\$AppVersion") "Installer build directory"
$MaintenanceDist = Join-Path $BuildRoot "maintenance-dist"
$MaintenanceWork = Join-Path $BuildRoot "maintenance-work"
New-Item -ItemType Directory -Force -Path $MaintenanceDist, $MaintenanceWork | Out-Null

$MaintenanceSpec = Join-Path $PSScriptRoot "installer\server_maintenance.spec"
& $PythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --log-level WARN `
    --distpath $MaintenanceDist `
    --workpath $MaintenanceWork `
    $MaintenanceSpec
if ($LASTEXITCODE -ne 0) {
    throw "The server maintenance utility build failed."
}
$MaintenanceExe = Join-Path $MaintenanceDist "MissionLegalServerMaintenance.exe"
if (-not (Test-Path -LiteralPath $MaintenanceExe -PathType Leaf)) {
    throw "The server maintenance executable is missing: $MaintenanceExe"
}
& $MaintenanceExe --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The server maintenance executable failed its CLI smoke test."
}

if (-not $IsccPath) {
    $Command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($Command) {
        $IsccPath = $Command.Source
    }
    else {
        $Candidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
        )
        $IsccPath = $Candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    }
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw "Inno Setup Compiler (ISCC.exe) was not found. Install Inno Setup 6 or 7, or pass -IsccPath."
}
$IsccPath = [IO.Path]::GetFullPath($IsccPath)

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if ($ExistingReleaseArtifacts.Count -gt 0) {
    Write-Warning (
        "Unpublished development override: replacing same-version server release artifacts. " +
        "The resulting installer will require /ALLOWDEVREINSTALL=1 for a same-version installed test."
    )
    Remove-Item -LiteralPath $ExistingReleaseArtifacts -Force
}

if ([bool]$SignToolName -xor [bool]$SignToolCommand) {
    throw "SignToolName and SignToolCommand must be supplied together."
}

$InstallerScript = Join-Path $PSScriptRoot "installer\mission_legal_server.iss"
$CompilerArguments = @(
    "/DAppVersion=$AppVersion",
    "/DAppVersionNumeric=$NumericVersion",
    "/DServerPackageDir=$ServerPackageDir",
    "/DMaintenanceExe=$MaintenanceExe",
    "/DOutputDir=$OutputDir"
)
if ($SignToolName) {
    $CompilerArguments += "/DSignToolName=$SignToolName"
    $CompilerArguments += "/S$SignToolName=$SignToolCommand"
}
if ($AllowUnpublishedDevelopmentOverwrite) {
    $CompilerArguments += "/DDevelopmentBuild=1"
}
$CompilerArguments += $InstallerScript

& $IsccPath @CompilerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed to compile the server installer."
}

if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Expected server installer is missing: $InstallerPath"
}
if ($SignToolName) {
    $Signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
    if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Server installer Authenticode signature is not valid: $($Signature.Status) - $($Signature.StatusMessage)"
    }
}
$InstallerHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    app_version = $AppVersion
    filename = Split-Path -Leaf $InstallerPath
    sha256 = $InstallerHash
    size = (Get-Item -LiteralPath $InstallerPath).Length
    built_at = [DateTimeOffset]::UtcNow.ToString("o")
    development_build = [bool]$AllowUnpublishedDevelopmentOverwrite
    silent_upgrade_arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG"
}
$Manifest | ConvertTo-Json | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

Write-Host "Mission Legal Server installer: $InstallerPath"
Write-Host "SHA-256: $InstallerHash"
Write-Host "Release manifest: $ManifestPath"
