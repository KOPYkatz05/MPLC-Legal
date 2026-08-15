import threading
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from datetime import date

from services.api_client import (
    ApiUnavailableError,
    ApiUploadConflictError,
    ApiUploadOutcomeUnknownError,
    MissionLegalApiClient,
    RemoteRecord,
)
from services.remote_service import RemoteServiceMixin


def test_remote_record_decodes_birthdate_as_date():
    record = RemoteRecord({"date_of_birth": "2001-02-03"})

    assert record.date_of_birth == date(2001, 2, 3)


@pytest.fixture(autouse=True)
def reset_environment_client():
    MissionLegalApiClient.close_environment_client()
    yield
    MissionLegalApiClient.close_environment_client()


def test_instance_reuses_mock_transport_client_until_closed():
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"status": "ok"})

    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(handler),
    )

    assert client.health() == {"status": "ok"}
    transport_owner = client._http_client
    assert client.health() == {"status": "ok"}

    assert requests == ["/health", "/health"]
    assert client._http_client is transport_owner
    assert transport_owner.is_closed is False

    client.close()

    assert client.closed is True
    assert transport_owner.is_closed is True
    with pytest.raises(RuntimeError, match="closed"):
        client.health()


def test_download_404_does_not_mark_the_server_unavailable(monkeypatch):
    destination = Path("test-download-404-document.pdf")
    destination.unlink(missing_ok=True)
    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    )
    unavailable_reports = []
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr(
        client,
        "_report_unavailable",
        lambda detail: unavailable_reports.append(detail),
    )

    with pytest.raises(ApiUnavailableError, match="404 Not Found"):
        client.download("/v1/documents/882/content", destination)

    assert unavailable_reports == []
    assert not destination.exists()


def test_download_preserves_structured_storage_error(monkeypatch):
    destination = Path("test-download-cloud-document.pdf")
    destination.unlink(missing_ok=True)
    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                503, json={"detail": {"code": "cloud_unavailable"}}
            )
        ),
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    unavailable_reports = []
    monkeypatch.setattr(
        client, "_report_unavailable", lambda detail: unavailable_reports.append(detail)
    )

    with pytest.raises(ApiUnavailableError) as raised:
        client.download("/v1/documents/882/content", destination)

    assert raised.value.status_code == 503
    assert raised.value.code == "cloud_unavailable"
    assert unavailable_reports == []


def test_close_defers_transport_shutdown_until_concurrent_calls_finish():
    both_started = threading.Event()
    release = threading.Event()
    state_lock = threading.Lock()
    active_handlers = 0

    def handler(_request):
        nonlocal active_handlers
        with state_lock:
            active_handlers += 1
            if active_handlers == 2:
                both_started.set()
        assert release.wait(timeout=3)
        return httpx.Response(200, json={"status": "ok"})

    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(handler),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        calls = [executor.submit(client.health) for _index in range(2)]
        assert both_started.wait(timeout=3)
        transport_owner = client._http_client

        client.close()

        assert client.closed is True
        assert transport_owner.is_closed is False
        release.set()
        assert [call.result(timeout=3) for call in calls] == [
            {"status": "ok"},
            {"status": "ok"},
        ]

    assert transport_owner.is_closed is True
    assert client._http_client is None


