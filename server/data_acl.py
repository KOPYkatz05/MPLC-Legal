import json
import os
import shutil
import subprocess
from pathlib import Path

from database.runtime import get_app_data_dir


SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
USERS_SID = "S-1-5-32-545"
PUBLIC_CA_RELATIVE_PATH = Path("Public") / "mission-legal-ca.pem"


class ServerDataAclError(RuntimeError):
    pass


_WINDOWS_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
trap {
    [Console]::Error.WriteLine($_.ToString())
    exit 1
}

$SystemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$AdministratorsSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$UsersSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-545')
$FullControl = [Security.AccessControl.FileSystemRights]::FullControl
$ReadAndExecute = [Security.AccessControl.FileSystemRights]::ReadAndExecute
$AllowedType = [Security.AccessControl.AccessControlType]::Allow
$NoInheritance = [Security.AccessControl.InheritanceFlags]::None
$ContainerAndObjectInheritance = (
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
)
$NoPropagation = [Security.AccessControl.PropagationFlags]::None
$ReparsePoint = [IO.FileAttributes]::ReparsePoint
$Mode = [string]$env:MISSION_LEGAL_ACL_MODE
$DecodedPaths = $env:MISSION_LEGAL_ACL_PATHS | ConvertFrom-Json -ErrorAction Stop
$Paths = @()
foreach ($DecodedPath in $DecodedPaths) {
    # Windows PowerShell 5.1 returns a JSON array as one nested Object[] when
    # it is wrapped directly in @(...). Flatten it explicitly so each ACL
    # target remains one path string.
    $Paths += [string]$DecodedPath
}

function Assert-NormalItem {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Directory
    )

    $PathType = if ($Directory) { 'Container' } else { 'Leaf' }
    if (-not (Test-Path -LiteralPath $Path -PathType $PathType)) {
        throw "Required ACL target is missing or has the wrong type: $Path"
    }
    $Item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($Item.Attributes -band $ReparsePoint) -ne 0) {
        throw "Refusing to apply a server-data ACL through a reparse point: $Path"
    }
}

function New-ExactAcl {
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
        $ContainerAndObjectInheritance
    }
    else {
        $NoInheritance
    }
    foreach ($Sid in @($SystemSid, $AdministratorsSid)) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $Sid,
            $FullControl,
            $Inheritance,
            $NoPropagation,
            $AllowedType
        )
        [void]$Acl.AddAccessRule($Rule)
    }
    if ($PublicRead) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $UsersSid,
            $ReadAndExecute,
            $Inheritance,
            $NoPropagation,
            $AllowedType
        )
        [void]$Acl.AddAccessRule($Rule)
    }
    return $Acl
}

function Assert-ExactAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Directory,
        [Parameter(Mandatory = $true)][bool]$PublicRead
    )

    Assert-NormalItem -Path $Path -Directory $Directory
    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if (-not $Acl.AreAccessRulesProtected) {
        throw "ACL inheritance remains enabled: $Path"
    }
    $Owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($Owner.Value -cne $AdministratorsSid.Value) {
        throw "ACL owner is not Builtin Administrators: $Path"
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
        if ($Rule.AccessControlType -ne $AllowedType) {
            throw "ACL contains a deny rule: $Path"
        }
        if ($SidValue -cnotin $AllowedSids) {
            throw "ACL grants access to an unexpected SID '$SidValue': $Path"
        }
        if ($Rule.IsInherited) {
            throw "ACL still contains an inherited rule: $Path"
        }
        if (-not $RightsBySid.ContainsKey($SidValue)) {
            $RightsBySid[$SidValue] = [long]0
        }
        $RightsBySid[$SidValue] = (
            [long]$RightsBySid[$SidValue] -bor [long]$Rule.FileSystemRights
        )
    }
    foreach ($Sid in @($SystemSid, $AdministratorsSid)) {
        if (
            -not $RightsBySid.ContainsKey($Sid.Value) -or
            (($RightsBySid[$Sid.Value] -band [long]$FullControl) -ne [long]$FullControl)
        ) {
            throw "ACL is missing FullControl for '$($Sid.Value)': $Path"
        }
    }
    if ($PublicRead) {
        if (
            -not $RightsBySid.ContainsKey($UsersSid.Value) -or
            (($RightsBySid[$UsersSid.Value] -band [long]$ReadAndExecute) -ne [long]$ReadAndExecute)
        ) {
            throw "Public ACL is missing Builtin Users read access: $Path"
        }
        $WriteMask = (
            [long][Security.AccessControl.FileSystemRights]::Write -bor
            [long][Security.AccessControl.FileSystemRights]::Modify -bor
            [long][Security.AccessControl.FileSystemRights]::Delete -bor
            [long][Security.AccessControl.FileSystemRights]::ChangePermissions -bor
            [long][Security.AccessControl.FileSystemRights]::TakeOwnership
        )
        if (($RightsBySid[$UsersSid.Value] -band $WriteMask) -ne 0) {
            throw "Public ACL grants Builtin Users write-capable access: $Path"
        }
    }
}

