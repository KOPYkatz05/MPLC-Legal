<#
.SYNOPSIS
Builds the complete Mission Legal Windows release.

.DESCRIPTION
Runs the existing PyInstaller, Velopack, and Inno Setup builders in sequence,
then writes a SHA-256 summary for the release artifacts. Nothing is uploaded.

.EXAMPLE
.\deployment\build_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -InstallVpk

.EXAMPLE
$env:MISSION_LEGAL_VPK_SIGN_PARAMS = '/sha1 CERT_THUMBPRINT /fd sha256 /td sha256 /tr https://timestamp.example'
.\deployment\build_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -RequireSigning `
  -ServerSignToolName missionlegal `
  -ServerSignToolCommand 'signtool.exe sign /fd sha256 /td sha256 /tr https://timestamp.example /a $f'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$UpdateUrl,
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe",
    [string]$OcrModelRoot = "C:\Local Apps\paddle_models\.paddleocr\whl",
    [switch]$SkipRawBuilds,
    [string]$VpkPath,
    [switch]$InstallVpk,
    [string]$PreviousReleaseUrl,
    [ValidateSet("http", "github")]
    [string]$PreviousReleaseProvider,
    [string]$PreviousReleaseDirectory,
    [ValidateSet("http", "github")]
    [string]$UpdateProvider = "http",
    [switch]$Prerelease,
    [string]$ReleaseNotesPath,
    [string]$IsccPath,
    [string]$ClientSignParams,
    [string]$ClientSignTemplate,
    [string]$ClientAzureTrustedSignFile,
    [string]$ClientSignExclude,
    [ValidateRange(1, 100)]
    [int]$ClientSignParallel = 10,
    [string]$ServerSignToolName,
    [string]$ServerSignToolCommand,
    [switch]$RequireSigning,
    [switch]$AllowUnpublishedDevelopmentOverwrite
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RepoPrefix = $RepoRoot.TrimEnd('\') + '\'
$PythonPath = [IO.Path]::GetFullPath($PythonPath)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable was not found: $PythonPath"
}
if ([string]::IsNullOrWhiteSpace($UpdateUrl)) {
    throw "UpdateUrl is required."
}
if (
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseUrl) -and
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseDirectory)
) {
    throw "Use either PreviousReleaseUrl or PreviousReleaseDirectory, not both."
}

$ClientSigningValues = @(@(
    $ClientSignParams,
    $ClientSignTemplate,
    $ClientAzureTrustedSignFile
) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
if ($ClientSigningValues.Count -gt 1) {
    throw "Choose only one client signing mode."
}
$HasClientSigning = (
    $ClientSigningValues.Count -eq 1 -or
    -not [string]::IsNullOrWhiteSpace([string]$env:MISSION_LEGAL_VPK_SIGN_PARAMS)
)
$HasEnvironmentClientSigning = -not [string]::IsNullOrWhiteSpace(
    [string]$env:MISSION_LEGAL_VPK_SIGN_PARAMS
)
if ($HasEnvironmentClientSigning -and $ClientSigningValues.Count -gt 0) {
    throw "MISSION_LEGAL_VPK_SIGN_PARAMS cannot be combined with another client signing mode."
}
$HasServerSigning = (
    -not [string]::IsNullOrWhiteSpace($ServerSignToolName) -and
    -not [string]::IsNullOrWhiteSpace($ServerSignToolCommand)
)
if (
    [string]::IsNullOrWhiteSpace($ServerSignToolName) -xor
    [string]::IsNullOrWhiteSpace($ServerSignToolCommand)
) {
    throw "ServerSignToolName and ServerSignToolCommand must be supplied together."
}
if ($RequireSigning -and -not $HasClientSigning) {
    throw "A production release requires a client signing mode or MISSION_LEGAL_VPK_SIGN_PARAMS."
}
if ($RequireSigning -and -not $HasServerSigning) {
    throw "A production release requires ServerSignToolName and ServerSignToolCommand."
}
if (-not $RequireSigning) {
    Write-Warning "Development release mode: -RequireSigning is off, so artifacts may be unsigned."
}

$AppVersion = (& $PythonPath -c "from version import APP_VERSION; print(APP_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($AppVersion)) {
    throw "Could not read APP_VERSION from version.py."
}
$ReleaseConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot "client_release.json") -Raw |
    ConvertFrom-Json
$Channel = [string]$ReleaseConfig.channel
if ([string]::IsNullOrWhiteSpace($Channel)) {
    throw "client_release.json does not define a release channel."
}

