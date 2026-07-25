import base64
import json

import pytest

from services import pairing_package


CA_PEM = "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"


def test_pairing_package_round_trip_keeps_only_public_bootstrap_material():
    encoded = pairing_package.encode_pairing_package(
        server_url="https://192.168.108.50:8765",
        ca_certificate_pem=CA_PEM,
        pairing_code="123456",
        expires_at="2026-07-25T12:10:00+00:00",
    )

    decoded = pairing_package.decode_pairing_package(encoded)

    assert encoded.startswith("MLPAIR1:")
    assert decoded.server_url == "https://192.168.108.50:8765"
    assert decoded.ca_certificate_pem == CA_PEM
    assert decoded.pairing_code == "123456"
    assert "PRIVATE KEY" not in encoded


def test_pairing_package_rejects_tampered_certificate_checksum():
    encoded = pairing_package.encode_pairing_package(
        server_url="https://192.168.108.50:8765",
        ca_certificate_pem=CA_PEM,
        pairing_code="123456",
        expires_at="2026-07-25T12:10:00+00:00",
    )
    payload_text = encoded.split(":", 1)[1]
    payload_text += "=" * (-len(payload_text) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_text))
    payload["ca_certificate_pem"] = payload["ca_certificate_pem"].replace(
        "PUBLIC", "ALTERED"
    )
    tampered = "MLPAIR1:" + base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")

    with pytest.raises(pairing_package.PairingPackageError, match="checksum"):
        pairing_package.decode_pairing_package(tampered)


def test_pairing_package_rejects_private_key_material():
    with pytest.raises(pairing_package.PairingPackageError, match="private key"):
        pairing_package.encode_pairing_package(
            server_url="https://192.168.108.50:8765",
            ca_certificate_pem=(
                CA_PEM + "-----BEGIN PRIVATE KEY-----\nSECRET\n"
            ),
            pairing_code="123456",
            expires_at="2026-07-25T12:10:00+00:00",
        )
