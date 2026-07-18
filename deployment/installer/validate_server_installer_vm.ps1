[CmdletBinding(DefaultParameterSetName = "Validate")]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaselineInstaller,
    [Parameter(Mandatory = $true)]
    [string]$UpgradeInstaller,
    [Parameter(Mandatory = $true)]
    [string]$BaselineVersion,
    [Parameter(Mandatory = $true)]
    [string]$UpgradeVersion,

    [Parameter(Mandatory = $true, ParameterSetName = "Validate")]
    [switch]$ValidateOnly,
    [Parameter(Mandatory = $true, ParameterSetName = "Execute")]
    [switch]$Execute,
    [Parameter(Mandatory = $true, ParameterSetName = "Execute")]
    [string]$DisposableVmConfirmation,

    [string]$WorkRoot = "$env:SystemDrive\MissionLegalInstallerValidation-VM",
    [ValidateRange(1024, 65535)]
    [int]$ValidationPort = 18765,
    [ValidateRange(120, 1800)]
    [int]$ProcessTimeoutSeconds = 900,
    [switch]$AllowUnsignedInstallers
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedConfirmation = "I CONFIRM THIS IS A DISPOSABLE MISSION LEGAL TEST VM"
$MarkerPurpose = "mission-legal-server-installer-validation"
$ServiceName = "MissionLegalServer"
$AppId = "{8A39739D-CBD2-4C38-AE5D-9DE7E69B29D5}_is1"
$DefaultServerPort = 8765
$ProgramFilesRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
$ProgramDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData)
$InstallDir = [IO.Path]::GetFullPath((Join-Path $ProgramFilesRoot "Mission Legal\Server"))
$ExpectedDataRoot = [IO.Path]::GetFullPath((Join-Path $ProgramDataRoot "MissionLegal"))
$MarkerDirectory = [IO.Path]::GetFullPath(
    (Join-Path $ProgramDataRoot "MissionLegalInstallerValidation")
)
$MarkerPath = Join-Path $MarkerDirectory "vm-consent.json"
$UninstallRegistryPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$script:Phases = New-Object System.Collections.Generic.List[object]
$script:ValidationContext = @{}
$script:OverallStatus = "not-started"
$script:FailureMessage = $null
$script:RunRoot = $null
$script:TranscriptStarted = $false

function Test-IsAdministrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-VirtualMachineIdentity {
    $Computer = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
    $Manufacturer = [string]$Computer.Manufacturer
    $Model = [string]$Computer.Model
    $Identity = "$Manufacturer $Model".ToLowerInvariant()
    $KnownVmPatterns = @(
        "virtual machine",
        "vmware",
        "virtualbox",
        "kvm",
        "qemu",
        "hvm domu",
        "parallels",
        "xen"
    )
    $Recognized = $false
    foreach ($Pattern in $KnownVmPatterns) {
        if ($Identity.Contains($Pattern)) {
            $Recognized = $true
            break
        }
    }
    return [pscustomobject]@{
        manufacturer = $Manufacturer
        model = $Model
        recognized = $Recognized
    }
}

function Get-CoreVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if ($Value -notmatch '^(\d+)\.(\d+)\.(\d+)(?:[.+-].*)?$') {
        throw "$Description must start with three numeric components: $Value"
    }
    return [version]::new(
        [int]$Matches[1],
        [int]$Matches[2],
        [int]$Matches[3]
    )
}

function Get-ArtifactEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $Resolved = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $Resolved -PathType Leaf)) {
        throw "$Description was not found: $Resolved"
    }
    if ([IO.Path]::GetExtension($Resolved) -ine ".exe") {
        throw "$Description must be an .exe file: $Resolved"
    }

    $ExpectedCore = Get-CoreVersion $ExpectedVersion "$Description expected version"
    $VersionInfo = (Get-Item -LiteralPath $Resolved).VersionInfo
    $ProductVersion = [string]$VersionInfo.ProductVersion
    if ($ProductVersion -notmatch '(\d+)\.(\d+)\.(\d+)') {
        throw "$Description has no readable three-part ProductVersion: $Resolved"
    }
    $ProductCore = [version]::new(
        [int]$Matches[1],
        [int]$Matches[2],
        [int]$Matches[3]
    )
    if ($ProductCore -ne $ExpectedCore) {
        throw (
            "$Description ProductVersion '$ProductVersion' does not match " +
            "expected version '$ExpectedVersion'."
        )
    }

    $Signature = Get-AuthenticodeSignature -LiteralPath $Resolved
    $Signer = $null
    if ($null -ne $Signature.SignerCertificate) {
        $Signer = [string]$Signature.SignerCertificate.Subject
    }
    return [pscustomobject]@{
        path = $Resolved
        expected_version = $ExpectedVersion
        product_version = $ProductVersion
        sha256 = (Get-FileHash -LiteralPath $Resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        size = (Get-Item -LiteralPath $Resolved).Length
        signature_status = [string]$Signature.Status
        signer = $Signer
    }
}

function Get-MachineState {
    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $ServiceState = "absent"
    if ($null -ne $Service) {
        try {
            $ServiceState = $Service.Status.ToString()
        }
        finally {
            $Service.Dispose()
        }
    }
    $FirewallRules = @(
        @(
            Get-NetFirewallRule -Name "MissionLegalServerHTTPS" -ErrorAction SilentlyContinue
            Get-NetFirewallRule -DisplayName "Mission Legal Server HTTPS" -ErrorAction SilentlyContinue
        ) | Sort-Object Name -Unique
    )
    return [pscustomobject]@{
        service = $ServiceState
        uninstall_registration_exists = (Test-Path -LiteralPath $UninstallRegistryPath)
        install_directory_exists = (Test-Path -LiteralPath $InstallDir)
        data_directory_exists = (Test-Path -LiteralPath $ExpectedDataRoot)
        firewall_rule_count = $FirewallRules.Count
    }
}

function Assert-SafeWorkRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$RequireAbsent
    )

    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($Resolved.StartsWith('\\')) {
        throw "WorkRoot must be on a local fixed-volume path: $Resolved"
    }
    $VolumeRoot = [IO.Path]::GetPathRoot($Resolved)
    $Drive = [IO.DriveInfo]::new($VolumeRoot)
    if ($Drive.DriveType -ne [IO.DriveType]::Fixed) {
        throw "WorkRoot must be on a fixed local volume: $Resolved"
    }
    $Parent = [IO.Directory]::GetParent($Resolved)
    if ($null -eq $Parent -or -not $Parent.FullName.TrimEnd('\').Equals(
        $VolumeRoot.TrimEnd('\'),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "WorkRoot must be an initially absent top-level directory: $Resolved"
    }
    $Leaf = [IO.Path]::GetFileName($Resolved)
    if ($Leaf -notmatch '^MissionLegalInstallerValidation-[A-Za-z0-9_-]{2,64}$') {
        throw (
            "WorkRoot leaf must use the dedicated MissionLegalInstallerValidation-* " +
            "name: $Resolved"
        )
    }
    $ForbiddenRoots = @(
        $env:SystemRoot,
        $ProgramFilesRoot,
        [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86),
        $ProgramDataRoot,
        $env:USERPROFILE,
        [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile),
        [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData),
        [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
    ) | Where-Object { $_ }
    foreach ($Forbidden in $ForbiddenRoots) {
        $ForbiddenFull = [IO.Path]::GetFullPath([string]$Forbidden).TrimEnd('\')
        if (
            $Resolved.Equals($ForbiddenFull, [StringComparison]::OrdinalIgnoreCase) -or
            $Resolved.StartsWith($ForbiddenFull + '\', [StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "WorkRoot cannot be under Windows, application, ProgramData, or user-profile paths: $Resolved"
        }
    }
    Assert-NoReparseAncestors $Resolved
    if ($RequireAbsent -and (Test-Path -LiteralPath $Resolved)) {
        throw "WorkRoot must be absent at the beginning of an execution run: $Resolved"
    }
    return $Resolved
}

function Assert-NoReparseAncestors {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Current = [IO.Path]::GetFullPath($Path)
    while ($Current) {
        if (Test-Path -LiteralPath $Current) {
            $Item = Get-Item -LiteralPath $Current -Force -ErrorAction Stop
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Validation path contains a reparse point: $Current"
            }
        }
        $Parent = [IO.Directory]::GetParent($Current)
        if ($null -eq $Parent -or $Parent.FullName -ieq $Current) {
            break
        }
        $Current = $Parent.FullName
    }
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Child,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $ParentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $ChildFull = [IO.Path]::GetFullPath($Child)
    if (-not $ChildFull.StartsWith($ParentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description must stay under '$($ParentFull.TrimEnd('\'))': $ChildFull"
    }
    return $ChildFull
}

function Assert-NewScenarioPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $Resolved = Assert-ChildPath $script:RunRoot $Path $Description
    Assert-NoReparseAncestors $Resolved
    if (Test-Path -LiteralPath $Resolved) {
        throw "$Description must be initially absent: $Resolved"
    }
    return $Resolved
}

function Assert-RestrictedValidationAcl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $AdministratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
    $SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if (-not $Acl.AreAccessRulesProtected) {
        throw "Validation control-path ACL inheritance is not protected: $Path"
    }
    $Owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($Owner.Value -notin @($AdministratorsSid.Value, $SystemSid.Value)) {
        throw "Validation control-path owner is not Administrators or LocalSystem: $($Owner.Value)"
    }
    $Rules = @($Acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ))
    foreach ($Rule in $Rules) {
        if (
            $Rule.IdentityReference.Value -notin @($AdministratorsSid.Value, $SystemSid.Value) -or
            $Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow
        ) {
            throw "Validation control-path ACL grants access outside Administrators/LocalSystem."
        }
    }
    foreach ($Sid in @($AdministratorsSid, $SystemSid)) {
        $Full = @($Rules | Where-Object {
            $_.IdentityReference.Value -ceq $Sid.Value -and
            ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
                [Security.AccessControl.FileSystemRights]::FullControl
        })
        if ($Full.Count -lt 1) {
            throw "Validation control-path ACL is missing FullControl for $($Sid.Value)."
        }
    }
}

function Assert-ExecutionConsent {
    if (-not $Execute) {
        throw "Mutating validation requires the explicit -Execute switch."
    }
    if ($DisposableVmConfirmation -cne $ExpectedConfirmation) {
        throw "The disposable-VM confirmation text did not match exactly."
    }
    if (-not (Test-IsAdministrator)) {
        throw "Run the validation from an elevated Windows PowerShell session."
    }
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        throw "Run the validation from 64-bit Windows PowerShell."
    }

    $VmIdentity = Get-VirtualMachineIdentity
    if (-not $VmIdentity.recognized) {
        throw (
            "This machine was not recognized as a virtual machine " +
            "(manufacturer '$($VmIdentity.manufacturer)', model '$($VmIdentity.model)')."
        )
    }

    $ResolvedMarker = [IO.Path]::GetFullPath($MarkerPath)
    $ExpectedMarker = [IO.Path]::GetFullPath(
        (Join-Path $ProgramDataRoot "MissionLegalInstallerValidation\vm-consent.json")
    )
    if (-not $ResolvedMarker.Equals($ExpectedMarker, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The validation marker must use the dedicated ProgramData path: $ExpectedMarker"
    }
    if (-not (Test-Path -LiteralPath $ResolvedMarker -PathType Leaf)) {
        throw (
            "The machine-bound disposable-VM marker is missing: $ResolvedMarker. " +
            "Create it with new_server_installer_vm_marker.ps1 inside the clean VM."
        )
    }
    Assert-NoReparseAncestors $MarkerDirectory
    Assert-NoReparseAncestors $ResolvedMarker
    Assert-RestrictedValidationAcl $MarkerDirectory
    Assert-RestrictedValidationAcl $ResolvedMarker
    try {
        $Marker = Get-Content -LiteralPath $ResolvedMarker -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "The disposable-VM marker is unreadable: $($_.Exception.Message)"
    }
    if ([int]$Marker.schema_version -ne 1 -or [string]$Marker.purpose -cne $MarkerPurpose) {
        throw "The disposable-VM marker has the wrong schema or purpose."
    }
    $MachineGuid = (
        Get-ItemPropertyValue `
            -LiteralPath "HKLM:\SOFTWARE\Microsoft\Cryptography" `
            -Name "MachineGuid" `
            -ErrorAction Stop
    ).ToString()
    if ([string]$Marker.machine_guid -cne $MachineGuid) {
        throw "The disposable-VM marker belongs to another Windows installation."
    }
    if ([string]$Marker.computer_name -cne [Environment]::MachineName) {
        throw "The disposable-VM marker belongs to another computer name."
    }
    $Created = [DateTimeOffset]::Parse([string]$Marker.created_at_utc)
    $Expires = [DateTimeOffset]::Parse([string]$Marker.expires_at_utc)
    $Now = [DateTimeOffset]::UtcNow
    if ($Created -gt $Now.AddMinutes(5)) {
        throw "The disposable-VM marker creation time is in the future."
    }
    if ($Expires -le $Now) {
        throw "The disposable-VM marker expired at $($Expires.ToString('o'))."
    }
    if (($Expires - $Created).TotalHours -gt 24.1) {
        throw "The disposable-VM marker is valid for longer than the 24-hour maximum."
    }
    return [pscustomobject]@{
        marker_path = $ResolvedMarker
        marker_expires_at_utc = $Expires.ToString("o")
        virtualization = $VmIdentity
    }
}

function ConvertTo-WindowsCommandLineArgument {
    param([AllowEmptyString()][string]$Value)

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }
    $Builder = New-Object Text.StringBuilder
    [void]$Builder.Append('"')
    $Backslashes = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq '\') {
            $Backslashes += 1
            continue
        }
        if ($Character -eq '"') {
            [void]$Builder.Append(('\' * (($Backslashes * 2) + 1)))
            [void]$Builder.Append('"')
            $Backslashes = 0
            continue
        }
        if ($Backslashes -gt 0) {
            [void]$Builder.Append(('\' * $Backslashes))
            $Backslashes = 0
        }
        [void]$Builder.Append($Character)
    }
    if ($Backslashes -gt 0) {
        [void]$Builder.Append(('\' * ($Backslashes * 2)))
    }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

function Invoke-NativeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$OutputPath,
        [int]$TimeoutSeconds = $ProcessTimeoutSeconds
    )

    $StartInfo = New-Object Diagnostics.ProcessStartInfo
    $StartInfo.FileName = [IO.Path]::GetFullPath($FilePath)
    $StartInfo.Arguments = (($Arguments | ForEach-Object {
        ConvertTo-WindowsCommandLineArgument ([string]$_)
    }) -join ' ')
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $Process = New-Object Diagnostics.Process
    $Process.StartInfo = $StartInfo

    Write-Host "Starting $([IO.Path]::GetFileName($StartInfo.FileName))"
    if (-not $Process.Start()) {
        throw "Could not start $($StartInfo.FileName)."
    }
    $StdOutTask = $Process.StandardOutput.ReadToEndAsync()
    $StdErrTask = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
        try {
            $Process.Kill()
        }
        catch {
        }
        throw "$($StartInfo.FileName) exceeded the $TimeoutSeconds-second timeout."
    }
    $StdOut = $StdOutTask.Result
    $StdErr = $StdErrTask.Result
    $ExitCode = $Process.ExitCode
    $Process.Dispose()

    if ($OutputPath) {
        @(
            "exit_code=$ExitCode"
            "--- stdout ---"
            $StdOut
            "--- stderr ---"
            $StdErr
        ) | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    }
    Write-Host "Process exit code: $ExitCode"
    return [pscustomobject]@{
        ExitCode = $ExitCode
        StdOut = $StdOut
        StdErr = $StdErr
    }
}

function Invoke-ValidationPhase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $Started = [DateTimeOffset]::UtcNow
    Write-Host ""
    Write-Host "[$Name] started"
    try {
        $Evidence = & $Action
        $Finished = [DateTimeOffset]::UtcNow
        $script:Phases.Add([pscustomobject]@{
            name = $Name
            status = "passed"
            started_at_utc = $Started.ToString("o")
            finished_at_utc = $Finished.ToString("o")
            duration_seconds = [Math]::Round(($Finished - $Started).TotalSeconds, 3)
            evidence = $Evidence
            error = $null
        })
        Write-Host "[$Name] passed"
        return $Evidence
    }
    catch {
        $Finished = [DateTimeOffset]::UtcNow
        $script:Phases.Add([pscustomobject]@{
            name = $Name
            status = "failed"
            started_at_utc = $Started.ToString("o")
            finished_at_utc = $Finished.ToString("o")
            duration_seconds = [Math]::Round(($Finished - $Started).TotalSeconds, 3)
            evidence = $null
            error = $_.Exception.Message
        })
        Write-Host "[$Name] failed: $($_.Exception.Message)"
        throw
    }
}

function Assert-TcpPortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)

    $Listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try {
        $Listener.Start()
    }
    catch {
        throw "TCP port $Port is already in use on loopback."
    }
    finally {
        try {
            $Listener.Stop()
        }
        catch {
        }
    }
}

function Get-PrivateNetworkEvidence {
    $Profiles = @(Get-NetConnectionProfile -ErrorAction Stop | Where-Object {
        [string]$_.NetworkCategory -ceq "Private" -and
        [string]$_.IPv4Connectivity -notin @("Disconnected", "NoTraffic")
    })
    foreach ($Profile in $Profiles) {
        $Addresses = @(Get-NetIPAddress `
            -InterfaceIndex $Profile.InterfaceIndex `
            -AddressFamily IPv4 `
            -ErrorAction SilentlyContinue | Where-Object {
                $_.IPAddress -ne "127.0.0.1" -and
                -not $_.IPAddress.StartsWith("169.254.")
            })
        if ($Addresses.Count -gt 0) {
            return [pscustomobject]@{
                interface_alias = [string]$Profile.InterfaceAlias
                interface_index = [int]$Profile.InterfaceIndex
                network_category = [string]$Profile.NetworkCategory
                ipv4_connectivity = [string]$Profile.IPv4Connectivity
                ipv4_addresses = @($Addresses | ForEach-Object { [string]$_.IPAddress })
            }
        }
    }
    throw (
        "The VM has no connected Private-profile IPv4 interface. " +
        "The Private-only firewall rule could not provide client reachability."
    )
}

