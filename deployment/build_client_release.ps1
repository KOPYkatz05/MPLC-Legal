<#
.SYNOPSIS
Builds the per-user Mission Legal client installer and static update feed.

.DESCRIPTION
Consumes the existing PyInstaller onedir client folder and runs the pinned
Velopack CLI. The output directory is intentionally stable across releases so
Velopack can use the prior full package to create a delta package. Nothing is
uploaded: the resulting directory can be published by any static HTTPS host.

The immutable product identity, main executable, and required vpk version live
in client_release.json. Relative paths are resolved from the repository root.

.EXAMPLE
.\deployment\build_client_release.ps1 `
  -InstallVpk `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/'

.EXAMPLE
$env:MISSION_LEGAL_VPK_SIGN_PARAMS = '/sha1 CERT_THUMBPRINT /fd sha256 /td sha256 /tr https://timestamp.example'
.\deployment\build_client_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -RequireSigning

.EXAMPLE
.\deployment\build_client_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -PreviousReleaseUrl 'https://updates.example.org/mission-legal/client/' `
  -ReleaseNotesPath '.\release-notes\0.2.0.md' `
  -AzureTrustedSignFile 'C:\signing\metadata.json' `
  -RequireSigning

.NOTES
Production releases should pass -RequireSigning. SignParams can also be set by
MISSION_LEGAL_VPK_SIGN_PARAMS so certificate selection is not hard-coded here.
#>
[CmdletBinding()]
param(
    [string]$Version,
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe",
    [string]$Channel,
    [string]$InputDir,
    [string]$ProvenanceManifestPath,
    [string]$OutputDir,
    [string]$VpkPath,
    [switch]$InstallVpk,
    [string]$PreviousReleaseUrl,
    [ValidateSet("http", "github")]
    [string]$PreviousReleaseProvider,
    [string]$PreviousReleaseDirectory,
    [switch]$InitialRelease,
    [string]$UpdateUrl,
    [ValidateSet("http", "github")]
    [string]$UpdateProvider = "http",
    [switch]$Prerelease,
    [string]$ReleaseNotesPath,
    [string]$IconPath,
    [string]$SplashImagePath,
    [string]$SignParams,
    [string]$SignTemplate,
    [string]$AzureTrustedSignFile,
    [string]$SignExclude,
    [ValidateRange(1, 100)]
    [int]$SignParallel = 10,
    [string]$ExpectedSignerThumbprint,
    [switch]$RequireSigning,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$ConfigPath = Join-Path $PSScriptRoot "client_release.json"
$ReleaseSafetyPath = Join-Path $PSScriptRoot "release_safety.ps1"
if (-not (Test-Path -LiteralPath $ReleaseSafetyPath -PathType Leaf)) {
    throw "Release safety helpers are missing: $ReleaseSafetyPath"
}
. $ReleaseSafetyPath

function Get-RepoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Resolve-ExistingFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $FullPath = Get-RepoPath $Path
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {
        throw "$Description was not found: $FullPath"
    }
    return (Resolve-Path -LiteralPath $FullPath).Path
}

function Resolve-ExistingDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $FullPath = Get-RepoPath $Path
    if (-not (Test-Path -LiteralPath $FullPath -PathType Container)) {
        throw "$Description was not found: $FullPath"
    }
    return (Resolve-Path -LiteralPath $FullPath).Path
}

function Test-PathInside {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,
        [Parameter(Mandatory = $true)]
        [string]$Parent
    )

    $CandidatePath = [IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $ParentPath = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    if ($CandidatePath.Equals($ParentPath, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $Prefix = $ParentPath + [IO.Path]::DirectorySeparatorChar
    return $CandidatePath.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)
}

function Get-ConfiguredVersion {
    $VersionText = Get-Content -LiteralPath (Join-Path $RepoRoot "version.py") -Raw
    $Match = [regex]::Match(
        $VersionText,
        '(?m)^APP_VERSION\s*=\s*["''](?<version>[^"'']+)["'']\s*$'
    )
    if (-not $Match.Success) {
        throw "Could not read APP_VERSION from version.py."
    }
    return $Match.Groups["version"].Value
}

function Get-ConfiguredApiVersion {
    $VersionText = Get-Content -LiteralPath (Join-Path $RepoRoot "version.py") -Raw
    $Match = [regex]::Match(
        $VersionText,
        '(?m)^API_VERSION\s*=\s*["''](?<version>[^"'']+)["'']\s*$'
    )
    if (-not $Match.Success) {
        throw "Could not read API_VERSION from version.py."
    }
    return $Match.Groups["version"].Value
}

function Get-ConfiguredSchemaVersion {
    $VersionText = Get-Content -LiteralPath (Join-Path $RepoRoot "version.py") -Raw
    $Match = [regex]::Match(
        $VersionText,
        '(?m)^SCHEMA_VERSION\s*=\s*(?<version>[0-9]+)\s*$'
    )
    if (-not $Match.Success) {
        throw "Could not read SCHEMA_VERSION from version.py."
    }
    return [int]$Match.Groups["version"].Value
}

function Assert-SemVer {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $SemVerPattern = '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
    if ($Value -notmatch $SemVerPattern) {
        throw "Release version must be SemVer 2 with three numeric parts: $Value"
    }
}

function Get-FeedAssets {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FeedPath,
        [switch]$AllowMissing
    )

    if (-not (Test-Path -LiteralPath $FeedPath -PathType Leaf)) {
        if ($AllowMissing) {
            return @()
        }
        throw "Velopack release feed is missing: $FeedPath"
    }

    try {
        $Feed = Get-Content -LiteralPath $FeedPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Velopack release feed is not valid JSON: $FeedPath. $($_.Exception.Message)"
    }

    $AssetsProperty = $Feed.PSObject.Properties |
        Where-Object { $_.Name -ieq "Assets" } |
        Select-Object -First 1
    if ($null -eq $AssetsProperty) {
        throw "Velopack release feed has no Assets collection: $FeedPath"
    }
    return @($AssetsProperty.Value)
}

function Get-LatestAssetEntries {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ManifestPath
    )

    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Velopack latest-assets manifest is missing: $ManifestPath"
    }
    try {
        $Entries = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Velopack latest-assets manifest is not valid JSON: $ManifestPath. $($_.Exception.Message)"
    }
    return @($Entries)
}

function Assert-SafeFeedAsset {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Asset,
        [Parameter(Mandatory = $true)]
        [string]$ReleaseRoot,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedPackId,
        [switch]$VerifyHash,
        [switch]$RequireSha256
    )

    $PackageId = [string]$Asset.PackageId
    if (-not $PackageId.Equals($ExpectedPackId, [StringComparison]::Ordinal)) {
        throw "Release feed contains unexpected package id '$PackageId'; expected '$ExpectedPackId'."
    }

    $FileName = [string]$Asset.FileName
    if (-not (Test-MissionLegalSafeWindowsLeafName $FileName)) {
        throw "Release feed contains an unsafe asset file name: '$FileName'."
    }

    $AssetPath = Join-Path $ReleaseRoot $FileName
    if (-not (Test-Path -LiteralPath $AssetPath -PathType Leaf)) {
        throw "Release feed references a missing package: $AssetPath"
    }
    $AssetFile = Get-Item -LiteralPath $AssetPath
    if ($AssetFile.Length -le 0) {
        throw "Release package is empty: $AssetPath"
    }

    $SizeProperty = $Asset.PSObject.Properties |
        Where-Object { $_.Name -ieq 'Size' } |
        Select-Object -First 1
    if ($RequireSha256 -and (
        $null -eq $SizeProperty -or
        [int64]$SizeProperty.Value -le 0
    )) {
        throw "Release feed asset '$FileName' is missing a valid positive size."
    }
    if ($null -ne $SizeProperty -and [int64]$SizeProperty.Value -ne $AssetFile.Length) {
        throw "Release feed size does not match '$FileName'."
    }

    if ($VerifyHash -and $null -ne $Asset.SHA1 -and -not [string]::IsNullOrWhiteSpace([string]$Asset.SHA1)) {
        $ActualHash = (Get-FileHash -LiteralPath $AssetPath -Algorithm SHA1).Hash
        if (-not $ActualHash.Equals([string]$Asset.SHA1, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Release feed SHA1 does not match '$FileName'."
        }
    }
    $Sha256Property = $Asset.PSObject.Properties |
        Where-Object { $_.Name -ieq "SHA256" } |
        Select-Object -First 1
    if ($RequireSha256 -and (
        $null -eq $Sha256Property -or
        [string]$Sha256Property.Value -notmatch '^[0-9A-Fa-f]{64}$'
    )) {
        throw "Release feed asset '$FileName' is missing a valid SHA-256 digest."
    }
    if (
        $VerifyHash -and
        $null -ne $Sha256Property -and
        -not [string]::IsNullOrWhiteSpace([string]$Sha256Property.Value)
    ) {
        $ActualHash = (Get-FileHash -LiteralPath $AssetPath -Algorithm SHA256).Hash
        if (-not $ActualHash.Equals([string]$Sha256Property.Value, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Release feed SHA256 does not match '$FileName'."
        }
    }
}

function Test-ReleaseArtifacts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReleaseRoot,
        [Parameter(Mandatory = $true)]
        [string]$ReleaseChannel,
        [Parameter(Mandatory = $true)]
        [string]$ReleaseVersion,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedPackId,
        [bool]$ExpectDelta,
        [bool]$ExpectSignature,
        [bool]$VerifyAllHashes,
        [bool]$RequireSha256,
        [string]$ExpectedSignerThumbprint,
        [string]$SignatureTemporaryRoot,
        [bool]$RequireTimestamp
    )

    $FeedPath = Join-Path $ReleaseRoot "releases.$ReleaseChannel.json"
    $Assets = @(Get-FeedAssets -FeedPath $FeedPath)
    if ($Assets.Count -eq 0) {
        throw "Velopack release feed contains no packages: $FeedPath"
    }

    foreach ($Asset in $Assets) {
        $IsCurrent = (
            ([string]$Asset.PackageId).Equals($ExpectedPackId, [StringComparison]::Ordinal) -and
            ([string]$Asset.Version).Equals($ReleaseVersion, [StringComparison]::OrdinalIgnoreCase)
        )
        Assert-SafeFeedAsset `
            -Asset $Asset `
            -ReleaseRoot $ReleaseRoot `
            -ExpectedPackId $ExpectedPackId `
            -VerifyHash:($IsCurrent -or $VerifyAllHashes) `
            -RequireSha256:$RequireSha256
    }

    $CurrentAssets = @($Assets | Where-Object {
        ([string]$_.PackageId).Equals($ExpectedPackId, [StringComparison]::Ordinal) -and
        ([string]$_.Version).Equals($ReleaseVersion, [StringComparison]::OrdinalIgnoreCase)
    })
    $FullAssets = @($CurrentAssets | Where-Object { ([string]$_.Type) -ieq "Full" })
    if ($FullAssets.Count -ne 1) {
        throw "Release feed must contain exactly one full package for $ExpectedPackId $ReleaseVersion."
    }

    $DeltaAssets = @($CurrentAssets | Where-Object { ([string]$_.Type) -ieq "Delta" })
    if ($ExpectDelta -and $DeltaAssets.Count -lt 1) {
        throw "A previous full release was available, but no delta package was generated for $ReleaseVersion."
    }

    $LatestAssetsPath = Join-Path $ReleaseRoot "assets.$ReleaseChannel.json"
    $LatestAssets = @(Get-LatestAssetEntries -ManifestPath $LatestAssetsPath)
    $InstallerEntries = @($LatestAssets | Where-Object { ([string]$_.Type) -ieq "Installer" })
    if ($InstallerEntries.Count -ne 1) {
        throw "Velopack latest-assets manifest must contain exactly one installer: $LatestAssetsPath"
    }
    $SetupName = [string]$InstallerEntries[0].RelativeFileName
    if (-not (Test-MissionLegalSafeWindowsLeafName $SetupName)) {
        throw "Velopack latest-assets manifest contains an unsafe installer file name: '$SetupName'."
    }
    $SetupPath = Join-Path $ReleaseRoot $SetupName
    if (-not (Test-Path -LiteralPath $SetupPath -PathType Leaf)) {
        throw "Velopack per-user installer is missing: $SetupPath"
    }
    if ((Get-Item -LiteralPath $SetupPath).Length -le 0) {
        throw "Velopack per-user installer is empty: $SetupPath"
    }

    $SignatureEvidence = @()
    if ($ExpectSignature) {
        if ([string]::IsNullOrWhiteSpace($SignatureTemporaryRoot)) {
            throw "SignatureTemporaryRoot is required when signed client artifacts are validated."
        }
        New-Item -ItemType Directory -Force -Path $SignatureTemporaryRoot | Out-Null
        $InstallerEvidence = Assert-MissionLegalAuthenticodeSignature `
            -Path $SetupPath `
            -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
            -RequireTimestamp:$RequireTimestamp
        $InstallerEvidence['artifact_role'] = 'client_installer'
        $SignatureEvidence += $InstallerEvidence

        $FullPackagePath = Join-Path $ReleaseRoot ([string]$FullAssets[0].FileName)
        $PackageEvidence = @(Assert-MissionLegalClientPackageSignatures `
            -PackagePath $FullPackagePath `
            -TemporaryRoot $SignatureTemporaryRoot `
            -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
            -RequireTimestamp:$RequireTimestamp)
        foreach ($Evidence in $PackageEvidence) {
            $Evidence['artifact_role'] = 'client_packaged_executable'
            $SignatureEvidence += $Evidence
        }
    }

    return [pscustomobject]@{
        Setup = $SetupPath
        Feed = $FeedPath
        FullPackage = (Join-Path $ReleaseRoot ([string]$FullAssets[0].FileName))
        DeltaPackages = @($DeltaAssets | ForEach-Object { Join-Path $ReleaseRoot ([string]$_.FileName) })
        SignatureEvidence = @($SignatureEvidence)
    }
}

function Get-VpkVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable
    )

    $Output = @(& $Executable -H 2>&1)
    $ExitCode = $LASTEXITCODE
    $Text = ($Output | Out-String).Trim()
    $Match = [regex]::Match($Text, 'Velopack CLI\s+(?<version>[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)')
    if ($ExitCode -ne 0 -or -not $Match.Success) {
        throw "Could not determine the vpk version from '$Executable'."
    }
    return $Match.Groups["version"].Value
}

function Resolve-Vpk {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RequiredVersion,
        [Parameter(Mandatory = $true)]
        [string]$PackageUrl,
        [Parameter(Mandatory = $true)]
        [string]$PackageSha256,
        [Parameter(Mandatory = $true)]
        [string]$TargetFramework
    )

    $PinnedToolRoot = Join-Path $RepoRoot "build\tools\velopack\$RequiredVersion"
    $PinnedToolLauncher = Join-Path $PinnedToolRoot "vpk.cmd"
    $PackagePath = Join-Path $PinnedToolRoot "vpk.$RequiredVersion.nupkg"
    $PayloadRoot = Join-Path $PinnedToolRoot "payload"
    $ToolDll = Join-Path $PayloadRoot "tools\$TargetFramework\any\vpk.dll"

    if (-not [string]::IsNullOrWhiteSpace($VpkPath)) {
        if ($InstallVpk) {
            throw "Use either -VpkPath or -InstallVpk, not both."
        }
        $Candidate = Resolve-ExistingFile -Path $VpkPath -Description "vpk executable"
    }
    elseif (Test-Path -LiteralPath $PinnedToolLauncher -PathType Leaf) {
        $Candidate = $PinnedToolLauncher
    }
    elseif ($InstallVpk) {
        if ($PackageSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
            throw "Configured vpk package SHA-256 is invalid."
        }
        $PackageUri = $null
        if (
            -not [Uri]::TryCreate($PackageUrl, [UriKind]::Absolute, [ref]$PackageUri) -or
            $PackageUri.Scheme -ne "https"
        ) {
            throw "Configured vpk package URL must use absolute HTTPS: $PackageUrl"
        }
        $FrameworkMatch = [regex]::Match($TargetFramework, '^net(?<major>[0-9]+)\.0$')
        if (-not $FrameworkMatch.Success) {
            throw "Configured vpk target framework is invalid: $TargetFramework"
        }

        $Dotnet = Get-Command dotnet -CommandType Application -ErrorAction SilentlyContinue
        if ($null -eq $Dotnet) {
            throw ".NET $($FrameworkMatch.Groups['major'].Value) runtime or newer is required to run vpk."
        }
        $InstalledRuntimes = @(& $Dotnet.Source --list-runtimes 2>&1)
        $RequiredRuntimePrefix = "Microsoft.NETCore.App $($FrameworkMatch.Groups['major'].Value)."
        if ($LASTEXITCODE -ne 0 -or @($InstalledRuntimes | Where-Object {
            ([string]$_).StartsWith($RequiredRuntimePrefix, [StringComparison]::OrdinalIgnoreCase)
        }).Count -eq 0) {
            throw ".NET $($FrameworkMatch.Groups['major'].Value) runtime is required to run vpk $RequiredVersion."
        }

        New-Item -ItemType Directory -Force -Path $PinnedToolRoot | Out-Null
        if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
            $DownloadPath = Join-Path $PinnedToolRoot ("download-" + [Guid]::NewGuid().ToString("N") + ".tmp")
            $WebClient = New-Object Net.WebClient
            $WebClient.Headers["User-Agent"] = "MissionLegalReleaseBuilder/$RequiredVersion"
            try {
                Write-Host "Downloading pinned vpk $RequiredVersion from the official NuGet feed..."
                $WebClient.DownloadFile($PackageUri, $DownloadPath)
                $DownloadedHash = (Get-FileHash -LiteralPath $DownloadPath -Algorithm SHA256).Hash
                if (-not $DownloadedHash.Equals($PackageSha256, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Downloaded vpk package hash mismatch. Expected $PackageSha256, found $DownloadedHash."
                }
                Move-Item -LiteralPath $DownloadPath -Destination $PackagePath
            }
            finally {
                $WebClient.Dispose()
                if (Test-Path -LiteralPath $DownloadPath -PathType Leaf) {
                    Remove-Item -LiteralPath $DownloadPath -Force
                }
            }
        }

        $CachedHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash
        if (-not $CachedHash.Equals($PackageSha256, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Cached vpk package hash mismatch: $PackagePath"
        }

        if (-not (Test-Path -LiteralPath $PayloadRoot -PathType Container)) {
            $ExtractRoot = Join-Path $PinnedToolRoot ("payload-" + [Guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Path $ExtractRoot | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [IO.Compression.ZipFile]::ExtractToDirectory($PackagePath, $ExtractRoot)
            $ExtractedDll = Join-Path $ExtractRoot "tools\$TargetFramework\any\vpk.dll"
            if (-not (Test-Path -LiteralPath $ExtractedDll -PathType Leaf)) {
                throw "Pinned vpk package does not contain the expected tool: $ExtractedDll"
            }
            Move-Item -LiteralPath $ExtractRoot -Destination $PayloadRoot
        }
        if (-not (Test-Path -LiteralPath $ToolDll -PathType Leaf)) {
            throw "Pinned vpk payload is incomplete: $ToolDll"
        }

        $LauncherText = "@echo off`r`ndotnet `"%~dp0payload\tools\$TargetFramework\any\vpk.dll`" %*`r`nexit /b %ERRORLEVEL%`r`n"
        [IO.File]::WriteAllText($PinnedToolLauncher, $LauncherText, [Text.Encoding]::ASCII)
        $Candidate = $PinnedToolLauncher
    }
    else {
        $Command = Get-Command vpk -CommandType Application -ErrorAction SilentlyContinue
        if ($null -eq $Command) {
            throw "vpk $RequiredVersion was not found. Re-run with -InstallVpk or provide -VpkPath."
        }
        $Candidate = $Command.Source
    }

    $ActualVersion = Get-VpkVersion -Executable $Candidate
    if (-not $ActualVersion.Equals($RequiredVersion, [StringComparison]::OrdinalIgnoreCase)) {
        throw "vpk version mismatch. Required $RequiredVersion, found $ActualVersion at $Candidate."
    }
    return $Candidate
}

