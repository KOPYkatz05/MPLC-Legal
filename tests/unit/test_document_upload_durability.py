from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.document import Document
from database.models.missionary import Missionary
from services import document_service as module


class FakeValidator:
    def validate_workflows(self, _missionary_id):
        return None


@pytest.fixture
def upload_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: None),
    )
    root = (Path("tmp_document_upload_tests") / uuid4().hex).resolve()
    root.mkdir(parents=True)
    session = sessions()
    missionary = Missionary(
        full_name="Upload Example",
        missionary_code="upload-1",
        status="ACTIVE",
        folder_path=str(root / "missionary"),
    )
    session.add(missionary)
    session.commit()
    session.expunge(missionary)
    session.close()
    service = module.DocumentService()
    service.workflow_validator = FakeValidator()
    return service, sessions, missionary, root


def test_upload_commits_only_after_readable_atomic_copy(upload_env):
    service, sessions, missionary, root = upload_env
    source = root / "source.pdf"
    source.write_bytes(b"document")

    document = service.upload_document(
        missionary, source, "PASSPORT", "GENERAL"
    )

    destination = Path(document.file_path)
    assert destination.read_bytes() == b"document"
    assert not list(destination.parent.glob("*.uploading"))
    session = sessions()
    assert session.query(Document).count() == 1
    session.close()


def test_unreadable_staged_copy_leaves_no_row_or_destination(monkeypatch, upload_env):
    service, sessions, missionary, root = upload_env
    source = root / "source.pdf"
    source.write_bytes(b"document")
    monkeypatch.setattr(module, "verify_readable", lambda _path: "unreadable")

    with pytest.raises(OSError):
        service.upload_document(missionary, source, "PASSPORT", "GENERAL")

    session = sessions()
    assert session.query(Document).count() == 0
    session.close()
    destination_folder = Path(missionary.folder_path) / "GENERAL"
    assert not list(destination_folder.glob("PASSPORT*"))
