import hashlib
import json
import secrets
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.runtime import get_app_data_dir
from utils.interprocess_lock import interprocess_file_lock


PAIRING_LIFETIME_MINUTES = 10
PENDING_DEVICE_LIFETIME_MINUTES = 15
_PATH_LOCKS = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path):
    key = str(Path(path).resolve()).casefold()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _utcnow():
    return datetime.now(timezone.utc)


def _hash_secret(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_json_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.stem}_",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(4):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


class DeviceCredentialStore:
    def __init__(self, path=None):
        self.path = Path(
            path or (get_app_data_dir() / "Configuration" / "devices.json")
        )
        self._lock = _path_lock(self.path)

    def _read(self):
        if not self.path.exists():
            return {"devices": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"devices": []}
        devices = payload.get("devices")
        return payload if isinstance(devices, list) else {"devices": []}

    def _write(self, payload):
        _atomic_json_write(self.path, payload)

    def register(self, device_name, *, pending_confirmation=False):
        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            device_id = secrets.token_hex(16)
            credential = secrets.token_urlsafe(48)
            payload = self._read()
            device = {
                "device_id": device_id,
                "device_name": device_name.strip(),
                "credential_hash": _hash_secret(credential),
                "created_at": _utcnow().isoformat(),
                "revoked_at": None,
            }
            if pending_confirmation:
                device["pending_confirmation"] = True
                device["pending_expires_at"] = (
                    _utcnow() + timedelta(minutes=PENDING_DEVICE_LIFETIME_MINUTES)
                ).isoformat()
            payload["devices"].append(device)
            self._write(payload)
        return {"device_id": device_id, "credential": credential}

    @staticmethod
    def _pending_is_current(device):
        if not device.get("pending_confirmation"):
            return False
        try:
            return datetime.fromisoformat(device["pending_expires_at"]) > _utcnow()
        except (KeyError, TypeError, ValueError):
            return False

    def authenticate(self, device_id, credential, *, allow_pending=False):
        credential_hash = _hash_secret(credential)
        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            payload = self._read()
            original_count = len(payload["devices"])
            payload["devices"] = [
                device
                for device in payload["devices"]
                if not device.get("pending_confirmation")
                or self._pending_is_current(device)
            ]
            if len(payload["devices"]) != original_count:
                self._write(payload)
            for device in payload["devices"]:
                if (
                    secrets.compare_digest(device.get("device_id", ""), device_id)
                    and not device.get("revoked_at")
                    and (
                        not device.get("pending_confirmation") or allow_pending
                    )
                    and secrets.compare_digest(
                        device.get("credential_hash", ""), credential_hash
                    )
                ):
                    return {
                        "device_id": device["device_id"],
                        "device_name": device["device_name"],
                        "pending_confirmation": bool(
                            device.get("pending_confirmation")
                        ),
                    }
        return None

    def confirm(self, device_id):
        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            payload = self._read()
            for device in payload["devices"]:
                if device.get("device_id") != device_id:
                    continue
                if not self._pending_is_current(device):
                    return False
                device.pop("pending_confirmation", None)
                device.pop("pending_expires_at", None)
                device["confirmed_at"] = _utcnow().isoformat()
                self._write(payload)
                return True
            return False

    def revoke(self, device_id):
        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            payload = self._read()
            changed = False
            for device in payload["devices"]:
                if device.get("device_id") == device_id and not device.get("revoked_at"):
                    device["revoked_at"] = _utcnow().isoformat()
                    changed = True
            if changed:
                self._write(payload)
        return changed

    def remove(self, device_id):
        """Remove a registration that was never returned to a pairing client."""

        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            payload = self._read()
            retained = [
                device
                for device in payload["devices"]
                if device.get("device_id") != device_id
            ]
            if len(retained) == len(payload["devices"]):
                return False
            payload["devices"] = retained
            self._write(payload)
            return True

    def remove_pending(self, device_id):
        """Remove only a still-pending registration, rechecking under lock."""

        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            payload = self._read()
            for index, device in enumerate(payload["devices"]):
                if device.get("device_id") != device_id:
                    continue
                if not device.get("pending_confirmation"):
                    return False
                del payload["devices"][index]
                self._write(payload)
                return True
            return False

    def list_devices(self):
        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            payload = self._read()
            original_count = len(payload["devices"])
            payload["devices"] = [
                device
                for device in payload["devices"]
                if not device.get("pending_confirmation")
                or self._pending_is_current(device)
            ]
            if len(payload["devices"]) != original_count:
                self._write(payload)
            return [
                {
                    "device_id": device.get("device_id"),
                    "device_name": device.get("device_name"),
                    "created_at": device.get("created_at"),
                    "revoked_at": device.get("revoked_at"),
                    "pending_confirmation": bool(
                        device.get("pending_confirmation")
                    ),
                }
                for device in payload["devices"]
            ]


class PairingCodeStore:
    def __init__(self, path=None):
        self.path = Path(
            path or (get_app_data_dir() / "Configuration" / "pairing.json")
        )
        self._lock = _path_lock(self.path)

    def create(self, lifetime_minutes=PAIRING_LIFETIME_MINUTES):
        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            code = f"{secrets.randbelow(1_000_000):06d}"
            expires_at = _utcnow() + timedelta(minutes=lifetime_minutes)
            payload = {
                "code_hash": _hash_secret(code),
                "expires_at": expires_at.isoformat(),
                "attempts_remaining": 5,
            }
            _atomic_json_write(self.path, payload)
        return {"code": code, "expires_at": expires_at}

    def consume(self, code):
        valid, _result = self.consume_and_execute(code, lambda: None)
        return valid

    def consume_and_execute(self, code, action, rollback=None):
        """Run ``action`` once while atomically claiming a valid pairing code.

        The callback runs before the code file is removed, so a failed device
        registration leaves the one-use code available for a safe retry. The
        per-path lock prevents concurrent requests from both claiming it.
        """

        with self._lock, interprocess_file_lock(f"{self.path}.lock"):
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(payload["expires_at"])
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                return False, None
            attempts_remaining = int(payload.get("attempts_remaining", 0))
            valid = (
                attempts_remaining > 0
                and expires_at > _utcnow()
                and secrets.compare_digest(
                    payload.get("code_hash", ""), _hash_secret(code)
                )
            )
            if not valid:
                if attempts_remaining > 0 and expires_at > _utcnow():
                    payload["attempts_remaining"] = attempts_remaining - 1
                    _atomic_json_write(self.path, payload)
                return False, None

            result = action()
            try:
                self.path.unlink(missing_ok=False)
            except Exception:
                if rollback is not None:
                    rollback(result)
                raise
            return True, result
