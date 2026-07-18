param(
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe",
    [string]$IsccPath,
    [string]$ServerPackageDir,
    [string]$ProvenanceManifestPath,
    [string]$OutputDir,
    [switch]$SkipServerPackageBuild,
    [string]$SignToolName,
    [string]$SignToolCommand,
    [string]$ExpectedSignerThumbprint,
    [switch]$RequireSigning,
    [switch]$AllowUnpublishedDevelopmentOverwrite
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseSafetyPath = Join-Path $PSScriptRoot "release_safety.ps1"
if (-not (Test-Path -LiteralPath $ReleaseSafetyPath -PathType Leaf)) {
    throw "Release safety helpers are missing: $ReleaseSafetyPath"
}
. $ReleaseSafetyPath
# release_safety.ps1 centralizes Get-AuthenticodeSignature and emits the
# "Authenticode signature is not valid" failure used by this production gate.
$PythonPath = [IO.Path]::GetFullPath($PythonPath)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable was not found: $PythonPath"
}

$VersionPayloadText = (& $PythonPath -B -c "import json,sys; sys.path.insert(0,sys.argv[1]); from version import API_VERSION, APP_VERSION, SCHEMA_VERSION; print(json.dumps({'app_version':APP_VERSION,'api_version':API_VERSION,'schema_version':SCHEMA_VERSION}))" $RepoRoot).Trim()
if ($LASTEXITCODE -ne 0 -or -not $VersionPayloadText) {
    throw "Could not read release versions from version.py."
}
try {
    $VersionPayload = $VersionPayloadText | ConvertFrom-Json
}
catch {
    throw "version.py returned invalid release-version metadata: $VersionPayloadText"
}
$AppVersion = [string]$VersionPayload.app_version
$ApiVersion = [string]$VersionPayload.api_version
$SchemaVersion = [int]$VersionPayload.schema_version
$SchemaVersionText = [string]$SchemaVersion
if (-not $AppVersion -or -not $ApiVersion -or $SchemaVersion -lt 1) {
    throw "version.py returned incomplete release-version metadata."
}
if ($AppVersion -notmatch '^(\d+)\.(\d+)\.(\d+)(?:[.+-].*)?$') {
    throw "APP_VERSION must start with three numeric components for Windows version metadata: $AppVersion"
}
$NumericVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3]).0"

if ([bool]$SignToolName -xor [bool]$SignToolCommand) {
    throw "SignToolName and SignToolCommand must be supplied together."
}
if ($RequireSigning -and -not $SignToolName) {
    throw "A production server installer requires SignToolName and SignToolCommand."
}
if ($RequireSigning -and [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint)) {
    throw "A production server installer requires ExpectedSignerThumbprint to bind signatures to the approved certificate."
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint)) {
    $ExpectedSignerThumbprint = Get-NormalizedCertificateThumbprint $ExpectedSignerThumbprint
}
if ($RequireSigning -and $AllowUnpublishedDevelopmentOverwrite) {
    throw "RequireSigning cannot be combined with AllowUnpublishedDevelopmentOverwrite."
}

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
$FinalOutputDir = $OutputDir
$InstallerPath = Join-Path $OutputDir "MissionLegalServerSetup-$AppVersion.exe"
$ManifestPath = Join-Path $OutputDir "MissionLegalServerSetup-$AppVersion.json"
$ReleaseLock = Enter-MissionLegalReleaseLock `
    -LockPath (Join-Path $RepoRoot "build\release-locks\server-$AppVersion.lock")
$TransactionOutputDir = $null
$BuildTransactionRoot = $null
try {
Repair-MissionLegalInterruptedReleaseTransaction -FinalDirectory $FinalOutputDir
$ExistingReleaseArtifacts = @($InstallerPath, $ManifestPath) |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
if ($ExistingReleaseArtifacts.Count -gt 0 -and -not $AllowUnpublishedDevelopmentOverwrite) {
    throw (
        "Server release artifacts already exist for version $AppVersion. " +
        "Published or potentially published same-version artifacts are immutable. " +
        "Bump APP_VERSION, or use -AllowUnpublishedDevelopmentOverwrite only for an unpublished development build."
    )
}
if ($RequireSigning) {
    $ExistingServerVersions = [Collections.Generic.List[string]]::new()
    $DistRoot = Join-Path $RepoRoot 'dist'
    if (Test-Path -LiteralPath $DistRoot -PathType Container) {
        foreach ($VersionDirectory in @(Get-ChildItem -LiteralPath $DistRoot -Directory)) {
            try {
                ConvertTo-MissionLegalSemVer $VersionDirectory.Name | Out-Null
            }
            catch {
                continue
            }
            $CandidateInstaller = Join-Path $VersionDirectory.FullName "installers\MissionLegalServerSetup-$($VersionDirectory.Name).exe"
            $CandidateManifest = Join-Path $VersionDirectory.FullName "installers\MissionLegalServerSetup-$($VersionDirectory.Name).json"
            if (
                (Test-Path -LiteralPath $CandidateInstaller -PathType Leaf) -and
                (Test-Path -LiteralPath $CandidateManifest -PathType Leaf)
            ) {
                $ExistingServerVersions.Add($VersionDirectory.Name)
            }
        }
    }
    Assert-MissionLegalVersionIsNewer `
        -CandidateVersion $AppVersion `
        -ExistingVersions @($ExistingServerVersions) `
        -SourceDescription 'the existing versioned server installer output'
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

