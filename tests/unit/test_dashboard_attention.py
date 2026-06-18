from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.appointment import Appointment
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
from services import dashboard_service as dashboard_module
from services.dashboard_service import DashboardService
from ui.pages import dashboard_page
from ui.pages.dashboard_page import DashboardPage


@pytest.fixture()
def dashboard_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(dashboard_module, "SessionLocal", TestingSession)
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


def test_dashboard_attention_includes_expiring_missing_tasks_and_appointments(
    dashboard_env,
):
    today = date.today()
    session = dashboard_env()
    try:
        missionary = _missionary(
            session,
            full_name="Urgent Person",
            visa_expiration=today - timedelta(days=2),
        )
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
                title="Call Migraciones",
                status="OPEN",
                priority="IMPORTANT",
                due_date=today,
                missionary_id=missionary.id,
            )
        )
        session.commit()
    finally:
        session.close()

    summary = DashboardService().get_summary()
    items = summary["attention_items"]
    item_types = {item["type"] for item in items}

    assert "document_expiration" in item_types
    assert "missing_document" in item_types
    assert "appointment_due" in item_types
    assert "secretary_task" in item_types
    assert all("title" in item and "detail" in item for item in items)
    appointment_item = next(
        item for item in items if item["type"] == "appointment_due"
    )
    assert appointment_item["appointment_id"]


def test_dashboard_attention_sorts_overdue_before_due_today(dashboard_env):
    today = date.today()
    session = dashboard_env()
    try:
        _missionary(
            session,
            full_name="Overdue Person",
            visa_expiration=today - timedelta(days=1),
        )
        session.add(
            SecretaryTask(
                title="Due today task",
                status="OPEN",
                priority="NORMAL",
                due_date=today,
            )
        )
        session.commit()
    finally:
        session.close()

    items = DashboardService().get_summary()["attention_items"]

    assert items[0]["severity"] == "critical"
    assert items[0]["days"] < 0


def test_dashboard_suppresses_visa_expiration_after_residency(dashboard_env):
    today = date.today()
    session = dashboard_env()
    try:
        _missionary(
            session,
            full_name="Resident Person",
            visa_expiration=today - timedelta(days=4),
            residency_expiration=today + timedelta(days=90),
        )
        session.commit()
    finally:
        session.close()

    summary = DashboardService().get_summary()

    assert not any(
        item["field_label"] == "Visa Expiration"
        for item in summary["expiring"]
    )
    assert not any(
        item["type"] == "document_expiration"
        and "Visa" in item["title"]
        for item in summary["attention_items"]
    )


def test_dashboard_still_tracks_residency_expiration(dashboard_env):
    today = date.today()
    session = dashboard_env()
    try:
        _missionary(
            session,
            full_name="Residency Due Person",
            visa_expiration=today - timedelta(days=4),
            residency_expiration=today - timedelta(days=1),
        )
        session.commit()
    finally:
        session.close()

    summary = DashboardService().get_summary()

    assert any(
        item["field_label"] == "Residency Expiration"
        for item in summary["expiring"]
    )
    assert any(
        item["type"] == "document_expiration"
        and "Residency" in item["title"]
        for item in summary["attention_items"]
    )


def test_dashboard_renders_attention_section(monkeypatch, qapp):
    _ = qapp

    class FakeDashboardService:
        def get_summary(self):
            return {
                "total": 1,
                "stage_counts": {
                    "INTERPOL": 1,
                    "CARNET DE EXTRANJERIA": 0,
                    "PRORROGA": 0,
                    "CANCELACION": 0,
                },
                "expiring": [],
                "missing_docs": [],
                "attention_items": [
                    {
                        "type": "secretary_task",
                        "severity": "warning",
                        "title": "Call Migraciones",
                        "detail": "Important task due today.",
                        "missionary_id": None,
                        "target": "office_work",
                        "days": 0,
                    }
                ],
            }

    monkeypatch.setattr(
        dashboard_page,
        "DashboardService",
        FakeDashboardService,
    )
    page = DashboardPage()

    try:
        card = page.findChild(dashboard_page.QFrame, "NeedsAttentionCard")
        row = page.findChild(dashboard_page.QFrame, "NeedsAttentionRow")

        assert card is not None
        assert row is not None
    finally:
        page.close()


