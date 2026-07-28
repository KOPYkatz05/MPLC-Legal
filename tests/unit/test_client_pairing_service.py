import base64
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from services import client_pairing_service as pairing
from services.pairing_package import encode_pairing_package


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / f"mission-legal-client-pairing-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


@pytest.fixture
def isolated_qsettings(monkeypatch):
    class Settings:
        NoError = 0
        values = {}

        def __init__(self, *_args):
            pass

        def setValue(self, key, value):
            type(self).values[key] = value

        def contains(self, key):
            return key in type(self).values

        def value(self, key, default=None):
            return type(self).values.get(key, default)

        def remove(self, key):
            type(self).values.pop(key, None)

        def sync(self):
            pass

        def status(self):
            return self.NoError

    monkeypatch.setattr(pairing, "QSettings", Settings)
    return Settings


def _digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _recovery_journal(
    *,
    transaction_id,
    phase,
    new_device_id,
    previous_pointer,
    old_certificate,
    new_certificate,
    staged_name,
    backup_name,
):
    return {
        "version": 1,
        "transaction_id": transaction_id,
        "phase": phase,
        "server_url": "https://new-main-computer:8765",
        "new_device_id": new_device_id,
        "previous_device_pointer": {
            "existed": previous_pointer is not None,
            "bytes_base64": (
                base64.b64encode(previous_pointer).decode("ascii")
                if previous_pointer is not None
                else None
            ),
        },
        "previous_settings": {
            "server/url": {
                "contained": True,
                "value": "https://old-main-computer:8765",
            },
            "server/ca_certificate": {
                "contained": True,
                "value": "old-ca.pem",
            },
        },
        "previous_certificate_existed": old_certificate is not None,
        "previous_certificate_sha256": (
            _digest(old_certificate) if old_certificate is not None else None
        ),
        "new_certificate_sha256": _digest(new_certificate),
        "staged_certificate_name": staged_name,
        "certificate_backup_name": backup_name,
    }


@pytest.mark.parametrize(
    "value",
    [
        "http://main-computer:8765",
        "https://user:secret@main-computer:8765",
        "https://main-computer:8765/path",
        "https://main-computer:8765?token=secret",
        "https://main-computer:8765#fragment",
    ],
)
def test_server_url_rejects_insecure_or_secret_bearing_values(value):
    with pytest.raises(pairing.ClientPairingError):
        pairing.normalize_server_url(value)


def test_server_url_is_normalized_without_trailing_slash():
    assert (
        pairing.normalize_server_url("  https://MAIN-COMPUTER:8765/  ")
        == "https://MAIN-COMPUTER:8765"
    )


def test_stale_server_address_recovers_only_from_matching_saved_ca(
    monkeypatch,
    tmp_path,
    isolated_qsettings,
):
    from services.lan_discovery import DiscoveredServer, certificate_sha256

    certificate = (
        "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
    )
    ca_path = tmp_path / "mission-legal-ca.pem"
    ca_path.write_text(certificate, encoding="ascii")
    fingerprint = certificate_sha256(certificate)
    isolated_qsettings.values = {
        "server/url": "https://192.168.1.20:8765",
        "server/ca_certificate": str(ca_path),
    }
    monkeypatch.setattr(
        pairing,
        "discover_servers",
        lambda **_kwargs: (
            DiscoveredServer(
                server_id=fingerprint,
                name="Secretary Laptop",
                server_url="https://192.168.50.40:8765",
                ca_certificate_pem=certificate,
                ca_sha256=fingerprint,
            ),
        ),
    )
    refreshed = []
    monkeypatch.setattr(
        pairing.MissionLegalApiClient,
        "from_environment",
        lambda: refreshed.append(True),
    )

    recovered = pairing.recover_configured_server_address()

    assert recovered == "https://192.168.50.40:8765"
    assert (
        isolated_qsettings.values["server/url"]
        == "https://192.168.50.40:8765"
    )
    assert refreshed == [True]


@pytest.mark.parametrize("value", ["", "12345", "1234567", "ABC123"])
def test_pairing_code_requires_six_digits(value):
    with pytest.raises(pairing.ClientPairingError):
        pairing.validate_pairing_code(value)


def test_automatic_setup_code_supplies_address_certificate_and_pairing_code(
    monkeypatch,
):
    public_ca = "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
    setup_code = encode_pairing_package(
        server_url="https://192.168.108.50:8765",
        ca_certificate_pem=public_ca,
        pairing_code="123456",
        expires_at="2026-07-25T12:10:00+00:00",
    )
    observed = {}
    expected = object()

    def capture(server_url, certificate, pairing_code, device_name=None):
        observed.update(
            server_url=server_url,
            certificate=certificate,
            pairing_code=pairing_code,
            device_name=device_name,
        )
        return expected

    monkeypatch.setattr(pairing, "pair_client", capture)

    result = pairing.pair_client_from_setup_code(setup_code, "Front Office")

    assert result is expected
    assert observed == {
        "server_url": "https://192.168.108.50:8765",
        "certificate": public_ca,
        "pairing_code": "123456",
        "device_name": "Front Office",
    }


def test_embedded_public_ca_is_staged_without_a_manual_certificate_file(
    monkeypatch,
    tmp_path,
):
    public_ca = b"-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
    client_root = tmp_path / "client-data"
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    verification, saved, staged = pairing._stage_ca_certificate(public_ca)

    assert verification == staged
    assert saved == (
        client_root / "Configuration" / "mission-legal-ca.pem"
    ).resolve()
    assert staged.read_bytes() == public_ca


