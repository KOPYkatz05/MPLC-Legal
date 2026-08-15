import json
import stat
from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.residency_event import ResidencyEvent
from services import document_service as module


class FakeValidator:
    def validate_workflows(self, _missionary_id):
        return None


def _write_pdf(path, text="document"):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    pdf.save(path)
    pdf.close()
    return path


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
    _write_pdf(source)

    document = service.upload_document(
        missionary, source, "PASSPORT", "GENERAL"
    )

    destination = Path(document.file_path)
    assert destination.read_bytes() == source.read_bytes()
    assert not list(destination.parent.glob("*.uploading"))
    session = sessions()
    assert session.query(Document).count() == 1
    session.close()


def test_unreadable_staged_copy_leaves_no_row_or_destination(monkeypatch, upload_env):
    service, sessions, missionary, root = upload_env
    source = root / "source.pdf"
    _write_pdf(source)
    monkeypatch.setattr(module, "verify_readable", lambda _path: "unreadable")

    with pytest.raises(OSError):
        service.upload_document(missionary, source, "PASSPORT", "GENERAL")

    session = sessions()
    assert session.query(Document).count() == 0
    session.close()
    destination_folder = Path(missionary.folder_path) / "GENERAL"
    assert not list(destination_folder.glob("PASSPORT*"))


def test_upload_flushes_file_and_rename_before_database_commit(
    monkeypatch,
    upload_env,
):
    service, _sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")
    events = []
    original_file_flush = module._fsync_file
    original_directory_flush = module._fsync_parent_directory
    original_commit = Session.commit

    def flush_file(path):
        events.append(("file", Path(path).name))
        return original_file_flush(path)

    def flush_directory(path):
        events.append(("directory", Path(path).parent.name))
        return original_directory_flush(path)

    def commit(session):
        events.append(("commit", None))
        return original_commit(session)

    monkeypatch.setattr(module, "_fsync_file", flush_file)
    monkeypatch.setattr(module, "_fsync_parent_directory", flush_directory)
    monkeypatch.setattr(Session, "commit", commit)

    document = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
    )

    assert Path(document.file_path).is_file()
    assert [event[0] for event in events[:4]] == [
        "file",
        "file",
        "directory",
        "commit",
    ]


def test_failed_file_flush_never_commits_document_row(monkeypatch, upload_env):
    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")
    monkeypatch.setattr(
        module,
        "_fsync_file",
        lambda _path: (_ for _ in ()).throw(
            OSError("injected durable flush failure")
        ),
    )

    with pytest.raises(OSError, match="durable flush failure"):
        service.upload_document(
            missionary,
            source,
            "PASSPORT",
            "GENERAL",
        )

    session = sessions()
    try:
        assert session.query(Document).count() == 0
    finally:
        session.close()
    destination_folder = Path(missionary.folder_path) / "GENERAL"
    assert not list(destination_folder.glob("PASSPORT*"))


def test_read_only_source_uploads_through_writable_app_staging(upload_env):
    service, _sessions, missionary, root = upload_env
    source = _write_pdf(root / "read-only-source.pdf")
    source.chmod(stat.S_IREAD)
    try:
        document = service.upload_document(
            missionary,
            source,
            "PASSPORT",
            "GENERAL",
        )
    finally:
        source.chmod(stat.S_IREAD | stat.S_IWRITE)

    destination = Path(document.file_path)
    assert destination.is_file()
    assert destination.read_bytes() == source.read_bytes()


def test_idempotent_retry_returns_same_document(upload_env):
    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")
    upload_id = str(uuid4())

    first = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
        upload_id=upload_id,
    )
    repeated = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
        upload_id=upload_id,
    )

    assert repeated.id == first.id
    session = sessions()
    try:
        assert session.query(Document).count() == 1
    finally:
        session.close()

