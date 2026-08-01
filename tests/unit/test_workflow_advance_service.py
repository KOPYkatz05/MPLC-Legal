from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models.missionary import Missionary
from database.models.stage_history import StageHistory
from database.models.workflow import WorkflowStage
from services import workflow_service as module
from utils.constants import WORKFLOW_STAGES


class FakeOneDrive:
    def archive_missionary_folder(self, path):
        return f"archived/{path}"


def _service(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(module, "SessionLocal", testing_session)
    service = module.WorkflowService()
    service.onedrive_service = FakeOneDrive()
    return service, testing_session


def _missionary_with_workflows(session_factory, current_stage):
    session = session_factory()
    missionary = Missionary(
        full_name="Stage Example",
        missionary_code="700",
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

    assert service.advance_missionary(missionary_id) is True

    session = sessions()
    missionary = session.get(Missionary, missionary_id)
    assert missionary.status == "ARCHIVED"
    assert missionary.folder_path.startswith("archived/")
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