function Get-RegisteredServiceExecutable {
    $Info = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
    $PathName = [Environment]::ExpandEnvironmentVariables([string]$Info.PathName).Trim()
    if ($PathName.StartsWith('"')) {
        $ClosingQuote = $PathName.IndexOf('"', 1)
        if ($ClosingQuote -lt 2) {
            throw "The registered service has an invalid path: $PathName"
        }
        return $PathName.Substring(1, $ClosingQuote - 1)
    }
    return $PathName.Split(' ')[0]
}

function Assert-ServiceRegistration {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedVersion,
        [Parameter(Mandatory = $true)][string]$ExpectedState
    )

    Assert-NoReparseAncestors $InstallDir
    $Service = Get-Service -Name $ServiceName -ErrorAction Stop
    try {
        $Service.Refresh()
        if ($Service.Status.ToString() -ine $ExpectedState) {
            throw "Service state is '$($Service.Status)', expected '$ExpectedState'."
        }
    }
    finally {
        $Service.Dispose()
    }
    $RegisteredExe = [IO.Path]::GetFullPath((Get-RegisteredServiceExecutable))
    $ExpectedExe = [IO.Path]::GetFullPath((Join-Path $InstallDir "MissionLegalService.exe"))
    if (-not $RegisteredExe.Equals($ExpectedExe, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Service executable is '$RegisteredExe', expected '$ExpectedExe'."
    }
    $Info = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
    if ([string]$Info.StartMode -ne "Auto") {
        throw "Service start mode is '$($Info.StartMode)', expected automatic."
    }
    if ([string]$Info.StartName -cne "LocalSystem") {
        throw "Service account is '$($Info.StartName)', expected LocalSystem."
    }
    $ServiceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
    if ([int](Get-ItemPropertyValue -LiteralPath $ServiceKey -Name "DelayedAutoStart" -ErrorAction Stop) -ne 1) {
        throw "Service is not configured for delayed automatic start."
    }
    if (-not (Get-ItemPropertyValue -LiteralPath $ServiceKey -Name "FailureActions" -ErrorAction Stop)) {
        throw "Service recovery actions are missing."
    }
    if ([int](Get-ItemPropertyValue -LiteralPath $ServiceKey -Name "FailureActionsOnNonCrashFailures" -ErrorAction Stop) -ne 1) {
        throw "Service non-crash recovery actions are not enabled."
    }
    $Installed = Get-ItemProperty -LiteralPath $UninstallRegistryPath -ErrorAction Stop
    if ([string]$Installed.DisplayVersion -cne $ExpectedVersion) {
        throw "Installed version is '$($Installed.DisplayVersion)', expected '$ExpectedVersion'."
    }
    $RegistryInstallDir = [IO.Path]::GetFullPath([string]$Installed.InstallLocation).TrimEnd('\')
    if (-not $RegistryInstallDir.Equals($InstallDir.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Installer registered '$RegistryInstallDir', expected '$InstallDir'."
    }
}

function Assert-DeferredFirstInstallState {
    param([Parameter(Mandatory = $true)][string]$ExpectedVersion)

    Assert-NoReparseAncestors $InstallDir
    foreach ($Name in @(
        "MissionLegalServer.exe",
        "MissionLegalServerSetup.exe",
        "MissionLegalService.exe"
    )) {
        $Path = Join-Path $InstallDir $Name
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Deferred first install is missing packaged binary: $Path"
        }
        Assert-NoReparseAncestors $Path
    }
    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($null -ne $Service) {
        $State = $Service.Status.ToString()
        $Service.Dispose()
        throw "Deferred first install unexpectedly registered service $ServiceName ($State)."
    }
    Assert-NoServerFirewallRule
    foreach ($Persistent in @(
        (Join-Path $ExpectedDataRoot "app.db"),
        (Join-Path $ExpectedDataRoot "Configuration\server.json")
    )) {
        if (Test-Path -LiteralPath $Persistent) {
            throw "Deferred first install unexpectedly created configured server state: $Persistent"
        }
    }
    $Installed = Get-ItemProperty -LiteralPath $UninstallRegistryPath -ErrorAction Stop
    if ([string]$Installed.DisplayVersion -cne $ExpectedVersion) {
        throw "Installed version is '$($Installed.DisplayVersion)', expected '$ExpectedVersion'."
    }
    $RegistryInstallDir = [IO.Path]::GetFullPath([string]$Installed.InstallLocation).TrimEnd('\')
    if (-not $RegistryInstallDir.Equals($InstallDir.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Deferred installer registered '$RegistryInstallDir', expected '$InstallDir'."
    }
    return [pscustomobject]@{
        installed_version = $ExpectedVersion
        service = "absent"
        firewall_rule_count = 0
        database = "absent"
        server_configuration = "absent"
    }
}

function Get-ServerFirewallRuleEvidence {
    param([int]$Port = -1)

    $ExpectedExe = [IO.Path]::GetFullPath((Join-Path $InstallDir "MissionLegalService.exe"))
    $Evidence = @()
    $ManagedRules = @(
        @(
            Get-NetFirewallRule -Name "MissionLegalServerHTTPS" -ErrorAction SilentlyContinue
            Get-NetFirewallRule -DisplayName "Mission Legal Server HTTPS" -ErrorAction SilentlyContinue
        ) | Sort-Object Name -Unique
    )
    foreach ($Rule in $ManagedRules) {
        $Application = $Rule | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue
        $ServiceFilter = $Rule | Get-NetFirewallServiceFilter -ErrorAction SilentlyContinue
        $PortFilter = $Rule | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
        $ApplicationPath = ""
        $ServiceTarget = ""
        $Protocol = ""
        $LocalPort = ""
        if ($null -ne $Application) {
            $ApplicationPath = [string]$Application.Program
        }
        if ($null -ne $ServiceFilter) {
            $ServiceTarget = [string]$ServiceFilter.Service
        }
        if ($null -ne $PortFilter) {
            $Protocol = [string]$PortFilter.Protocol
            $LocalPort = [string]$PortFilter.LocalPort
        }
        if ($ApplicationPath -and $ApplicationPath -notin @("Any", "System")) {
            $ApplicationPath = [Environment]::ExpandEnvironmentVariables($ApplicationPath)
            try {
                $ApplicationPath = [IO.Path]::GetFullPath($ApplicationPath)
            }
            catch {
            }
        }
        $TargetsServer = (
            ([string]$Rule.Name -ceq "MissionLegalServerHTTPS") -and
            ([string]$Rule.DisplayName -ceq "Mission Legal Server HTTPS")
        )
        if (-not $TargetsServer) {
            continue
        }
        if ($Port -ge 0 -and $LocalPort -cne $Port.ToString()) {
            continue
        }
        $Evidence += [pscustomobject]@{
            name = [string]$Rule.Name
            display_name = [string]$Rule.DisplayName
            enabled = [string]$Rule.Enabled
            direction = [string]$Rule.Direction
            action = [string]$Rule.Action
            profile = [string]$Rule.Profile
            protocol = $Protocol
            local_port = $LocalPort
            program = $ApplicationPath
            service = $ServiceTarget
        }
    }
    return @($Evidence)
}

function Assert-PrivateServerFirewallRule {
    param([Parameter(Mandatory = $true)][int]$Port)

    $AllProductRules = @(Get-ServerFirewallRuleEvidence)
    $Candidates = @($AllProductRules | Where-Object {
        $_.local_port -ceq $Port.ToString()
    })
    $Valid = @($Candidates | Where-Object {
        $_.enabled -ceq "True" -and
        $_.direction -ceq "Inbound" -and
        $_.action -ceq "Allow" -and
        $_.protocol -in @("TCP", "6") -and
        $_.profile -match 'Private' -and
        $_.profile -notmatch 'Public|Domain|Any'
    })
    if ($AllProductRules.Count -ne 1 -or $Candidates.Count -ne 1 -or $Valid.Count -ne 1) {
        throw (
            "Expected exactly one product firewall rule and it must be enabled, inbound, " +
            "Private-only TCP for $ServiceName on port $Port. Found " +
            "$($AllProductRules.Count) product rule(s), $($Candidates.Count) on the port, " +
            "and $($Valid.Count) valid rule(s)."
        )
    }
    return $Valid[0]
}

function Assert-NoServerFirewallRule {
    param([int]$Port = -1)

    $Candidates = @(Get-ServerFirewallRuleEvidence -Port $Port)
    if ($Candidates.Count -gt 0) {
        $PortDescription = if ($Port -lt 0) { "any port" } else { "port $Port" }
        throw "Mission Legal Server firewall rules remain for $PortDescription after uninstall."
    }
}

function Wait-ServiceCreatedMirrorBackup {
    param(
        [Parameter(Mandatory = $true)][DateTimeOffset]$NotBefore,
        [Parameter(Mandatory = $true)][string]$BackupRoot,
        [int]$TimeoutSeconds = 120
    )

    $ResolvedBackupRoot = Assert-ChildPath $script:RunRoot $BackupRoot "Mirror backup root"
    Assert-NoReparseAncestors $ResolvedBackupRoot
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $LastError = "No service-created mirrored backup appeared."
    do {
        foreach ($MetadataPath in @(Get-ChildItem -LiteralPath $ResolvedBackupRoot -Filter "mission-legal_*.json" -File -ErrorAction SilentlyContinue)) {
            try {
                $Metadata = Get-Content -LiteralPath $MetadataPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                $Created = [DateTimeOffset]::Parse([string]$Metadata.created_at)
                if (
                    $Created -ge $NotBefore.AddSeconds(-2) -and
                    [string]$Metadata.reason -in @("pre-migration", "daily")
                ) {
                    $DatabasePath = [IO.Path]::ChangeExtension($MetadataPath.FullName, ".db")
                    if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) {
                        throw "Mirrored backup database is missing: $DatabasePath"
                    }
                    $ActualHash = (Get-FileHash -LiteralPath $DatabasePath -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($ActualHash -cne ([string]$Metadata.sha256).ToLowerInvariant()) {
                        throw "Mirrored backup SHA-256 does not match: $DatabasePath"
                    }
                    return [pscustomobject]@{
                        path = $DatabasePath
                        metadata_path = $MetadataPath.FullName
                        reason = [string]$Metadata.reason
                        sha256 = $ActualHash
                        created_at_utc = $Created.ToString("o")
                    }
                }
            }
            catch {
                $LastError = $_.Exception.Message
            }
        }
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $Deadline)
    throw "LocalSystem did not create a verified mirror backup. Last error: $LastError"
}

function Invoke-LocalRestMethod {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [object]$Body,
        [hashtable]$Headers
    )

    $PreviousCallback = [Net.ServicePointManager]::ServerCertificateValidationCallback
    try {
        [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $Parameters = @{
            Uri = $Uri
            Method = $Method
            TimeoutSec = 10
            ErrorAction = "Stop"
        }
        if ($null -ne $Body) {
            $Parameters.ContentType = "application/json"
            $Parameters.Body = $Body | ConvertTo-Json -Depth 8 -Compress
        }
        if ($null -ne $Headers) {
            $Parameters.Headers = $Headers
        }
        return Invoke-RestMethod @Parameters
    }
    finally {
        [Net.ServicePointManager]::ServerCertificateValidationCallback = $PreviousCallback
    }
}

function Wait-ServerHealth {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion,
        [int]$TimeoutSeconds = 120
    )

    $Uri = "https://127.0.0.1:$Port/health"
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $LastError = "No response was received."
    do {
        try {
            $Health = Invoke-LocalRestMethod -Method GET -Uri $Uri
            if ([string]$Health.status -cne "ok") {
                throw "Health status was '$($Health.status)'."
            }
            if ([string]$Health.app_version -cne $ExpectedVersion) {
                throw "Health version was '$($Health.app_version)', expected '$ExpectedVersion'."
            }
            return $Health
        }
        catch {
            $LastError = $_.Exception.Message
            Start-Sleep -Seconds 2
        }
    } while ([DateTimeOffset]::UtcNow -lt $Deadline)
    throw "Server health failed at $Uri. Last error: $LastError"
}

function Wait-ServerHealthSurfaces {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    $Loopback = Wait-ServerHealth `
        -Port $Port `
        -ExpectedVersion $ExpectedVersion
    $PrivateAddresses = @($script:ValidationContext["PrivateNetwork"].ipv4_addresses)
    if ($PrivateAddresses.Count -lt 1) {
        throw "No selected Private-profile IPv4 address is available for health verification."
    }
    $PrivateAddress = [string]$PrivateAddresses[0]
    $Uri = "https://${PrivateAddress}:$Port/health"
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds(120)
    $LastError = "No response was received."
    do {
        try {
            $Health = Invoke-LocalRestMethod -Method GET -Uri $Uri
            if (
                [string]$Health.status -cne "ok" -or
                [string]$Health.app_version -cne $ExpectedVersion
            ) {
                throw (
                    "Private-address health returned status '$($Health.status)' " +
                    "and version '$($Health.app_version)'."
                )
            }
            return [pscustomobject]@{
                loopback_uri = "https://127.0.0.1:$Port/health"
                private_uri = $Uri
                app_version = [string]$Health.app_version
                schema_version = $Health.schema_version
                loopback_status = [string]$Loopback.status
                private_status = [string]$Health.status
            }
        }
        catch {
            $LastError = $_.Exception.Message
            Start-Sleep -Seconds 2
        }
    } while ([DateTimeOffset]::UtcNow -lt $Deadline)
    throw "Server health failed through selected Private IPv4 endpoint $Uri. Last error: $LastError"
}

function Assert-SentinelApiRecord {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][hashtable]$Headers,
        [Parameter(Mandatory = $true)][string]$MissionaryCode,
        [Parameter(Mandatory = $true)][string]$PassportNumber
    )

    $Response = Invoke-LocalRestMethod `
        -Method GET `
        -Uri "https://127.0.0.1:$Port/v1/missionaries?status_filter=ACTIVE" `
        -Headers $Headers
    $Match = @($Response.items | Where-Object {
        [string]$_.missionary_code -ceq $MissionaryCode -and
        [string]$_.passport_number -ceq $PassportNumber
    })
    if ($Match.Count -ne 1) {
        throw "The seeded API record was not preserved exactly once."
    }
    return $Match[0]
}

function Test-LocalSystemMissionRootRelocation {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][hashtable]$Headers,
        [Parameter(Mandatory = $true)][int]$MissionaryId,
        [Parameter(Mandatory = $true)][string]$ExpectedRoot,
        [Parameter(Mandatory = $true)][string]$RunToken
    )

    $BaseUri = "https://127.0.0.1:$Port"
    $Before = Invoke-LocalRestMethod `
        -Method GET `
        -Uri "$BaseUri/v1/missionaries/$MissionaryId" `
        -Headers $Headers
    $OriginalFolder = Assert-ChildPath $ExpectedRoot ([string]$Before.folder_path) "Missionary folder"
    if (-not (Test-Path -LiteralPath $OriginalFolder -PathType Container)) {
        throw "LocalSystem did not create the configured missionary folder: $OriginalFolder"
    }

    $SentinelPath = Join-Path $OriginalFolder "relocation-sentinel-$RunToken.txt"
    "Harness-created mission-root relocation sentinel $RunToken" |
        Set-Content -LiteralPath $SentinelPath -Encoding UTF8
    $ExpectedHash = (Get-FileHash -LiteralPath $SentinelPath -Algorithm SHA256).Hash.ToLowerInvariant()

    $Archive = Invoke-LocalRestMethod `
        -Method POST `
        -Uri "$BaseUri/v1/missionaries/$MissionaryId/archive" `
        -Headers $Headers `
        -Body @{ reason = "installer LocalSystem validation" }
    if (-not [bool]$Archive.archived) {
        throw "The LocalSystem service did not archive the validation folder."
    }
    $Archived = Invoke-LocalRestMethod `
        -Method GET `
        -Uri "$BaseUri/v1/missionaries/$MissionaryId" `
        -Headers $Headers
    $ArchivedFolder = Assert-ChildPath $ExpectedRoot ([string]$Archived.folder_path) "Archived missionary folder"
    $ArchivedSentinel = Join-Path $ArchivedFolder ([IO.Path]::GetFileName($SentinelPath))
    if (-not (Test-Path -LiteralPath $ArchivedSentinel -PathType Leaf)) {
        throw "The sentinel did not move with the LocalSystem archive operation."
    }
    if ((Get-FileHash -LiteralPath $ArchivedSentinel -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedHash) {
        throw "The sentinel changed during the LocalSystem archive operation."
    }

    $Restore = Invoke-LocalRestMethod `
        -Method POST `
        -Uri "$BaseUri/v1/missionaries/$MissionaryId/restore" `
        -Headers $Headers
    if (-not [bool]$Restore.restored) {
        throw "The LocalSystem service did not restore the validation folder."
    }
    $Restored = Invoke-LocalRestMethod `
        -Method GET `
        -Uri "$BaseUri/v1/missionaries/$MissionaryId" `
        -Headers $Headers
    $RestoredFolder = Assert-ChildPath $ExpectedRoot ([string]$Restored.folder_path) "Restored missionary folder"
    $RestoredSentinel = Join-Path $RestoredFolder ([IO.Path]::GetFileName($SentinelPath))
    if (-not (Test-Path -LiteralPath $RestoredSentinel -PathType Leaf)) {
        throw "The sentinel did not return with the LocalSystem restore operation."
    }
    if ((Get-FileHash -LiteralPath $RestoredSentinel -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedHash) {
        throw "The sentinel changed during the LocalSystem restore operation."
    }
    return [pscustomobject]@{
        service_account = "LocalSystem"
        folder_creation_and_relocation = $true
        content_was_created_by_harness = $true
        sentinel_content_unchanged = $true
        original_folder = $OriginalFolder
        archived_folder = $ArchivedFolder
        restored_folder = $RestoredFolder
        sentinel_path = $RestoredSentinel
        sentinel_sha256 = $ExpectedHash
    }
}

function Get-UninstallerPath {
    $Installed = Get-ItemProperty -LiteralPath $UninstallRegistryPath -ErrorAction Stop
    $Command = [string]$Installed.UninstallString
    if ($Command.StartsWith('"')) {
        $ClosingQuote = $Command.IndexOf('"', 1)
        if ($ClosingQuote -lt 2) {
            throw "The uninstaller registration is invalid: $Command"
        }
        $Path = $Command.Substring(1, $ClosingQuote - 1)
    }
    elseif ($Command -match '^(.+?\.exe)(?:\s|$)') {
        $Path = $Matches[1]
    }
    else {
        throw "The uninstaller path could not be parsed: $Command"
    }
    $Resolved = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $Resolved -PathType Leaf)) {
        throw "The registered uninstaller is missing: $Resolved"
    }
    Assert-NoReparseAncestors $InstallDir
    Assert-NoReparseAncestors $Resolved
    $UninstallerParent = [IO.Directory]::GetParent($Resolved)
    if (
        $null -eq $UninstallerParent -or
        -not $UninstallerParent.FullName.TrimEnd('\').Equals(
            $InstallDir.TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetFileName($Resolved) -notmatch '^unins\d+\.exe$'
    ) {
        throw "The registered uninstaller is not an exact child of InstallDir: $Resolved"
    }
    return $Resolved
}

function Wait-ServiceAbsent {
    param([int]$TimeoutSeconds = 90)

    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $Service) {
            return
        }
        $Service.Dispose()
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $Deadline)
    throw "Service $ServiceName was not removed before timeout."
}

function Assert-ServerUninstalled {
    Wait-ServiceAbsent
    if (Test-Path -LiteralPath $UninstallRegistryPath) {
        throw "The Add/Remove Programs registration still exists after uninstall."
    }
    if (Test-Path -LiteralPath $InstallDir) {
        throw "The application directory still exists after uninstall: $InstallDir"
    }
    Assert-NoServerFirewallRule
}

function Invoke-InstallerExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Installer,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$ProcessOutputPath
    )

    $ResolvedInstaller = [IO.Path]::GetFullPath($Installer)
    if ($ResolvedInstaller.Equals($BaselineArtifact.path, [StringComparison]::OrdinalIgnoreCase)) {
        $ExpectedHash = [string]$BaselineArtifact.sha256
    }
    elseif ($ResolvedInstaller.Equals($UpgradeArtifact.path, [StringComparison]::OrdinalIgnoreCase)) {
        $ExpectedHash = [string]$UpgradeArtifact.sha256
    }
    else {
        throw "Installer is not one of the prevalidated immutable artifacts: $ResolvedInstaller"
    }
    $CurrentHash = (Get-FileHash -LiteralPath $ResolvedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($CurrentHash -cne $ExpectedHash) {
        throw "Installer changed after validation: $ResolvedInstaller"
    }
    return Invoke-NativeProcess `
        -FilePath $ResolvedInstaller `
        -Arguments @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/LOG=$LogPath"
        ) `
        -OutputPath $ProcessOutputPath
}

