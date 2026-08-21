from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.base import Base
from database.models.missionary import Missionary
from database.models.workflow import WorkflowStage
from services import missionary_service as service_module


def _local_service(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(service_module, "SessionLocal", sessions)
    monkeypatch.setattr(
        service_module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: None),
    )
    monkeypatch.setattr(
        service_module.OneDriveService,
        "create_missionary_folders",
        lambda _self, _name: "C:/Missionaries/Example",
    )
    return service_module.MissionaryService(), sessions


def test_local_create_routes_peruvian_to_dni_without_foreign_workflows(
    monkeypatch,
):
    service, sessions = _local_service(monkeypatch)

    created = service.create_missionary(
        full_name="Quispe, Ana",
        missionary_code="101",
        nationality="Peru",
        passport_number="P1234567",
        arrival_date=date(2026, 7, 12),
    )

    session = sessions()
    missionary = session.get(Missionary, created.id)
    assert missionary.tracking_profile == "PERUVIAN_DNI"
    assert missionary.current_stage == "DNI"
    assert missionary.passport_number is None
    assert missionary.arrival_date is None
    assert session.query(WorkflowStage).filter_by(
        missionary_id=created.id
    ).count() == 0
    session.close()