if (-not $SkipRawBuilds) {
    $RawBuildArguments = @{
        Target = "All"
        PythonPath = $PythonPath
        OcrModelRoot = $OcrModelRoot
    }
    & (Join-Path $PSScriptRoot "build_windows.ps1") @RawBuildArguments
}

$ClientArguments = @{
    UpdateUrl = $UpdateUrl
    UpdateProvider = $UpdateProvider
    SignParallel = $ClientSignParallel
    RequireSigning = [bool]$RequireSigning
}
if (-not [string]::IsNullOrWhiteSpace($VpkPath)) {
    $ClientArguments.VpkPath = $VpkPath
}
if ($InstallVpk) {
    $ClientArguments.InstallVpk = $true
}
if (-not [string]::IsNullOrWhiteSpace($PreviousReleaseUrl)) {
    $ClientArguments.PreviousReleaseUrl = $PreviousReleaseUrl
}
if (-not [string]::IsNullOrWhiteSpace($PreviousReleaseProvider)) {
    $ClientArguments.PreviousReleaseProvider = $PreviousReleaseProvider
}
if (-not [string]::IsNullOrWhiteSpace($PreviousReleaseDirectory)) {
    $ClientArguments.PreviousReleaseDirectory = $PreviousReleaseDirectory
}
if ($Prerelease) {
    $ClientArguments.Prerelease = $true
}
if (-not [string]::IsNullOrWhiteSpace($ReleaseNotesPath)) {
    $ClientArguments.ReleaseNotesPath = $ReleaseNotesPath
}
if (-not [string]::IsNullOrWhiteSpace($ClientSignParams)) {
    $ClientArguments.SignParams = $ClientSignParams
}
if (-not [string]::IsNullOrWhiteSpace($ClientSignTemplate)) {
    $ClientArguments.SignTemplate = $ClientSignTemplate
}
if (-not [string]::IsNullOrWhiteSpace($ClientAzureTrustedSignFile)) {
    $ClientArguments.AzureTrustedSignFile = $ClientAzureTrustedSignFile
}
if (-not [string]::IsNullOrWhiteSpace($ClientSignExclude)) {
    $ClientArguments.SignExclude = $ClientSignExclude
}
$ServerArguments = @{
    PythonPath = $PythonPath
    SkipServerPackageBuild = $true
}
if ($AllowUnpublishedDevelopmentOverwrite) {
    $ServerArguments.AllowUnpublishedDevelopmentOverwrite = $true
}
if (-not [string]::IsNullOrWhiteSpace($IsccPath)) {
    $ServerArguments.IsccPath = $IsccPath
}
if ($HasServerSigning) {
    # Hashtable splatting preserves the complete sign-tool command as one value.
    $ServerArguments.SignToolName = $ServerSignToolName
    $ServerArguments.SignToolCommand = $ServerSignToolCommand
}
$ServerReleaseRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "dist\$AppVersion\installers"))
$ServerInstallerPath = Join-Path $ServerReleaseRoot "MissionLegalServerSetup-$AppVersion.exe"
$ServerManifestPath = Join-Path $ServerReleaseRoot "MissionLegalServerSetup-$AppVersion.json"
$HasServerInstaller = Test-Path -LiteralPath $ServerInstallerPath -PathType Leaf
$HasServerManifest = Test-Path -LiteralPath $ServerManifestPath -PathType Leaf
if ($HasServerInstaller -xor $HasServerManifest) {
    throw (
        "The existing same-version server release is incomplete. Preserve the existing file for diagnosis, " +
        "then bump APP_VERSION or explicitly use -AllowUnpublishedDevelopmentOverwrite for unpublished development artifacts."
    )
}
$ReuseExistingServerRelease = $HasServerInstaller -and -not $AllowUnpublishedDevelopmentOverwrite
if ($ReuseExistingServerRelease) {
    Write-Host "Reusing immutable server installer for $AppVersion after validating its manifest."
}
else {
    & (Join-Path $PSScriptRoot "build_server_installer.ps1") @ServerArguments
}

