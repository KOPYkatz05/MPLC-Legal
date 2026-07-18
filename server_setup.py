import argparse
import hashlib
import json
import os
import sqlite3
import socket
import subprocess
import sys
import uuid
from contextlib import closing
from pathlib import Path

from app_identity import APP, ORG
from version import APP_VERSION


SERVICE_NAME = "MissionLegalServer"
FIREWALL_RULE_NAME = "MissionLegalServerHTTPS"
FIREWALL_RULE_DISPLAY_NAME = "Mission Legal Server HTTPS"


class ServerSetupError(RuntimeError):
    pass


def _port(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


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


def _run_windows_powershell(script, *, environment=None, description):
    command_environment = os.environ.copy()
    command_environment.update(environment or {})
    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=command_environment,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise ServerSetupError(f"{description} failed: {detail}")
    return completed.stdout.strip()


def _installed_service_helper(
    *,
    frozen=None,
    executable=None,
    installed_root=None,
):
    if os.name != "nt":
        return None
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return None
    executable_path = Path(executable or sys.executable).resolve()
    if installed_root is None:
        program_files = os.environ.get("ProgramFiles")
        if not program_files:
            return None
        installed_root = Path(program_files) / "Mission Legal" / "Server"
    installed_root = Path(installed_root).expanduser().resolve()
    if executable_path.parent != installed_root:
        return None
    helper = (
        installed_root
        / "InstallerSupport"
        / "server_installer_actions.ps1"
    )
    return helper if helper.is_file() else None


def _run_installed_service_action(
    helper,
    action,
    *,
    data_dir,
    app_version=APP_VERSION,
):
    helper = Path(helper).resolve()
    install_dir = helper.parent.parent.resolve()
    data_dir = Path(data_dir).expanduser().resolve()
    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-Action",
            action,
            "-InstallDir",
            str(install_dir),
            "-DataDir",
            str(data_dir),
            "-AppVersion",
            str(app_version),
        ],
        cwd=str(install_dir),
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise ServerSetupError(
            f"Installed service action {action} failed: {detail}"
        )
    output = completed.stdout.strip()
    if output:
        print(output)
    return output


def _finish_installed_service_setup(
    data_dir,
    *,
    helper=None,
    app_version=APP_VERSION,
):
    if helper is None:
        helper = _installed_service_helper()
    if helper is None:
        return False

    _run_installed_service_action(
        helper,
        "InstallOrUpdate",
        data_dir=data_dir,
        app_version=app_version,
    )
    try:
        _run_installed_service_action(
            helper,
            "StartAndVerify",
            data_dir=data_dir,
            app_version=app_version,
        )
    except Exception:
        try:
            _run_installed_service_action(
                helper,
                "Stop",
                data_dir=data_dir,
                app_version=app_version,
            )
        except Exception as stop_error:
            print(
                "WARNING: The failed server service could not be stopped: "
                f"{stop_error}"
            )
        raise
    return True


def _assert_server_service_stopped():
    if os.name != "nt":
        return
    script = rf"""
$ErrorActionPreference = 'Stop'
$service = Get-Service -Name '{SERVICE_NAME}' -ErrorAction SilentlyContinue
if ($null -eq $service) {{
    Write-Output 'absent'
    exit 0
}}
if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {{
    throw "Service {SERVICE_NAME} must be stopped before replacing the authoritative database; current state: $($service.Status)."
}}
Write-Output 'stopped'
"""
    _run_windows_powershell(
        script,
        description=f"Checking the {SERVICE_NAME} service state",
    )


def _assert_windows_host_prerequisites():
    if os.name != "nt":
        return
    script = r"""
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Mission Legal Server setup must run from an elevated Administrator PowerShell window.'
}
$requiredCommands = @(
    'Get-NetFirewallRule',
    'Get-NetFirewallPortFilter',
    'New-NetFirewallRule',
    'Remove-NetFirewallRule',
    'Get-Acl'
)
foreach ($command in $requiredCommands) {
    if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required Windows command is unavailable: $command"
    }
}
$icacls = Join-Path $env:SystemRoot 'System32\icacls.exe'
if (-not (Test-Path -LiteralPath $icacls -PathType Leaf)) {
    throw "Required Windows ACL utility is unavailable: $icacls"
}
Write-Output 'Windows host prerequisites verified.'
"""
    _run_windows_powershell(
        script,
        description="Checking elevated Windows host prerequisites",
    )