function Invoke-UninstallerExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$ProcessOutputPath
    )

    $Uninstaller = Get-UninstallerPath
    return Invoke-NativeProcess `
        -FilePath $Uninstaller `
        -Arguments @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/LOG=$LogPath"
        ) `
        -OutputPath $ProcessOutputPath
}

function Get-VerifiedUpgradeBackup {
    param(
        [Parameter(Mandatory = $true)][DateTimeOffset]$NotBefore,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceVersion,
        [Parameter(Mandatory = $true)][string]$ExpectedTargetVersion,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceDatabaseSha256
    )

    $BackupRoot = Join-Path $ExpectedDataRoot "Backups\Installer"
    if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) {
        throw "Installer backup directory was not created: $BackupRoot"
    }
    $Candidates = @()
    foreach ($MetadataPath in @(Get-ChildItem -LiteralPath $BackupRoot -Filter "mission-legal_*.json" -File)) {
        try {
            $Metadata = Get-Content -LiteralPath $MetadataPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $Created = [DateTimeOffset]::Parse([string]$Metadata.created_at)
            if (
                [string]$Metadata.reason -ceq "installer-pre-upgrade" -and
                [string]$Metadata.app_version_from -ceq $ExpectedSourceVersion -and
                [string]$Metadata.app_version_to -ceq $ExpectedTargetVersion -and
                $Created -ge $NotBefore.AddMinutes(-1)
            ) {
                $DatabasePath = [IO.Path]::ChangeExtension($MetadataPath.FullName, ".db")
                if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) {
                    throw "Upgrade backup metadata has no database file: $MetadataPath"
                }
                $ActualHash = (Get-FileHash -LiteralPath $DatabasePath -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($ActualHash -cne ([string]$Metadata.backup_sha256).ToLowerInvariant()) {
                    throw "Upgrade backup SHA-256 does not match its metadata: $DatabasePath"
                }
                if ((Get-Item -LiteralPath $DatabasePath).Length -ne [long]$Metadata.size) {
                    throw "Upgrade backup size does not match its metadata: $DatabasePath"
                }
                if (
                    ([string]$Metadata.source_file_sha256).ToLowerInvariant() -cne
                    $ExpectedSourceDatabaseSha256.ToLowerInvariant()
                ) {
                    throw "Upgrade backup metadata does not identify the expected baseline database: $DatabasePath"
                }
                $Candidates += [pscustomobject]@{
                    path = $DatabasePath
                    metadata_path = $MetadataPath.FullName
                    sha256 = $ActualHash
                    created_at_utc = $Created.ToString("o")
                }
            }
        }
        catch {
            if ($_.Exception.Message -like "Upgrade backup*") {
                throw
            }
        }
    }
    if ($Candidates.Count -eq 0) {
        throw "No verified pre-upgrade backup from $ExpectedSourceVersion was created."
    }
    return $Candidates | Sort-Object created_at_utc -Descending | Select-Object -First 1
}

function Get-VerifiedRollbackReceipt {
    param(
        [Parameter(Mandatory = $true)][DateTimeOffset]$NotBefore,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceVersion,
        [Parameter(Mandatory = $true)][string]$ExpectedTargetVersion,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceDatabaseSha256,
        [Parameter(Mandatory = $true)][string]$InstallerLogPath
    )

    $BackupRoot = [IO.Path]::GetFullPath((Join-Path $ExpectedDataRoot "Backups\Installer"))
    $LiveDatabase = [IO.Path]::GetFullPath((Join-Path $ExpectedDataRoot "app.db"))
    if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) {
        throw "Installer backup directory was not created: $BackupRoot"
    }
    $Candidates = @()
    foreach ($ReceiptPath in @(Get-ChildItem -LiteralPath $BackupRoot -Filter "installer-attempt-*.json" -File)) {
        try {
            $Receipt = Get-Content -LiteralPath $ReceiptPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $Created = [DateTimeOffset]::Parse([string]$Receipt.created_at)
            if (
                [int]$Receipt.format -ne 1 -or
                [string]$Receipt.status -cne "backed-up" -or
                [string]$Receipt.restore_status -cne "restored" -or
                [string]$Receipt.app_version_from -cne $ExpectedSourceVersion -or
                [string]$Receipt.app_version_to -cne $ExpectedTargetVersion -or
                $Created -lt $NotBefore.AddMinutes(-1)
            ) {
                continue
            }
            $ReceiptFullPath = [IO.Path]::GetFullPath($ReceiptPath.FullName)
            $RecordedReceiptPath = [IO.Path]::GetFullPath([string]$Receipt.receipt_path)
            $RecordedBackupRoot = [IO.Path]::GetFullPath([string]$Receipt.backup_dir)
            $RecordedDatabase = [IO.Path]::GetFullPath([string]$Receipt.database)
            if (
                -not $RecordedReceiptPath.Equals($ReceiptFullPath, [StringComparison]::OrdinalIgnoreCase) -or
                -not $RecordedBackupRoot.Equals($BackupRoot, [StringComparison]::OrdinalIgnoreCase) -or
                -not $RecordedDatabase.Equals($LiveDatabase, [StringComparison]::OrdinalIgnoreCase)
            ) {
                throw "Rollback receipt path binding is invalid: $ReceiptPath"
            }
            $BackupPath = [IO.Path]::GetFullPath([string]$Receipt.backup_path)
            $MetadataPath = [IO.Path]::GetFullPath([string]$Receipt.metadata_path)
            if (
                -not ([IO.Directory]::GetParent($BackupPath).FullName).Equals($BackupRoot, [StringComparison]::OrdinalIgnoreCase) -or
                -not ([IO.Directory]::GetParent($MetadataPath).FullName).Equals($BackupRoot, [StringComparison]::OrdinalIgnoreCase) -or
                -not ([IO.Path]::ChangeExtension($BackupPath, ".json")).Equals($MetadataPath, [StringComparison]::OrdinalIgnoreCase)
            ) {
                throw "Rollback receipt backup paths escape their expected directory: $ReceiptPath"
            }
            foreach ($Path in @($ReceiptFullPath, $BackupPath, $MetadataPath)) {
                Assert-NoReparseAncestors $Path
                if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
                    throw "Rollback receipt evidence file is missing: $Path"
                }
            }
            $BackupSha256 = (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $MetadataSha256 = (Get-FileHash -LiteralPath $MetadataPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if (
                $BackupSha256 -cne ([string]$Receipt.backup_sha256).ToLowerInvariant() -or
                $MetadataSha256 -cne ([string]$Receipt.metadata_sha256).ToLowerInvariant() -or
                $BackupSha256 -cne ([string]$Receipt.restored_database_sha256).ToLowerInvariant() -or
                ([string]$Receipt.source_file_sha256).ToLowerInvariant() -cne $ExpectedSourceDatabaseSha256.ToLowerInvariant() -or
                -not [bool]$Receipt.sqlite_sidecars_cleared
            ) {
                throw "Rollback receipt hash or sidecar evidence is invalid: $ReceiptPath"
            }
            if ((Get-Item -LiteralPath $BackupPath).Length -ne [long]$Receipt.snapshot_size) {
                throw "Rollback receipt snapshot size is invalid: $BackupPath"
            }
            $Metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if (
                [string]$Metadata.reason -cne "installer-pre-upgrade" -or
                [string]$Metadata.attempt_id -cne [string]$Receipt.attempt_id -or
                [string]$Metadata.app_version_from -cne $ExpectedSourceVersion -or
                [string]$Metadata.app_version_to -cne $ExpectedTargetVersion -or
                ([string]$Metadata.backup_sha256).ToLowerInvariant() -cne $BackupSha256 -or
                ([string]$Metadata.source_file_sha256).ToLowerInvariant() -cne $ExpectedSourceDatabaseSha256.ToLowerInvariant()
            ) {
                throw "Rollback receipt metadata binding is invalid: $MetadataPath"
            }
            $Candidates += [pscustomobject]@{
                receipt_path = $ReceiptFullPath
                backup_path = $BackupPath
                metadata_path = $MetadataPath
                source_database_sha256 = $ExpectedSourceDatabaseSha256.ToLowerInvariant()
                restored_snapshot_sha256 = $BackupSha256
                restored_at_utc = [DateTimeOffset]::Parse([string]$Receipt.restored_at).ToString("o")
                created_at_utc = $Created.ToString("o")
                sqlite_sidecars_cleared = $true
            }
        }
        catch {
            if ($_.Exception.Message -like "Rollback receipt*") {
                throw
            }
        }
    }
    if ($Candidates.Count -eq 0) {
        throw "No verified restored database receipt from $ExpectedSourceVersion was found."
    }
    if (-not (Test-Path -LiteralPath $InstallerLogPath -PathType Leaf)) {
        throw "Post-copy installer log is missing: $InstallerLogPath"
    }
    $InstallerLog = Get-Content -LiteralPath $InstallerLogPath -Raw
    $RollbackCompleted = "Verified authoritative database rollback completed before binary and service recovery."
    $PriorServiceStart = "Service action StartOnly"
    $RollbackIndex = $InstallerLog.IndexOf($RollbackCompleted, [StringComparison]::Ordinal)
    $StartIndex = $InstallerLog.IndexOf($PriorServiceStart, [StringComparison]::Ordinal)
    if ($RollbackIndex -lt 0 -or $StartIndex -lt 0 -or $RollbackIndex -ge $StartIndex) {
        throw "Installer log does not prove database restoration completed before prior-service startup."
    }
    $Selected = $Candidates | Sort-Object restored_at_utc -Descending | Select-Object -First 1
    $Selected | Add-Member -NotePropertyName restored_before_prior_service_start -NotePropertyValue $true
    return $Selected
}

function Assert-PreservedFiles {
    param(
        [Parameter(Mandatory = $true)][hashtable]$ExpectedHashes,
        [switch]$ExcludeDatabaseHash
    )

    $DatabasePath = Join-Path $ExpectedDataRoot "app.db"
    if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) {
        throw "The authoritative database was removed: $DatabasePath"
    }
    if ((Get-Item -LiteralPath $DatabasePath).Length -le 0) {
        throw "The authoritative database is empty after uninstall."
    }
    foreach ($Name in $ExpectedHashes.Keys) {
        if ($ExcludeDatabaseHash -and $Name -ceq "authoritative_database") {
            continue
        }
        $Expected = $ExpectedHashes[$Name]
        $Path = [string]$Expected.path
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "$Name was removed during uninstall: $Path"
        }
        $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -cne [string]$Expected.sha256) {
            throw "$Name changed during uninstall: $Path"
        }
    }
    $Backups = @(Get-ChildItem -LiteralPath (Join-Path $ExpectedDataRoot "Backups") -Filter "*.db" -File)
    if ($Backups.Count -eq 0) {
        throw "No database backups survived uninstall."
    }
    return [pscustomobject]@{
        database = $DatabasePath
        database_size = (Get-Item -LiteralPath $DatabasePath).Length
        preserved_backup_count = $Backups.Count
    }
}

function Stop-ServerServiceAndWait {
    Stop-Service -Name $ServiceName -Force -ErrorAction Stop
    $Service = Get-Service -Name $ServiceName -ErrorAction Stop
    try {
        $Service.WaitForStatus(
            [System.ServiceProcess.ServiceControllerStatus]::Stopped,
            [TimeSpan]::FromSeconds(90)
        )
        $Service.Refresh()
        if ($Service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
            throw "Service $ServiceName did not stop."
        }
    }
    finally {
        $Service.Dispose()
    }
}

function Invoke-PackagedServerSetup {
    param(
        [Parameter(Mandatory = $true)][string]$ProcessOutputPath,
        [Parameter(Mandatory = $true)][string]$MissionRoot,
        [Parameter(Mandatory = $true)][string]$BackupRoot,
        [string]$ExistingDatabase
    )

    $ResolvedMissionRoot = Assert-ChildPath $script:RunRoot $MissionRoot "Mission storage root"
    $ResolvedBackupRoot = Assert-ChildPath $script:RunRoot $BackupRoot "Mirror backup root"
    Assert-NoReparseAncestors $ResolvedMissionRoot
    Assert-NoReparseAncestors $ResolvedBackupRoot
    $Arguments = @(
        "--data-dir", $ExpectedDataRoot,
        "--onedrive-backup-dir", $ResolvedBackupRoot,
        "--mission-storage-root", $ResolvedMissionRoot,
        "--host", "0.0.0.0",
        "--port", $ValidationPort.ToString(),
        "--overwrite-certificates",
        "--skip-main-client"
    )
    if ($ExistingDatabase) {
        $Arguments += @("--existing-database", [IO.Path]::GetFullPath($ExistingDatabase))
    }
    $Result = Invoke-NativeProcess `
        -FilePath (Join-Path $InstallDir "MissionLegalServerSetup.exe") `
        -Arguments $Arguments `
        -OutputPath $ProcessOutputPath
    if ($Result.ExitCode -ne 0) {
        throw "Packaged server setup exited with code $($Result.ExitCode)."
    }
    foreach ($ConfiguredRoot in @($ResolvedMissionRoot, $ResolvedBackupRoot)) {
        if (-not (Test-Path -LiteralPath $ConfiguredRoot -PathType Container)) {
            throw "Packaged server setup did not create configured root: $ConfiguredRoot"
        }
        Assert-NoReparseAncestors $ConfiguredRoot
    }
    return $Result
}

