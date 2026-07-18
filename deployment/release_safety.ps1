Set-StrictMode -Version Latest

function ConvertTo-MissionLegalSemVer {
    param([Parameter(Mandatory = $true)][string]$Version)

    $Pattern = '^(?<major>0|[1-9][0-9]*)\.(?<minor>0|[1-9][0-9]*)\.(?<patch>0|[1-9][0-9]*)(?:-(?<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
    $Match = [regex]::Match($Version, $Pattern)
    if (-not $Match.Success) {
        throw "Release version must be SemVer 2 with three numeric parts: $Version"
    }
    $PrereleaseIdentifiers = if ($Match.Groups['pre'].Success) {
        @($Match.Groups['pre'].Value.Split('.'))
    }
    else {
        @()
    }
    foreach ($Identifier in $PrereleaseIdentifiers) {
        if ($Identifier -match '^[0-9]+$' -and $Identifier.Length -gt 1 -and $Identifier.StartsWith('0')) {
            throw "Numeric SemVer prerelease identifiers must not contain leading zeroes: $Version"
        }
    }
    return [pscustomobject]@{
        Text = $Version
        Major = [uint64]$Match.Groups['major'].Value
        Minor = [uint64]$Match.Groups['minor'].Value
        Patch = [uint64]$Match.Groups['patch'].Value
        Prerelease = $PrereleaseIdentifiers
    }
}

function Compare-MissionLegalSemVer {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $LeftVersion = ConvertTo-MissionLegalSemVer $Left
    $RightVersion = ConvertTo-MissionLegalSemVer $Right
    foreach ($Part in @('Major', 'Minor', 'Patch')) {
        if ($LeftVersion.$Part -lt $RightVersion.$Part) { return -1 }
        if ($LeftVersion.$Part -gt $RightVersion.$Part) { return 1 }
    }

    $LeftPre = @($LeftVersion.Prerelease)
    $RightPre = @($RightVersion.Prerelease)
    if ($LeftPre.Count -eq 0 -and $RightPre.Count -eq 0) { return 0 }
    if ($LeftPre.Count -eq 0) { return 1 }
    if ($RightPre.Count -eq 0) { return -1 }

    $Count = [Math]::Max($LeftPre.Count, $RightPre.Count)
    for ($Index = 0; $Index -lt $Count; $Index++) {
        if ($Index -ge $LeftPre.Count) { return -1 }
        if ($Index -ge $RightPre.Count) { return 1 }
        $LeftIdentifier = [string]$LeftPre[$Index]
        $RightIdentifier = [string]$RightPre[$Index]
        $LeftNumeric = $LeftIdentifier -match '^(0|[1-9][0-9]*)$'
        $RightNumeric = $RightIdentifier -match '^(0|[1-9][0-9]*)$'
        if ($LeftNumeric -and $RightNumeric) {
            $LeftNumber = [System.Numerics.BigInteger]::Parse($LeftIdentifier)
            $RightNumber = [System.Numerics.BigInteger]::Parse($RightIdentifier)
            if ($LeftNumber -lt $RightNumber) { return -1 }
            if ($LeftNumber -gt $RightNumber) { return 1 }
            continue
        }
        if ($LeftNumeric -and -not $RightNumeric) { return -1 }
        if (-not $LeftNumeric -and $RightNumeric) { return 1 }
        $Comparison = [string]::CompareOrdinal($LeftIdentifier, $RightIdentifier)
        if ($Comparison -lt 0) { return -1 }
        if ($Comparison -gt 0) { return 1 }
    }
    return 0
}

function Assert-MissionLegalVersionIsNewer {
    param(
        [Parameter(Mandatory = $true)][string]$CandidateVersion,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$ExistingVersions,
        [Parameter(Mandatory = $true)][string]$SourceDescription
    )

    ConvertTo-MissionLegalSemVer $CandidateVersion | Out-Null
    $Highest = $null
    foreach ($ExistingVersion in @($ExistingVersions)) {
        if ([string]::IsNullOrWhiteSpace($ExistingVersion)) { continue }
        ConvertTo-MissionLegalSemVer $ExistingVersion | Out-Null
        if ($null -eq $Highest -or (Compare-MissionLegalSemVer $ExistingVersion $Highest) -gt 0) {
            $Highest = $ExistingVersion
        }
    }
    if ($null -ne $Highest -and (Compare-MissionLegalSemVer $CandidateVersion $Highest) -le 0) {
        throw (
            "Production release version $CandidateVersion is not newer than $Highest in $SourceDescription. " +
            "Bump APP_VERSION; published version history is monotonic and immutable."
        )
    }
}

