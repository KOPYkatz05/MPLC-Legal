"""First-run pairing workflow for an installed Mission Legal client."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import uuid
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QSettings

from app_identity import APP, ORG
from database.runtime import get_client_data_dir
from services.api_client import ApiPairingRecoveryRequired, MissionLegalApiClient
from utils.interprocess_lock import interprocess_file_lock


logger = logging.getLogger(__name__)


_JOURNAL_VERSION = 1
_JOURNAL_NAME = "pairing-transaction.json"
_LOCK_NAME = "pairing-transaction.lock"
_SETTING_KEYS = ("server/url", "server/ca_certificate")
_MAX_DEVICE_POINTER_BYTES = 64 * 1024


class ClientPairingError(RuntimeError):
    """Raised when first-run pairing input is unsafe or incomplete."""


class ClientPairingRecoveryError(ClientPairingError):
    """Raised when an interrupted pairing cannot yet be reconciled safely."""


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
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove a failed staged CA certificate",
                exc_info=True,
            )
        raise
    return staged, saved_certificate, staged


def _snapshot_settings(settings, keys):
    snapshot = {}
    for key in keys:
        contains = bool(settings.contains(key))
        snapshot[key] = (contains, settings.value(key) if contains else None)
    return snapshot


def _settings_for_journal(snapshot):
    payload = {}
    for key, (contained, value) in snapshot.items():
        string_value = None if value is None else str(value)
        if key == "server/url" and contained and string_value:
            try:
                parsed = urlparse(string_value)
            except ValueError as exc:
                raise ClientPairingError(
                    "The previous server connection settings are invalid."
                ) from exc
            if (
                parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ClientPairingError(
                    "The previous server connection contains secret-bearing URL "
                    "data and cannot be placed in a pairing recovery record."
                )
        payload[key] = {
            "contained": bool(contained),
            # These two application settings are public path/URL strings. Cast
            # unusual Qt values to strings so the recovery journal stays JSON.
            "value": string_value,
        }
    return payload


def _settings_from_journal(payload):
    if not isinstance(payload, dict) or set(payload) != set(_SETTING_KEYS):
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    snapshot = {}
    for key in _SETTING_KEYS:
        entry = payload.get(key)
        if not isinstance(entry, dict) or not isinstance(
            entry.get("contained"), bool
        ):
            raise ClientPairingRecoveryError(
                "The interrupted pairing recovery record is invalid."
            )
        value = entry.get("value")
        if value is not None and not isinstance(value, str):
            raise ClientPairingRecoveryError(
                "The interrupted pairing recovery record is invalid."
            )
        snapshot[key] = (entry["contained"], value)
    return snapshot


def _restore_settings(settings, snapshot):
    for key, (contained, value) in snapshot.items():
        if contained:
            settings.setValue(key, value)
        else:
            settings.remove(key)
    settings.sync()
    if settings.status() != QSettings.NoError:
        raise ClientPairingError(
            "Windows could not restore the previous server connection settings."
        )


def _unlink_pairing_artifact(path, description):
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove %s: %s", description, path, exc_info=True)


def _configuration_dir():
    return get_client_data_dir() / "Configuration"


def _journal_path():
    return _configuration_dir() / _JOURNAL_NAME


def _lock_path():
    return _configuration_dir() / _LOCK_NAME


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path, content, *, suffix=".tmp"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}{suffix}")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove a temporary pairing transaction file: %s",
                temporary,
                exc_info=True,
            )


def _write_journal(path, payload):
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(path, encoded, suffix=".journal.tmp")


def _read_previous_device_pointer(path):
    path = Path(path)
    if not path.exists():
        return {"existed": False, "bytes_base64": None}
    content = path.read_bytes()
    if len(content) > _MAX_DEVICE_POINTER_BYTES:
        raise ClientPairingError("The saved device registration is unexpectedly large.")
    try:
        device = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # A malformed pointer cannot identify an authenticated prior device and
        # is therefore treated as absent instead of copied into the journal.
        return {"existed": False, "bytes_base64": None}
    if (
        not isinstance(device, dict)
        or not isinstance(device.get("device_id"), str)
        or not device["device_id"].strip()
        or len(device["device_id"]) > 200
    ):
        return {"existed": False, "bytes_base64": None}
    # The pointer contract is deliberately only a device ID; canonicalizing it
    # prevents legacy or hand-edited secret fields from entering the journal.
    content = (json.dumps({"device_id": device["device_id"]}, indent=2) + "\n").encode(
        "utf-8"
    )
    return {
        "existed": True,
        "bytes_base64": base64.b64encode(content).decode("ascii"),
    }


def _decode_previous_device_pointer(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("existed"), bool):
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    encoded = payload.get("bytes_base64")
    if not payload["existed"]:
        if encoded is not None:
            raise ClientPairingRecoveryError(
                "The interrupted pairing recovery record is invalid."
            )
        return None
    if not isinstance(encoded, str):
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        ) from exc
    if len(content) > _MAX_DEVICE_POINTER_BYTES:
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    try:
        device = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        ) from exc
    if (
        not isinstance(device, dict)
        or set(device) != {"device_id"}
        or not isinstance(device.get("device_id"), str)
        or not device["device_id"].strip()
        or len(device["device_id"]) > 200
    ):
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    return content


def _device_id_from_bytes(content):
    if content is None:
        return None
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("device_id"):
        return None
    return str(payload["device_id"])


def _read_current_device_id(path):
    try:
        return _device_id_from_bytes(Path(path).read_bytes())
    except OSError:
        return None


def _validate_artifact_name(name, *, transaction_id, ending):
    expected_prefix = f".mission-legal-ca.pem.{transaction_id}."
    if (
        not isinstance(name, str)
        or Path(name).name != name
        or not name.startswith(expected_prefix)
        or not name.endswith(ending)
    ):
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    return name


def _load_journal(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClientPairingRecoveryError(
            "Mission Legal found an unreadable interrupted pairing record. "
            "Do not pair again until the local connection can be recovered."
        ) from exc
    if not isinstance(payload, dict) or payload.get("version") != _JOURNAL_VERSION:
        raise ClientPairingRecoveryError(
            "Mission Legal found an unsupported interrupted pairing record."
        )
    transaction_id = payload.get("transaction_id")
    try:
        uuid.UUID(str(transaction_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        ) from exc
    try:
        payload["server_url"] = normalize_server_url(payload.get("server_url"))
    except ClientPairingError as exc:
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        ) from exc
    _settings_from_journal(payload.get("previous_settings"))
    _decode_previous_device_pointer(payload.get("previous_device_pointer"))
    new_device_id = payload.get("new_device_id")
    if new_device_id is not None and (
        not isinstance(new_device_id, str) or not new_device_id.strip()
    ):
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    for field in ("new_certificate_sha256", "previous_certificate_sha256"):
        value = payload.get(field)
        if value is not None and (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ClientPairingRecoveryError(
                "The interrupted pairing recovery record is invalid."
            )
    staged_name = payload.get("staged_certificate_name")
    if staged_name is not None:
        _validate_artifact_name(
            staged_name,
            transaction_id=str(transaction_id),
            ending=".pairing",
        )
    backup_name = payload.get("certificate_backup_name")
    if backup_name is not None:
        _validate_artifact_name(
            backup_name,
            transaction_id=str(transaction_id),
            ending=".rollback",
        )
    if not isinstance(payload.get("previous_certificate_existed"), bool):
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    if payload.get("phase") not in {
        "prepared",
        "registered",
        "local-state-applied",
        "confirmed",
    }:
        raise ClientPairingRecoveryError(
            "The interrupted pairing recovery record is invalid."
        )
    return payload


def _journal_artifacts(journal):
    configuration = _configuration_dir()
    saved = configuration / "mission-legal-ca.pem"
    staged_name = journal.get("staged_certificate_name")
    backup_name = journal.get("certificate_backup_name")
    return (
        saved,
        configuration / staged_name if staged_name else None,
        configuration / backup_name if backup_name else None,
    )


def _path_has_sha256(path, expected):
    return bool(path and expected and Path(path).is_file() and _sha256(path) == expected)


def _verification_certificate(journal):
    saved, staged, _backup = _journal_artifacts(journal)
    expected = journal["new_certificate_sha256"]
    if _path_has_sha256(saved, expected):
        return saved
    if _path_has_sha256(staged, expected):
        return staged
    raise ClientPairingRecoveryError(
        "Mission Legal cannot verify the CA certificate for an interrupted "
        "pairing. The existing connection has not been changed."
    )


def _restore_previous_device_pointer(path, journal, *, expected_new_device_id=None):
    previous = _decode_previous_device_pointer(journal["previous_device_pointer"])
    current_id = _read_current_device_id(path)
    previous_id = _device_id_from_bytes(previous)
    allowed = {None, previous_id, expected_new_device_id}
    if current_id not in allowed:
        raise ClientPairingRecoveryError(
            "The saved device registration changed during pairing recovery."
        )
    if previous is None:
        Path(path).unlink(missing_ok=True)
    else:
        _atomic_write_bytes(path, previous, suffix=".pointer.rollback.tmp")


def _restore_previous_certificate(journal):
    saved, _staged, backup = _journal_artifacts(journal)
    previous_existed = journal["previous_certificate_existed"]
    previous_hash = journal.get("previous_certificate_sha256")
    new_hash = journal["new_certificate_sha256"]
    if previous_existed:
        if _path_has_sha256(backup, previous_hash):
            saved.unlink(missing_ok=True)
            os.replace(backup, saved)
            return
        if _path_has_sha256(saved, previous_hash):
            return
        raise ClientPairingRecoveryError(
            "Mission Legal could not safely restore the previous CA certificate."
        )
    if saved.exists():
        if not _path_has_sha256(saved, new_hash):
            raise ClientPairingRecoveryError(
                "The CA certificate changed during pairing recovery."
            )
        saved.unlink()


def _apply_new_local_state(journal):
    saved, staged, backup = _journal_artifacts(journal)
    expected = journal["new_certificate_sha256"]
    if not _path_has_sha256(saved, expected):
        if not _path_has_sha256(staged, expected):
            raise ClientPairingRecoveryError(
                "Mission Legal cannot restore the confirmed server certificate."
            )
        if saved.exists() and journal["previous_certificate_existed"]:
            previous_hash = journal.get("previous_certificate_sha256")
            if not _path_has_sha256(saved, previous_hash):
                raise ClientPairingRecoveryError(
                    "The CA certificate changed during pairing recovery."
                )
            if backup is None:
                raise ClientPairingRecoveryError(
                    "The interrupted pairing recovery record is invalid."
                )
            if not backup.exists():
                os.replace(saved, backup)
        elif saved.exists():
            raise ClientPairingRecoveryError(
                "The CA certificate changed during pairing recovery."
            )
        os.replace(staged, saved)

    settings = QSettings(ORG, APP)
    settings.setValue("server/url", journal["server_url"])
    settings.setValue("server/ca_certificate", str(saved.resolve()))
    settings.sync()
    if settings.status() != QSettings.NoError:
        raise ClientPairingRecoveryError(
            "Windows could not save the new server connection."
        )


def _rollback_local_state(journal, credential_path):
    # Restore every durable public/local pointer before deleting the journal.
    # Callers retain the journal if any restoration step fails.
    settings = QSettings(ORG, APP)
    _restore_settings(settings, _settings_from_journal(journal["previous_settings"]))
    _restore_previous_certificate(journal)
    _restore_previous_device_pointer(
        credential_path,
        journal,
        expected_new_device_id=journal.get("new_device_id"),
    )


def _cleanup_completed_journal(path, journal):
    _saved, staged, backup = _journal_artifacts(journal)
    _unlink_pairing_artifact(staged, "the staged CA certificate")
    _unlink_pairing_artifact(backup, "the previous CA certificate backup")
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        raise ClientPairingRecoveryError(
            "Windows could not finish the pairing recovery record cleanup."
        ) from exc


def _recover_interrupted_pairing_locked():
    path = _journal_path()
    if not path.exists():
        return False
    journal = _load_journal(path)
    credential_path = _configuration_dir() / "api-device.json"
    new_device_id = journal.get("new_device_id")

    if not new_device_id:
        try:
            _rollback_local_state(journal, credential_path)
            _cleanup_completed_journal(path, journal)
        except Exception as exc:
            if isinstance(exc, ClientPairingRecoveryError):
                raise
            raise ClientPairingRecoveryError(
                "Windows could not restore the interrupted server connection."
            ) from exc
        return "rolled-back"

    current_id = _read_current_device_id(credential_path)
    previous_id = _device_id_from_bytes(
        _decode_previous_device_pointer(journal["previous_device_pointer"])
    )
    if current_id not in {None, previous_id, new_device_id}:
        raise ClientPairingRecoveryError(
            "The saved device registration changed during pairing recovery."
        )

    def select_new_device_pointer():
        if _read_current_device_id(credential_path) != new_device_id:
            _atomic_write_bytes(
                credential_path,
                (json.dumps({"device_id": new_device_id}, indent=2) + "\n").encode(
                    "utf-8"
                ),
                suffix=".pointer.recovery.tmp",
            )

    # A durable confirmed phase is authoritative. Replaying the local commit
    # requires neither network access nor a Credential Manager read, which is
    # important during transient Windows credential-service outages.
    if journal["phase"] == "confirmed":
        try:
            select_new_device_pointer()
            _apply_new_local_state(journal)
            _cleanup_completed_journal(path, journal)
        except Exception as exc:
            if isinstance(exc, ClientPairingRecoveryError):
                raise
            raise ClientPairingRecoveryError(
                "The server confirmed this computer, but Windows could not finish "
                "saving the new local connection. Reopen Mission Legal to retry."
            ) from exc
        return "confirmed"

    client = MissionLegalApiClient(
        journal["server_url"],
        # Credential Manager is local. Check it before requiring the staged CA
        # so a crash during completed rollback cleanup can finish even when the
        # new public certificate has already been removed.
        certificate=True,
        credential_path=credential_path,
    )
    if not client.pairing_credential_available(new_device_id):
        try:
            _rollback_local_state(journal, credential_path)
            _cleanup_completed_journal(path, journal)
        except Exception as exc:
            if isinstance(exc, ClientPairingRecoveryError):
                raise
            raise ClientPairingRecoveryError(
                "Windows could not restore the interrupted server connection."
            ) from exc
        return "rolled-back"

    certificate = _verification_certificate(journal)
    client.certificate = str(certificate)
    select_new_device_pointer()

    try:
        client.confirm_pairing()
        confirmed = True
    except Exception as confirmation_error:
        try:
            confirmed = client.cancel_pairing() == "confirmed"
        except Exception as cancellation_error:
            logger.warning(
                "Interrupted pairing remains unresolved; local credentials and "
                "the recovery journal were preserved",
                exc_info=True,
            )
            raise ClientPairingRecoveryError(
                "Mission Legal could not verify whether the interrupted pairing "
                "was confirmed. The new device credential was preserved. Check "
                "the server connection and reopen Mission Legal."
            ) from confirmation_error
        if not confirmed:
            try:
                _rollback_local_state(journal, credential_path)
                _cleanup_completed_journal(path, journal)
            except Exception as rollback_error:
                logger.warning(
                    "Could not restore local state after the server rejected an "
                    "interrupted pairing",
                    exc_info=True,
                )
                raise ClientPairingRecoveryError(
                    "The server rejected the interrupted pairing, but Windows "
                    "could not restore the previous local connection."
                ) from confirmation_error
            return "rolled-back"

    try:
        journal["phase"] = "confirmed"
        _write_journal(path, journal)
        _apply_new_local_state(journal)
        _cleanup_completed_journal(path, journal)
    except Exception as exc:
        if isinstance(exc, ClientPairingRecoveryError):
            raise
        raise ClientPairingRecoveryError(
            "The server confirmed this computer, but Windows could not finish "
            "saving the new local connection. Reopen Mission Legal to retry."
        ) from exc
    return "confirmed"


def recover_interrupted_pairing():
    """Reconcile a prior process termination before normal client startup."""

    with interprocess_file_lock(_lock_path()):
        return _recover_interrupted_pairing_locked()


def pair_client(server_url, certificate, pairing_code, device_name=None):
    """Serialize the complete per-user pairing transaction across processes."""

    with interprocess_file_lock(_lock_path()):
        _recover_interrupted_pairing_locked()
        return _pair_client_locked(
            server_url,
            certificate,
            pairing_code,
            device_name=device_name,
        )


def _pair_client_locked(server_url, certificate, pairing_code, device_name=None):
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
    transaction_id = str(uuid.uuid4())
    configuration = _configuration_dir()
    if staged_certificate is not None:
        durable_staged_certificate = configuration / (
            f".{saved_certificate.name}.{transaction_id}.pairing"
        )
        os.replace(staged_certificate, durable_staged_certificate)
        staged_certificate = durable_staged_certificate
        verification_certificate = staged_certificate
    certificate_backup = (
        configuration / f".{saved_certificate.name}.{transaction_id}.rollback"
        if saved_certificate.exists() and staged_certificate is not None
        else None
    )
    settings = QSettings(ORG, APP)
    settings_snapshot = _snapshot_settings(settings, _SETTING_KEYS)
    credential_path = configuration / "api-device.json"
    previous_device_pointer = _read_previous_device_pointer(credential_path)
    journal = {
        "version": _JOURNAL_VERSION,
        "transaction_id": transaction_id,
        "phase": "prepared",
        "server_url": normalized_url,
        "new_device_id": None,
        "previous_device_pointer": previous_device_pointer,
        "previous_settings": _settings_for_journal(settings_snapshot),
        "previous_certificate_existed": saved_certificate.exists(),
        "previous_certificate_sha256": (
            _sha256(saved_certificate) if saved_certificate.exists() else None
        ),
        "new_certificate_sha256": _sha256(verification_certificate),
        "staged_certificate_name": (
            staged_certificate.name if staged_certificate is not None else None
        ),
        "certificate_backup_name": (
            certificate_backup.name if certificate_backup is not None else None
        ),
    }
    journal_path = _journal_path()
    client = None
    paired = None
    pairing_confirmed = False
    try:
        client = MissionLegalApiClient(
            normalized_url,
            certificate=str(verification_certificate),
        )
        health = client.health()
        client.validate_compatibility(health)
        _write_journal(journal_path, journal)

        def record_remote_registration(device_id):
            journal["new_device_id"] = str(device_id)
            journal["phase"] = "registered"
            _write_journal(journal_path, journal)

        paired = client.begin_pair(
            code,
            name,
            before_local_persist=record_remote_registration,
        )
        _apply_new_local_state(journal)
        journal["phase"] = "local-state-applied"
        _write_journal(journal_path, journal)
        client.certificate = str(saved_certificate)

        client.confirm_pairing()
        pairing_confirmed = True
        journal["phase"] = "confirmed"
        _write_journal(journal_path, journal)
    except Exception as pairing_error:
        if isinstance(pairing_error, ApiPairingRecoveryRequired):
            raise ClientPairingRecoveryError(
                "The server may have saved this computer, but Windows could not "
                "finish the local pairing. The new credential and recovery "
                "record were preserved. Reopen Mission Legal to reconcile it."
            ) from pairing_error
        recovered_confirmation = False
        cancellation_failed = False
        if paired is not None and client is not None:
            try:
                # A local-state failure may have already moved the staged CA to
                # its final path. Select whichever verified copy remains before
                # asking the server to cancel the pending registration.
                client.certificate = str(_verification_certificate(journal))
                recovered_confirmation = client.cancel_pairing() == "confirmed"
            except Exception:
                cancellation_failed = True
                logger.warning(
                    "Could not cancel an incomplete server pairing; the pending "
                    "registration will expire automatically",
                    exc_info=True,
                )
        if recovered_confirmation:
            pairing_confirmed = True
        elif cancellation_failed:
            raise ClientPairingRecoveryError(
                "The server connection was interrupted after this computer saved "
                "its pairing. Close and reopen Mission Legal to verify the connection."
            ) from pairing_error
        else:
            try:
                _rollback_local_state(journal, credential_path)
                _cleanup_completed_journal(journal_path, journal)
            except Exception:
                logger.warning(
                    "Could not restore local connection state after pairing failed",
                    exc_info=True,
                )
                raise ClientPairingRecoveryError(
                    "Pairing failed, and Windows could not safely restore the "
                    "previous local connection. Reopen Mission Legal to recover."
                ) from pairing_error
        if not recovered_confirmation:
            raise

    if pairing_confirmed:
        try:
            journal["phase"] = "confirmed"
            _write_journal(journal_path, journal)
            _apply_new_local_state(journal)
            _cleanup_completed_journal(journal_path, journal)
        except Exception as exc:
            if isinstance(exc, ClientPairingRecoveryError):
                raise
            raise ClientPairingRecoveryError(
                "The server confirmed this computer, but Windows could not finish "
                "saving the new local connection. Reopen Mission Legal to retry."
            ) from exc

    return ClientPairingResult(
        device_id=str(paired["device_id"]),
        server_url=normalized_url,
        api_version=str(health.get("api_version", "")),
        schema_version=health.get("schema_version", ""),
        saved_certificate=saved_certificate,
    )
