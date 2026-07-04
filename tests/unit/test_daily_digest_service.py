from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.appointment import Appointment
from database.models.missionary import Missionary
from database.models.secretary_work import (
    MissionaryGroup,
    SecretaryTask,
    SecretaryTaskMissionary,
)
from services import daily_digest_service as digest_module
from services import notification_feed_service as feed_module
from services.daily_digest_service import DailyDigestService


def _session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(digest_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(feed_module, "SessionLocal", TestingSession)
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


def test_digest_includes_waiting_follow_up_due_tasks(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Follow up with missionary",
                status="WAITING",
                priority="NORMAL",
                waiting_reason="MISSIONARY",
                waiting_follow_up_date=today,
            )
        )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)

    assert any(
        item["type"] == "waiting_follow_up"
        and item["title"] == "Follow up with missionary"
        for item in digest["items"]
    )
    assert digest["summary"]["due_today"] >= 1
    assert digest["summary"]["tasks"] >= 1
    assert "Follow up with missionary" in digest["text"]


def test_digest_includes_waiting_tasks_without_follow_up(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Waiting task needs follow-up date",
                status="WAITING",
                priority="IMPORTANT",
                waiting_reason="OTHER",
            )
        )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)

    assert any(
        item["type"] == "waiting_no_follow_up"
        and item["title"] == "Waiting task needs follow-up date"
        for item in digest["items"]
    )
    assert digest["summary"]["due_today"] >= 1
    assert digest["summary"]["tasks"] >= 1
    assert "Waiting task needs follow-up date" in digest["text"]


def test_digest_includes_ready_tasks_without_due_date(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Review ready Interpol packet",
                status="READY",
                priority="IMPORTANT",
            )
        )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)

    assert any(
        item["type"] == "ready_task"
        and item["title"] == "Review ready Interpol packet"
        for item in digest["items"]
    )
    assert digest["summary"]["due_today"] >= 1
    assert digest["summary"]["tasks"] >= 1
    assert "Review ready Interpol packet" in digest["text"]


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


def test_digest_has_summary_and_grouped_who_needs_what(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        missionary = _missionary(session, "Elder Smith")
        session.add(
            SecretaryTask(
                title="Critical Prorroga follow-up needed",
                status="OPEN",
                priority="CRITICAL",
                due_date=today,
                missionary_id=missionary.id,
                automation_key="prorroga:1:30:2026-07-18",
                automation_source="process_automation",
            )
        )
        session.add(
            SecretaryTask(
                title="Update Travel Connect/GVM with Carne",
                status="OPEN",
                priority="IMPORTANT",
                due_date=today - timedelta(days=1),
                missionary_id=missionary.id,
                automation_key="gvm:carne:1",
                automation_source="process_automation",
            )
        )
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)

    assert digest["summary"]["critical"] == 1
    assert digest["summary"]["overdue"] == 1
    assert digest["summary"]["due_today"] == 1
    assert digest["summary"]["tasks"] == 2
    assert digest["summary"]["total"] == 6
    groups = {
        group["key"]: group
        for group in digest["detail_groups"]
    }
    assert {"gvm", "prorroga"}.issubset(set(groups))
    assert groups["gvm"]["items"][0]["who"] == "Elder Smith"
    assert "Who needs what" in digest["text"]
    assert "Elder Smith: Update Travel Connect/GVM with Carne" in digest["text"]


def test_digest_uses_missionary_name_for_document_expiration(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        _missionary(
            session,
            "Sister Rivera",
        ).residency_expiration = today - timedelta(days=1)
        session.commit()
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)
    groups = {
        group["key"]: group
        for group in digest["detail_groups"]
    }

    assert groups["document"]["items"][0]["who"] == "Sister Rivera"
    assert "Sister Rivera: Residency Expiration needs attention" in digest["text"]
    assert "Missionary #" not in digest["text"]


def test_digest_includes_task_identity_and_grouped_missionary_count(monkeypatch):
    today = date(2026, 6, 18)
    session = _session(monkeypatch)
    try:
        first = _missionary(session, "Elder One")
        second = _missionary(session, "Sister Two")
        group = MissionaryGroup(
            name="Temporary - Critical Prorroga follow-up needed",
            group_type="TEMPORARY_AUTOMATION",
            automation_key="prorroga:group:30:2026-06-18",
        )
        session.add(group)
        session.flush()
        task = SecretaryTask(
            title="Critical Prorroga follow-up needed",
            status="OPEN",
            priority="CRITICAL",
            due_date=today,
            group_id=group.id,
            group_scope_label="Temporary - Critical Prorroga follow-up needed",
            automation_key="prorroga:group:30:2026-06-18",
            automation_source="process_automation",
        )
        session.add(task)
        session.flush()
        session.add_all([
            SecretaryTaskMissionary(task_id=task.id, missionary_id=first.id),
            SecretaryTaskMissionary(task_id=task.id, missionary_id=second.id),
        ])
        session.commit()
        task_id = task.id
    finally:
        session.close()

    digest = DailyDigestService().build_digest(today=today)

    item = digest["detail_groups"][0]["items"][0]
    assert item["task_id"] == task_id
    assert item["missionary_count"] == 2
    assert item["who"] == "Temporary - Critical Prorroga follow-up needed"


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