def test_pair_client_persists_public_certificate_and_connection(monkeypatch, tmp_path):
    source_certificate = tmp_path / "copied-from-server.pem"
    public_ca = "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
    source_certificate.write_text(public_ca, encoding="utf-8")
    client_root = tmp_path / "client-data"
    observed = {}

    class FakeClient:
        def __init__(self, base_url, *, certificate):
            observed["base_url"] = base_url
            observed["certificate"] = certificate
            observed["certificate_content"] = Path(certificate).read_text(
                encoding="utf-8"
            )

        def health(self):
            return {"api_version": "1", "schema_version": 7}

        def validate_compatibility(self, payload):
            observed["compatibility"] = dict(payload)

        def begin_pair(self, code, device_name, *, before_local_persist=None):
            observed["pair"] = (code, device_name)
            if before_local_persist is not None:
                before_local_persist("device-123")
                journal_text = (
                    client_root
                    / "Configuration"
                    / "pairing-transaction.json"
                ).read_text(encoding="utf-8")
                observed["journal_before_local_persist"] = json.loads(journal_text)
                assert "credential" not in journal_text.casefold()
            return {"device_id": "device-123"}

        def confirm_pairing(self):
            observed["confirmed"] = True

        def cancel_pairing(self):
            observed["cancelled"] = True

    class FakeSettings:
        NoError = 0
        values = {}

        def __init__(self, organization, application):
            observed["settings_identity"] = (organization, application)

        def setValue(self, key, value):
            self.values[key] = value

        def contains(self, key):
            return key in self.values

        def value(self, key):
            return self.values.get(key)

        def remove(self, key):
            self.values.pop(key, None)

        def sync(self):
            observed["settings_synced"] = True

        def status(self):
            return self.NoError

    monkeypatch.setattr(pairing, "MissionLegalApiClient", FakeClient)
    monkeypatch.setattr(pairing, "QSettings", FakeSettings)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    result = pairing.pair_client(
        "https://main-computer:8765/",
        source_certificate,
        "123456",
        "Front office",
    )

    saved_certificate = client_root / "Configuration" / "mission-legal-ca.pem"
    assert saved_certificate.read_text(encoding="utf-8") == public_ca
    assert result.device_id == "device-123"
    assert result.server_url == "https://main-computer:8765"
    assert observed["certificate_content"] == public_ca
    assert observed["pair"] == ("123456", "Front office")
    assert observed["journal_before_local_persist"]["new_device_id"] == "device-123"
    assert observed["confirmed"] is True
    assert FakeSettings.values["server/url"] == "https://main-computer:8765"
    assert FakeSettings.values["server/ca_certificate"] == str(
        saved_certificate.resolve()
    )


def test_failed_connection_does_not_replace_a_saved_certificate(
    monkeypatch,
    tmp_path,
    isolated_qsettings,
):
    _ = isolated_qsettings
    source_certificate = tmp_path / "wrong.pem"
    wrong_ca = "-----BEGIN CERTIFICATE-----\nWRONG CA\n-----END CERTIFICATE-----\n"
    source_certificate.write_text(wrong_ca, encoding="utf-8")
    client_root = tmp_path / "client-data"
    configuration = client_root / "Configuration"
    configuration.mkdir(parents=True)
    saved_certificate = configuration / "mission-legal-ca.pem"
    saved_certificate.write_text("KNOWN CA", encoding="utf-8")

    class FailingClient:
        def __init__(self, _base_url, *, certificate):
            assert Path(certificate).read_text(encoding="utf-8") == wrong_ca

        def health(self):
            raise RuntimeError("certificate rejected")

    monkeypatch.setattr(pairing, "MissionLegalApiClient", FailingClient)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    with pytest.raises(RuntimeError, match="certificate rejected"):
        pairing.pair_client(
            "https://main-computer:8765",
            source_certificate,
            "123456",
            "Front office",
        )

    assert saved_certificate.read_text(encoding="utf-8") == "KNOWN CA"
    assert not list(configuration.glob("*.pairing"))