def test_remote_service_calls_share_environment_connection_and_retarget_on_change(
    monkeypatch,
):
    built_clients = []
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"result": "pong"})

    transport = httpx.MockTransport(handler)

    def build_client(client):
        built = httpx.Client(
            base_url=client.base_url,
            transport=transport,
            timeout=client.timeout,
        )
        built_clients.append(built)
        return built

    class PingService(RemoteServiceMixin):
        REMOTE_SERVICE = "ping"
        REMOTE_METHODS = frozenset({"ping"})

        def ping(self):
            raise AssertionError("Remote dispatch was not used")

    monkeypatch.delenv("MISSION_LEGAL_SERVER_PROCESS", raising=False)
    monkeypatch.delenv("MISSION_LEGAL_API_CERT", raising=False)
    monkeypatch.setenv("MISSION_LEGAL_API_URL", "https://first-server.test")
    monkeypatch.setattr(MissionLegalApiClient, "_build_client", build_client)
    monkeypatch.setattr(MissionLegalApiClient, "_headers", lambda _client: {})

    service = PingService()
    assert service.ping() == "pong"
    first_owner = MissionLegalApiClient.from_environment()
    assert service.ping() == "pong"

    assert MissionLegalApiClient.from_environment() is first_owner
    assert len(built_clients) == 1
    assert built_clients[0].is_closed is False

    monkeypatch.setenv("MISSION_LEGAL_API_URL", "https://second-server.test")
    second_owner = MissionLegalApiClient.from_environment()

    assert second_owner is first_owner
    assert first_owner.closed is False
    assert first_owner.base_url == "https://second-server.test"
    assert built_clients[0].is_closed is True
    assert second_owner.health() == {"status": "ok"}
    assert len(built_clients) == 2

    MissionLegalApiClient.close_environment_client()

    assert second_owner.closed is True
    assert built_clients[1].is_closed is True
    assert requests == ["/v1/rpc/ping/ping", "/v1/rpc/ping/ping", "/health"]


def _upload_source():
    path = Path(f"test-api-upload-{uuid.uuid4().hex}.pdf").resolve()
    path.write_bytes(b"durable upload payload")
    return path


def _upload_payload(upload_id, *, content_sha256, file_size):
    return {
        "id": 41,
        "upload_id": upload_id,
        "missionary_id": 9,
        "document_type": "PASSPORT",
        "workflow_stage": "INTERPOL",
        "content_sha256": content_sha256,
        "file_size": file_size,
        "supersedes_document_id": None,
    }


def test_upload_sends_integrity_metadata_with_a_longer_timeout(monkeypatch):
    source = _upload_source()
    upload_id = str(uuid.uuid4())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            201,
            json=_upload_payload(
                upload_id,
                content_sha256=digest,
                file_size=source.stat().st_size,
            ),
        )

    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(handler),
        timeout=7.0,
        upload_timeout=73.0,
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    try:
        result = client.upload(
            "/v1/documents/upload",
            file_path=source,
            data={
                "missionary_id": "9",
                "document_type": "PASSPORT",
                "workflow_stage": "INTERPOL",
            },
            upload_id=upload_id,
        )
    finally:
        client.close()
        source.unlink(missing_ok=True)

    body = requests[0].content
    assert result["id"] == 41
    assert upload_id.encode() in body
    assert digest.encode() in body
    assert str(len(b"durable upload payload")).encode() in body
    assert requests[0].extensions["timeout"]["read"] == 73.0
    assert requests[0].extensions["timeout"]["connect"] == 7.0


def test_upload_timeout_reconciles_the_committed_upload(monkeypatch):
    source = _upload_source()
    upload_id = str(uuid.uuid4())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(
            200,
            json=_upload_payload(
                upload_id,
                content_sha256=digest,
                file_size=source.stat().st_size,
            ),
        )

    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr(client, "_report_unavailable", lambda _detail: None)
    monkeypatch.setattr(client, "UPLOAD_RECONCILIATION_DELAYS", (0.0,))
    try:
        result = client.upload(
            "/v1/documents/upload",
            file_path=source,
            data={
                "missionary_id": "9",
                "document_type": "PASSPORT",
                "workflow_stage": "INTERPOL",
            },
            upload_id=upload_id,
        )
    finally:
        client.close()
        source.unlink(missing_ok=True)

    assert result["upload_id"] == upload_id
    assert calls == [
        ("POST", "/v1/documents/upload"),
        ("GET", f"/v1/document-uploads/{upload_id}"),
    ]


