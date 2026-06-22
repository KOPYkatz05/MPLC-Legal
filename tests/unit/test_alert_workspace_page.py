from types import SimpleNamespace

from ui.pages import alert_workspace_page
from ui.pages.alert_workspace_page import AlertWorkspacePage


class FakeWorkspaceService:
    def __init__(self):
        self.completed = []
        self.calls = 0

    def get_task_workspace(self, task_id):
        self.calls += 1
        return {
            "id": task_id,
            "title": "Critical Prorroga follow-up needed",
            "description": "Review Prorroga records.",
            "status": "OPEN",
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


def test_alert_workspace_renders_task_context(qapp):
    _ = qapp
    page = AlertWorkspacePage(service=FakeWorkspaceService())

    try:
        page.load_task(12)

        assert page.header.title_label.text() == (
            "Critical Prorroga follow-up needed"
        )
        assert page.findChild(alert_workspace_page.QFrame, "AlertMissionaryRow")
    finally:
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
