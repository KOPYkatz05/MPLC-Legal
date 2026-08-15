from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QPushButton
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models.appointment import Appointment
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
from services import dashboard_service as dashboard_module
from services import notification_feed_service as feed_module
from services.dashboard_service import DashboardService
from services.notification_feed_service import NotificationFeedService
from ui.pages import dashboard_page
from ui.pages.dashboard_page import DashboardPage
from utils.i18n import get_i18n


@pytest.fixture()
def dashboard_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(dashboard_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(feed_module, "SessionLocal", TestingSession)
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
            nationality="USA",
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

    feed = NotificationFeedService(
        settings_service=SimpleNamespace(
            get_notification_settings=lambda: {
                "include_expiring_documents": True,
                "include_missing_documents": True,
                "include_appointments": True,
                "include_office_tasks": True,
                "dashboard_expiration_days": 60,
                "critical_expiration_days": 7,
            }
        )
    )
    summary = DashboardService(notification_feed_service=feed).get_summary()
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
    task_item = next(item for item in items if item["type"] == "secretary_task")
    assert task_item["task_id"]

    assert summary["urgent_count"] >= 4
    assert summary["appointments_today"] == 1
    assert summary["open_task_count"] == 1
    assert summary["today_appointments"][0]["name"] == "Urgent Person"
    assert summary["today_tasks"][0]["title"] == "Call Migraciones"


def test_dashboard_includes_recommended_automatic_tasks(dashboard_env):
    today = date.today()
    session = dashboard_env()
    try:
        session.add(
            SecretaryTask(
                title="Prorroga submission window is open",
                description="Recommended process work.",
                status="OPEN",
                priority="IMPORTANT",
                work_date=today,
                due_date=today,
                automation_key="prorroga:1:60:2026-09-01",
                automation_source="process_automation",
            )
        )
        session.commit()
    finally:
        session.close()

    recommended = DashboardService().get_summary()["recommended_tasks"]

    assert [task["title"] for task in recommended] == [
        "Prorroga submission window is open"
    ]


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


def test_residency_card_tracks_next_90_days_and_prorroga_progress(
    dashboard_env,
):
    today = date.today()
    session = dashboard_env()
    try:
        due = _missionary(
            session,
            full_name="Due Resident",
            residency_expiration=today + timedelta(days=90),
        )
        _missionary(
            session,
            missionary_code="10002",
            full_name="Later Resident",
            residency_expiration=today + timedelta(days=91),
        )
        for document_type in ("PAGO_PRORROGA", "CARTA_MINJUS"):
            session.add(Document(
                missionary_id=due.id,
                document_type=document_type,
                workflow_stage="PRORROGA",
                file_name=f"{document_type}.pdf",
                file_path=f"{document_type}.pdf",
                status="ACTIVE",
            ))
        session.commit()
    finally:
        session.close()

    items = DashboardService().get_summary()["residency_expirations"]

    assert len(items) == 1
    assert items[0]["name"] == "Due Resident"
    assert items[0]["days_left"] == 90
    assert items[0]["has_pago"] is True
    assert items[0]["papers_started"] is True


def test_residency_card_excludes_missionary_on_release_date(dashboard_env):
    today = date.today()
    session = dashboard_env()
    try:
        _missionary(
            session,
            full_name="Released Resident",
            release_date=today,
            residency_expiration=today + timedelta(days=20),
        )
        session.commit()
    finally:
        session.close()

    items = DashboardService().get_summary()["residency_expirations"]

    assert items == []


def test_cancelaciones_tracks_30_days_before_release_until_both_documents(
    dashboard_env,
):
    today = date.today()
    session = dashboard_env()
    try:
        due = _missionary(
            session,
            full_name="Cancellation Due",
            release_date=today + timedelta(days=30),
        )
        overdue = _missionary(
            session,
            missionary_code="10002",
            full_name="Cancellation Overdue",
            release_date=today - timedelta(days=5),
            dynamics_status="Released",
        )
        complete = _missionary(
            session,
            missionary_code="10003",
            full_name="Cancellation Complete",
            release_date=today - timedelta(days=10),
        )
        _missionary(
            session,
            missionary_code="10004",
            full_name="Cancellation Later",
            release_date=today + timedelta(days=31),
        )
        session.add(Document(
            missionary_id=due.id,
            document_type="PAGO_CANCELACION_DE_RESIDENCIA",
            workflow_stage="CANCELACION",
            file_name="pago.pdf",
            file_path="pago.pdf",
            status="ACTIVE",
        ))
        for document_type in (
            "PAGO_CANCELACION_DE_RESIDENCIA",
            "CONSTANCIA_CANCELACION",
        ):
            session.add(Document(
                missionary_id=complete.id,
                document_type=document_type,
                workflow_stage="CANCELACION",
                file_name=f"{document_type}.pdf",
                file_path=f"{document_type}.pdf",
                status="ACTIVE",
            ))
        session.commit()
    finally:
        session.close()

    items = DashboardService().get_summary()["cancelaciones"]

    assert [item["name"] for item in items] == [
        "Cancellation Overdue",
        "Cancellation Due",
    ]
    assert items[0]["days_left"] == -5
    assert items[0]["has_pago"] is False
    assert items[0]["papers_submitted"] is False
    assert items[1]["has_pago"] is True
    assert items[1]["papers_submitted"] is False


def test_dashboard_does_not_render_todays_priorities(monkeypatch, qapp):
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
                "recommended_tasks": [],
            }

    monkeypatch.setattr(
        dashboard_page,
        "DashboardService",
        FakeDashboardService,
    )
    page = DashboardPage()

    try:
        card = page.findChild(dashboard_page.QFrame, "DashboardPrioritiesCard")
        row = page.findChild(dashboard_page.QFrame, "DashboardPriorityRow")

        assert card is None
        assert row is None
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
                "recommended_tasks": [],
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
        residency_card = page.findChild(
            dashboard_page.QFrame, "DashboardResidencyCard"
        )
        cancelaciones_card = page.findChild(
            dashboard_page.QFrame, "DashboardCancelacionesCard"
        )

        assert residency_card is not None
        assert cancelaciones_card is not None
        assert residency_card.layout().itemAt(
            residency_card.layout().count() - 1
        ).spacerItem() is not None
        assert cancelaciones_card.layout().itemAt(
            cancelaciones_card.layout().count() - 1
        ).spacerItem() is not None
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


