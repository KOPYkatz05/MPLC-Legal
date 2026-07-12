import argparse
import json
import os
import socket
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Configure the main Mission Legal server")
    parser.add_argument("--onedrive-backup-dir", required=True)
    parser.add_argument("--mission-storage-root", required=True)
    parser.add_argument("--data-dir")
    parser.add_argument("--existing-database")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--overwrite-certificates", action="store_true")
    parser.add_argument("--create-pairing-code", action="store_true")
    parser.add_argument("--skip-main-client", action="store_true")
    args = parser.parse_args()

    data_dir = args.data_dir
    if not data_dir:
        program_data = os.environ.get("PROGRAMDATA")
        data_dir = str(Path(program_data) / "MissionLegal") if program_data else None
    if data_dir:
        os.environ["MISSION_LEGAL_DATA_DIR"] = str(Path(data_dir).expanduser().resolve())

    from server.configuration import load_server_configuration, save_server_configuration
    from server.security import PairingCodeStore
    from server.security import DeviceCredentialStore
    from server.tls import generate_local_tls
    from database.runtime import get_client_data_dir, get_database_path
    from services.database_backup_service import DatabaseBackupService

    backup_dir = Path(args.onedrive_backup_dir).expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    mission_root = Path(args.mission_storage_root).expanduser().resolve()
    if not mission_root.is_dir():
        parser.error(f"Mission storage root does not exist: {mission_root}")
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
    tls_paths = generate_local_tls(overwrite=args.overwrite_certificates)

    destination_database = get_database_path()
    default_existing = Path(__file__).resolve().parent / "data" / "app.db"
    existing_database = Path(
        args.existing_database or default_existing
    ).expanduser().resolve()
    if not destination_database.exists() and existing_database.is_file():
        DatabaseBackupService.transfer_database(
            existing_database, destination_database
        )
        print(f"Transferred database: {existing_database} -> {destination_database}")
    elif destination_database.exists():
        DatabaseBackupService.verify(destination_database)

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
        settings = QSettings("MissionLegal", "MissionLegalTracker")
        settings.setValue(
            "server/url", f"https://{socket.gethostname()}:{args.port}"
        )
        settings.setValue("server/ca_certificate", str(tls_paths["ca_cert"]))
        settings.sync()

    if os.name == "nt" and data_dir:
        username = os.environ.get("USERNAME")
        grants = ["SYSTEM:(OI)(CI)F", "Administrators:(OI)(CI)F"]
        if username:
            grants.append(f"{username}:(OI)(CI)R")
        subprocess.run(
            [
                "icacls",
                str(Path(data_dir).resolve()),
                "/inheritance:r",
                "/grant:r",
                *grants,
                "/T",
            ],
            capture_output=True,
            check=False,
        )

    print(f"Server configuration: {config_path}")
    print(f"Client CA certificate: {tls_paths['ca_cert']}")
    print(f"OneDrive backup directory: {backup_dir}")
    print(f"Mission document root: {mission_root}")
    print(f"Authoritative database: {destination_database}")
    if not args.skip_main_client:
        print("Configured this Windows user to access the database through HTTPS.")
    if args.create_pairing_code:
        pairing = PairingCodeStore().create()
        print(
            f"Pairing code: {pairing['code']} "
            f"(expires {pairing['expires_at'].isoformat()})"
        )


if __name__ == "__main__":
    main()
