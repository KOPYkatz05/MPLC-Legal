from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.appointment import Appointment
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
from services import daily_digest_service as digest_module
from services.daily_digest_service import DailyDigestService


def _session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(digest_module, "SessionLocal", TestingSession)
    return TestingSession()


def _missionary(session, name="Test Person"):
    missionary = Missionary(
        missionary_code=name.replace(" ", "-").lower(),
        full_name=name,
        status="ACTIVE",
    )
    session.add(missionary)
    session.flush()
    return missionary


def test_digest_compresses_due_today_prorrogas(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        for index in range(11):
            session.add(
                SecretaryTask(
                    title=f"Prorroga packet {index}",
                    status="OPEN",
                    priority="NORMAL",
                    due_date=today,
                )
            )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)

    assert "11 prorrogas due today" in digest["due_today"]


def test_digest_can_exclude_overdue_tasks(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Old task",
                status="OPEN",
                priority="CRITICAL",
                due_date=today - timedelta(days=1),
            )
        )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(
        include_overdue=False,
        today=today,
    )

    assert digest["overdue"] == []
    assert "Old task" not in digest["text"]


def test_digest_orders_critical_items_before_important(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Important item",
                status="OPEN",
                priority="IMPORTANT",
                due_date=today,
            )
        )
        session.add(
            SecretaryTask(
                title="Critical item",
                status="OPEN",
                priority="CRITICAL",
                due_date=today,
            )
        )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)

    assert digest["top_items"][0]["text"].endswith("Critical item")


def test_digest_uses_spanish_subject_and_text(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        missionary = _missionary(session, "Persona Prueba")
        session.add(
            Appointment(
                missionary_id=missionary.id,
                appointment_field="interpol_appointment_date",
                appointment_type="Interpol",
                scheduled_date=today,
                status="SCHEDULED",
            )
        )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(language="es", today=today)

    assert digest["subject"] == "Mission Legal - Resumen de Hoy"
    assert "Vence hoy" in digest["text"]