def test_dashboard_attention_task_routes_to_alert_workspace(qapp):
    _ = qapp
    page = DashboardPage.__new__(DashboardPage)
    opened = []
    page.main_window = SimpleNamespace(
        open_alert_workspace=lambda task_id, return_key="dashboard":
        opened.append((task_id, return_key))
    )

    DashboardPage._open_attention_item(
        page,
        {
            "type": "secretary_task",
            "task_id": 55,
            "target": "office_work",
        },
    )

    assert opened == [(55, "dashboard")]


def test_dashboard_attention_follow_up_task_routes_to_alert_workspace(qapp):
    _ = qapp
    page = DashboardPage.__new__(DashboardPage)
    opened = []
    page.main_window = SimpleNamespace(
        open_alert_workspace=lambda task_id, return_key="dashboard":
        opened.append((task_id, return_key))
    )

    DashboardPage._open_attention_item(
        page,
        {
            "type": "waiting_no_follow_up",
            "task_id": 56,
            "target": "office_work",
        },
    )

    assert opened == [(56, "dashboard")]


def test_dashboard_attention_action_labels_are_specific():
    i18n = get_i18n()
    original_language = i18n.get_language()

    try:
        i18n.set_language("en")
        assert (
            DashboardPage._attention_action_label(
                {
                    "type": "secretary_task",
                    "task_id": 55,
                    "target": "office_work",
                }
            )
            == "Review Task"
        )
        assert (
            DashboardPage._attention_action_label(
                {
                    "type": "waiting_no_follow_up",
                    "task_id": 56,
                    "target": "office_work",
                }
            )
            == "Review Task"
        )
        assert DashboardPage._attention_type_label(
            "waiting_no_follow_up"
        ) == "Follow-Up"
        assert (
            DashboardPage._attention_action_label(
                {"type": "missing_document", "missionary_id": 42}
            )
            == "Open Missionary"
        )
        assert (
            DashboardPage._attention_action_label({"target": "appointments"})
            == "Open Calendar"
        )

        i18n.set_language("es")
        assert (
            DashboardPage._attention_action_label(
                {
                    "type": "secretary_task",
                    "task_id": 55,
                    "target": "office_work",
                }
            )
            == "Revisar tarea"
        )
        assert (
            DashboardPage._attention_action_label(
                {"type": "missing_document", "missionary_id": 42}
            )
            == "Abrir misionero"
        )
        assert (
            DashboardPage._attention_action_label({"target": "appointments"})
            == "Abrir calendario"
        )
    finally:
        i18n.set_language(original_language)