def test_settings_failure_cancels_pending_pairing_and_restores_certificate(
    monkeypatch,
    tmp_path,
):
    source_certificate = tmp_path / "new.pem"
    source_certificate.write_text(
        "-----BEGIN CERTIFICATE-----\nNEW CA\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    client_root = tmp_path / "client-data"
    configuration = client_root / "Configuration"
    configuration.mkdir(parents=True)
    saved_certificate = configuration / "mission-legal-ca.pem"
    saved_certificate.write_text(
        "-----BEGIN CERTIFICATE-----\nOLD CA\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    observed = {"cancelled": 0, "confirmed": 0}

    class FakeClient:
        def __init__(self, _base_url, *, certificate):
            self.certificate = certificate

        def health(self):
            return {"api_version": "1", "schema_version": 7}

        def validate_compatibility(self, _payload):
            return True

        def begin_pair(self, _code, _name, *, before_local_persist=None):
            if before_local_persist is not None:
                before_local_persist("pending-device")
            return {"device_id": "pending-device"}

        def confirm_pairing(self):
            observed["confirmed"] += 1

        def cancel_pairing(self):
            observed["cancelled"] += 1

    class FailingSettings:
        NoError = 0
        status_checks = 0

        def __init__(self, *_args):
            self.values = {
                "server/url": "https://old-server:8765",
                "server/ca_certificate": "old-ca.pem",
            }

        def contains(self, key):
            return key in self.values

        def value(self, key):
            return self.values.get(key)

        def setValue(self, key, value):
            self.values[key] = value

        def remove(self, key):
            self.values.pop(key, None)

        def sync(self):
            pass

        def status(self):
            type(self).status_checks += 1
            return 1 if type(self).status_checks == 1 else self.NoError

    monkeypatch.setattr(pairing, "MissionLegalApiClient", FakeClient)
    monkeypatch.setattr(pairing, "QSettings", FailingSettings)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    with pytest.raises(pairing.ClientPairingError, match="could not save"):
        pairing.pair_client(
            "https://main-computer:8765",
            source_certificate,
            "123456",
            "Front office",
        )

    assert observed == {"cancelled": 1, "confirmed": 0}
    assert "OLD CA" in saved_certificate.read_text(encoding="utf-8")
    assert not list(configuration.glob("*.rollback"))


def test_keyring_failure_cancels_remote_pending_registration(monkeypatch, tmp_path):
    import httpx

    from services.api_client import ApiAuthenticationError, MissionLegalApiClient

    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/pair":
            return httpx.Response(
                201,
                json={"device_id": "pending-device", "credential": "secret"},
            )
        if request.method == "DELETE" and request.url.path == "/pair/pending":
            return httpx.Response(200, json={"removed": True})
        return httpx.Response(404)

    class FailingKeyring:
        @staticmethod
        def set_password(*_args):
            raise OSError("credential manager unavailable")

        @staticmethod
        def delete_password(*_args):
            return None

    client = MissionLegalApiClient(
        "https://main-computer:8765",
        credential_path=tmp_path / "api-device.json",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_keyring", lambda: FailingKeyring)

    with pytest.raises(ApiAuthenticationError, match="could not save"):
        client.begin_pair("123456", "Front office")

    assert requests == [("POST", "/pair"), ("DELETE", "/pair/pending")]
    assert not client.credential_path.exists()


def test_device_file_failure_cancels_remote_and_removes_keyring_entry(
    monkeypatch,
    tmp_path,
):
    import httpx

    from services.api_client import ApiAuthenticationError, MissionLegalApiClient

    requests = []
    keyring_events = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/pair" and request.method == "POST":
            return httpx.Response(
                201,
                json={"device_id": "pending-device", "credential": "secret"},
            )
        if request.url.path == "/pair/pending" and request.method == "DELETE":
            return httpx.Response(200, json={"removed": True})
        return httpx.Response(404)

    class FakeKeyring:
        @staticmethod
        def set_password(_service, device_id, _credential):
            keyring_events.append(("set", device_id))

        @staticmethod
        def delete_password(_service, device_id):
            keyring_events.append(("delete", device_id))

    credential_path = tmp_path / "Configuration" / "api-device.json"
    client = MissionLegalApiClient(
        "https://main-computer:8765",
        credential_path=credential_path,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_keyring", lambda: FakeKeyring)
    original_replace = Path.replace

    def fail_device_file_replace(path, target):
        if path.name.endswith(".pairing.tmp"):
            raise OSError("device file unavailable")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_device_file_replace)

    with pytest.raises(ApiAuthenticationError, match="could not save"):
        client.begin_pair("123456", "Front office")

    assert requests == [("POST", "/pair"), ("DELETE", "/pair/pending")]
    assert keyring_events == [
        ("set", "pending-device"),
        ("delete", "pending-device"),
    ]
    assert not credential_path.exists()


def test_ambiguous_begin_pair_cleanup_preserves_new_keyring_credential(
    monkeypatch,
    tmp_path,
):
    import httpx

    from services.api_client import (
        ApiPairingRecoveryRequired,
        MissionLegalApiClient,
    )

    passwords = {"old-device": "old-secret"}
    keyring_events = []
    credential_path = tmp_path / "Configuration" / "api-device.json"
    credential_path.parent.mkdir(parents=True)
    credential_path.write_text(
        '{"device_id": "old-device"}\n',
        encoding="utf-8",
    )

    def handler(request):
        if request.method == "POST" and request.url.path == "/pair":
            return httpx.Response(
                201,
                json={"device_id": "new-device", "credential": "new-secret"},
            )
        if request.method == "DELETE" and request.url.path == "/pair/pending":
            raise httpx.ReadError("response lost", request=request)
        return httpx.Response(404)

    class FakeKeyring:
        @staticmethod
        def set_password(_service, device_id, credential):
            passwords[device_id] = credential
            keyring_events.append(("set", device_id))

        @staticmethod
        def get_password(_service, device_id):
            return passwords.get(device_id)

        @staticmethod
        def delete_password(_service, device_id):
            passwords.pop(device_id, None)
            keyring_events.append(("delete", device_id))

    client = MissionLegalApiClient(
        "https://new-main-computer:8765",
        credential_path=credential_path,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_keyring", lambda: FakeKeyring)
    monkeypatch.setattr(
        client,
        "_write_device_pointer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk busy")),
    )

    with pytest.raises(ApiPairingRecoveryRequired) as raised:
        client.begin_pair("123456", "Front office")

    assert raised.value.device_id == "new-device"
    assert passwords == {
        "old-device": "old-secret",
        "new-device": "new-secret",
    }
    assert keyring_events == [("set", "new-device")]
    assert json.loads(credential_path.read_text(encoding="utf-8")) == {
        "device_id": "old-device"
    }


def test_certificate_replace_failure_cancels_pairing_and_restores_prior_ca(
    monkeypatch,
    tmp_path,
    isolated_qsettings,
):
    _ = isolated_qsettings
    source_certificate = tmp_path / "new.pem"
    source_certificate.write_text(
        "-----BEGIN CERTIFICATE-----\nNEW CA\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    client_root = tmp_path / "client-data"
    configuration = client_root / "Configuration"
    configuration.mkdir(parents=True)
    saved_certificate = configuration / "mission-legal-ca.pem"
    saved_certificate.write_text(
        "-----BEGIN CERTIFICATE-----\nOLD CA\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    observed = {"cancelled": 0}

    class FakeClient:
        def __init__(self, _base_url, *, certificate):
            self.certificate = certificate

        def health(self):
            return {"api_version": "1", "schema_version": 7}

        def validate_compatibility(self, _payload):
            return True

        def begin_pair(self, _code, _name, *, before_local_persist=None):
            if before_local_persist is not None:
                before_local_persist("pending-device")
            return {"device_id": "pending-device"}

        def confirm_pairing(self):
            return {"device_id": "pending-device"}

        def cancel_pairing(self):
            observed["cancelled"] += 1

    original_replace = pairing.os.replace

    def fail_staged_replace(path, target):
        path = Path(path)
        target = Path(target)
        if path.name.endswith(".pairing") and target.name == "mission-legal-ca.pem":
            raise OSError("certificate replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(pairing, "MissionLegalApiClient", FakeClient)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)
    monkeypatch.setattr(pairing.os, "replace", fail_staged_replace)

    with pytest.raises(OSError, match="certificate replace failed"):
        pairing.pair_client(
            "https://main-computer:8765",
            source_certificate,
            "123456",
            "Front office",
        )

    assert observed["cancelled"] == 1
    assert "OLD CA" in saved_certificate.read_text(encoding="utf-8")
    assert not list(configuration.glob("*.rollback"))


def test_cancelled_repairing_restores_previous_device_pointer(monkeypatch, tmp_path):
    import json
    import httpx

    from services.api_client import MissionLegalApiClient

    credential_path = tmp_path / "Configuration" / "api-device.json"
    credential_path.parent.mkdir(parents=True)
    credential_path.write_text(
        json.dumps({"device_id": "working-device"}),
        encoding="utf-8",
    )
    passwords = {"working-device": "working-secret"}

    def handler(request):
        if request.method == "POST" and request.url.path == "/pair":
            return httpx.Response(
                201,
                json={"device_id": "pending-device", "credential": "pending-secret"},
            )
        if request.method == "DELETE" and request.url.path == "/pair/pending":
            return httpx.Response(200, json={"removed": True})
        return httpx.Response(404)

    class FakeKeyring:
        @staticmethod
        def set_password(_service, device_id, credential):
            passwords[device_id] = credential

        @staticmethod
        def get_password(_service, device_id):
            return passwords.get(device_id)

        @staticmethod
        def delete_password(_service, device_id):
            passwords.pop(device_id, None)

    client = MissionLegalApiClient(
        "https://new-main-computer:8765",
        credential_path=credential_path,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_keyring", lambda: FakeKeyring)

    client.begin_pair("123456", "Front office")
    assert json.loads(credential_path.read_text(encoding="utf-8")) == {
        "device_id": "pending-device"
    }

    client.cancel_pairing()

    assert json.loads(credential_path.read_text(encoding="utf-8")) == {
        "device_id": "working-device"
    }
    assert passwords == {"working-device": "working-secret"}


def test_lost_confirm_response_is_reconciled_with_authenticated_session(
    monkeypatch,
    tmp_path,
):
    import httpx

    from services.api_client import MissionLegalApiClient

    credential_path = tmp_path / "api-device.json"
    passwords = {}
    confirm_calls = 0

    def handler(request):
        nonlocal confirm_calls
        if request.method == "POST" and request.url.path == "/pair":
            return httpx.Response(
                201,
                json={"device_id": "new-device", "credential": "secret"},
            )
        if request.method == "POST" and request.url.path == "/pair/confirm":
            confirm_calls += 1
            raise httpx.ReadError("response was lost", request=request)
        if request.method == "GET" and request.url.path == "/v1/session":
            return httpx.Response(
                200,
                json={"device": {"device_id": "new-device", "device_name": "Front"}},
            )
        return httpx.Response(404)

    class FakeKeyring:
        @staticmethod
        def set_password(_service, device_id, credential):
            passwords[device_id] = credential

        @staticmethod
        def get_password(_service, device_id):
            return passwords.get(device_id)

        @staticmethod
        def delete_password(_service, device_id):
            passwords.pop(device_id, None)

    client = MissionLegalApiClient(
        "https://main-computer:8765",
        credential_path=credential_path,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_keyring", lambda: FakeKeyring)

    client.begin_pair("123456", "Front")
    confirmed = client.confirm_pairing()

    assert confirm_calls == 1
    assert confirmed == {"device_id": "new-device"}
    assert credential_path.exists()
    assert passwords == {"new-device": "secret"}


def test_api_journal_callback_runs_before_credential_or_pointer_changes(
    monkeypatch,
    tmp_path,
):
    import httpx

    from services.api_client import MissionLegalApiClient

    credential_path = tmp_path / "Configuration" / "api-device.json"
    credential_path.parent.mkdir(parents=True)
    previous = b'{"device_id": "working-device"}\n'
    credential_path.write_bytes(previous)
    events = []
    passwords = {"working-device": "old-secret"}

    def handler(request):
        if request.method == "POST" and request.url.path == "/pair":
            return httpx.Response(
                201,
                json={"device_id": "new-device", "credential": "new-secret"},
            )
        return httpx.Response(404)

    class FakeKeyring:
        @staticmethod
        def set_password(_service, device_id, credential):
            events.append(("credential", device_id))
            passwords[device_id] = credential

        @staticmethod
        def get_password(_service, device_id):
            return passwords.get(device_id)

        @staticmethod
        def delete_password(_service, device_id):
            passwords.pop(device_id, None)

    client = MissionLegalApiClient(
        "https://new-main-computer:8765",
        credential_path=credential_path,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_keyring", lambda: FakeKeyring)

    def persist_journal(device_id):
        events.append(("journal", device_id))
        assert credential_path.read_bytes() == previous
        assert "new-device" not in passwords

    client.begin_pair(
        "123456",
        "Front office",
        before_local_persist=persist_journal,
    )

    assert events == [("journal", "new-device"), ("credential", "new-device")]
    assert json.loads(credential_path.read_text(encoding="utf-8")) == {
        "device_id": "new-device"
    }


def test_confirmed_recovery_finishes_locally_without_network_or_keyring(
    monkeypatch,
    tmp_path,
):
    client_root = tmp_path / "client-data"
    configuration = client_root / "Configuration"
    configuration.mkdir(parents=True)
    old_ca = "-----BEGIN CERTIFICATE-----\nOLD CA\n-----END CERTIFICATE-----\n"
    new_ca = "-----BEGIN CERTIFICATE-----\nNEW CA\n-----END CERTIFICATE-----\n"
    transaction_id = str(uuid.uuid4())
    staged_name = f".mission-legal-ca.pem.{transaction_id}.pairing"
    backup_name = f".mission-legal-ca.pem.{transaction_id}.rollback"
    saved = configuration / "mission-legal-ca.pem"
    saved.write_text(new_ca, encoding="utf-8", newline="")
    (configuration / backup_name).write_text(
        old_ca,
        encoding="utf-8",
        newline="",
    )
    previous_pointer = b'{"device_id": "old-device"}\n'
    (configuration / "api-device.json").write_text(
        '{"device_id": "new-device"}\n',
        encoding="utf-8",
    )
    journal = _recovery_journal(
        transaction_id=transaction_id,
        phase="confirmed",
        new_device_id="new-device",
        previous_pointer=previous_pointer,
        old_certificate=old_ca,
        new_certificate=new_ca,
        staged_name=staged_name,
        backup_name=backup_name,
    )
    journal_path = configuration / "pairing-transaction.json"
    pairing._write_journal(journal_path, journal)

    class PersistentSettings:
        NoError = 0
        values = {
            "server/url": "https://old-main-computer:8765",
            "server/ca_certificate": "old-ca.pem",
        }

        def __init__(self, *_args):
            pass

        def setValue(self, key, value):
            self.values[key] = value

        def contains(self, key):
            return key in self.values

        def value(self, key):
            return self.values.get(key)

        def remove(self, key):
            self.values.pop(key, None)

        def sync(self):
            pass

        def status(self):
            return self.NoError

    class NoNetworkClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("confirmed journal recovery must not use the network")

    monkeypatch.setattr(pairing, "QSettings", PersistentSettings)
    monkeypatch.setattr(pairing, "MissionLegalApiClient", NoNetworkClient)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    assert pairing.recover_interrupted_pairing() == "confirmed"
    assert not journal_path.exists()
    assert not (configuration / backup_name).exists()
    assert saved.read_text(encoding="utf-8") == new_ca
    assert json.loads(
        (configuration / "api-device.json").read_text(encoding="utf-8")
    ) == {"device_id": "new-device"}
    assert PersistentSettings.values == {
        "server/url": "https://new-main-computer:8765",
        "server/ca_certificate": str(saved.resolve()),
    }


def test_ambiguous_recovery_preserves_new_credential_pointer_and_journal(
    monkeypatch,
    tmp_path,
):
    client_root = tmp_path / "client-data"
    configuration = client_root / "Configuration"
    configuration.mkdir(parents=True)
    old_ca = "-----BEGIN CERTIFICATE-----\nOLD CA\n-----END CERTIFICATE-----\n"
    new_ca = "-----BEGIN CERTIFICATE-----\nNEW CA\n-----END CERTIFICATE-----\n"
    transaction_id = str(uuid.uuid4())
    staged_name = f".mission-legal-ca.pem.{transaction_id}.pairing"
    backup_name = f".mission-legal-ca.pem.{transaction_id}.rollback"
    saved = configuration / "mission-legal-ca.pem"
    staged = configuration / staged_name
    saved.write_text(old_ca, encoding="utf-8", newline="")
    staged.write_text(new_ca, encoding="utf-8", newline="")
    previous_pointer = b'{"device_id": "old-device"}\n'
    pointer = configuration / "api-device.json"
    pointer.write_text('{"device_id": "new-device"}\n', encoding="utf-8")
    journal = _recovery_journal(
        transaction_id=transaction_id,
        phase="registered",
        new_device_id="new-device",
        previous_pointer=previous_pointer,
        old_certificate=old_ca,
        new_certificate=new_ca,
        staged_name=staged_name,
        backup_name=backup_name,
    )
    journal_path = configuration / "pairing-transaction.json"
    pairing._write_journal(journal_path, journal)
    events = []

    class AmbiguousClient:
        def __init__(self, _url, *, certificate, credential_path):
            assert certificate is True
            assert Path(credential_path) == pointer
            self.certificate = certificate

        def pairing_credential_available(self, device_id):
            assert device_id == "new-device"
            return True

        def confirm_pairing(self):
            assert Path(self.certificate) == staged
            events.append("confirm")
            raise RuntimeError("network unavailable")

        def cancel_pairing(self):
            events.append("cancel")
            raise RuntimeError("network unavailable")

    monkeypatch.setattr(pairing, "MissionLegalApiClient", AmbiguousClient)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    with pytest.raises(pairing.ClientPairingRecoveryError, match="was preserved"):
        pairing.recover_interrupted_pairing()

    assert events == ["confirm", "cancel"]
    assert journal_path.exists()
    assert staged.exists()
    assert saved.read_text(encoding="utf-8") == old_ca
    assert json.loads(pointer.read_text(encoding="utf-8")) == {
        "device_id": "new-device"
    }


def test_rejected_recovery_restores_previous_public_state(monkeypatch, tmp_path):
    client_root = tmp_path / "client-data"
    configuration = client_root / "Configuration"
    configuration.mkdir(parents=True)
    old_ca = "-----BEGIN CERTIFICATE-----\nOLD CA\n-----END CERTIFICATE-----\n"
    new_ca = "-----BEGIN CERTIFICATE-----\nNEW CA\n-----END CERTIFICATE-----\n"
    transaction_id = str(uuid.uuid4())
    staged_name = f".mission-legal-ca.pem.{transaction_id}.pairing"
    backup_name = f".mission-legal-ca.pem.{transaction_id}.rollback"
    saved = configuration / "mission-legal-ca.pem"
    backup = configuration / backup_name
    saved.write_text(new_ca, encoding="utf-8", newline="")
    backup.write_text(old_ca, encoding="utf-8", newline="")
    previous_pointer = b'{"device_id": "old-device"}\n'
    pointer = configuration / "api-device.json"
    pointer.write_text('{"device_id": "new-device"}\n', encoding="utf-8")
    journal = _recovery_journal(
        transaction_id=transaction_id,
        phase="local-state-applied",
        new_device_id="new-device",
        previous_pointer=previous_pointer,
        old_certificate=old_ca,
        new_certificate=new_ca,
        staged_name=staged_name,
        backup_name=backup_name,
    )
    journal_path = configuration / "pairing-transaction.json"
    pairing._write_journal(journal_path, journal)

    class PersistentSettings:
        NoError = 0
        values = {
            "server/url": "https://new-main-computer:8765",
            "server/ca_certificate": str(saved),
        }

        def __init__(self, *_args):
            pass

        def setValue(self, key, value):
            self.values[key] = value

        def contains(self, key):
            return key in self.values

        def value(self, key):
            return self.values.get(key)

        def remove(self, key):
            self.values.pop(key, None)

        def sync(self):
            pass

        def status(self):
            return self.NoError

    class RejectedClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def pairing_credential_available(self, _device_id):
            return True

        def confirm_pairing(self):
            raise RuntimeError("registration rejected")

        def cancel_pairing(self):
            return "cancelled"

    monkeypatch.setattr(pairing, "QSettings", PersistentSettings)
    monkeypatch.setattr(pairing, "MissionLegalApiClient", RejectedClient)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    assert pairing.recover_interrupted_pairing() == "rolled-back"
    assert not journal_path.exists()
    assert pointer.read_bytes() == previous_pointer
    assert saved.read_text(encoding="utf-8") == old_ca
    assert PersistentSettings.values == {
        "server/url": "https://old-main-computer:8765",
        "server/ca_certificate": "old-ca.pem",
    }


def test_recovery_finishes_rollback_after_new_ca_and_credential_are_gone(
    monkeypatch,
    tmp_path,
):
    client_root = tmp_path / "client-data"
    configuration = client_root / "Configuration"
    configuration.mkdir(parents=True)
    old_ca = "-----BEGIN CERTIFICATE-----\nOLD CA\n-----END CERTIFICATE-----\n"
    new_ca = "-----BEGIN CERTIFICATE-----\nNEW CA\n-----END CERTIFICATE-----\n"
    transaction_id = str(uuid.uuid4())
    staged_name = f".mission-legal-ca.pem.{transaction_id}.pairing"
    backup_name = f".mission-legal-ca.pem.{transaction_id}.rollback"
    saved = configuration / "mission-legal-ca.pem"
    saved.write_text(old_ca, encoding="utf-8", newline="")
    previous_pointer = b'{"device_id": "old-device"}\n'
    pointer = configuration / "api-device.json"
    pointer.write_bytes(previous_pointer)
    journal = _recovery_journal(
        transaction_id=transaction_id,
        phase="local-state-applied",
        new_device_id="new-device",
        previous_pointer=previous_pointer,
        old_certificate=old_ca,
        new_certificate=new_ca,
        staged_name=staged_name,
        backup_name=backup_name,
    )
    journal_path = configuration / "pairing-transaction.json"
    pairing._write_journal(journal_path, journal)

    class PersistentSettings:
        NoError = 0
        values = {
            "server/url": "https://old-main-computer:8765",
            "server/ca_certificate": "old-ca.pem",
        }

        def __init__(self, *_args):
            pass

        def setValue(self, key, value):
            self.values[key] = value

        def contains(self, key):
            return key in self.values

        def value(self, key):
            return self.values.get(key)

        def remove(self, key):
            self.values.pop(key, None)

        def sync(self):
            pass

        def status(self):
            return self.NoError

    class NoCredentialClient:
        def __init__(self, _url, *, certificate, credential_path):
            assert certificate is True
            assert Path(credential_path) == pointer

        def pairing_credential_available(self, device_id):
            assert device_id == "new-device"
            return False

    monkeypatch.setattr(pairing, "QSettings", PersistentSettings)
    monkeypatch.setattr(pairing, "MissionLegalApiClient", NoCredentialClient)
    monkeypatch.setattr(pairing, "get_client_data_dir", lambda: client_root)

    assert pairing.recover_interrupted_pairing() == "rolled-back"
    assert not journal_path.exists()
    assert pointer.read_bytes() == previous_pointer
    assert saved.read_text(encoding="utf-8") == old_ca


def test_pair_client_rejects_a_certificate_file_containing_a_private_key(
    monkeypatch,
    tmp_path,
):
    unsafe = tmp_path / "server-bundle.pem"
    unsafe.write_text(
        "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
        "-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pairing,
        "get_client_data_dir",
        lambda: tmp_path / "client-data",
    )

    with pytest.raises(pairing.ClientPairingError, match="contains a private key"):
        pairing.pair_client(
            "https://main-computer:8765",
            unsafe,
            "123456",
            "Front office",
        )


def test_frozen_main_opens_first_run_pairing_dialog():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "ClientPairingDialog" in source
    assert "pairing_dialog.exec()" in source
    assert "pairing_dialog.update_scheduled" in source
    assert source.count("is client_update_scheduled") == 2
    assert '"Change connection"' in source
    assert source.index("recover_interrupted_pairing()") < source.index(
        "MissionLegalApiClient.from_environment()"
    )
    assert "Run MissionLegalClientSetup.exe" not in source


def test_first_run_dialog_exposes_pairing_inputs(qtbot):
    from ui.dialogs.client_pairing_dialog import ClientPairingDialog

    dialog = ClientPairingDialog(discovery_provider=lambda: ())
    qtbot.addWidget(dialog)
    assert "advanced recovery" in dialog.setup_code_edit.placeholderText().lower()
    assert dialog.server_edit.placeholderText().startswith("https://")
    assert dialog.code_edit.maxLength() == 6
    assert dialog.setup_code_edit.isHidden()
    assert dialog.server_edit.isHidden()
    assert dialog.certificate_edit.isHidden()
    assert dialog.server_combo.count() == 1
    assert dialog.device_edit.text()
    assert dialog.check_updates_button.text() == "Check for updates"
    assert dialog.check_updates_button.isEnabled()
    assert dialog.connect_button.isEnabled()


def test_pairing_worker_uses_automatic_setup_code(qapp, monkeypatch):
    from ui.dialogs import client_pairing_dialog as dialog_module

    observed = {}
    expected = object()

    def pair_from_setup(setup_code, *, device_name=None):
        observed.update(setup_code=setup_code, device_name=device_name)
        return expected

    monkeypatch.setattr(
        dialog_module,
        "pair_client_from_setup_code",
        pair_from_setup,
    )
    worker = dialog_module._ClientPairingWorker(
        {"setup_code": "MLPAIR1:payload", "device_name": "Front Office"}
    )
    results = []
    worker.succeeded.connect(results.append)

    worker.run()

    assert observed == {
        "setup_code": "MLPAIR1:payload",
        "device_name": "Front Office",
    }
    assert results == [expected]


def test_discovered_server_pairs_with_only_six_digit_code(
    qapp,
    qtbot,
    monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox
    from services.lan_discovery import DiscoveredServer
    from ui.dialogs import client_pairing_dialog as dialog_module

    observed = {}
    expected = object()

    def pair(**values):
        observed.update(values)
        return expected

    monkeypatch.setattr(dialog_module, "pair_client", pair)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    dialog = dialog_module.ClientPairingDialog(discovery_provider=lambda: ())
    qtbot.addWidget(dialog)
    discovered = DiscoveredServer(
        server_id="a" * 64,
        name="Secretary Laptop",
        server_url="https://192.168.108.50:8765",
        ca_certificate_pem=(
            "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
        ),
        ca_sha256="a" * 64,
    )
    dialog._discovery_pending_result = (discovered,)
    dialog._discovery_finished()
    dialog.code_edit.setText("123456")

    dialog._start_pairing()
    qtbot.waitUntil(lambda: dialog._thread is None, timeout=3000)

    assert observed == {
        "server_url": discovered.server_url,
        "certificate": discovered.ca_certificate_pem,
        "pairing_code": "123456",
        "device_name": dialog.device_edit.text(),
    }
    assert dialog.pairing_result is expected


def test_optional_update_check_remains_in_pairing_when_no_apply_is_scheduled(
    qapp,
    qtbot,
    monkeypatch,
):
    from PySide6.QtWidgets import QDialog
    from ui import update_coordinator
    from ui.dialogs.client_pairing_dialog import ClientPairingDialog

    dialog = ClientPairingDialog(discovery_provider=lambda: ())
    qtbot.addWidget(dialog)
    observed = []
    monkeypatch.setattr(
        update_coordinator,
        "offer_optional_client_update",
        lambda parent: observed.append(parent) or False,
    )

    dialog._check_for_updates()

    assert observed == [dialog]
    assert dialog.update_scheduled is False
    assert dialog.result() != QDialog.Accepted
    assert "continue pairing" in dialog.status_label.text().lower()
    assert dialog.connect_button.isEnabled()


def test_optional_update_check_closes_pairing_only_after_apply_is_scheduled(
    qapp,
    qtbot,
    monkeypatch,
):
    from PySide6.QtWidgets import QDialog
    from ui import update_coordinator
    from ui.dialogs.client_pairing_dialog import ClientPairingDialog

    dialog = ClientPairingDialog(discovery_provider=lambda: ())
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        update_coordinator,
        "offer_optional_client_update",
        lambda _parent: True,
    )

    dialog._check_for_updates()

    assert dialog.update_scheduled is True
    assert dialog.result() == QDialog.Accepted


def test_pairing_worker_preserves_typed_client_update_error(qapp, monkeypatch):
    from services.api_client import ApiCompatibilityError
    from ui.dialogs import client_pairing_dialog as dialog_module

    problem = ApiCompatibilityError(
        "Mission Legal 0.2.0 is required.",
        reason=ApiCompatibilityError.CLIENT_UPDATE_REQUIRED,
        required_client_version="0.2.0",
    )

    def fail_pairing(**_values):
        raise problem

    monkeypatch.setattr(dialog_module, "pair_client", fail_pairing)
    worker = dialog_module._ClientPairingWorker({})
    errors = []
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == [problem]


def test_pairing_thread_preserves_compatibility_error_for_required_update(
    qapp,
    qtbot,
    monkeypatch,
):
    from services.api_client import ApiCompatibilityError
    from ui import update_coordinator
    from ui.dialogs import client_pairing_dialog as dialog_module

    problem = ApiCompatibilityError(
        "Mission Legal 0.2.0 is required.",
        reason=ApiCompatibilityError.CLIENT_UPDATE_REQUIRED,
        required_client_version="0.2.0",
    )
    observed = []

    def fail_pairing(**_values):
        raise problem

    def defer_update(detail, parent, *, required_client_version=None):
        observed.append((detail, parent, required_client_version))
        return False

    monkeypatch.setattr(dialog_module, "pair_client", fail_pairing)
    monkeypatch.setattr(
        update_coordinator,
        "offer_required_client_update",
        defer_update,
    )
    dialog = dialog_module.ClientPairingDialog(discovery_provider=lambda: ())
    qtbot.addWidget(dialog)
    dialog._toggle_manual_setup()
    dialog.server_edit.setText("https://main-computer:8765")
    dialog.certificate_edit.setText("mission-legal-ca.pem")
    dialog.code_edit.setText("123456")

    dialog._start_pairing()
    qtbot.waitUntil(lambda: dialog._thread is None, timeout=3000)

    assert observed == [(str(problem), dialog, "0.2.0")]
    assert dialog.update_scheduled is False
    assert "still required" in dialog.status_label.text().lower()


def test_required_pairing_update_routes_to_updater_and_remains_when_deferred(
    qapp,
    qtbot,
    monkeypatch,
):
    from PySide6.QtWidgets import QDialog
    from services.api_client import ApiCompatibilityError
    from ui import update_coordinator
    from ui.dialogs.client_pairing_dialog import ClientPairingDialog

    problem = ApiCompatibilityError(
        "Mission Legal 0.2.0 is required.",
        reason=ApiCompatibilityError.CLIENT_UPDATE_REQUIRED,
        required_client_version="0.2.0",
    )
    observed = {}

    def defer_update(detail, parent, *, required_client_version=None):
        observed.update(
            detail=detail,
            parent=parent,
            required_client_version=required_client_version,
        )
        return False

    monkeypatch.setattr(
        update_coordinator,
        "offer_required_client_update",
        defer_update,
    )
    dialog = ClientPairingDialog(discovery_provider=lambda: ())
    qtbot.addWidget(dialog)
    dialog._pending_error = problem

    dialog._pairing_finished()

    assert observed == {
        "detail": str(problem),
        "parent": dialog,
        "required_client_version": "0.2.0",
    }
    assert dialog.update_scheduled is False
    assert dialog.result() != QDialog.Accepted
    assert "still required" in dialog.status_label.text().lower()


def test_required_pairing_update_closes_after_apply_is_scheduled(
    qapp,
    qtbot,
    monkeypatch,
):
    from PySide6.QtWidgets import QDialog
    from services.api_client import ApiCompatibilityError
    from ui import update_coordinator
    from ui.dialogs.client_pairing_dialog import ClientPairingDialog

    problem = ApiCompatibilityError(
        "Mission Legal 0.2.0 is required.",
        reason=ApiCompatibilityError.CLIENT_UPDATE_REQUIRED,
        required_client_version="0.2.0",
    )
    monkeypatch.setattr(
        update_coordinator,
        "offer_required_client_update",
        lambda *_args, **_kwargs: True,
    )
    dialog = ClientPairingDialog(discovery_provider=lambda: ())
    qtbot.addWidget(dialog)
    dialog._pending_error = problem

    dialog._pairing_finished()

    assert dialog.update_scheduled is True
    assert dialog.result() == QDialog.Accepted