def _ensure_system_modify_access(path):
    if os.name != "nt":
        return
    resolved = Path(path).expanduser().resolve()
    script = r"""
$ErrorActionPreference = 'Stop'
$path = [IO.Path]::GetFullPath($env:MISSION_LEGAL_ACL_PATH)
if (-not (Test-Path -LiteralPath $path -PathType Container)) {
    throw "Configured directory does not exist: $path"
}
$icacls = Join-Path $env:SystemRoot 'System32\icacls.exe'
& $icacls $path '/grant:r' '*S-1-5-18:(OI)(CI)M' '/T' '/Q' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "icacls.exe exited with code $LASTEXITCODE for $path"
}
$systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$rules = (Get-Acl -LiteralPath $path -ErrorAction Stop).GetAccessRules(
    $true,
    $true,
    [Security.Principal.SecurityIdentifier]
)
$modify = [Security.AccessControl.FileSystemRights]::Modify
$container = [Security.AccessControl.InheritanceFlags]::ContainerInherit
$object = [Security.AccessControl.InheritanceFlags]::ObjectInherit
$allow = @($rules | Where-Object {
    $_.IdentityReference.Value -ceq $systemSid.Value -and
    $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
    ($_.FileSystemRights -band $modify) -eq $modify -and
    ($_.InheritanceFlags -band $container) -eq $container -and
    ($_.InheritanceFlags -band $object) -eq $object
})
$deny = @($rules | Where-Object {
    $_.IdentityReference.Value -ceq $systemSid.Value -and
    $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Deny -and
    ($_.FileSystemRights -band $modify) -ne 0
})
if ($allow.Count -lt 1 -or $deny.Count -gt 0) {
    throw "LocalSystem Modify access could not be verified for $path"
}
Write-Output $path
"""
    _run_windows_powershell(
        script,
        environment={"MISSION_LEGAL_ACL_PATH": str(resolved)},
        description=f"Granting LocalSystem Modify access to {resolved}",
    )


def _configure_firewall_rule(port):
    if os.name != "nt":
        return
    script = rf"""
$ErrorActionPreference = 'Stop'
$port = [int]$env:MISSION_LEGAL_SERVER_PORT
$name = '{FIREWALL_RULE_NAME}'
$displayName = '{FIREWALL_RULE_DISPLAY_NAME}'
Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction Stop
Get-NetFirewallRule -DisplayName $displayName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction Stop
New-NetFirewallRule `
    -Name $name `
    -DisplayName $displayName `
    -Description 'Allows authenticated Mission Legal clients to reach the main-computer HTTPS server on Private networks.' `
    -Group 'Mission Legal' `
    -Enabled True `
    -Direction Inbound `
    -Action Allow `
    -Profile Private `
    -Protocol TCP `
    -LocalPort $port | Out-Null
$matches = @(Get-NetFirewallRule -DisplayName $displayName -ErrorAction Stop)
if ($matches.Count -ne 1) {{
    throw "Expected exactly one managed firewall rule; found $($matches.Count)."
}}
$rule = $matches[0]
$filters = @($rule | Get-NetFirewallPortFilter -ErrorAction Stop)
$protocol = if ($filters.Count -eq 1) {{ [string]$filters[0].Protocol }} else {{ '' }}
$localPort = if ($filters.Count -eq 1) {{ [string]$filters[0].LocalPort }} else {{ '' }}
if (
    [string]$rule.Name -cne $name -or
    [string]$rule.Enabled -cne 'True' -or
    [string]$rule.Direction -cne 'Inbound' -or
    [string]$rule.Action -cne 'Allow' -or
    [string]$rule.Profile -cne 'Private' -or
    $filters.Count -ne 1 -or
    $protocol -notin @('TCP', '6') -or
    $localPort -cne $port.ToString()
) {{
    throw 'The managed firewall rule did not match the required enabled, inbound, Private-only TCP policy.'
}}
Write-Output "$displayName ($port/TCP, Private)"
"""
    _run_windows_powershell(
        script,
        environment={"MISSION_LEGAL_SERVER_PORT": str(port)},
        description=f"Configuring the Private-profile firewall rule on TCP {port}",
    )


def _database_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_has_application_data(path):
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        for (table_name,) in tables:
            escaped = table_name.replace('"', '""')
            if table_name == "app_metadata":
                row = connection.execute(
                    'SELECT 1 FROM "app_metadata" '
                    "WHERE key != 'schema_version' LIMIT 1"
                ).fetchone()
            else:
                row = connection.execute(
                    f'SELECT 1 FROM "{escaped}" LIMIT 1'
                ).fetchone()
            if row is not None:
                return True
    return False


def _checkpoint_database(path):
    with closing(sqlite3.connect(str(path), timeout=30)) as connection:
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if result and int(result[0]) != 0:
        raise ServerSetupError(
            "The authoritative database is still busy and could not be checkpointed. "
            f"Stop {SERVICE_NAME} and every process using {path}, then retry."
        )


