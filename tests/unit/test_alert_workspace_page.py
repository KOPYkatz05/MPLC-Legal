from types import SimpleNamespace

from PySide6.QtWidgets import QPushButton

from ui.pages import alert_workspace_page
from ui.pages.alert_workspace_page import AlertWorkspacePage
from utils.i18n import get_i18n


class FakeWorkspaceService:
    def __init__(self):
        self.completed = []
        self.ready = []
        self.reopened = []
        self.calls = 0
        self.status = "OPEN"

    def get_task_workspace(self, task_id):
        self.calls += 1
        return {
            "id": task_id,
            "title": "Critical Prorroga follow-up needed",
            "description": "Review Prorroga records.",
            "status": self.status,
            "priority": "CRITICAL",
            "timing": "19 day(s) overdue",
            "brief_text": "Prorroga follow-up is overdue for 1 missionary record.",
            "why_text": "This alert was created by process automation.",
            "why_points": [
                "19 day(s) overdue",
                "1 linked missionary record",
            ],
            "key_facts": [
                {
                    "label": "Due",
                    "value": "19 day(s) overdue",
                    "color": "#DC2626",
                }
            ],
            "recommended_steps": [
                "Review each affected missionary record.",
                "Mark this alert done when the records are resolved.",
            ],
            "evidence": [
                {
                    "label": "Automation source",
                    "value": "process_automation",
                }
            ],
            "status_history": [
                {
                    "summary": "Waiting -> Ready",
                    "created_at_text": "Jul 01, 2026",
                },
                {
                    "summary": "Created as Waiting",
                    "created_at_text": "Jun 30, 2026",
                },
            ],
            "affected_missionaries": [
                {
                    "id": 4,
                    "name": "Elder One",
                    "current_stage": "PRORROGA",
                    "issue_summary": "Missing Prorroga confirmation",
                    "residency_expiration_text": "Aug 09, 2026",
                    "prorroga_expiration_text": "Not set",
                }
            ],
        }

    def complete_task(self, task_id):
        self.completed.append(task_id)
        self.status = "DONE"

    def mark_task_ready(self, task_id):
        self.ready.append(task_id)
        self.status = "READY"

    def reopen_task(self, task_id):
        self.reopened.append(task_id)
        self.status = "OPEN"


def test_alert_workspace_renders_task_context(qapp):
    _ = qapp
    page = AlertWorkspacePage(service=FakeWorkspaceService())

    try:
        page.load_task(12)

        assert page.header.title_label.text() == (
            "Critical Prorroga follow-up needed"
        )
        texts = {
            label.text()
            for label in page.findChildren(alert_workspace_page.QLabel)
            if label.text()
        }
        assert "Recent status changes" in texts
        assert "Waiting -> Ready" in texts
        assert page.findChild(alert_workspace_page.QFrame, "AlertMissionaryRow")
    finally:
        page.close()


def test_alert_workspace_chrome_uses_active_language(qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    try:
        i18n.set_language("es")
        page = AlertWorkspacePage(service=FakeWorkspaceService())
        page.load_task(12, return_key="office_work")

        texts = {
            label.text()
            for label in page.findChildren(alert_workspace_page.QLabel)
            if label.text()
        }
        buttons = {
            button.text()
            for button in page.findChildren(QPushButton)
            if button.text()
        }

        assert page.back_btn.text() == "Volver"
        assert "Editar tarea" in buttons
        assert "Marcar lista" in buttons
        assert "Marcar hecha" in buttons
        assert "Trabajo de oficina / Espacio de alerta" in texts
        assert "Vista rápida" in texts
        assert "Por qué aparece esta alerta" in texts
        assert "Próximos pasos recomendados" in texts
        assert "Detalles de origen" in texts
        assert "Misioneros afectados (1)" in texts
    finally:
        i18n.set_language(original_language)
        if "page" in locals():
            page.close()


def test_alert_workspace_mark_done_confirms_and_reloads(monkeypatch, qapp):
    _ = qapp
    service = FakeWorkspaceService()
    refreshed = []
    monkeypatch.setattr(
        alert_workspace_page,
        "show_message",
        lambda *args, **kwargs: 16384,
    )
    page = AlertWorkspacePage(
        main_window=SimpleNamespace(
            dashboard_page=SimpleNamespace(load_data=lambda: refreshed.append("dash")),
            office_work_page=SimpleNamespace(load_data=lambda: refreshed.append("office")),
            calendar_page=SimpleNamespace(load_data=lambda: refreshed.append("calendar")),
        ),
        service=service,
    )

    try:
        page.load_task(12)
        page._mark_done()

        assert service.completed == [12]
        assert refreshed == ["dash", "office", "calendar"]
        assert service.calls == 2
    finally:
        page.close()


def test_alert_workspace_mark_done_confirmation_is_translated(monkeypatch, qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    service = FakeWorkspaceService()
    prompts = []

    def fake_show_message(*args, **kwargs):
        prompts.append((args, kwargs))
        return 16384

    monkeypatch.setattr(alert_workspace_page, "show_message", fake_show_message)
    try:
        i18n.set_language("es")
        page = AlertWorkspacePage(service=service)
        page.load_task(12)
        page._mark_done()

        assert prompts
        assert prompts[0][0][1] == "¿Marcar tarea hecha?"
        assert "registros estén resueltos" in prompts[0][0][2]
        assert service.completed == [12]
    finally:
        i18n.set_language(original_language)
        if "page" in locals():
            page.close()


def test_alert_workspace_ready_actions_reload_and_toggle(qapp):
    _ = qapp
    service = FakeWorkspaceService()
    page = AlertWorkspacePage(service=service)

    try:
        page.load_task(12)
        assert page.ready_btn.isHidden() is False
        assert page.needs_work_btn.isHidden() is True

        page._mark_ready()

        assert service.ready == [12]
        assert service.calls == 2
        assert page.ready_btn.isHidden() is True
        assert page.needs_work_btn.isHidden() is False

        page._mark_needs_work()

        assert service.reopened == [12]
        assert service.calls == 3
        assert page.ready_btn.isHidden() is False
        assert page.needs_work_btn.isHidden() is True
    finally:
        page.close()


def test_alert_workspace_edit_task_reloads(monkeypatch, qapp):
    _ = qapp
    service = FakeWorkspaceService()

    class FakeTaskDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return True

    monkeypatch.setattr(alert_workspace_page, "TaskDialog", FakeTaskDialog)
    page = AlertWorkspacePage(service=service)

    try:
        page.load_task(12)
        page._edit_task()

        assert service.calls == 2
    finally:
        page.close()


def test_alert_workspace_back_returns_to_source(qapp):
    _ = qapp
    keys = []
    page = AlertWorkspacePage(
        main_window=SimpleNamespace(set_current_key=lambda key: keys.append(key)),
        service=FakeWorkspaceService(),
    )

    try:
        page.load_task(12, return_key="office_work")
        page._go_back()

        assert keys == ["office_work"]
    finally:
        page.close()
