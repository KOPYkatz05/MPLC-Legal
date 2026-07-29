from pathlib import Path

import pytest

from services import document_service as module
from services.api_client import ApiUnavailableError, RemoteRecord


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


def test_remote_document_is_downloaded_once_when_requested(monkeypatch, tmp_path):
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
    assert client.download_calls == ["/v1/documents/3/content"]


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
    source.write_bytes(b"upload")
    missionary = type("Missionary", (), {"id": 9})()

    document = module.DocumentService().upload_document(
        missionary, source, "PASSPORT", "INTERPOL"
    )

    assert document.id == 5
    assert document.file_path == "C:/server/new.pdf"


def test_remote_ocr_upload_serializes_multipart_json_fields(monkeypatch):
    client = FakeDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    source = Path(__file__)
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