if (-not (Test-Path -LiteralPath $ServerInstallerPath -PathType Leaf)) {
    throw "Expected server installer is missing: $ServerInstallerPath"
}
if (-not (Test-Path -LiteralPath $ServerManifestPath -PathType Leaf)) {
    throw "Expected server installer manifest is missing: $ServerManifestPath"
}
try {
    $ServerManifest = Get-Content -LiteralPath $ServerManifestPath -Raw |
        ConvertFrom-Json
}
catch {
    throw "Server installer manifest is not valid JSON: $ServerManifestPath. $($_.Exception.Message)"
}
$ServerInstaller = Get-Item -LiteralPath $ServerInstallerPath
$ServerInstallerHash = (
    Get-FileHash -LiteralPath $ServerInstallerPath -Algorithm SHA256
).Hash.ToLowerInvariant()
if ([string]$ServerManifest.app_version -ne $AppVersion) {
    throw "Server installer manifest version does not match APP_VERSION."
}
$DevelopmentBuildProperty = $ServerManifest.PSObject.Properties["development_build"]
if (
    $null -ne $DevelopmentBuildProperty -and
    [bool]$DevelopmentBuildProperty.Value -and
    -not $AllowUnpublishedDevelopmentOverwrite
) {
    throw (
        "The existing server artifact is marked as an unpublished development build. " +
        "It cannot be reused as an immutable release artifact."
    )
}
if ([string]$ServerManifest.filename -ne $ServerInstaller.Name) {
    throw "Server installer manifest filename does not match the installer."
}
if ([int64]$ServerManifest.size -ne $ServerInstaller.Length) {
    throw "Server installer manifest size does not match the installer."
}
if (-not $ServerInstallerHash.Equals(
    [string]$ServerManifest.sha256,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Server installer manifest SHA-256 does not match the installer."
}
if ($HasServerSigning -or $RequireSigning) {
    $ServerSignature = Get-AuthenticodeSignature -LiteralPath $ServerInstallerPath
    if ($ServerSignature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Server installer Authenticode signature is not valid: $($ServerSignature.Status)"
    }
}

# Build the immutable client feed last. If server compilation or signing fails,
# the same client version can still be retried after correcting the problem.
& (Join-Path $PSScriptRoot "build_client_release.ps1") @ClientArguments

$ClientReleaseRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "dist\client-releases\$Channel"))
$ClientFeedPath = Join-Path $ClientReleaseRoot "releases.$Channel.json"
$ClientAssetsPath = Join-Path $ClientReleaseRoot "assets.$Channel.json"
$ClientInstallerPath = Join-Path $ClientReleaseRoot "$($ReleaseConfig.packId)-$Channel-Setup.exe"

$Artifacts = [Collections.Generic.List[object]]::new()
$SeenArtifacts = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
function Add-ReleaseArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Role,
        [Parameter(Mandatory = $true)]
        [string]$Kind
    )

    $FullPath = [IO.Path]::GetFullPath($Path)
    if (-not $FullPath.StartsWith($RepoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Release artifact escaped the repository root: $FullPath"
    }
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {
        throw "Expected release artifact is missing: $FullPath"
    }
    if (-not $SeenArtifacts.Add($FullPath)) {
        return
    }
    $File = Get-Item -LiteralPath $FullPath
    $Artifacts.Add([ordered]@{
        role = $Role
        kind = $Kind
        path = $FullPath.Substring($RepoPrefix.Length).Replace('\', '/')
        sha256 = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $File.Length
    }) | Out-Null
}

Add-ReleaseArtifact -Path $ClientInstallerPath -Role "client" -Kind "installer"
Add-ReleaseArtifact -Path $ClientFeedPath -Role "client" -Kind "update_feed"
Add-ReleaseArtifact -Path $ClientAssetsPath -Role "client" -Kind "latest_assets"

$ClientFeed = Get-Content -LiteralPath $ClientFeedPath -Raw | ConvertFrom-Json
$CurrentPackages = @($ClientFeed.Assets | Where-Object {
    ([string]$_.Version).Equals($AppVersion, [StringComparison]::OrdinalIgnoreCase)
})
foreach ($Package in $CurrentPackages) {
    Add-ReleaseArtifact `
        -Path (Join-Path $ClientReleaseRoot ([string]$Package.FileName)) `
        -Role "client" `
        -Kind ([string]$Package.Type).ToLowerInvariant()
}

Add-ReleaseArtifact -Path $ServerInstallerPath -Role "server" -Kind "installer"
Add-ReleaseArtifact -Path $ServerManifestPath -Role "server" -Kind "installer_manifest"

$SummaryRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "dist\$AppVersion"))
New-Item -ItemType Directory -Force -Path $SummaryRoot | Out-Null
$SummaryPath = Join-Path $SummaryRoot "release-summary.json"
$Summary = [ordered]@{
    app_version = $AppVersion
    channel = $Channel
    update_url = $UpdateUrl
    production_signing_required = [bool]$RequireSigning
    client_signing_configured = $HasClientSigning
    server_signing_configured = $HasServerSigning
    built_at = [DateTimeOffset]::UtcNow.ToString("o")
    artifacts = @($Artifacts)
}
$Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $SummaryPath -Encoding UTF8

Write-Host "Mission Legal $AppVersion release completed."
Write-Host "Release summary: $SummaryPath"
