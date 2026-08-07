from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.document import Document
from database.models.missionary import Missionary
from services import missionary_service as module


class FakeOneDrive:
    def archive_missionary_folder(self, path, group_name=None):
        return f"archive/{group_name or 'single'}/{path}"

    def trash_missionary_folder(self, path):
        return f"trash/{path}"

    def restore_missionary_folder(self, path):
        return f"active/{path}"


def _environment(monkeypatch, status="ACTIVE", folder="source/Missionary"):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: None),
    )
    service = module.MissionaryService()
    service.onedrive_service = FakeOneDrive()
    session = sessions()
    missionary = Missionary(
        full_name="Move Example",
        missionary_code="move-1",
        status=status,
        folder_path=folder,
    )
    session.add(missionary)
    session.flush()
    session.add(
        Document(
            missionary_id=missionary.id,
            document_type="PASSPORT",
            workflow_stage="GENERAL",
            status="ACTIVE",
            file_name="passport.pdf",
            file_path=f"{folder}/GENERAL/passport.pdf",
        )
    )
    session.commit()
    missionary_id = missionary.id
    session.close()
    return service, sessions, missionary_id


def _paths(sessions, missionary_id):
    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    document = session.query(Document).filter_by(missionary_id=missionary_id).one()
    values = missionary.folder_path, document.file_path, missionary.status
    session.close()
    return values


def test_archive_rewrites_document_path(monkeypatch):
    service, sessions, missionary_id = _environment(monkeypatch)
    assert service.archive_missionary(missionary_id) is True
    folder, document, status = _paths(sessions, missionary_id)
    assert folder.startswith("archive/single/")
    assert document.startswith("archive\\single\\source\\Missionary")
    assert status == "ARCHIVED"


def test_trash_and_restore_rewrite_document_path(monkeypatch):
    service, sessions, missionary_id = _environment(monkeypatch)
    assert service.delete_missionary(missionary_id) is True
    trash_folder, trash_document, status = _paths(sessions, missionary_id)
    assert trash_document.startswith("trash\\source\\Missionary")
    assert status == "TRASH"

    assert service.restore_missionary(missionary_id) is True
    active_folder, active_document, status = _paths(sessions, missionary_id)
    assert active_folder.startswith("active/")
    assert active_document.startswith("active\\trash\\source\\Missionary")
    assert status == "ACTIVE"
