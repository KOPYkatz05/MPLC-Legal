import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from database.runtime import get_app_data_dir


SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
USERS_SID = "S-1-5-32-545"
PUBLIC_CA_RELATIVE_PATH = Path("Public") / "mission-legal-ca.pem"
PUBLIC_CA_ROLLBACK_NAME = ".mission-legal-public-ca.rollback"


class ServerDataAclError(RuntimeError):
    pass


_WINDOWS_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
trap {
    $ErrorRecord = $_
    [Console]::Error.WriteLine($ErrorRecord.ToString())
    if (
        $null -ne $ErrorRecord.InvocationInfo -and
        -not [string]::IsNullOrWhiteSpace(
            $ErrorRecord.InvocationInfo.PositionMessage
        )
    ) {
        [Console]::Error.WriteLine($ErrorRecord.InvocationInfo.PositionMessage)
    }
    if (-not [string]::IsNullOrWhiteSpace($ErrorRecord.ScriptStackTrace)) {
        [Console]::Error.WriteLine(
            "PowerShell stack: $($ErrorRecord.ScriptStackTrace)"
        )
    }
    exit 1
}

$SystemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$AdministratorsSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$UsersSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-545')
$FullControl = [Security.AccessControl.FileSystemRights]::FullControl
$ReadAndExecute = [Security.AccessControl.FileSystemRights]::ReadAndExecute
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