function New-ScenarioRoots {
    param([Parameter(Mandatory = $true)][string]$Name)

    if ($Name -notmatch '^[a-z0-9][a-z0-9-]{2,50}$') {
        throw "Scenario root name is invalid: $Name"
    }
    $ScenariosRoot = Assert-ChildPath $script:RunRoot (Join-Path $script:RunRoot "Scenarios") "Scenarios root"
    if (-not (Test-Path -LiteralPath $ScenariosRoot)) {
        New-Item -ItemType Directory -Path $ScenariosRoot | Out-Null
    }
    Assert-NoReparseAncestors $ScenariosRoot
    $ScenarioRoot = Assert-NewScenarioPath (Join-Path $ScenariosRoot $Name) "Scenario root"
    New-Item -ItemType Directory -Path $ScenarioRoot | Out-Null
    $MissionRoot = Assert-NewScenarioPath (Join-Path $ScenarioRoot "MissionDocuments") "Mission storage root"
    $BackupRoot = Assert-NewScenarioPath (Join-Path $ScenarioRoot "MirrorBackups") "Mirror backup root"
    # The setup CLI intentionally requires the operator-selected mission root
    # to exist. Record both roots as absent first, then create only that input;
    # packaged setup creates the backup root itself.
    New-Item -ItemType Directory -Path $MissionRoot | Out-Null
    Assert-NoReparseAncestors $MissionRoot
    $Evidence = [pscustomobject]@{
        name = $Name
        scenario_root = $ScenarioRoot
        mission_root = $MissionRoot
        backup_root = $BackupRoot
        roots_initially_absent = $true
        mission_root_created_by_harness = $true
        backup_root_created_by_setup = $true
    }
    if (-not $script:ValidationContext.ContainsKey("ScenarioRoots")) {
        $script:ValidationContext["ScenarioRoots"] = New-Object System.Collections.Generic.List[object]
    }
    $script:ValidationContext["ScenarioRoots"].Add($Evidence)
    return $Evidence
}

function New-ApiValidationCredential {
    param([Parameter(Mandatory = $true)][int]$Port)

    $PairingResult = Invoke-NativeProcess `
        -FilePath (Join-Path $InstallDir "MissionLegalServer.exe") `
        -Arguments @("--create-pairing-code")
    if ($PairingResult.ExitCode -ne 0) {
        throw "Pairing-code command exited with code $($PairingResult.ExitCode)."
    }
    $PairingText = "$($PairingResult.StdOut)`n$($PairingResult.StdErr)"
    if ($PairingText -notmatch 'Pairing code:\s*(\d{6})') {
        throw "The packaged administration command did not return a pairing code."
    }
    $PairResponse = Invoke-LocalRestMethod `
        -Method POST `
        -Uri "https://127.0.0.1:$Port/pair" `
        -Body @{
            code = $Matches[1]
            device_name = "Disposable VM installer validation"
        }
    return @{
        "X-Device-Id" = [string]$PairResponse.device_id
        "X-Device-Credential" = [string]$PairResponse.credential
    }
}

function Assert-ServerDataAclEntry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$PublicRead,
        [switch]$RequireProtected
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required server-data ACL target is missing: $Path"
    }
    Assert-NoReparseAncestors $Path
    $AdministratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
    $SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $UsersSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-545")
    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if ($RequireProtected -and -not $Acl.AreAccessRulesProtected) {
        throw "Required server-data ACL inheritance is not protected: $Path"
    }
    $Owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($Owner.Value -notin @($AdministratorsSid.Value, $SystemSid.Value)) {
        throw "Server-data owner is outside Builtin Administrators/LocalSystem: $Path"
    }
    $AllowedSids = @($AdministratorsSid.Value, $SystemSid.Value)
    if ($PublicRead) {
        $AllowedSids += $UsersSid.Value
    }
    $RightsBySid = @{}
    $Rules = @($Acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ))
    foreach ($Rule in $Rules) {
        $SidValue = [string]$Rule.IdentityReference.Value
        if (
            $Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $SidValue -cnotin $AllowedSids
        ) {
            throw "Server-data ACL grants access outside its SID policy: $Path"
        }
        if (-not $RightsBySid.ContainsKey($SidValue)) {
            $RightsBySid[$SidValue] = [long]0
        }
        $RightsBySid[$SidValue] = (
            [long]$RightsBySid[$SidValue] -bor [long]$Rule.FileSystemRights
        )
    }
    $FullControl = [long][Security.AccessControl.FileSystemRights]::FullControl
    foreach ($Sid in @($AdministratorsSid, $SystemSid)) {
        if (
            -not $RightsBySid.ContainsKey($Sid.Value) -or
            (($RightsBySid[$Sid.Value] -band $FullControl) -ne $FullControl)
        ) {
            throw "Server-data ACL is missing FullControl for '$($Sid.Value)': $Path"
        }
    }
    if ($PublicRead) {
        $ReadAndExecute = [long][Security.AccessControl.FileSystemRights]::ReadAndExecute
        if (
            -not $RightsBySid.ContainsKey($UsersSid.Value) -or
            (($RightsBySid[$UsersSid.Value] -band $ReadAndExecute) -ne $ReadAndExecute)
        ) {
            throw "Public CA ACL is missing Builtin Users read access: $Path"
        }
        $WriteMask = (
            [long][Security.AccessControl.FileSystemRights]::Write -bor
            [long][Security.AccessControl.FileSystemRights]::Modify -bor
            [long][Security.AccessControl.FileSystemRights]::Delete -bor
            [long][Security.AccessControl.FileSystemRights]::ChangePermissions -bor
            [long][Security.AccessControl.FileSystemRights]::TakeOwnership
        )
        if (($RightsBySid[$UsersSid.Value] -band $WriteMask) -ne 0) {
            throw "Public CA ACL grants Builtin Users write-capable access: $Path"
        }
    }
    elseif ($RightsBySid.ContainsKey($UsersSid.Value)) {
        throw "Sensitive server data grants Builtin Users access: $Path"
    }
}

function Invoke-StandardUserServerDataProbe {
    param(
        [Parameter(Mandatory = $true)][string[]]$SensitivePaths,
        [Parameter(Mandatory = $true)][string]$PublicCaPath
    )

    $UsersSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-545")
    $AdministratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
    do {
        $AccountName = "MLAcl" + [Guid]::NewGuid().ToString("N").Substring(0, 10)
    } while ($null -ne (Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue))
    $PlainPassword = [Guid]::NewGuid().ToString("N") + "aA1!"
    $SecurePassword = ConvertTo-SecureString $PlainPassword -AsPlainText -Force
    $Account = $null
    try {
        $Account = New-LocalUser `
            -Name $AccountName `
            -Password $SecurePassword `
            -AccountNeverExpires `
            -UserMayNotChangePassword `
            -ErrorAction Stop
        $UsersMembers = @(Get-LocalGroupMember -SID $UsersSid -ErrorAction Stop)
        if ($Account.SID.Value -notin @($UsersMembers | ForEach-Object { $_.SID.Value })) {
            Add-LocalGroupMember -SID $UsersSid -Member $Account.SID -ErrorAction Stop
        }
        $AdministratorMembers = @(
            Get-LocalGroupMember -SID $AdministratorsSid -ErrorAction Stop
        )
        if ($Account.SID.Value -in @($AdministratorMembers | ForEach-Object { $_.SID.Value })) {
            throw "Disposable ACL probe account unexpectedly belongs to Builtin Administrators."
        }

        $SensitiveEncoded = @($SensitivePaths | ForEach-Object {
            "'" + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_)) + "'"
        }) -join ","
        $PublicEncoded = [Convert]::ToBase64String(
            [Text.Encoding]::UTF8.GetBytes($PublicCaPath)
        )
        $ProbeTemplate = @'
