from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.missionary import Missionary
from services import alert_service as alert_module
from services.alert_service import AlertService


@pytest.fixture()
def alert_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(alert_module, "SessionLocal", TestingSession)
    return TestingSession


def _missionary(session, **fields):
    missionary = Missionary(
        missionary_code=fields.pop("missionary_code", "10001"),
        full_name=fields.pop("full_name", "Test Missionary"),
        status=fields.pop("status", "ACTIVE"),
        current_stage=fields.pop("current_stage", "INTERPOL"),
        **fields,
    )
    session.add(missionary)
    session.flush()
    return missionary


def test_alert_service_tracks_visa_when_residency_is_missing(alert_env):
    today = date.today()
    session = alert_env()
    try:
        _missionary(
            session,
            full_name="Visa Person",
            visa_expiration=today + timedelta(days=5),
        )
        session.commit()
    finally:
        session.close()

    alerts = AlertService().get_expiring_soon(within_days=30)

    assert [alert["field_label"] for alert in alerts] == ["Visa"]


def test_alert_service_suppresses_visa_after_residency(alert_env):
    today = date.today()
    session = alert_env()
    try:
        _missionary(
            session,
            full_name="Resident Person",
            visa_expiration=today - timedelta(days=3),
            residency_expiration=today + timedelta(days=90),
        )
        session.commit()
    finally:
        session.close()

    alerts = AlertService().get_all_alerts(within_days=30)

    assert not any(alert["field_label"] == "Visa" for alert in alerts)


def test_alert_service_keeps_passport_alert_after_residency(alert_env):
    today = date.today()
    session = alert_env()
    try:
        _missionary(
            session,
            full_name="Passport Person",
            visa_expiration=today - timedelta(days=3),
            residency_expiration=today + timedelta(days=90),
            passport_expiration=today + timedelta(days=8),
        )
        session.commit()
    finally:
        session.close()

    alerts = AlertService().get_expiring_soon(within_days=30)

    assert [alert["field_label"] for alert in alerts] == ["Passport"]
