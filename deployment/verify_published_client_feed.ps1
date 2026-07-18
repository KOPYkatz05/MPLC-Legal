<#
.SYNOPSIS
Read-only verification of a published Mission Legal Velopack HTTPS feed.

.DESCRIPTION
Downloads the feed, latest-assets manifest, current version packages, and Setup
into a temporary directory. It compares them with an immutable local release
summary, verifies feed SHA-256/size, and validates timestamped Authenticode
signatures on Setup and the required executables inside the full package.
No remote state is changed and redirects are rejected.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$FeedBaseUrl,
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$ReleaseSummaryPath,
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$ExpectedSignerThumbprint,
    [string]$Channel = 'stable'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ReleaseSafetyPath = Join-Path $PSScriptRoot 'release_safety.ps1'
if (-not (Test-Path -LiteralPath $ReleaseSafetyPath -PathType Leaf)) {
    throw "Release safety helpers are missing: $ReleaseSafetyPath"
}
. $ReleaseSafetyPath

$ExpectedSignerThumbprint = Get-NormalizedCertificateThumbprint $ExpectedSignerThumbprint
$ReleaseSummaryPath = (Resolve-Path -LiteralPath $ReleaseSummaryPath).Path
try {
    $Summary = Get-Content -LiteralPath $ReleaseSummaryPath -Raw | ConvertFrom-Json
}
catch {
    throw "Release summary is not valid JSON: $ReleaseSummaryPath. $($_.Exception.Message)"
}
$ExpectedVersion = [string]$Summary.app_version
ConvertTo-MissionLegalSemVer $ExpectedVersion | Out-Null
if (-not [bool]$Summary.production_signing_required) {
    throw 'Published-feed verification requires a production release summary.'
}
if (-not ([string]$Summary.expected_signer_thumbprint).Equals(
    $ExpectedSignerThumbprint,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw 'Release summary signer identity does not match ExpectedSignerThumbprint.'
}
if (-not ([string]$Summary.channel).Equals($Channel, [StringComparison]::Ordinal)) {
    throw "Release summary channel '$($Summary.channel)' does not match '$Channel'."
}

$BaseUri = $null
if (-not [Uri]::TryCreate($FeedBaseUrl, [UriKind]::Absolute, [ref]$BaseUri)) {
    throw "FeedBaseUrl must be an absolute HTTPS URL: $FeedBaseUrl"
}
if (
    $BaseUri.Scheme -ne 'https' -or
    [string]::IsNullOrWhiteSpace($BaseUri.Host) -or
    $BaseUri.Host -in @('localhost', '127.0.0.1', '::1') -or
    -not [string]::IsNullOrWhiteSpace($BaseUri.UserInfo) -or
    -not [string]::IsNullOrWhiteSpace($BaseUri.Query) -or
    -not [string]::IsNullOrWhiteSpace($BaseUri.Fragment)
) {
    throw 'FeedBaseUrl must be a non-loopback HTTPS directory URL without credentials, query, or fragment.'
}
if (-not $BaseUri.AbsoluteUri.EndsWith('/', [StringComparison]::Ordinal)) {
    $BaseUri = [Uri]::new($BaseUri.AbsoluteUri + '/')
}

function Get-SafePublishedAssetUri {
    param([Parameter(Mandatory = $true)][string]$FileName)

    if (-not (Test-MissionLegalSafeWindowsLeafName $FileName)) {
        throw "Published feed contains an unsafe file name: '$FileName'."
    }
    $Uri = [Uri]::new($BaseUri, [Uri]::EscapeDataString($FileName))
    if (
        $Uri.Scheme -ne $BaseUri.Scheme -or
        $Uri.Host -ne $BaseUri.Host -or
        $Uri.Port -ne $BaseUri.Port -or
        -not $Uri.AbsolutePath.StartsWith($BaseUri.AbsolutePath, [StringComparison]::Ordinal)
    ) {
        throw "Published asset escaped the configured feed origin: $FileName"
    }
    return $Uri
}

Add-Type -AssemblyName System.Net.Http
$Handler = [Net.Http.HttpClientHandler]::new()
$Handler.AllowAutoRedirect = $false
$Client = [Net.Http.HttpClient]::new($Handler)
$Client.DefaultRequestHeaders.UserAgent.ParseAdd('MissionLegalPublishedFeedVerifier/1')
$TemporaryRoot = Join-Path ([IO.Path]::GetTempPath()) (
    'mission-legal-published-feed-' + [Guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $TemporaryRoot | Out-Null

function Receive-PublishedFile {
    param(
        [Parameter(Mandatory = $true)][string]$FileName,
        [Parameter(Mandatory = $true)][string]$DestinationPath
    )

    $Uri = Get-SafePublishedAssetUri $FileName
    $Request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $Uri)
    $Response = $null
    try {
        $Response = $Client.SendAsync(
            $Request,
            [Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        if ($Response.StatusCode -ne [Net.HttpStatusCode]::OK) {
            throw "HTTPS GET $Uri returned $([int]$Response.StatusCode) $($Response.ReasonPhrase)."
        }
        $InputStream = $Response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $OutputStream = [IO.File]::Create($DestinationPath)
        try {
            $InputStream.CopyTo($OutputStream)
        }
        finally {
            $OutputStream.Dispose()
            $InputStream.Dispose()
        }
    }
    finally {
        if ($null -ne $Response) { $Response.Dispose() }
        $Request.Dispose()
    }
    return $DestinationPath
}

function Get-SummaryArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][string]$Kind,
        [string]$FileName
    )

    $Matches = @($Summary.artifacts | Where-Object {
        ([string]$_.role).Equals($Role, [StringComparison]::Ordinal) -and
        ([string]$_.kind).Equals($Kind, [StringComparison]::Ordinal) -and
        (
            [string]::IsNullOrWhiteSpace($FileName) -or
            ([IO.Path]::GetFileName([string]$_.path)).Equals($FileName, [StringComparison]::Ordinal)
        )
    })
    if ($Matches.Count -ne 1) {
        throw "Release summary must contain exactly one $Role/$Kind artifact '$FileName'."
    }
    return $Matches[0]
}

function Assert-DownloadedArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][int64]$ExpectedSize,
        [Parameter(Mandatory = $true)][string]$Description
    )

    if ($ExpectedSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "$Description does not provide a valid SHA-256 digest."
    }
    $File = Get-Item -LiteralPath $Path
    if ($File.Length -ne $ExpectedSize) {
        throw "$Description size mismatch. Expected $ExpectedSize, found $($File.Length)."
    }
    $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if (-not $ActualHash.Equals($ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description SHA-256 mismatch."
    }
}

