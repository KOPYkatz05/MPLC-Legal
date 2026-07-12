import argparse
import shutil
import socket
from pathlib import Path

from PySide6.QtCore import QSettings

from app_identity import APP, ORG
from services.api_client import MissionLegalApiClient
from database.runtime import get_client_data_dir


def main():
    parser = argparse.ArgumentParser(description="Pair this computer with Mission Legal Server")
    parser.add_argument("--server", required=True, help="HTTPS URL, for example https://MAIN-PC:8765")
    parser.add_argument("--ca-cert", required=True, help="Mission Legal CA certificate copied from the server")
    parser.add_argument("--pairing-code", required=True)
    parser.add_argument("--device-name", default=socket.gethostname())
    args = parser.parse_args()

    certificate = Path(args.ca_cert).expanduser().resolve()
    if not certificate.is_file():
        parser.error(f"CA certificate does not exist: {certificate}")

    client = MissionLegalApiClient(args.server, certificate=str(certificate))
    health = client.health()
    client.validate_compatibility(health)
    paired = client.pair(args.pairing_code, args.device_name)

    configuration_dir = get_client_data_dir() / "Configuration"
    configuration_dir.mkdir(parents=True, exist_ok=True)
    saved_certificate = configuration_dir / "mission-legal-ca.pem"
    if certificate != saved_certificate.resolve():
        temporary = saved_certificate.with_suffix(".pem.tmp")
        shutil.copy2(certificate, temporary)
        temporary.replace(saved_certificate)

    settings = QSettings(ORG, APP)
    settings.setValue("server/url", args.server.rstrip("/"))
    settings.setValue("server/ca_certificate", str(saved_certificate))
    settings.sync()
    print(
        f"Paired device {paired['device_id']} with API {health['api_version']} "
        f"and schema {health['schema_version']}."
    )


if __name__ == "__main__":
    main()
