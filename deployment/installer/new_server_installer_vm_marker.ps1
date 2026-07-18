[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [switch]$CreateMarker,
    [Parameter(Mandatory = $true)]
    [string]$DisposableVmConfirmation,
    [ValidateRange(1, 24)]
    [int]$ExpiresInHours = 8
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedConfirmation = "I CONFIRM THIS IS A DISPOSABLE MISSION LEGAL TEST VM"
$MarkerPurpose = "mission-legal-server-installer-validation"
$ProgramFilesRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
$ProgramDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData)
$MarkerDirectory = [IO.Path]::GetFullPath(
    (Join-Path $ProgramDataRoot "MissionLegalInstallerValidation")
)
$MarkerPath = Join-Path $MarkerDirectory "vm-consent.json"
$ServiceName = "MissionLegalServer"
$AppId = "{8A39739D-CBD2-4C38-AE5D-9DE7E69B29D5}_is1"
$AdministratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
$SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")

function Test-IsAdministrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-VirtualMachineIdentity {
    $Computer = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
    $Manufacturer = [string]$Computer.Manufacturer
    $Model = [string]$Computer.Model
    $Identity = "$Manufacturer $Model".ToLowerInvariant()
    $KnownVmPatterns = @(
        "virtual machine", "vmware", "virtualbox", "kvm", "qemu",
        "hvm domu", "parallels", "xen"
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

function Assert-NoReparseAncestors {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Current = [IO.Path]::GetFullPath($Path)
    while ($Current) {
        if (Test-Path -LiteralPath $Current) {
            $Item = Get-Item -LiteralPath $Current -Force
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Validation marker path contains a reparse point: $Current"
            }
        }
        $Parent = [IO.Directory]::GetParent($Current)
        if ($null -eq $Parent) {
            break
        }
        $Next = $Parent.FullName
        if ($Next -ieq $Current) {
            break
        }
        $Current = $Next
    }
}

function Set-RestrictedMarkerAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Container
    )

    if ($Container) {
        $Security = [Security.AccessControl.DirectorySecurity]::new()
        $Inheritance = (
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
        )
    }
    else {
        $Security = [Security.AccessControl.FileSecurity]::new()
        $Inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $Security.SetOwner($AdministratorsSid)
    $Security.SetAccessRuleProtection($true, $false)
    foreach ($Sid in @($AdministratorsSid, $SystemSid)) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $Sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $Inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$Security.AddAccessRule($Rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $Security -ErrorAction Stop
}

function Assert-RestrictedMarkerAcl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if (-not $Acl.AreAccessRulesProtected) {
        throw "Validation marker ACL inheritance is not protected: $Path"
    }
    $Owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($Owner.Value -notin @($AdministratorsSid.Value, $SystemSid.Value)) {
        throw "Validation marker owner is not Administrators or LocalSystem: $($Owner.Value)"
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
            throw "Validation marker ACL grants access outside Administrators/LocalSystem."
        }
    }
    foreach ($Sid in @($AdministratorsSid, $SystemSid)) {
        $Full = @($Rules | Where-Object {
            $_.IdentityReference.Value -ceq $Sid.Value -and
            ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
                [Security.AccessControl.FileSystemRights]::FullControl
        })
        if ($Full.Count -lt 1) {
            throw "Validation marker ACL is missing FullControl for $($Sid.Value)."
        }
    }
}

if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) {
    throw "The validation marker can only be created on Windows."
}
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    throw "Use 64-bit Windows PowerShell to create the validation marker."
}
if (-not $CreateMarker) {
    throw "Creating the VM marker requires the explicit -CreateMarker switch."
}
if ($DisposableVmConfirmation -cne $ExpectedConfirmation) {
    throw "The disposable-VM confirmation text did not match exactly."
}
if (-not (Test-IsAdministrator)) {
    throw "Open an elevated Windows PowerShell session before creating the VM marker."
}

$VmIdentity = Get-VirtualMachineIdentity
if (-not $VmIdentity.recognized) {
    throw (
        "This machine was not recognized as a virtual machine " +
        "(manufacturer '$($VmIdentity.manufacturer)', model '$($VmIdentity.model)'). " +
        "The marker was not created. Use a supported disposable VM."
    )
}

$UninstallPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$InstallDir = Join-Path $ProgramFilesRoot "Mission Legal\Server"
$DataDir = Join-Path $ProgramDataRoot "MissionLegal"
$ExistingState = @()
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    $ExistingState += "Windows service $ServiceName"
}
if (Test-Path -LiteralPath $UninstallPath) {
    $ExistingState += "Mission Legal Server uninstall registration"
}
if (Test-Path -LiteralPath $InstallDir) {
    $ExistingState += "server install directory $InstallDir"
}
if (Test-Path -LiteralPath $DataDir) {
    $ExistingState += "server data directory $DataDir"
}
if (@(Get-NetFirewallRule -Name "MissionLegalServerHTTPS" -ErrorAction SilentlyContinue).Count -gt 0) {
    $ExistingState += "Mission Legal Server firewall rule"
}
if ($ExistingState.Count -gt 0) {
    throw (
        "This VM is not pristine. Revert to a clean snapshot before validating: " +
        ($ExistingState -join "; ")
    )
}
if (Test-Path -LiteralPath $MarkerDirectory) {
    throw (
        "The dedicated validation-marker directory already exists: $MarkerDirectory. " +
        "Revert the disposable VM instead of overwriting or reusing consent state."
    )
}
Assert-NoReparseAncestors $MarkerDirectory

$MachineGuid = (
    Get-ItemPropertyValue `
        -LiteralPath "HKLM:\SOFTWARE\Microsoft\Cryptography" `
        -Name "MachineGuid" `
        -ErrorAction Stop
).ToString()
$Now = [DateTimeOffset]::UtcNow
$Payload = [ordered]@{
    schema_version = 1
    purpose = $MarkerPurpose
    computer_name = [Environment]::MachineName
    machine_guid = $MachineGuid
    created_at_utc = $Now.ToString("o")
    expires_at_utc = $Now.AddHours($ExpiresInHours).ToString("o")
    virtualization = [ordered]@{
        manufacturer = $VmIdentity.manufacturer
        model = $VmIdentity.model
    }
}

New-Item -ItemType Directory -Path $MarkerDirectory | Out-Null
Set-RestrictedMarkerAcl -Path $MarkerDirectory -Container $true
$Temporary = Join-Path $MarkerDirectory "vm-consent.json.tmp"
$Payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Temporary -Encoding UTF8
Move-Item -LiteralPath $Temporary -Destination $MarkerPath
Set-RestrictedMarkerAcl -Path $MarkerPath -Container $false
Assert-NoReparseAncestors $MarkerPath
Assert-RestrictedMarkerAcl $MarkerDirectory
Assert-RestrictedMarkerAcl $MarkerPath

Write-Host "Disposable-VM validation marker created: $MarkerPath"
Write-Host "Marker expires: $($Payload.expires_at_utc)"
Write-Host "Revert this VM to its clean snapshot after validation."
