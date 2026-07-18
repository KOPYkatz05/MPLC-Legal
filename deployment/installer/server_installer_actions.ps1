[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Stop", "InstallOrUpdate", "StartAndVerify", "StartOnly", "Remove")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [Parameter(Mandatory = $true)]
    [string]$DataDir,
    [Parameter(Mandatory = $true)]
    [string]$AppVersion,
    [string]$StateFile,
    [ValidateRange(10, 300)]
    [int]$ServiceTimeoutSeconds = 90,
    [ValidateRange(10, 600)]
    [int]$HealthTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ServiceName = "MissionLegalServer"
$FirewallRuleName = "MissionLegalServerHTTPS"
$FirewallRuleDisplayName = "Mission Legal Server HTTPS"
$ServiceExe = [IO.Path]::GetFullPath((Join-Path $InstallDir "MissionLegalService.exe"))
$LogPath = Join-Path $DataDir "Logs\installer-service.log"

function Write-InstallerLog {
    param([string]$Message)

    $Line = "{0} {1}" -f [DateTimeOffset]::UtcNow.ToString("o"), $Message
    Write-Output $Line
    try {
        $Parent = Split-Path -Parent $LogPath
        New-Item -ItemType Directory -Force -Path $Parent | Out-Null
        Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    }
    catch {
        # Inno Setup also keeps a mandatory setup/uninstall log.  Do not mask a
        # service result just because the secondary ProgramData log failed.
    }
}

function Get-MissionLegalService {
    return Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
}

function Get-ServerConfiguration {
    $ConfigPath = Join-Path $DataDir "Configuration\server.json"
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Server configuration is unreadable at '$ConfigPath': $($_.Exception.Message)"
    }
}

function Get-ConfiguredServerPort {
    $Port = 8765
    $Configuration = Get-ServerConfiguration
    if ($null -ne $Configuration -and $null -ne $Configuration.port) {
        $Port = [int]$Configuration.port
    }
    if ($Port -lt 1 -or $Port -gt 65535) {
        throw "Configured server port is outside the valid TCP range: $Port"
    }
    return $Port
}

function Grant-SystemModifyAccess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $Resolved = [IO.Path]::GetFullPath(
        [Environment]::ExpandEnvironmentVariables($Path)
    )
    if (-not (Test-Path -LiteralPath $Resolved -PathType Container)) {
        throw "$Description directory does not exist: $Resolved"
    }

    $IcaclsExe = Join-Path $env:SystemRoot "System32\icacls.exe"
    & $IcaclsExe $Resolved "/grant:r" "*S-1-5-18:(OI)(CI)M" "/T" "/Q" |
        Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls.exe could not grant LocalSystem Modify access to $Description '$Resolved' (exit $LASTEXITCODE)."
    }

    $SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $Rules = (Get-Acl -LiteralPath $Resolved -ErrorAction Stop).GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    )
    $Modify = [Security.AccessControl.FileSystemRights]::Modify
    $Container = [Security.AccessControl.InheritanceFlags]::ContainerInherit
    $Object = [Security.AccessControl.InheritanceFlags]::ObjectInherit
    $AllowRules = @($Rules | Where-Object {
        $_.IdentityReference.Value -ceq $SystemSid.Value -and
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
        ($_.FileSystemRights -band $Modify) -eq $Modify -and
        ($_.InheritanceFlags -band $Container) -eq $Container -and
        ($_.InheritanceFlags -band $Object) -eq $Object
    })
    $DenyRules = @($Rules | Where-Object {
        $_.IdentityReference.Value -ceq $SystemSid.Value -and
        $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Deny -and
        ($_.FileSystemRights -band $Modify) -ne 0
    })
    if ($AllowRules.Count -lt 1 -or $DenyRules.Count -gt 0) {
        throw "LocalSystem Modify access could not be verified for $Description '$Resolved'."
    }
    Write-InstallerLog "Verified LocalSystem Modify access to $Description at $Resolved."
}

function Grant-ConfiguredStorageAccess {
    $Configuration = Get-ServerConfiguration
    if ($null -eq $Configuration) {
        Write-InstallerLog "Server storage is not configured yet; storage ACL checks are deferred to MissionLegalServerSetup.exe."
        return
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Configuration.mission_storage_root)) {
        Grant-SystemModifyAccess `
            -Path ([string]$Configuration.mission_storage_root) `
            -Description "mission-storage"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Configuration.onedrive_backup_dir)) {
        Grant-SystemModifyAccess `
            -Path ([string]$Configuration.onedrive_backup_dir) `
            -Description "mirrored-backup"
    }
}

