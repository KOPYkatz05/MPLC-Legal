[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "RuntimeSelfTest",
        "ValidateManagerOperator",
        "StopManager",
        "RemoveLegacyManagerAutostart",
        "Stop",
        "InstallOrUpdate",
        "StartAndVerify",
        "StartOnly",
        "Remove"
    )]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [Parameter(Mandatory = $true)]
    [string]$DataDir,
    [Parameter(Mandatory = $true)]
    [string]$AppVersion,
    [string]$ManagerOperatorAccount,
    [string]$StateFile,
    [ValidateRange(10, 300)]
    [int]$ServiceTimeoutSeconds = 90,
    [ValidateRange(10, 600)]
    [int]$HealthTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

$ServiceName = "MissionLegalServer"
$FirewallRuleName = "MissionLegalServerHTTPS"
$FirewallRuleDisplayName = "Mission Legal Server HTTPS"
$DiscoveryFirewallRuleName = "MissionLegalServerDiscovery"
$DiscoveryFirewallRuleDisplayName = "Mission Legal Server Discovery"
$DiscoveryPort = 43876
$DataDir = [IO.Path]::GetFullPath(
    [Environment]::ExpandEnvironmentVariables($DataDir)
)
$ServiceExe = [IO.Path]::GetFullPath((Join-Path $InstallDir "MissionLegalService.exe"))
$ManagerExe = [IO.Path]::GetFullPath(
    (Join-Path $InstallDir "MissionLegalServerManager.exe")
)
$LogPath = Join-Path $DataDir "Logs\installer-service.log"
$PublicCaDirectory = Join-Path $DataDir "Public"
$PublicCaPath = Join-Path $PublicCaDirectory "mission-legal-ca.pem"
$PrivateCaPath = Join-Path $DataDir "Configuration\tls\mission-legal-ca.pem"
$ReadinessMarkerPath = Join-Path $DataDir "Configuration\installer-ready-v1.marker"
$ReadinessMarkerContent = "mission-legal-server-ready-v1"
$SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$AdministratorsSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
$UsersSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-545")
$WriteCapableRightsMask = (
    [long][Security.AccessControl.FileSystemRights]::WriteData -bor
    [long][Security.AccessControl.FileSystemRights]::AppendData -bor
    [long][Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
    [long][Security.AccessControl.FileSystemRights]::WriteAttributes -bor
    [long][Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
    [long][Security.AccessControl.FileSystemRights]::Delete -bor
    [long][Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [long][Security.AccessControl.FileSystemRights]::TakeOwnership
)

function Test-WriteCapableFileSystemRights {
    param([Parameter(Mandatory = $true)][long]$Rights)

    # Modify also contains read/execute bits, so it is not a valid mutation
    # mask. The explicit mask above still detects Modify and FullControl through
    # their constituent write, delete, and ownership-management permissions.
    return (($Rights -band $WriteCapableRightsMask) -ne 0)
}

function Write-InstallerLog {
    param([string]$Message)

    $Line = "{0} {1}" -f [DateTimeOffset]::UtcNow.ToString("o"), $Message
    Write-Output $Line
    try {
        if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) {
            return
        }
        $Parent = Split-Path -Parent $LogPath
        New-Item -ItemType Directory -Force -Path $Parent | Out-Null
        Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    }
    catch {
        # Inno Setup also keeps a mandatory setup/uninstall log.  Do not mask a
        # service result just because the secondary ProgramData log failed.
    }
}

function Assert-ManagerOperatorIsUser {
    if (
        [string]::IsNullOrWhiteSpace($ManagerOperatorAccount) -or
        $ManagerOperatorAccount.Length -gt 256 -or
        $ManagerOperatorAccount.IndexOfAny([char[]]"`0`r`n") -ge 0
    ) {
        throw "The Server Manager operator account is invalid."
    }
    if ($null -eq ("MissionLegalInstallerAccountResolver" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

public static class MissionLegalInstallerAccountResolver
{
    private const int ErrorInsufficientBuffer = 122;
    private const int SidTypeUser = 1;

    [DllImport(
        "advapi32.dll",
        CharSet = CharSet.Unicode,
        SetLastError = true)]
    private static extern bool LookupAccountName(
        string systemName,
        string accountName,
        byte[] sid,
        ref uint sidSize,
        StringBuilder referencedDomainName,
        ref uint referencedDomainNameSize,
        out int accountType);

    public static string ResolveUserSid(string accountName)
    {
        uint sidSize = 0;
        uint domainSize = 0;
        int accountType;
        LookupAccountName(
            null,
            accountName,
            null,
            ref sidSize,
            null,
            ref domainSize,
            out accountType);
        int firstError = Marshal.GetLastWin32Error();
        if (firstError != ErrorInsufficientBuffer || sidSize == 0)
        {
            throw new Win32Exception(firstError);
        }

        byte[] sid = new byte[sidSize];
        StringBuilder domain = new StringBuilder((int)Math.Max(domainSize, 1));
        if (!LookupAccountName(
            null,
            accountName,
            sid,
            ref sidSize,
            domain,
            ref domainSize,
            out accountType))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        if (accountType != SidTypeUser)
        {
            throw new InvalidOperationException(
                "The selected principal is not one Windows user account.");
        }
        return new SecurityIdentifier(sid, 0).Value;
    }
}
"@
    }
    $ResolvedSid = [MissionLegalInstallerAccountResolver]::ResolveUserSid(
        $ManagerOperatorAccount
    )
    if ([string]::IsNullOrWhiteSpace($ResolvedSid)) {
        throw "The Server Manager operator did not resolve to a user SID."
    }
    Write-InstallerLog "Verified that the Server Manager operator is one Windows user SID."
}

function Get-InstalledServerManagerProcesses {
    $Processes = @(
        Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "Name='MissionLegalServerManager.exe'" `
            -ErrorAction Stop
    )
    return @(
        $Processes | Where-Object {
            if ([string]::IsNullOrWhiteSpace([string]$_.ExecutablePath)) {
                return $false
            }
            try {
                $ExecutablePath = [IO.Path]::GetFullPath(
                    [Environment]::ExpandEnvironmentVariables(
                        [string]$_.ExecutablePath
                    )
                )
                return $ExecutablePath.Equals(
                    $ManagerExe,
                    [StringComparison]::OrdinalIgnoreCase
                )
            }
            catch {
                return $false
            }
        }
    )
}

function Stop-InstalledServerManagerProcesses {
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
    do {
        $Processes = @(Get-InstalledServerManagerProcesses)
        if ($Processes.Count -eq 0) {
            Write-InstallerLog (
                "No Server Manager process remains at the exact installed path."
            )
            return
        }
        foreach ($Process in $Processes) {
            $ExecutablePath = [IO.Path]::GetFullPath(
                [string]$Process.ExecutablePath
            )
            if (-not $ExecutablePath.Equals(
                $ManagerExe,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Refusing to stop a Server Manager process from another path."
            }
            Write-InstallerLog (
                "Stopping installed Server Manager process ID " +
                "$([uint32]$Process.ProcessId)."
            )
            Stop-Process `
                -Id ([uint32]$Process.ProcessId) `
                -Force `
                -ErrorAction Stop
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTimeOffset]::UtcNow -lt $Deadline)

    $Remaining = @(Get-InstalledServerManagerProcesses)
    if ($Remaining.Count -ne 0) {
        throw (
            "Server Manager processes remain at the exact installed path after " +
            "the shutdown timeout."
        )
    }
}

function Remove-LegacyServerManagerAutostart {
    $ValueName = "Mission Legal Server Manager"
    $ExpectedCommand = '"' + $ManagerExe + '" --startup'
    foreach ($Hive in @(
        Get-ChildItem -LiteralPath "Registry::HKEY_USERS" -ErrorAction Stop |
        Where-Object { $_.PSChildName -match "^S-1-\d+(?:-\d+)+$" }
    )) {
        $RunKey = (
            "Registry::HKEY_USERS\" + $Hive.PSChildName +
            "\Software\Microsoft\Windows\CurrentVersion\Run"
        )
        if (-not (Test-Path -LiteralPath $RunKey -PathType Container)) {
            continue
        }
        $Command = Get-ItemPropertyValue `
            -LiteralPath $RunKey `
            -Name $ValueName `
            -ErrorAction SilentlyContinue
        if (
            $null -ne $Command -and
            ([string]$Command).Trim().Equals(
                $ExpectedCommand,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            Remove-ItemProperty `
                -LiteralPath $RunKey `
                -Name $ValueName `
                -Force `
                -ErrorAction Stop
            Write-InstallerLog (
                "Removed an exact legacy per-user Server Manager startup entry."
            )
        }
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
        $Configuration = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        if (
            $null -eq $Configuration -or
            $Configuration -is [Array] -or
            $Configuration -is [string] -or
            $Configuration.GetType().IsValueType
        ) {
            throw "The root value must be a JSON object."
        }
        return $Configuration
    }
    catch {
        throw "Server configuration is unreadable at '$ConfigPath': $($_.Exception.Message)"
    }
}

function Get-ConfigurationPropertyValue {
    param(
        [Parameter(Mandatory = $true)][object]$Configuration,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $Property = $Configuration.PSObject.Properties[$Name]
    if ($null -eq $Property) {
        return $null
    }
    return $Property.Value
}

function Get-ConfiguredServerPort {
    $Port = 8765
    $Configuration = Get-ServerConfiguration
    if ($null -ne $Configuration) {
        $ConfiguredPort = Get-ConfigurationPropertyValue `
            -Configuration $Configuration `
            -Name "port"
        if ($null -ne $ConfiguredPort) {
            $ParsedPort = 0
            if (
                -not [int]::TryParse(
                    [string]$ConfiguredPort,
                    [ref]$ParsedPort
                )
            ) {
                throw "Configured server port is not an integer: $ConfiguredPort"
            }
            $Port = $ParsedPort
        }
    }
    if ($Port -lt 1 -or $Port -gt 65535) {
        throw "Configured server port is outside the valid TCP range: $Port"
    }
    return $Port
}

function Assert-NormalServerDataItem {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Directory
    )

    $PathType = if ($Directory) { "Container" } else { "Leaf" }
    if (-not (Test-Path -LiteralPath $Path -PathType $PathType)) {
        throw "Required server-data ACL target is missing or has the wrong type: $Path"
    }
    $Item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to apply a server-data ACL through a reparse point: $Path"
    }
}

function New-ExactServerDataAcl {
    param(
        [Parameter(Mandatory = $true)][bool]$Directory,
        [Parameter(Mandatory = $true)][bool]$PublicRead
    )

    $Acl = if ($Directory) {
        [Security.AccessControl.DirectorySecurity]::new()
    }
    else {
        [Security.AccessControl.FileSecurity]::new()
    }
    $Acl.SetOwner($AdministratorsSid)
    $Acl.SetAccessRuleProtection($true, $false)
    $Inheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    foreach ($Sid in @($SystemSid, $AdministratorsSid)) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $Sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $Inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$Acl.AddAccessRule($Rule)
    }
    if ($PublicRead) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $UsersSid,
            [Security.AccessControl.FileSystemRights]::ReadAndExecute,
            $Inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$Acl.AddAccessRule($Rule)
    }
    return $Acl
}

function Assert-ExactServerDataAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Directory,
        [Parameter(Mandatory = $true)][bool]$PublicRead
    )

    Assert-NormalServerDataItem -Path $Path -Directory $Directory
    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if (-not $Acl.AreAccessRulesProtected) {
        throw "Server-data ACL inheritance remains enabled: $Path"
    }
    $Owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($Owner.Value -cne $AdministratorsSid.Value) {
        throw "Server-data ACL owner is not Builtin Administrators: $Path"
    }
    $AllowedSids = @($SystemSid.Value, $AdministratorsSid.Value)
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
        if ($Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
            throw "Server-data ACL contains a deny rule: $Path"
        }
        if ($SidValue -cnotin $AllowedSids) {
            throw "Server-data ACL grants access to unexpected SID '$SidValue': $Path"
        }
        if ($Rule.IsInherited) {
            throw "Server-data ACL still contains an inherited rule: $Path"
        }
        if (-not $RightsBySid.ContainsKey($SidValue)) {
            $RightsBySid[$SidValue] = [long]0
        }
        $RightsBySid[$SidValue] = (
            [long]$RightsBySid[$SidValue] -bor [long]$Rule.FileSystemRights
        )
    }
    $FullControl = [long][Security.AccessControl.FileSystemRights]::FullControl
    foreach ($Sid in @($SystemSid, $AdministratorsSid)) {
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
        if (
            Test-WriteCapableFileSystemRights -Rights $RightsBySid[$UsersSid.Value]
        ) {
            throw "Public CA ACL grants Builtin Users write-capable access: $Path"
        }
    }
}

function Set-ExactServerDataAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Directory,
        [Parameter(Mandatory = $true)][bool]$PublicRead
    )

    Assert-NormalServerDataItem -Path $Path -Directory $Directory
    $Acl = New-ExactServerDataAcl -Directory $Directory -PublicRead $PublicRead
    Set-Acl -LiteralPath $Path -AclObject $Acl -ErrorAction Stop
    Assert-ExactServerDataAcl `
        -Path $Path `
        -Directory $Directory `
        -PublicRead $PublicRead
}

function Get-SensitiveServerDataItems {
    param(
        [string]$Root = $DataDir,
        [string]$ExcludedPublicRoot = $PublicCaDirectory
    )

    $Root = [IO.Path]::GetFullPath($Root)
    $ExcludedPublicRoot = [IO.Path]::GetFullPath($ExcludedPublicRoot)
    $Items = New-Object System.Collections.Generic.List[object]
    $Queue = New-Object System.Collections.Generic.Queue[string]
    $Queue.Enqueue($Root)
    while ($Queue.Count -gt 0) {
        $Current = $Queue.Dequeue()
        Assert-NormalServerDataItem -Path $Current -Directory $true
        $Items.Add([pscustomobject]@{ Path = $Current; Directory = $true })
        foreach ($Child in @(Get-ChildItem -LiteralPath $Current -Force -ErrorAction Stop)) {
            if (($Child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing to apply a server-data ACL through a reparse point: $($Child.FullName)"
            }
            if ($Child.FullName.Equals($ExcludedPublicRoot, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            if ($Child.PSIsContainer) {
                $Queue.Enqueue($Child.FullName)
            }
            else {
                $Items.Add([pscustomobject]@{
                    Path = $Child.FullName
                    Directory = $false
                })
            }
        }
    }
    # Windows PowerShell 5.1 cannot materialize a Generic.List[object] of
    # PSCustomObjects with @($Items); its binder throws "Argument types do not
    # match." Convert to a normal Object[] before returning it to the pipeline.
    return $Items.ToArray()
}

function Protect-MissionLegalServerData {
    if (-not (Test-Path -LiteralPath $DataDir)) {
        New-Item -ItemType Directory -Path $DataDir -Force -ErrorAction Stop |
            Out-Null
    }
    $Items = @(Get-SensitiveServerDataItems)
    foreach ($Item in $Items) {
        Set-ExactServerDataAcl `
            -Path $Item.Path `
            -Directory $Item.Directory `
            -PublicRead $false
    }
    foreach ($Item in $Items) {
        Assert-ExactServerDataAcl `
            -Path $Item.Path `
            -Directory $Item.Directory `
            -PublicRead $false
    }
    Write-InstallerLog (
        "Verified protected Builtin Administrators/LocalSystem-only ACLs " +
        "for sensitive server data at $DataDir."
    )
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash
}

function Invoke-PreparedFileCommit {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Rollback
    )

    if (Test-Path -LiteralPath $Rollback) {
        throw "Atomic file rollback path already exists: $Rollback"
    }
    if (Test-Path -LiteralPath $Destination) {
        # Windows PowerShell 5.1/.NET Framework rejects a null backup path for
        # File.Replace. A real same-volume rollback path is also what lets the
        # caller restore the prior bytes if a post-commit verification fails.
        [IO.File]::Replace($Candidate, $Destination, $Rollback, $true)
        return $true
    }
    [IO.File]::Move($Candidate, $Destination)
    return $false
}

function Publish-MissionLegalPublicCa {
    param([switch]$AllowMissing)

    if (-not (Test-Path -LiteralPath $PrivateCaPath -PathType Leaf)) {
        if ($AllowMissing) {
            Write-InstallerLog "Public CA publication is deferred until server TLS configuration exists."
            return $null
        }
        throw "Server CA certificate is missing after healthy startup: $PrivateCaPath"
    }
    Assert-NormalServerDataItem -Path $PrivateCaPath -Directory $false
    $PublicDirectoryCreated = -not (Test-Path -LiteralPath $PublicCaDirectory)
    if ($PublicDirectoryCreated) {
        New-Item -ItemType Directory -Path $PublicCaDirectory -ErrorAction Stop |
            Out-Null
    }
    Assert-NormalServerDataItem -Path $PublicCaDirectory -Directory $true
    Set-ExactServerDataAcl `
        -Path $PublicCaDirectory `
        -Directory $true `
        -PublicRead $false

    $Temporary = Join-Path $PublicCaDirectory ".mission-legal-ca.pem.tmp"
    $Rollback = Join-Path $PublicCaDirectory ".mission-legal-ca.pem.rollback"
    $AllowedPaths = @($PublicCaPath, $Temporary, $Rollback)
    $CommitOccurred = $false
    $DestinationCreated = $false
    $DestinationReplaced = $false
    $PreviousHash = $null
    try {
        foreach ($Child in @(
            Get-ChildItem -LiteralPath $PublicCaDirectory -Force -ErrorAction Stop
        )) {
            if (($Child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Public CA directory contains a reparse point: $($Child.FullName)"
            }
            $Allowed = $false
            foreach ($AllowedPath in $AllowedPaths) {
                if (
                    $Child.FullName.Equals(
                        $AllowedPath,
                        [StringComparison]::OrdinalIgnoreCase
                    )
                ) {
                    $Allowed = $true
                    break
                }
            }
            if (-not $Allowed) {
                throw "Public CA directory contains an unexpected item: $($Child.FullName)"
            }
            if ($Child.PSIsContainer) {
                throw "Public CA directory contains an unexpected directory: $($Child.FullName)"
            }
            Set-ExactServerDataAcl `
                -Path $Child.FullName `
                -Directory $false `
                -PublicRead $false
        }

        # Recover a transaction interrupted after File.Replace but before its
        # rollback file was removed. A matching destination is already committed;
        # otherwise restore the previous bytes before preparing a new candidate.
        if (Test-Path -LiteralPath $Rollback) {
            if (
                (Test-Path -LiteralPath $PublicCaPath) -and
                ((Get-Sha256Hex -Path $PublicCaPath) -ceq
                    (Get-Sha256Hex -Path $PrivateCaPath))
            ) {
                Remove-Item -LiteralPath $Rollback -Force -ErrorAction Stop
            }
            else {
                if (Test-Path -LiteralPath $PublicCaPath) {
                    Remove-Item -LiteralPath $PublicCaPath -Force -ErrorAction Stop
                }
                [IO.File]::Move($Rollback, $PublicCaPath)
            }
        }
        if (Test-Path -LiteralPath $Temporary) {
            Remove-Item -LiteralPath $Temporary -Force -ErrorAction Stop
        }

        $SourceHash = Get-Sha256Hex -Path $PrivateCaPath
        if (Test-Path -LiteralPath $PublicCaPath) {
            $PreviousHash = Get-Sha256Hex -Path $PublicCaPath
            if ($PreviousHash -ceq $SourceHash) {
                Set-ExactServerDataAcl `
                    -Path $PublicCaPath `
                    -Directory $false `
                    -PublicRead $true
                Set-ExactServerDataAcl `
                    -Path $PublicCaDirectory `
                    -Directory $true `
                    -PublicRead $true
                if (
                    (Get-Sha256Hex -Path $PrivateCaPath) -cne $SourceHash -or
                    (Get-Sha256Hex -Path $PublicCaPath) -cne $SourceHash
                ) {
                    throw "The server CA changed during idempotent public-CA verification."
                }
                Write-InstallerLog "Verified the existing read-only client CA certificate at $PublicCaPath."
                return $PublicCaPath
            }
        }

        Copy-Item `
            -LiteralPath $PrivateCaPath `
            -Destination $Temporary `
            -ErrorAction Stop
        Set-ExactServerDataAcl `
            -Path $Temporary `
            -Directory $false `
            -PublicRead $false
        if (
            (Get-Sha256Hex -Path $PrivateCaPath) -cne $SourceHash -or
            (Get-Sha256Hex -Path $Temporary) -cne $SourceHash
        ) {
            throw "The server CA changed while its public candidate was prepared."
        }

        $HadDestination = Test-Path -LiteralPath $PublicCaPath
        $DestinationReplaced = Invoke-PreparedFileCommit `
            -Candidate $Temporary `
            -Destination $PublicCaPath `
            -Rollback $Rollback
        $DestinationCreated = -not $HadDestination
        $CommitOccurred = $true
        if (
            (Get-Sha256Hex -Path $PrivateCaPath) -cne $SourceHash -or
            (Get-Sha256Hex -Path $PublicCaPath) -cne $SourceHash
        ) {
            throw "Published CA certificate does not match the protected server CA certificate."
        }

        Set-ExactServerDataAcl `
            -Path $PublicCaPath `
            -Directory $false `
            -PublicRead $true
        Set-ExactServerDataAcl `
            -Path $PublicCaDirectory `
            -Directory $true `
            -PublicRead $true
        if (
            (Get-Sha256Hex -Path $PrivateCaPath) -cne $SourceHash -or
            (Get-Sha256Hex -Path $PublicCaPath) -cne $SourceHash
        ) {
            throw "Published CA certificate changed during ACL verification."
        }
        if (Test-Path -LiteralPath $Rollback) {
            Remove-Item -LiteralPath $Rollback -Force -ErrorAction Stop
        }
        Write-InstallerLog "Published and verified the read-only client CA certificate at $PublicCaPath."
        return $PublicCaPath
    }
    catch {
        $PrimaryError = $_.Exception.Message
        $RecoveryErrors = [Collections.Generic.List[string]]::new()
        try {
            if (Test-Path -LiteralPath $PublicCaDirectory -PathType Container) {
                Set-ExactServerDataAcl `
                    -Path $PublicCaDirectory `
                    -Directory $true `
                    -PublicRead $false
            }
        }
        catch {
            $RecoveryErrors.Add("could not protect the public directory: $($_.Exception.Message)")
        }
        try {
            if (Test-Path -LiteralPath $Temporary) {
                Remove-Item -LiteralPath $Temporary -Force -ErrorAction Stop
            }
        }
        catch {
            $RecoveryErrors.Add("could not remove the CA candidate: $($_.Exception.Message)")
        }
        try {
            if (Test-Path -LiteralPath $Rollback) {
                if (Test-Path -LiteralPath $PublicCaPath) {
                    Remove-Item -LiteralPath $PublicCaPath -Force -ErrorAction Stop
                }
                [IO.File]::Move($Rollback, $PublicCaPath)
                if (
                    $null -ne $PreviousHash -and
                    (Get-Sha256Hex -Path $PublicCaPath) -cne $PreviousHash
                ) {
                    throw "Restored public CA does not match its pre-commit hash."
                }
            }
            elseif ($CommitOccurred -and $DestinationCreated) {
                if (Test-Path -LiteralPath $PublicCaPath) {
                    Remove-Item -LiteralPath $PublicCaPath -Force -ErrorAction Stop
                }
            }
            if (Test-Path -LiteralPath $PublicCaPath) {
                Set-ExactServerDataAcl `
                    -Path $PublicCaPath `
                    -Directory $false `
                    -PublicRead $true
                Set-ExactServerDataAcl `
                    -Path $PublicCaDirectory `
                    -Directory $true `
                    -PublicRead $true
            }
            elseif ($PublicDirectoryCreated) {
                Remove-Item `
                    -LiteralPath $PublicCaDirectory `
                    -Force `
                    -ErrorAction Stop
            }
        }
        catch {
            $RecoveryErrors.Add("could not restore the prior public CA state: $($_.Exception.Message)")
        }
        if ($RecoveryErrors.Count -gt 0) {
            throw (
                "Public CA publication failed: $PrimaryError Rollback also failed: " +
                ($RecoveryErrors.ToArray() -join "; ")
            )
        }
        throw "Public CA publication failed and the prior state was restored: $PrimaryError"
    }
}

function Test-MissionLegalReadinessMarker {
    if (-not (Test-Path -LiteralPath $ReadinessMarkerPath -PathType Leaf)) {
        return $false
    }
    Assert-NormalServerDataItem -Path $ReadinessMarkerPath -Directory $false
    return (
        [IO.File]::ReadAllText($ReadinessMarkerPath) -ceq
        $ReadinessMarkerContent
    )
}

function Set-MissionLegalReadinessMarker {
    $MarkerDirectory = Split-Path -Parent $ReadinessMarkerPath
    Assert-NormalServerDataItem -Path $MarkerDirectory -Directory $true
    $Temporary = "$ReadinessMarkerPath.tmp"
    $Rollback = "$ReadinessMarkerPath.rollback"
    foreach ($Path in @($ReadinessMarkerPath, $Temporary, $Rollback)) {
        if (Test-Path -LiteralPath $Path) {
            Assert-NormalServerDataItem -Path $Path -Directory $false
            Set-ExactServerDataAcl `
                -Path $Path `
                -Directory $false `
                -PublicRead $false
        }
    }

    # Resolve only installer-owned residue from an interrupted marker commit.
    if (Test-Path -LiteralPath $Rollback) {
        if (Test-MissionLegalReadinessMarker) {
            Remove-Item -LiteralPath $Rollback -Force -ErrorAction Stop
        }
        else {
            if (Test-Path -LiteralPath $ReadinessMarkerPath) {
                Remove-Item -LiteralPath $ReadinessMarkerPath -Force -ErrorAction Stop
            }
            [IO.File]::Move($Rollback, $ReadinessMarkerPath)
        }
    }
    if (Test-Path -LiteralPath $Temporary) {
        Remove-Item -LiteralPath $Temporary -Force -ErrorAction Stop
    }
    if (Test-MissionLegalReadinessMarker) {
        Set-ExactServerDataAcl `
            -Path $ReadinessMarkerPath `
            -Directory $false `
            -PublicRead $false
        Write-InstallerLog "Verified the protected server readiness marker."
        return
    }

    $CommitOccurred = $false
    $DestinationCreated = $false
    try {
        [IO.File]::WriteAllText(
            $Temporary,
            $ReadinessMarkerContent,
            [Text.UTF8Encoding]::new($false)
        )
        Set-ExactServerDataAcl `
            -Path $Temporary `
            -Directory $false `
            -PublicRead $false
        $HadDestination = Test-Path -LiteralPath $ReadinessMarkerPath
        $null = Invoke-PreparedFileCommit `
            -Candidate $Temporary `
            -Destination $ReadinessMarkerPath `
            -Rollback $Rollback
        $DestinationCreated = -not $HadDestination
        $CommitOccurred = $true
        if (-not (Test-MissionLegalReadinessMarker)) {
            throw "The committed readiness marker did not match its required content."
        }
        Set-ExactServerDataAcl `
            -Path $ReadinessMarkerPath `
            -Directory $false `
            -PublicRead $false
        if (Test-Path -LiteralPath $Rollback) {
            Remove-Item -LiteralPath $Rollback -Force -ErrorAction Stop
        }
        Write-InstallerLog "Created and verified the protected server readiness marker."
    }
    catch {
        $PrimaryError = $_.Exception.Message
        $RecoveryError = $null
        try {
            if (Test-Path -LiteralPath $Temporary) {
                Remove-Item -LiteralPath $Temporary -Force -ErrorAction Stop
            }
            if (Test-Path -LiteralPath $Rollback) {
                if (Test-Path -LiteralPath $ReadinessMarkerPath) {
                    Remove-Item `
                        -LiteralPath $ReadinessMarkerPath `
                        -Force `
                        -ErrorAction Stop
                }
                [IO.File]::Move($Rollback, $ReadinessMarkerPath)
                Set-ExactServerDataAcl `
                    -Path $ReadinessMarkerPath `
                    -Directory $false `
                    -PublicRead $false
            }
            elseif ($CommitOccurred -and $DestinationCreated) {
                if (Test-Path -LiteralPath $ReadinessMarkerPath) {
                    Remove-Item `
                        -LiteralPath $ReadinessMarkerPath `
                        -Force `
                        -ErrorAction Stop
                }
            }
        }
        catch {
            $RecoveryError = $_.Exception.Message
        }
        if ($null -ne $RecoveryError) {
            throw (
                "Readiness marker commit failed: $PrimaryError " +
                "Rollback also failed: $RecoveryError"
            )
        }
        throw "Readiness marker commit failed and prior state was restored: $PrimaryError"
    }
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
    $MissionStorageRoot = Get-ConfigurationPropertyValue `
        -Configuration $Configuration `
        -Name "mission_storage_root"
    $BackupDirectory = Get-ConfigurationPropertyValue `
        -Configuration $Configuration `
        -Name "onedrive_backup_dir"
    if (-not [string]::IsNullOrWhiteSpace([string]$MissionStorageRoot)) {
        Grant-SystemModifyAccess `
            -Path ([string]$MissionStorageRoot) `
            -Description "mission-storage"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$BackupDirectory)) {
        Grant-SystemModifyAccess `
            -Path ([string]$BackupDirectory) `
            -Description "mirrored-backup"
    }
}

function Set-MissionLegalFirewallRule {
    param([Parameter(Mandatory = $true)][int]$Port)

    foreach ($RuleName in @($FirewallRuleName, $DiscoveryFirewallRuleName)) {
        Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule -ErrorAction Stop
    }
    # Remove pre-stable-name/display-name rules created by older setup scripts.
    foreach ($DisplayName in @(
        $FirewallRuleDisplayName,
        $DiscoveryFirewallRuleDisplayName
    )) {
        Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule -ErrorAction Stop
    }

    New-NetFirewallRule `
        -Name $FirewallRuleName `
        -DisplayName $FirewallRuleDisplayName `
        -Description "Allows same-subnet authenticated Mission Legal clients to reach the HTTPS server." `
        -Group "Mission Legal" `
        -Enabled True `
        -Direction Inbound `
        -Action Allow `
        -Profile Any `
        -RemoteAddress LocalSubnet `
        -Protocol TCP `
        -LocalPort $Port | Out-Null

    New-NetFirewallRule `
        -Name $DiscoveryFirewallRuleName `
        -DisplayName $DiscoveryFirewallRuleDisplayName `
        -Description "Allows same-subnet Mission Legal discovery; the service responds only on trusted networks." `
        -Group "Mission Legal" `
        -Enabled True `
        -Direction Inbound `
        -Action Allow `
        -Profile Any `
        -RemoteAddress LocalSubnet `
        -Protocol UDP `
        -LocalPort $DiscoveryPort | Out-Null

    $ExpectedRules = @(
        @{
            Name = $FirewallRuleName
            DisplayName = $FirewallRuleDisplayName
            Protocols = @("TCP", "6")
            Port = $Port.ToString()
        },
        @{
            Name = $DiscoveryFirewallRuleName
            DisplayName = $DiscoveryFirewallRuleDisplayName
            Protocols = @("UDP", "17")
            Port = $DiscoveryPort.ToString()
        }
    )
    foreach ($Expected in $ExpectedRules) {
        $Matches = @(
            Get-NetFirewallRule `
                -DisplayName $Expected.DisplayName `
                -ErrorAction Stop
        )
        if ($Matches.Count -ne 1) {
            throw "Expected exactly one managed firewall rule named $($Expected.Name)."
        }
        $Rule = $Matches[0]
        $PortFilters = @($Rule | Get-NetFirewallPortFilter -ErrorAction Stop)
        $AddressFilters = @($Rule | Get-NetFirewallAddressFilter -ErrorAction Stop)
        $Protocol = if ($PortFilters.Count -eq 1) { [string]$PortFilters[0].Protocol } else { "" }
        $LocalPort = if ($PortFilters.Count -eq 1) { [string]$PortFilters[0].LocalPort } else { "" }
        $RemoteAddress = if ($AddressFilters.Count -eq 1) { [string]$AddressFilters[0].RemoteAddress } else { "" }
        if (
            [string]$Rule.Name -cne $Expected.Name -or
            [string]$Rule.Enabled -cne "True" -or
            [string]$Rule.Direction -cne "Inbound" -or
            [string]$Rule.Action -cne "Allow" -or
            [string]$Rule.Profile -cne "Any" -or
            $PortFilters.Count -ne 1 -or
            $Expected.Protocols -notcontains $Protocol -or
            $LocalPort -cne $Expected.Port -or
            $AddressFilters.Count -ne 1 -or
            $RemoteAddress -cne "LocalSubnet"
        ) {
            throw "Managed firewall rule $($Expected.Name) did not match the required same-subnet policy."
        }
    }
    Write-InstallerLog (
        "Verified LocalSubnet HTTPS TCP $Port and discovery UDP $DiscoveryPort firewall rules."
    )
}

function Remove-MissionLegalFirewallRule {
    foreach ($RuleName in @($FirewallRuleName, $DiscoveryFirewallRuleName)) {
        Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule -ErrorAction Stop
    }
    foreach ($DisplayName in @(
        $FirewallRuleDisplayName,
        $DiscoveryFirewallRuleDisplayName
    )) {
        Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule -ErrorAction Stop
    }
    $Remaining = @()
    $Remaining += @(
        Get-NetFirewallRule -DisplayName $FirewallRuleDisplayName -ErrorAction SilentlyContinue
    )
    $Remaining += @(
        Get-NetFirewallRule -DisplayName $DiscoveryFirewallRuleDisplayName -ErrorAction SilentlyContinue
    )
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

function Get-RunningServiceProcessId {
    $Info = Get-CimInstance `
        -ClassName Win32_Service `
        -Filter "Name='$ServiceName'" `
        -ErrorAction Stop
    if ([string]$Info.State -cne "Running" -or [uint32]$Info.ProcessId -eq 0) {
        throw (
            "Service $ServiceName is not backed by a running process " +
            "(state '$($Info.State)', PID '$($Info.ProcessId)')."
        )
    }
    return [uint32]$Info.ProcessId
}

function Assert-ServiceOwnsConfiguredListener {
    param([uint32]$ExpectedProcessId = 0)

    $ServiceProcessId = Get-RunningServiceProcessId
    if (
        $ExpectedProcessId -ne 0 -and
        $ServiceProcessId -ne $ExpectedProcessId
    ) {
        throw (
            "Service process changed during verification. Expected PID " +
            "$ExpectedProcessId, found $ServiceProcessId."
        )
    }
    $Port = Get-ConfiguredServerPort
    $Listeners = @(
        Get-NetTCPConnection `
            -State Listen `
            -LocalPort $Port `
            -ErrorAction Stop |
            Where-Object { [uint32]$_.OwningProcess -eq $ServiceProcessId }
    )
    if ($Listeners.Count -lt 1) {
        throw (
            "Service PID $ServiceProcessId does not own a listening TCP socket " +
            "on configured port $Port."
        )
    }
    return $ServiceProcessId
}

function Assert-ServiceRemainsStable {
    param(
        [Parameter(Mandatory = $true)][uint32]$ExpectedProcessId,
        [int]$Seconds = 3
    )

    Start-Sleep -Seconds $Seconds
    $null = Assert-ServiceOwnsConfiguredListener `
        -ExpectedProcessId $ExpectedProcessId
}

function Get-HealthUri {
    $HostName = "127.0.0.1"
    $Port = Get-ConfiguredServerPort
    $Configuration = Get-ServerConfiguration
    if ($null -ne $Configuration) {
        $ConfiguredHost = Get-ConfigurationPropertyValue `
            -Configuration $Configuration `
            -Name "host"
        if (-not [string]::IsNullOrWhiteSpace([string]$ConfiguredHost)) {
            if ([string]$ConfiguredHost -ceq "::") {
                $HostName = "::1"
            }
            elseif ([string]$ConfiguredHost -notin @("0.0.0.0", "localhost")) {
                $HostName = [string]$ConfiguredHost
            }
        }
    }
    if ($HostName.Contains(":")) {
        $HostName = "[$HostName]"
    }
    return "https://${HostName}:${Port}/health"
}

function Initialize-MissionLegalTlsValidator {
    if (-not (Test-Path -LiteralPath $PrivateCaPath -PathType Leaf)) {
        throw "Mission Legal private CA certificate is missing: $PrivateCaPath"
    }
    if ($null -eq ("MissionLegalInstallerTlsValidator" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Net;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;

public static class MissionLegalInstallerTlsValidator
{
    private static X509Certificate2 trustedCa;

    public static void Configure(string path)
    {
        if (trustedCa != null)
        {
            trustedCa.Dispose();
        }
        trustedCa = new X509Certificate2(path);
        ServicePointManager.ServerCertificateValidationCallback = Validate;
    }

    public static bool Validate(
        object sender,
        X509Certificate certificate,
        X509Chain ignoredChain,
        SslPolicyErrors policyErrors)
    {
        if (certificate == null || trustedCa == null)
        {
            return false;
        }
        if ((policyErrors & SslPolicyErrors.RemoteCertificateNotAvailable) != 0 ||
            (policyErrors & SslPolicyErrors.RemoteCertificateNameMismatch) != 0)
        {
            return false;
        }

        using (X509Certificate2 leaf = new X509Certificate2(certificate))
        using (X509Chain chain = new X509Chain())
        {
            chain.ChainPolicy.ExtraStore.Add(trustedCa);
            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
            chain.ChainPolicy.VerificationFlags =
                X509VerificationFlags.AllowUnknownCertificateAuthority;
            if (!chain.Build(leaf) || chain.ChainElements.Count == 0)
            {
                return false;
            }
            X509Certificate2 root =
                chain.ChainElements[chain.ChainElements.Count - 1].Certificate;
            return String.Equals(
                root.Thumbprint,
                trustedCa.Thumbprint,
                StringComparison.OrdinalIgnoreCase);
        }
    }
}
"@
    }
    [MissionLegalInstallerTlsValidator]::Configure($PrivateCaPath)
}

function Test-ServerHealth {
    $Uri = Get-HealthUri
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $PreviousCallback = [Net.ServicePointManager]::ServerCertificateValidationCallback
    $PreviousSecurityProtocol = [Net.ServicePointManager]::SecurityProtocol
    try {
        # PowerShell 5.1 cannot safely use a PowerShell script block as this
        # callback: Schannel invokes it on a networking thread without a
        # runspace, surfacing only "unexpected error occurred on a send".
        # The compiled callback also verifies the exact installer-owned CA
        # without placing that CA in the Windows machine trust store.
        Initialize-MissionLegalTlsValidator
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
                if ([string]::IsNullOrWhiteSpace([string]$Health.api_version)) {
                    throw "Health endpoint did not report an API version."
                }
                $ReportedSchemaVersion = 0
                if (
                    -not [int]::TryParse(
                        [string]$Health.schema_version,
                        [ref]$ReportedSchemaVersion
                    ) -or
                    $ReportedSchemaVersion -lt 1
                ) {
                    throw (
                        "Health endpoint reported invalid schema version " +
                        "'$($Health.schema_version)'."
                    )
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
        [Net.ServicePointManager]::SecurityProtocol = $PreviousSecurityProtocol
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

function Invoke-InstallerRuntimeSelfTest {
    if ($PSVersionTable.PSVersion.Major -ne 5) {
        throw (
            "Installer runtime self-test requires Windows PowerShell 5.1; found " +
            "$($PSVersionTable.PSVersion)."
        )
    }
    $TemporaryParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $SelfTestRoot = Join-Path (
        $TemporaryParent
    ) ("MissionLegalInstallerRuntimeSelfTest-" + [Guid]::NewGuid().ToString("N"))
    if (
        -not $SelfTestRoot.StartsWith(
            $TemporaryParent.TrimEnd("\") + "\",
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        (Test-Path -LiteralPath $SelfTestRoot)
    ) {
        throw "Could not allocate an isolated installer runtime self-test directory."
    }

    New-Item -ItemType Directory -Path $SelfTestRoot -ErrorAction Stop |
        Out-Null
    try {
        $InventoryRoot = Join-Path $SelfTestRoot "inventory"
        $InventoryPublic = Join-Path $InventoryRoot "Public"
        $InventoryNested = Join-Path $InventoryRoot "Backups"
        New-Item `
            -ItemType Directory `
            -Path $InventoryPublic, $InventoryNested `
            -ErrorAction Stop |
            Out-Null
        [IO.File]::WriteAllText(
            (Join-Path $InventoryNested "snapshot.db"),
            "fixture"
        )
        $Inventory = @(
            Get-SensitiveServerDataItems `
                -Root $InventoryRoot `
                -ExcludedPublicRoot $InventoryPublic
        )
        $InventoryMaterialized = (
            $Inventory -is [Array] -and
            $Inventory.Count -eq 3 -and
            -not (
                @($Inventory | Where-Object {
                    $_.Path.StartsWith(
                        $InventoryPublic,
                        [StringComparison]::OrdinalIgnoreCase
                    )
                }).Count
            )
        )
        if (-not $InventoryMaterialized) {
            throw "Sensitive-data inventory did not materialize as the expected Object array."
        }

        $ConfigurationRoot = Join-Path $SelfTestRoot "configuration-fixture"
        $ConfigurationDirectory = Join-Path $ConfigurationRoot "Configuration"
        $ConfigurationPath = Join-Path $ConfigurationDirectory "server.json"
        New-Item `
            -ItemType Directory `
            -Path $ConfigurationDirectory `
            -ErrorAction Stop |
            Out-Null
        $OriginalDataDir = $DataDir
        try {
            $DataDir = $ConfigurationRoot
            [IO.File]::WriteAllText(
                $ConfigurationPath,
                "{}",
                [Text.UTF8Encoding]::new($false)
            )
            $ConfigurationDefaultsPassed = (
                (Get-ConfiguredServerPort) -eq 8765
            )
            $UnicodeStorageRoot = Join-Path $SelfTestRoot "Perú Legalización"
            $UnicodeConfigurationJson = [ordered]@{
                mission_storage_root = $UnicodeStorageRoot
            } | ConvertTo-Json -Compress
            [IO.File]::WriteAllText(
                $ConfigurationPath,
                $UnicodeConfigurationJson,
                [Text.UTF8Encoding]::new($false)
            )
            $UnicodeConfiguration = Get-ServerConfiguration
            $UnicodeConfigurationPassed = (
                (Get-ConfigurationPropertyValue `
                    -Configuration $UnicodeConfiguration `
                    -Name "mission_storage_root") -ceq $UnicodeStorageRoot
            )
            [IO.File]::WriteAllText(
                $ConfigurationPath,
                "[]",
                [Text.UTF8Encoding]::new($false)
            )
            $ConfigurationValidationPassed = $false
            try {
                $null = Get-ServerConfiguration
            }
            catch {
                $ConfigurationValidationPassed = (
                    $_.Exception.Message -like "*root value must be a JSON object*"
                )
            }
        }
        finally {
            $DataDir = $OriginalDataDir
        }
        if (
            -not $ConfigurationDefaultsPassed -or
            -not $UnicodeConfigurationPassed -or
            -not $ConfigurationValidationPassed
        ) {
            throw "Server configuration compatibility self-test failed."
        }

        $Destination = Join-Path $SelfTestRoot "public-ca.pem"
        $Candidate = Join-Path $SelfTestRoot "public-ca.tmp"
        $Rollback = Join-Path $SelfTestRoot "public-ca.rollback"
        [IO.File]::WriteAllText($Candidate, "first")
        $FirstReplaced = Invoke-PreparedFileCommit `
            -Candidate $Candidate `
            -Destination $Destination `
            -Rollback $Rollback
        $FirstPublishPassed = (
            -not $FirstReplaced -and
            [IO.File]::ReadAllText($Destination) -ceq "first" -and
            -not (Test-Path -LiteralPath $Candidate) -and
            -not (Test-Path -LiteralPath $Rollback)
        )
        if (-not $FirstPublishPassed) {
            throw "First-publication atomic file commit failed."
        }

        $IdenticalPublishPassed = (
            (Get-Sha256Hex -Path $Destination) -ceq
            (Get-Sha256Hex -Path $Destination)
        )
        [IO.File]::WriteAllText($Candidate, "second")
        $SecondReplaced = Invoke-PreparedFileCommit `
            -Candidate $Candidate `
            -Destination $Destination `
            -Rollback $Rollback
        $RepublishPassed = (
            $SecondReplaced -and
            [IO.File]::ReadAllText($Destination) -ceq "second" -and
            [IO.File]::ReadAllText($Rollback) -ceq "first" -and
            -not (Test-Path -LiteralPath $Candidate)
        )
        if (-not $RepublishPassed) {
            throw "Existing-destination atomic file replacement failed."
        }
        Remove-Item -LiteralPath $Rollback -Force -ErrorAction Stop

        $PublicAcl = New-ExactServerDataAcl `
            -Directory $false `
            -PublicRead $true
        $UsersRules = @(
            @($PublicAcl.GetAccessRules(
                $true,
                $true,
                [Security.Principal.SecurityIdentifier]
            )) | Where-Object {
                $_.IdentityReference.Value -ceq $UsersSid.Value
            }
        )
        if ($UsersRules.Count -ne 1) {
            throw "Public ACL self-test did not create exactly one Builtin Users rule."
        }
        $RightsClassificationPassed = (
            -not (Test-WriteCapableFileSystemRights -Rights (
                [long]$UsersRules[0].FileSystemRights
            )) -and
            (Test-WriteCapableFileSystemRights -Rights (
                [long][Security.AccessControl.FileSystemRights]::Write
            )) -and
            (Test-WriteCapableFileSystemRights -Rights (
                [long][Security.AccessControl.FileSystemRights]::Modify
            )) -and
            (Test-WriteCapableFileSystemRights -Rights (
                [long][Security.AccessControl.FileSystemRights]::Delete
            )) -and
            (Test-WriteCapableFileSystemRights -Rights (
                [long][Security.AccessControl.FileSystemRights]::FullControl
            ))
        )
        if (-not $RightsClassificationPassed) {
            throw "Filesystem-rights classification self-test failed."
        }

        $ResidueCount = @(
            Get-ChildItem -LiteralPath $SelfTestRoot -Force |
            Where-Object { $_.Name -match "\.(tmp|rollback)$" }
        ).Count
        if ($ResidueCount -ne 0) {
            throw "Installer runtime self-test left transaction residue."
        }
        [ordered]@{
            status = "ok"
            action = "RuntimeSelfTest"
            powershell_major = [int]$PSVersionTable.PSVersion.Major
            inventory_materialized = [bool]$InventoryMaterialized
            configuration_defaults = [bool]$ConfigurationDefaultsPassed
            configuration_validation = [bool]$ConfigurationValidationPassed
            unicode_configuration = [bool]$UnicodeConfigurationPassed
            public_ca_first_publish = [bool]$FirstPublishPassed
            public_ca_identical_publish = [bool]$IdenticalPublishPassed
            public_ca_republish = [bool]$RepublishPassed
            rights_classification = [bool]$RightsClassificationPassed
            residue_count = [int]$ResidueCount
        } | ConvertTo-Json -Compress
    }
    finally {
        if (
            $SelfTestRoot.StartsWith(
                $TemporaryParent.TrimEnd("\") + "\",
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Test-Path -LiteralPath $SelfTestRoot -PathType Container)
        ) {
            Remove-Item `
                -LiteralPath $SelfTestRoot `
                -Recurse `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
}

try {
    if ($Action -eq "RuntimeSelfTest") {
        Invoke-InstallerRuntimeSelfTest
        exit 0
    }
    if ($Action -eq "ValidateManagerOperator") {
        Assert-ManagerOperatorIsUser
        exit 0
    }
    if ($Action -eq "StopManager") {
        Stop-InstalledServerManagerProcesses
        exit 0
    }
    if ($Action -eq "RemoveLegacyManagerAutostart") {
        Remove-LegacyServerManagerAutostart
        exit 0
    }
    if ($Action -in @("InstallOrUpdate", "StartAndVerify", "StartOnly")) {
        # Secure the root before the first ProgramData log write or service action.
        Protect-MissionLegalServerData
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
            $ServiceProcessId = Assert-ServiceOwnsConfiguredListener
            $null = Publish-MissionLegalPublicCa
            Test-ServerHealth
            Assert-ServiceRemainsStable `
                -ExpectedProcessId $ServiceProcessId `
                -Seconds 3
            Set-MissionLegalReadinessMarker
        }
        "StartOnly" {
            Start-ServiceAndWait
            $ServiceProcessId = Get-RunningServiceProcessId
            Start-Sleep -Seconds 3
            $StableProcessId = Get-RunningServiceProcessId
            if ($StableProcessId -ne $ServiceProcessId) {
                throw (
                    "Restored service process changed during its stability check. " +
                    "Expected PID $ServiceProcessId, found $StableProcessId."
                )
            }
            Write-InstallerLog "Restored service remained running during its stability check."
        }
        "Remove" {
            Remove-MissionLegalService
            Remove-MissionLegalFirewallRule
        }
    }
    Write-InstallerLog "Installer service action '$Action' completed."
}
catch {
    $Failure = $_
    $Location = if (
        $null -ne $Failure.InvocationInfo -and
        -not [string]::IsNullOrWhiteSpace(
            [string]$Failure.InvocationInfo.PositionMessage
        )
    ) {
        $Failure.InvocationInfo.PositionMessage.Trim()
    }
    else {
        "source location unavailable"
    }
    $Trace = if (
        -not [string]::IsNullOrWhiteSpace([string]$Failure.ScriptStackTrace)
    ) {
        $Failure.ScriptStackTrace.Trim()
    }
    else {
        "stack trace unavailable"
    }
    [Console]::Error.WriteLine(
        "Mission Legal installer action '$Action' failed: " +
        "$($Failure.Exception.Message)`n$Location`n$Trace"
    )
    exit 1
}