def test_dashboard_renders_daily_digest_section(monkeypatch, qapp):
    _ = qapp

    class FakeDashboardService:
        def get_summary(self):
            return {
                "total": 0,
                "stage_counts": {
                    "INTERPOL": 0,
                    "CARNET DE EXTRANJERIA": 0,
                    "PRORROGA": 0,
                    "CANCELACION": 0,
                },
                "expiring": [],
                "missing_docs": [],
                "attention_items": [],
            }

    class FakeDigestService:
        def build_digest(self, **kwargs):
            return {
                "title": "Today's Digest",
                "text": "Today's Digest\n\nDue today:\n- 1 office task due today",
            }

    class FakeSettingsService:
        def get_daily_digest_settings(self):
            return {
                "include_overdue": True,
                "detail_level": "balanced",
            }

        def get_language(self):
            return "en"

    monkeypatch.setattr(
        dashboard_page,
        "DashboardService",
        FakeDashboardService,
    )
    monkeypatch.setattr(
        dashboard_page,
        "DailyDigestService",
        FakeDigestService,
    )
    monkeypatch.setattr(
        dashboard_page,
        "SettingsService",
        FakeSettingsService,
    )

    page = DashboardPage()

    try:
        card = page.findChild(dashboard_page.QFrame, "DailyDigestCard")
        assert card is not None
    finally:
        page.close()


def test_dashboard_attention_action_routes_to_missionary_detail(qapp):
    _ = qapp
    page = DashboardPage.__new__(DashboardPage)
    opened = []
    page.main_window = SimpleNamespace(
        open_missionary_detail=lambda missionary_id: opened.append(
            missionary_id
        )
    )

    DashboardPage._open_attention_item(
        page,
        {
            "missionary_id": 42,
            "target": "missionary",
        },
    )

    assert opened == [42]


def test_dashboard_attention_complete_appointment_refreshes_pages(monkeypatch, qapp):
    _ = qapp
    completed = []

    class FakeAppointmentService:
        def complete_appointment(self, appointment_id):
            completed.append(appointment_id)

    monkeypatch.setattr(
        dashboard_page,
        "AppointmentService",
        FakeAppointmentService,
    )

    page = DashboardPage.__new__(DashboardPage)
    refreshed = []
    page.load_data = lambda: refreshed.append("dashboard")
    page.main_window = SimpleNamespace(
        calendar_page=SimpleNamespace(
            load_data=lambda: refreshed.append("calendar")
        ),
        office_work_page=SimpleNamespace(
            load_data=lambda: refreshed.append("office_work")
        ),
    )

    DashboardPage._complete_attention_appointment(
        page,
        {"appointment_id": 77},
    )

    assert completed == [77]
    assert refreshed == ["dashboard", "calendar", "office_work"]


def test_dashboard_attention_miss_appointment_confirms_and_refreshes(
    monkeypatch,
    qapp,
):
    _ = qapp
    missed = []

    class FakeAppointmentService:
        def miss_appointment(self, appointment_id):
            missed.append(appointment_id)

    monkeypatch.setattr(
        dashboard_page,
        "AppointmentService",
        FakeAppointmentService,
    )
    monkeypatch.setattr(
        dashboard_page,
        "show_message",
        lambda *args, **kwargs: 16384,
    )

    page = DashboardPage.__new__(DashboardPage)
    refreshed = []
    page.load_data = lambda: refreshed.append("dashboard")
    page.main_window = SimpleNamespace(
        calendar_page=SimpleNamespace(
            load_data=lambda: refreshed.append("calendar")
        ),
        office_work_page=SimpleNamespace(
            load_data=lambda: refreshed.append("office_work")
        ),
    )

    DashboardPage._miss_attention_appointment(
        page,
        {"appointment_id": 88},
    )

    assert missed == [88]
    assert refreshed == ["dashboard", "calendar", "office_work"]
