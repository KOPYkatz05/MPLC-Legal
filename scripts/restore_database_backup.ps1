param(
    [Parameter(Mandatory = $true)]
    [string]$Snapshot,
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$SnapshotPath = (Resolve-Path -LiteralPath $Snapshot).Path
$env:MISSION_LEGAL_DATA_DIR = Join-Path $env:PROGRAMDATA "MissionLegal"
$wasRunning = (Get-Service MissionLegalServer -ErrorAction Stop).Status -eq "Running"

if ($wasRunning) {
    Stop-Service MissionLegalServer
}

try {
    & $PythonPath (Join-Path $RepoRoot "restore_database.py") $SnapshotPath
    if ($LASTEXITCODE -ne 0) {
        throw "Database restore failed."
    }
} finally {
    if ($wasRunning) {
        Start-Service MissionLegalServer
    }
}