$ErrorActionPreference = 'Stop'
$SensitiveEncoded = @(__SENSITIVE_PATHS__)
$PublicEncoded = '__PUBLIC_CA_PATH__'
function Decode-Path([string]$Value) {
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}
foreach ($EncodedPath in $SensitiveEncoded) {
    $Path = Decode-Path $EncodedPath
    try {
        $Stream = [IO.File]::Open(
            $Path,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::ReadWrite
        )
        $Stream.Dispose()
        exit 21
    }
    catch {
        if (
            $_.Exception -isnot [UnauthorizedAccessException] -and
            $_.Exception.InnerException -isnot [UnauthorizedAccessException]
        ) {
            exit 22
        }
        # Expected: a standard user cannot read sensitive server data.
    }
}
$PublicPath = Decode-Path $PublicEncoded
try {
    $Text = [IO.File]::ReadAllText($PublicPath, [Text.Encoding]::ASCII)
}
catch {
    exit 23
}
if (-not $Text.Contains('BEGIN CERTIFICATE')) {
    exit 24
}
try {
    $WriteStream = [IO.File]::Open(
        $PublicPath,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    $WriteStream.Dispose()
    exit 25
}
catch {
    if (
        $_.Exception -isnot [UnauthorizedAccessException] -and
        $_.Exception.InnerException -isnot [UnauthorizedAccessException]
    ) {
        exit 26
    }
    # Expected: Builtin Users receive read access only.
}
exit 0
'@
        $ProbeScript = $ProbeTemplate.Replace(
            "__SENSITIVE_PATHS__",
            $SensitiveEncoded
        ).Replace(
            "__PUBLIC_CA_PATH__",
            $PublicEncoded
        )
        $EncodedCommand = [Convert]::ToBase64String(
            [Text.Encoding]::Unicode.GetBytes($ProbeScript)
        )
        $PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        $StartInfo = [Diagnostics.ProcessStartInfo]::new()
        $StartInfo.FileName = $PowerShellExe
        $StartInfo.Arguments = (
            "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass " +
            "-EncodedCommand $EncodedCommand"
        )
        $StartInfo.UseShellExecute = $false
        $StartInfo.CreateNoWindow = $true
        $StartInfo.WorkingDirectory = $env:SystemRoot
        $StartInfo.Domain = $env:COMPUTERNAME
        $StartInfo.UserName = $AccountName
        $StartInfo.Password = $SecurePassword
        $StartInfo.LoadUserProfile = $false
        $Process = [Diagnostics.Process]::Start($StartInfo)
        if ($null -eq $Process) {
            throw "Could not start the standard-user server-data ACL probe."
        }
        try {
            if (-not $Process.WaitForExit(60000)) {
                $Process.Kill()
                $Process.WaitForExit()
                throw "Standard-user server-data ACL probe timed out."
            }
            if ($Process.ExitCode -ne 0) {
                throw "Standard-user server-data ACL probe failed with exit code $($Process.ExitCode)."
            }
        }
        finally {
            $Process.Dispose()
        }
    }
    finally {
        $PlainPassword = $null
        if ($null -ne $Account) {
            Remove-LocalUser -SID $Account.SID -ErrorAction Stop
        }
    }
    if ($null -ne (Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue)) {
        throw "Disposable ACL probe account remains after validation: $AccountName"
    }
    return [pscustomobject]@{
        temporary_standard_user_removed = $true
        sensitive_read_denied = $true
        public_ca_read_allowed = $true
        public_ca_write_denied = $true
    }
}

