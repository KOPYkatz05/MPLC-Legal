from datetime import date

import pytest
from sqlalchemy import create_engine

from database.db import Base, SessionLocal
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.residency_event import ResidencyEvent
from services.residency_service import (
    ResidencyService,
    calculate_residency_expiration,
)
from services.upload_pipeline import apply_missionary_updates


@pytest.fixture()
def residency_db():
    old_bind = SessionLocal.kw.get("bind")
    engine = create_engine("sqlite:///:memory:")
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)
        SessionLocal.configure(bind=old_bind)


def _create_missionary(arrival_date=date(2026, 1, 5)):
    session = SessionLocal()
    try:
        missionary = Missionary(
            missionary_code="123",
            full_name="Test Missionary",
            arrival_date=arrival_date,
            status="ACTIVE",
        )
        session.add(missionary)
        session.commit()
        session.refresh(missionary)
        return missionary.id
    finally:
        session.close()


def _create_document(missionary_id, document_type):
    session = SessionLocal()
    try:
        document = Document(
            missionary_id=missionary_id,
            document_type=document_type,
            workflow_stage="PRORROGA",
            file_name=f"{document_type}.pdf",
            file_path=f"/tmp/{document_type}.pdf",
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        return document.id
    finally:
        session.close()


def _missionary(missionary_id):
    session = SessionLocal()
    try:
        missionary = (
            session.query(Missionary)
            .filter_by(id=missionary_id)
            .first()
        )
        return missionary
    finally:
        session.close()


def _events(missionary_id):
    session = SessionLocal()
    try:
        return (
            session.query(ResidencyEvent)
            .filter_by(missionary_id=missionary_id)
            .order_by(ResidencyEvent.sequence_number.asc())
            .all()
        )
    finally:
        session.close()


def test_calculate_residency_expiration_uses_arrival_anniversary():
    arrival = date(2026, 1, 5)

    assert calculate_residency_expiration(arrival, 0) == date(2027, 1, 5)
    assert calculate_residency_expiration(arrival, 1) == date(2028, 1, 5)
    assert calculate_residency_expiration(arrival, 2) == date(2029, 1, 5)


def test_calculate_residency_expiration_handles_february_29():
    assert calculate_residency_expiration(date(2024, 2, 29), 0) == date(
        2025,
        2,
        28,
    )


def test_approve_next_prorroga_caps_at_two_events(residency_db):
    missionary_id = _create_missionary()
    service = ResidencyService()

    first = service.approve_next_prorroga(missionary_id, document_id=1)
    second = service.approve_next_prorroga(missionary_id, document_id=2)
    third = service.approve_next_prorroga(missionary_id, document_id=3)

    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert third is None
    assert len(_events(missionary_id)) == 2
    assert _missionary(missionary_id).residency_expiration == date(
        2029,
        1,
        5,
    )


def test_approve_next_prorroga_is_idempotent_for_document(residency_db):
    missionary_id = _create_missionary()
    service = ResidencyService()

    first = service.approve_next_prorroga(missionary_id, document_id=10)
    repeated = service.approve_next_prorroga(missionary_id, document_id=10)

    assert first.id == repeated.id
    assert len(_events(missionary_id)) == 1
    assert _missionary(missionary_id).residency_expiration == date(
        2028,
        1,
        5,
    )


def test_carnet_upload_creates_initial_residency_event(residency_db):
    missionary_id = _create_missionary()
    document_id = _create_document(missionary_id, "CARNE_DE_EXTRANJERIA")

    updated = apply_missionary_updates(
        missionary_id,
        "CARNE_DE_EXTRANJERIA",
        document_id,
        {},
    )

    events = _events(missionary_id)
    assert "residency_expiration" in updated
    assert len(events) == 1
    assert events[0].event_type == "INITIAL_RESIDENCY"
    assert events[0].sequence_number == 0
    assert _missionary(missionary_id).residency_expiration == date(
        2027,
        1,
        5,
    )


def test_prorroga_upload_derives_expiration_from_arrival_not_ocr(
    residency_db,
):
    missionary_id = _create_missionary()
    document_id = _create_document(missionary_id, "APROBACION_DE_PRORROGA")

    updated = apply_missionary_updates(
        missionary_id,
        "APROBACION_DE_PRORROGA",
        document_id,
        {"prorroga_expiration": "2035-12-31"},
    )

    events = _events(missionary_id)
    missionary = _missionary(missionary_id)
    assert "residency_expiration" in updated
    assert "prorroga_expiration" not in updated
    assert len(events) == 1
    assert events[0].event_type == "PRORROGA"
    assert events[0].sequence_number == 1
    assert missionary.residency_expiration == date(2028, 1, 5)
    assert missionary.prorroga_expiration is None