function Set-ExactAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Directory,
        [Parameter(Mandatory = $true)][bool]$PublicRead
    )

    Assert-NormalItem -Path $Path -Directory $Directory
    $Acl = New-ExactAcl -Directory $Directory -PublicRead $PublicRead
    Set-Acl -LiteralPath $Path -AclObject $Acl -ErrorAction Stop
    Assert-ExactAcl -Path $Path -Directory $Directory -PublicRead $PublicRead
}

function Get-SensitiveItems {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$PublicRoot
    )

    $Items = New-Object System.Collections.Generic.List[object]
    $Queue = New-Object System.Collections.Generic.Queue[string]
    $Queue.Enqueue($Root)
    while ($Queue.Count -gt 0) {
        $Current = $Queue.Dequeue()
        Assert-NormalItem -Path $Current -Directory $true
        $Items.Add([pscustomobject]@{ Path = $Current; Directory = $true })
        foreach ($Child in @(Get-ChildItem -LiteralPath $Current -Force -ErrorAction Stop)) {
            if (($Child.Attributes -band $ReparsePoint) -ne 0) {
                throw "Refusing to apply a server-data ACL through a reparse point: $($Child.FullName)"
            }
            if ($Child.FullName.Equals($PublicRoot, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            if ($Child.PSIsContainer) {
                $Queue.Enqueue($Child.FullName)
            }
            else {
                $Items.Add([pscustomobject]@{ Path = $Child.FullName; Directory = $false })
            }
        }
    }
    return @($Items)
}

switch ($Mode) {
    'ProtectSensitive' {
        if ($Paths.Count -ne 2) {
            throw 'ProtectSensitive requires the data root and public root.'
        }
        $Root = [IO.Path]::GetFullPath([string]$Paths[0])
        $PublicRoot = [IO.Path]::GetFullPath([string]$Paths[1])
        if (-not (Test-Path -LiteralPath $Root)) {
            New-Item -ItemType Directory -Path $Root -Force -ErrorAction Stop | Out-Null
        }
        $Items = @(Get-SensitiveItems -Root $Root -PublicRoot $PublicRoot)
        foreach ($Item in $Items) {
            Set-ExactAcl -Path $Item.Path -Directory $Item.Directory -PublicRead $false
        }
        foreach ($Item in $Items) {
            Assert-ExactAcl -Path $Item.Path -Directory $Item.Directory -PublicRead $false
        }
    }
    'ProtectPrivate' {
        if ($Paths.Count -lt 1) {
            throw 'ProtectPrivate requires at least one private-key path.'
        }
        foreach ($Path in $Paths) {
            Set-ExactAcl -Path ([IO.Path]::GetFullPath([string]$Path)) -Directory $false -PublicRead $false
        }
    }
    'PreparePublic' {
        if ($Paths.Count -ne 5) {
            throw 'PreparePublic requires root, source, public directory, destination, and temporary paths.'
        }
        $Root = [IO.Path]::GetFullPath([string]$Paths[0])
        $Source = [IO.Path]::GetFullPath([string]$Paths[1])
        $PublicRoot = [IO.Path]::GetFullPath([string]$Paths[2])
        $Destination = [IO.Path]::GetFullPath([string]$Paths[3])
        $Temporary = [IO.Path]::GetFullPath([string]$Paths[4])
        Assert-NormalItem -Path $Root -Directory $true
        Assert-NormalItem -Path $Source -Directory $false
        if (-not (Test-Path -LiteralPath $PublicRoot)) {
            New-Item -ItemType Directory -Path $PublicRoot -ErrorAction Stop | Out-Null
        }
        Set-ExactAcl -Path $PublicRoot -Directory $true -PublicRead $false
        foreach ($Child in @(Get-ChildItem -LiteralPath $PublicRoot -Force -ErrorAction Stop)) {
            if (($Child.Attributes -band $ReparsePoint) -ne 0) {
                throw "Public CA directory contains a reparse point: $($Child.FullName)"
            }
            if (
                -not $Child.FullName.Equals($Destination, [StringComparison]::OrdinalIgnoreCase) -and
                -not $Child.FullName.Equals($Temporary, [StringComparison]::OrdinalIgnoreCase)
            ) {
                throw "Public CA directory contains an unexpected item: $($Child.FullName)"
            }
            if ($Child.PSIsContainer) {
                throw "Public CA directory contains an unexpected directory: $($Child.FullName)"
            }
            Set-ExactAcl -Path $Child.FullName -Directory $false -PublicRead $false
        }
    }
    'ProtectPublic' {
        if ($Paths.Count -ne 2) {
            throw 'ProtectPublic requires the public directory and CA file.'
        }
        $PublicRoot = [IO.Path]::GetFullPath([string]$Paths[0])
        $Destination = [IO.Path]::GetFullPath([string]$Paths[1])
        Assert-NormalItem -Path $PublicRoot -Directory $true
        Assert-NormalItem -Path $Destination -Directory $false
        $Children = @(Get-ChildItem -LiteralPath $PublicRoot -Force -ErrorAction Stop)
        if ($Children.Count -ne 1 -or -not $Children[0].FullName.Equals(
            $Destination,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw 'Public CA directory must contain only the published CA certificate.'
        }
        Set-ExactAcl -Path $Destination -Directory $false -PublicRead $true
        Set-ExactAcl -Path $PublicRoot -Directory $true -PublicRead $true
        Assert-ExactAcl -Path $Destination -Directory $false -PublicRead $true
        Assert-ExactAcl -Path $PublicRoot -Directory $true -PublicRead $true
    }
    'ValidatePaths' {
        if ($Paths.Count -lt 1) {
            throw 'ValidatePaths requires at least one path.'
        }
        Write-Output ($Paths | ConvertTo-Json -Compress)
    }
    default {
        throw "Unknown Mission Legal ACL mode: $Mode"
    }
}
"""


def _absolute_path(path):
    expanded = Path(path).expanduser()
    return Path(os.path.abspath(expanded))


def _is_windows():
    return os.name == "nt"


def public_ca_path(data_dir=None):
    root = _absolute_path(data_dir or get_app_data_dir())
    return root / PUBLIC_CA_RELATIVE_PATH


def _powershell_executable():
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidate = (
            Path(system_root)
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        if candidate.is_file():
            return str(candidate)
    return "powershell.exe"


def _invoke_windows_acl(mode, paths):
    environment = os.environ.copy()
    environment.update(
        {
            "MISSION_LEGAL_ACL_MODE": mode,
            "MISSION_LEGAL_ACL_PATHS": json.dumps([str(Path(path)) for path in paths]),
        }
    )
    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _WINDOWS_ACL_SCRIPT,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise ServerDataAclError(f"Server data ACL enforcement failed: {detail}")
    return completed.stdout.strip()


def _protect_portable_tree(root, public_root):
    root.mkdir(parents=True, exist_ok=True)

    def visit(directory):
        if directory.is_symlink():
            raise ServerDataAclError(
                f"Refusing to apply a server-data ACL through a symbolic link: {directory}"
            )
        directory.chmod(0o700)
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if path == public_root:
                    if entry.is_symlink():
                        raise ServerDataAclError(
                            f"Public CA directory is a symbolic link: {path}"
                        )
                    continue
                if entry.is_symlink():
                    raise ServerDataAclError(
                        f"Refusing to apply a server-data ACL through a symbolic link: {path}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    visit(path)
                else:
                    path.chmod(0o600)

    visit(root)


def protect_sensitive_server_data(data_dir=None):
    root = _absolute_path(data_dir or get_app_data_dir())
    published_root = public_ca_path(root).parent
    if _is_windows():
        _invoke_windows_acl("ProtectSensitive", (root, published_root))
    else:
        _protect_portable_tree(root, published_root)
    return root


def protect_private_key_files(*paths):
    supplied = tuple(Path(path).expanduser() for path in paths)
    if not supplied:
        raise ValueError("At least one private-key path is required")
    resolved = tuple(_absolute_path(path) for path in supplied)
    for supplied_path, path in zip(supplied, resolved):
        if supplied_path.is_symlink():
            raise ServerDataAclError(f"Private-key file is a symbolic link: {path}")
        if not path.is_file() or path.is_symlink():
            raise ServerDataAclError(f"Private-key file is missing or unsafe: {path}")
    if _is_windows():
        _invoke_windows_acl("ProtectPrivate", resolved)
    else:
        for path in resolved:
            path.chmod(0o600)


def publish_public_ca(source_ca, data_dir=None):
    root = _absolute_path(data_dir or get_app_data_dir())
    supplied_source = Path(source_ca).expanduser()
    source = _absolute_path(supplied_source)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ServerDataAclError(
            f"CA certificate must be inside the protected server data root: {source}"
        ) from exc
    if supplied_source.is_symlink() or not source.is_file() or source.is_symlink():
        raise ServerDataAclError(f"CA certificate is missing or unsafe: {source}")

    destination = public_ca_path(root)
    public_root = destination.parent
    temporary = destination.with_name(f".{destination.name}.tmp")
    protect_sensitive_server_data(root)
    if _is_windows():
        _invoke_windows_acl(
            "PreparePublic",
            (root, source, public_root, destination, temporary),
        )
    else:
        if public_root.is_symlink():
            raise ServerDataAclError(f"Public CA directory is a symbolic link: {public_root}")
        public_root.mkdir(parents=True, exist_ok=True)
        unexpected = [
            path
            for path in public_root.iterdir()
            if path not in (destination, temporary)
        ]
        if unexpected:
            raise ServerDataAclError(
                f"Public CA directory contains an unexpected item: {unexpected[0]}"
            )
        public_root.chmod(0o700)
        for path in (destination, temporary):
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise ServerDataAclError(f"Public CA path is unsafe: {path}")
                path.chmod(0o600)

    if temporary.exists():
        temporary.unlink()
    try:
        with temporary.open("xb") as stream:
            with source.open("rb") as source_stream:
                shutil.copyfileobj(source_stream, stream)
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    if _is_windows():
        _invoke_windows_acl("ProtectPublic", (public_root, destination))
    else:
        destination.chmod(0o644)
        public_root.chmod(0o755)
    return destination
