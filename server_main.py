import argparse
import os
import sys
import threading


def _should_enforce_production_tls_key_acl(frozen=None):
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    return bool(frozen)


def main():
    os.environ["MISSION_LEGAL_SERVER_PROCESS"] = "1"
    parser = argparse.ArgumentParser(description="Mission Legal local API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    parser.add_argument("--create-pairing-code", action="store_true")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--revoke-device")
    parser.add_argument("--send-daily-digest", action="store_true")
    parser.add_argument(
        "--backup-before-upgrade",
        action="store_true",
        help=(
            "Create and verify a local database snapshot, then exit. "
            "Installers use this as a mandatory pre-upgrade gate."
        ),
    )
    parser.add_argument("--package-smoke-test", action="store_true")
    args = parser.parse_args()

    if args.package_smoke_test:
        from utils.package_smoke import run_server_package_smoke_test

        return run_server_package_smoke_test()

    if args.send_daily_digest:
        from database.db import init_db
        from services.email_digest_service import EmailDigestService

        init_db()
        result = EmailDigestService().send_daily_digest()
        if result.get("sent"):
            print("Daily digest email sent.")
            return 0
        print(f"Daily digest email not sent: {result.get('reason')}")
        return 1

    if args.backup_before_upgrade:
        from database.runtime import get_database_path
        from services.database_backup_service import DatabaseBackupService

        database_path = get_database_path()
        if not database_path.exists():
            print("No existing database was found; no upgrade snapshot is required.")
            return 0
        backup_service = DatabaseBackupService()
        result = backup_service.create_snapshot(reason="pre-upgrade", mirror=False)
        DatabaseBackupService.verify(result["path"])
        print(f"Verified pre-upgrade snapshot: {result['path']}")
        return 0

    from server.configuration import load_server_configuration

    saved = load_server_configuration()
    if saved.get("mission_storage_root"):
        os.environ["MISSIONS_ROOT"] = saved["mission_storage_root"]
    if args.host == "127.0.0.1" and saved.get("host"):
        args.host = saved["host"]
    if args.port == 8765 and saved.get("port"):
        args.port = int(saved["port"])

    if args.create_pairing_code:
        from server.security import PairingCodeStore

        pairing = PairingCodeStore().create()
        print(
            f"Pairing code: {pairing['code']} "
            f"(expires {pairing['expires_at'].isoformat()})"
        )
        return

    if args.list_devices or args.revoke_device:
        from server.security import DeviceCredentialStore

        store = DeviceCredentialStore()
        if args.revoke_device:
            if not store.revoke(args.revoke_device):
                parser.error("Device was not found or was already revoked")
            print(f"Revoked device: {args.revoke_device}")
            return
        for device in store.list_devices():
            state = (
                "revoked"
                if device["revoked_at"]
                else "pending"
                if device["pending_confirmation"]
                else "active"
            )
            print(f"{device['device_id']}  {state:7}  {device['device_name']}")
        return

    if not args.tls_cert and not args.tls_key:
        from server.tls import generate_local_tls

        # Frozen server/service processes run under the installed production
        # boundary and must fail closed on the SYSTEM/Administrators-only DACL.
        # Source-mode development and integration tests run as the caller, who
        # still needs to read the generated key before uvicorn starts.
        paths = generate_local_tls(
            protect_keys=_should_enforce_production_tls_key_acl()
        )
        args.tls_cert = str(paths["server_cert"])
        args.tls_key = str(paths["server_key"])

    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert and --tls-key must be provided together")

    import uvicorn

    from server.tls import default_tls_paths
    from server.trusted_networks import TrustedNetworkStore
    from services.lan_discovery import LanDiscoveryResponder

    trusted_networks = TrustedNetworkStore()
    public_ca = (
        paths["ca_cert"] if "paths" in locals() else default_tls_paths()["ca_cert"]
    )
    responder = LanDiscoveryResponder(
        enabled_provider=trusted_networks.is_current_trusted,
        ca_certificate_provider=lambda: public_ca.read_text(encoding="ascii"),
        port_provider=lambda: args.port,
    )
    discovery_thread = threading.Thread(
        target=responder.serve_forever,
        name="MissionLegalLanDiscovery",
        daemon=True,
    )
    discovery_thread.start()
    try:
        uvicorn.run(
            "server.app:app",
            host=args.host,
            port=args.port,
            ssl_certfile=args.tls_cert,
            ssl_keyfile=args.tls_key,
            proxy_headers=False,
            server_header=False,
        )
    finally:
        responder.stop()


if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        raise SystemExit(result)
