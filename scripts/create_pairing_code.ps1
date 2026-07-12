param(
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$env:MISSION_LEGAL_DATA_DIR = Join-Path $env:PROGRAMDATA "MissionLegal"

& $PythonPath (Join-Path $RepoRoot "server_main.py") --create-pairing-code
if ($LASTEXITCODE -ne 0) {
    throw "Could not create a Mission Legal pairing code."
}
