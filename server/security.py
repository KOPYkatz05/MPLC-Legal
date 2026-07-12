import hashlib
import json
import secrets
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.runtime import get_app_data_dir


PAIRING_LIFETIME_MINUTES = 10


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

    def register(self, device_name):
        device_id = secrets.token_hex(16)
        credential = secrets.token_urlsafe(48)
        payload = self._read()
        payload["devices"].append(
            {
                "device_id": device_id,
                "device_name": device_name.strip(),
                "credential_hash": _hash_secret(credential),
                "created_at": _utcnow().isoformat(),
                "revoked_at": None,
            }
        )
        self._write(payload)
        return {"device_id": device_id, "credential": credential}

    def authenticate(self, device_id, credential):
        credential_hash = _hash_secret(credential)
        for device in self._read()["devices"]:
            if (
                secrets.compare_digest(device.get("device_id", ""), device_id)
                and not device.get("revoked_at")
                and secrets.compare_digest(
                    device.get("credential_hash", ""), credential_hash
                )
            ):
                return {
                    "device_id": device["device_id"],
                    "device_name": device["device_name"],
                }
        return None

    def revoke(self, device_id):
        payload = self._read()
        changed = False
        for device in payload["devices"]:
            if device.get("device_id") == device_id and not device.get("revoked_at"):
                device["revoked_at"] = _utcnow().isoformat()
                changed = True
        if changed:
            self._write(payload)
        return changed

    def list_devices(self):
        return [
            {
                "device_id": device.get("device_id"),
                "device_name": device.get("device_name"),
                "created_at": device.get("created_at"),
                "revoked_at": device.get("revoked_at"),
            }
            for device in self._read()["devices"]
        ]


class PairingCodeStore:
    def __init__(self, path=None):
        self.path = Path(
            path or (get_app_data_dir() / "Configuration" / "pairing.json")
        )

    def create(self, lifetime_minutes=PAIRING_LIFETIME_MINUTES):
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
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(payload["expires_at"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return False
        attempts_remaining = int(payload.get("attempts_remaining", 0))
        valid = attempts_remaining > 0 and expires_at > _utcnow() and secrets.compare_digest(
            payload.get("code_hash", ""), _hash_secret(code)
        )
        if valid:
            self.path.unlink(missing_ok=True)
        elif attempts_remaining > 0 and expires_at > _utcnow():
            payload["attempts_remaining"] = attempts_remaining - 1
            _atomic_json_write(self.path, payload)
        return valid