function Get-NormalizedCertificateThumbprint {
    param([Parameter(Mandatory = $true)][string]$Thumbprint)

    $Trimmed = $Thumbprint.Trim()
    if ($Trimmed -match '[^0-9A-Fa-f\s]') {
        throw "Expected signer thumbprint may contain only hexadecimal digits and whitespace separators."
    }
    $Normalized = ($Trimmed -replace '\s', '').ToUpperInvariant()
    if ($Normalized -notmatch '^[0-9A-F]{40}$') {
        throw "Expected signer thumbprint must be the certificate's 40-character hexadecimal SHA-1 thumbprint."
    }
    return $Normalized
}

function Test-MissionLegalSafeWindowsLeafName {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (
        [string]::IsNullOrWhiteSpace($Name) -or
        $Name -in @('.', '..') -or
        [IO.Path]::IsPathRooted($Name) -or
        -not $Name.Equals([IO.Path]::GetFileName($Name), [StringComparison]::Ordinal) -or
        $Name -match '[<>:"/\\|?*\x00-\x1F]' -or
        $Name.EndsWith('.', [StringComparison]::Ordinal) -or
        $Name.EndsWith(' ', [StringComparison]::Ordinal)
    ) {
        return $false
    }
    $Stem = $Name.Split('.')[0]
    if ($Stem -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') {
        return $false
    }
    return $true
}

function Assert-MissionLegalAuthenticodeSignature {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedSignerThumbprint,
        [switch]$RequireTimestamp
    )

    $ResolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $Signature = Get-AuthenticodeSignature -LiteralPath $ResolvedPath
    if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw (
            "Authenticode signature is not valid for '$ResolvedPath': " +
            "$($Signature.Status) - $($Signature.StatusMessage)"
        )
    }
    if ($null -eq $Signature.SignerCertificate) {
        throw "Authenticode signature has no signer certificate: $ResolvedPath"
    }
    $ActualThumbprint = Get-NormalizedCertificateThumbprint $Signature.SignerCertificate.Thumbprint
    $ExpectedThumbprint = $null
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint)) {
        $ExpectedThumbprint = Get-NormalizedCertificateThumbprint $ExpectedSignerThumbprint
        if (-not $ActualThumbprint.Equals($ExpectedThumbprint, [StringComparison]::OrdinalIgnoreCase)) {
            throw (
                "Authenticode signer mismatch for '$ResolvedPath'. " +
                "Expected $ExpectedThumbprint, found $ActualThumbprint."
            )
        }
    }
    if ($RequireTimestamp -and $null -eq $Signature.TimeStamperCertificate) {
        throw "Authenticode signature is missing a trusted timestamp countersignature: $ResolvedPath"
    }

    return [ordered]@{
        filename = [IO.Path]::GetFileName($ResolvedPath)
        sha256 = (Get-FileHash -LiteralPath $ResolvedPath -Algorithm SHA256).Hash.ToLowerInvariant()
        signer_subject = $Signature.SignerCertificate.Subject
        signer_thumbprint = $ActualThumbprint
        timestamped = [bool]($null -ne $Signature.TimeStamperCertificate)
        timestamp_authority = if ($null -ne $Signature.TimeStamperCertificate) {
            $Signature.TimeStamperCertificate.Subject
        }
        else {
            $null
        }
    }
}

