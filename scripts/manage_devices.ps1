param(
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe",
    [string]$RevokeDeviceId
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$env:MISSION_LEGAL_DATA_DIR = Join-Path $env:PROGRAMDATA "MissionLegal"
$ServerScript = Join-Path $RepoRoot "server_main.py"

if ($RevokeDeviceId) {
    & $PythonPath $ServerScript --revoke-device $RevokeDeviceId
} else {
    & $PythonPath $ServerScript --list-devices
}

if ($LASTEXITCODE -ne 0) {
    throw "Mission Legal device management failed."
}
