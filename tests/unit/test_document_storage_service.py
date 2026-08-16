from pathlib import Path
import hashlib
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.document import Document
from database.models.missionary import Missionary
from services import document_storage_service as storage


@pytest.fixture
def storage_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(storage, "SessionLocal", sessions)
    root = Path("tmp_document_storage_tests") / uuid4().hex
    root.mkdir(parents=True)
    return sessions, root


def _record(sessions, root, *, saved_path, file_name="passport.pdf"):
    session = sessions()
    missionary = Missionary(
        full_name="Storage Example",
        missionary_code="storage-1",
        status="ACTIVE",
        folder_path=str(root),
    )
    session.add(missionary)
    session.flush()
    document = Document(
        missionary_id=missionary.id,
        document_type="PASSPORT",
        workflow_stage="GENERAL",
        status="ACTIVE",
        file_name=file_name,
        file_path=str(saved_path),
    )
    session.add(document)
    session.commit()
    document_id = document.id
    missionary_id = missionary.id
    session.close()
    return missionary_id, document_id


def test_unique_scoped_match_repairs_and_persists(storage_env):
    sessions, root = storage_env
    missionary_root = root / "missionary"
    recovered = missionary_root / "GENERAL" / "passport.pdf"
    recovered.parent.mkdir(parents=True)
    recovered.write_bytes(b"pdf")
    _, document_id = _record(
        sessions, missionary_root, saved_path=root / "old" / "passport.pdf"
    )

    assert storage.resolve_document_path(document_id, session_factory=sessions) == recovered

    session = sessions()
    assert session.get(Document, document_id).file_path == str(recovered)
    session.close()


def test_ambiguous_matches_are_never_relinked(storage_env):
    sessions, root = storage_env
    missionary_root = root / "missionary"
    for folder in ("GENERAL", "INTERPOL"):
        candidate = missionary_root / folder / "passport.pdf"
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(folder.encode())
    _, document_id = _record(
        sessions, missionary_root, saved_path=root / "old" / "passport.pdf"
    )

    with pytest.raises(storage.DocumentStorageError) as raised:
        storage.resolve_document_path(document_id, session_factory=sessions)

    assert raised.value.code == storage.AMBIGUOUS


def test_match_outside_missionary_folder_is_ignored(storage_env):
    sessions, root = storage_env
    outside = root / "other-missionary" / "passport.pdf"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"wrong")
    _, document_id = _record(
        sessions, root / "missionary", saved_path=root / "old" / "passport.pdf"
    )

    with pytest.raises(storage.DocumentStorageError) as raised:
        storage.resolve_document_path(document_id, session_factory=sessions)

    assert raised.value.code == storage.MISSING


def test_checksum_match_in_canonical_root_repairs_legacy_onedrive_path(
    storage_env, monkeypatch
):
    sessions, root = storage_env
    canonical_root = root / "canonical"
    recovered = canonical_root / "ACTIVE" / "Storage Example" / "GENERAL" / "passport.pdf"
    recovered.parent.mkdir(parents=True)
    recovered.write_bytes(b"verified document")
    monkeypatch.setattr(storage, "get_storage_root", lambda: canonical_root)
    _, document_id = _record(
        sessions,
        root / "legacy" / "ACTIVE" / "Storage Example",
        saved_path=root / "legacy" / "ACTIVE" / "Storage Example" / "GENERAL" / "passport.pdf",
    )
    session = sessions()
    document = session.get(Document, document_id)
    document.content_sha256 = hashlib.sha256(recovered.read_bytes()).hexdigest()
    document.file_size = recovered.stat().st_size
    session.commit()
    session.close()

    assert storage.resolve_document_path(document_id, session_factory=sessions) == recovered

    session = sessions()
    repaired = session.get(Document, document_id)
    assert repaired.file_path == str(recovered)
    assert repaired.storage_relative_path == str(
        Path("ACTIVE") / "Storage Example" / "GENERAL" / "passport.pdf"
    )
    session.close()


def test_folder_move_rewrites_only_paths_beneath_source(storage_env):
    sessions, root = storage_env
    source = root / "Active" / "Missionary"
    destination = root / "Archive" / "Missionary"
    inside = source / "GENERAL" / "passport.pdf"
    outside = root / "external.pdf"
    missionary_id, document_id = _record(sessions, source, saved_path=inside)
    session = sessions()
    session.add(
        Document(
            missionary_id=missionary_id,
            document_type="OTHER",
            workflow_stage="GENERAL",
            status="ACTIVE",
            file_name="external.pdf",
            file_path=str(outside),
        )
    )
    session.commit()
    missionary = session.get(Missionary, missionary_id)

    move = storage.move_folder_and_rewrite_paths(
        session, missionary, lambda _path: destination
    )
    storage.commit_with_folder_rollback(session, move)

    documents = session.query(Document).order_by(Document.id).all()
    assert documents[0].file_path == str(destination / "GENERAL" / "passport.pdf")
    assert documents[1].file_path == str(outside)
    session.close()


def test_commit_failure_moves_folder_back(storage_env, monkeypatch):
    sessions, root = storage_env
    source = root / "Active" / "Missionary"
    destination = root / "Archive" / "Missionary"
    document_path = source / "GENERAL" / "passport.pdf"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(b"pdf")
    destination.parent.mkdir(parents=True)
    missionary_id, _ = _record(sessions, source, saved_path=document_path)
    session = sessions()
    missionary = session.get(Missionary, missionary_id)

    move = storage.move_folder_and_rewrite_paths(
        session,
        missionary,
        lambda path: shutil.move(path, destination),
    )
    monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db")))

    with pytest.raises(RuntimeError, match="db"):
        storage.commit_with_folder_rollback(session, move)

    assert source.is_dir()
    assert (source / "GENERAL" / "passport.pdf").is_file()
    assert not destination.exists()
    session.close()


def test_write_folder_refuses_to_create_second_split_root(storage_env, monkeypatch):
    sessions, root = storage_env
    canonical_root = root / "canonical"
    legacy_folder = root / "legacy" / "ACTIVE" / "Storage Example"
    legacy_folder.mkdir(parents=True)
    monkeypatch.setattr(storage, "get_storage_root", lambda: canonical_root)
    missionary = Missionary(id=7, folder_path=str(legacy_folder))

    with pytest.raises(storage.DocumentStorageError) as raised:
        storage.resolve_missionary_write_folder(missionary)

    assert raised.value.code == storage.ROOT_MISMATCH
    assert not (canonical_root / "ACTIVE" / "Storage Example").exists()