def test_failed_post_processing_is_durable_and_same_upload_retries(
    monkeypatch,
    upload_env,
):
    from services.residency_service import ResidencyService

    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "carne.pdf")
    upload_id = str(uuid4())
    attempts = []
    original_approval = ResidencyService.approve_initial_residency_in_session

    def approve_residency(service_instance, *args, **kwargs):
        attempts.append("attempt")
        if len(attempts) == 1:
            raise RuntimeError("injected missionary update failure")
        return original_approval(service_instance, *args, **kwargs)

    monkeypatch.setattr(
        ResidencyService,
        "approve_initial_residency_in_session",
        approve_residency,
    )

    first = service.upload_document(
        missionary,
        source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
        upload_id=upload_id,
    )

    assert first.post_processing_status == "RETRY_REQUIRED"
    assert "injected missionary update failure" in first.post_processing_error
    first_path = Path(first.file_path)
    assert first_path.is_file()

    repeated = service.upload_document(
        missionary,
        source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
        upload_id=upload_id,
    )

    assert repeated.id == first.id
    assert repeated.post_processing_status == "COMPLETE"
    assert repeated.post_processing_error is None
    assert isinstance(json.loads(repeated.post_processing_updated_fields), list)
    assert Path(repeated.file_path) == first_path
    assert attempts == ["attempt", "attempt"]
    session = sessions()
    try:
        assert session.query(Document).count() == 1
        stored = session.get(Document, first.id)
        assert stored.post_processing_status == "COMPLETE"
    finally:
        session.close()


def test_crash_boundary_leaves_pending_marker_for_same_upload_retry(
    monkeypatch,
    upload_env,
):
    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "passport.pdf")
    upload_id = str(uuid4())
    original_runner = service._run_post_processing_best_effort
    monkeypatch.setattr(
        service,
        "_run_post_processing_best_effort",
        lambda document: document,
    )

    first = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
        ocr_confirmed_data={"passport_number": "A1234567"},
        upload_id=upload_id,
    )

    session = sessions()
    try:
        assert session.get(Document, first.id).post_processing_status == "PENDING"
    finally:
        session.close()

    monkeypatch.setattr(
        service,
        "_run_post_processing_best_effort",
        original_runner,
    )

    repeated = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
        ocr_confirmed_data={"passport_number": "A1234567"},
        upload_id=upload_id,
    )

    assert repeated.id == first.id
    assert repeated.post_processing_status == "COMPLETE"
    session = sessions()
    try:
        assert session.get(Missionary, missionary.id).passport_number == "A1234567"
    finally:
        session.close()


def test_post_processing_retry_rejects_corrupt_committed_file(
    monkeypatch,
    upload_env,
):
    from services import upload_pipeline

    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "passport.pdf")
    document = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
    )
    session = sessions()
    try:
        stored = session.get(Document, document.id)
        stored.post_processing_status = "RETRY_REQUIRED"
        session.commit()
    finally:
        session.close()
    _write_pdf(Path(document.file_path), "different valid contents")
    monkeypatch.setattr(
        upload_pipeline,
        "apply_missionary_updates",
        lambda *_args, **_kwargs: pytest.fail(
            "corrupt committed bytes must not update missionary data"
        ),
    )

    with pytest.raises(module.DocumentStorageError) as raised:
        service.retry_document_post_processing(document.id)

    assert raised.value.code == module.UNREADABLE


def test_superseding_upload_cancels_failed_old_post_processing(
    monkeypatch,
    upload_env,
):
    from services.residency_service import ResidencyService

    service, sessions, missionary, root = upload_env
    old_source = _write_pdf(root / "old-carne.pdf", "old")
    new_source = _write_pdf(root / "new-carne.pdf", "new")
    old_upload_id = str(uuid4())
    attempted_document_ids = []
    original_approval = ResidencyService.approve_initial_residency_in_session

    def fail_old_then_succeed(service_instance, session, selected, document_id=None):
        attempted_document_ids.append(document_id)
        if len(attempted_document_ids) == 1:
            raise RuntimeError("old carné follow-up failed")
        return original_approval(
            service_instance,
            session,
            selected,
            document_id=document_id,
        )

    monkeypatch.setattr(
        ResidencyService,
        "approve_initial_residency_in_session",
        fail_old_then_succeed,
    )
    old = service.upload_document(
        missionary,
        old_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
        upload_id=old_upload_id,
    )
    assert old.post_processing_status == "RETRY_REQUIRED"

    replacement = service.upload_document(
        missionary,
        new_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
        supersedes_document_id=old.id,
    )
    assert replacement.post_processing_status == "COMPLETE"

    retried_old = service.upload_document(
        missionary,
        old_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
        upload_id=old_upload_id,
    )

    assert retried_old.status == "SUPERSEDED"
    assert retried_old.post_processing_status == "CANCELLED"
    assert attempted_document_ids == [old.id, replacement.id]
    session = sessions()
    try:
        residency_event = session.query(ResidencyEvent).one()
        assert residency_event.document_id == replacement.id
        assert session.get(Document, old.id).post_processing_status == "CANCELLED"
    finally:
        session.close()


