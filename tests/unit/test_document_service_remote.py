from pathlib import Path
from uuid import uuid4

import fitz
import pytest

from services import document_service as module
from services.api_client import (
    ApiUnavailableError,
    ApiUploadLookupResult,
    RemoteRecord,
)


def _write_pdf(path, text="document"):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    pdf.save(path)
    pdf.close()
    return path


@pytest.fixture
def tmp_path():
    path = Path("tmp_document_remote_tests") / uuid4().hex
    path.mkdir(parents=True)
    return path.resolve()


class FakeDocumentClient:
    def __init__(self):
        self.upload_data = None
        self.download_calls = []

    def get(self, path, **kwargs):
        if path.endswith("get_documents"):
            return {
                "items": [
                    {
                        "id": 3,
                        "missionary_id": 9,
                        "document_type": "PASSPORT",
                        "file_path": "C:/server/passport.pdf",
                    }
                ]
            }
        raise AssertionError(path)

    def download(self, path, destination):
        self.download_calls.append(path)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"document")
        return destination

    def upload(self, path, *, file_path, data):
        assert Path(file_path).is_file()
        assert data["missionary_id"] == "9"
        self.upload_data = data
        return {
            "id": 5,
            "missionary_id": 9,
            "document_type": data["document_type"],
            "file_path": "C:/server/new.pdf",
        }


def test_remote_document_listing_keeps_server_metadata_until_requested(monkeypatch):
    client = FakeDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )

    documents = module.DocumentService().get_documents(9)

    assert documents[0].file_path == "C:/server/passport.pdf"
    assert client.download_calls == []


def test_remote_document_is_revalidated_when_requested(monkeypatch, tmp_path):
    client = FakeDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    monkeypatch.setattr(module, "get_client_data_dir", lambda: tmp_path)
    service = module.DocumentService()
    document = service.get_documents(9)[0]

    cached = service.ensure_local_copy(document)
    assert cached.read_bytes() == b"document"
    assert cached.parent == tmp_path / "DocumentCache" / "9"
    assert service.ensure_local_copy(document) == cached
    assert client.download_calls == [
        "/v1/documents/3/content",
        "/v1/documents/3/content",
    ]


def test_remote_thumbnail_is_downloaded_without_full_document(monkeypatch, tmp_path):
    client = FakeDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    monkeypatch.setattr(module, "get_client_data_dir", lambda: tmp_path)
    service = module.DocumentService()
    document = service.get_documents(9)[0]

    cached = service.ensure_local_thumbnail(document)

    assert cached.parent == tmp_path / "DocumentCache" / "9" / "thumbnails"
    assert client.download_calls == ["/v1/documents/3/thumbnail"]


def test_remote_get_document_by_id_keeps_metadata_only(monkeypatch):
    class MetadataClient(FakeDocumentClient):
        def get(self, path, **kwargs):
            if path == "/v1/documents/3":
                return {
                    "id": 3,
                    "missionary_id": 9,
                    "document_type": "PASSPORT",
                    "file_name": "passport.pdf",
                    "file_path": "C:/server/passport.pdf",
                }
            return super().get(path, **kwargs)

    client = MetadataClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )

    document = module.DocumentService().get_document_by_id(3)

    assert document.file_path == "C:/server/passport.pdf"
    assert client.download_calls == []


def test_remote_upload_sends_file_without_downloading_response(monkeypatch, tmp_path):
    client = FakeDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    monkeypatch.setattr(module, "get_client_data_dir", lambda: tmp_path)
    source = tmp_path / "source.pdf"
    _write_pdf(source)
    missionary = type("Missionary", (), {"id": 9})()

    document = module.DocumentService().upload_document(
        missionary, source, "PASSPORT", "INTERPOL"
    )

    assert document.id == 5
    assert document.file_path == "C:/server/new.pdf"
    assert client.upload_data["upload_id"]
    assert len(client.upload_data["content_sha256"]) == 64
    assert int(client.upload_data["file_size"]) == source.stat().st_size


