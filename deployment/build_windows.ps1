param(
    [ValidateSet("All", "Client", "Server")]
    [string]$Target = "All",
    [string]$PythonPath = "$PSScriptRoot\..\venv\Scripts\python.exe",
    [string]$OcrModelRoot = "C:\Local Apps\paddle_models\.paddleocr\whl"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = [IO.Path]::GetFullPath($PythonPath)

# Build and smoke-test roles must not inherit a role marker from a previously
# launched development process.
Remove-Item Env:MISSION_LEGAL_REMOTE_CLIENT -ErrorAction SilentlyContinue
Remove-Item Env:MISSION_LEGAL_SERVER_PROCESS -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable was not found: $PythonPath"
}

& $PythonPath -c "import PyInstaller; import _pyinstaller_hooks_contrib"
if ($LASTEXITCODE -ne 0) {
    throw "Build dependencies are missing. Run: $PythonPath -m pip install -r requirements_build.txt"
}

$AppVersion = (& $PythonPath -c "from version import APP_VERSION; print(APP_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $AppVersion) {
    throw "Could not read APP_VERSION from version.py."
}

$DistRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "dist\$AppVersion"))
$WorkRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "build\pyinstaller\$AppVersion"))
$RepoPrefix = $RepoRoot.TrimEnd('\') + '\'
foreach ($Path in @($DistRoot, $WorkRoot)) {
    if (-not $Path.StartsWith($RepoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build output escaped the repository root: $Path"
    }
}

New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
$MatplotlibConfig = Join-Path $WorkRoot "matplotlib"
New-Item -ItemType Directory -Force -Path $MatplotlibConfig | Out-Null
$env:MPLCONFIGDIR = $MatplotlibConfig

function Invoke-PyInstallerBuild {
    param(
        [string]$SpecName,
        [string]$WorkName
    )

    $SpecPath = Join-Path $PSScriptRoot $SpecName
    $WorkPath = Join-Path $WorkRoot $WorkName
    & $PythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --log-level WARN `
        --distpath $DistRoot `
        --workpath $WorkPath `
        $SpecPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed for $SpecName."
    }
}

if ($Target -in @("All", "Client")) {
    $ResolvedModelRoot = (Resolve-Path -LiteralPath $OcrModelRoot).Path
    $env:MISSION_LEGAL_BUILD_OCR_MODEL_ROOT = $ResolvedModelRoot
    Invoke-PyInstallerBuild "mission_legal_client.spec" "client"

    $ClientDir = Join-Path $DistRoot "MissionLegalClient"
    $ClientExe = Join-Path $ClientDir "MissionLegal.exe"
    $ClientDiagnosticsExe = Join-Path $ClientDir "MissionLegalDiagnostics.exe"
    $ClientSetupExe = Join-Path $ClientDir "MissionLegalClientSetup.exe"
    foreach ($Path in @($ClientExe, $ClientDiagnosticsExe, $ClientSetupExe)) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Expected client artifact is missing: $Path"
        }
    }
    $ClientRuntime = Join-Path $WorkRoot "client-smoke-runtime"
    New-Item -ItemType Directory -Force -Path $ClientRuntime | Out-Null
    $env:MISSION_LEGAL_CLIENT_DATA_DIR = $ClientRuntime
    $env:MISSION_LEGAL_SMOKE_PROGRESS = Join-Path $ClientRuntime "progress.log"
    if (Test-Path -LiteralPath $env:MISSION_LEGAL_SMOKE_PROGRESS -PathType Leaf) {
        Remove-Item -LiteralPath $env:MISSION_LEGAL_SMOKE_PROGRESS -Force
    }
    $ClientSmoke = Start-Process `
        -FilePath $ClientDiagnosticsExe `
        -ArgumentList "--package-smoke-test" `
        -WorkingDirectory $ClientDir `
        -WindowStyle Hidden `
        -PassThru
    if (-not $ClientSmoke.WaitForExit(180000)) {
        Stop-Process -Id $ClientSmoke.Id -Force
        throw "The packaged client smoke test timed out. See $env:MISSION_LEGAL_SMOKE_PROGRESS"
    }
    if ($ClientSmoke.ExitCode -ne 0) {
        throw "The packaged client smoke test failed. See $env:MISSION_LEGAL_SMOKE_PROGRESS"
    }
    & $ClientSetupExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged client setup utility failed its CLI smoke test."
    }
}

if ($Target -in @("All", "Server")) {
    Invoke-PyInstallerBuild "mission_legal_server.spec" "server"

    $ServerDir = Join-Path $DistRoot "MissionLegalServer"
    $ServerExe = Join-Path $ServerDir "MissionLegalServer.exe"
    $ServerSetupExe = Join-Path $ServerDir "MissionLegalServerSetup.exe"
    $ServiceExe = Join-Path $ServerDir "MissionLegalService.exe"
    foreach ($Path in @($ServerExe, $ServerSetupExe, $ServiceExe)) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Expected server artifact is missing: $Path"
        }
    }
    $ServerRuntime = Join-Path $WorkRoot "server-smoke-runtime"
    New-Item -ItemType Directory -Force -Path $ServerRuntime | Out-Null
    $env:MISSION_LEGAL_SMOKE_DATA_DIR = $ServerRuntime
    $env:MISSION_LEGAL_SMOKE_PROGRESS = Join-Path $ServerRuntime "progress.log"
    if (Test-Path -LiteralPath $env:MISSION_LEGAL_SMOKE_PROGRESS -PathType Leaf) {
        Remove-Item -LiteralPath $env:MISSION_LEGAL_SMOKE_PROGRESS -Force
    }
    & $ServerExe --package-smoke-test
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged server smoke test failed."
    }
    & $ServerSetupExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged server setup utility failed its CLI smoke test."
    }
}

Write-Host "Mission Legal $AppVersion package build completed: $DistRoot"