function Invoke-Vpk {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Operation
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "vpk failed while $Operation (exit code $LASTEXITCODE)."
    }
}

function Write-ClientUpdateConfig {
    param(
        [Parameter(Mandatory = $true)] [string]$DestinationDirectory,
        [Parameter(Mandatory = $true)] [string]$SourceUrl,
        [Parameter(Mandatory = $true)] [string]$Provider,
        [bool]$IncludePrereleases
    )

    $Uri = $null
    if (-not [Uri]::TryCreate($SourceUrl, [UriKind]::Absolute, [ref]$Uri)) {
        throw "UpdateUrl must be an absolute URL: $SourceUrl"
    }
    if (-not [string]::IsNullOrWhiteSpace($Uri.UserInfo) -or -not [string]::IsNullOrWhiteSpace($Uri.Query) -or -not [string]::IsNullOrWhiteSpace($Uri.Fragment)) {
        throw "UpdateUrl must not embed credentials, query tokens, or fragments."
    }
    if ($Provider -eq "github") {
        if ($Uri.Scheme -ne "https" -or [string]::IsNullOrWhiteSpace($Uri.Host)) {
            throw "GitHub update sources must be public HTTPS repository URLs."
        }
    }
    elseif ($Uri.Scheme -ne "https") {
        $IsLocalHttp = $Uri.Scheme -eq "http" -and $Uri.Host -in @("localhost", "127.0.0.1")
        if (-not $IsLocalHttp) {
            throw "Static update sources must use HTTPS; localhost HTTP is allowed only for installed-update tests."
        }
        Write-Warning "Packaging a localhost update URL; this build is suitable only for local update testing."
    }

    $Payload = [ordered]@{ url = $SourceUrl; provider = $Provider; prerelease = $IncludePrereleases }
    $Json = ($Payload | ConvertTo-Json -Depth 3) + "`n"
    $ConfigPath = Join-Path $DestinationDirectory "mission-legal-update.json"
    $TemporaryPath = "$ConfigPath.$PID.tmp"
    try {
        [IO.File]::WriteAllText($TemporaryPath, $Json, (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $TemporaryPath -Destination $ConfigPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $TemporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $TemporaryPath -Force
        }
    }
    return $ConfigPath
}

function Get-PublishedHttpFeedAssets {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$ReleaseChannel
    )

    $BaseUri = [Uri]::new($BaseUrl)
    if (-not $BaseUri.AbsoluteUri.EndsWith('/', [StringComparison]::Ordinal)) {
        $BaseUri = [Uri]::new($BaseUri.AbsoluteUri + '/')
    }
    $FeedUri = [Uri]::new($BaseUri, "releases.$ReleaseChannel.json")
    Add-Type -AssemblyName System.Net.Http
    $Handler = [Net.Http.HttpClientHandler]::new()
    $Handler.AllowAutoRedirect = $false
    $Client = [Net.Http.HttpClient]::new($Handler)
    try {
        $Response = $Client.GetAsync($FeedUri).GetAwaiter().GetResult()
        try {
            if ($Response.StatusCode -eq [Net.HttpStatusCode]::NotFound) {
                return @()
            }
            if ($Response.StatusCode -ne [Net.HttpStatusCode]::OK) {
                throw (
                    "Initial-release history check returned $([int]$Response.StatusCode) " +
                    "$($Response.ReasonPhrase) for $FeedUri."
                )
            }
            $Json = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            try {
                $Feed = $Json | ConvertFrom-Json
            }
            catch {
                throw "Published initial-release history is not valid JSON: $FeedUri"
            }
            $AssetsProperty = $Feed.PSObject.Properties | Where-Object {
                $_.Name -ieq 'Assets'
            } | Select-Object -First 1
            if ($null -eq $AssetsProperty) {
                throw "Published initial-release history has no Assets collection: $FeedUri"
            }
            return @($AssetsProperty.Value)
        }
        finally {
            $Response.Dispose()
        }
    }
    finally {
        $Client.Dispose()
        $Handler.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Client release configuration is missing: $ConfigPath"
}
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json

$RequiredVpkVersion = [string]$Config.vpkVersion
$VpkPackageUrl = [string]$Config.vpkPackageUrl
$VpkPackageSha256 = [string]$Config.vpkPackageSha256
$VpkTargetFramework = [string]$Config.vpkTargetFramework
$PackId = [string]$Config.packId
$PackTitle = [string]$Config.packTitle
$PackAuthors = [string]$Config.packAuthors
$MainExe = [string]$Config.mainExe
$Runtime = [string]$Config.runtime
$Shortcuts = [string]$Config.shortcuts
$DeltaMode = [string]$Config.deltaMode

foreach ($RequiredValue in @(
    @{ Name = "vpkVersion"; Value = $RequiredVpkVersion },
    @{ Name = "vpkPackageUrl"; Value = $VpkPackageUrl },
    @{ Name = "vpkPackageSha256"; Value = $VpkPackageSha256 },
    @{ Name = "vpkTargetFramework"; Value = $VpkTargetFramework },
    @{ Name = "packId"; Value = $PackId },
    @{ Name = "packTitle"; Value = $PackTitle },
    @{ Name = "packAuthors"; Value = $PackAuthors },
    @{ Name = "mainExe"; Value = $MainExe },
    @{ Name = "runtime"; Value = $Runtime },
    @{ Name = "shortcuts"; Value = $Shortcuts },
    @{ Name = "deltaMode"; Value = $DeltaMode }
)) {
    if ([string]::IsNullOrWhiteSpace([string]$RequiredValue.Value)) {
        throw "client_release.json is missing '$($RequiredValue.Name)'."
    }
}
if ($VpkPackageSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
    throw "client_release.json has an invalid vpkPackageSha256."
}

if ($PackId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Configured packId contains unsupported characters: $PackId"
}
if (
    [IO.Path]::IsPathRooted($MainExe) -or
    -not $MainExe.Equals([IO.Path]::GetFileName($MainExe), [StringComparison]::Ordinal) -or
    -not $MainExe.EndsWith(".exe", [StringComparison]::OrdinalIgnoreCase)
) {
    throw "Configured mainExe must be an executable file name, not a path: $MainExe"
}

$ConfiguredVersion = Get-ConfiguredVersion
$ConfiguredApiVersion = Get-ConfiguredApiVersion
$ConfiguredSchemaVersion = Get-ConfiguredSchemaVersion
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $ConfiguredVersion
}
Assert-SemVer $Version