function Set-MissionLegalFirewallRule {
    param([Parameter(Mandatory = $true)][int]$Port)

    Get-NetFirewallRule -Name $FirewallRuleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction Stop
    # Remove the pre-stable-name rule created by older setup scripts as well.
    Get-NetFirewallRule -DisplayName $FirewallRuleDisplayName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction Stop

    New-NetFirewallRule `
        -Name $FirewallRuleName `
        -DisplayName $FirewallRuleDisplayName `
        -Description "Allows authenticated Mission Legal clients to reach the main-computer HTTPS server on Private networks." `
        -Group "Mission Legal" `
        -Enabled True `
        -Direction Inbound `
        -Action Allow `
        -Profile Private `
        -Protocol TCP `
        -LocalPort $Port | Out-Null

    $Matches = @(Get-NetFirewallRule -DisplayName $FirewallRuleDisplayName -ErrorAction Stop)
    if ($Matches.Count -ne 1) {
        throw "Expected exactly one managed firewall rule; found $($Matches.Count)."
    }
    $Rule = $Matches[0]
    $PortFilters = @($Rule | Get-NetFirewallPortFilter -ErrorAction Stop)
    $Protocol = if ($PortFilters.Count -eq 1) { [string]$PortFilters[0].Protocol } else { "" }
    $LocalPort = if ($PortFilters.Count -eq 1) { [string]$PortFilters[0].LocalPort } else { "" }
    if (
        [string]$Rule.Name -cne $FirewallRuleName -or
        [string]$Rule.Enabled -cne "True" -or
        [string]$Rule.Direction -cne "Inbound" -or
        [string]$Rule.Action -cne "Allow" -or
        [string]$Rule.Profile -cne "Private" -or
        $PortFilters.Count -ne 1 -or
        $Protocol -notin @("TCP", "6") -or
        $LocalPort -cne $Port.ToString()
    ) {
        throw "The managed firewall rule did not match the required enabled, inbound, Private-only TCP policy."
    }
    Write-InstallerLog "Verified Private-only inbound TCP firewall rule on port $Port."
}

function Remove-MissionLegalFirewallRule {
    Get-NetFirewallRule -Name $FirewallRuleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction Stop
    Get-NetFirewallRule -DisplayName $FirewallRuleDisplayName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction Stop
    $Remaining = @(Get-NetFirewallRule -DisplayName $FirewallRuleDisplayName -ErrorAction SilentlyContinue)
    if ($Remaining.Count -ne 0) {
        throw "Managed Mission Legal Server firewall rules remain after removal."
    }
    Write-InstallerLog "Managed Mission Legal Server firewall rule is absent."
}

function Wait-ServiceStatus {
    param(
        [Parameter(Mandatory = $true)]
        [System.ServiceProcess.ServiceController]$Service,
        [Parameter(Mandatory = $true)]
        [System.ServiceProcess.ServiceControllerStatus]$Status
    )

    $Service.WaitForStatus($Status, [TimeSpan]::FromSeconds($ServiceTimeoutSeconds))
    $Service.Refresh()
    if ($Service.Status -ne $Status) {
        throw "Service $ServiceName did not reach state $Status."
    }
}

function Stop-MissionLegalService {
    param([switch]$RecordState)

    $Service = Get-MissionLegalService
    $InitialState = if ($null -eq $Service) { "absent" } else { $Service.Status.ToString().ToLowerInvariant() }
    if ($RecordState -and $StateFile) {
        $StateParent = Split-Path -Parent $StateFile
        if ($StateParent) {
            New-Item -ItemType Directory -Force -Path $StateParent | Out-Null
        }
        Set-Content -LiteralPath $StateFile -Value $InitialState -Encoding ASCII
    }

    if ($null -eq $Service) {
        Write-InstallerLog "Service is not installed; stop is not required."
        return
    }
    try {
        $Service.Refresh()
        if ($Service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
            Write-InstallerLog "Stopping service from state $($Service.Status)."
            Stop-Service -Name $ServiceName -Force -ErrorAction Stop
            Wait-ServiceStatus -Service $Service -Status ([System.ServiceProcess.ServiceControllerStatus]::Stopped)
        }
        Write-InstallerLog "Service is stopped."
    }
    finally {
        $Service.Dispose()
    }
}

function Get-RegisteredServiceExecutable {
    $Info = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
    $PathName = [Environment]::ExpandEnvironmentVariables([string]$Info.PathName).Trim()
    if ($PathName.StartsWith('"')) {
        $ClosingQuote = $PathName.IndexOf('"', 1)
        if ($ClosingQuote -lt 2) {
            throw "Service $ServiceName has an invalid executable path: $PathName"
        }
        return $PathName.Substring(1, $ClosingQuote - 1)
    }
    return $PathName.Split(' ')[0]
}

