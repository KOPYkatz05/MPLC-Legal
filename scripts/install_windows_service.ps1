param(
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe",
    [int]$Port = 8765,
    [Parameter(Mandatory = $true)]
    [string]$MissionStorageRoot,
    [Parameter(Mandatory = $true)]
    [string]$OneDriveBackupDir
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$ServiceScript = Join-Path $RepoRoot "windows_service.py"

& $PythonPath (Join-Path $RepoRoot "server_setup.py") `
    --mission-storage-root $MissionStorageRoot `
    --onedrive-backup-dir $OneDriveBackupDir `
    --port $Port
if ($LASTEXITCODE -ne 0) {
    throw "Mission Legal Server configuration failed."
}

icacls.exe $MissionStorageRoot /grant "SYSTEM:(OI)(CI)M" | Out-Null
icacls.exe $OneDriveBackupDir /grant "SYSTEM:(OI)(CI)M" | Out-Null

& $PythonPath $ServiceScript --startup auto install
if ($LASTEXITCODE -ne 0) {
    throw "Mission Legal Server service installation failed."
}

sc.exe failure MissionLegalServer reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
sc.exe failureflag MissionLegalServer 1 | Out-Null

$RuleName = "Mission Legal Server HTTPS"
if (-not (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule `
        -DisplayName $RuleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Port `
        -Profile Private | Out-Null
}

Start-Service MissionLegalServer

try {
    $dataVolume = (Split-Path -Qualifier (Join-Path $env:PROGRAMDATA "MissionLegal")).TrimEnd('\')
    $bitLocker = Get-BitLockerVolume -MountPoint $dataVolume -ErrorAction Stop
    if ($bitLocker.ProtectionStatus -ne "On") {
        Write-Warning "BitLocker protection is not enabled on $dataVolume."
    }
} catch {
    Write-Warning "BitLocker status could not be verified: $($_.Exception.Message)"
}

Write-Host "Mission Legal Server installed and started on HTTPS port $Port."