if ([string]::IsNullOrWhiteSpace($Channel)) {
    $Channel = [string]$Config.channel
}
if ($Channel -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Channel contains unsupported characters: $Channel"
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $RepoRoot "dist\client-releases\$Channel"
}
$OutputDir = Get-RepoPath $OutputDir
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputDir) | Out-Null
$FinalOutputDir = $OutputDir

if ([string]::IsNullOrWhiteSpace($SignParams) -and -not [string]::IsNullOrWhiteSpace($env:MISSION_LEGAL_VPK_SIGN_PARAMS)) {
    $SignParams = $env:MISSION_LEGAL_VPK_SIGN_PARAMS
}
$SigningValues = @(@(
    $SignParams,
    $SignTemplate,
    $AzureTrustedSignFile
) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
if ($SigningValues.Count -gt 1) {
    throw "Choose only one signing mode: -SignParams, -SignTemplate, or -AzureTrustedSignFile."
}
$HasSigning = (
    -not [string]::IsNullOrWhiteSpace($SignParams) -or
    -not [string]::IsNullOrWhiteSpace($SignTemplate) -or
    -not [string]::IsNullOrWhiteSpace($AzureTrustedSignFile)
)
if ($RequireSigning -and -not $ValidateOnly -and -not $HasSigning) {
    throw "A production release requires signing. Supply a signing mode or MISSION_LEGAL_VPK_SIGN_PARAMS."
}
if ($RequireSigning -and [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint)) {
    throw "A production release requires ExpectedSignerThumbprint to bind signatures to the approved certificate."
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint)) {
    $ExpectedSignerThumbprint = Get-NormalizedCertificateThumbprint $ExpectedSignerThumbprint
}

