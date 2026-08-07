import pytest
import shutil
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.missionary import Missionary
from database.models.document import Document
from database.models.stage_history import StageHistory
from database.models.workflow import WorkflowStage
from services import workflow_service as module
from services import missionary_service as missionary_module
from services.missionary_service import MissionaryService
from utils.constants import WORKFLOW_STAGES


@pytest.fixture
def workflow_temp_path():
    path = Path(tempfile.gettempdir()) / f"mission-legal-workflow-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class FakeOneDrive:
    def archive_missionary_folder(self, path):
        return f"archived/{path}"


def _service(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(module, "SessionLocal", testing_session)
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: None),
    )
    service = module.WorkflowService()
    service.onedrive_service = FakeOneDrive()
    return service, testing_session


def _missionary_with_workflows(session_factory, current_stage):
    session = session_factory()
    sequence = session.query(Missionary).count()
    missionary = Missionary(
        full_name="Stage Example",
        missionary_code=str(700 + sequence),
        status="ACTIVE",
        current_stage=current_stage,
        folder_path="active/Stage Example",
    )
    session.add(missionary)
    session.flush()
    current_index = WORKFLOW_STAGES.index(current_stage)
    for index, stage in enumerate(WORKFLOW_STAGES):
        status = "NOT STARTED"
        if index < current_index:
            status = "COMPLETED"
        elif stage == current_stage:
            status = "IN PROGRESS"
        session.add(
            WorkflowStage(
                missionary_id=missionary.id,
                stage_name=stage,
                status=status,
            )
        )
    session.commit()
    missionary_id = missionary.id
    session.close()
    return missionary_id


def test_advance_missionary_updates_workflow_stage_and_history(monkeypatch):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])

    assert service.advance_missionary(missionary_id) is True

    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    assert missionary.current_stage == WORKFLOW_STAGES[1]
    assert session.query(StageHistory).one().to_stage == WORKFLOW_STAGES[1]
    session.close()


def test_advance_final_stage_archives_and_moves_folder(monkeypatch):
    service, sessions = _service(monkeypatch)
    final_stage = WORKFLOW_STAGES[-1]
    missionary_id = _missionary_with_workflows(sessions, final_stage)
    session = sessions()
    session.add(
        Document(
            missionary_id=missionary_id,
            document_type="PASSPORT",
            workflow_stage="GENERAL",
            status="ACTIVE",
            file_name="passport.pdf",
            file_path="active/Stage Example/GENERAL/passport.pdf",
        )
    )
    session.commit()
    session.close()

    assert service.advance_missionary(missionary_id) is True

    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    assert missionary.status == "ARCHIVED"
    assert missionary.folder_path.startswith("archived/")
    assert session.query(Document).one().file_path.startswith(
        "archived\\active\\Stage Example"
    )
    assert session.query(StageHistory).one().to_stage == "ARCHIVED"
    session.close()


def test_peruvian_dni_tracking_cannot_advance(monkeypatch):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])

    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    missionary.tracking_profile = "PERUVIAN_DNI"
    missionary.current_stage = "DNI"
    session.commit()
    session.close()

    assert service.advance_missionary(missionary_id) is False

    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    assert missionary.current_stage == "DNI"
    assert session.query(StageHistory).count() == 0
    session.close()


def test_manual_completion_atomically_advances_and_returns_snapshot(monkeypatch):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    session = sessions()
    workflow_id = (
        session.query(WorkflowStage)
        .filter_by(missionary_id=missionary_id, stage_name=WORKFLOW_STAGES[0])
        .one()
        .id
    )
    session.close()