$ProvenanceHelper = Join-Path $PSScriptRoot "package_provenance.py"
if (-not (Test-Path -LiteralPath $ProvenanceHelper -PathType Leaf)) {
    throw "Package provenance helper is missing: $ProvenanceHelper"
}
if ([string]::IsNullOrWhiteSpace($ProvenanceManifestPath)) {
    $PackageParent = Split-Path -Parent $ServerPackageDir
    $PackageName = Split-Path -Leaf $ServerPackageDir
    $ProvenanceManifestPath = Join-Path $PackageParent "$PackageName.provenance.json"
}
$ProvenanceManifestPath = [IO.Path]::GetFullPath($ProvenanceManifestPath)
if (-not (Test-Path -LiteralPath $ProvenanceManifestPath -PathType Leaf)) {
    throw (
        "Server raw-package provenance manifest is missing: $ProvenanceManifestPath. " +
        "Rebuild with deployment\build_windows.ps1 -Target Server."
    )
}
& $PythonPath -B $ProvenanceHelper `
    verify `
    --repo-root $RepoRoot `
    --package-dir $ServerPackageDir `
    --manifest-path $ProvenanceManifestPath `
    --expected-role server `
    --expected-app-version $AppVersion `
    --expected-api-version $ApiVersion `
    --expected-schema-version $SchemaVersionText `
    --required-windows-version-exe MissionLegalServer.exe `
    --required-windows-version-exe MissionLegalServerSetup.exe `
    --required-windows-version-exe MissionLegalService.exe
if ($LASTEXITCODE -ne 0) {
    throw (
        "Server raw package does not match its provenance manifest. " +
        "Rebuild it with deployment\build_windows.ps1 -Target Server."
    )
}
if ($RequireSigning) {
    try {
        $VerifiedProvenance = Get-Content -LiteralPath $ProvenanceManifestPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Could not read the verified server provenance for production policy checks: $ProvenanceManifestPath"
    }
    if ([bool]$VerifiedProvenance.source.git_dirty) {
        throw (
            "A signed production server installer requires package provenance from a clean Git commit. " +
            "Commit the release source and rebuild the raw server package."
        )
    }
}

function Test-ForbiddenPackagedState {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    $Name = $File.Name.ToLowerInvariant()
    $Extension = $File.Extension.ToLowerInvariant()
    if ($Extension -in @(".db", ".sqlite", ".sqlite3", ".key", ".pfx", ".p12")) {
        return $true
    }
    if ($Name -match '\.(db|sqlite|sqlite3)-(wal|shm|journal)$') {
        return $true
    }
    if ($Name -in @(
        "api-device.json",
        "devices.json",
        "pairing.json",
        "pairing-transaction.json",
        "server.json",
        "workspaces.json"
    )) {
        return $true
    }
    if ($Name -match '^pairing[-_.].*(journal|pointer|transaction).*(\.json|\.lock)$') {
        return $true
    }
    if ($Extension -eq ".pem") {
        if ($Name -match '(^|[-_.])key\.pem$') {
            return $true
        }
        if (Select-String -LiteralPath $File.FullName -Pattern '-----BEGIN .*PRIVATE KEY-----' -Quiet) {
            return $true
        }
    }
    return $false
}

$ForbiddenPersistentFiles = Get-ChildItem -LiteralPath $ServerPackageDir -Recurse -Force -File |
    Where-Object { Test-ForbiddenPackagedState -File $_ }
if ($ForbiddenPersistentFiles) {
    $Names = ($ForbiddenPersistentFiles.FullName -join [Environment]::NewLine)
    throw "Persistent data or secret material was found in the server package:`n$Names"
}

$BuildTransactionRoot = Assert-RepositoryPath `
    (Join-Path $RepoRoot ("build\installer\server\$AppVersion\transaction-" + [Guid]::NewGuid().ToString('N'))) `
    "Installer transaction directory"
New-Item -ItemType Directory -Path $BuildTransactionRoot | Out-Null
$StagedServerPackageDir = Join-Path $BuildTransactionRoot 'server-payload'
New-Item -ItemType Directory -Path $StagedServerPackageDir | Out-Null
foreach ($Item in @(Get-ChildItem -LiteralPath $ServerPackageDir -Force)) {
    Copy-Item -LiteralPath $Item.FullName -Destination $StagedServerPackageDir -Recurse -Force
}