if ($ValidateOnly) {
    $ValidationFeedPath = Join-Path $OutputDir "releases.$Channel.json"
    $ValidationAssets = @(Get-FeedAssets -FeedPath $ValidationFeedPath)
    $HasPriorValidationRelease = @($ValidationAssets | Where-Object {
        ([string]$_.PackageId).Equals($PackId, [StringComparison]::Ordinal) -and
        ([string]$_.Type) -ieq "Full" -and
        -not ([string]$_.Version).Equals($Version, [StringComparison]::OrdinalIgnoreCase)
    }).Count -gt 0
    $Result = Test-ReleaseArtifacts `
        -ReleaseRoot $OutputDir `
        -ReleaseChannel $Channel `
        -ReleaseVersion $Version `
        -ExpectedPackId $PackId `
        -ExpectDelta:$HasPriorValidationRelease `
        -ExpectSignature:($HasSigning -or $RequireSigning) `
        -VerifyAllHashes:$RequireSigning `
        -RequireSha256:$RequireSigning `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -SignatureTemporaryRoot (Join-Path $RepoRoot "build\release-validation") `
        -RequireTimestamp:$RequireSigning
    Write-Host "Client release artifacts are valid:"
    Write-Host "  Installer: $($Result.Setup)"
    Write-Host "  Feed:      $($Result.Feed)"
    Write-Host "  Full:      $($Result.FullPackage)"
    return
}