def test_manual_completion_does_not_query_expired_models_after_commit(monkeypatch):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    session = sessions()
    workflow_id = (
        session.query(WorkflowStage)
        .filter_by(missionary_id=missionary_id, stage_name=WORKFLOW_STAGES[0])
        .one()
        .id
    )
    session.close()
    committed = False

    def mark_committed(_session):
        nonlocal committed
        committed = True

    def reject_post_commit_queries(
        _connection, _cursor, _statement, _parameters, _context, _executemany
    ):
        if committed:
            raise RuntimeError("post-commit database access")

    engine = sessions.kw["bind"]
    event.listen(sessions.class_, "after_commit", mark_committed)
    event.listen(engine, "before_cursor_execute", reject_post_commit_queries)
    try:
        result = service.update_workflow_status(workflow_id, "COMPLETED")
    finally:
        event.remove(sessions.class_, "after_commit", mark_committed)
        event.remove(engine, "before_cursor_execute", reject_post_commit_queries)

    assert result["current_stage"] == WORKFLOW_STAGES[1]

    result = service.update_workflow_status(workflow_id, "COMPLETED")

    assert result == {
        "workflow_id": workflow_id,
        "missionary_id": missionary_id,
        "workflow_status": "COMPLETED",
        "current_stage": WORKFLOW_STAGES[1],
        "missionary_status": "ACTIVE",
    }
    session = sessions()
    assert session.get(Missionary, missionary_id).current_stage == WORKFLOW_STAGES[1]
    assert session.get(WorkflowStage, workflow_id).status == "COMPLETED"
    session.close()


