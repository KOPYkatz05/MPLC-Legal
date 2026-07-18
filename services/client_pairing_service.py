"""First-run pairing workflow for an installed Mission Legal client."""

from __future__ import annotations

import shutil
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QSettings

from app_identity import APP, ORG
from database.runtime import get_client_data_dir
from services.api_client import MissionLegalApiClient


class ClientPairingError(RuntimeError):
    """Raised when first-run pairing input is unsafe or incomplete."""


@dataclass(frozen=True)
class ClientPairingResult:
    device_id: str
    server_url: str
    api_version: str
    schema_version: int | str
    saved_certificate: Path


def default_device_name():
    return socket.gethostname()


def normalize_server_url(value):
    url = str(value or "").strip().rstrip("/")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ClientPairingError("The server address is invalid.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ClientPairingError(
            "Enter the server's HTTPS address without credentials, a path, "
            "a query, or a fragment."
        )
    return url


def validate_pairing_code(value):
    code = str(value or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise ClientPairingError("The pairing code must contain exactly six digits.")
    return code


def _stage_ca_certificate(certificate):
    certificate = Path(certificate).expanduser().resolve()
    if not certificate.is_file():
        raise ClientPairingError(f"The CA certificate does not exist: {certificate}")
    try:
        certificate_bytes = certificate.read_bytes()
    except OSError as exc:
        raise ClientPairingError(
            f"Windows could not read the CA certificate: {certificate}"
        ) from exc
    if not certificate_bytes or len(certificate_bytes) > 2 * 1024 * 1024:
        raise ClientPairingError(
            "Choose the public Mission Legal CA certificate supplied by the administrator."
        )
    private_key_markers = (
        b"-----BEGIN PRIVATE KEY-----",
        b"-----BEGIN ENCRYPTED PRIVATE KEY-----",
        b"-----BEGIN RSA PRIVATE KEY-----",
        b"-----BEGIN EC PRIVATE KEY-----",
        b"-----BEGIN DSA PRIVATE KEY-----",
        b"-----BEGIN OPENSSH PRIVATE KEY-----",
    )
    if any(marker in certificate_bytes for marker in private_key_markers):
        raise ClientPairingError(
            "The selected file contains a private key. Choose only the public "
            "Mission Legal CA certificate."
        )
    if (
        b"-----BEGIN CERTIFICATE-----" not in certificate_bytes
        or b"-----END CERTIFICATE-----" not in certificate_bytes
    ):
        raise ClientPairingError(
            "The selected file is not a PEM certificate. Choose mission-legal-ca.pem."
        )

    configuration_dir = get_client_data_dir() / "Configuration"
    configuration_dir.mkdir(parents=True, exist_ok=True)
    saved_certificate = (configuration_dir / "mission-legal-ca.pem").resolve()
    if certificate == saved_certificate:
        return certificate, saved_certificate, None

    staged = saved_certificate.with_name(
        f".{saved_certificate.name}.{uuid.uuid4().hex}.pairing"
    )
    try:
        shutil.copy2(certificate, staged)
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    return staged, saved_certificate, staged


def pair_client(server_url, certificate, pairing_code, device_name=None):
    """Pair this Windows user and persist only public connection material."""

    normalized_url = normalize_server_url(server_url)
    code = validate_pairing_code(pairing_code)
    name = str(device_name or default_device_name()).strip()
    if not name:
        raise ClientPairingError("Enter a name for this computer.")
    if len(name) > 100:
        raise ClientPairingError("The computer name cannot exceed 100 characters.")

    verification_certificate, saved_certificate, staged_certificate = (
        _stage_ca_certificate(certificate)
    )
    try:
        client = MissionLegalApiClient(
            normalized_url,
            certificate=str(verification_certificate),
        )
        health = client.health()
        client.validate_compatibility(health)
        paired = client.pair(code, name)
        if staged_certificate is not None:
            staged_certificate.replace(saved_certificate)
    finally:
        if staged_certificate is not None:
            staged_certificate.unlink(missing_ok=True)

    settings = QSettings(ORG, APP)
    settings.setValue("server/url", normalized_url)
    settings.setValue("server/ca_certificate", str(saved_certificate))
    settings.sync()
    if settings.status() != QSettings.NoError:
        raise ClientPairingError("Windows could not save the server connection settings.")

    return ClientPairingResult(
        device_id=str(paired["device_id"]),
        server_url=normalized_url,
        api_version=str(health.get("api_version", "")),
        schema_version=health.get("schema_version", ""),
        saved_certificate=saved_certificate,
    )