$PythonPath = [IO.Path]::GetFullPath($PythonPath)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable for provenance verification was not found: $PythonPath"
}
$ProvenanceHelper = Join-Path $PSScriptRoot "package_provenance.py"
if (-not (Test-Path -LiteralPath $ProvenanceHelper -PathType Leaf)) {
    throw "Package provenance helper is missing: $ProvenanceHelper"
}

if ([string]::IsNullOrWhiteSpace($InputDir)) {
    $InputDir = Join-Path $RepoRoot "dist\$Version\MissionLegalClient"
}
$InputDir = Resolve-ExistingDirectory -Path $InputDir -Description "PyInstaller client directory"
$MainExePath = Join-Path $InputDir $MainExe
if (-not (Test-Path -LiteralPath $MainExePath -PathType Leaf)) {
    throw "Configured client executable is missing from the PyInstaller folder: $MainExePath"
}
$UpdateWorkerPath = Join-Path $InputDir "MissionLegalUpdateWorker.exe"
if (-not (Test-Path -LiteralPath $UpdateWorkerPath -PathType Leaf)) {
    throw "The isolated client update worker is missing from the PyInstaller folder: $UpdateWorkerPath"
}

if ([string]::IsNullOrWhiteSpace($ProvenanceManifestPath)) {
    $InputParent = Split-Path -Parent $InputDir
    $InputName = Split-Path -Leaf $InputDir
    $ProvenanceManifestPath = Join-Path $InputParent "$InputName.provenance.json"
}
$ProvenanceManifestPath = Resolve-ExistingFile `
    -Path $ProvenanceManifestPath `
    -Description "Client raw-package provenance manifest"
$ProvenanceArguments = @(
    $ProvenanceHelper,
    "verify",
    "--repo-root", $RepoRoot,
    "--package-dir", $InputDir,
    "--manifest-path", $ProvenanceManifestPath,
    "--expected-role", "client",
    "--expected-app-version", $Version,
    "--expected-api-version", $ConfiguredApiVersion,
    "--expected-schema-version", [string]$ConfiguredSchemaVersion,
    "--required-windows-version-exe", "MissionLegal.exe",
    "--required-windows-version-exe", "MissionLegalDiagnostics.exe",
    "--required-windows-version-exe", "MissionLegalClientSetup.exe",
    "--required-windows-version-exe", "MissionLegalUpdateWorker.exe"
)
function Assert-ClientRawPackageProvenance {
    & $PythonPath -B @ProvenanceArguments
    if ($LASTEXITCODE -ne 0) {
        throw (
            "Client raw package does not match its provenance manifest. " +
            "Rebuild it with deployment\build_windows.ps1 -Target Client."
        )
    }
}
Assert-ClientRawPackageProvenance
if ($RequireSigning) {
    try {
        $VerifiedProvenance = Get-Content -LiteralPath $ProvenanceManifestPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Could not read the verified client provenance for production policy checks: $ProvenanceManifestPath"
    }
    if ([bool]$VerifiedProvenance.source.git_dirty) {
        throw (
            "A signed production client release requires package provenance from a clean Git commit. " +
            "Commit the release source and rebuild the raw client package."
        )
    }
}

