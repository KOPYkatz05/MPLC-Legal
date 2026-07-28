import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.security import DeviceCredentialStore, PairingCodeStore
from version import APP_VERSION, MIN_SUPPORTED_CLIENT_VERSION


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / f"mission-legal-server-app-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_pairing_bootstrap_returns_only_public_ca_identity(tmp_path, monkeypatch):
    public_ca = tmp_path / "Public" / "mission-legal-ca.pem"
    public_ca.parent.mkdir(parents=True)
    public_ca.write_text(
        "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n",
        encoding="ascii",
    )
    monkeypatch.setattr("server.app.get_app_data_dir", lambda: tmp_path)
    client = TestClient(
        create_app(
            DeviceCredentialStore(tmp_path / "devices.json"),
            PairingCodeStore(tmp_path / "pairing.json"),
            manage_lifecycle=False,
        )
    )

    response = client.get("/pair/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["server_id"] == payload["ca_sha256"]
    assert payload["ca_certificate_pem"].startswith("-----BEGIN CERTIFICATE-----")
    assert "PRIVATE KEY" not in response.text


def test_remote_pairing_is_blocked_when_current_network_is_not_trusted(tmp_path):
    pairing = PairingCodeStore(tmp_path / "pairing.json")
    code = pairing.create()["code"]
    client = TestClient(
        create_app(
            DeviceCredentialStore(tmp_path / "devices.json"),
            pairing,
            manage_lifecycle=False,
            network_trust_provider=lambda: False,
        )
    )

    response = client.post(
        "/pair",
        json={"code": code, "device_name": "Unknown network"},
    )

    assert response.status_code == 403


def test_pairing_and_authenticated_session(tmp_path):
    devices = DeviceCredentialStore(tmp_path / "devices.json")
    pairing = PairingCodeStore(tmp_path / "pairing.json")
    code = pairing.create()["code"]
    client = TestClient(create_app(devices, pairing, manage_lifecycle=False))

    response = client.post(
        "/pair",
        json={
            "code": code,
            "device_name": "Second computer",
            "deferred_confirmation": True,
        },
    )
    assert response.status_code == 201
    credentials = response.json()

    pending_session = client.get(
        "/v1/session",
        headers={
            "X-Device-ID": credentials["device_id"],
            "X-Device-Credential": credentials["credential"],
        },
    )
    assert pending_session.status_code == 401

    confirmed = client.post(
        "/pair/confirm",
        headers={
            "X-Device-ID": credentials["device_id"],
            "X-Device-Credential": credentials["credential"],
        },
    )
    assert confirmed.status_code == 200
    assert client.post(
        "/pair/confirm",
        headers={
            "X-Device-ID": credentials["device_id"],
            "X-Device-Credential": credentials["credential"],
        },
    ).status_code == 200

    session = client.get(
        "/v1/session",
        headers={
            "X-Device-ID": credentials["device_id"],
            "X-Device-Credential": credentials["credential"],
        },
    )
    assert session.status_code == 200
    assert session.json()["device"]["device_name"] == "Second computer"
    assert session.json()["app_version"] == APP_VERSION
    assert session.json()["minimum_client_version"] == MIN_SUPPORTED_CLIENT_VERSION


def test_failed_registration_does_not_consume_pairing_code(tmp_path):
    class FailsOnceStore(DeviceCredentialStore):
        def __init__(self, path):
            super().__init__(path)
            self.fail_next = True

        def register(self, device_name, *, pending_confirmation=False):
            if self.fail_next:
                self.fail_next = False
                raise OSError("device store unavailable")
            return super().register(
                device_name,
                pending_confirmation=pending_confirmation,
            )

    devices = FailsOnceStore(tmp_path / "devices.json")
    pairing = PairingCodeStore(tmp_path / "pairing.json")
    code = pairing.create()["code"]
    client = TestClient(
        create_app(devices, pairing, manage_lifecycle=False),
        raise_server_exceptions=False,
    )

    failed = client.post(
        "/pair",
        json={
            "code": code,
            "device_name": "Retry client",
            "deferred_confirmation": True,
        },
    )
    retried = client.post(
        "/pair",
        json={
            "code": code,
            "device_name": "Retry client",
            "deferred_confirmation": True,
        },
    )

    assert failed.status_code == 500
    assert retried.status_code == 201


def test_pending_pairing_can_be_cancelled_without_active_device(tmp_path):
    devices = DeviceCredentialStore(tmp_path / "devices.json")
    pairing = PairingCodeStore(tmp_path / "pairing.json")
    code = pairing.create()["code"]
    client = TestClient(create_app(devices, pairing, manage_lifecycle=False))
    registered = client.post(
        "/pair",
        json={
            "code": code,
            "device_name": "Cancelled client",
            "deferred_confirmation": True,
        },
    ).json()
    headers = {
        "X-Device-ID": registered["device_id"],
        "X-Device-Credential": registered["credential"],
    }

    cancelled = client.delete("/pair/pending", headers=headers)

    assert cancelled.status_code == 200
    assert cancelled.json()["removed"] is True
    assert client.post("/pair/confirm", headers=headers).status_code == 401


def test_legacy_pairing_request_remains_immediately_active(tmp_path):
    devices = DeviceCredentialStore(tmp_path / "devices.json")
    pairing = PairingCodeStore(tmp_path / "pairing.json")
    code = pairing.create()["code"]
    client = TestClient(create_app(devices, pairing, manage_lifecycle=False))

    registered = client.post(
        "/pair", json={"code": code, "device_name": "Legacy client"}
    )
    assert registered.status_code == 201
    credentials = registered.json()
    session = client.get(
        "/v1/session",
        headers={
            "X-Device-ID": credentials["device_id"],
            "X-Device-Credential": credentials["credential"],
        },
    )

    assert session.status_code == 200
    assert session.json()["device"]["device_name"] == "Legacy client"
    assert client.delete(
        "/pair/pending",
        headers={
            "X-Device-ID": credentials["device_id"],
            "X-Device-Credential": credentials["credential"],
        },
    ).status_code == 409
    assert devices.authenticate(
        credentials["device_id"], credentials["credential"]
    ) is not None


def test_session_rejects_unpaired_device(tmp_path):
    client = TestClient(
        create_app(
            DeviceCredentialStore(tmp_path / "devices.json"),
            PairingCodeStore(tmp_path / "pairing.json"),
            manage_lifecycle=False,
        )
    )

    assert client.get("/v1/session").status_code == 401