# Verify the copied tree before signing mutates only this transaction-local copy.
& $PythonPath -B $ProvenanceHelper `
    verify `
    --repo-root $RepoRoot `
    --package-dir $StagedServerPackageDir `
    --manifest-path $ProvenanceManifestPath `
    --expected-role server `
    --expected-app-version $AppVersion `
    --expected-api-version $ApiVersion `
    --expected-schema-version $SchemaVersionText `
    --required-windows-version-exe MissionLegalServer.exe `
    --required-windows-version-exe MissionLegalServerSetup.exe `
    --required-windows-version-exe MissionLegalService.exe
if ($LASTEXITCODE -ne 0) {
    throw "The transaction-local server payload did not match its provenance manifest."
}

$TransactionOutputDir = New-MissionLegalReleaseTransaction `
    -FinalDirectory $FinalOutputDir `
    -Label "server-$AppVersion"
$OutputDir = $TransactionOutputDir
$InstallerPath = Join-Path $OutputDir "MissionLegalServerSetup-$AppVersion.exe"
$ManifestPath = Join-Path $OutputDir "MissionLegalServerSetup-$AppVersion.json"

& $PythonPath -c "import PyInstaller"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is required. Run: $PythonPath -m pip install -r requirements_build.txt"
}

$BuildRoot = $BuildTransactionRoot
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
}

$InstallerScript = Join-Path $PSScriptRoot "installer\mission_legal_server.iss"
$CompilerArguments = @(
    "/DAppVersion=$AppVersion",
    "/DAppVersionNumeric=$NumericVersion",
    "/DServerPackageDir=$StagedServerPackageDir",
    "/DMaintenanceExe=$MaintenanceExe",
    "/DOutputDir=$OutputDir"
)
if ($SignToolName) {
    $CompilerArguments += "/DSignToolName=$SignToolName"
    $CompilerArguments += "/S$SignToolName=$SignToolCommand"
}
if (-not $RequireSigning) {
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
$SignatureEvidence = [Collections.Generic.List[object]]::new()
if ($SignToolName) {
    $OuterEvidence = Assert-MissionLegalAuthenticodeSignature `
        -Path $InstallerPath `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -RequireTimestamp:$RequireSigning
    $OuterEvidence['artifact_role'] = 'server_installer'
    $SignatureEvidence.Add($OuterEvidence) | Out-Null

    foreach ($PayloadName in @(
        'MissionLegalServer.exe',
        'MissionLegalServerSetup.exe',
        'MissionLegalService.exe'
    )) {
        $PayloadEvidence = Assert-MissionLegalAuthenticodeSignature `
            -Path (Join-Path $StagedServerPackageDir $PayloadName) `
            -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
            -RequireTimestamp:$RequireSigning
        $PayloadEvidence['artifact_role'] = 'server_installed_executable'
        $SignatureEvidence.Add($PayloadEvidence) | Out-Null
    }
    $MaintenanceEvidence = Assert-MissionLegalAuthenticodeSignature `
        -Path $MaintenanceExe `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -RequireTimestamp:$RequireSigning
    $MaintenanceEvidence['artifact_role'] = 'server_embedded_maintenance_executable'
    $SignatureEvidence.Add($MaintenanceEvidence) | Out-Null
}
$InstallerHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$ProvenanceHash = (Get-FileHash -LiteralPath $ProvenanceManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    app_version = $AppVersion
    filename = Split-Path -Leaf $InstallerPath
    sha256 = $InstallerHash
    size = (Get-Item -LiteralPath $InstallerPath).Length
    built_at = [DateTimeOffset]::UtcNow.ToString("o")
    development_build = [bool](-not $RequireSigning)
    production_signing_required = [bool]$RequireSigning
    expected_signer_thumbprint = if ($RequireSigning) { $ExpectedSignerThumbprint } else { $null }
    package_provenance = [ordered]@{
        filename = [IO.Path]::GetFileName($ProvenanceManifestPath)
        sha256 = $ProvenanceHash
    }
    signatures = @($SignatureEvidence)
    silent_upgrade_arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG"
}
$Manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

$CommittedOutputDir = Complete-MissionLegalReleaseTransaction `
    -TransactionDirectory $TransactionOutputDir `
    -FinalDirectory $FinalOutputDir
$TransactionOutputDir = $null
$InstallerPath = Join-Path $CommittedOutputDir "MissionLegalServerSetup-$AppVersion.exe"
$ManifestPath = Join-Path $CommittedOutputDir "MissionLegalServerSetup-$AppVersion.json"

Write-Host "Mission Legal Server installer: $InstallerPath"
Write-Host "SHA-256: $InstallerHash"
Write-Host "Release manifest: $ManifestPath"
}
finally {
    if (
        -not [string]::IsNullOrWhiteSpace([string]$TransactionOutputDir) -and
        (Test-Path -LiteralPath $TransactionOutputDir -PathType Container)
    ) {
        Remove-Item -LiteralPath $TransactionOutputDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (
        -not [string]::IsNullOrWhiteSpace([string]$BuildTransactionRoot) -and
        (Test-Path -LiteralPath $BuildTransactionRoot -PathType Container)
    ) {
        Remove-Item -LiteralPath $BuildTransactionRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $ReleaseLock) {
        $ReleaseLock.Dispose()
    }
}
