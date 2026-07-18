<#
Runs fast, non-installing contract checks for test_installed_client_update.ps1.
All generated fixtures stay below the repository's ignored build tree.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = [IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
)
$BuildRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "build\tests"))
$BuildPrefix = $BuildRoot.TrimEnd("\/".ToCharArray()) + [IO.Path]::DirectorySeparatorChar
$TestRoot = Join-Path $BuildRoot ("installed-update-harness-" + [Guid]::NewGuid().ToString("N"))
if (-not $TestRoot.StartsWith($BuildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Test fixture escaped the repository build directory: $TestRoot"
}

New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
try {
    $Harness = Join-Path $PSScriptRoot "test_installed_client_update.ps1"
    $Installer = Join-Path $TestRoot "MissionLegal-1.0.0-Setup.exe"
    $FeedDirectory = Join-Path $TestRoot "feed"
    New-Item -ItemType Directory -Force -Path $FeedDirectory | Out-Null
    Set-Content -LiteralPath $Installer -Value "fixture installer" -NoNewline

    $FullName = "MissionLegal.MissionLegalTracker-1.0.1-stable-full.nupkg"
    $DeltaName = "MissionLegal.MissionLegalTracker-1.0.1-stable-delta.nupkg"
    $FullPath = Join-Path $FeedDirectory $FullName
    $DeltaPath = Join-Path $FeedDirectory $DeltaName
    Set-Content -LiteralPath $FullPath -Value "fixture full" -NoNewline
    Set-Content -LiteralPath $DeltaPath -Value "fixture delta" -NoNewline
    $Full = Get-Item -LiteralPath $FullPath
    $Delta = Get-Item -LiteralPath $DeltaPath
    $Feed = @{
        Assets = @(
            @{
                PackageId = "MissionLegal.MissionLegalTracker"
                Version = "1.0.1"
                Type = "Full"
                FileName = $FullName
                SHA256 = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA256).Hash
                Size = $Full.Length
            },
            @{
                PackageId = "MissionLegal.MissionLegalTracker"
                Version = "1.0.1"
                Type = "Delta"
                FileName = $DeltaName
                SHA256 = (Get-FileHash -LiteralPath $DeltaPath -Algorithm SHA256).Hash
                Size = $Delta.Length
            },
            @{
                PackageId = "MissionLegal.MissionLegalTracker"
                Version = "1.0.0"
                Type = "Full"
                FileName = "unused-baseline-full.nupkg"
                SHA256 = ("0" * 64)
                Size = 1
            }
        )
    }
    $FeedPath = Join-Path $FeedDirectory "releases.stable.json"
    $Feed | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $FeedPath

    & $Harness `
        -BaselineInstaller $Installer `
        -FeedDirectory $FeedDirectory `
        -BaselineVersion "1.0.0" `
        -ExpectedVersion "1.0.1" `
        -ValidateOnly

    $RejectedNonUpgrade = $false
    try {
        & $Harness `
            -BaselineInstaller $Installer `
            -FeedDirectory $FeedDirectory `
            -BaselineVersion "1.0.1" `
            -ExpectedVersion "1.0.1" `
            -ValidateOnly
    }
    catch {
        if ($_.Exception.Message -notmatch "must be older") {
            throw
        }
        $RejectedNonUpgrade = $true
    }
    if (-not $RejectedNonUpgrade) {
        throw "Harness did not reject a non-upgrade baseline."
    }

    $OutsideInstaller = Join-Path $env:WINDIR "System32\notepad.exe"
    $RejectedOutsideArtifact = $false
    try {
        & $Harness `
            -BaselineInstaller $OutsideInstaller `
            -FeedDirectory $FeedDirectory `
            -BaselineVersion "1.0.0" `
            -ExpectedVersion "1.0.1" `
            -ValidateOnly
    }
    catch {
        if ($_.Exception.Message -notmatch "must stay inside the repository") {
            throw
        }
        $RejectedOutsideArtifact = $true
    }
    if (-not $RejectedOutsideArtifact) {
        throw "Harness did not reject an artifact outside the repository."
    }

    $UnsafeFeed = Get-Content -LiteralPath $FeedPath -Raw | ConvertFrom-Json
    $UnsafeFeed.Assets[0].FileName = "..\escaped.nupkg"
    $UnsafeFeed | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $FeedPath
    $RejectedTraversal = $false
    try {
        & $Harness `
            -BaselineInstaller $Installer `
            -FeedDirectory $FeedDirectory `
            -BaselineVersion "1.0.0" `
            -ExpectedVersion "1.0.1" `
            -ValidateOnly
    }
    catch {
        if ($_.Exception.Message -notmatch "unsafe target asset") {
            throw
        }
        $RejectedTraversal = $true
    }
    if (-not $RejectedTraversal) {
        throw "Harness did not reject feed path traversal."
    }

    Write-Host "Installed client update harness contract test passed."
}
finally {
    $ResolvedTestRoot = [IO.Path]::GetFullPath($TestRoot)
    if ($ResolvedTestRoot.StartsWith($BuildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $ResolvedTestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