function Test-MissionLegalSafeArchiveEntry {
    param([Parameter(Mandatory = $true)][string]$EntryName)

    if ([string]::IsNullOrWhiteSpace($EntryName) -or [IO.Path]::IsPathRooted($EntryName)) {
        return $false
    }
    if ($EntryName.Contains(':')) {
        return $false
    }
    $Normalized = $EntryName.Replace('/', '\')
    foreach ($Segment in $Normalized.Split('\')) {
        if ($Segment -in @('.', '..')) { return $false }
    }
    return $true
}

function Assert-MissionLegalClientPackageSignatures {
    param(
        [Parameter(Mandatory = $true)][string]$PackagePath,
        [Parameter(Mandatory = $true)][string]$TemporaryRoot,
        [string]$ExpectedSignerThumbprint,
        [switch]$RequireTimestamp
    )

    $ExtractionRoot = Join-Path $TemporaryRoot ("client-package-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $ExtractionRoot | Out-Null
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $Archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $PackagePath).Path)
        try {
            $SeenEntries = [Collections.Generic.HashSet[string]]::new(
                [StringComparer]::OrdinalIgnoreCase
            )
            foreach ($Entry in $Archive.Entries) {
                if (-not (Test-MissionLegalSafeArchiveEntry $Entry.FullName)) {
                    throw "Client package contains an unsafe archive entry: $($Entry.FullName)"
                }
                $NormalizedEntry = $Entry.FullName.Replace('\', '/').TrimEnd('/')
                if (-not [string]::IsNullOrWhiteSpace($NormalizedEntry) -and -not $SeenEntries.Add($NormalizedEntry)) {
                    throw "Client package contains a duplicate case-insensitive archive path: $($Entry.FullName)"
                }
            }
        }
        finally {
            $Archive.Dispose()
        }
        [IO.Compression.ZipFile]::ExtractToDirectory(
            (Resolve-Path -LiteralPath $PackagePath).Path,
            $ExtractionRoot
        )

        $Evidence = [Collections.Generic.List[object]]::new()
        foreach ($RelativePath in @(
            'lib\app\MissionLegal.exe',
            'lib\app\MissionLegalUpdateWorker.exe',
            'lib\app\MissionLegalClientSetup.exe',
            'lib\app\MissionLegalDiagnostics.exe',
            'lib\app\MissionLegal_ExecutionStub.exe'
        )) {
            $ExecutablePath = Join-Path $ExtractionRoot $RelativePath
            if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
                throw "Signed client package is missing required executable '$RelativePath'."
            }
            $Item = Assert-MissionLegalAuthenticodeSignature `
                -Path $ExecutablePath `
                -ExpectedSignerThumbprint $ExpectedSignerThumbprint `
                -RequireTimestamp:$RequireTimestamp
            $Item['path_in_package'] = $RelativePath.Replace('\', '/')
            $Evidence.Add($Item) | Out-Null
        }
        return @($Evidence)
    }
    finally {
        if (Test-Path -LiteralPath $ExtractionRoot -PathType Container) {
            Remove-Item -LiteralPath $ExtractionRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-MissionLegalClientPackageUpdateConfig {
    param([Parameter(Mandatory = $true)][string]$PackagePath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $PackagePath).Path)
    try {
        $Matches = @($Archive.Entries | Where-Object {
            $_.FullName.Equals('lib/app/mission-legal-update.json', [StringComparison]::Ordinal)
        })
        if ($Matches.Count -ne 1) {
            throw "Client full package must contain exactly one controlled mission-legal-update.json."
        }
        $Stream = $Matches[0].Open()
        $Reader = [IO.StreamReader]::new($Stream, (New-Object Text.UTF8Encoding($false, $true)))
        try {
            $Json = $Reader.ReadToEnd()
        }
        finally {
            $Reader.Dispose()
            $Stream.Dispose()
        }
        try {
            return $Json | ConvertFrom-Json
        }
        catch {
            throw "Embedded mission-legal-update.json is not valid UTF-8 JSON."
        }
    }
    finally {
        $Archive.Dispose()
    }
}

function Enter-MissionLegalReleaseLock {
    param([Parameter(Mandatory = $true)][string]$LockPath)

    $FullPath = [IO.Path]::GetFullPath($LockPath)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $FullPath) | Out-Null
    try {
        return [IO.File]::Open(
            $FullPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch {
        throw "Another release transaction holds the build lock '$FullPath'. $($_.Exception.Message)"
    }
}

function New-MissionLegalReleaseTransaction {
    param(
        [Parameter(Mandatory = $true)][string]$FinalDirectory,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$CopyExisting
    )

    $FinalPath = [IO.Path]::GetFullPath($FinalDirectory).TrimEnd('\', '/')
    $Parent = Split-Path -Parent $FinalPath
    $Leaf = Split-Path -Leaf $FinalPath
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    $SafeLabel = $Label -replace '[^A-Za-z0-9._-]', '-'
    $Transaction = Join-Path $Parent (".$Leaf.$SafeLabel.transaction-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Transaction | Out-Null

    if ($CopyExisting -and (Test-Path -LiteralPath $FinalPath -PathType Container)) {
        foreach ($Item in @(Get-ChildItem -LiteralPath $FinalPath -Force)) {
            Copy-Item -LiteralPath $Item.FullName -Destination $Transaction -Recurse -Force
        }
    }
    return $Transaction
}

function Repair-MissionLegalInterruptedReleaseTransaction {
    param([Parameter(Mandatory = $true)][string]$FinalDirectory)

    $FinalPath = [IO.Path]::GetFullPath($FinalDirectory).TrimEnd('\', '/')
    $Parent = Split-Path -Parent $FinalPath
    $Leaf = Split-Path -Leaf $FinalPath
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    $RollbackDirectories = @(Get-ChildItem -LiteralPath $Parent -Directory -Force | Where-Object {
        $_.Name.StartsWith("$Leaf.rollback-", [StringComparison]::OrdinalIgnoreCase)
    })
    $TransactionDirectories = @(Get-ChildItem -LiteralPath $Parent -Directory -Force | Where-Object {
        $_.Name.StartsWith(".$Leaf.", [StringComparison]::OrdinalIgnoreCase) -and
        $_.Name -match '\.transaction-[0-9a-f]{32}$'
    })

    if (-not (Test-Path -LiteralPath $FinalPath -PathType Container)) {
        if ($RollbackDirectories.Count -gt 1) {
            throw (
                "Multiple interrupted release rollback directories exist for '$FinalPath'. " +
                "Preserve them for diagnosis and restore the intended release manually."
            )
        }
        if ($RollbackDirectories.Count -eq 1) {
            Move-Item -LiteralPath $RollbackDirectories[0].FullName -Destination $FinalPath
            Write-Warning "Recovered the prior release directory after an interrupted finalization: $FinalPath"
            $RollbackDirectories = @()
        }
    }

    if (Test-Path -LiteralPath $FinalPath -PathType Container) {
        foreach ($Rollback in $RollbackDirectories) {
            try {
                Remove-Item -LiteralPath $Rollback.FullName -Recurse -Force
            }
            catch {
                Write-Warning "Could not remove completed release rollback directory: $($Rollback.FullName)"
            }
        }
    }
    foreach ($Transaction in $TransactionDirectories) {
        try {
            Remove-Item -LiteralPath $Transaction.FullName -Recurse -Force
        }
        catch {
            throw "Could not remove interrupted release transaction '$($Transaction.FullName)'. $($_.Exception.Message)"
        }
    }
}

function Complete-MissionLegalReleaseTransaction {
    param(
        [Parameter(Mandatory = $true)][string]$TransactionDirectory,
        [Parameter(Mandatory = $true)][string]$FinalDirectory
    )

    $TransactionPath = (Resolve-Path -LiteralPath $TransactionDirectory).Path.TrimEnd('\', '/')
    $FinalPath = [IO.Path]::GetFullPath($FinalDirectory).TrimEnd('\', '/')
    $TransactionParent = Split-Path -Parent $TransactionPath
    $FinalParent = Split-Path -Parent $FinalPath
    if (-not $TransactionParent.Equals($FinalParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Release transaction and final directory must be siblings on the same volume."
    }

    $BackupPath = "$FinalPath.rollback-" + [Guid]::NewGuid().ToString('N')
    $HadFinal = Test-Path -LiteralPath $FinalPath -PathType Container
    if ($HadFinal) {
        Move-Item -LiteralPath $FinalPath -Destination $BackupPath
    }
    try {
        Move-Item -LiteralPath $TransactionPath -Destination $FinalPath
    }
    catch {
        if ($HadFinal -and -not (Test-Path -LiteralPath $FinalPath) -and (Test-Path -LiteralPath $BackupPath)) {
            Move-Item -LiteralPath $BackupPath -Destination $FinalPath
        }
        throw
    }

    if ($HadFinal -and (Test-Path -LiteralPath $BackupPath -PathType Container)) {
        try {
            Remove-Item -LiteralPath $BackupPath -Recurse -Force
        }
        catch {
            Write-Warning "Release committed, but the rollback directory could not be removed: $BackupPath"
        }
    }
    return $FinalPath
}

function Write-MissionLegalJsonAtomic {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(2, 100)][int]$Depth = 20,
        [switch]$RequireAbsent
    )

    $FullPath = [IO.Path]::GetFullPath($Path)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $FullPath) | Out-Null
    if ($RequireAbsent -and (Test-Path -LiteralPath $FullPath)) {
        throw "Immutable release metadata already exists: $FullPath"
    }
    # Keep the temporary leaf short. Windows PowerShell 5.1 still reaches
    # legacy MAX_PATH behavior through some .NET file APIs, and appending a
    # GUID to the complete release-manifest name can surface as a misleading
    # DirectoryNotFoundException even though the transaction directory exists.
    $TemporaryPath = Join-Path `
        (Split-Path -Parent $FullPath) `
        ('.json-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $Json = $Value | ConvertTo-Json -Depth $Depth
        [IO.File]::WriteAllText($TemporaryPath, $Json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
        if ($RequireAbsent -and (Test-Path -LiteralPath $FullPath)) {
            throw "Immutable release metadata appeared during finalization: $FullPath"
        }
        Move-Item -LiteralPath $TemporaryPath -Destination $FullPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $TemporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $TemporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
    return $FullPath
}
