"""Portable public bootstrap material for one-step client pairing."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass


PAIRING_PACKAGE_PREFIX = "MLPAIR1:"
PAIRING_PACKAGE_VERSION = 1
MAX_PAIRING_PACKAGE_CHARACTERS = 32 * 1024
MAX_CA_CERTIFICATE_BYTES = 2 * 1024 * 1024
_PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN ENCRYPTED PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN DSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)


class PairingPackageError(ValueError):
    """Raised when a copied pairing package is malformed or unsafe."""


@dataclass(frozen=True)
class PairingPackage:
    server_url: str
    ca_certificate_pem: str
    pairing_code: str
    expires_at: str


def _validate_ca_certificate(value: object) -> bytes:
    if not isinstance(value, str):
        raise PairingPackageError("The setup code does not contain a CA certificate.")
    try:
        certificate = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise PairingPackageError("The setup code contains an invalid CA certificate.") from exc
    if not certificate or len(certificate) > MAX_CA_CERTIFICATE_BYTES:
        raise PairingPackageError("The setup code contains an invalid CA certificate.")
    if any(marker in certificate for marker in _PRIVATE_KEY_MARKERS):
        raise PairingPackageError("The setup code must never contain a private key.")
    if (
        b"-----BEGIN CERTIFICATE-----" not in certificate
        or b"-----END CERTIFICATE-----" not in certificate
    ):
        raise PairingPackageError("The setup code does not contain a PEM CA certificate.")
    return certificate


def encode_pairing_package(
    *,
    server_url: str,
    ca_certificate_pem: str,
    pairing_code: str,
    expires_at: str,
) -> str:
    certificate = _validate_ca_certificate(ca_certificate_pem)
    code = str(pairing_code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise PairingPackageError("The pairing code must contain exactly six digits.")
    payload = {
        "version": PAIRING_PACKAGE_VERSION,
        "server_url": str(server_url or "").strip(),
        "ca_certificate_pem": certificate.decode("ascii"),
        "ca_sha256": hashlib.sha256(certificate).hexdigest(),
        "pairing_code": code,
        "expires_at": str(expires_at or "").strip(),
    }
    if not payload["server_url"].startswith("https://") or not payload["expires_at"]:
        raise PairingPackageError("The setup code contains incomplete server details.")
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    package = PAIRING_PACKAGE_PREFIX + encoded
    if len(package) > MAX_PAIRING_PACKAGE_CHARACTERS:
        raise PairingPackageError("The generated setup code is unexpectedly large.")
    return package


def decode_pairing_package(value: object) -> PairingPackage:
    package = "".join(str(value or "").split())
    if not package.startswith(PAIRING_PACKAGE_PREFIX):
        raise PairingPackageError(
            "Paste the complete setup code copied from Mission Legal Server Manager."
        )
    if len(package) > MAX_PAIRING_PACKAGE_CHARACTERS:
        raise PairingPackageError("The setup code is unexpectedly large.")
    encoded = package[len(PAIRING_PACKAGE_PREFIX) :]
    try:
        padded = encoded + ("=" * (-len(encoded) % 4))
        decoded = base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise PairingPackageError("The setup code is damaged or incomplete.") from exc
    if not isinstance(payload, dict) or payload.get("version") != PAIRING_PACKAGE_VERSION:
        raise PairingPackageError("This setup code version is not supported.")
    if set(payload) != {
        "version",
        "server_url",
        "ca_certificate_pem",
        "ca_sha256",
        "pairing_code",
        "expires_at",
    }:
        raise PairingPackageError("The setup code contains unsupported fields.")
    certificate = _validate_ca_certificate(payload.get("ca_certificate_pem"))
    expected_hash = hashlib.sha256(certificate).hexdigest()
    if payload.get("ca_sha256") != expected_hash:
        raise PairingPackageError("The setup code certificate checksum does not match.")
    code = str(payload.get("pairing_code") or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise PairingPackageError("The setup code contains an invalid pairing code.")
    server_url = str(payload.get("server_url") or "").strip()
    expires_at = str(payload.get("expires_at") or "").strip()
    if not server_url.startswith("https://") or not expires_at:
        raise PairingPackageError("The setup code contains incomplete server details.")
    return PairingPackage(
        server_url=server_url,
        ca_certificate_pem=certificate.decode("ascii"),
        pairing_code=code,
        expires_at=expires_at,
    )