def test_idempotent_retry_never_accepts_corrupted_committed_file(upload_env):
    service, _sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")
    upload_id = str(uuid4())
    document = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
        upload_id=upload_id,
    )
    Path(document.file_path).write_bytes(b"corrupted")

    with pytest.raises(module.DocumentStorageError) as raised:
        service.upload_document(
            missionary,
            source,
            "PASSPORT",
            "GENERAL",
            upload_id=upload_id,
        )

    assert raised.value.code == module.UNREADABLE


def test_reused_upload_id_with_different_bytes_is_rejected(upload_env):
    service, sessions, missionary, root = upload_env
    first_source = _write_pdf(root / "first.pdf", "first")
    second_source = _write_pdf(root / "second.pdf", "second")
    upload_id = str(uuid4())

    original = service.upload_document(
        missionary,
        first_source,
        "PASSPORT",
        "GENERAL",
        upload_id=upload_id,
    )

    with pytest.raises(module.DocumentUploadConflictError):
        service.upload_document(
            missionary,
            second_source,
            "PASSPORT",
            "GENERAL",
            upload_id=upload_id,
        )

    assert Path(original.file_path).read_bytes() == first_source.read_bytes()
    session = sessions()
    try:
        assert session.query(Document).count() == 1
    finally:
        session.close()


def test_successful_replacement_keeps_old_file_recoverable(upload_env):
    service, sessions, missionary, root = upload_env
    old_source = _write_pdf(root / "old.pdf", "old")
    new_source = _write_pdf(root / "new.pdf", "new")
    old = service.upload_document(
        missionary,
        old_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
    )

    new = service.upload_document(
        missionary,
        new_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
        supersedes_document_id=old.id,
    )

    session = sessions()
    try:
        stored_old = session.get(Document, old.id)
        stored_new = session.get(Document, new.id)
        assert stored_old.status == "SUPERSEDED"
        assert stored_new.status == "ACTIVE"
        assert stored_new.supersedes_document_id == stored_old.id
        assert Path(stored_old.file_path).is_file()
        assert Path(stored_new.file_path).is_file()
    finally:
        session.close()


def test_failed_replacement_never_removes_old_document(monkeypatch, upload_env):
    service, sessions, missionary, root = upload_env
    old_source = _write_pdf(root / "old.pdf", "old")
    new_source = _write_pdf(root / "new.pdf", "new")
    old = service.upload_document(
        missionary,
        old_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
    )
    old_path = Path(old.file_path)
    real_sha256 = module.sha256_file
    monkeypatch.setattr(
        module,
        "sha256_file",
        lambda path: (
            "wrong-checksum"
            if Path(path).suffix == ".uploading"
            else real_sha256(path)
        ),
    )

    with pytest.raises(OSError):
        service.upload_document(
            missionary,
            new_source,
            "CARNE_DE_EXTRANJERIA",
            "CARNET DE EXTRANJERIA",
            supersedes_document_id=old.id,
        )

    session = sessions()
    try:
        stored_old = session.get(Document, old.id)
        assert stored_old.status == "ACTIVE"
        assert session.query(Document).count() == 1
        assert old_path.is_file()
    finally:
        session.close()


def test_post_commit_workflow_failure_does_not_delete_file(upload_env):
    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")

    class BrokenValidator:
        def validate_workflows(self, _missionary_id):
            raise RuntimeError("validator unavailable")

    service.workflow_validator = BrokenValidator()
    document = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
    )

    assert Path(document.file_path).is_file()
    session = sessions()
    try:
        assert session.get(Document, document.id) is not None
    finally:
        session.close()


