from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.appointment import Appointment
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
from services import notification_feed_service as feed_module
from services.notification_feed_service import NotificationFeedService


class FakeSettings:
    def __init__(self, **overrides):
        self.values = {
            "startup_popup_enabled": True,
            "dashboard_expiration_days": 60,
            "critical_expiration_days": 7,
            "include_overdue_tasks": True,
            "include_due_today_tasks": True,
            "include_appointments": True,
            "include_expiring_documents": True,
            "include_missing_documents": True,
            "include_transfer_reminders": True,
        }
        self.values.update(overrides)

    def get_notification_settings(self):
        return dict(self.values)


def _session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(feed_module, "SessionLocal", TestingSession)
    return TestingSession()


def _missionary(session, name="Test Person"):
    missionary = Missionary(
        missionary_code=name.replace(" ", "-").lower(),
        full_name=name,
        status="ACTIVE",
        current_stage="INTERPOL",
    )
    session.add(missionary)
    session.flush()
    return missionary


def test_feed_includes_appointments_through_current_week(monkeypatch):
    today = date(2026, 6, 22)
    session = _session(monkeypatch)
    try:
        missionary = _missionary(session)
        session.add_all([
            Appointment(
                missionary_id=missionary.id,
                appointment_field="interpol_appointment_date",
                appointment_type="Interpol",
                scheduled_date=today + timedelta(days=6),
                status="SCHEDULED",
            ),
            Appointment(
                missionary_id=missionary.id,
                appointment_field="biometric_appointment_date",
                appointment_type="Biometric",
                scheduled_date=today + timedelta(days=7),
                status="SCHEDULED",
            ),
        ])
        session.commit()
    finally:
        session.close()

    feed = NotificationFeedService(FakeSettings()).build_feed(today=today)
    appointments = [
        item for item in feed if item["type"] == "appointment_due"
    ]

    assert [item["title"] for item in appointments] == [
        "Interpol appointment"
    ]
    assert appointments[0]["severity"] == "info"
    assert appointments[0]["who"] == "Test Person"


def test_feed_includes_missionary_name_for_document_expiration(monkeypatch):
    today = date(2026, 6, 22)
    session = _session(monkeypatch)
    try:
        missionary = _missionary(session, "Sister Rivera")
        missionary.residency_expiration = today - timedelta(days=1)
        session.commit()
    finally:
        session.close()

    feed = NotificationFeedService(FakeSettings()).build_feed(today=today)
    document_item = next(
        item for item in feed
        if item["type"] == "document_expiration"
        and item["field_label"] == "Residency Expiration"
    )

    assert document_item["who"] == "Sister Rivera"
    assert document_item["missionary_name"] == "Sister Rivera"


def test_feed_respects_task_and_appointment_toggles(monkeypatch):
    today = date(2026, 6, 22)
    session = _session(monkeypatch)
    try:
        missionary = _missionary(session)
        session.add(
            Appointment(
                missionary_id=missionary.id,
                appointment_field="interpol_appointment_date",
                appointment_type="Interpol",
                scheduled_date=today,
                status="SCHEDULED",
            )
        )
        session.add(
            SecretaryTask(
                title="Old task",
                status="OPEN",
                priority="IMPORTANT",
                due_date=today - timedelta(days=1),
            )
        )
        session.add(
            SecretaryTask(
                title="Today task",
                status="OPEN",
                priority="NORMAL",
                due_date=today,
            )
        )
        session.commit()
    finally:
        session.close()

    feed = NotificationFeedService(
        FakeSettings(
            include_overdue_tasks=False,
            include_due_today_tasks=False,
            include_appointments=False,
            include_expiring_documents=False,
            include_missing_documents=False,
        )
    ).build_feed(today=today)

    assert not any(
        item["type"] in {"secretary_task", "appointment_due"}
        for item in feed
    )


