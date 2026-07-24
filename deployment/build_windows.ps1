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

$VersionPayloadText = (& $PythonPath -B -c "import json,sys; sys.path.insert(0,sys.argv[1]); from version import API_VERSION, APP_VERSION, SCHEMA_VERSION; print(json.dumps({'app_version':APP_VERSION,'api_version':API_VERSION,'schema_version':SCHEMA_VERSION}))" $RepoRoot).Trim()
if ($LASTEXITCODE -ne 0 -or -not $VersionPayloadText) {
    throw "Could not read release versions from version.py."
}
try {
    $VersionPayload = $VersionPayloadText | ConvertFrom-Json
}
catch {
    throw "version.py returned invalid release-version metadata: $VersionPayloadText"
}
$AppVersion = [string]$VersionPayload.app_version
$ApiVersion = [string]$VersionPayload.api_version
$SchemaVersion = [int]$VersionPayload.schema_version
if (-not $AppVersion -or -not $ApiVersion -or $SchemaVersion -lt 1) {
    throw "version.py returned incomplete release-version metadata."
}

$ProvenanceHelper = Join-Path $PSScriptRoot "package_provenance.py"
if (-not (Test-Path -LiteralPath $ProvenanceHelper -PathType Leaf)) {
    throw "Package provenance helper is missing: $ProvenanceHelper"
}
$DependencyLock = Join-Path $RepoRoot "requirements_lock.txt"
$BuildDependencyLock = Join-Path $RepoRoot "requirements_build.txt"
foreach ($LockPath in @($DependencyLock, $BuildDependencyLock)) {
    if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
        throw "Required dependency lock is missing: $LockPath"
    }
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