def test_dashboard_chrome_uses_active_language(monkeypatch, qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    monkeypatch.setattr(
        dashboard_page,
        "DashboardService",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        dashboard_page,
        "DailyDigestService",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(DashboardPage, "load_data", lambda self: None)

    try:
        i18n.set_language("es")
        page = DashboardPage()

        labels = {
            label.text()
            for label in page.findChildren(QLabel)
            if label.text()
        }
        buttons = {
            button.text()
            for button in page.findChildren(QPushButton)
            if button.text()
        }

        assert "Panel de control" in labels
        assert "Cargando el trabajo de hoy..." in labels
        assert not {"Misión", "Proceso", "Enlace"}.intersection(labels)
        assert "Actualizar" in buttons
    finally:
        i18n.set_language(original_language)
        if "page" in locals():
            page.close()


def test_dashboard_summary_helpers_follow_active_language():
    i18n = get_i18n()
    original_language = i18n.get_language()

    try:
        i18n.set_language("es")
        assert DashboardPage._digest_total_text(0) == (
            "No hay acciones que necesiten atención hoy."
        )
        assert DashboardPage._digest_total_text(3) == (
            "3 acciones necesitan atención hoy."
        )
        assert DashboardPage._recommended_summary_text(
            [
                {"days": -1},
                {"days": 0},
                {"days": 8},
            ]
        ) == "1 vencido(s) | 1 vence(n) hoy | 1 próximo(s)"
    finally:
        i18n.set_language(original_language)


def test_dashboard_merges_priorities_without_duplicate_tasks(qapp):
    _ = qapp
    page = DashboardPage.__new__(DashboardPage)
    priorities = DashboardPage._merged_priorities(
        page,
        {
            "attention_items": [
                {
                    "type": "secretary_task",
                    "task_id": 7,
                    "title": "Due task",
                    "severity": "warning",
                    "days": 0,
                }
            ],
            "recommended_tasks": [
                {"id": 7, "title": "Due task", "severity": "warning", "days": 0},
                {"id": 8, "title": "Later task", "severity": "info", "days": 2},
            ],
        },
    )

    assert [item.get("task_id") for item in priorities] == [7, 8]


def test_missing_document_priority_detail_names_the_document():
    text = DashboardPage._priority_detail_text(
        {
            "type": "missing_document",
            "title": "Missing Documents",
            "document_label": "Passport Bio Page",
            "detail": "Test Missionary needs this for INTERPOL.",
        }
    )

    assert text == (
        "Missing Passport Bio Page. "
        "Test Missionary needs this for INTERPOL."
    )


def test_simplified_dashboard_limits_and_expands_priorities(monkeypatch, qapp):
    data = {
        "total": 12,
        "stage_counts": {},
        "urgent_count": 8,
        "appointments_today": 0,
        "open_task_count": 8,
        "today_appointments": [],
        "today_tasks": [],
        "expiring": [],
        "missing_docs": [],
        "attention_items": [
            {
                "type": "secretary_task",
                "task_id": index,
                "title": f"Task {index}",
                "detail": "Needs review",
                "severity": "warning",
                "days": 0,
                "target": "office_work",
            }
            for index in range(8)
        ],
        "recommended_tasks": [],
    }

    monkeypatch.setattr(
        dashboard_page,
        "DashboardService",
        lambda: SimpleNamespace(get_summary=lambda: data),
    )
    monkeypatch.setattr(
        dashboard_page,
        "DailyDigestService",
        lambda: SimpleNamespace(
            build_digest=lambda **_kwargs: {
                "summary": {"total": 0},
                "detail_groups": [],
                "text": "All clear",
            }
        ),
    )
    monkeypatch.setattr(
        dashboard_page,
        "SettingsService",
        lambda: SimpleNamespace(
            get_daily_digest_settings=lambda: {},
            get_language=lambda: "en",
        ),
    )

    page = DashboardPage()
    try:
        assert page.findChild(
            dashboard_page.QFrame, "DashboardPrioritiesCard"
        ) is None
        assert page.findChild(
            dashboard_page.QFrame, "DashboardPriorityRow"
        ) is None
        assert page.findChild(dashboard_page.QFrame, "DashboardResidencyCard") is not None
        assert page.findChild(dashboard_page.QFrame, "DashboardUpcomingCard") is not None
        exceptions_row = next(
            page.content_layout.itemAt(index).widget()
            for index in range(page.content_layout.count())
            if page.content_layout.itemAt(index).widget() is not None
            and page.content_layout.itemAt(index).widget().objectName()
            == "DashboardExceptionsRow"
        )
        assert len(exceptions_row.findChildren(dashboard_page.QFrame, "DashboardExceptionCard")) == 2
        dashboard_buttons = page.findChildren(QPushButton)
        assert dashboard_buttons
        assert all(button.property("dashboardTone") for button in dashboard_buttons)
        assert all(button.height() in {26, 28, 30, 34} for button in dashboard_buttons)
    finally:
        page.close()


def test_dashboard_cache_is_instant_and_force_refresh_runs_in_background(
    monkeypatch,
    qapp,
    qtbot,
):
    calls = []
    data = {
        "total": 1,
        "stage_counts": {},
        "urgent_count": 0,
        "appointments_today": 0,
        "open_task_count": 0,
        "today_appointments": [],
        "today_tasks": [],
        "expiring": [],
        "missing_docs": [],
        "attention_items": [],
        "recommended_tasks": [],
    }

    class FakeDashboardService:
        def get_summary(self):
            calls.append("summary")
            return data

    monkeypatch.setattr(dashboard_page, "DashboardService", FakeDashboardService)
    monkeypatch.setattr(
        dashboard_page,
        "DailyDigestService",
        lambda: SimpleNamespace(
            build_digest=lambda **_kwargs: {
                "summary": {"total": 0},
                "detail_groups": [],
                "text": "All clear",
            }
        ),
    )
    monkeypatch.setattr(
        dashboard_page,
        "SettingsService",
        lambda: SimpleNamespace(
            get_daily_digest_settings=lambda: {},
            get_language=lambda: "en",
        ),
    )

    page = DashboardPage()
    try:
        assert calls == ["summary"]
        assert page.request_refresh(force=False) is False
        assert calls == ["summary"]

        renders = []
        page._render_dashboard = lambda payload: renders.append(payload)
        assert page.request_refresh(force=True) is True
        assert page._refresh_in_flight is True
        qtbot.waitUntil(lambda: not page._refresh_in_flight, timeout=3000)
        assert calls == ["summary", "summary"]
        assert page._last_dashboard_data["total"] == 1
        assert renders == []
    finally:
        page.close()


def test_dashboard_digest_task_routes_to_alert_workspace(qapp):
    _ = qapp
    page = DashboardPage.__new__(DashboardPage)
    opened = []
    page.main_window = SimpleNamespace(
        open_alert_workspace=lambda task_id, return_key="dashboard":
        opened.append((task_id, return_key))
    )

    DashboardPage._open_digest_item(
        page,
        {
            "task_id": 66,
            "action": "Critical Prorroga follow-up needed",
        },
    )

    assert opened == [(66, "dashboard")]


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
