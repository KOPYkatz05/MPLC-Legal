[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Capture", "Restore", "Discard")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [Parameter(Mandatory = $true)]
    [string]$SnapshotDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$SnapshotDir = [IO.Path]::GetFullPath($SnapshotDir).TrimEnd('\')
if ($InstallDir.Equals($SnapshotDir, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The binary rollback snapshot cannot be the installation directory."
}
if (
    $SnapshotDir.StartsWith($InstallDir + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $InstallDir.StartsWith($SnapshotDir + '\', [StringComparison]::OrdinalIgnoreCase)
) {
    throw "The installation and rollback snapshot directories cannot contain one another."
}

$MetadataPath = Join-Path $SnapshotDir "snapshot.json"
$FilesDir = Join-Path $SnapshotDir "files"
$RobocopyPath = Join-Path $env:SystemRoot "System32\robocopy.exe"

function Invoke-RobocopyMirror {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $RobocopyPath -PathType Leaf)) {
        throw "Windows robocopy.exe is required for binary rollback."
    }
    New-Item -ItemType Directory -Force -Path $Source, $Destination | Out-Null
    & $RobocopyPath `
        $Source `
        $Destination `
        /MIR `
        /COPY:DAT `
        /DCOPY:DAT `
        /R:2 `
        /W:1 `
        /XJ `
        /NFL `
        /NDL `
        /NP `
        /NJH `
        /NJS | Out-Null
    $ExitCode = $LASTEXITCODE
    # Robocopy uses 0 through 7 for successful copy/difference outcomes.
    if ($ExitCode -gt 7) {
        throw "Robocopy failed with exit code $ExitCode."
    }
}

function Get-FileInventory {
    param([Parameter(Mandatory = $true)][string]$Root)

    $RootPrefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    return @(
        Get-ChildItem -LiteralPath $Root -Recurse -Force -File |
            Sort-Object FullName |
            ForEach-Object {
                $FullName = [IO.Path]::GetFullPath($_.FullName)
                if (-not $FullName.StartsWith($RootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Rollback inventory escaped its expected root: $FullName"
                }
                [ordered]@{
                    path = $FullName.Substring($RootPrefix.Length).Replace('\', '/')
                    size = $_.Length
                    sha256 = (Get-FileHash -LiteralPath $FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                }
            }
    )
}

function Get-InventoryFingerprint {
    param([AllowEmptyCollection()][object[]]$Inventory)

    $Lines = @(
        foreach ($Entry in @($Inventory)) {
            $Path = [string]$Entry.path
            $Size = [int64]$Entry.size
            $Sha256 = ([string]$Entry.sha256).ToLowerInvariant()
            if (
                [string]::IsNullOrWhiteSpace($Path) -or
                $Size -lt 0 -or
                $Sha256 -notmatch '^[0-9a-f]{64}$'
            ) {
                throw "The binary rollback inventory contains an invalid file record."
            }
            "{0}`t{1}`t{2}" -f $Path, $Size, $Sha256
        }
    )
    return [string]::Join("`n", [string[]]$Lines)
}

function Test-InventoryMatches {
    param(
        [AllowEmptyCollection()][object[]]$Expected,
        [AllowEmptyCollection()][object[]]$Actual
    )

    $ExpectedFingerprint = Get-InventoryFingerprint -Inventory @($Expected)
    $ActualFingerprint = Get-InventoryFingerprint -Inventory @($Actual)
    return $ExpectedFingerprint.Equals(
        $ActualFingerprint,
        [StringComparison]::Ordinal
    )
}

function Read-SnapshotMetadata {
    if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) {
        throw "The binary rollback snapshot metadata is missing: $MetadataPath"
    }
    try {
        $Metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
    }
    catch {
        throw "The binary rollback snapshot metadata is invalid: $($_.Exception.Message)"
    }
    if (
        -not ([string]$Metadata.install_dir).Equals(
            $InstallDir,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "The binary rollback snapshot belongs to a different installation directory."
    }
    if ([int]$Metadata.format -ne 1) {
        throw "The binary rollback snapshot format is not supported."
    }
    return $Metadata
}

function Assert-SnapshotInventory {
    param([Parameter(Mandatory = $true)][object]$Metadata)

    if (-not (Test-Path -LiteralPath $FilesDir -PathType Container)) {
        throw "The binary rollback files directory is missing: $FilesDir"
    }
    $Expected = @($Metadata.files)
    $Actual = @(Get-FileInventory -Root $FilesDir)
    if (-not (Test-InventoryMatches -Expected $Expected -Actual $Actual)) {
        throw "The saved rollback files do not match their SHA-256 inventory."
    }
}

switch ($Action) {
    "Capture" {
        if (Test-Path -LiteralPath $SnapshotDir) {
            try {
                $ExistingMetadata = Read-SnapshotMetadata
                Assert-SnapshotInventory -Metadata $ExistingMetadata
                $CurrentInstallExists = Test-Path -LiteralPath $InstallDir -PathType Container
                if ([bool]$ExistingMetadata.had_installation -ne $CurrentInstallExists) {
                    throw "The current installation presence does not match the saved rollback state."
                }
                $CurrentInventory = if ($CurrentInstallExists) {
                    @(Get-FileInventory -Root $InstallDir)
                }
                else {
                    @()
                }
                if (
                    -not (Test-InventoryMatches `
                        -Expected @($ExistingMetadata.files) `
                        -Actual @($CurrentInventory))
                ) {
                    throw "The current installation differs from the saved rollback snapshot."
                }
            }
            catch {
                throw (
                    "An existing binary rollback snapshot was preserved at '$SnapshotDir'. " +
                    "It cannot be replaced because the prior installation may still require recovery. " +
                    "Restore or archive that snapshot before retrying this version. Details: $($_.Exception.Message)"
                )
            }
            Remove-Item -LiteralPath $SnapshotDir -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $FilesDir | Out-Null
        $HadInstallation = Test-Path -LiteralPath $InstallDir -PathType Container
        if ($HadInstallation) {
            Invoke-RobocopyMirror -Source $InstallDir -Destination $FilesDir
        }
        $Inventory = Get-FileInventory -Root $FilesDir
        $Metadata = [ordered]@{
            format = 1
            install_dir = $InstallDir
            had_installation = [bool]$HadInstallation
            captured_at = [DateTimeOffset]::UtcNow.ToString("o")
            files = $Inventory
        }
        $Metadata | ConvertTo-Json -Depth 6 |
            Set-Content -LiteralPath $MetadataPath -Encoding UTF8
        Write-Host "Captured $($Inventory.Count) installed files for rollback."
    }
    "Restore" {
        $Metadata = Read-SnapshotMetadata
        Assert-SnapshotInventory -Metadata $Metadata
        if (-not [bool]$Metadata.had_installation) {
            Write-Host "There was no prior installation to restore."
            break
        }
        Invoke-RobocopyMirror -Source $FilesDir -Destination $InstallDir
        $Expected = @($Metadata.files)
        $Actual = @(Get-FileInventory -Root $InstallDir)
        if (-not (Test-InventoryMatches -Expected $Expected -Actual $Actual)) {
            throw "The restored application files do not match the verified rollback snapshot."
        }
        Write-Host "Restored and verified $($Actual.Count) installed files."
    }
    "Discard" {
        $Metadata = Read-SnapshotMetadata
        Assert-SnapshotInventory -Metadata $Metadata
        Remove-Item -LiteralPath $SnapshotDir -Recurse -Force
        Write-Host "Discarded the verified binary rollback snapshot."
    }
}