function Assert-ServerDataAclPolicy {
    $PublicDirectory = Join-Path $ExpectedDataRoot "Public"
    $PublicCa = Join-Path $PublicDirectory "mission-legal-ca.pem"
    $RequiredProtected = @(
        $ExpectedDataRoot,
        (Join-Path $ExpectedDataRoot "app.db"),
        (Join-Path $ExpectedDataRoot "Backups"),
        (Join-Path $ExpectedDataRoot "Configuration"),
        (Join-Path $ExpectedDataRoot "Configuration\tls"),
        (Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-ca-key.pem"),
        (Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-server-key.pem")
    )
    $SensitiveItems = New-Object System.Collections.Generic.List[string]
    $Queue = New-Object System.Collections.Generic.Queue[string]
    $Queue.Enqueue($ExpectedDataRoot)
    while ($Queue.Count -gt 0) {
        $Current = $Queue.Dequeue()
        $SensitiveItems.Add($Current)
        foreach ($Child in @(Get-ChildItem -LiteralPath $Current -Force -ErrorAction Stop)) {
            if (($Child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Server data contains a reparse point: $($Child.FullName)"
            }
            if ($Child.FullName.Equals($PublicDirectory, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            $SensitiveItems.Add($Child.FullName)
            if ($Child.PSIsContainer) {
                $Queue.Enqueue($Child.FullName)
            }
        }
    }
    foreach ($Path in @($SensitiveItems | Select-Object -Unique)) {
        Assert-ServerDataAclEntry `
            -Path $Path `
            -PublicRead $false `
            -RequireProtected:($Path -in $RequiredProtected)
    }
    Assert-ServerDataAclEntry -Path $PublicDirectory -PublicRead $true -RequireProtected
    Assert-ServerDataAclEntry -Path $PublicCa -PublicRead $true -RequireProtected

    $PrivateCa = Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-ca.pem"
    if (
        (Get-FileHash -LiteralPath $PrivateCa -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $PublicCa -Algorithm SHA256).Hash
    ) {
        throw "Public CA certificate does not match the protected CA certificate."
    }
    $BackupDatabase = @(
        Get-ChildItem `
            -LiteralPath (Join-Path $ExpectedDataRoot "Backups") `
            -Filter "*.db" `
            -File `
            -Recurse `
            -ErrorAction Stop
    ) | Select-Object -First 1
    if ($null -eq $BackupDatabase) {
        throw "No server backup database exists for the standard-user denial probe."
    }
    $SensitiveProbePaths = @(
        (Join-Path $ExpectedDataRoot "app.db"),
        (Join-Path $ExpectedDataRoot "Configuration\server.json"),
        (Join-Path $ExpectedDataRoot "Configuration\devices.json"),
        (Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-ca-key.pem"),
        (Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-server-key.pem"),
        $BackupDatabase.FullName
    )
    foreach ($Path in $SensitiveProbePaths) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Sensitive standard-user probe target is missing: $Path"
        }
    }
    $StandardUserProbe = Invoke-StandardUserServerDataProbe `
        -SensitivePaths $SensitiveProbePaths `
        -PublicCaPath $PublicCa
    return [pscustomobject]@{
        sensitive_root = $ExpectedDataRoot
        sensitive_item_count = @($SensitiveItems | Select-Object -Unique).Count
        protected_acl_sids = @("S-1-5-18", "S-1-5-32-544")
        public_ca = $PublicCa
        public_read_sid = "S-1-5-32-545"
        standard_user_probe = $StandardUserProbe
    }
}

function Get-PersistenceHashMap {
    param(
        [Parameter(Mandatory = $true)][string]$DocumentPath,
        [switch]$IncludeDatabase
    )

    $Paths = [ordered]@{
        configuration = Join-Path $ExpectedDataRoot "Configuration\server.json"
        device_credentials = Join-Path $ExpectedDataRoot "Configuration\devices.json"
        tls_ca_certificate = Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-ca.pem"
        tls_ca_private_key = Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-ca-key.pem"
        tls_server_certificate = Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-server.pem"
        tls_server_private_key = Join-Path $ExpectedDataRoot "Configuration\tls\mission-legal-server-key.pem"
        mission_document = [IO.Path]::GetFullPath($DocumentPath)
    }
    if ($IncludeDatabase) {
        $Paths["authoritative_database"] = Join-Path $ExpectedDataRoot "app.db"
    }
    $PublicCa = Join-Path $ExpectedDataRoot "Public\mission-legal-ca.pem"
    if (Test-Path -LiteralPath $PublicCa -PathType Leaf) {
        $Paths["public_ca_certificate"] = $PublicCa
    }
    $Hashes = @{}
    foreach ($Name in $Paths.Keys) {
        $Path = [string]$Paths[$Name]
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Persistence fixture '$Name' is missing: $Path"
        }
        $Hashes[$Name] = @{
            path = $Path
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    return $Hashes
}

function Assert-PristineProductState {
    $State = Get-MachineState
    if (
        $State.service -cne "absent" -or
        $State.uninstall_registration_exists -or
        $State.install_directory_exists -or
        $State.data_directory_exists -or
        $State.firewall_rule_count -gt 0
    ) {
        throw (
            "The product state is not pristine. Revert the disposable VM or archive the " +
            "completed scenario before continuing. " + ($State | ConvertTo-Json -Compress)
        )
    }
    return $State
}

function Archive-ProductData {
    param([Parameter(Mandatory = $true)][string]$Name)

    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,64}$') {
        throw "ProgramData archive name is invalid: $Name"
    }
    if (-not (Test-Path -LiteralPath $ExpectedDataRoot -PathType Container)) {
        throw "Expected ProgramData is missing before archive: $ExpectedDataRoot"
    }
    Assert-NoReparseAncestors $ExpectedDataRoot
    $ArchiveRoot = Assert-ChildPath $script:RunRoot (Join-Path $script:RunRoot "ProgramDataArchives") "ProgramData archive root"
    if (-not (Test-Path -LiteralPath $ArchiveRoot)) {
        New-Item -ItemType Directory -Path $ArchiveRoot | Out-Null
    }
    Assert-NoReparseAncestors $ArchiveRoot
    $Destination = Assert-NewScenarioPath (Join-Path $ArchiveRoot $Name) "ProgramData archive"
    Move-Item -LiteralPath $ExpectedDataRoot -Destination $Destination
    if (Test-Path -LiteralPath $ExpectedDataRoot) {
        throw "ProgramData remained after archive: $ExpectedDataRoot"
    }
    Assert-NoReparseAncestors $Destination
    return $Destination
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)

    $Sha = [Security.Cryptography.SHA256]::Create()
    try {
        $Bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($Sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $Sha.Dispose()
    }
}

function Get-InstallTreeInventory {
    if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) {
        throw "Install directory is missing: $InstallDir"
    }
    Assert-NoReparseAncestors $InstallDir
    $RootPrefix = $InstallDir.TrimEnd('\') + '\'
    $Queue = New-Object System.Collections.Generic.Queue[string]
    $Queue.Enqueue($InstallDir)
    $Entries = @()
    while ($Queue.Count -gt 0) {
        $Directory = $Queue.Dequeue()
        $DirectoryItem = Get-Item -LiteralPath $Directory -Force -ErrorAction Stop
        if (($DirectoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Install tree contains a reparse-point directory: $Directory"
        }
        foreach ($Item in @(Get-ChildItem -LiteralPath $Directory -Force -ErrorAction Stop)) {
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Install tree contains a reparse point: $($Item.FullName)"
            }
            if ($Item.PSIsContainer) {
                $Queue.Enqueue($Item.FullName)
                continue
            }
            $Relative = $Item.FullName.Substring($RootPrefix.Length).Replace('/', '\')
            $Entries += [pscustomobject]@{
                relative_path = $Relative
                size = [long]$Item.Length
                sha256 = (Get-FileHash -LiteralPath $Item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    $Sorted = @($Entries | Sort-Object relative_path)
    $Canonical = (($Sorted | ForEach-Object {
        "$($_.relative_path)|$($_.size)|$($_.sha256)"
    }) -join "`n")
    return [pscustomobject]@{
        root = $InstallDir
        file_count = $Sorted.Count
        fingerprint_sha256 = Get-TextSha256 $Canonical
        files = $Sorted
    }
}

function Assert-InstallTreeMatches {
    param(
        [Parameter(Mandatory = $true)][object]$Expected,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $Current = Get-InstallTreeInventory
    if (
        [int]$Current.file_count -ne [int]$Expected.file_count -or
        [string]$Current.fingerprint_sha256 -cne [string]$Expected.fingerprint_sha256
    ) {
        throw (
            "$Description did not restore the exact baseline install tree. Expected " +
            "$($Expected.file_count) files/$($Expected.fingerprint_sha256), found " +
            "$($Current.file_count) files/$($Current.fingerprint_sha256)."
        )
    }
    return $Current
}

function Set-RestrictedValidationAcl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $AdministratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
    $SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $Acl = [Security.AccessControl.DirectorySecurity]::new()
    $Acl.SetOwner($AdministratorsSid)
    $Acl.SetAccessRuleProtection($true, $false)
    foreach ($Sid in @($AdministratorsSid, $SystemSid)) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $Sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                [Security.AccessControl.InheritanceFlags]::ObjectInherit,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$Acl.AddAccessRule($Rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $Acl
}

function Start-RedirectedNativeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$OutputPath
    )

    $ResolvedOutput = Assert-ChildPath $script:RunRoot $OutputPath "Process output"
    Assert-NoReparseAncestors $ResolvedOutput
    if (Test-Path -LiteralPath $ResolvedOutput) {
        throw "Process output path must be initially absent: $ResolvedOutput"
    }
    $StartInfo = New-Object Diagnostics.ProcessStartInfo
    $StartInfo.FileName = [IO.Path]::GetFullPath($FilePath)
    $StartInfo.Arguments = (($Arguments | ForEach-Object {
        ConvertTo-WindowsCommandLineArgument ([string]$_)
    }) -join ' ')
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $Process = New-Object Diagnostics.Process
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) {
        throw "Could not start $($StartInfo.FileName)."
    }
    return [pscustomobject]@{
        Process = $Process
        StdOutTask = $Process.StandardOutput.ReadToEndAsync()
        StdErrTask = $Process.StandardError.ReadToEndAsync()
        OutputPath = $ResolvedOutput
        FilePath = $StartInfo.FileName
    }
}

function Complete-RedirectedNativeProcess {
    param(
        [Parameter(Mandatory = $true)][object]$Handle,
        [int]$TimeoutSeconds = $ProcessTimeoutSeconds
    )

    $Process = $Handle.Process
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
        try {
            $Process.Kill()
        }
        catch {
        }
        throw "$($Handle.FilePath) exceeded the $TimeoutSeconds-second timeout."
    }
    $StdOut = $Handle.StdOutTask.Result
    $StdErr = $Handle.StdErrTask.Result
    $ExitCode = $Process.ExitCode
    @(
        "exit_code=$ExitCode"
        "--- stdout ---"
        $StdOut
        "--- stderr ---"
        $StdErr
    ) | Set-Content -LiteralPath $Handle.OutputPath -Encoding UTF8
    $Process.Dispose()
    return [pscustomobject]@{
        ExitCode = $ExitCode
        StdOut = $StdOut
        StdErr = $StdErr
    }
}

function Stop-OwnedProcess {
    param([object]$Handle)

    if ($null -eq $Handle -or $null -eq $Handle.Process) {
        return
    }
    try {
        if (-not $Handle.Process.HasExited) {
            $Handle.Process.Kill()
            [void]$Handle.Process.WaitForExit(10000)
        }
    }
    catch {
    }
}

function Invoke-PostCopyUpgradeFailure {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$InstallerOutputPath,
        [Parameter(Mandatory = $true)][string]$WatcherOutputPath,
        [Parameter(Mandatory = $true)][string]$BaselineServiceSha256,
        [Parameter(Mandatory = $true)][string]$BaselineDatabaseSha256
    )

    $WatcherScript = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "server_installer_failure_watcher.ps1"))
    if (-not (Test-Path -LiteralPath $WatcherScript -PathType Leaf)) {
        throw "Post-copy failure watcher is missing: $WatcherScript"
    }
    Assert-NoReparseAncestors $WatcherScript
    $CurrentArtifactHash = (Get-FileHash -LiteralPath $UpgradeArtifact.path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($CurrentArtifactHash -cne [string]$UpgradeArtifact.sha256) {
        throw "Upgrade artifact changed before failure injection."
    }
    $ServicePath = [IO.Path]::GetFullPath((Join-Path $InstallDir "MissionLegalService.exe"))
    if (-not (Test-Path -LiteralPath $ServicePath -PathType Leaf)) {
        throw "Baseline service executable is missing before failure injection: $ServicePath"
    }
    if ((Get-FileHash -LiteralPath $ServicePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $BaselineServiceSha256) {
        throw "Installed service executable changed before failure injection."
    }
    $DatabasePath = [IO.Path]::GetFullPath((Join-Path $ExpectedDataRoot "app.db"))
    if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) {
        throw "Baseline database is missing before failure injection: $DatabasePath"
    }
    if ((Get-FileHash -LiteralPath $DatabasePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $BaselineDatabaseSha256) {
        throw "Authoritative database changed before failure injection."
    }

    $FailureRoot = Assert-NewScenarioPath (Join-Path $script:RunRoot "FailureInjection") "Failure-injection root"
    New-Item -ItemType Directory -Path $FailureRoot | Out-Null
    Set-RestrictedValidationAcl $FailureRoot
    Assert-RestrictedValidationAcl $FailureRoot
    Assert-NoReparseAncestors $FailureRoot
    $Token = [Guid]::NewGuid().ToString("N")
    $AuthorizationFile = Join-Path $FailureRoot "authorization.json"
    $ReadyFile = Join-Path $FailureRoot "watcher-ready.json"
    $SignalFile = Join-Path $FailureRoot "installer-started.json"
    $ResultFile = Join-Path $FailureRoot "watcher-result.json"
    [ordered]@{
        schema_version = 1
        purpose = "mission-legal-server-installer-post-copy-failure"
        token = $Token
        created_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        expires_at_utc = [DateTimeOffset]::UtcNow.AddMinutes(10).ToString("o")
        install_dir = $InstallDir
        target_path = $ServicePath
        baseline_sha256 = $BaselineServiceSha256
        database_path = $DatabasePath
        database_sha256 = $BaselineDatabaseSha256
        upgrade_installer_path = $UpgradeArtifact.path
        upgrade_installer_sha256 = $UpgradeArtifact.sha256
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $AuthorizationFile -Encoding UTF8

    $PowerShellExe = [IO.Path]::GetFullPath((Get-Process -Id $PID).Path)
    $WatcherHandle = $null
    $InstallerHandle = $null
    try {
        $WatcherHandle = Start-RedirectedNativeProcess `
            -FilePath $PowerShellExe `
            -Arguments @(
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-File", $WatcherScript,
                "-WorkRoot", $ResolvedWorkRoot,
                "-AuthorizationFile", $AuthorizationFile,
                "-AuthorizationToken", $Token,
                "-ReadyFile", $ReadyFile,
                "-SignalFile", $SignalFile,
                "-ResultFile", $ResultFile,
                "-TimeoutSeconds", ([Math]::Min($ProcessTimeoutSeconds, 900)).ToString()
            ) `
            -OutputPath $WatcherOutputPath
        $ReadyDeadline = [DateTimeOffset]::UtcNow.AddSeconds(60)
        while (-not (Test-Path -LiteralPath $ReadyFile -PathType Leaf)) {
            if ($WatcherHandle.Process.HasExited) {
                $EarlyWatcher = Complete-RedirectedNativeProcess -Handle $WatcherHandle -TimeoutSeconds 5
                $WatcherHandle = $null
                throw "Post-copy failure watcher exited before readiness with code $($EarlyWatcher.ExitCode)."
            }
            if ([DateTimeOffset]::UtcNow -ge $ReadyDeadline) {
                throw "Post-copy failure watcher did not become ready within 60 seconds."
            }
            Start-Sleep -Milliseconds 100
        }
        Assert-NoReparseAncestors $ReadyFile

        $InstallerHandle = Start-RedirectedNativeProcess `
            -FilePath $UpgradeArtifact.path `
            -Arguments @(
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/LOG=$LogPath"
            ) `
            -OutputPath $InstallerOutputPath
        [ordered]@{
            schema_version = 1
            purpose = "mission-legal-server-installer-post-copy-failure"
            token = $Token
            installer_pid = $InstallerHandle.Process.Id
            signaled_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $SignalFile -Encoding UTF8

        $WatcherResult = Complete-RedirectedNativeProcess `
            -Handle $WatcherHandle `
            -TimeoutSeconds ([Math]::Min($ProcessTimeoutSeconds, 900))
        $WatcherHandle = $null
        $InstallerResult = Complete-RedirectedNativeProcess `
            -Handle $InstallerHandle `
            -TimeoutSeconds $ProcessTimeoutSeconds
        $InstallerHandle = $null
        if ($WatcherResult.ExitCode -ne 0) {
            throw "Post-copy failure watcher exited with code $($WatcherResult.ExitCode)."
        }
        if (-not (Test-Path -LiteralPath $ResultFile -PathType Leaf)) {
            throw "Post-copy failure watcher produced no result evidence."
        }
        $WatcherEvidence = Get-Content -LiteralPath $ResultFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if (
            [string]$WatcherEvidence.status -cne "injected" -or
            [IO.Path]::GetFullPath([string]$WatcherEvidence.target_path) -ine $ServicePath -or
            [string]$WatcherEvidence.baseline_sha256 -cne $BaselineServiceSha256 -or
            [string]$WatcherEvidence.candidate_sha256 -ceq $BaselineServiceSha256 -or
            [string]$WatcherEvidence.candidate_sha256 -notmatch '^[a-f0-9]{64}$' -or
            [long]$WatcherEvidence.candidate_size -le 0 -or
            [string]$WatcherEvidence.damaged_sha256 -ceq [string]$WatcherEvidence.candidate_sha256 -or
            [IO.Path]::GetFullPath([string]$WatcherEvidence.database_path) -ine $DatabasePath -or
            [string]$WatcherEvidence.database_before_sha256 -cne $BaselineDatabaseSha256 -or
            [string]$WatcherEvidence.database_mutated_sha256 -ceq $BaselineDatabaseSha256 -or
            [string]$WatcherEvidence.database_mutated_sha256 -notmatch '^[a-f0-9]{64}$' -or
            [long]$WatcherEvidence.database_mutated_size -le [long]$WatcherEvidence.database_before_size -or
            [string]$WatcherEvidence.upgrade_installer_sha256 -cne [string]$UpgradeArtifact.sha256
        ) {
            throw "Post-copy failure watcher did not prove a distinct installed candidate was damaged."
        }
        if ($InstallerResult.ExitCode -eq 0) {
            throw "Upgrade unexpectedly succeeded after post-copy candidate damage."
        }
        if ((Get-FileHash -LiteralPath $UpgradeArtifact.path -Algorithm SHA256).Hash.ToLowerInvariant() -cne [string]$UpgradeArtifact.sha256) {
            throw "Upgrade artifact changed during post-copy failure injection."
        }
        return [pscustomobject]@{
            installer_exit_code = $InstallerResult.ExitCode
            watcher_exit_code = $WatcherResult.ExitCode
            watcher_evidence = $WatcherEvidence
            installer_artifact_sha256 = $UpgradeArtifact.sha256
            artifact_unchanged = $true
        }
    }
    finally {
        Stop-OwnedProcess $WatcherHandle
        Stop-OwnedProcess $InstallerHandle
    }
}

function Write-ValidationResult {
    if (-not $script:RunRoot) {
        return
    }
    $Payload = [ordered]@{
        schema_version = 1
        status = $script:OverallStatus
        failure = $script:FailureMessage
        computer_name = [Environment]::MachineName
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        baseline_artifact = $script:ValidationContext["BaselineArtifact"]
        upgrade_artifact = $script:ValidationContext["UpgradeArtifact"]
        install_directory = $InstallDir
        data_directory = $ExpectedDataRoot
        scenario_roots = $script:ValidationContext["ScenarioRoots"]
        private_network = $script:ValidationContext["PrivateNetwork"]
        upgrade_backup = $script:ValidationContext["UpgradeBackup"]
        phases = $script:Phases
        note = "Product data and validation evidence are intentionally preserved; revert the disposable VM snapshot."
    }
    $ResultPath = Join-Path $script:RunRoot "result.json"
    $Payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    Write-Host "Validation result: $ResultPath"
}

if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) {
    throw "Server installer validation can only run on Windows."
}
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    throw "Server installer validation requires 64-bit Windows PowerShell on 64-bit Windows."
}

$BaselineCore = Get-CoreVersion $BaselineVersion "BaselineVersion"
$UpgradeCore = Get-CoreVersion $UpgradeVersion "UpgradeVersion"
if ($UpgradeCore -le $BaselineCore) {
    throw "UpgradeVersion must be newer than BaselineVersion."
}
$BaselineArtifact = Get-ArtifactEvidence $BaselineInstaller $BaselineVersion "Baseline installer"
$UpgradeArtifact = Get-ArtifactEvidence $UpgradeInstaller $UpgradeVersion "Upgrade installer"
if ($BaselineArtifact.sha256 -ceq $UpgradeArtifact.sha256) {
    throw "Baseline and upgrade installers must be different immutable artifacts."
}
$script:ValidationContext.BaselineArtifact = $BaselineArtifact
$script:ValidationContext.UpgradeArtifact = $UpgradeArtifact

$ResolvedWorkRoot = Assert-SafeWorkRoot $WorkRoot
$InitialState = Get-MachineState

if ($ValidateOnly) {
    $Plan = [ordered]@{
        mode = "validate-only"
        mutating_actions_performed = $false
        baseline_artifact = $BaselineArtifact
        upgrade_artifact = $UpgradeArtifact
        current_machine_state = $InitialState
        production_install_directory = $InstallDir
        production_data_directory = $ExpectedDataRoot
        exact_marker_path = $MarkerPath
        work_root = $ResolvedWorkRoot
        work_root_exists = (Test-Path -LiteralPath $ResolvedWorkRoot)
        execution_requires = @(
            "64-bit elevated Windows PowerShell on 64-bit Windows",
            "recognized virtual machine",
            "unexpired machine-bound marker at the exact dedicated ProgramData path",
            "Administrators/LocalSystem-only protected marker ACL",
            "exact disposable-VM confirmation text",
            "initially absent safe top-level WorkRoot with no reparse ancestors",
            "pristine service, install, uninstall, firewall, and ProgramData state"
        )
        scenario = @(
            "baseline clean install proves deferred service/firewall/configuration, then packaged setup auto-finalizes",
            "seed a database fixture through the API and archive the first scenario",
            "UpgradeArtifact clean install migrates the fixture on pristine no-ProgramData state",
            "same-version UpgradeArtifact invocation is rejected without state changes",
            "fresh baseline plus the same fixture establishes the real upgrade baseline",
            "separate preflight failure preserves the exact baseline state",
            "authorized watcher damages a distinct post-copy candidate and proves exact binary rollback",
            "successful upgrade creates a verified backup and preserves authoritative data",
            "downgrade is rejected without changing the upgraded state",
            "uninstall preserves data; reinstall proves it remains usable; final uninstall removes system integration"
        )
        health_surfaces = @(
            "https://127.0.0.1:<configured-port>/health",
            "https://<selected-Private-profile-IPv4>:<configured-port>/health"
        )
    }
    $Plan | ConvertTo-Json -Depth 8
    return
}

$ConsentEvidence = Assert-ExecutionConsent
if ($BaselineArtifact.signature_status -cne "Valid" -or $UpgradeArtifact.signature_status -cne "Valid") {
    if (-not $AllowUnsignedInstallers) {
        throw (
            "Both installers must have valid Authenticode signatures. " +
            "Use -AllowUnsignedInstallers only for an explicit development-artifact VM run."
        )
    }
    Write-Warning "Unsigned or invalidly signed development installers were explicitly allowed for this VM run."
}
$null = Assert-PristineProductState
Assert-TcpPortAvailable $DefaultServerPort
if ($ValidationPort -ne $DefaultServerPort) {
    Assert-TcpPortAvailable $ValidationPort
}
$PrivateNetwork = Get-PrivateNetworkEvidence
$script:ValidationContext.PrivateNetwork = $PrivateNetwork

# Require absence again immediately before the first write. ValidateOnly never
# reaches this gate and therefore never creates WorkRoot.
$ResolvedWorkRoot = Assert-SafeWorkRoot $ResolvedWorkRoot -RequireAbsent
New-Item -ItemType Directory -Path $ResolvedWorkRoot | Out-Null
Set-RestrictedValidationAcl $ResolvedWorkRoot
Assert-RestrictedValidationAcl $ResolvedWorkRoot
Assert-NoReparseAncestors $ResolvedWorkRoot
$RunId = "{0}-{1}" -f [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ"), ([Guid]::NewGuid().ToString("N").Substring(0, 8))
$script:RunRoot = Assert-ChildPath $ResolvedWorkRoot (Join-Path $ResolvedWorkRoot "run-$RunId") "Run directory"
Assert-NoReparseAncestors $script:RunRoot
if (Test-Path -LiteralPath $script:RunRoot) {
    throw "Run directory must be initially absent: $script:RunRoot"
}
New-Item -ItemType Directory -Path $script:RunRoot | Out-Null
$LogsRoot = Assert-NewScenarioPath (Join-Path $script:RunRoot "Logs") "Logs root"
New-Item -ItemType Directory -Path $LogsRoot | Out-Null
$script:ValidationContext.Consent = $ConsentEvidence

Start-Transcript -LiteralPath (Join-Path $LogsRoot "validation-transcript.log") | Out-Null
$script:TranscriptStarted = $true
$script:OverallStatus = "running"

try {
    $null = Invoke-ValidationPhase "baseline-deferred-setup-and-seeded-fixture" {
        $Roots = New-ScenarioRoots "bootstrap-baseline"
        $Install = Invoke-InstallerExecutable `
            -Installer $BaselineArtifact.path `
            -LogPath (Join-Path $LogsRoot "01-baseline-install.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "01-baseline-install-process.log")
        if ($Install.ExitCode -ne 0) {
            throw "Baseline installer exited with code $($Install.ExitCode)."
        }
        $Deferred = Assert-DeferredFirstInstallState -ExpectedVersion $BaselineVersion
        $SetupStarted = [DateTimeOffset]::UtcNow
        $null = Invoke-PackagedServerSetup `
            -ProcessOutputPath (Join-Path $LogsRoot "01-baseline-server-setup-process.log") `
            -MissionRoot $Roots.mission_root `
            -BackupRoot $Roots.backup_root
        Assert-ServiceRegistration -ExpectedVersion $BaselineVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $BaselineVersion
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        if ($ValidationPort -ne $DefaultServerPort) {
            Assert-NoServerFirewallRule -Port $DefaultServerPort
        }

        $Headers = New-ApiValidationCredential -Port $ValidationPort
        $SeedTime = [DateTimeOffset]::UtcNow
        $MissionaryCode = $SeedTime.ToUnixTimeMilliseconds().ToString()
        $PassportNumber = "VALIDATION-$RunId"
        $SeedResponse = Invoke-LocalRestMethod `
            -Method POST `
            -Uri "https://127.0.0.1:$ValidationPort/v1/missionaries" `
            -Headers $Headers `
            -Body @{
                full_name = "Installer Validation Sentinel"
                missionary_code = $MissionaryCode
                nationality = "PER"
                passport_number = $PassportNumber
            }
        if ([string]$SeedResponse.missionary_code -cne $MissionaryCode) {
            throw "The API did not persist the seeded record."
        }
        $Relocation = Test-LocalSystemMissionRootRelocation `
            -Port $ValidationPort `
            -Headers $Headers `
            -MissionaryId ([int]$SeedResponse.id) `
            -ExpectedRoot $Roots.mission_root `
            -RunToken $RunId
        $MirrorBackup = Wait-ServiceCreatedMirrorBackup `
            -NotBefore $SetupStarted `
            -BackupRoot $Roots.backup_root

        Stop-ServerServiceAndWait
        $FixtureRoot = Assert-NewScenarioPath (Join-Path $script:RunRoot "Fixtures") "Fixture directory"
        New-Item -ItemType Directory -Path $FixtureRoot | Out-Null
        $DatabaseFixture = Join-Path $FixtureRoot "seeded-existing-app.db"
        Copy-Item -LiteralPath (Join-Path $ExpectedDataRoot "app.db") -Destination $DatabaseFixture
        Assert-NoReparseAncestors $DatabaseFixture
        $FixtureHash = (Get-FileHash -LiteralPath $DatabaseFixture -Algorithm SHA256).Hash.ToLowerInvariant()

        $Uninstall = Invoke-UninstallerExecutable `
            -LogPath (Join-Path $LogsRoot "01-bootstrap-uninstall.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "01-bootstrap-uninstall-process.log")
        if ($Uninstall.ExitCode -ne 0) {
            throw "Bootstrap uninstaller exited with code $($Uninstall.ExitCode)."
        }
        Assert-ServerUninstalled
        $Archive = Archive-ProductData "bootstrap-baseline"
        $null = Assert-PristineProductState

        $script:ValidationContext.MissionaryCode = $MissionaryCode
        $script:ValidationContext.PassportNumber = $PassportNumber
        $script:ValidationContext.SeededMissionaryId = [int]$SeedResponse.id
        $script:ValidationContext.DatabaseFixture = $DatabaseFixture
        $script:ValidationContext.DatabaseFixtureSha256 = $FixtureHash
        [pscustomobject]@{
            deferred_first_install = $Deferred
            health = $Health
            firewall_rule = $Firewall
            seeded_missionary_id = $SeedResponse.id
            seeded_database_fixture = $DatabaseFixture
            fixture_sha256 = $FixtureHash
            local_system_folder_relocation = $Relocation
            local_system_mirror_backup = $MirrorBackup
            archived_program_data = $Archive
            pristine_after_archive = $true
        }
    }

    $null = Invoke-ValidationPhase "upgrade-artifact-pristine-migration-and-same-version-rejection" {
        $null = Assert-PristineProductState
        $Roots = New-ScenarioRoots "candidate-pristine"
        $Install = Invoke-InstallerExecutable `
            -Installer $UpgradeArtifact.path `
            -LogPath (Join-Path $LogsRoot "02-candidate-pristine-install.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "02-candidate-pristine-install-process.log")
        if ($Install.ExitCode -ne 0) {
            throw "UpgradeArtifact pristine installer exited with code $($Install.ExitCode)."
        }
        $Deferred = Assert-DeferredFirstInstallState -ExpectedVersion $UpgradeVersion
        $null = Invoke-PackagedServerSetup `
            -ProcessOutputPath (Join-Path $LogsRoot "02-candidate-pristine-server-setup-process.log") `
            -MissionRoot $Roots.mission_root `
            -BackupRoot $Roots.backup_root `
            -ExistingDatabase $script:ValidationContext.DatabaseFixture
        if ((Get-FileHash -LiteralPath $script:ValidationContext.DatabaseFixture -Algorithm SHA256).Hash.ToLowerInvariant() -cne $script:ValidationContext.DatabaseFixtureSha256) {
            throw "The existing-database fixture was modified by UpgradeArtifact setup."
        }
        Assert-ServiceRegistration -ExpectedVersion $UpgradeVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $UpgradeVersion
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $Headers = New-ApiValidationCredential -Port $ValidationPort
        $Record = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $Headers `
            -MissionaryCode $script:ValidationContext.MissionaryCode `
            -PassportNumber $script:ValidationContext.PassportNumber
        if ([int]$Record.id -ne $script:ValidationContext.SeededMissionaryId) {
            throw "UpgradeArtifact pristine migration changed the seeded row identity."
        }
        $DataAclBeforeSameVersion = Assert-ServerDataAclPolicy

        $BeforeSameVersionTree = Get-InstallTreeInventory
        $FixtureDocument = Join-Path ([string]$Record.folder_path) "relocation-sentinel-$RunId.txt"
        $BeforeSameVersionData = Get-PersistenceHashMap -DocumentPath $FixtureDocument -IncludeDatabase
        $SameVersion = Invoke-InstallerExecutable `
            -Installer $UpgradeArtifact.path `
            -LogPath (Join-Path $LogsRoot "02-same-version-rejection.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "02-same-version-rejection-process.log")
        if ($SameVersion.ExitCode -eq 0) {
            throw "The installed UpgradeArtifact unexpectedly accepted the same version."
        }
        $null = Assert-InstallTreeMatches -Expected $BeforeSameVersionTree -Description "Same-version rejection"
        $null = Assert-PreservedFiles -ExpectedHashes $BeforeSameVersionData
        Assert-ServiceRegistration -ExpectedVersion $UpgradeVersion -ExpectedState "Running"
        $null = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $UpgradeVersion
        $null = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $null = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $Headers `
            -MissionaryCode $script:ValidationContext.MissionaryCode `
            -PassportNumber $script:ValidationContext.PassportNumber
        $DataAclAfterSameVersion = Assert-ServerDataAclPolicy

        $Uninstall = Invoke-UninstallerExecutable `
            -LogPath (Join-Path $LogsRoot "02-candidate-pristine-uninstall.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "02-candidate-pristine-uninstall-process.log")
        if ($Uninstall.ExitCode -ne 0) {
            throw "UpgradeArtifact pristine uninstaller exited with code $($Uninstall.ExitCode)."
        }
        Assert-ServerUninstalled
        $Archive = Archive-ProductData "candidate-pristine"
        $null = Assert-PristineProductState
        [pscustomobject]@{
            deferred_first_install = $Deferred
            health = $Health
            firewall_rule = $Firewall
            migrated_missionary_id = $Record.id
            fixture_source_unchanged = $true
            same_version_exit_code = $SameVersion.ExitCode
            same_version_tree_fingerprint = $BeforeSameVersionTree.fingerprint_sha256
            same_version_state_unchanged = $true
            data_acl_before_same_version = $DataAclBeforeSameVersion
            data_acl_after_same_version = $DataAclAfterSameVersion
            archived_program_data = $Archive
        }
    }

    $null = Invoke-ValidationPhase "fresh-baseline-from-same-fixture" {
        $null = Assert-PristineProductState
        $Roots = New-ScenarioRoots "baseline-upgrade"
        $Install = Invoke-InstallerExecutable `
            -Installer $BaselineArtifact.path `
            -LogPath (Join-Path $LogsRoot "03-baseline-upgrade-install.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "03-baseline-upgrade-install-process.log")
        if ($Install.ExitCode -ne 0) {
            throw "Upgrade-scenario baseline installer exited with code $($Install.ExitCode)."
        }
        $Deferred = Assert-DeferredFirstInstallState -ExpectedVersion $BaselineVersion
        $SetupStarted = [DateTimeOffset]::UtcNow
        $null = Invoke-PackagedServerSetup `
            -ProcessOutputPath (Join-Path $LogsRoot "03-baseline-upgrade-server-setup-process.log") `
            -MissionRoot $Roots.mission_root `
            -BackupRoot $Roots.backup_root `
            -ExistingDatabase $script:ValidationContext.DatabaseFixture
        if ((Get-FileHash -LiteralPath $script:ValidationContext.DatabaseFixture -Algorithm SHA256).Hash.ToLowerInvariant() -cne $script:ValidationContext.DatabaseFixtureSha256) {
            throw "The shared existing-database fixture was modified by baseline setup."
        }
        Assert-ServiceRegistration -ExpectedVersion $BaselineVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $BaselineVersion
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $Headers = New-ApiValidationCredential -Port $ValidationPort
        $MigratedRecord = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $Headers `
            -MissionaryCode $script:ValidationContext.MissionaryCode `
            -PassportNumber $script:ValidationContext.PassportNumber
        if ([int]$MigratedRecord.id -ne $script:ValidationContext.SeededMissionaryId) {
            throw "Fresh baseline migration changed the seeded row identity."
        }

        $UpgradeCode = ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() + 1).ToString()
        $UpgradePassport = "UPGRADE-$RunId"
        $UpgradeRecord = Invoke-LocalRestMethod `
            -Method POST `
            -Uri "https://127.0.0.1:$ValidationPort/v1/missionaries" `
            -Headers $Headers `
            -Body @{
                full_name = "Upgrade Rollback Sentinel"
                missionary_code = $UpgradeCode
                nationality = "PER"
                passport_number = $UpgradePassport
            }
        $Relocation = Test-LocalSystemMissionRootRelocation `
            -Port $ValidationPort `
            -Headers $Headers `
            -MissionaryId ([int]$UpgradeRecord.id) `
            -ExpectedRoot $Roots.mission_root `
            -RunToken "upgrade-$RunId"
        $MirrorBackup = Wait-ServiceCreatedMirrorBackup `
            -NotBefore $SetupStarted `
            -BackupRoot $Roots.backup_root

        # Establish the byte-exact database baseline only after a clean service
        # shutdown has checkpointed and released SQLite. Restart afterward so
        # the installer still owns the stop/recovery behavior under test.
        Stop-ServerServiceAndWait
        $BaselineTree = Get-InstallTreeInventory
        $BaselineServicePath = Join-Path $InstallDir "MissionLegalService.exe"
        $BaselineServiceSha256 = (Get-FileHash -LiteralPath $BaselineServicePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $PreservedHashes = Get-PersistenceHashMap -DocumentPath $Relocation.sentinel_path
        $FailureHashes = Get-PersistenceHashMap -DocumentPath $Relocation.sentinel_path -IncludeDatabase
        Start-Service -Name $ServiceName -ErrorAction Stop
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $BaselineVersion
        Assert-ServiceRegistration -ExpectedVersion $BaselineVersion -ExpectedState "Running"
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $script:ValidationContext.ApiHeaders = $Headers
        $script:ValidationContext.UpgradeMissionaryCode = $UpgradeCode
        $script:ValidationContext.UpgradePassportNumber = $UpgradePassport
        $script:ValidationContext.UpgradeMissionaryId = [int]$UpgradeRecord.id
        $script:ValidationContext.DocumentPath = $Relocation.sentinel_path
        $script:ValidationContext.PreservedHashes = $PreservedHashes
        $script:ValidationContext.FailureHashes = $FailureHashes
        $script:ValidationContext.BaselineInstallTree = $BaselineTree
        $script:ValidationContext.BaselineServiceSha256 = $BaselineServiceSha256
        $script:ValidationContext.BaselineSchemaVersion = [string]$Health.schema_version
        [pscustomobject]@{
            deferred_first_install = $Deferred
            health = $Health
            firewall_rule = $Firewall
            migrated_fixture_row_id = $MigratedRecord.id
            rollback_sentinel_row_id = $UpgradeRecord.id
            local_system_folder_relocation = $Relocation
            local_system_mirror_backup = $MirrorBackup
            baseline_tree_file_count = $BaselineTree.file_count
            baseline_tree_fingerprint = $BaselineTree.fingerprint_sha256
            baseline_service_sha256 = $BaselineServiceSha256
        }
    }

    $null = Invoke-ValidationPhase "preflight-upgrade-failure-preserves-baseline" {
        $BackupDir = Assert-ChildPath $ExpectedDataRoot (Join-Path $ExpectedDataRoot "Backups") "Backup directory"
        $SavedBackupDir = Assert-ChildPath $ExpectedDataRoot (Join-Path $ExpectedDataRoot "Backups.validation-saved-$RunId") "Saved backup directory"
        Assert-NoReparseAncestors $BackupDir
        if (-not (Test-Path -LiteralPath $BackupDir -PathType Container)) {
            throw "Configured backup directory is missing before preflight failure injection: $BackupDir"
        }
        if (Test-Path -LiteralPath $SavedBackupDir) {
            throw "Preflight failure save path already exists: $SavedBackupDir"
        }
        $FailureResult = $null
        Move-Item -LiteralPath $BackupDir -Destination $SavedBackupDir
        New-Item -ItemType File -Path $BackupDir | Out-Null
        try {
            $FailureResult = Invoke-InstallerExecutable `
                -Installer $UpgradeArtifact.path `
                -LogPath (Join-Path $LogsRoot "04-preflight-failure.log") `
                -ProcessOutputPath (Join-Path $LogsRoot "04-preflight-failure-process.log")
        }
        finally {
            if (Test-Path -LiteralPath $BackupDir -PathType Leaf) {
                Remove-Item -LiteralPath $BackupDir -Force
            }
            elseif (Test-Path -LiteralPath $BackupDir) {
                throw "Preflight blocker changed type unexpectedly: $BackupDir"
            }
            if (Test-Path -LiteralPath $SavedBackupDir -PathType Container) {
                Move-Item -LiteralPath $SavedBackupDir -Destination $BackupDir
            }
        }
        if ($null -eq $FailureResult -or $FailureResult.ExitCode -eq 0) {
            throw "Upgrade unexpectedly succeeded while preflight backup gates were blocked."
        }
        $Tree = Assert-InstallTreeMatches `
            -Expected $script:ValidationContext.BaselineInstallTree `
            -Description "Preflight failure"
        if ((Get-FileHash -LiteralPath (Join-Path $InstallDir "MissionLegalService.exe") -Algorithm SHA256).Hash.ToLowerInvariant() -cne $script:ValidationContext.BaselineServiceSha256) {
            throw "Preflight failure changed the baseline service executable."
        }
        $null = Assert-PreservedFiles -ExpectedHashes $script:ValidationContext.FailureHashes
        Assert-ServiceRegistration -ExpectedVersion $BaselineVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $BaselineVersion
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $null = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $script:ValidationContext.ApiHeaders `
            -MissionaryCode $script:ValidationContext.UpgradeMissionaryCode `
            -PassportNumber $script:ValidationContext.UpgradePassportNumber
        [pscustomobject]@{
            expected_failure_exit_code = $FailureResult.ExitCode
            exact_baseline_tree_restored = $true
            tree_fingerprint = $Tree.fingerprint_sha256
            service_binary_unchanged = $true
            authoritative_database_unchanged = $true
            health = $Health
            firewall_rule = $Firewall
        }
    }

    $null = Invoke-ValidationPhase "post-copy-upgrade-failure-rolls-back-exact-baseline" {
        $FailureStarted = [DateTimeOffset]::UtcNow
        $FailureLog = Join-Path $LogsRoot "05-post-copy-failure.log"
        $Injection = Invoke-PostCopyUpgradeFailure `
            -LogPath $FailureLog `
            -InstallerOutputPath (Join-Path $LogsRoot "05-post-copy-failure-process.log") `
            -WatcherOutputPath (Join-Path $LogsRoot "05-post-copy-watcher-process.log") `
            -BaselineServiceSha256 $script:ValidationContext.BaselineServiceSha256 `
            -BaselineDatabaseSha256 ([string]$script:ValidationContext["FailureHashes"]["authoritative_database"]["sha256"])
        $Tree = Assert-InstallTreeMatches `
            -Expected $script:ValidationContext.BaselineInstallTree `
            -Description "Post-copy rollback"
        if ((Get-FileHash -LiteralPath (Join-Path $InstallDir "MissionLegalService.exe") -Algorithm SHA256).Hash.ToLowerInvariant() -cne $script:ValidationContext.BaselineServiceSha256) {
            throw "Post-copy rollback did not restore the exact baseline service executable."
        }
        $null = Assert-PreservedFiles `
            -ExpectedHashes $script:ValidationContext.FailureHashes `
            -ExcludeDatabaseHash
        $RollbackReceipt = Get-VerifiedRollbackReceipt `
            -NotBefore $FailureStarted `
            -ExpectedSourceVersion $BaselineVersion `
            -ExpectedTargetVersion $UpgradeVersion `
            -ExpectedSourceDatabaseSha256 ([string]$script:ValidationContext["FailureHashes"]["authoritative_database"]["sha256"]) `
            -InstallerLogPath $FailureLog
        Assert-ServiceRegistration -ExpectedVersion $BaselineVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $BaselineVersion
        if ([string]$Health.schema_version -cne [string]$script:ValidationContext.BaselineSchemaVersion) {
            throw "Post-copy rollback did not restore the baseline database schema version."
        }
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $Record = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $script:ValidationContext.ApiHeaders `
            -MissionaryCode $script:ValidationContext.UpgradeMissionaryCode `
            -PassportNumber $script:ValidationContext.UpgradePassportNumber
        $SeededRecord = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $script:ValidationContext.ApiHeaders `
            -MissionaryCode $script:ValidationContext.MissionaryCode `
            -PassportNumber $script:ValidationContext.PassportNumber
        if (-not (Test-Path -LiteralPath $script:ValidationContext.DocumentPath -PathType Leaf)) {
            throw "Post-copy rollback lost the mission-document sentinel."
        }
        [pscustomobject]@{
            injection = $Injection
            exact_baseline_tree_restored = $true
            tree_fingerprint = $Tree.fingerprint_sha256
            exact_service_binary_restored = $true
            installed_version_restored = $BaselineVersion
            candidate_database_mutation_sha256 = $Injection.watcher_evidence.database_mutated_sha256
            restored_database_receipt = $RollbackReceipt
            authoritative_database_restored_from_exact_snapshot = $true
            database_schema_version_restored = [string]$Health.schema_version
            pre_upgrade_rows_restored = @($SeededRecord.id, $Record.id)
            preserved_missionary_id = $Record.id
            health = $Health
            firewall_rule = $Firewall
        }
    }

    $null = Invoke-ValidationPhase "successful-upgrade" {
        $UpgradeStarted = [DateTimeOffset]::UtcNow
        $Result = Invoke-InstallerExecutable `
            -Installer $UpgradeArtifact.path `
            -LogPath (Join-Path $LogsRoot "06-successful-upgrade.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "06-successful-upgrade-process.log")
        if ($Result.ExitCode -ne 0) {
            throw "Upgrade installer exited with code $($Result.ExitCode)."
        }
        Assert-ServiceRegistration -ExpectedVersion $UpgradeVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $UpgradeVersion
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $Record = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $script:ValidationContext.ApiHeaders `
            -MissionaryCode $script:ValidationContext.UpgradeMissionaryCode `
            -PassportNumber $script:ValidationContext.UpgradePassportNumber
        if (-not (Test-Path -LiteralPath $script:ValidationContext.DocumentPath -PathType Leaf)) {
            throw "Successful upgrade lost the mission-document sentinel."
        }
        $UpgradeBackup = Get-VerifiedUpgradeBackup `
            -NotBefore $UpgradeStarted `
            -ExpectedSourceVersion $BaselineVersion `
            -ExpectedTargetVersion $UpgradeVersion `
            -ExpectedSourceDatabaseSha256 ([string]$script:ValidationContext["FailureHashes"]["authoritative_database"]["sha256"])
        $null = Assert-PreservedFiles -ExpectedHashes $script:ValidationContext.PreservedHashes
        $PostUpgradeHashes = Get-PersistenceHashMap -DocumentPath $script:ValidationContext.DocumentPath
        $DataAcl = Assert-ServerDataAclPolicy
        $UpgradedTree = Get-InstallTreeInventory
        $script:ValidationContext.PreservedHashes = $PostUpgradeHashes
        $script:ValidationContext.UpgradedInstallTree = $UpgradedTree
        $script:ValidationContext.UpgradeBackup = $UpgradeBackup
        [pscustomobject]@{
            health = $Health
            firewall_rule = $Firewall
            preserved_missionary_id = $Record.id
            document_preserved = $true
            tls_configuration_and_credentials_preserved = $true
            server_data_acl = $DataAcl
            verified_upgrade_backup = $UpgradeBackup
            upgraded_tree_fingerprint = $UpgradedTree.fingerprint_sha256
        }
    }

    $null = Invoke-ValidationPhase "downgrade-rejected-with-upgraded-state-unchanged" {
        $Result = Invoke-InstallerExecutable `
            -Installer $BaselineArtifact.path `
            -LogPath (Join-Path $LogsRoot "07-downgrade-rejection.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "07-downgrade-rejection-process.log")
        if ($Result.ExitCode -eq 0) {
            throw "The older baseline installer unexpectedly downgraded the upgraded server."
        }
        $Tree = Assert-InstallTreeMatches `
            -Expected $script:ValidationContext.UpgradedInstallTree `
            -Description "Downgrade rejection"
        $null = Assert-PreservedFiles -ExpectedHashes $script:ValidationContext.PreservedHashes
        Assert-ServiceRegistration -ExpectedVersion $UpgradeVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $UpgradeVersion
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $Record = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $script:ValidationContext.ApiHeaders `
            -MissionaryCode $script:ValidationContext.UpgradeMissionaryCode `
            -PassportNumber $script:ValidationContext.UpgradePassportNumber
        $DataAcl = Assert-ServerDataAclPolicy
        [pscustomobject]@{
            expected_failure_exit_code = $Result.ExitCode
            installed_version_remained = $Health.app_version
            exact_upgraded_tree_unchanged = $true
            tree_fingerprint = $Tree.fingerprint_sha256
            preserved_missionary_id = $Record.id
            firewall_rule = $Firewall
            server_data_acl = $DataAcl
        }
    }

    $null = Invoke-ValidationPhase "uninstall-preserves-data" {
        $Result = Invoke-UninstallerExecutable `
            -LogPath (Join-Path $LogsRoot "08-uninstall.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "08-uninstall-process.log")
        if ($Result.ExitCode -ne 0) {
            throw "Uninstaller exited with code $($Result.ExitCode)."
        }
        Assert-ServerUninstalled
        $Preserved = Assert-PreservedFiles -ExpectedHashes $script:ValidationContext.PreservedHashes
        $DataAcl = Assert-ServerDataAclPolicy
        [pscustomobject]@{
            service_removed = $true
            binaries_removed = $true
            firewall_rule_removed = $true
            program_data_preserved = $true
            database_size = $Preserved.database_size
            backup_count = $Preserved.preserved_backup_count
            server_data_acl = $DataAcl
        }
    }

    $null = Invoke-ValidationPhase "reinstall-proves-preserved-data" {
        $Result = Invoke-InstallerExecutable `
            -Installer $UpgradeArtifact.path `
            -LogPath (Join-Path $LogsRoot "09-reinstall.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "09-reinstall-process.log")
        if ($Result.ExitCode -ne 0) {
            throw "Reinstall exited with code $($Result.ExitCode)."
        }
        Assert-ServiceRegistration -ExpectedVersion $UpgradeVersion -ExpectedState "Running"
        $Health = Wait-ServerHealthSurfaces -Port $ValidationPort -ExpectedVersion $UpgradeVersion
        $Firewall = Assert-PrivateServerFirewallRule -Port $ValidationPort
        $Record = Assert-SentinelApiRecord `
            -Port $ValidationPort `
            -Headers $script:ValidationContext.ApiHeaders `
            -MissionaryCode $script:ValidationContext.UpgradeMissionaryCode `
            -PassportNumber $script:ValidationContext.UpgradePassportNumber
        $null = Assert-PreservedFiles -ExpectedHashes $script:ValidationContext.PreservedHashes
        $DataAcl = Assert-ServerDataAclPolicy
        [pscustomobject]@{
            health = $Health
            firewall_rule = $Firewall
            preserved_missionary_id = $Record.id
            original_device_credential_still_valid = $true
            document_still_present = $true
            server_data_acl = $DataAcl
        }
    }

    $null = Invoke-ValidationPhase "final-uninstall" {
        $Result = Invoke-UninstallerExecutable `
            -LogPath (Join-Path $LogsRoot "10-final-uninstall.log") `
            -ProcessOutputPath (Join-Path $LogsRoot "10-final-uninstall-process.log")
        if ($Result.ExitCode -ne 0) {
            throw "Final uninstaller exited with code $($Result.ExitCode)."
        }
        Assert-ServerUninstalled
        $Preserved = Assert-PreservedFiles -ExpectedHashes $script:ValidationContext.PreservedHashes
        $DataAcl = Assert-ServerDataAclPolicy
        [pscustomobject]@{
            service_removed = $true
            binaries_removed = $true
            firewall_rule_removed = $true
            program_data_preserved = $true
            database = $Preserved.database
            database_size = $Preserved.database_size
            backup_count = $Preserved.preserved_backup_count
            document = $script:ValidationContext.DocumentPath
            server_data_acl = $DataAcl
        }
    }

    $script:OverallStatus = "passed"
}
catch {
    $script:OverallStatus = "failed"
    $script:FailureMessage = $_.Exception.Message
    throw
}
finally {
    $ResultWriteError = $null
    try {
        Write-ValidationResult
    }
    catch {
        $ResultWriteError = $_
        Write-Warning "Could not write validation result JSON: $($_.Exception.Message)"
    }
    finally {
        if ($script:TranscriptStarted) {
            Stop-Transcript | Out-Null
        }
    }
    if ($null -ne $ResultWriteError -and $script:OverallStatus -ceq "passed") {
        throw $ResultWriteError
    }
}

Write-Host "Server installer VM validation passed."
Write-Host "Revert this disposable VM to its clean snapshot; preserved data was not deleted."
