<#
Runs a small, offline contract test for build_client_release.ps1 using a fake
vpk executable. All fixtures stay under the repository's ignored build tree.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$BuildRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "build\tests"))
$TestRoot = Join-Path $BuildRoot ("client-release-" + [Guid]::NewGuid().ToString("N"))
$BuildPrefix = $BuildRoot.TrimEnd('\') + '\'
if (-not $TestRoot.StartsWith($BuildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Test fixture escaped the repository build directory: $TestRoot"
}

New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
try {
    $InputDir = Join-Path $TestRoot "input"
    $OutputDir = Join-Path $TestRoot "releases"
    New-Item -ItemType Directory -Force -Path $InputDir | Out-Null
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    Set-Content -LiteralPath (Join-Path $InputDir "MissionLegal.exe") -Value "fixture exe" -NoNewline
    Set-Content -LiteralPath (Join-Path $InputDir "MissionLegalUpdateWorker.exe") -Value "fixture worker" -NoNewline

    $FakeVpkScript = Join-Path $TestRoot "fake-vpk.ps1"
    $FakeVpkCommand = Join-Path $TestRoot "fake-vpk.cmd"
    $FakeVpkBody = @'
$ErrorActionPreference = "Stop"
$CliArgs = @($args)
if ($CliArgs.Count -eq 1 -and $CliArgs[0] -eq "-H") {
    Write-Output "Velopack CLI 1.2.0, for distributing applications."
    exit 0
}

function Get-ArgumentValue([string]$Name) {
    $Index = [Array]::IndexOf($CliArgs, $Name)
    if ($Index -lt 0 -or $Index + 1 -ge $CliArgs.Count) {
        throw "Missing fake-vpk argument: $Name"
    }
    return $CliArgs[$Index + 1]
}

if ($CliArgs -contains "download") {
    if ($CliArgs -contains "github") {
        if ($CliArgs -notcontains "--repoUrl" -or $CliArgs -contains "--url") {
            throw "Fixture expected a GitHub previous release to use --repoUrl."
        }
        if ((Get-ArgumentValue "--repoUrl") -ne "https://github.com/example/mission-legal-releases") {
            throw "Fixture received the wrong GitHub repository URL."
        }
        exit 0
    }
    throw "Fixture did not expect a non-GitHub download command."
}

if ($CliArgs -notcontains "pack") {
    throw "Fixture expected the pack command."
}
foreach ($Required in @("--noPortable", "--packId", "--packVersion", "--packDir", "--mainExe", "--channel")) {
    if ($CliArgs -notcontains $Required) {
        throw "Fixture invocation omitted $Required"
    }
}

$OutputDir = Get-ArgumentValue "--outputDir"
$PackId = Get-ArgumentValue "--packId"
$Version = Get-ArgumentValue "--packVersion"
$Channel = Get-ArgumentValue "--channel"
$MainExe = Get-ArgumentValue "--mainExe"
if ($PackId -ne "MissionLegal.MissionLegalTracker" -or $MainExe -ne "MissionLegal.exe" -or $Channel -ne "stable") {
    throw "Stable release identity changed."
}

$FullName = "$PackId-$Version-$Channel-full.nupkg"
$FullPath = Join-Path $OutputDir $FullName
$SetupName = "$PackId-$Channel-Setup.exe"
$SetupPath = Join-Path $OutputDir $SetupName
Set-Content -LiteralPath $FullPath -Value "fixture package" -NoNewline
Set-Content -LiteralPath $SetupPath -Value "fixture setup" -NoNewline
$Full = Get-Item -LiteralPath $FullPath
$Hash = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA1).Hash
$Hash256 = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA256).Hash
$FeedPath = Join-Path $OutputDir "releases.$Channel.json"
$Assets = @()
if (Test-Path -LiteralPath $FeedPath -PathType Leaf) {
    $ExistingFeed = Get-Content -LiteralPath $FeedPath -Raw | ConvertFrom-Json
    $Assets += @($ExistingFeed.Assets)
}
$HasPreviousFull = @($Assets | Where-Object { $_.PackageId -eq $PackId -and $_.Type -eq "Full" }).Count -gt 0
$Assets += @{
    PackageId = $PackId
    Version = $Version
    Type = "Full"
    FileName = $FullName
    SHA1 = $Hash
    SHA256 = $Hash256
    Size = $Full.Length
}
if ($HasPreviousFull) {
    $DeltaName = "$PackId-$Version-$Channel-delta.nupkg"
    $DeltaPath = Join-Path $OutputDir $DeltaName
    Set-Content -LiteralPath $DeltaPath -Value "fixture delta" -NoNewline
    $Delta = Get-Item -LiteralPath $DeltaPath
    $DeltaHash = (Get-FileHash -LiteralPath $DeltaPath -Algorithm SHA1).Hash
    $DeltaHash256 = (Get-FileHash -LiteralPath $DeltaPath -Algorithm SHA256).Hash
    $Assets += @{
        PackageId = $PackId
        Version = $Version
        Type = "Delta"
        FileName = $DeltaName
        SHA1 = $DeltaHash
        SHA256 = $DeltaHash256
        Size = $Delta.Length
    }
}
$Feed = @{
    Assets = @($Assets)
}
$Feed | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $FeedPath
$LatestAssets = @(
    @{ RelativeFileName = $SetupName; Type = "Installer" },
    @{ RelativeFileName = $FullName; Type = "Full" }
)
if ($HasPreviousFull) {
    $LatestAssets += @{ RelativeFileName = $DeltaName; Type = "Delta" }
}
$LatestAssets | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDir "assets.$Channel.json")
exit 0
'@
    Set-Content -LiteralPath $FakeVpkScript -Value $FakeVpkBody -Encoding UTF8
    Set-Content `
        -LiteralPath $FakeVpkCommand `
        -Value "@powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$FakeVpkScript`" %*`r`n@exit /b %ERRORLEVEL%" `
        -Encoding ASCII

    $ReleaseScript = Join-Path $RepoRoot "deployment\build_client_release.ps1"
    & $ReleaseScript `
        -Version "9.8.7" `
        -InputDir $InputDir `
        -OutputDir $OutputDir `
        -VpkPath $FakeVpkCommand `
        -UpdateUrl "https://updates.example.test/mission-legal/client/"

    $EmbeddedConfigPath = Join-Path $InputDir "mission-legal-update.json"
    $EmbeddedConfig = Get-Content -LiteralPath $EmbeddedConfigPath -Raw | ConvertFrom-Json
    if ($EmbeddedConfig.url -ne "https://updates.example.test/mission-legal/client/" -or $EmbeddedConfig.provider -ne "http" -or $EmbeddedConfig.prerelease) {
        throw "Embedded update source configuration is incorrect."
    }
    $ConfigBytes = [IO.File]::ReadAllBytes($EmbeddedConfigPath)
    if ($ConfigBytes.Length -ge 3 -and $ConfigBytes[0] -eq 0xEF -and $ConfigBytes[1] -eq 0xBB -and $ConfigBytes[2] -eq 0xBF) {
        throw "Embedded update source configuration must be UTF-8 without a BOM."
    }

    $RejectedInsecurePreviousFeed = $false
    try {
        & $ReleaseScript `
            -Version "9.8.9" `
            -InputDir $InputDir `
            -OutputDir (Join-Path $TestRoot "insecure-previous-feed") `
            -VpkPath $FakeVpkCommand `
            -UpdateUrl "https://updates.example.test/mission-legal/client/" `
            -PreviousReleaseUrl "http://updates.example.test/mission-legal/client/"
    }
    catch {
        if ($_.Exception.Message -notmatch "must use HTTPS") {
            throw
        }
        $RejectedInsecurePreviousFeed = $true
    }
    if (-not $RejectedInsecurePreviousFeed) {
        throw "An insecure remote previous-release feed was not rejected."
    }

    $RejectedSignedLocalFeed = $false
    try {
        & $ReleaseScript `
            -Version "9.8.5" `
            -InputDir $InputDir `
            -OutputDir (Join-Path $TestRoot "signed-local-feed") `
            -VpkPath $FakeVpkCommand `
            -UpdateUrl "http://127.0.0.1:49173/" `
            -SignParams "fixture-signing-command" `
            -RequireSigning
    }
    catch {
        if ($_.Exception.Message -notmatch "non-loopback HTTPS") {
            throw
        }
        $RejectedSignedLocalFeed = $true
    }
    if (-not $RejectedSignedLocalFeed) {
        throw "A signed release accepted a loopback-only update source."
    }

    & $ReleaseScript `
        -Version "9.8.6" `
        -InputDir $InputDir `
        -OutputDir (Join-Path $TestRoot "github-release") `
        -VpkPath $FakeVpkCommand `
        -UpdateUrl "https://github.com/example/mission-legal-releases" `
        -UpdateProvider "github" `
        -PreviousReleaseUrl "https://github.com/example/mission-legal-releases"
    $GitHubEmbeddedConfig = Get-Content `
        -LiteralPath (Join-Path $InputDir "mission-legal-update.json") `
        -Raw | ConvertFrom-Json
    if ($GitHubEmbeddedConfig.provider -ne "github") {
        throw "GitHub update provider was not embedded in the client package."
    }

    & $ReleaseScript `
        -Version "9.8.7" `
        -OutputDir $OutputDir `
        -ValidateOnly

    & $ReleaseScript `
        -Version "9.8.8" `
        -InputDir $InputDir `
        -OutputDir $OutputDir `
        -VpkPath $FakeVpkCommand `
        -UpdateUrl "https://updates.example.test/mission-legal/client/"

    & $ReleaseScript `
        -Version "9.8.8" `
        -OutputDir $OutputDir `
        -ValidateOnly

    $RejectedVersionReplacement = $false
    try {
        & $ReleaseScript `
            -Version "9.8.8" `
            -InputDir $InputDir `
            -OutputDir $OutputDir `
            -VpkPath $FakeVpkCommand `
            -UpdateUrl "https://updates.example.test/mission-legal/client/"
    }
    catch {
        if ($_.Exception.Message -notmatch "already exists") {
            throw
        }
        $RejectedVersionReplacement = $true
    }
    if (-not $RejectedVersionReplacement) {
        throw "Replacing an existing release version was not rejected."
    }

    $FeedPath = Join-Path $OutputDir "releases.stable.json"
    $Feed = Get-Content -LiteralPath $FeedPath -Raw | ConvertFrom-Json
    $Feed.Assets[0].FileName = "..\escaped.nupkg"
    $Feed | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $FeedPath

    $RejectedUnsafeFeed = $false
    try {
        & $ReleaseScript `
            -Version "9.8.7" `
            -OutputDir $OutputDir `
            -ValidateOnly
    }
    catch {
        if ($_.Exception.Message -notmatch "unsafe asset file name") {
            throw
        }
        $RejectedUnsafeFeed = $true
    }
    if (-not $RejectedUnsafeFeed) {
        throw "Unsafe feed asset path was not rejected."
    }

    Write-Host "Client release packaging fixture test passed."
}
finally {
    $ResolvedTestRoot = [IO.Path]::GetFullPath($TestRoot)
    if ($ResolvedTestRoot.StartsWith($BuildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $ResolvedTestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