def _replace_database_safely(
    source_database,
    destination_database,
    *,
    database_backup_service,
    backup_dir,
):
    source_database = Path(source_database).resolve()
    destination_database = Path(destination_database).resolve()
    database_backup_service.verify(source_database)
    source_hash = _database_sha256(source_database)

    if source_database == destination_database:
        print(f"Existing database is already authoritative and verified: {source_database}")
        return "already-authoritative"

    if not destination_database.exists():
        destination_created = False
        try:
            database_backup_service.transfer_database(
                source_database,
                destination_database,
            )
            destination_created = True
            database_backup_service.verify(destination_database)
            if _database_sha256(source_database) != source_hash:
                raise ServerSetupError(
                    "The supplied database changed while it was being transferred; "
                    "leave the service stopped and retry from a stable source."
                )
        except Exception:
            if destination_created:
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{destination_database}{suffix}").unlink(missing_ok=True)
            raise
        print(f"Transferred database: {source_database} -> {destination_database}")
        return "transferred"

    _checkpoint_database(destination_database)
    database_backup_service.verify(destination_database)
    backup_service = database_backup_service(
        database_path=destination_database,
        local_backup_dir=backup_dir,
        mirror_dir=None,
    )
    snapshot = backup_service.create_snapshot(
        reason="pre-existing-database-replacement",
        mirror=False,
    )

    token = uuid.uuid4().hex
    staging = destination_database.with_name(
        f".{destination_database.name}.incoming-{token}"
    )
    rollback = destination_database.with_name(
        f".{destination_database.name}.rollback-{token}"
    )
    rollback_sidecars = []
    try:
        database_backup_service.transfer_database(source_database, staging)
        database_backup_service.verify(staging)
        destination_database.replace(rollback)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{destination_database}{suffix}")
            if sidecar.exists():
                saved = Path(f"{rollback}{suffix}")
                sidecar.replace(saved)
                rollback_sidecars.append((sidecar, saved))
        staging.replace(destination_database)
        database_backup_service.verify(destination_database)
        if _database_sha256(source_database) != source_hash:
            raise ServerSetupError(
                "The supplied database changed while it was being transferred."
            )
    except Exception:
        destination_database.unlink(missing_ok=True)
        if rollback.exists():
            rollback.replace(destination_database)
        for sidecar, saved in rollback_sidecars:
            if saved.exists():
                saved.replace(sidecar)
        if destination_database.exists():
            database_backup_service.verify(destination_database)
        raise
    else:
        rollback.unlink(missing_ok=True)
        for _sidecar, saved in rollback_sidecars:
            saved.unlink(missing_ok=True)
    finally:
        staging.unlink(missing_ok=True)

    print(
        f"Replaced authoritative database from verified source: {source_database}"
    )
    print(f"Preserved previous authoritative database: {snapshot['path']}")
    return "replaced"


def _handle_existing_database(
    source_database,
    destination_database,
    *,
    explicitly_supplied,
    allow_populated_replacement,
    database_backup_service,
    backup_dir,
):
    source_database = Path(source_database).expanduser().resolve()
    destination_database = Path(destination_database).expanduser().resolve()
    if not source_database.is_file():
        if explicitly_supplied:
            raise ServerSetupError(
                f"The explicitly supplied database does not exist: {source_database}"
            )
        return "not-found"

    if explicitly_supplied:
        _assert_server_service_stopped()

    if destination_database.exists() and not explicitly_supplied:
        database_backup_service.verify(destination_database)
        print(
            "Existing authoritative database verified and preserved: "
            f"{destination_database}"
        )
        return "destination-preserved"

    if destination_database.exists() and source_database != destination_database:
        database_backup_service.verify(destination_database)
        populated = _database_has_application_data(destination_database)
        if populated and not allow_populated_replacement:
            raise ServerSetupError(
                "The authoritative destination database already contains application "
                f"data: {destination_database}. The supplied --existing-database was "
                "not applied. Preserve and review both databases, stop the service, "
                "then re-run with --replace-existing-database only if replacing the "
                "authoritative data is intentional."
            )

    return _replace_database_safely(
        source_database,
        destination_database,
        database_backup_service=database_backup_service,
        backup_dir=backup_dir,
    )


