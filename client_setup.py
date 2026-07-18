import argparse

from services.client_pairing_service import default_device_name, pair_client


def main():
    parser = argparse.ArgumentParser(description="Pair this computer with Mission Legal Server")
    parser.add_argument("--server", required=True, help="HTTPS URL, for example https://MAIN-PC:8765")
    parser.add_argument("--ca-cert", required=True, help="Mission Legal CA certificate copied from the server")
    parser.add_argument("--pairing-code", required=True)
    parser.add_argument("--device-name", default=default_device_name())
    args = parser.parse_args()

    result = pair_client(
        args.server,
        args.ca_cert,
        args.pairing_code,
        args.device_name,
    )
    print(
        f"Paired device {result.device_id} with API {result.api_version} "
        f"and schema {result.schema_version}."
    )


if __name__ == "__main__":
    main()