def test_feed_includes_waiting_follow_up_due_tasks(monkeypatch):
    today = date(2026, 6, 22)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Call missionary about missing document",
                status="WAITING",
                priority="NORMAL",
                waiting_reason="MISSIONARY",
                waiting_follow_up_date=today,
            )
        )
        session.add(
            SecretaryTask(
                title="Later waiting task",
                status="WAITING",
                priority="NORMAL",
                waiting_reason="DOCUMENT",
                waiting_follow_up_date=today + timedelta(days=1),
            )
        )
        session.commit()
    finally:
        session.close()

    feed = NotificationFeedService(FakeSettings()).build_feed(today=today)
    follow_ups = [
        item for item in feed
        if item["type"] == "waiting_follow_up"
    ]

    assert [item["title"] for item in follow_ups] == [
        "Call missionary about missing document"
    ]
    assert follow_ups[0]["target_date"] == today
    assert follow_ups[0]["detail"] == "Normal waiting follow-up due today."


def test_feed_includes_waiting_tasks_without_follow_up(monkeypatch):
    today = date(2026, 6, 22)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Waiting task needs check-in",
                status="WAITING",
                priority="IMPORTANT",
                waiting_reason="OTHER",
            )
        )
        session.add(
            SecretaryTask(
                title="Waiting task already scheduled",
                status="WAITING",
                priority="NORMAL",
                waiting_reason="MISSIONARY",
                waiting_follow_up_date=today + timedelta(days=1),
            )
        )
        session.commit()
    finally:
        session.close()

    feed = NotificationFeedService(FakeSettings()).build_feed(today=today)
    missing_follow_ups = [
        item for item in feed
        if item["type"] == "waiting_no_follow_up"
    ]

    assert [item["title"] for item in missing_follow_ups] == [
        "Waiting task needs check-in"
    ]
    assert missing_follow_ups[0]["target_date"] == today
    assert missing_follow_ups[0]["detail"] == (
        "Important waiting task needs a follow-up date."
    )


def test_due_waiting_task_without_follow_up_is_not_duplicated(monkeypatch):
    today = date(2026, 6, 22)
    session = _session(monkeypatch)
    try:
        task = SecretaryTask(
            title="Waiting task already due",
            status="WAITING",
            priority="IMPORTANT",
            waiting_reason="OTHER",
            due_date=today,
        )
        session.add(task)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    feed = NotificationFeedService(FakeSettings()).build_feed(today=today)
    task_items = [
        item for item in feed
        if item.get("task_id") == task_id
    ]

    assert [item["type"] for item in task_items] == ["secretary_task"]
    assert task_items[0]["detail"] == "Important task due today."


def test_windows_summary_labels_waiting_tasks_without_follow_up():
    summary = NotificationFeedService(FakeSettings()).windows_summary([
        {
            "type": "waiting_no_follow_up",
            "fingerprint": "task:1:WAITING:missing_follow_up:2026-06-22",
        }
    ])

    assert "1 task missing follow-up" in summary["body"]


def test_feed_includes_ready_tasks_without_due_date_once(monkeypatch):
    today = date(2026, 6, 22)
    session = _session(monkeypatch)
    try:
        session.add(
            SecretaryTask(
                title="Review complete packet",
                status="READY",
                priority="IMPORTANT",
            )
        )
        session.add(
            SecretaryTask(
                title="Ready with due date",
                status="READY",
                priority="NORMAL",
                due_date=today,
            )
        )
        session.commit()
    finally:
        session.close()

    feed = NotificationFeedService(FakeSettings()).build_feed(today=today)
    ready_items = [
        item for item in feed
        if item["type"] == "ready_task"
    ]

    assert sorted(item["title"] for item in ready_items) == [
        "Ready with due date",
        "Review complete packet",
    ]
    review_item = next(
        item for item in ready_items
        if item["title"] == "Review complete packet"
    )
    due_item = next(
        item for item in ready_items
        if item["title"] == "Ready with due date"
    )
    assert review_item["target_date"] == today
    assert review_item["detail"] == "Important task ready for review."
    assert len([
        item for item in feed
        if item.get("task_id") == due_item["task_id"]
    ]) == 1