function New-PackageProvenance {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("client", "server")][string]$Role,
        [Parameter(Mandatory = $true)][string]$PackageDir,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$SmokeResultPath,
        [Parameter(Mandatory = $true)][string[]]$WindowsVersionExecutables,
        [string]$ResolvedOcrModelRoot
    )

    $ProvenanceArguments = @(
        $ProvenanceHelper,
        "create",
        "--repo-root", $RepoRoot,
        "--package-dir", $PackageDir,
        "--manifest-path", $ManifestPath,
        "--role", $Role,
        "--app-version", $AppVersion,
        "--api-version", $ApiVersion,
        "--schema-version", [string]$SchemaVersion,
        "--smoke-result", $SmokeResultPath,
        "--dependency-lock", $DependencyLock,
        "--dependency-lock", $BuildDependencyLock,
        "--tool-package", "PyInstaller",
        "--tool-package", "pyinstaller-hooks-contrib"
    )
    if ($WindowsVersionExecutables.Count -lt 1) {
        throw "$Role package provenance requires PyInstaller executable version checks."
    }
    foreach ($Executable in $WindowsVersionExecutables) {
        $ProvenanceArguments += @("--windows-version-exe", $Executable)
    }
    if ($Role -eq "client") {
        if ([string]::IsNullOrWhiteSpace($ResolvedOcrModelRoot)) {
            throw "Client package provenance requires the resolved OCR model root."
        }
        $ProvenanceArguments += @(
            "--tool-package", "PySide6",
            "--tool-package", "paddleocr",
            "--tool-package", "paddlepaddle",
            "--tool-package", "velopack",
            "--ocr-model-root", $ResolvedOcrModelRoot
        )
    }
    else {
        $ProvenanceArguments += @(
            "--tool-package", "cryptography",
            "--tool-package", "fastapi",
            "--tool-package", "SQLAlchemy",
            "--tool-package", "uvicorn"
        )
    }

    & $PythonPath -B @ProvenanceArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create verified $Role package provenance: $ManifestPath"
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
    $ClientUpdateWorkerExe = Join-Path $ClientDir "MissionLegalUpdateWorker.exe"
    foreach ($Path in @(
        $ClientExe,
        $ClientDiagnosticsExe,
        $ClientSetupExe,
        $ClientUpdateWorkerExe
    )) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Expected client artifact is missing: $Path"
        }
    }
    $ClientRuntime = Join-Path $WorkRoot "client-smoke-runtime"
    New-Item -ItemType Directory -Force -Path $ClientRuntime | Out-Null
    $env:MISSION_LEGAL_CLIENT_DATA_DIR = $ClientRuntime
    $env:MISSION_LEGAL_SMOKE_PROGRESS = Join-Path $ClientRuntime "progress.log"
    $ClientSmokeOutput = Join-Path $ClientRuntime "smoke-result.stdout.log"
    $ClientSmokeError = Join-Path $ClientRuntime "smoke-result.stderr.log"
    foreach ($SmokePath in @(
        $env:MISSION_LEGAL_SMOKE_PROGRESS,
        $ClientSmokeOutput,
        $ClientSmokeError
    )) {
        if (Test-Path -LiteralPath $SmokePath -PathType Leaf) {
            Remove-Item -LiteralPath $SmokePath -Force
        }
    }
    # The raw PyInstaller folder is intentionally not a Velopack installation.
    # Skip only the Velopack lifecycle bootstrap while exercising the packaged
    # application imports; installed-update smoke tests leave it enabled.
    $PreviousVelopackBootstrapSkip = [Environment]::GetEnvironmentVariable(
        "MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP",
        "Process"
    )
    $env:MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP = "1"
    try {
        $ClientSmoke = Start-Process `
            -FilePath $ClientDiagnosticsExe `
            -ArgumentList "--package-smoke-test" `
            -WorkingDirectory $ClientDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $ClientSmokeOutput `
            -RedirectStandardError $ClientSmokeError `
            -PassThru
        try {
            $ClientSmoke | Wait-Process -Timeout 180 -ErrorAction Stop
        }
        catch {
            if (-not $ClientSmoke.HasExited) {
                Stop-Process -Id $ClientSmoke.Id -Force
                throw "The packaged client smoke test timed out. See $env:MISSION_LEGAL_SMOKE_PROGRESS"
            }
            throw
        }
        if ($null -eq $ClientSmoke.ExitCode) {
            throw "The packaged client smoke test completed without a readable exit code."
        }
        if ($ClientSmoke.ExitCode -ne 0) {
            throw "The packaged client smoke test failed. See $env:MISSION_LEGAL_SMOKE_PROGRESS"
        }
    }
    finally {
        if ($null -eq $PreviousVelopackBootstrapSkip) {
            Remove-Item Env:MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP -ErrorAction SilentlyContinue
        }
        else {
            $env:MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP = $PreviousVelopackBootstrapSkip
        }
    }
    & $ClientSetupExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged client setup utility failed its CLI smoke test."
    }
    & $ClientUpdateWorkerExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged client update worker failed its CLI smoke test."
    }
    $ClientManifest = Join-Path $DistRoot "MissionLegalClient.provenance.json"
    New-PackageProvenance `
        -Role "client" `
        -PackageDir $ClientDir `
        -ManifestPath $ClientManifest `
        -SmokeResultPath $ClientSmokeOutput `
        -WindowsVersionExecutables @(
            "MissionLegal.exe",
            "MissionLegalDiagnostics.exe",
            "MissionLegalClientSetup.exe",
            "MissionLegalUpdateWorker.exe"
        ) `
        -ResolvedOcrModelRoot $ResolvedModelRoot
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
    $ServerSmokeOutput = Join-Path $ServerRuntime "smoke-result.stdout.log"
    $ServerSmokeError = Join-Path $ServerRuntime "smoke-result.stderr.log"
    $ServiceSmokeOutput = Join-Path $ServerRuntime "service-smoke-result.stdout.log"
    $ServiceSmokeError = Join-Path $ServerRuntime "service-smoke-result.stderr.log"
    $ServerHttpsSmokeOutput = Join-Path $ServerRuntime "https-smoke-result.jsonl"
    $ServerHttpsSmokeStdout = Join-Path $ServerRuntime "https-server.stdout.log"
    $ServerHttpsSmokeStderr = Join-Path $ServerRuntime "https-server.stderr.log"
    foreach ($SmokePath in @(
        $env:MISSION_LEGAL_SMOKE_PROGRESS,
        $ServerSmokeOutput,
        $ServerSmokeError,
        $ServiceSmokeOutput,
        $ServiceSmokeError,
        $ServerHttpsSmokeOutput,
        $ServerHttpsSmokeStdout,
        $ServerHttpsSmokeStderr
    )) {
        if (Test-Path -LiteralPath $SmokePath -PathType Leaf) {
            Remove-Item -LiteralPath $SmokePath -Force
        }
    }
    $ServerSmoke = Start-Process `
        -FilePath $ServerExe `
        -ArgumentList "--package-smoke-test" `
        -WorkingDirectory $ServerDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ServerSmokeOutput `
        -RedirectStandardError $ServerSmokeError `
        -PassThru
    try {
        $ServerSmoke | Wait-Process -Timeout 180 -ErrorAction Stop
    }
    catch {
        if (-not $ServerSmoke.HasExited) {
            Stop-Process -Id $ServerSmoke.Id -Force
            throw "The packaged server smoke test timed out. See $env:MISSION_LEGAL_SMOKE_PROGRESS"
        }
        throw
    }
    if ($null -eq $ServerSmoke.ExitCode) {
        throw "The packaged server smoke test completed without a readable exit code."
    }
    if ($ServerSmoke.ExitCode -ne 0) {
        throw "The packaged server smoke test failed."
    }
    $ServiceSmoke = Start-Process `
        -FilePath $ServiceExe `
        -ArgumentList "--package-smoke-test" `
        -WorkingDirectory $ServerDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ServiceSmokeOutput `
        -RedirectStandardError $ServiceSmokeError `
        -PassThru
    try {
        $ServiceSmoke | Wait-Process -Timeout 180 -ErrorAction Stop
    }
    catch {
        if (-not $ServiceSmoke.HasExited) {
            Stop-Process -Id $ServiceSmoke.Id -Force
            throw (
                "The packaged service entry-point smoke test timed out. " +
                "See $ServiceSmokeError."
            )
        }
        throw
    }
    if ($null -eq $ServiceSmoke.ExitCode) {
        throw "The packaged service entry-point smoke test completed without a readable exit code."
    }
    if ($ServiceSmoke.ExitCode -ne 0) {
        throw "The packaged service entry-point smoke test failed. See $ServiceSmokeError."
    }
    $ServiceSmokeResult = $null
    foreach ($Line in (Get-Content -LiteralPath $ServiceSmokeOutput -ErrorAction Stop)) {
        try {
            $Candidate = $Line | ConvertFrom-Json -ErrorAction Stop
            if ($Candidate.status -eq "ok") {
                $ServiceSmokeResult = $Candidate
            }
        }
        catch {
            continue
        }
    }
    if (
        $null -eq $ServiceSmokeResult -or
        $ServiceSmokeResult.role -ne "server" -or
        $ServiceSmokeResult.frozen -ne $true -or
        [string]$ServiceSmokeResult.app_version -ne [string]$AppVersion -or
        [string]$ServiceSmokeResult.api_version -ne [string]$ApiVersion -or
        [int]$ServiceSmokeResult.schema_version -ne [int]$SchemaVersion
    ) {
        throw "The packaged service entry-point smoke result is invalid. See $ServiceSmokeOutput."
    }
    & $ServerSetupExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged server setup utility failed its CLI smoke test."
    }
    $ServerHttpsSmokeHelper = Join-Path $PSScriptRoot "frozen_server_https_smoke.py"
    if (-not (Test-Path -LiteralPath $ServerHttpsSmokeHelper -PathType Leaf)) {
        throw "The frozen server HTTPS smoke helper is missing: $ServerHttpsSmokeHelper"
    }
    & $PythonPath -B $ServerHttpsSmokeHelper `
        --server-exe $ServerExe `
        --runtime-parent $ServerRuntime `
        --base-smoke-result $ServerSmokeOutput `
        --output $ServerHttpsSmokeOutput `
        --server-stdout $ServerHttpsSmokeStdout `
        --server-stderr $ServerHttpsSmokeStderr `
        --app-version $AppVersion `
        --api-version $ApiVersion `
        --schema-version $SchemaVersion
    if ($LASTEXITCODE -ne 0) {
        throw (
            "The packaged server failed its CA-verified HTTPS health smoke test. " +
            "See $ServerHttpsSmokeStdout and $ServerHttpsSmokeStderr."
        )
    }
    $ServerManifest = Join-Path $DistRoot "MissionLegalServer.provenance.json"
    New-PackageProvenance `
        -Role "server" `
        -PackageDir $ServerDir `
        -ManifestPath $ServerManifest `
        -SmokeResultPath $ServerHttpsSmokeOutput `
        -WindowsVersionExecutables @(
            "MissionLegalServer.exe",
            "MissionLegalServerSetup.exe",
            "MissionLegalService.exe"
        )
}

Write-Host "Mission Legal $AppVersion package build completed: $DistRoot"
