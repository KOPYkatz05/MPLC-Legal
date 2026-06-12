from types import SimpleNamespace

from ui.dialogs import office_work_dialogs
from ui.dialogs.office_work_dialogs import ProjectDialog, TaskDialog
from ui.main_window import MainWindow
from ui.pages.office_work_page import OfficeWorkPage


class FakeSecretaryWorkService:
    def __init__(self):
        self.completed_tasks = []

    def summary(self):
        return {
            "open": 1,
            "overdue": 1,
            "due_today": 0,
            "waiting": 0,
        }

    def grouped_tasks(self, **filters):
        _ = filters
        return {
            "overdue": [
                {
                    "id": 1,
                    "title": "Call mission office",
                    "description": "",
                    "status": "OPEN",
                    "priority": "IMPORTANT",
                    "due_date": None,
                    "due_group": "overdue",
                    "project_id": None,
                    "project_title": "",
                    "missionary_id": None,
                    "missionary_name": "",
                    "appointment_field": None,
                }
            ],
            "today": [],
            "this_week": [],
            "later": [],
            "no_due_date": [],
        }

    def list_projects(self, **filters):
        _ = filters
        return [
            {
                "id": 7,
                "title": "June arrivals",
                "description": "",
                "status": "ACTIVE",
                "priority": "NORMAL",
                "due_date": None,
                "open_tasks": 1,
                "done_tasks": 1,
                "total_tasks": 2,
                "progress": "1/2 done",
            }
        ]

    def project_options(self):
        return [{"id": 7, "title": "June arrivals"}]

    def missionary_options(self):
        return [{"id": 4, "name": "Test Missionary"}]

    def complete_task(self, task_id):
        self.completed_tasks.append(task_id)


def test_office_work_page_loads_with_mocked_service(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        assert page._selected_tab == "tasks"
        assert page.stack.currentIndex() == page.tasks_index
    finally:
        page.close()


def test_office_work_page_can_filter_to_project(qapp):
    _ = qapp
    page = OfficeWorkPage(service=FakeSecretaryWorkService())

    try:
        page._show_project_tasks(7)

        assert page._project_filter_id == 7
        assert page._selected_tab == "tasks"
    finally:
        page.close()


def test_task_dialog_validates_required_title(monkeypatch, qapp):
    _ = qapp
    messages = []
    monkeypatch.setattr(
        office_work_dialogs,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )
    dialog = TaskDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("")

        assert dialog._validate_title() is False
        assert messages
    finally:
        dialog.close()


def test_project_dialog_validates_required_title(monkeypatch, qapp):
    _ = qapp
    messages = []
    monkeypatch.setattr(
        office_work_dialogs,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )
    dialog = ProjectDialog(FakeSecretaryWorkService())

    try:
        dialog.title_input.setText("")

        assert dialog._validate_title() is False
        assert messages
    finally:
        dialog.close()


def test_main_window_refreshes_office_work_page():
    window = MainWindow.__new__(MainWindow)
    calls = []
    window.dashboard_page = SimpleNamespace(load_data=lambda: None)
    window.missionaries_page = SimpleNamespace(load_data=lambda: None)
    window.office_work_page = SimpleNamespace(load_data=lambda: calls.append("office"))
    window.calendar_page = SimpleNamespace(load_data=lambda: None)
    window.reports_page = SimpleNamespace(load_data=lambda: None)
    window.trash_page = SimpleNamespace(load_data=lambda: None)

    MainWindow._on_nav_changed(window, "office_work", 3)

    assert calls == ["office"]
