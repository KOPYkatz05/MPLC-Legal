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
    [switch]$InitialRelease,
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
    [string]$ExpectedSignerThumbprint,
    [switch]$RequireSigning,
    [switch]$AllowUnpublishedDevelopmentOverwrite
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RepoPrefix = $RepoRoot.TrimEnd('\') + '\'
$ReleaseSafetyPath = Join-Path $PSScriptRoot "release_safety.ps1"
if (-not (Test-Path -LiteralPath $ReleaseSafetyPath -PathType Leaf)) {
    throw "Release safety helpers are missing: $ReleaseSafetyPath"
}
. $ReleaseSafetyPath
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
if ($InitialRelease -and (
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseUrl) -or
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseDirectory)
)) {
    throw "InitialRelease cannot be combined with a previous-release source."
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
if ($RequireSigning -and [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint)) {
    throw "A production release requires ExpectedSignerThumbprint to bind client and server signatures to one approved certificate."
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint)) {
    $ExpectedSignerThumbprint = Get-NormalizedCertificateThumbprint $ExpectedSignerThumbprint
}
if ($RequireSigning -and $AllowUnpublishedDevelopmentOverwrite) {
    throw "RequireSigning cannot be combined with AllowUnpublishedDevelopmentOverwrite."
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
    ExpectedSignerThumbprint = $ExpectedSignerThumbprint
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
if ($InitialRelease) {
    $ClientArguments.InitialRelease = $true
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
    RequireSigning = [bool]$RequireSigning
    ExpectedSignerThumbprint = $ExpectedSignerThumbprint
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
    ($RequireSigning -or ($ReuseExistingServerRelease -and -not $AllowUnpublishedDevelopmentOverwrite))
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
$ExpectedServerProvenancePath = Join-Path $RepoRoot "dist\$AppVersion\MissionLegalServer.provenance.json"
if (-not (Test-Path -LiteralPath $ExpectedServerProvenancePath -PathType Leaf)) {
    throw "Server raw-package provenance is missing: $ExpectedServerProvenancePath"
}
$ExpectedServerProvenanceHash = (
    Get-FileHash -LiteralPath $ExpectedServerProvenancePath -Algorithm SHA256
).Hash
if (
    $RequireSigning -and
    -not $ExpectedServerProvenanceHash.Equals(
        [string]$ServerManifest.package_provenance.sha256,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "Server installer manifest is not bound to the current raw-package provenance."
}
if ($HasServerSigning -or $RequireSigning) {
    # release_safety.ps1 reports "Server installer Authenticode signature is not valid"
    # through the shared signer/timestamp validation gate before client packing.
    Assert-MissionLegalAuthenticodeSignature `
        -Path $ServerInstallerPath `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -RequireTimestamp:$RequireSigning | Out-Null
    if ($RequireSigning) {
        if (-not ([string]$ServerManifest.expected_signer_thumbprint).Equals(
            $ExpectedSignerThumbprint,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Server installer manifest does not match ExpectedSignerThumbprint."
        }
        $RequiredServerSignatureRoleCounts = [ordered]@{
            server_installer = 1
            server_installed_executable = 3
            server_embedded_maintenance_executable = 1
        }
        foreach ($Role in $RequiredServerSignatureRoleCounts.Keys) {
            $MatchingEvidence = @($ServerManifest.signatures | Where-Object {
                ([string]$_.artifact_role).Equals($Role, [StringComparison]::Ordinal) -and
                [bool]$_.timestamped -and
                ([string]$_.signer_thumbprint).Equals($ExpectedSignerThumbprint, [StringComparison]::OrdinalIgnoreCase)
            })
            if ($MatchingEvidence.Count -ne [int]$RequiredServerSignatureRoleCounts[$Role]) {
                throw (
                    "Server installer manifest has $($MatchingEvidence.Count) timestamped '$Role' signatures; " +
                    "expected $($RequiredServerSignatureRoleCounts[$Role])."
                )
            }
        }
    }
}

$ClientReleaseRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "dist\client-releases\$Channel"))
$ClientFeedPath = Join-Path $ClientReleaseRoot "releases.$Channel.json"
$ClientAssetsPath = Join-Path $ClientReleaseRoot "assets.$Channel.json"
$ClientInstallerPath = Join-Path $ClientReleaseRoot "$($ReleaseConfig.packId)-$Channel-Setup.exe"

# Build the immutable client feed last. A prior interrupted orchestrator run may
# already have committed the complete client transaction, so validate and reuse
# that exact version rather than attempting a same-version rebuild.
$ReuseExistingClientRelease = $false
if (Test-Path -LiteralPath $ClientFeedPath -PathType Leaf) {
    try {
        $ExistingClientFeed = Get-Content -LiteralPath $ClientFeedPath -Raw | ConvertFrom-Json
        $ExistingCurrentFull = @($ExistingClientFeed.Assets | Where-Object {
            ([string]$_.PackageId).Equals([string]$ReleaseConfig.packId, [StringComparison]::Ordinal) -and
            ([string]$_.Version).Equals($AppVersion, [StringComparison]::OrdinalIgnoreCase) -and
            ([string]$_.Type) -ieq 'Full'
        })
        $ReuseExistingClientRelease = $ExistingCurrentFull.Count -gt 0
    }
    catch {
        throw "Existing client feed is invalid and cannot be reused: $ClientFeedPath. $($_.Exception.Message)"
    }
}
if ($ReuseExistingClientRelease) {
    $ClientValidationArguments = $ClientArguments.Clone()
    $ClientValidationArguments.ValidateOnly = $true
    $ClientValidationArguments.OutputDir = $ClientReleaseRoot
    Write-Host "Reusing immutable client release $AppVersion after full validation."
    & (Join-Path $PSScriptRoot "build_client_release.ps1") @ClientValidationArguments
}
else {
    & (Join-Path $PSScriptRoot "build_client_release.ps1") @ClientArguments
}

$ClientProvenancePath = Join-Path $RepoRoot "dist\$AppVersion\MissionLegalClient.provenance.json"
$ClientVersionManifestPath = Join-Path $ClientReleaseRoot "$($ReleaseConfig.packId)-$AppVersion-$Channel-release.json"
if (-not (Test-Path -LiteralPath $ClientVersionManifestPath -PathType Leaf)) {
    throw "Immutable client release manifest is missing: $ClientVersionManifestPath"
}
$ClientVersionManifest = Get-Content -LiteralPath $ClientVersionManifestPath -Raw | ConvertFrom-Json
if (
    [string]$ClientVersionManifest.app_version -ne $AppVersion -or
    [string]$ClientVersionManifest.channel -ne $Channel -or
    [string]$ClientVersionManifest.pack_id -ne [string]$ReleaseConfig.packId
) {
    throw "Client release manifest identity does not match the requested release."
}
$ClientProvenanceHash = (Get-FileHash -LiteralPath $ClientProvenancePath -Algorithm SHA256).Hash
$ClientProvenance = Get-Content -LiteralPath $ClientProvenancePath -Raw | ConvertFrom-Json
if (-not $ClientProvenanceHash.Equals(
    [string]$ClientVersionManifest.raw_package_provenance.sha256,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Client release manifest is not bound to the current raw-package provenance."
}
foreach ($ManifestArtifact in @($ClientVersionManifest.artifacts)) {
    $ManifestArtifactPath = Join-Path $ClientReleaseRoot ([string]$ManifestArtifact.filename)
    if (-not (Test-Path -LiteralPath $ManifestArtifactPath -PathType Leaf)) {
        throw "Client release manifest references a missing artifact: $ManifestArtifactPath"
    }
    $ManifestArtifactFile = Get-Item -LiteralPath $ManifestArtifactPath
    $ManifestArtifactHash = (Get-FileHash -LiteralPath $ManifestArtifactPath -Algorithm SHA256).Hash
    if (
        $ManifestArtifactFile.Length -ne [int64]$ManifestArtifact.size -or
        -not $ManifestArtifactHash.Equals([string]$ManifestArtifact.sha256, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Client release manifest artifact mismatch: $ManifestArtifactPath"
    }
}
if ($RequireSigning) {
    if (
        -not [bool]$ClientVersionManifest.production_signing_required -or
        [bool]$ClientProvenance.source.git_dirty
    ) {
        throw "A production summary cannot reuse a development or dirty-provenance client release."
    }
    if (-not ([string]$ClientVersionManifest.expected_signer_thumbprint).Equals(
        $ExpectedSignerThumbprint,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Client release manifest does not match ExpectedSignerThumbprint."
    }
    $ClientSignatureRoleCounts = [ordered]@{
        client_installer = 1
        client_packaged_executable = 5
    }
    foreach ($Role in $ClientSignatureRoleCounts.Keys) {
        $MatchingEvidence = @($ClientVersionManifest.signatures | Where-Object {
            ([string]$_.artifact_role).Equals($Role, [StringComparison]::Ordinal) -and
            [bool]$_.timestamped -and
            ([string]$_.signer_thumbprint).Equals($ExpectedSignerThumbprint, [StringComparison]::OrdinalIgnoreCase)
        })
        if ($MatchingEvidence.Count -ne [int]$ClientSignatureRoleCounts[$Role]) {
            throw "Client release manifest has the wrong timestamped signature count for '$Role'."
        }
    }
}

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
Add-ReleaseArtifact -Path $ClientVersionManifestPath -Role "client" -Kind "release_manifest"

$ClientFeed = Get-Content -LiteralPath $ClientFeedPath -Raw | ConvertFrom-Json
$CurrentPackages = @($ClientFeed.Assets | Where-Object {
    ([string]$_.PackageId).Equals([string]$ReleaseConfig.packId, [StringComparison]::Ordinal) -and
    ([string]$_.Version).Equals($AppVersion, [StringComparison]::OrdinalIgnoreCase)
})
$CurrentFullPackages = @($CurrentPackages | Where-Object { ([string]$_.Type) -ieq 'Full' })
if ($CurrentFullPackages.Count -ne 1) {
    throw "Client feed must contain exactly one full package for $AppVersion."
}
$CurrentFullPackagePath = Join-Path $ClientReleaseRoot ([string]$CurrentFullPackages[0].FileName)
$EmbeddedUpdateConfig = Get-MissionLegalClientPackageUpdateConfig $CurrentFullPackagePath
if (
    -not ([string]$EmbeddedUpdateConfig.url).Equals($UpdateUrl, [StringComparison]::Ordinal) -or
    -not ([string]$EmbeddedUpdateConfig.provider).Equals($UpdateProvider, [StringComparison]::Ordinal) -or
    [bool]$EmbeddedUpdateConfig.prerelease -ne [bool]$Prerelease
) {
    throw "Client full package update configuration does not match this release invocation."
}
foreach ($Package in $CurrentPackages) {
    Add-ReleaseArtifact `
        -Path (Join-Path $ClientReleaseRoot ([string]$Package.FileName)) `
        -Role "client" `
        -Kind ([string]$Package.Type).ToLowerInvariant()
}

Add-ReleaseArtifact -Path $ServerInstallerPath -Role "server" -Kind "installer"
Add-ReleaseArtifact -Path $ServerManifestPath -Role "server" -Kind "installer_manifest"
$ServerProvenancePath = Join-Path $RepoRoot "dist\$AppVersion\MissionLegalServer.provenance.json"
Add-ReleaseArtifact -Path $ClientProvenancePath -Role "client" -Kind "raw_package_provenance"
Add-ReleaseArtifact -Path $ServerProvenancePath -Role "server" -Kind "raw_package_provenance"

$SignatureEvidence = [Collections.Generic.List[object]]::new()
if ($RequireSigning) {
    $ClientInstallerEvidence = Assert-MissionLegalAuthenticodeSignature `
        -Path $ClientInstallerPath `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -RequireTimestamp
    $ClientInstallerEvidence['artifact_role'] = 'client_installer'
    $SignatureEvidence.Add($ClientInstallerEvidence) | Out-Null

    $ClientPackageEvidence = @(Assert-MissionLegalClientPackageSignatures `
        -PackagePath $CurrentFullPackagePath `
        -TemporaryRoot (Join-Path $RepoRoot 'build\release-validation') `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -RequireTimestamp)
    foreach ($Evidence in $ClientPackageEvidence) {
        $Evidence['artifact_role'] = 'client_packaged_executable'
        $SignatureEvidence.Add($Evidence) | Out-Null
    }
    foreach ($Evidence in @($ServerManifest.signatures)) {
        $SignatureEvidence.Add($Evidence) | Out-Null
    }
}

$SummaryRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "dist\$AppVersion"))
New-Item -ItemType Directory -Force -Path $SummaryRoot | Out-Null
$MetadataRoot = Join-Path $SummaryRoot 'release-metadata'
$SummaryLock = Enter-MissionLegalReleaseLock `
    -LockPath (Join-Path $RepoRoot "build\release-locks\summary-$AppVersion.lock")
$MetadataTransaction = $null
try {
Repair-MissionLegalInterruptedReleaseTransaction -FinalDirectory $MetadataRoot
if (Test-Path -LiteralPath $MetadataRoot -PathType Container) {
    throw (
        "Immutable release metadata already exists for $AppVersion at $MetadataRoot. " +
        "Validate or publish that release; do not replace a completed version."
    )
}
$MetadataTransaction = New-MissionLegalReleaseTransaction `
    -FinalDirectory $MetadataRoot `
    -Label "metadata-$AppVersion"

$MetadataSnapshots = [ordered]@{
    client_feed = 'client-feed.json'
    client_latest_assets = 'client-assets.json'
    client_release_manifest = 'client-release-manifest.json'
    client_raw_provenance = 'client-raw-package-provenance.json'
    server_raw_provenance = 'server-raw-package-provenance.json'
    server_installer_manifest = 'server-installer-manifest.json'
}
Copy-Item -LiteralPath $ClientFeedPath -Destination (Join-Path $MetadataTransaction $MetadataSnapshots.client_feed)
Copy-Item -LiteralPath $ClientAssetsPath -Destination (Join-Path $MetadataTransaction $MetadataSnapshots.client_latest_assets)
Copy-Item -LiteralPath $ClientVersionManifestPath -Destination (Join-Path $MetadataTransaction $MetadataSnapshots.client_release_manifest)
Copy-Item -LiteralPath $ClientProvenancePath -Destination (Join-Path $MetadataTransaction $MetadataSnapshots.client_raw_provenance)
Copy-Item -LiteralPath $ServerProvenancePath -Destination (Join-Path $MetadataTransaction $MetadataSnapshots.server_raw_provenance)
Copy-Item -LiteralPath $ServerManifestPath -Destination (Join-Path $MetadataTransaction $MetadataSnapshots.server_installer_manifest)

$MetadataSnapshotEvidence = [ordered]@{}
foreach ($SnapshotRole in $MetadataSnapshots.Keys) {
    $SnapshotFileName = [string]$MetadataSnapshots[$SnapshotRole]
    $SnapshotPath = Join-Path $MetadataTransaction $SnapshotFileName
    $SnapshotFile = Get-Item -LiteralPath $SnapshotPath
    $MetadataSnapshotEvidence[$SnapshotRole] = [ordered]@{
        filename = $SnapshotFileName
        sha256 = (Get-FileHash -LiteralPath $SnapshotPath -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $SnapshotFile.Length
    }
}

$ClientProvenance = Get-Content -LiteralPath $ClientProvenancePath -Raw | ConvertFrom-Json
$ServerProvenance = Get-Content -LiteralPath $ServerProvenancePath -Raw | ConvertFrom-Json
$Summary = [ordered]@{
    format_version = 1
    app_version = $AppVersion
    channel = $Channel
    update_url = $UpdateUrl
    production_signing_required = [bool]$RequireSigning
    client_signing_configured = $HasClientSigning
    server_signing_configured = $HasServerSigning
    expected_signer_thumbprint = if ($RequireSigning) { $ExpectedSignerThumbprint } else { $null }
    built_at = [DateTimeOffset]::UtcNow.ToString("o")
    source = [ordered]@{
        git_commit = [string]$ClientProvenance.source.git_commit
        git_dirty = [bool]$ClientProvenance.source.git_dirty
        client_tree_sha256 = [string]$ClientProvenance.tree_sha256
        server_tree_sha256 = [string]$ServerProvenance.tree_sha256
    }
    metadata_snapshots = $MetadataSnapshotEvidence
    signatures = @($SignatureEvidence)
    artifacts = @($Artifacts)
}
$TransactionSummaryPath = Join-Path $MetadataTransaction 'release-summary.json'
Write-MissionLegalJsonAtomic -Value $Summary -Path $TransactionSummaryPath -Depth 20 -RequireAbsent | Out-Null
$CommittedMetadataRoot = Complete-MissionLegalReleaseTransaction `
    -TransactionDirectory $MetadataTransaction `
    -FinalDirectory $MetadataRoot
$MetadataTransaction = $null
$SummaryPath = Join-Path $CommittedMetadataRoot 'release-summary.json'
}
finally {
    if (
        -not [string]::IsNullOrWhiteSpace([string]$MetadataTransaction) -and
        (Test-Path -LiteralPath $MetadataTransaction -PathType Container)
    ) {
        Remove-Item -LiteralPath $MetadataTransaction -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $SummaryLock) {
        $SummaryLock.Dispose()
    }
}

Write-Host "Mission Legal $AppVersion release completed."
Write-Host "Release summary: $SummaryPath"