try {
    $FeedName = "releases.$Channel.json"
    $AssetsName = "assets.$Channel.json"
    $FeedPath = Receive-PublishedFile $FeedName (Join-Path $TemporaryRoot $FeedName)
    $AssetsPath = Receive-PublishedFile $AssetsName (Join-Path $TemporaryRoot $AssetsName)

    $FeedSummary = Get-SummaryArtifact -Role client -Kind update_feed -FileName $FeedName
    $AssetsSummary = Get-SummaryArtifact -Role client -Kind latest_assets -FileName $AssetsName
    Assert-DownloadedArtifact $FeedPath ([string]$FeedSummary.sha256) ([int64]$FeedSummary.size) 'Published release feed'
    Assert-DownloadedArtifact $AssetsPath ([string]$AssetsSummary.sha256) ([int64]$AssetsSummary.size) 'Published latest-assets manifest'

    try {
        $Feed = Get-Content -LiteralPath $FeedPath -Raw | ConvertFrom-Json
        $LatestAssets = @(Get-Content -LiteralPath $AssetsPath -Raw | ConvertFrom-Json)
    }
    catch {
        throw "Published Velopack metadata is not valid JSON. $($_.Exception.Message)"
    }
    $ExpectedPackId = [string](@($Feed.Assets | Where-Object {
        ([string]$_.Version).Equals($ExpectedVersion, [StringComparison]::OrdinalIgnoreCase) -and
        ([string]$_.Type) -ieq 'Full'
    } | Select-Object -First 1).PackageId)
    if ([string]::IsNullOrWhiteSpace($ExpectedPackId)) {
        throw "Published feed has no full package for $ExpectedVersion."
    }
    $CurrentAssets = @($Feed.Assets | Where-Object {
        ([string]$_.PackageId).Equals($ExpectedPackId, [StringComparison]::Ordinal) -and
        ([string]$_.Version).Equals($ExpectedVersion, [StringComparison]::OrdinalIgnoreCase)
    })
    $FullAssets = @($CurrentAssets | Where-Object { ([string]$_.Type) -ieq 'Full' })
    if ($FullAssets.Count -ne 1) {
        throw "Published feed must contain exactly one full package for $ExpectedPackId $ExpectedVersion."
    }

    $DownloadedPackages = [Collections.Generic.List[object]]::new()
    foreach ($Asset in $CurrentAssets) {
        $FileName = [string]$Asset.FileName
        $PackagePath = Receive-PublishedFile $FileName (Join-Path $TemporaryRoot $FileName)
        Assert-DownloadedArtifact $PackagePath ([string]$Asset.SHA256) ([int64]$Asset.Size) "Published package $FileName"
        $SummaryPackage = Get-SummaryArtifact `
            -Role client `
            -Kind ([string]$Asset.Type).ToLowerInvariant() `
            -FileName $FileName
        Assert-DownloadedArtifact $PackagePath ([string]$SummaryPackage.sha256) ([int64]$SummaryPackage.size) "Release-summary package $FileName"
        $DownloadedPackages.Add([ordered]@{
            filename = $FileName
            type = [string]$Asset.Type
            sha256 = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
            size = (Get-Item -LiteralPath $PackagePath).Length
        }) | Out-Null
    }

    $InstallerEntries = @($LatestAssets | Where-Object { ([string]$_.Type) -ieq 'Installer' })
    if ($InstallerEntries.Count -ne 1) {
        throw 'Published latest-assets manifest must contain exactly one installer.'
    }
    $SetupName = [string]$InstallerEntries[0].RelativeFileName
    $SetupPath = Receive-PublishedFile $SetupName (Join-Path $TemporaryRoot $SetupName)
    $SetupSummary = Get-SummaryArtifact -Role client -Kind installer -FileName $SetupName
    Assert-DownloadedArtifact $SetupPath ([string]$SetupSummary.sha256) ([int64]$SetupSummary.size) 'Published client installer'
    $SetupSignature = Assert-MissionLegalAuthenticodeSignature `
        -Path $SetupPath `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -RequireTimestamp
    $InnerSignatures = @(Assert-MissionLegalClientPackageSignatures `
        -PackagePath (Join-Path $TemporaryRoot ([string]$FullAssets[0].FileName)) `
        -TemporaryRoot $TemporaryRoot `
        -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
        -RequireTimestamp)

    [ordered]@{
        status = 'ok'
        feed_url = $BaseUri.AbsoluteUri
        channel = $Channel
        app_version = $ExpectedVersion
        signer_thumbprint = $ExpectedSignerThumbprint
        setup_signature = $SetupSignature
        inner_signatures = $InnerSignatures
        packages = @($DownloadedPackages)
        remote_mutations_performed = $false
    } | ConvertTo-Json -Depth 10
}
finally {
    $Client.Dispose()
    $Handler.Dispose()
    if (Test-Path -LiteralPath $TemporaryRoot -PathType Container) {
        Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
