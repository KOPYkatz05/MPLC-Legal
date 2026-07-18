import json
import os
import ssl
from datetime import date, datetime
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version

from database.runtime import get_client_data_dir
from version import (
    APP_VERSION,
    MAX_SUPPORTED_SERVER_API_VERSION,
    MIN_SUPPORTED_SERVER_API_VERSION,
)


KEYRING_SERVICE = "MissionLegalLocalAPI"


class ApiUnavailableError(RuntimeError):
    pass


class ApiAuthenticationError(RuntimeError):
    pass


class ApiCompatibilityError(RuntimeError):
    """Describe why a client/server pair cannot communicate safely."""

    CLIENT_UPDATE_REQUIRED = "client-update-required"
    SERVER_UPDATE_REQUIRED = "server-update-required"
    INVALID_METADATA = "invalid-metadata"

    def __init__(
        self,
        message,
        *,
        reason=INVALID_METADATA,
        required_client_version=None,
    ):
        super().__init__(message)
        self.reason = str(reason)
        self.required_client_version = (
            str(required_client_version) if required_client_version else None
        )

    @property
    def client_update_required(self):
        return self.reason == self.CLIENT_UPDATE_REQUIRED


class MissionLegalApiClient:
    def __init__(
        self,
        base_url,
        *,
        certificate=None,
        credential_path=None,
        transport=None,
        timeout=10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.certificate = certificate if certificate is not None else True
        self.credential_path = Path(
            credential_path
            or (get_client_data_dir() / "Configuration" / "api-device.json")
        )
        self._transport = transport
        self.timeout = timeout

    @classmethod
    def from_environment(cls):
        if os.environ.get("MISSION_LEGAL_SERVER_PROCESS") == "1":
            return None
        base_url = os.environ.get("MISSION_LEGAL_API_URL")
        certificate = os.environ.get("MISSION_LEGAL_API_CERT")
        if not base_url:
            try:
                from PySide6.QtCore import QSettings
                from app_identity import APP, ORG

                settings = QSettings(ORG, APP)
                base_url = settings.value("server/url", None)
                certificate = certificate or settings.value(
                    "server/ca_certificate", None
                )
            except Exception:
                base_url = None
        if not base_url:
            return None
        return cls(base_url, certificate=certificate or True)

    def _client(self):
        verify = self.certificate
        if isinstance(verify, (str, Path)):
            verify = ssl.create_default_context(cafile=str(verify))
        return httpx.Client(
            base_url=self.base_url,
            verify=verify,
            timeout=self.timeout,
            transport=self._transport,
        )

    def _read_device(self):
        try:
            return json.loads(self.credential_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _keyring():
        try:
            import keyring

            return keyring
        except Exception:
            return None

    def _credential(self, device_id):
        keyring = self._keyring()
        if keyring is None:
            return None
        try:
            return keyring.get_password(KEYRING_SERVICE, device_id)
        except Exception:
            return None

    def _headers(self):
        device = self._read_device()
        if not device or not device.get("device_id"):
            raise ApiAuthenticationError("This computer has not been paired")
        credential = self._credential(device["device_id"])
        if not credential:
            raise ApiAuthenticationError("Paired device credentials are unavailable")
        return {
            "X-Device-ID": device["device_id"],
            "X-Device-Credential": credential,
        }

    def _request(self, method, path, *, authenticated=True, **kwargs):
        if authenticated:
            kwargs.setdefault("headers", {}).update(self._headers())
        try:
            with self._client() as client:
                response = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            self._report_unavailable(exc)
            raise ApiUnavailableError(str(exc)) from exc
        if response.status_code == 401:
            raise ApiAuthenticationError(response.json().get("detail", "Unauthorized"))
        response.raise_for_status()
        self._report_restored()
        return response.json()

    @staticmethod
    def _report_unavailable(detail):
        try:
            from services.api_connection_state import api_connection_state

            api_connection_state().report_unavailable(detail)
        except Exception:
            pass

    @staticmethod
    def _report_restored():
        try:
            from services.api_connection_state import api_connection_state

            api_connection_state().report_restored()
        except Exception:
            pass

    def health(self):
        return self._request("GET", "/health", authenticated=False)

    @staticmethod
    def validate_compatibility(payload):
        if not isinstance(payload, dict):
            raise ApiCompatibilityError(
                "Server compatibility metadata is invalid",
                reason=ApiCompatibilityError.INVALID_METADATA,
            )

        server_api = str(payload.get("api_version", "")).strip()
        if not server_api:
            raise ApiCompatibilityError(
                "Server compatibility metadata is missing",
                reason=ApiCompatibilityError.INVALID_METADATA,
            )

        try:
            server_api_number = int(server_api)
            minimum_api = int(MIN_SUPPORTED_SERVER_API_VERSION)
            maximum_api = int(MAX_SUPPORTED_SERVER_API_VERSION)
        except (TypeError, ValueError) as exc:
            raise ApiCompatibilityError(
                "Server API compatibility metadata is invalid",
                reason=ApiCompatibilityError.INVALID_METADATA,
            ) from exc

        minimum_client = payload.get("minimum_client_version")
        installed_version = Version(APP_VERSION)
        required_version = None
        if minimum_client:
            try:
                required_version = Version(str(minimum_client))
            except InvalidVersion as exc:
                raise ApiCompatibilityError(
                    "Server client-version compatibility metadata is invalid",
                    reason=ApiCompatibilityError.INVALID_METADATA,
                ) from exc

        if server_api_number < minimum_api:
            raise ApiCompatibilityError(
                f"The server API is incompatible. This client supports API "
                f"{minimum_api} through "
                f"{maximum_api}, but the server uses API {server_api}. "
                "Update Mission Legal Server on the main computer.",
                reason=ApiCompatibilityError.SERVER_UPDATE_REQUIRED,
            )

        if server_api_number > maximum_api:
            if required_version is None or required_version <= installed_version:
                raise ApiCompatibilityError(
                    "The server uses a newer API but does not identify a newer "
                    "compatible client version. Repair or update Mission Legal "
                    "Server on the main computer.",
                    reason=ApiCompatibilityError.INVALID_METADATA,
                )
            raise ApiCompatibilityError(
                f"The server API is incompatible. This client supports API "
                f"{minimum_api} through "
                f"{maximum_api}, but the server uses API {server_api}.",
                reason=ApiCompatibilityError.CLIENT_UPDATE_REQUIRED,
                required_client_version=required_version,
            )

        if required_version is not None and installed_version < required_version:
            raise ApiCompatibilityError(
                f"Mission Legal {required_version} or newer is required. "
                f"This computer is running {installed_version}.",
                reason=ApiCompatibilityError.CLIENT_UPDATE_REQUIRED,
                required_client_version=required_version,
            )

        # The database schema is an implementation detail of the authoritative
        # server. Remote clients intentionally validate the API contract rather
        # than requiring the server's internal schema number to match.
        return True

    def pair(self, code, device_name):
        payload = self._request(
            "POST",
            "/pair",
            authenticated=False,
            json={"code": code, "device_name": device_name},
        )
        keyring = self._keyring()
        if keyring is None:
            raise ApiAuthenticationError("Windows Credential Manager is unavailable")
        keyring.set_password(KEYRING_SERVICE, payload["device_id"], payload["credential"])
        self.credential_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.credential_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"device_id": payload["device_id"]}, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.credential_path)
        return {"device_id": payload["device_id"]}

    def session(self):
        return self._request("GET", "/v1/session")

    def get(self, path, **kwargs):
        return self._request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self._request("POST", path, **kwargs)

    def patch(self, path, **kwargs):
        return self._request("PATCH", path, **kwargs)

    def delete(self, path, **kwargs):
        return self._request("DELETE", path, **kwargs)

    def upload(self, path, *, file_path, data):
        headers = self._headers()
        try:
            with self._client() as client, Path(file_path).open("rb") as handle:
                response = client.post(
                    path,
                    headers=headers,
                    data=data,
                    files={"file": (Path(file_path).name, handle, "application/octet-stream")},
                )
        except (httpx.HTTPError, OSError) as exc:
            self._report_unavailable(exc)
            raise ApiUnavailableError(str(exc)) from exc
        if response.status_code == 401:
            raise ApiAuthenticationError(response.json().get("detail", "Unauthorized"))
        response.raise_for_status()
        self._report_restored()
        return response.json()

    def download(self, path, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".downloading")
        try:
            with self._client() as client:
                response = client.get(path, headers=self._headers())
                response.raise_for_status()
                temporary.write_bytes(response.content)
            temporary.replace(destination)
        except (httpx.HTTPError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            self._report_unavailable(exc)
            raise ApiUnavailableError(str(exc)) from exc
        self._report_restored()
        return destination


class RemoteRecord:
    """Attribute-compatible representation of an API database record."""

    def __init__(self, payload):
        for key, value in payload.items():
            if isinstance(value, dict):
                value = RemoteRecord(value)
            elif isinstance(value, list):
                value = [RemoteRecord(item) if isinstance(item, dict) else item for item in value]
            elif isinstance(value, str):
                try:
                    if key.endswith("_at"):
                        value = datetime.fromisoformat(value)
                    elif key.endswith("_date") or "expiration" in key:
                        value = date.fromisoformat(value)
                except ValueError:
                    pass
            setattr(self, key, value)


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value
