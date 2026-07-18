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
    $PythonPath = Join-Path $RepoRoot "venv\Scripts\python.exe"
    $ProvenanceHelper = Join-Path $RepoRoot "deployment\package_provenance.py"
    $ProvenanceManifestPath = "$InputDir.provenance.json"
    $DependencyLock = Join-Path $RepoRoot "requirements_lock.txt"
    $BuildDependencyLock = Join-Path $RepoRoot "requirements_build.txt"
    $OcrSourceRoot = Join-Path $TestRoot "ocr-source"
    New-Item -ItemType Directory -Force -Path $InputDir | Out-Null
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Fixture Python executable is missing: $PythonPath"
    }

    $VersionPayloadText = (& $PythonPath -B -c "import json,sys; sys.path.insert(0,sys.argv[1]); from version import API_VERSION, SCHEMA_VERSION; print(json.dumps({'api_version':API_VERSION,'schema_version':SCHEMA_VERSION}))" $RepoRoot).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $VersionPayloadText) {
        throw "Could not read fixture API/schema versions from version.py."
    }
    $VersionPayload = $VersionPayloadText | ConvertFrom-Json
    $ConfiguredApiVersion = [string]$VersionPayload.api_version
    $ConfiguredSchemaVersion = [int]$VersionPayload.schema_version

    $OcrFixtures = @(
        @{ Source = "det\en\en_PP-OCRv3_det_infer"; Destination = "det"; Value = "fixture det model" },
        @{ Source = "rec\en\en_PP-OCRv4_rec_infer"; Destination = "rec"; Value = "fixture rec model" },
        @{ Source = "cls\ch_ppocr_mobile_v2.0_cls_infer"; Destination = "cls"; Value = "fixture cls model" }
    )
    foreach ($Model in $OcrFixtures) {
        $SourceDir = Join-Path $OcrSourceRoot $Model.Source
        $DestinationDir = Join-Path $InputDir ("_internal\ocr_models\" + $Model.Destination)
        New-Item -ItemType Directory -Force -Path $SourceDir | Out-Null
        New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
        Set-Content -LiteralPath (Join-Path $SourceDir "inference.pdmodel") -Value $Model.Value -NoNewline
        Set-Content -LiteralPath (Join-Path $DestinationDir "inference.pdmodel") -Value $Model.Value -NoNewline
    }

    function Write-FixtureExecutables([string]$Version) {
        if ($Version -notmatch '^\d+\.\d+\.\d+$') {
            throw "Fixture executable version must have three numeric components: $Version"
        }
        $Token = $Version.Replace(".", "")
        $AssemblyVersion = "$Version.0"
        $CompiledExe = Join-Path $TestRoot "fixture-$Token.exe"
        if (Test-Path -LiteralPath $CompiledExe) {
            Remove-Item -LiteralPath $CompiledExe -Force
        }
        $Source = @"
using System;
using System.Reflection;
[assembly: AssemblyVersion("$AssemblyVersion")]
[assembly: AssemblyFileVersion("$AssemblyVersion")]
[assembly: AssemblyInformationalVersion("$Version")]
public class MissionLegalFixture$Token { public static void Main() {} }
"@
        Add-Type `
            -TypeDefinition $Source `
            -Language CSharp `
            -OutputAssembly $CompiledExe `
            -OutputType ConsoleApplication
        foreach ($Name in @(
            "MissionLegal.exe",
            "MissionLegalDiagnostics.exe",
            "MissionLegalClientSetup.exe",
            "MissionLegalUpdateWorker.exe"
        )) {
            Copy-Item -LiteralPath $CompiledExe -Destination (Join-Path $InputDir $Name) -Force
        }
    }

    function Write-FixtureProvenance([string]$Version) {
        $SmokeResultPath = Join-Path $TestRoot "smoke-$($Version.Replace('.', '-')).jsonl"
        $SmokeResult = [ordered]@{
            api_version = $ConfiguredApiVersion
            app_version = $Version
            frozen = $true
            imports = @()
            role = "client"
            schema_version = $ConfiguredSchemaVersion
            status = "ok"
        }
        $SmokeResult | ConvertTo-Json -Compress | Set-Content -LiteralPath $SmokeResultPath -Encoding UTF8
        & $PythonPath -B $ProvenanceHelper `
            create `
            --repo-root $RepoRoot `
            --package-dir $InputDir `
            --manifest-path $ProvenanceManifestPath `
            --role client `
            --app-version $Version `
            --api-version $ConfiguredApiVersion `
            --schema-version ([string]$ConfiguredSchemaVersion) `
            --smoke-result $SmokeResultPath `
            --dependency-lock $DependencyLock `
            --dependency-lock $BuildDependencyLock `
            --ocr-model-root $OcrSourceRoot `
            --windows-version-exe MissionLegal.exe `
            --windows-version-exe MissionLegalDiagnostics.exe `
            --windows-version-exe MissionLegalClientSetup.exe `
            --windows-version-exe MissionLegalUpdateWorker.exe
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create fixture package provenance for $Version."
        }
    }

    $InitialVersion = "9.8.7"
    $NextVersion = "9.8.8"
    Write-FixtureExecutables -Version $InitialVersion
    Write-FixtureProvenance -Version $InitialVersion

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
$PackDir = Get-ArgumentValue "--packDir"
$PackId = Get-ArgumentValue "--packId"
$Version = Get-ArgumentValue "--packVersion"
$Channel = Get-ArgumentValue "--channel"
$MainExe = Get-ArgumentValue "--mainExe"
if ($PackId -ne "MissionLegal.MissionLegalTracker" -or $MainExe -ne "MissionLegal.exe" -or $Channel -ne "stable") {
    throw "Stable release identity changed."
}
$UpdateConfigPath = Join-Path $PackDir "mission-legal-update.json"
if (-not (Test-Path -LiteralPath $UpdateConfigPath -PathType Leaf)) {
    throw "Fixture pack directory did not contain the controlled update configuration."
}
Copy-Item `
    -LiteralPath $UpdateConfigPath `
    -Destination (Join-Path $OutputDir "captured-update-$Version.json") `
    -Force

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
if ($env:MISSION_LEGAL_TEST_FAIL_AFTER_WRITE -eq "1") {
    Set-Content -LiteralPath $FeedPath -Value '{intentional-invalid-json' -NoNewline
}
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

    $RejectedStaleVersion = $false
    try {
        & $ReleaseScript `
            -Version $NextVersion `
            -InputDir $InputDir `
            -OutputDir (Join-Path $TestRoot "stale-version") `
            -VpkPath $FakeVpkCommand `
            -UpdateUrl "https://updates.example.test/mission-legal/client/"
    }
    catch {
        if ($_.Exception.Message -notmatch "raw package.*provenance") {
            throw
        }
        $RejectedStaleVersion = $true
    }
    if (-not $RejectedStaleVersion) {
        throw "A raw client package was relabeled with a stale release version."
    }

    Add-Content -LiteralPath (Join-Path $InputDir "MissionLegal.exe") -Value "tampered"
    $RejectedTamperedPackage = $false
    try {
        & $ReleaseScript `
            -Version $InitialVersion `
            -InputDir $InputDir `
            -OutputDir (Join-Path $TestRoot "tampered-package") `
            -VpkPath $FakeVpkCommand `
            -UpdateUrl "https://updates.example.test/mission-legal/client/"
    }
    catch {
        if ($_.Exception.Message -notmatch "raw package.*provenance") {
            throw
        }
        $RejectedTamperedPackage = $true
    }
    if (-not $RejectedTamperedPackage) {
        throw "A modified raw client package was accepted."
    }
    Copy-Item `
        -LiteralPath (Join-Path $InputDir "MissionLegalUpdateWorker.exe") `
        -Destination (Join-Path $InputDir "MissionLegal.exe") `
        -Force

    $ForbiddenFixtures = @(
        @{ Name = "api-device.json"; Value = "fixture client device pointer" },
        @{ Name = "pairing-transaction.json"; Value = "fixture pairing journal" },
        @{ Name = "workspaces.json"; Value = "fixture user workspace state" },
        @{ Name = "mission-legal-ca-key.pem"; Value = "fixture key filename" },
        @{ Name = "certificate.pem"; Value = "-----BEGIN PRIVATE KEY-----`nfixture`n-----END PRIVATE KEY-----" },
        @{ Name = "app.db-wal"; Value = "fixture sqlite sidecar" }
    )
    foreach ($ForbiddenFixture in $ForbiddenFixtures) {
        $ForbiddenPath = Join-Path $InputDir $ForbiddenFixture.Name
        Set-Content -LiteralPath $ForbiddenPath -Value $ForbiddenFixture.Value -NoNewline
        Write-FixtureProvenance -Version $InitialVersion
        $RejectedForbiddenState = $false
        try {
            & $ReleaseScript `
                -Version $InitialVersion `
                -InputDir $InputDir `
                -OutputDir (Join-Path $TestRoot ("forbidden-" + $ForbiddenFixture.Name.Replace(".", "-"))) `
                -VpkPath $FakeVpkCommand `
                -UpdateUrl "https://updates.example.test/mission-legal/client/"
        }
        catch {
            if ($_.Exception.Message -notmatch "forbidden persistent/private files") {
                throw
            }
            $RejectedForbiddenState = $true
        }
        if (-not $RejectedForbiddenState) {
            throw "Forbidden client fixture was accepted: $($ForbiddenFixture.Name)"
        }
        Remove-Item -LiteralPath $ForbiddenPath -Force
        Write-FixtureProvenance -Version $InitialVersion
    }

    $DirtyMarker = Join-Path $RepoRoot (".provenance-dirty-fixture-" + [Guid]::NewGuid().ToString("N") + ".untracked")
    try {
        Set-Content -LiteralPath $DirtyMarker -Value "fixture dirty source" -NoNewline
        Write-FixtureProvenance -Version $InitialVersion
        $DirtyManifest = Get-Content -LiteralPath $ProvenanceManifestPath -Raw | ConvertFrom-Json
        if (-not [bool]$DirtyManifest.source.git_dirty) {
            throw "Fixture could not create dirty Git provenance."
        }
        $RejectedDirtyProduction = $false
        try {
            & $ReleaseScript `
                -Version $InitialVersion `
                -InputDir $InputDir `
                -OutputDir (Join-Path $TestRoot "dirty-production") `
                -VpkPath $FakeVpkCommand `
                -UpdateUrl "https://updates.example.test/mission-legal/client/" `
                -SignParams "fixture-signing-command" `
                -ExpectedSignerThumbprint "0000000000000000000000000000000000000000" `
                -RequireSigning
        }
        catch {
            if ($_.Exception.Message -notmatch "clean Git commit") {
                throw
            }
            $RejectedDirtyProduction = $true
        }
        if (-not $RejectedDirtyProduction) {
            throw "A signed production release accepted dirty source provenance."
        }
    }
    finally {
        Remove-Item -LiteralPath $DirtyMarker -Force -ErrorAction SilentlyContinue
        Write-FixtureProvenance -Version $InitialVersion
    }

    $ExistingSentinel = Join-Path $OutputDir "existing-release-sentinel.txt"
    Set-Content -LiteralPath $ExistingSentinel -Value "unchanged" -NoNewline
    $env:MISSION_LEGAL_TEST_FAIL_AFTER_WRITE = "1"
    try {
        $RejectedPartialTransaction = $false
        try {
            & $ReleaseScript `
                -Version $InitialVersion `
                -InputDir $InputDir `
                -OutputDir $OutputDir `
                -VpkPath $FakeVpkCommand `
                -UpdateUrl "https://updates.example.test/mission-legal/client/"
        }
        catch {
            $RejectedPartialTransaction = $true
        }
        if (-not $RejectedPartialTransaction) {
            throw "Intentional staged build failure unexpectedly succeeded."
        }
    }
    finally {
        Remove-Item Env:MISSION_LEGAL_TEST_FAIL_AFTER_WRITE -ErrorAction SilentlyContinue
    }
    if ((Get-Content -LiteralPath $ExistingSentinel -Raw) -ne "unchanged") {
        throw "A failed release transaction changed the existing output directory."
    }
    if (Test-Path -LiteralPath (Join-Path $OutputDir "MissionLegal.MissionLegalTracker-9.8.7-stable-full.nupkg")) {
        throw "A failed release transaction leaked a partial package into the final output."
    }

    & $ReleaseScript `
        -Version $InitialVersion `
        -InputDir $InputDir `
        -OutputDir $OutputDir `
        -VpkPath $FakeVpkCommand `
        -UpdateUrl "https://updates.example.test/mission-legal/client/"

    $CapturedConfigPath = Join-Path $OutputDir "captured-update-$InitialVersion.json"
    $EmbeddedConfig = Get-Content -LiteralPath $CapturedConfigPath -Raw | ConvertFrom-Json
    if ($EmbeddedConfig.url -ne "https://updates.example.test/mission-legal/client/" -or $EmbeddedConfig.provider -ne "http" -or $EmbeddedConfig.prerelease) {
        throw "Embedded update source configuration is incorrect."
    }
    $ConfigBytes = [IO.File]::ReadAllBytes($CapturedConfigPath)
    if ($ConfigBytes.Length -ge 3 -and $ConfigBytes[0] -eq 0xEF -and $ConfigBytes[1] -eq 0xBB -and $ConfigBytes[2] -eq 0xBF) {
        throw "Embedded update source configuration must be UTF-8 without a BOM."
    }
    if (Test-Path -LiteralPath (Join-Path $InputDir "mission-legal-update.json")) {
        throw "The release-specific update configuration was not removed from the verified raw package."
    }

    $RejectedInsecurePreviousFeed = $false
    try {
        & $ReleaseScript `
            -Version $InitialVersion `
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

    & $ReleaseScript `
        -Version $InitialVersion `
        -InputDir $InputDir `
        -OutputDir (Join-Path $TestRoot "github-release") `
        -VpkPath $FakeVpkCommand `
        -UpdateUrl "https://github.com/example/mission-legal-releases" `
        -UpdateProvider "github" `
        -PreviousReleaseUrl "https://github.com/example/mission-legal-releases"
    $GitHubEmbeddedConfig = Get-Content `
        -LiteralPath (Join-Path (Join-Path $TestRoot "github-release") "captured-update-$InitialVersion.json") `
        -Raw | ConvertFrom-Json
    if ($GitHubEmbeddedConfig.provider -ne "github") {
        throw "GitHub update provider was not embedded in the client package."
    }

    & $ReleaseScript `
        -Version $InitialVersion `
        -OutputDir $OutputDir `
        -ValidateOnly

    Write-FixtureExecutables -Version $NextVersion
    Write-FixtureProvenance -Version $NextVersion
    & $ReleaseScript `
        -Version $NextVersion `
        -InputDir $InputDir `
        -OutputDir $OutputDir `
        -VpkPath $FakeVpkCommand `
        -UpdateUrl "https://updates.example.test/mission-legal/client/"

    & $ReleaseScript `
        -Version $NextVersion `
        -OutputDir $OutputDir `
        -ValidateOnly

    $RejectedVersionReplacement = $false
    try {
        & $ReleaseScript `
            -Version $NextVersion `
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
            -Version $InitialVersion `
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

    $Feed.Assets[0].FileName = "package.nupkg:alternate-stream"
    $Feed | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $FeedPath
    $RejectedAdsFeedName = $false
    try {
        & $ReleaseScript `
            -Version $InitialVersion `
            -OutputDir $OutputDir `
            -ValidateOnly
    }
    catch {
        if ($_.Exception.Message -notmatch "unsafe asset file name") {
            throw
        }
        $RejectedAdsFeedName = $true
    }
    if (-not $RejectedAdsFeedName) {
        throw "An NTFS alternate-data-stream feed filename was not rejected."
    }

    Write-Host "Client release packaging fixture test passed."
}
finally {
    $ResolvedTestRoot = [IO.Path]::GetFullPath($TestRoot)
    if ($ResolvedTestRoot.StartsWith($BuildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $ResolvedTestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