function Install-OrUpdateService {
    if (-not (Test-Path -LiteralPath $ServiceExe -PathType Leaf)) {
        throw "Packaged service executable is missing: $ServiceExe"
    }
    $Existing = Get-MissionLegalService
    if ($null -ne $Existing) {
        try {
            $Existing.Refresh()
            if ($Existing.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
                throw "Service must be stopped before its registration is updated."
            }
        }
        finally {
            $Existing.Dispose()
        }
    }

    # pywin32 getopt requires options before the install/update command.  Its
    # frozen command wrapper does not currently propagate every nonzero result,
    # so the SCM registration is independently inspected below.
    $Command = if ($null -eq (Get-MissionLegalService)) { "install" } else { "update" }
    Write-InstallerLog "Running service registration command: $Command."
    $Process = Start-Process `
        -FilePath $ServiceExe `
        -ArgumentList @("--startup", "delayed", $Command) `
        -WorkingDirectory $InstallDir `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "Service registration command exited with code $($Process.ExitCode)."
    }
    Start-Sleep -Milliseconds 500

    $Registered = Get-MissionLegalService
    if ($null -eq $Registered) {
        throw "Service registration did not create $ServiceName."
    }
    $Registered.Dispose()
    $RegisteredExe = [IO.Path]::GetFullPath((Get-RegisteredServiceExecutable))
    if (-not $RegisteredExe.Equals($ServiceExe, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Service executable mismatch. Expected '$ServiceExe', registered '$RegisteredExe'."
    }

    $Info = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
    if ([string]$Info.StartMode -ne "Auto") {
        throw "Service start mode is '$($Info.StartMode)' instead of automatic."
    }

    $ScExe = Join-Path $env:SystemRoot "System32\sc.exe"
    & $ScExe failure $ServiceName "reset=" 86400 "actions=" "restart/5000/restart/15000/restart/60000" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not configure service recovery actions (sc.exe exit $LASTEXITCODE)."
    }
    & $ScExe failureflag $ServiceName 1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not enable service recovery actions (sc.exe exit $LASTEXITCODE)."
    }
    Write-InstallerLog "Service registration and recovery policy verified at $ServiceExe."
}

function Start-ServiceAndWait {
    $Service = Get-MissionLegalService
    if ($null -eq $Service) {
        throw "Service $ServiceName is not installed."
    }
    try {
        $Service.Refresh()
        if ($Service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
            Write-InstallerLog "Starting service from state $($Service.Status)."
            Start-Service -Name $ServiceName -ErrorAction Stop
            Wait-ServiceStatus -Service $Service -Status ([System.ServiceProcess.ServiceControllerStatus]::Running)
        }
        Write-InstallerLog "Service is running."
    }
    finally {
        $Service.Dispose()
    }
}

function Get-HealthUri {
    $HostName = "127.0.0.1"
    $Port = Get-ConfiguredServerPort
    $Configuration = Get-ServerConfiguration
    if ($null -ne $Configuration) {
        if ($Configuration.host -and $Configuration.host -notin @("0.0.0.0", "::", "localhost")) {
            $HostName = [string]$Configuration.host
        }
    }
    if ($HostName.Contains(":")) {
        $HostName = "[$HostName]"
    }
    return "https://${HostName}:${Port}/health"
}

function Test-ServerHealth {
    $Uri = Get-HealthUri
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $PreviousCallback = [Net.ServicePointManager]::ServerCertificateValidationCallback
    try {
        # The request never leaves this machine.  The server uses its own local
        # CA, which is not placed in the machine trust store by design.
        [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        do {
            try {
                $Health = Invoke-RestMethod -Uri $Uri -Method Get -TimeoutSec 5 -ErrorAction Stop
                if ([string]$Health.status -ne "ok") {
                    throw "Health endpoint returned status '$($Health.status)'."
                }
                if ([string]$Health.app_version -ne $AppVersion) {
                    throw "Health endpoint reports version '$($Health.app_version)', expected '$AppVersion'."
                }
                Write-InstallerLog "Health verification passed at $Uri for version $AppVersion."
                return
            }
            catch {
                $LastError = $_.Exception.Message
                Start-Sleep -Seconds 2
            }
        } while ([DateTimeOffset]::UtcNow -lt $Deadline)
    }
    finally {
        [Net.ServicePointManager]::ServerCertificateValidationCallback = $PreviousCallback
    }
    throw "Server health verification timed out at $Uri. Last error: $LastError"
}

function Remove-MissionLegalService {
    Stop-MissionLegalService
    if ($null -eq (Get-MissionLegalService)) {
        Write-InstallerLog "Service is already absent."
        return
    }
    $ScExe = Join-Path $env:SystemRoot "System32\sc.exe"
    & $ScExe delete $ServiceName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not delete service $ServiceName (sc.exe exit $LASTEXITCODE)."
    }
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($ServiceTimeoutSeconds)
    do {
        $Service = Get-MissionLegalService
        if ($null -eq $Service) {
            Write-InstallerLog "Service was removed. ProgramData remains untouched."
            return
        }
        $Service.Dispose()
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $Deadline)
    throw "Service deletion did not finish before timeout."
}

Write-InstallerLog "Beginning installer service action '$Action' for version $AppVersion."
switch ($Action) {
    "Stop" {
        Stop-MissionLegalService -RecordState
    }
    "InstallOrUpdate" {
        Install-OrUpdateService
        Grant-ConfiguredStorageAccess
        Set-MissionLegalFirewallRule -Port (Get-ConfiguredServerPort)
    }
    "StartAndVerify" {
        Start-ServiceAndWait
        Test-ServerHealth
    }
    "StartOnly" {
        Start-ServiceAndWait
    }
    "Remove" {
        Remove-MissionLegalService
        Remove-MissionLegalFirewallRule
    }
}
Write-InstallerLog "Installer service action '$Action' completed."