if ((Test-PathInside -Candidate $OutputDir -Parent $InputDir) -or (Test-PathInside -Candidate $InputDir -Parent $OutputDir)) {
    throw "Input and output directories must not contain one another. Input: $InputDir Output: $OutputDir"
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

$ForbiddenFiles = @(Get-ChildItem -LiteralPath $InputDir -Recurse -Force -File | Where-Object {
    Test-ForbiddenPackagedState -File $_
})
if ($ForbiddenFiles.Count -gt 0) {
    $Names = ($ForbiddenFiles | Select-Object -First 10 -ExpandProperty FullName) -join ", "
    throw "Client package contains forbidden persistent/private files: $Names"
}

if ([string]::IsNullOrWhiteSpace($UpdateUrl)) {
    $UpdateUrl = [string]$env:MISSION_LEGAL_RELEASE_UPDATE_URL
}
if ([string]::IsNullOrWhiteSpace($UpdateUrl)) {
    throw "UpdateUrl is required so the installed client knows where to check for releases."
}
if ($RequireSigning) {
    $ProductionUpdateUri = $null
    if (
        -not [Uri]::TryCreate($UpdateUrl, [UriKind]::Absolute, [ref]$ProductionUpdateUri) -or
        $ProductionUpdateUri.Scheme -ne "https" -or
        $ProductionUpdateUri.Host -in @("localhost", "127.0.0.1", "::1") -or
        -not [string]::IsNullOrWhiteSpace($ProductionUpdateUri.UserInfo) -or
        -not [string]::IsNullOrWhiteSpace($ProductionUpdateUri.Query) -or
        -not [string]::IsNullOrWhiteSpace($ProductionUpdateUri.Fragment)
    ) {
        throw "A signed production release requires a non-loopback HTTPS update source."
    }
}

if ($InitialRelease -and (
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseUrl) -or
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseDirectory)
)) {
    throw "InitialRelease cannot be combined with a previous-release source."
}
if (
    $RequireSigning -and
    -not $InitialRelease -and
    [string]::IsNullOrWhiteSpace($PreviousReleaseUrl) -and
    [string]::IsNullOrWhiteSpace($PreviousReleaseDirectory)
) {
    $PreviousReleaseUrl = $UpdateUrl
    $PreviousReleaseProvider = $UpdateProvider
    Write-Host "Production history source defaults to the published update feed: $PreviousReleaseUrl"
}

if (-not [string]::IsNullOrWhiteSpace($PreviousReleaseUrl) -and -not [string]::IsNullOrWhiteSpace($PreviousReleaseDirectory)) {
    throw "Use either -PreviousReleaseUrl or -PreviousReleaseDirectory, not both."
}
if (
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseProvider) -and
    [string]::IsNullOrWhiteSpace($PreviousReleaseUrl)
) {
    throw "PreviousReleaseProvider can be used only with PreviousReleaseUrl."
}
if (
    -not [string]::IsNullOrWhiteSpace($PreviousReleaseUrl) -and
    [string]::IsNullOrWhiteSpace($PreviousReleaseProvider)
) {
    $PreviousReleaseProvider = $UpdateProvider
}
if ($RequireSigning -and $InitialRelease) {
    if ($UpdateProvider -eq 'http') {
        $PublishedInitialAssets = @(Get-PublishedHttpFeedAssets `
            -BaseUrl $UpdateUrl `
            -ReleaseChannel $Channel)
        if ($PublishedInitialAssets.Count -gt 0) {
            throw "InitialRelease was requested, but the published HTTPS feed already contains assets."
        }
    }
    else {
        # vpk's public GitHub reader is the authoritative history probe for a
        # repository-backed feed. The downloaded feed must remain empty below.
        $PreviousReleaseUrl = $UpdateUrl
        $PreviousReleaseProvider = 'github'
    }
}