def main():
    parser = argparse.ArgumentParser(description="Configure the main Mission Legal server")
    parser.add_argument("--onedrive-backup-dir", required=True)
    parser.add_argument("--mission-storage-root", required=True)
    parser.add_argument("--data-dir")
    parser.add_argument("--existing-database")
    parser.add_argument(
        "--replace-existing-database",
        action="store_true",
        help=(
            "Explicitly authorize replacing a populated authoritative database "
            "from --existing-database after preserving a verified local snapshot."
        ),
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=_port, default=8765)
    parser.add_argument("--overwrite-certificates", action="store_true")
    parser.add_argument("--create-pairing-code", action="store_true")
    parser.add_argument("--skip-main-client", action="store_true")
    args = parser.parse_args()
    if args.replace_existing_database and not args.existing_database:
        parser.error("--replace-existing-database requires --existing-database")

    data_dir = args.data_dir
    if not data_dir:
        program_data = os.environ.get("PROGRAMDATA")
        data_dir = str(Path(program_data) / "MissionLegal") if program_data else None
    if data_dir:
        os.environ["MISSION_LEGAL_DATA_DIR"] = str(Path(data_dir).expanduser().resolve())

    from server.configuration import load_server_configuration, save_server_configuration
    from server.security import PairingCodeStore
    from server.security import DeviceCredentialStore
    from server.data_acl import protect_sensitive_server_data, publish_public_ca
    from server.tls import generate_local_tls
    from database.runtime import get_app_data_dir, get_client_data_dir, get_database_path
    from services.database_backup_service import DatabaseBackupService

    app_data_dir = get_app_data_dir()
    backup_dir = Path(args.onedrive_backup_dir).expanduser().resolve()
    mission_root = Path(args.mission_storage_root).expanduser().resolve()
    if not mission_root.is_dir():
        parser.error(f"Mission storage root does not exist: {mission_root}")

    _assert_windows_host_prerequisites()
    protect_sensitive_server_data(app_data_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    _ensure_system_modify_access(mission_root)
    _ensure_system_modify_access(backup_dir)

    destination_database = get_database_path()
    default_existing = Path(__file__).resolve().parent / "data" / "app.db"
    explicitly_supplied = args.existing_database is not None
    existing_database = Path(
        args.existing_database or default_existing
    ).expanduser().resolve()
    local_backup_dir = destination_database.parent / "Backups"
    _handle_existing_database(
        existing_database,
        destination_database,
        explicitly_supplied=explicitly_supplied,
        allow_populated_replacement=args.replace_existing_database,
        database_backup_service=DatabaseBackupService,
        backup_dir=local_backup_dir,
    )

    configuration = load_server_configuration()
    configuration.update(
        {
            "host": args.host,
            "port": args.port,
            "onedrive_backup_dir": str(backup_dir),
            "mission_storage_root": str(mission_root),
        }
    )
    config_path = save_server_configuration(configuration)
    _configure_firewall_rule(args.port)
    tls_paths = generate_local_tls(overwrite=args.overwrite_certificates)
    published_ca = publish_public_ca(tls_paths["ca_cert"], app_data_dir)

    if destination_database.exists():
        backup_service = DatabaseBackupService(mirror_dir=backup_dir)
        backup_service.create_snapshot(reason="server-setup", mirror=True)
        backup_service.prune(keep=48, mirror_keep=30)

    if not args.skip_main_client:
        from PySide6.QtCore import QSettings
        import keyring

        from services.api_client import KEYRING_SERVICE

        credential_path = get_client_data_dir() / "Configuration" / "api-device.json"
        if not credential_path.exists():
            credential_path.parent.mkdir(parents=True, exist_ok=True)
            registered = DeviceCredentialStore().register(
                f"{socket.gethostname()} desktop"
            )
            keyring.set_password(
                KEYRING_SERVICE,
                registered["device_id"],
                registered["credential"],
            )
            temporary = credential_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps({"device_id": registered["device_id"]}, indent=2),
                encoding="utf-8",
            )
            temporary.replace(credential_path)
        settings = QSettings(ORG, APP)
        settings.setValue(
            "server/url", f"https://{socket.gethostname()}:{args.port}"
        )
        settings.setValue("server/ca_certificate", str(published_ca))
        settings.sync()

    pairing = PairingCodeStore().create() if args.create_pairing_code else None
    installed_service_started = _finish_installed_service_setup(
        app_data_dir,
    )

    print(f"Server configuration: {config_path}")
    print(f"Client CA certificate: {published_ca}")
    print(f"OneDrive backup directory: {backup_dir}")
    print(f"Mission document root: {mission_root}")
    print(f"Authoritative database: {destination_database}")
    if os.name == "nt":
        print(
            f"Windows firewall: {FIREWALL_RULE_DISPLAY_NAME} "
            f"(TCP {args.port}, Private profile only)"
        )
        print("Verified LocalSystem Modify access to mission and backup directories.")
    if not args.skip_main_client:
        print("Configured this Windows user to access the database through HTTPS.")
    if installed_service_started:
        print(
            f"Installed Windows service registered, started, and health-verified "
            f"at version {APP_VERSION}."
        )
    elif os.name == "nt":
        print(
            "Raw/source server setup completed. Service registration was not "
            "attempted because the installed service helper is absent; register "
            "and start MissionLegalService.exe manually."
        )
    if pairing is not None:
        print(
            f"Pairing code: {pairing['code']} "
            f"(expires {pairing['expires_at'].isoformat()})"
        )


if __name__ == "__main__":
    main()