function Test-WriteCapableFileSystemRights {
    param([Parameter(Mandatory = $true)][long]$Rights)

    # Do not use the composite Modify right here. It includes the read and
    # execute bits, so ReadAndExecute would be misclassified as writable.
    return (($Rights -band $WriteCapableRightsMask) -ne 0)
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
        if (
            Test-WriteCapableFileSystemRights -Rights $RightsBySid[$UsersSid.Value]
        ) {
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
    # Windows PowerShell 5.1 cannot materialize a Generic.List[object] of
    # PSCustomObjects with @($Items); its binder throws "Argument types do not
    # match." Convert to a normal Object[] before returning it to the pipeline.
    return $Items.ToArray()
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


def _path_entry_exists(path):
    return os.path.lexists(path)


def _is_reparse_point(path):
    details = os.lstat(path)
    if stat.S_ISLNK(details.st_mode):
        return True
    attributes = getattr(details, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_attribute and attributes & reparse_attribute)


def _assert_normal_file(path, *, label, allow_missing=False):
    if not _path_entry_exists(path):
        if allow_missing:
            return False
        raise ServerDataAclError(f"{label} is missing: {path}")
    if _is_reparse_point(path):
        raise ServerDataAclError(f"{label} is a reparse point: {path}")
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise ServerDataAclError(f"{label} is not a normal file: {path}")
    return True


def _assert_normal_directory(path, *, label):
    if not _path_entry_exists(path):
        raise ServerDataAclError(f"{label} is missing: {path}")
    if _is_reparse_point(path):
        raise ServerDataAclError(f"{label} is a reparse point: {path}")
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        raise ServerDataAclError(f"{label} is not a normal directory: {path}")


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


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.digest()


def _copy_file_exclusive(source, destination):
    with destination.open("xb") as destination_stream:
        with source.open("rb") as source_stream:
            shutil.copyfileobj(source_stream, destination_stream)
        destination_stream.flush()
        os.fsync(destination_stream.fileno())
    destination.chmod(0o600)


def _remove_known_publication_file(path, *, label):
    if not _assert_normal_file(path, label=label, allow_missing=True):
        return
    path.unlink()


def _prepare_public_ca_directory(
    root,
    source,
    public_root,
    destination,
    temporary,
):
    if _is_windows():
        _invoke_windows_acl(
            "PreparePublic",
            (root, source, public_root, destination, temporary),
        )
        return

    if _path_entry_exists(public_root):
        _assert_normal_directory(public_root, label="Public CA directory")
    else:
        public_root.mkdir(parents=True, exist_ok=False)
    public_root.chmod(0o700)
    for path in public_root.iterdir():
        if _is_reparse_point(path):
            raise ServerDataAclError(
                f"Public CA directory contains a reparse point: {path}"
            )
        if path not in (destination, temporary):
            raise ServerDataAclError(
                f"Public CA directory contains an unexpected item: {path}"
            )
        _assert_normal_file(path, label="Public CA publication file")
        path.chmod(0o600)


def _protect_public_ca(public_root, destination):
    if _is_windows():
        _invoke_windows_acl("ProtectPublic", (public_root, destination))
    else:
        _assert_normal_directory(public_root, label="Public CA directory")
        _assert_normal_file(destination, label="Published CA certificate")
        destination.chmod(0o644)
        public_root.chmod(0o755)


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
    if (
        supplied_source.is_symlink()
        or not _path_entry_exists(source)
        or _is_reparse_point(source)
        or not source.is_file()
    ):
        raise ServerDataAclError(f"CA certificate is missing or unsafe: {source}")

    destination = public_ca_path(root)
    public_root = destination.parent
    temporary = destination.with_name(f".{destination.name}.tmp")
    rollback = root / PUBLIC_CA_ROLLBACK_NAME
    if source in (destination, temporary, rollback):
        raise ServerDataAclError(
            f"CA certificate conflicts with a reserved publication path: {source}"
        )
    prepared = False
    had_destination = False
    committed = False
    rollback_owned = False
    previous_digest = None

    protect_sensitive_server_data(root)

    try:
        _prepare_public_ca_directory(
            root,
            source,
            public_root,
            destination,
            temporary,
        )
        prepared = True
        had_destination = _assert_normal_file(
            destination,
            label="Published CA certificate",
            allow_missing=True,
        )
        _remove_known_publication_file(
            temporary,
            label="Public CA staging file",
        )

        if _assert_normal_file(
            rollback,
            label="Public CA rollback file",
            allow_missing=True,
        ):
            if _path_entry_exists(destination):
                _assert_normal_file(
                    destination,
                    label="Interrupted published CA certificate",
                )
            os.replace(rollback, destination)
            had_destination = True
            _protect_public_ca(public_root, destination)
            _prepare_public_ca_directory(
                root,
                source,
                public_root,
                destination,
                temporary,
            )

        source_digest = _file_sha256(source)
        if had_destination:
            previous_digest = _file_sha256(destination)
            if previous_digest == source_digest:
                _protect_public_ca(public_root, destination)
                if _file_sha256(destination) != source_digest:
                    raise ServerDataAclError(
                        "Published CA certificate changed during verification"
                    )
                return destination

        _copy_file_exclusive(source, temporary)
        staged_digest = _file_sha256(temporary)
        if staged_digest != source_digest or _file_sha256(source) != source_digest:
            raise ServerDataAclError(
                "CA certificate changed while the public copy was staged"
            )

        if had_destination:
            rollback_owned = True
            _copy_file_exclusive(destination, rollback)
            if _is_windows():
                _invoke_windows_acl("ProtectPrivate", (rollback,))
            else:
                rollback.chmod(0o600)
            if (
                _file_sha256(rollback) != previous_digest
                or _file_sha256(destination) != previous_digest
            ):
                raise ServerDataAclError(
                    "Existing public CA certificate changed while it was preserved"
                )

        os.replace(temporary, destination)
        committed = True
        _protect_public_ca(public_root, destination)
        if _file_sha256(destination) != staged_digest:
            raise ServerDataAclError(
                "Published CA certificate failed post-commit hash verification"
            )
        _remove_known_publication_file(
            rollback,
            label="Public CA rollback file",
        )
        return destination
    except Exception as error:
        recovery_errors = []
        try:
            _remove_known_publication_file(
                temporary,
                label="Public CA staging file",
            )
        except Exception as cleanup_error:
            recovery_errors.append(f"staging cleanup failed: {cleanup_error}")

        if committed:
            if had_destination:
                try:
                    _assert_normal_file(
                        rollback,
                        label="Public CA rollback file",
                    )
                    if _path_entry_exists(destination):
                        _assert_normal_file(
                            destination,
                            label="Failed published CA certificate",
                        )
                    os.replace(rollback, destination)
                    if (
                        previous_digest is not None
                        and _file_sha256(destination) != previous_digest
                    ):
                        raise ServerDataAclError(
                            "Restored public CA certificate failed hash verification"
                        )
                except Exception as rollback_error:
                    recovery_errors.append(
                        f"prior CA restoration failed: {rollback_error}"
                    )
            else:
                try:
                    _remove_known_publication_file(
                        destination,
                        label="Failed published CA certificate",
                    )
                except Exception as removal_error:
                    recovery_errors.append(
                        f"failed CA removal failed: {removal_error}"
                    )
        elif rollback_owned:
            try:
                _remove_known_publication_file(
                    rollback,
                    label="Public CA rollback file",
                )
            except Exception as cleanup_error:
                recovery_errors.append(f"rollback cleanup failed: {cleanup_error}")

        if prepared and had_destination and _path_entry_exists(destination):
            try:
                _protect_public_ca(public_root, destination)
            except Exception as acl_error:
                recovery_errors.append(f"prior CA ACL restoration failed: {acl_error}")

        if recovery_errors:
            detail = "; ".join(recovery_errors)
            raise ServerDataAclError(
                f"Public CA publication failed: {error}. Recovery also failed: {detail}"
            ) from error
        raise