def test_remote_ocr_upload_serializes_multipart_json_fields(monkeypatch, tmp_path):
    client = FakeDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    source = _write_pdf(tmp_path / "ocr.pdf")
    missionary = type("Missionary", (), {"id": 9})()
    service = module.DocumentService()
    monkeypatch.setattr(service, "_materialize", lambda record: record)

    service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
        ocr_raw_data={"status": "success", "fields": ["passport_number"]},
        ocr_confirmed_data={"passport_number": "redacted"},
    )

    assert client.upload_data["ocr_raw_data"] == (
        '{"status": "success", "fields": ["passport_number"]}'
    )
    assert client.upload_data["ocr_confirmed_data"] == (
        '{"passport_number": "redacted"}'
    )


def test_remote_reconciliation_does_not_require_the_original_source(monkeypatch):
    upload_id = str(uuid4())
    digest = "a" * 64

    class LookupClient(FakeDocumentClient):
        def lookup_upload(self, candidate, *, expected):
            assert candidate == upload_id
            assert expected == {
                "upload_id": upload_id,
                "missionary_id": 9,
                "document_type": "CARNE_DE_EXTRANJERIA",
                "workflow_stage": "CARNET DE EXTRANJERIA",
                "content_sha256": digest,
                "file_size": 321,
                "supersedes_document_id": 87,
            }
            return ApiUploadLookupResult(
                status="committed",
                payload={"id": 55, **expected},
            )

    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: LookupClient()),
    )

    document = module.DocumentService().reconcile_upload(
        upload_id,
        missionary_id=9,
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        content_sha256=digest,
        file_size=321,
        supersedes_document_id=87,
    )

    assert document.id == 55
    assert document.content_sha256 == digest


@pytest.mark.parametrize(
    ("lookup_result", "expected_exception"),
    [
        (ApiUploadLookupResult(status="not_found"), None),
        (
            ApiUploadLookupResult(
                status="unavailable",
                detail="server offline",
            ),
            module.DocumentUploadOutcomeUnknownError,
        ),
    ],
)
def test_remote_reconciliation_distinguishes_absent_from_unavailable(
    monkeypatch,
    lookup_result,
    expected_exception,
):
    class LookupClient(FakeDocumentClient):
        def lookup_upload(self, *_args, **_kwargs):
            return lookup_result

    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: LookupClient()),
    )
    service = module.DocumentService()
    kwargs = {
        "missionary_id": 9,
        "document_type": "PASSPORT",
        "workflow_stage": "INTERPOL",
        "content_sha256": "b" * 64,
        "file_size": 123,
    }

    if expected_exception is None:
        assert service.reconcile_upload(str(uuid4()), **kwargs) is None
    else:
        with pytest.raises(expected_exception, match="server offline"):
            service.reconcile_upload(str(uuid4()), **kwargs)


def test_missing_remote_document_is_reported_as_server_unavailable(monkeypatch):
    class MissingDocumentClient(FakeDocumentClient):
        def download(self, path, destination):
            raise ApiUnavailableError("Client error '404 Not Found'")

    client = MissingDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    monkeypatch.setattr(module, "get_client_data_dir", lambda: Path("cache-root"))
    service = module.DocumentService()
    document = RemoteRecord(
        {
            "id": 3,
            "missionary_id": 9,
            "file_path": "C:/server/passport.pdf",
        }
    )

    with pytest.raises(module.DocumentFileUnavailableError):
        service.ensure_local_copy(document)


def test_structured_remote_storage_error_preserves_reason(monkeypatch):
    class CloudDocumentClient(FakeDocumentClient):
        def download(self, path, destination):
            raise ApiUnavailableError(
                "Service Unavailable", status_code=503, code="cloud_unavailable"
            )

    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: CloudDocumentClient()),
    )
    monkeypatch.setattr(module, "get_client_data_dir", lambda: Path("cache-root"))
    document = RemoteRecord(
        {"id": 3, "missionary_id": 9, "file_path": "C:/server/passport.pdf"}
    )

    with pytest.raises(module.DocumentFileUnavailableError) as raised:
        module.DocumentService().ensure_local_copy(document)

    assert raised.value.reason == "cloud_unavailable"
