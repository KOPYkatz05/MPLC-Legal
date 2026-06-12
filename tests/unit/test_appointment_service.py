from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.appointment import (
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
    APPOINTMENT_STATUS_SCHEDULED,
    Appointment,
)
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
from services import appointment_service as appointment_module
from services import secretary_work_service as secretary_module
from services import workflow_validator as validator_module
from services.appointment_service import AppointmentService
from services.workflow_validator import WorkflowValidator


@pytest.fixture()
def appointment_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(appointment_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(secretary_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(validator_module, "SessionLocal", TestingSession)
    return TestingSession


def _create_missionary(session_factory, **fields):
    session = session_factory()
    missionary = Missionary(
        missionary_code=fields.pop("missionary_code", "10001"),
        full_name=fields.pop("full_name", "Test Missionary"),
        status="ACTIVE",
        current_stage=fields.pop("current_stage", "INTERPOL"),
        **fields,
    )
    session.add(missionary)
    session.commit()
    session.refresh(missionary)
    missionary_id = missionary.id
    session.close()
    return missionary_id


def test_sync_backfills_existing_missionary_dates(appointment_env):
    missionary_id = _create_missionary(
        appointment_env,
        interpol_appointment_date=date(2026, 6, 1),
    )

    AppointmentService().sync_from_missionary_dates(missionary_id)

    session = appointment_env()
    try:
        appointment = session.query(Appointment).one()
        assert appointment.missionary_id == missionary_id
        assert appointment.appointment_field == "interpol_appointment_date"
        assert appointment.appointment_type == "Interpol"
        assert appointment.scheduled_date == date(2026, 6, 1)
        assert appointment.status == APPOINTMENT_STATUS_SCHEDULED
    finally:
        session.close()


def test_complete_appointment_clears_matching_date(appointment_env):
    missionary_id = _create_missionary(
        appointment_env,
        interpol_appointment_date=date(2026, 6, 1),
    )
    AppointmentService().sync_from_missionary_dates(missionary_id)

    session = appointment_env()
    appointment_id = session.query(Appointment).one().id
    session.close()

    AppointmentService().complete_appointment(appointment_id)

    session = appointment_env()
    try:
        appointment = session.query(Appointment).one()
        missionary = session.query(Missionary).filter_by(id=missionary_id).one()
        assert appointment.status == APPOINTMENT_STATUS_COMPLETED
        assert appointment.marked_at is not None
        assert missionary.interpol_appointment_date is None
    finally:
        session.close()


def test_missed_appointment_invalidates_documents_and_creates_task(appointment_env):
    missionary_id = _create_missionary(
        appointment_env,
        interpol_appointment_date=date(2026, 6, 1),
    )
    session = appointment_env()
    session.add_all(
        [
            Document(
                missionary_id=missionary_id,
                document_type="PAGO_INTERPOL",
                workflow_stage="INTERPOL",
                file_name="pago.pdf",
                file_path="pago.pdf",
                status="ACTIVE",
            ),
            Document(
                missionary_id=missionary_id,
                document_type="CONSTANCIA_DE_CITA_INTERPOL",
                workflow_stage="INTERPOL",
                file_name="cita.pdf",
                file_path="cita.pdf",
                status="ACTIVE",
            ),
        ]
    )
    session.commit()
    session.close()
    AppointmentService().sync_from_missionary_dates(missionary_id)

    session = appointment_env()
    appointment_id = session.query(Appointment).one().id
    session.close()

    AppointmentService().miss_appointment(appointment_id)

    session = appointment_env()
    try:
        appointment = session.query(Appointment).one()
        missionary = session.query(Missionary).filter_by(id=missionary_id).one()
        documents = session.query(Document).order_by(Document.document_type).all()
        task = session.query(SecretaryTask).one()

        assert appointment.status == APPOINTMENT_STATUS_MISSED
        assert missionary.interpol_appointment_date is None
        assert {doc.status for doc in documents} == {"STALE"}
        assert all(doc.invalidated_at is not None for doc in documents)
        assert task.missionary_id == missionary_id
        assert task.appointment_field == "interpol_appointment_date"
        assert "Get new Interpol pago" in task.title
    finally:
        session.close()


def test_new_date_after_missed_creates_new_scheduled_attempt(appointment_env):
    missionary_id = _create_missionary(
        appointment_env,
        interpol_appointment_date=date(2026, 6, 1),
    )
    service = AppointmentService()
    service.sync_from_missionary_dates(missionary_id)

    session = appointment_env()
    appointment_id = session.query(Appointment).one().id
    session.close()
    service.miss_appointment(appointment_id)

    session = appointment_env()
    missionary = session.query(Missionary).filter_by(id=missionary_id).one()
    missionary.interpol_appointment_date = date(2026, 6, 10)
    session.commit()
    session.close()

    service.sync_from_missionary_dates(
        missionary_id,
        ["interpol_appointment_date"],
    )

    session = appointment_env()
    try:
        appointments = (
            session.query(Appointment)
            .order_by(Appointment.scheduled_date)
            .all()
        )
        assert [appointment.status for appointment in appointments] == [
            APPOINTMENT_STATUS_MISSED,
            APPOINTMENT_STATUS_SCHEDULED,
        ]
        assert appointments[1].scheduled_date == date(2026, 6, 10)
    finally:
        session.close()


def test_stale_documents_do_not_satisfy_required_documents(appointment_env):
    missionary_id = _create_missionary(appointment_env)
    session = appointment_env()
    session.add(
        Document(
            missionary_id=missionary_id,
            document_type="PAGO_INTERPOL",
            workflow_stage="INTERPOL",
            file_name="pago.pdf",
            file_path="pago.pdf",
            status="STALE",
        )
    )
    session.commit()
    session.close()

    missing = WorkflowValidator().get_missing_documents(
        missionary_id,
        "INTERPOL",
    )

    assert "PAGO_INTERPOL" in missing


def test_active_replacement_document_satisfies_requirement(appointment_env):
    missionary_id = _create_missionary(appointment_env)
    session = appointment_env()
    session.add_all(
        [
            Document(
                missionary_id=missionary_id,
                document_type="PAGO_INTERPOL",
                workflow_stage="INTERPOL",
                file_name="old-pago.pdf",
                file_path="old-pago.pdf",
                status="STALE",
            ),
            Document(
                missionary_id=missionary_id,
                document_type="PAGO_INTERPOL",
                workflow_stage="INTERPOL",
                file_name="new-pago.pdf",
                file_path="new-pago.pdf",
                status="ACTIVE",
            ),
        ]
    )
    session.commit()
    session.close()

    missing = WorkflowValidator().get_missing_documents(
        missionary_id,
        "INTERPOL",
    )

    assert "PAGO_INTERPOL" not in missing
