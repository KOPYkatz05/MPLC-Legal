import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.document import Document
from database.models.missionary import Missionary
from services import document_storage_audit_service as audit


def test_audit_reports_checksum_verified_copy_without_mutating_database(
    monkeypatch
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    test_root = Path("tmp_document_storage_audit_tests") / uuid4().hex
    canonical = test_root / "canonical"
    legacy = test_root / "legacy"
    recovered = canonical / "ACTIVE" / "Example" / "GENERAL" / "passport.pdf"
    recovered.parent.mkdir(parents=True)
    recovered.write_bytes(b"verified")
    missing_legacy = legacy / "ACTIVE" / "Example" / "GENERAL" / "passport.pdf"
    session = sessions()
    missionary = Missionary(
        missionary_code="1", full_name="Example", status="ACTIVE",
        folder_path=str(missing_legacy.parents[1]),
    )
    session.add(missionary)
    session.flush()
    document = Document(
        missionary_id=missionary.id,
        document_type="PASSPORT",
        file_name="passport.pdf",
        file_path=str(missing_legacy),
        content_sha256=hashlib.sha256(recovered.read_bytes()).hexdigest(),
        file_size=recovered.stat().st_size,
        status="ACTIVE",
    )
    session.add(document)
    session.commit()
    document_id = document.id
    session.close()
    monkeypatch.setattr(audit, "get_storage_root", lambda: canonical)

    report = audit.audit_document_storage(
        session_factory=sessions, roots=[legacy]
    )

    assert report[0].status == "recoverable"
    assert report[0].matches == (str(recovered),)
    session = sessions()
    assert session.get(Document, document_id).file_path == str(missing_legacy)
    session.close()