def test_manual_completion_rolls_back_both_values_and_raises(monkeypatch):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    session = sessions()
    workflow_id = (
        session.query(WorkflowStage)
        .filter_by(missionary_id=missionary_id, stage_name=WORKFLOW_STAGES[0])
        .one()
        .id
    )
    session.close()

    def fail_commit(_session):
        raise RuntimeError("injected commit failure")

    event.listen(sessions.class_, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            service.update_workflow_status(workflow_id, "COMPLETED")
    finally:
        event.remove(sessions.class_, "before_commit", fail_commit)

    session = sessions()
    assert session.get(Missionary, missionary_id).current_stage == WORKFLOW_STAGES[0]
    assert session.get(WorkflowStage, workflow_id).status == "IN PROGRESS"
    session.close()


def test_repeated_completion_is_idempotent(monkeypatch):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    session = sessions()
    workflow_id = (
        session.query(WorkflowStage)
        .filter_by(missionary_id=missionary_id, stage_name=WORKFLOW_STAGES[0])
        .one()
        .id
    )
    session.close()

    first = service.update_workflow_status(workflow_id, "COMPLETED")
    second = service.update_workflow_status(workflow_id, "COMPLETED")

    assert first["current_stage"] == WORKFLOW_STAGES[1]
    assert second["current_stage"] == WORKFLOW_STAGES[1]
    session = sessions()
    assert session.query(StageHistory).count() == 0
    session.close()


def test_reconciliation_repairs_only_active_legal_records(monkeypatch):
    service, sessions = _service(monkeypatch)
    active_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    archived_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    trashed_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    peruvian_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    session = sessions()
    for missionary_id in (active_id, archived_id, trashed_id, peruvian_id):
        session.get(Missionary, missionary_id).current_stage = WORKFLOW_STAGES[2]
    session.get(Missionary, archived_id).status = "ARCHIVED"
    session.get(Missionary, trashed_id).status = "TRASH"
    session.get(Missionary, peruvian_id).tracking_profile = "PERUVIAN_DNI"
    session.commit()
    session.close()

    repaired = service.reconcile_missionary_stages(
        [active_id, archived_id, trashed_id, peruvian_id]
    )

    assert repaired == [{
        "missionary_id": active_id,
        "old_stage": WORKFLOW_STAGES[2],
        "current_stage": WORKFLOW_STAGES[0],
    }]
    session = sessions()
    assert session.get(Missionary, active_id).current_stage == WORKFLOW_STAGES[0]
    assert session.get(Missionary, archived_id).current_stage == WORKFLOW_STAGES[2]
    assert session.get(Missionary, trashed_id).current_stage == WORKFLOW_STAGES[2]
    assert session.get(Missionary, peruvian_id).current_stage == WORKFLOW_STAGES[2]
    session.close()


def test_reconciliation_does_not_commit_when_record_is_already_correct(monkeypatch):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    commit_count = 0

    def count_commit(_session):
        nonlocal commit_count
        commit_count += 1

    event.listen(sessions.class_, "before_commit", count_commit)
    try:
        assert service.reconcile_missionary_stages([missionary_id]) == []
    finally:
        event.remove(sessions.class_, "before_commit", count_commit)
    assert commit_count == 0


@pytest.mark.parametrize("malformation", ["missing", "duplicate"])
def test_reconciliation_skips_structurally_invalid_workflows(
    monkeypatch, caplog, malformation
):
    service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    missionary.current_stage = WORKFLOW_STAGES[2]
    first = (
        session.query(WorkflowStage)
        .filter_by(missionary_id=missionary_id, stage_name=WORKFLOW_STAGES[0])
        .one()
    )
    if malformation == "missing":
        session.delete(first)
    else:
        session.add(
            WorkflowStage(
                missionary_id=missionary_id,
                stage_name=first.stage_name,
                status=first.status,
            )
        )
    session.commit()
    session.close()

    with caplog.at_level("WARNING"):
        assert service.reconcile_missionary_stages([missionary_id]) == []

    session = sessions()
    assert session.get(Missionary, missionary_id).current_stage == WORKFLOW_STAGES[2]
    session.close()
    assert f"missionary {missionary_id}" in caplog.text
    assert "Stage Example" not in caplog.text


def test_active_missionary_read_returns_reconciled_stage(monkeypatch):
    workflow_service, sessions = _service(monkeypatch)
    missionary_id = _missionary_with_workflows(sessions, WORKFLOW_STAGES[0])
    session = sessions()
    session.get(Missionary, missionary_id).current_stage = WORKFLOW_STAGES[2]
    session.commit()
    session.close()

    monkeypatch.setattr(missionary_module, "SessionLocal", sessions)
    reader = MissionaryService.__new__(MissionaryService)
    reader.api_client = None
    reader.workflow_service = workflow_service

    rows = reader.get_all_missionaries()

    assert len(rows) == 1
    assert rows[0].current_stage == WORKFLOW_STAGES[0]


def test_manual_final_completion_archives_in_same_result(monkeypatch):
    service, sessions = _service(monkeypatch)
    final_stage = WORKFLOW_STAGES[-1]
    missionary_id = _missionary_with_workflows(sessions, final_stage)
    session = sessions()
    workflow_id = (
        session.query(WorkflowStage)
        .filter_by(missionary_id=missionary_id, stage_name=final_stage)
        .one()
        .id
    )
    session.close()

    result = service.update_workflow_status(workflow_id, "COMPLETED")

    assert result["current_stage"] == "NEW"
    assert result["missionary_status"] == "ARCHIVED"
    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    assert missionary.status == "ARCHIVED"
    assert missionary.cancelacion_date is not None
    assert session.query(StageHistory).one().to_stage == "ARCHIVED"
    session.close()


def test_manual_final_completion_restores_folder_when_commit_fails(
    monkeypatch, workflow_temp_path
):
    service, sessions = _service(monkeypatch)
    final_stage = WORKFLOW_STAGES[-1]
    missionary_id = _missionary_with_workflows(sessions, final_stage)
    source = workflow_temp_path / "active" / "Stage Example"
    source.mkdir(parents=True)
    document_path = source / "passport.pdf"
    document_path.write_bytes(b"test")
    archive_root = workflow_temp_path / "archive"

    class MovingOneDrive:
        def archive_missionary_folder(self, path):
            destination = archive_root / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, destination)
            return destination

    service.onedrive_service = MovingOneDrive()
    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    missionary.folder_path = str(source)
    workflow_id = (
        session.query(WorkflowStage)
        .filter_by(missionary_id=missionary_id, stage_name=final_stage)
        .one()
        .id
    )
    session.add(
        Document(
            missionary_id=missionary_id,
            document_type="PASSPORT",
            workflow_stage="GENERAL",
            status="ACTIVE",
            file_name=document_path.name,
            file_path=str(document_path),
        )
    )
    session.commit()
    session.close()

    def fail_commit(_session):
        raise RuntimeError("injected archive commit failure")

    event.listen(sessions.class_, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="injected archive commit failure"):
            service.update_workflow_status(workflow_id, "COMPLETED")
    finally:
        event.remove(sessions.class_, "before_commit", fail_commit)

    assert source.is_dir()
    assert document_path.is_file()
    assert not (archive_root / source.name).exists()
    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    assert missionary.status == "ACTIVE"
    assert missionary.current_stage == final_stage
    assert session.get(WorkflowStage, workflow_id).status == "IN PROGRESS"
    assert session.query(Document).one().file_path == str(document_path)
    assert session.query(StageHistory).count() == 0
    session.close()