def test_precommit_flush_failure_cleans_only_new_file(monkeypatch, upload_env):
    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")

    class FailingFlushSession(Session):
        def flush(self, objects=None):
            raise RuntimeError("injected flush failure")

    failing_sessions = sessionmaker(
        bind=sessions.kw["bind"],
        class_=FailingFlushSession,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(module, "SessionLocal", failing_sessions)

    with pytest.raises(RuntimeError, match="injected flush failure"):
        service.upload_document(
            missionary,
            source,
            "PASSPORT",
            "GENERAL",
        )

    destination_folder = Path(missionary.folder_path) / "GENERAL"
    assert not list(destination_folder.glob("PASSPORT*"))
    session = sessions()
    try:
        assert session.query(Document).count() == 0
    finally:
        session.close()


def test_lost_postcommit_signal_reconciles_without_deleting_file(
    monkeypatch,
    upload_env,
):
    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")

    class CommitThenRaiseSession(Session):
        def commit(self):
            super().commit()
            raise RuntimeError("injected lost commit acknowledgement")

    ambiguous_sessions = sessionmaker(
        bind=sessions.kw["bind"],
        class_=CommitThenRaiseSession,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(module, "SessionLocal", ambiguous_sessions)

    document = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
    )

    assert Path(document.file_path).is_file()
    session = sessions()
    try:
        assert session.query(Document).count() == 1
        assert session.get(Document, document.id).file_path == document.file_path
    finally:
        session.close()


def test_delete_commit_failure_preserves_row_and_file(monkeypatch, upload_env):
    service, sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")
    document = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
    )
    document_path = Path(document.file_path)

    class FailingCommitSession(Session):
        def commit(self):
            raise RuntimeError("injected delete commit failure")

    failing_sessions = sessionmaker(
        bind=sessions.kw["bind"],
        class_=FailingCommitSession,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(module, "SessionLocal", failing_sessions)

    assert service.delete_document_by_id(document.id) is False
    assert document_path.is_file()
    session = sessions()
    try:
        assert session.get(Document, document.id) is not None
    finally:
        session.close()


def test_ambiguous_duplicate_can_be_kept_but_not_replaced_by_guess(upload_env):
    service, _sessions, missionary, root = upload_env
    first_source = _write_pdf(root / "first.pdf", "front")
    second_source = _write_pdf(root / "second.pdf", "back")
    first = service.upload_document(
        missionary,
        first_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
    )
    second = service.upload_document(
        missionary,
        second_source,
        "CARNE_DE_EXTRANJERIA",
        "CARNET DE EXTRANJERIA",
    )

    assert first.id != second.id
    assert service.document_type_exists(
        missionary.id,
        "CARNE_DE_EXTRANJERIA",
    )
    with pytest.raises(module.DocumentReplacementError):
        service.get_active_document_by_type(
            missionary.id,
            "CARNE_DE_EXTRANJERIA",
        )


def test_precommit_retry_failure_reconciles_concurrent_winner(
    monkeypatch,
    upload_env,
):
    service, _sessions, missionary, root = upload_env
    source = _write_pdf(root / "source.pdf")
    upload_id = str(uuid4())
    winner_path = root / "winner.pdf"
    winner_path.write_bytes(source.read_bytes())
    winner = Document(
        id=501,
        missionary_id=missionary.id,
        document_type="PASSPORT",
        workflow_stage="GENERAL",
        status="ACTIVE",
        file_name=winner_path.name,
        file_path=str(winner_path),
        upload_id=upload_id,
        content_sha256=module.sha256_file(source),
        file_size=source.stat().st_size,
    )
    monkeypatch.setattr(
        service,
        "get_document_by_upload_id",
        lambda candidate: winner if candidate == upload_id else None,
    )
    monkeypatch.setattr(
        module.shutil,
        "copyfile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected retry copy failure")
        ),
    )

    reconciled = service.upload_document(
        missionary,
        source,
        "PASSPORT",
        "GENERAL",
        upload_id=upload_id,
    )

    assert reconciled is winner
    assert winner_path.is_file()