def test_authoritative_upload_lookup_distinguishes_absent_from_unavailable(
    monkeypatch,
):
    upload_id = str(uuid.uuid4())
    responses = iter(
        (
            httpx.Response(
                404,
                json={
                    "detail": {
                        "code": "upload_not_found",
                        "upload_id": upload_id,
                    }
                },
            ),
            httpx.Response(404, json={"detail": "Not Found"}),
        )
    )
    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(lambda _request: next(responses)),
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr(client, "UPLOAD_RECONCILIATION_DELAYS", (0.0,))
    try:
        absent = client.lookup_upload(upload_id)
        unavailable = client.lookup_upload(upload_id)
    finally:
        client.close()

    assert absent.not_found
    assert absent.payload is None
    assert unavailable.unavailable
    assert not unavailable.not_found


def test_authoritative_upload_lookup_rejects_different_immutable_metadata(
    monkeypatch,
):
    upload_id = str(uuid.uuid4())
    payload = _upload_payload(
        upload_id,
        content_sha256="0" * 64,
        file_size=99,
    )
    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        ),
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr(client, "UPLOAD_RECONCILIATION_DELAYS", (0.0,))
    try:
        with pytest.raises(ApiUploadConflictError, match="different file_size"):
            client.lookup_upload(
                upload_id,
                expected={
                    "missionary_id": 9,
                    "document_type": "PASSPORT",
                    "workflow_stage": "INTERPOL",
                    "content_sha256": "0" * 64,
                    "file_size": 100,
                    "supersedes_document_id": None,
                },
            )
    finally:
        client.close()


def test_upload_timeout_rejects_mismatched_reconciliation(monkeypatch):
    source = _upload_source()
    upload_id = str(uuid.uuid4())

    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(
            200,
            json=_upload_payload(
                upload_id,
                content_sha256="0" * 64,
                file_size=source.stat().st_size,
            ),
        )

    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr(client, "_report_unavailable", lambda _detail: None)
    monkeypatch.setattr(client, "UPLOAD_RECONCILIATION_DELAYS", (0.0,))
    try:
        with pytest.raises(ApiUploadOutcomeUnknownError) as raised:
            client.upload(
                "/v1/documents/upload",
                file_path=source,
                data={
                    "missionary_id": "9",
                    "document_type": "PASSPORT",
                    "workflow_stage": "INTERPOL",
                },
                upload_id=upload_id,
            )
    finally:
        client.close()
        source.unlink(missing_ok=True)

    assert raised.value.upload_id == upload_id
    assert "different content_sha256" in str(raised.value)


def test_upload_with_truncated_success_response_reconciles_by_upload_id(
    monkeypatch,
):
    source = _upload_source()
    upload_id = str(uuid.uuid4())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(
                201,
                content=b'{"id": 41,',
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            200,
            json=_upload_payload(
                upload_id,
                content_sha256=digest,
                file_size=source.stat().st_size,
            ),
        )

    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr(client, "UPLOAD_RECONCILIATION_DELAYS", (0.0,))
    try:
        result = client.upload(
            "/v1/documents/upload",
            file_path=source,
            data={
                "missionary_id": "9",
                "document_type": "PASSPORT",
                "workflow_stage": "INTERPOL",
            },
            upload_id=upload_id,
        )
    finally:
        client.close()
        source.unlink(missing_ok=True)

    assert result["upload_id"] == upload_id
    assert calls == [
        ("POST", "/v1/documents/upload"),
        ("GET", f"/v1/document-uploads/{upload_id}"),
    ]


def test_successful_legacy_upload_response_is_not_treated_as_durable(
    monkeypatch,
):
    source = _upload_source()
    client = MissionLegalApiClient(
        "https://mission-server.test",
        credential_path="unused-device.json",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                201,
                json={
                    "id": 8,
                    "missionary_id": 9,
                    "document_type": "PASSPORT",
                    "workflow_stage": "INTERPOL",
                },
            )
        ),
    )
    monkeypatch.setattr(client, "_headers", lambda: {})
    try:
        with pytest.raises(ApiUploadOutcomeUnknownError) as raised:
            client.upload(
                "/v1/documents/upload",
                file_path=source,
                data={
                    "missionary_id": "9",
                    "document_type": "PASSPORT",
                    "workflow_stage": "INTERPOL",
                },
            )
    finally:
        client.close()
        source.unlink(missing_ok=True)

    assert raised.value.upload_id
    assert "unknown outcome" in str(raised.value)
