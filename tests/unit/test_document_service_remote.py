from pathlib import Path

from services import document_service as module


class FakeDocumentClient:
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
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"document")
        return destination

    def upload(self, path, *, file_path, data):
        assert Path(file_path).read_bytes() == b"upload"
        assert data["missionary_id"] == "9"
        return {
            "id": 5,
            "missionary_id": 9,
            "document_type": data["document_type"],
            "file_path": "C:/server/new.pdf",
        }


def test_remote_documents_are_materialized_in_local_cache(monkeypatch, tmp_path):
    client = FakeDocumentClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    monkeypatch.setattr(module, "get_client_data_dir", lambda: tmp_path)

    documents = module.DocumentService().get_documents(9)

    cached = Path(documents[0].file_path)
    assert cached.read_bytes() == b"document"
    assert cached.parent == tmp_path / "DocumentCache" / "9"


def test_remote_upload_sends_file_and_materializes_response(monkeypatch, tmp_path):
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
    assert Path(document.file_path).read_bytes() == b"document"
