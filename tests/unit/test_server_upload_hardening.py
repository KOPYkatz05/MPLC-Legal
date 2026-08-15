import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.models.document import Document
from server import app as module
from server.security import DeviceCredentialStore, PairingCodeStore
from version import APP_VERSION


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / f"mission-legal-server-upload-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _authenticated_client(tmp_path):
    devices = DeviceCredentialStore(tmp_path / "devices.json")
    credentials = devices.register("Upload test client")
    client = TestClient(
        module.create_app(
            devices,
            PairingCodeStore(tmp_path / "pairing.json"),
            manage_lifecycle=False,
        )
    )
    headers = {
        "X-Device-ID": credentials["device_id"],
        "X-Device-Credential": credentials["credential"],
        "X-Client-Version": APP_VERSION,
    }
    return client, headers


def _upload_data(upload_id, content):
    return {
        "missionary_id": "9",
        "document_type": "CARNE_DE_EXTRANJERIA",
        "workflow_stage": "CARNET DE EXTRANJERIA",
        "upload_id": upload_id,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "file_size": str(len(content)),
    }


def test_upload_verifies_stream_and_passes_integrity_metadata(
    tmp_path,
    monkeypatch,
):
    from services.document_service import DocumentService
    from services.missionary_service import MissionaryService

    content = b"carne scan bytes"
    upload_id = str(uuid.uuid4())
    captured = {}
    missionary = type(
        "Missionary",
        (),
        {"id": 9, "full_name": "Upload Example"},
    )()

    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        MissionaryService,
        "get_missionary",
        lambda _service, missionary_id: missionary
        if missionary_id == 9
        else None,
    )

    def fake_upload(
        _service,
        received_missionary,
        source_file,
        document_type,
        workflow_stage,
        **kwargs,
    ):
        captured.update(kwargs)
        captured["source_bytes"] = Path(source_file).read_bytes()
        assert received_missionary is missionary
        return Document(
            id=51,
            missionary_id=9,
            document_type=document_type,
            workflow_stage=workflow_stage,
            status="ACTIVE",
            file_name="carne.pdf",
            file_path="C:/documents/carne.pdf",
            upload_id=kwargs["upload_id"],
            content_sha256=kwargs["content_sha256"],
            file_size=kwargs["file_size"],
            post_processing_status="RETRY_REQUIRED",
            post_processing_error="RuntimeError: database unavailable",
        )

    monkeypatch.setattr(DocumentService, "upload_document", fake_upload)
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/upload",
        headers=headers,
        data=_upload_data(upload_id, content),
        files={"file": ("carne.pdf", content, "application/pdf")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["upload_id"] == upload_id
    assert response.json()["post_processing_status"] == "RETRY_REQUIRED"
    assert response.json()["post_processing_error"].startswith("RuntimeError:")
    assert captured["source_bytes"] == content
    assert captured["content_sha256"] == hashlib.sha256(content).hexdigest()
    assert captured["file_size"] == len(content)
    assert list((tmp_path / "Incoming").iterdir()) == []


def test_retry_post_processing_returns_committed_warning_state(
    tmp_path,
    monkeypatch,
):
    from services.document_service import DocumentService

    document = Document(
        id=52,
        missionary_id=9,
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        status="ACTIVE",
        file_name="carne.pdf",
        file_path="C:/documents/carne.pdf",
        post_processing_status="RETRY_REQUIRED",
        post_processing_error="RuntimeError: database unavailable",
    )
    monkeypatch.setattr(
        DocumentService,
        "get_document_by_id",
        lambda _service, document_id: document if document_id == 52 else None,
    )
    monkeypatch.setattr(
        DocumentService,
        "_run_post_processing_best_effort",
        lambda _service, candidate: candidate,
    )
    monkeypatch.setattr(
        DocumentService,
        "_verify_committed_upload_file",
        lambda _service, candidate: Path(candidate.file_path),
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/52/retry-post-processing",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == 52
    assert response.json()["post_processing_status"] == "RETRY_REQUIRED"


@pytest.mark.parametrize(
    ("overrides", "filename", "expected_status", "expected_code"),
    [
        (
            {"document_type": "NOT_A_DOCUMENT"},
            "scan.pdf",
            422,
            "invalid_document_type",
        ),
        (
            {"workflow_stage": "NOT_A_STAGE"},
            "scan.pdf",
            422,
            "invalid_workflow_stage",
        ),
        ({}, "scan.heic", 415, "unsupported_document_extension"),
        (
            {"content_sha256": "not-a-hash"},
            "scan.pdf",
            422,
            "invalid_content_sha256",
        ),
        (
            {"upload_id": "not-a-uuid"},
            "scan.pdf",
            422,
            "invalid_upload_id",
        ),
    ],
)
def test_upload_rejects_invalid_metadata_before_storage(
    tmp_path,
    monkeypatch,
    overrides,
    filename,
    expected_status,
    expected_code,
):
    from services.missionary_service import MissionaryService

    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        MissionaryService,
        "get_missionary",
        lambda *_args: pytest.fail("invalid uploads must not reach storage"),
    )
    content = b"scan"
    data = _upload_data(str(uuid.uuid4()), content)
    data.update(overrides)
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/upload",
        headers=headers,
        data=data,
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code


@pytest.mark.parametrize(
    ("missing_field", "expected_code"),
    [
        ("upload_id", "missing_upload_id"),
        ("content_sha256", "missing_content_sha256"),
        ("file_size", "missing_file_size"),
    ],
)
def test_api_v3_upload_requires_reconciliation_metadata(
    tmp_path,
    monkeypatch,
    missing_field,
    expected_code,
):
    from services.missionary_service import MissionaryService

    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        MissionaryService,
        "get_missionary",
        lambda *_args: pytest.fail("incomplete uploads must not reach storage"),
    )
    content = b"scan"
    data = _upload_data(str(uuid.uuid4()), content)
    data.pop(missing_field)
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/upload",
        headers=headers,
        data=data,
        files={"file": ("scan.pdf", content, "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == expected_code


@pytest.mark.parametrize(
    ("content", "overrides", "expected_status", "expected_code"),
    [
        (b"", {"file_size": "0"}, 422, "empty_upload"),
        (b"actual", {"file_size": "999"}, 422, "file_size_mismatch"),
        (b"actual", {"content_sha256": "0" * 64}, 422, "content_sha256_mismatch"),
    ],
)
def test_upload_rejects_empty_or_mismatched_content(
    tmp_path,
    monkeypatch,
    content,
    overrides,
    expected_status,
    expected_code,
):
    from services.document_service import DocumentService
    from services.missionary_service import MissionaryService

    missionary = type("Missionary", (), {"id": 9})()
    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        MissionaryService,
        "get_missionary",
        lambda _service, _missionary_id: missionary,
    )
    monkeypatch.setattr(
        DocumentService,
        "upload_document",
        lambda *_args, **_kwargs: pytest.fail(
            "invalid content must not reach document storage"
        ),
    )
    data = _upload_data(str(uuid.uuid4()), content)
    data.update(overrides)
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/upload",
        headers=headers,
        data=data,
        files={"file": ("scan.pdf", content, "application/pdf")},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert list((tmp_path / "Incoming").iterdir()) == []


def test_upload_enforces_server_size_limit_and_cleans_partial_file(
    tmp_path,
    monkeypatch,
):
    from services.missionary_service import MissionaryService

    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setenv("MISSION_LEGAL_MAX_UPLOAD_BYTES", "3")
    monkeypatch.setattr(
        MissionaryService,
        "get_missionary",
        lambda _service, _missionary_id: type("Missionary", (), {"id": 9})(),
    )
    content = b"four"
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/upload",
        headers=headers,
        data=_upload_data(str(uuid.uuid4()), content),
        files={"file": ("scan.pdf", content, "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "upload_too_large"
    assert list((tmp_path / "Incoming").iterdir()) == []


def test_upload_reports_stale_replacement_as_conflict(tmp_path, monkeypatch):
    from services.document_service import DocumentReplacementError, DocumentService
    from services.missionary_service import MissionaryService

    content = b"replacement scan"
    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        MissionaryService,
        "get_missionary",
        lambda _service, _missionary_id: type("Missionary", (), {"id": 9})(),
    )

    def reject_replacement(*_args, **_kwargs):
        raise DocumentReplacementError("replacement is no longer active")

    monkeypatch.setattr(DocumentService, "upload_document", reject_replacement)
    data = _upload_data(str(uuid.uuid4()), content)
    data["supersedes_document_id"] = "88"
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/upload",
        headers=headers,
        data=data,
        files={"file": ("scan.pdf", content, "application/pdf")},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "replacement_conflict"


def test_upload_reports_invalid_document_content_as_422(tmp_path, monkeypatch):
    from services.document_service import DocumentService
    from services.missionary_service import MissionaryService

    content = b"not actually a PDF"
    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        MissionaryService,
        "get_missionary",
        lambda _service, _missionary_id: type("Missionary", (), {"id": 9})(),
    )
    monkeypatch.setattr(
        DocumentService,
        "upload_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("The file cannot be read as a valid PDF or image.")
        ),
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/upload",
        headers=headers,
        data=_upload_data(str(uuid.uuid4()), content),
        files={"file": ("scan.pdf", content, "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_document_file",
        "message": "The file cannot be read as a valid PDF or image.",
    }


def test_upload_lookup_is_authoritative_and_distinguishes_not_found(
    tmp_path,
    monkeypatch,
):
    from services.document_service import DocumentService
    from services import document_storage_service

    existing_id = str(uuid.uuid4())
    missing_id = str(uuid.uuid4())
    stored_path = tmp_path / "passport.pdf"
    stored_path.write_bytes(b"stored passport")
    stored_sha256 = hashlib.sha256(stored_path.read_bytes()).hexdigest()

    def lookup(_service, upload_id):
        if upload_id != existing_id:
            return None
        return Document(
            id=61,
            missionary_id=9,
            document_type="PASSPORT",
            workflow_stage="INTERPOL",
            status="ACTIVE",
            file_name="passport.pdf",
            file_path="C:/documents/passport.pdf",
            upload_id=existing_id,
            content_sha256=stored_sha256,
            file_size=stored_path.stat().st_size,
        )

    monkeypatch.setattr(DocumentService, "get_document_by_upload_id", lookup)
    monkeypatch.setattr(
        document_storage_service,
        "resolve_document_path",
        lambda document_id: stored_path
        if document_id == 61
        else pytest.fail("unexpected document lookup"),
    )
    client, headers = _authenticated_client(tmp_path)

    found = client.get(f"/v1/document-uploads/{existing_id}", headers=headers)
    missing = client.get(f"/v1/document-uploads/{missing_id}", headers=headers)

    assert found.status_code == 200
    assert found.json()["upload_id"] == existing_id
    assert found.json()["file_path"] == str(stored_path)
    assert missing.status_code == 404
    assert missing.json()["detail"] == {
        "code": "upload_not_found",
        "upload_id": missing_id,
    }


def test_upload_lookup_repairs_pending_post_processing(
    tmp_path,
    monkeypatch,
):
    from services.document_service import DocumentService
    from services import document_storage_service

    upload_id = str(uuid.uuid4())
    stored_path = tmp_path / "carne.pdf"
    stored_path.write_bytes(b"stored carne")
    document = Document(
        id=64,
        missionary_id=9,
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        status="ACTIVE",
        file_name="carne.pdf",
        file_path=str(stored_path),
        upload_id=upload_id,
        content_sha256=hashlib.sha256(stored_path.read_bytes()).hexdigest(),
        file_size=stored_path.stat().st_size,
        post_processing_status="PENDING",
    )
    calls = []
    monkeypatch.setattr(
        DocumentService,
        "get_document_by_upload_id",
        lambda _service, _upload_id: document,
    )

    def finish(_service, candidate):
        calls.append(candidate.id)
        candidate.post_processing_status = "COMPLETE"
        candidate.post_processing_updated_fields = "[]"
        return candidate

    monkeypatch.setattr(
        DocumentService,
        "_run_post_processing_best_effort",
        finish,
    )
    monkeypatch.setattr(
        document_storage_service,
        "resolve_document_path",
        lambda _document_id: stored_path,
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.get(f"/v1/document-uploads/{upload_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["post_processing_status"] == "COMPLETE"
    assert calls == [64]


def test_upload_lookup_does_not_hide_database_failure(tmp_path, monkeypatch):
    from services.document_service import DocumentService

    monkeypatch.setattr(
        DocumentService,
        "get_document_by_upload_id",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("database offline")),
    )
    devices = DeviceCredentialStore(tmp_path / "devices.json")
    credentials = devices.register("Upload test client")
    client = TestClient(
        module.create_app(
            devices,
            PairingCodeStore(tmp_path / "pairing.json"),
            manage_lifecycle=False,
        ),
        raise_server_exceptions=False,
    )
    headers = {
        "X-Device-ID": credentials["device_id"],
        "X-Device-Credential": credentials["credential"],
        "X-Client-Version": APP_VERSION,
    }

    response = client.get(
        f"/v1/document-uploads/{uuid.uuid4()}",
        headers=headers,
    )

    assert response.status_code == 500


def test_upload_lookup_propagates_document_storage_failure(tmp_path, monkeypatch):
    from services.document_service import DocumentService
    from services import document_storage_service

    upload_id = str(uuid.uuid4())
    document = Document(
        id=62,
        missionary_id=9,
        document_type="PASSPORT",
        workflow_stage="INTERPOL",
        status="ACTIVE",
        file_name="passport.pdf",
        file_path="C:/documents/missing-passport.pdf",
        upload_id=upload_id,
        content_sha256="a" * 64,
        file_size=123,
    )
    monkeypatch.setattr(
        DocumentService,
        "get_document_by_upload_id",
        lambda _service, _upload_id: document,
    )

    def unavailable(document_id):
        raise document_storage_service.DocumentStorageError(
            document_storage_service.MISSING,
            document_id,
        )

    monkeypatch.setattr(
        document_storage_service,
        "resolve_document_path",
        unavailable,
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.get(f"/v1/document-uploads/{upload_id}", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "missing",
        "document_id": 62,
    }


def test_upload_lookup_rejects_corrupted_committed_bytes(tmp_path, monkeypatch):
    from services.document_service import DocumentService
    from services import document_storage_service

    upload_id = str(uuid.uuid4())
    stored_path = tmp_path / "carne.pdf"
    stored_path.write_bytes(b"corrupted after commit")
    document = Document(
        id=63,
        missionary_id=9,
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        status="ACTIVE",
        file_name="carne.pdf",
        file_path=str(stored_path),
        upload_id=upload_id,
        content_sha256="a" * 64,
        file_size=stored_path.stat().st_size,
        post_processing_status="PENDING",
    )
    monkeypatch.setattr(
        DocumentService,
        "get_document_by_upload_id",
        lambda _service, _upload_id: document,
    )
    monkeypatch.setattr(
        document_storage_service,
        "resolve_document_path",
        lambda _document_id: stored_path,
    )
    monkeypatch.setattr(
        DocumentService,
        "_run_post_processing_best_effort",
        lambda *_args: pytest.fail(
            "post-processing must not run before integrity verification"
        ),
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.get(f"/v1/document-uploads/{upload_id}", headers=headers)

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "unreadable",
        "document_id": 63,
    }


def test_explicit_post_processing_retry_rejects_corrupt_file(
    tmp_path,
    monkeypatch,
):
    from services.document_service import DocumentService
    from services import document_service as document_service_module

    stored_path = tmp_path / "corrupt-carne.pdf"
    stored_path.write_bytes(b"corrupt committed bytes")
    document = Document(
        id=65,
        missionary_id=9,
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        status="ACTIVE",
        file_name="carne.pdf",
        file_path=str(stored_path),
        content_sha256="a" * 64,
        file_size=stored_path.stat().st_size,
        post_processing_status="RETRY_REQUIRED",
    )
    monkeypatch.setattr(
        DocumentService,
        "get_document_by_id",
        lambda _service, document_id: document if document_id == 65 else None,
    )
    monkeypatch.setattr(
        DocumentService,
        "_run_post_processing_best_effort",
        lambda *_args: pytest.fail(
            "corrupt committed bytes must not be post-processed"
        ),
    )
    monkeypatch.setattr(
        document_service_module,
        "verify_readable",
        lambda _path: None,
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/65/retry-post-processing",
        headers=headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "unreadable",
        "document_id": 65,
    }


def test_apply_updates_rejects_request_type_that_disagrees_with_stored_document(
    tmp_path,
    monkeypatch,
):
    from services.document_service import DocumentService
    from services import upload_pipeline

    document = Document(
        id=71,
        missionary_id=9,
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        status="ACTIVE",
        file_name="carne.pdf",
        file_path="C:/documents/carne.pdf",
    )
    monkeypatch.setattr(
        DocumentService,
        "get_document_by_id",
        lambda _service, _document_id: document,
    )
    monkeypatch.setattr(
        upload_pipeline,
        "apply_missionary_updates",
        lambda *_args, **_kwargs: pytest.fail(
            "mismatched request type must not update a missionary"
        ),
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/71/apply-updates",
        headers=headers,
        json={
            "document_type": "PASSPORT",
            "confirmed_data": {"carnet_number": "123"},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_type_mismatch"


def test_apply_updates_uses_authoritative_stored_document_type(
    tmp_path,
    monkeypatch,
):
    from services.document_service import DocumentService
    from services import upload_pipeline

    document = Document(
        id=72,
        missionary_id=9,
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        status="ACTIVE",
        file_name="carne.pdf",
        file_path="C:/documents/carne.pdf",
    )
    calls = []
    monkeypatch.setattr(
        DocumentService,
        "get_document_by_id",
        lambda _service, _document_id: document,
    )

    def apply_updates(missionary_id, document_type, document_id, data, **kwargs):
        calls.append((missionary_id, document_type, document_id, data, kwargs))
        return ["carnet_number"]

    monkeypatch.setattr(
        upload_pipeline,
        "apply_missionary_updates",
        apply_updates,
    )
    client, headers = _authenticated_client(tmp_path)

    response = client.post(
        "/v1/documents/72/apply-updates",
        headers=headers,
        json={
            "document_type": "CARNE_DE_EXTRANJERIA",
            "confirmed_data": {"carnet_number": "123"},
            "auto_update_fields": ["carnet_number", "passport_number"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"updated_fields": ["carnet_number"]}
    assert calls[0][0:4] == (
        9,
        "CARNE_DE_EXTRANJERIA",
        72,
        {"carnet_number": "123"},
    )
