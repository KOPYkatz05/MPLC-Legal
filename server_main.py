import argparse
import os


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
    args = parser.parse_args()

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
            state = "revoked" if device["revoked_at"] else "active"
            print(f"{device['device_id']}  {state:7}  {device['device_name']}")
        return

    if not args.tls_cert and not args.tls_key:
        from server.tls import generate_local_tls

        paths = generate_local_tls()
        args.tls_cert = str(paths["server_cert"])
        args.tls_key = str(paths["server_key"])

    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert and --tls-key must be provided together")

    import uvicorn

    uvicorn.run(
        "server.app:app",
        host=args.host,
        port=args.port,
        ssl_certfile=args.tls_cert,
        ssl_keyfile=args.tls_key,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