$ReleaseLock = Enter-MissionLegalReleaseLock `
    -LockPath (Join-Path $RepoRoot "build\release-locks\client-$Channel.lock")
$TransactionOutputDir = $null
try {
Repair-MissionLegalInterruptedReleaseTransaction -FinalDirectory $FinalOutputDir
$FinalFeedPath = Join-Path $FinalOutputDir "releases.$Channel.json"
$ExistingAssets = @(Get-FeedAssets -FeedPath $FinalFeedPath -AllowMissing)
foreach ($Asset in $ExistingAssets) {
    Assert-SafeFeedAsset `
        -Asset $Asset `
        -ReleaseRoot $FinalOutputDir `
        -ExpectedPackId $PackId `
        -VerifyHash:$RequireSigning `
        -RequireSha256:$RequireSigning
}
if (@($ExistingAssets | Where-Object {
    ([string]$_.PackageId).Equals($PackId, [StringComparison]::Ordinal) -and
    ([string]$_.Version).Equals($Version, [StringComparison]::OrdinalIgnoreCase)
}).Count -gt 0) {
    throw "Release $PackId $Version already exists in $FinalFeedPath. Bump APP_VERSION instead of replacing a published version."
}
if ($InitialRelease -and $ExistingAssets.Count -gt 0) {
    throw "InitialRelease requires an empty local channel; existing feed assets were found."
}
if ($RequireSigning) {
    $PublishedVersions = @($ExistingAssets | Where-Object {
        ([string]$_.PackageId).Equals($PackId, [StringComparison]::Ordinal) -and
        ([string]$_.Type) -ieq 'Full'
    } | ForEach-Object { [string]$_.Version } | Select-Object -Unique)
    Assert-MissionLegalVersionIsNewer `
        -CandidateVersion $Version `
        -ExistingVersions $PublishedVersions `
        -SourceDescription "the existing $Channel client feed"
}
$DuplicateFullPattern = '^' + [regex]::Escape($PackId) + '-' + [regex]::Escape($Version) + '(?:-' + [regex]::Escape($Channel) + ')?-full\.nupkg$'
$DuplicateFull = if (Test-Path -LiteralPath $FinalOutputDir -PathType Container) {
    Get-ChildItem -LiteralPath $FinalOutputDir -File |
        Where-Object { $_.Name -match $DuplicateFullPattern } |
        Select-Object -First 1
}
else {
    $null
}
if ($null -ne $DuplicateFull) {
    throw "Release package already exists without a matching clean feed entry: $($DuplicateFull.FullName)"
}

$TransactionOutputDir = New-MissionLegalReleaseTransaction `
    -FinalDirectory $FinalOutputDir `
    -Label "$Channel-$Version" `
    -CopyExisting
$OutputDir = $TransactionOutputDir
$FeedPath = Join-Path $OutputDir "releases.$Channel.json"

$Vpk = Resolve-Vpk `
    -RequiredVersion $RequiredVpkVersion `
    -PackageUrl $VpkPackageUrl `
    -PackageSha256 $VpkPackageSha256 `
    -TargetFramework $VpkTargetFramework

if (-not [string]::IsNullOrWhiteSpace($PreviousReleaseUrl)) {
    $Uri = $null
    if (-not [Uri]::TryCreate($PreviousReleaseUrl, [UriKind]::Absolute, [ref]$Uri)) {
        throw "PreviousReleaseUrl must be an absolute HTTPS URL: $PreviousReleaseUrl"
    }
    if (
        -not [string]::IsNullOrWhiteSpace($Uri.UserInfo) -or
        -not [string]::IsNullOrWhiteSpace($Uri.Query) -or
        -not [string]::IsNullOrWhiteSpace($Uri.Fragment)
    ) {
        throw "PreviousReleaseUrl must not embed credentials, query tokens, or fragments."
    }
    if ($PreviousReleaseProvider -eq "github") {
        if ($Uri.Scheme -ne "https" -or [string]::IsNullOrWhiteSpace($Uri.Host)) {
            throw "GitHub previous-release sources must use a public HTTPS repository URL."
        }
        $DownloadArguments = @(
            "--yes", "--skip-updates", "download", "github",
            "--repoUrl", $PreviousReleaseUrl,
            "--outputDir", $OutputDir,
            "--channel", $Channel
        )
        if ($Prerelease) {
            $DownloadArguments += @("--pre", "true")
        }
        Invoke-Vpk `
            -Executable $Vpk `
            -Arguments $DownloadArguments `
            -Operation "downloading the previous public GitHub release"
    }
    else {
        $IsLocalHttp = (
            $Uri.Scheme -eq "http" -and
            $Uri.Host -in @("localhost", "127.0.0.1")
        )
        if ($Uri.Scheme -ne "https" -and -not $IsLocalHttp) {
            throw "PreviousReleaseUrl must use HTTPS; localhost HTTP is allowed only for tests."
        }
        if ($IsLocalHttp) {
            Write-Warning "Using a localhost previous-release feed for local testing."
        }
        Invoke-Vpk `
            -Executable $Vpk `
            -Arguments @(
                "--yes", "--skip-updates", "download", "http",
                "--url", $PreviousReleaseUrl,
                "--outputDir", $OutputDir,
                "--channel", $Channel
            ) `
            -Operation "downloading the previous HTTP release"
    }
}
elseif (-not [string]::IsNullOrWhiteSpace($PreviousReleaseDirectory)) {
    $PreviousReleaseDirectory = Resolve-ExistingDirectory `
        -Path $PreviousReleaseDirectory `
        -Description "Previous release directory"
    if (
        (Test-PathInside -Candidate $PreviousReleaseDirectory -Parent $OutputDir) -or
        (Test-PathInside -Candidate $OutputDir -Parent $PreviousReleaseDirectory)
    ) {
        throw "Previous release directory must be separate from the output directory."
    }
    Invoke-Vpk `
        -Executable $Vpk `
        -Arguments @(
            "--yes", "--skip-updates", "download", "local",
            "--path", $PreviousReleaseDirectory,
            "--outputDir", $OutputDir,
            "--channel", $Channel
        ) `
        -Operation "copying the previous local release"
}

$AssetsBeforePack = @(Get-FeedAssets -FeedPath $FeedPath -AllowMissing)
foreach ($Asset in $AssetsBeforePack) {
    Assert-SafeFeedAsset `
        -Asset $Asset `
        -ReleaseRoot $OutputDir `
        -ExpectedPackId $PackId `
        -VerifyHash:$RequireSigning `
        -RequireSha256:$RequireSigning
}
if ($InitialRelease -and $AssetsBeforePack.Count -gt 0) {
    throw "InitialRelease history probe found published or local feed assets."
}
if (@($AssetsBeforePack | Where-Object {
    ([string]$_.PackageId).Equals($PackId, [StringComparison]::Ordinal) -and
    ([string]$_.Version).Equals($Version, [StringComparison]::OrdinalIgnoreCase)
}).Count -gt 0) {
    throw "Release $PackId $Version already exists after obtaining the prior feed. Bump APP_VERSION."
}
$HadPreviousFull = @($AssetsBeforePack | Where-Object {
    ([string]$_.PackageId).Equals($PackId, [StringComparison]::Ordinal) -and
    ([string]$_.Type) -ieq "Full"
}).Count -gt 0
if ($RequireSigning) {
    $PublishedVersions = @($AssetsBeforePack | Where-Object {
        ([string]$_.PackageId).Equals($PackId, [StringComparison]::Ordinal) -and
        ([string]$_.Type) -ieq 'Full'
    } | ForEach-Object { [string]$_.Version } | Select-Object -Unique)
    Assert-MissionLegalVersionIsNewer `
        -CandidateVersion $Version `
        -ExistingVersions $PublishedVersions `
        -SourceDescription 'the cloned/downloaded published client history'
}

if (-not [string]::IsNullOrWhiteSpace($ReleaseNotesPath)) {
    $ReleaseNotesPath = Resolve-ExistingFile -Path $ReleaseNotesPath -Description "Release notes"
}
if (-not [string]::IsNullOrWhiteSpace($IconPath)) {
    $IconPath = Resolve-ExistingFile -Path $IconPath -Description "Installer icon"
}
if (-not [string]::IsNullOrWhiteSpace($SplashImagePath)) {
    $SplashImagePath = Resolve-ExistingFile -Path $SplashImagePath -Description "Installer splash image"
}
if (-not [string]::IsNullOrWhiteSpace($AzureTrustedSignFile)) {
    $AzureTrustedSignFile = Resolve-ExistingFile `
        -Path $AzureTrustedSignFile `
        -Description "Azure Trusted Signing metadata"
}

$EmbeddedUpdateConfigPath = Join-Path $InputDir "mission-legal-update.json"
$HadOriginalUpdateConfig = Test-Path -LiteralPath $EmbeddedUpdateConfigPath -PathType Leaf
$OriginalUpdateConfigBytes = $null
if ($HadOriginalUpdateConfig) {
    $OriginalUpdateConfigBytes = [IO.File]::ReadAllBytes($EmbeddedUpdateConfigPath)
}
try {
    $EmbeddedUpdateConfig = Write-ClientUpdateConfig `
        -DestinationDirectory $InputDir `
        -SourceUrl $UpdateUrl `
        -Provider $UpdateProvider `
        -IncludePrereleases:$Prerelease
    Write-Host "Embedded client update source: $EmbeddedUpdateConfig"

$PackArguments = @(
    "--yes", "--skip-updates", "pack",
    "--outputDir", $OutputDir,
    "--channel", $Channel,
    "--runtime", $Runtime,
    "--packId", $PackId,
    "--packVersion", $Version,
    "--packDir", $InputDir,
    "--packAuthors", $PackAuthors,
    "--packTitle", $PackTitle,
    "--mainExe", $MainExe,
    "--shortcuts", $Shortcuts,
    "--delta", $DeltaMode,
    "--noPortable"
)
if (-not [string]::IsNullOrWhiteSpace($ReleaseNotesPath)) {
    $PackArguments += @("--releaseNotes", $ReleaseNotesPath)
}
if (-not [string]::IsNullOrWhiteSpace($IconPath)) {
    $PackArguments += @("--icon", $IconPath)
}
if (-not [string]::IsNullOrWhiteSpace($SplashImagePath)) {
    $PackArguments += @("--splashImage", $SplashImagePath)
}
if (-not [string]::IsNullOrWhiteSpace($SignParams)) {
    $PackArguments += @("--signParams", $SignParams)
}
elseif (-not [string]::IsNullOrWhiteSpace($SignTemplate)) {
    $PackArguments += @("--signTemplate", $SignTemplate)
}
elseif (-not [string]::IsNullOrWhiteSpace($AzureTrustedSignFile)) {
    $PackArguments += @("--azureTrustedSignFile", $AzureTrustedSignFile)
}
if ($HasSigning) {
    $PackArguments += @("--signParallel", [string]$SignParallel)
}
if (-not [string]::IsNullOrWhiteSpace($SignExclude)) {
    $PackArguments += @("--signExclude", $SignExclude)
}

Write-Host "Building Mission Legal client release $Version ($Channel) with vpk $RequiredVpkVersion..."
Invoke-Vpk `
    -Executable $Vpk `
    -Arguments $PackArguments `
    -Operation "packing the client release"

    $Result = Test-ReleaseArtifacts `
        -ReleaseRoot $OutputDir `
        -ReleaseChannel $Channel `
        -ReleaseVersion $Version `
        -ExpectedPackId $PackId `
        -ExpectDelta:$HadPreviousFull `
        -ExpectSignature:($HasSigning -or $RequireSigning) `
        -VerifyAllHashes:$RequireSigning `
        -RequireSha256:$RequireSigning `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -SignatureTemporaryRoot (Join-Path $RepoRoot "build\release-validation") `
        -RequireTimestamp:$RequireSigning
}
finally {
    if ($HadOriginalUpdateConfig) {
        $RestorePath = "$EmbeddedUpdateConfigPath.$PID.provenance-restore.tmp"
        try {
            [IO.File]::WriteAllBytes($RestorePath, $OriginalUpdateConfigBytes)
            Move-Item -LiteralPath $RestorePath -Destination $EmbeddedUpdateConfigPath -Force
        }
        finally {
            if (Test-Path -LiteralPath $RestorePath -PathType Leaf) {
                Remove-Item -LiteralPath $RestorePath -Force
            }
        }
    }
    else {
        Remove-Item -LiteralPath $EmbeddedUpdateConfigPath -Force -ErrorAction SilentlyContinue
    }
    Assert-ClientRawPackageProvenance
}

$ClientReleaseManifestName = "$PackId-$Version-$Channel-release.json"
$ClientReleaseManifestPath = Join-Path $OutputDir $ClientReleaseManifestName
if (Test-Path -LiteralPath $ClientReleaseManifestPath) {
    throw "Immutable client release manifest already exists: $ClientReleaseManifestPath"
}
$ClientReleaseArtifacts = [Collections.Generic.List[object]]::new()
foreach ($ReleaseArtifact in @(
    @{ Path = $Result.Setup; Kind = 'installer' },
    @{ Path = $Result.Feed; Kind = 'update_feed' },
    @{ Path = (Join-Path $OutputDir "assets.$Channel.json"); Kind = 'latest_assets' },
    @{ Path = $Result.FullPackage; Kind = 'full' }
)) {
    $ReleaseFile = Get-Item -LiteralPath $ReleaseArtifact.Path
    $ClientReleaseArtifacts.Add([ordered]@{
        kind = $ReleaseArtifact.Kind
        filename = $ReleaseFile.Name
        sha256 = (Get-FileHash -LiteralPath $ReleaseFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $ReleaseFile.Length
    }) | Out-Null
}
foreach ($DeltaPath in @($Result.DeltaPackages)) {
    $DeltaFile = Get-Item -LiteralPath $DeltaPath
    $ClientReleaseArtifacts.Add([ordered]@{
        kind = 'delta'
        filename = $DeltaFile.Name
        sha256 = (Get-FileHash -LiteralPath $DeltaFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $DeltaFile.Length
    }) | Out-Null
}
$ClientReleaseManifest = [ordered]@{
    format_version = 1
    app_version = $Version
    channel = $Channel
    pack_id = $PackId
    built_at = [DateTimeOffset]::UtcNow.ToString('o')
    production_signing_required = [bool]$RequireSigning
    expected_signer_thumbprint = if ($RequireSigning) { $ExpectedSignerThumbprint } else { $null }
    raw_package_provenance = [ordered]@{
        filename = [IO.Path]::GetFileName($ProvenanceManifestPath)
        sha256 = (Get-FileHash -LiteralPath $ProvenanceManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    signatures = @($Result.SignatureEvidence)
    artifacts = @($ClientReleaseArtifacts)
}
Write-MissionLegalJsonAtomic `
    -Value $ClientReleaseManifest `
    -Path $ClientReleaseManifestPath `
    -Depth 20 `
    -RequireAbsent | Out-Null

$CommittedOutputDir = Complete-MissionLegalReleaseTransaction `
    -TransactionDirectory $TransactionOutputDir `
    -FinalDirectory $FinalOutputDir
$TransactionOutputDir = $null
$Result = [pscustomobject]@{
    Setup = Join-Path $CommittedOutputDir ([IO.Path]::GetFileName($Result.Setup))
    Feed = Join-Path $CommittedOutputDir ([IO.Path]::GetFileName($Result.Feed))
    FullPackage = Join-Path $CommittedOutputDir ([IO.Path]::GetFileName($Result.FullPackage))
    DeltaPackages = @($Result.DeltaPackages | ForEach-Object {
        Join-Path $CommittedOutputDir ([IO.Path]::GetFileName([string]$_))
    })
    SignatureEvidence = @($Result.SignatureEvidence)
    VersionManifest = Join-Path $CommittedOutputDir $ClientReleaseManifestName
}

Write-Host "Mission Legal client release completed:"
Write-Host "  Installer: $($Result.Setup)"
Write-Host "  Feed:      $($Result.Feed)"
Write-Host "  Full:      $($Result.FullPackage)"
if ($Result.DeltaPackages.Count -gt 0) {
    Write-Host "  Delta:     $($Result.DeltaPackages -join ', ')"
}
elseif (-not $HadPreviousFull) {
    Write-Host "  Delta:     first release; no previous full package was available"
}
}
finally {
    if (
        -not [string]::IsNullOrWhiteSpace([string]$TransactionOutputDir) -and
        (Test-Path -LiteralPath $TransactionOutputDir -PathType Container)
    ) {
        Remove-Item -LiteralPath $TransactionOutputDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $ReleaseLock) {
        $ReleaseLock.Dispose()
    }
}
